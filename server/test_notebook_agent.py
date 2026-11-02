import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from .config import Settings
from .databricks_client import DatabricksHTTP
from .notebook_agent import GENIE, RAG, NotebookAgent, project_records
from .database import ToolRun
from .test_app import setup, create  # Shared authenticated API fixture.
from sqlalchemy import select


def configured():
    return Settings(databricks_host="https://workspace.example.test", genie_agent_id="test-genie", project_index="catalog.schema.projects",
                    rag_endpoint="test-rag", agent_model="test-agent-model")


def agent_with(handler, factory=None):
    workspace = SimpleNamespace(config=SimpleNamespace(authenticate=lambda: {"Authorization": "Bearer test-only"}))
    settings = configured()
    http = DatabricksHTTP(settings, workspace=workspace, transport=httpx.MockTransport(handler))
    return NotebookAgent(settings, http=http, graph_factory=factory)


def completed(text):
    return {"type": "response.completed", "response": {"status": "completed", "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]}}


def stream_response(*events):
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                          text=": heartbeat\n\n" + "".join("data: " + json.dumps(event) + "\n\n" for event in events))


def test_genie_calls_real_contract_and_ignores_tool_internal_text():
    def handler(request):
        assert request.url.path == "/api/2.0/genie/agents/test-genie/responses"
        assert request.headers["authorization"] == "Bearer test-only"
        assert json.loads(request.content)["input"][0]["content"] == [{"type": "input_text", "text": "Count categories"}]
        return stream_response({"type": "response.output_item.done", "item": {"type": "function_call_output", "output": "Internal SQL"}}, completed("7 distinct categories"))
    result = asyncio.run(agent_with(handler).genie("Count categories"))
    assert result == {"source": "Genie", "ok": True, "answer": "7 distinct categories"}


@pytest.mark.parametrize("failure", ["http", "failed", "truncated", "empty", "invalid_json"])
def test_genie_failure_never_falls_back_to_sample_categories(failure):
    def handler(request):
        if failure == "http":
            return httpx.Response(403, json={"secret": "provider-detail"})
        if failure == "failed":
            return stream_response({"type": "response.failed", "error": {"message": "provider-detail"}})
        if failure == "empty":
            return stream_response(completed(""))
        if failure == "invalid_json":
            return httpx.Response(200, text="data: invalid\n\n")
        return stream_response({"type": "response.created"})
    result = asyncio.run(agent_with(handler).invoke_tool(GENIE, "List categories"))
    assert result["ok"] is False
    assert "7" not in result["answer"] and "provider-detail" not in str(result)


def records():
    return {"manifest": {"columns": [{"name": "pk"}, {"name": "score"}, {"name": "full_text"}]},
            "result": {"data_array": [["Edward Jones||MLOps", .95, "# Project\nMLOps\n# Time Period\nNovember 2025 to February 2026"]]}}


def test_project_results_use_manifest_and_keep_source_dates():
    assert project_records(records())[0]["id"] == "Edward Jones||MLOps"
    assert "November 2025" in project_records(records())[0]["text"]
    with pytest.raises(ValueError):
        project_records({"result": {"data_array": [["unexpected"]]}})


def test_rag_calls_index_and_summarizes_only_returned_records():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("/query"):
            assert body["query_type"] == "HYBRID" and body["num_results"] == 5
            return httpx.Response(200, json=records())
        assert request.url.path == "/serving-endpoints/test-rag/invocations"
        assert "not an exhaustive inventory" in body["messages"][0]["content"]
        context = json.loads(body["messages"][1]["content"])
        assert context["documents"][0]["id"] == "Edward Jones||MLOps"
        return httpx.Response(200, json={"choices": [{"message": {"content": "November 2025 to February 2026 [Edward Jones||MLOps]"}}]})
    result = asyncio.run(agent_with(handler).project_rag("Edward Jones period?"))
    assert result["ok"] and not result["exhaustive"]
    assert len(paths) == 2 and len(result["records"]) == 1


def test_empty_retrieval_never_calls_summary_model():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"result": {"data_array": []}})
    result = asyncio.run(agent_with(handler).project_rag("Unknown project?"))
    assert not result["ok"] and len(calls) == 1


def test_cancelled_tool_is_not_converted_to_failure_answer():
    agent = agent_with(lambda _: httpx.Response(500))
    async def cancelled(query):
        raise asyncio.CancelledError()
    agent.genie = cancelled
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.invoke_tool(GENIE, "Query"))


def test_partial_failure_uses_successful_receipts_not_invented_final_answer():
    from langchain_core.messages import AIMessage, ToolMessage
    class Graph:
        async def astream(self, *args, **kwargs):
            yield {"model": {"messages": [AIMessage(content="", tool_calls=[
                {"name": GENIE, "args": {"query":"Count"}, "id":"genie"},
                {"name": RAG, "args": {"question":"Projects"}, "id":"rag"}])]}}
            yield {"tools": {"messages": [
                ToolMessage(tool_call_id="genie", content=json.dumps({"ok":False, "answer":"Unavailable"})),
                ToolMessage(tool_call_id="rag", content=json.dumps({"ok":True, "answer":"Retrieved projects: Fixture Project, dates not specified.", "records":[{"text":"x" * 65000}]}))]}}
            yield {"model": {"messages": [AIMessage(content="Invented count: 999.")]}}
    agent = agent_with(lambda _: httpx.Response(500), lambda _: Graph())
    async def run():
        return [event async for event in agent.stream([{"role":"user", "content":"Both sources"}], "balanced")]
    events = asyncio.run(run())
    assert "999" not in events[-1]
    assert "Genie is unavailable" in events[-1] and "Fixture Project" in events[-1]
    assert {e["tool"]["status"] for e in events if isinstance(e, dict)} == {"running", "error", "completed"}


def test_answer_without_data_tool_is_rejected():
    from langchain_core.messages import AIMessage
    class Graph:
        async def astream(self, *args, **kwargs):
            yield {"model": {"messages": [AIMessage(content="Invented dataset answer.")]}}
    agent = agent_with(lambda _: httpx.Response(500), lambda _: Graph())
    async def run():
        return [event async for event in agent.stream([{"role":"user", "content":"Data question"}], "balanced")]
    with pytest.raises(RuntimeError, match="no supporting data"):
        asyncio.run(run())


@pytest.mark.parametrize("case", ["categories", "count", "projects", "period", "combined"])
def test_five_routes_through_graph_api_and_saved_history(setup, monkeypatch, case):
    """Actual Deep Agent graph and API; model decisions and remote data are fixtures."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    import langchain_openai
    CASES = [
        {"question": "What categories of bikes are in the dataset?", "tools": [GENIE]},
        {"question": "How many distinct bike categories are in the bike-store dataset?", "tools": [GENIE]},
        {"question": "What projects are documented in the project index, and what were their time periods?", "tools": [RAG]},
        {"question": "What was the time period for the Edward Jones project?", "tools": [RAG]},
        {"question": "How many bike categories are there, and what projects are documented in the project index?", "tools": [GENIE, RAG]},
    ]

    index = ["categories", "count", "projects", "period", "combined"].index(case)
    names = CASES[index]["tools"]
    class FixtureModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "fixture"
        def bind_tools(self, tools, **kwargs):
            return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if not any(isinstance(m, ToolMessage) for m in messages):
                message = AIMessage(content="", tool_calls=[{"name": name, "args": {"query" if name == GENIE else "question": CASES[index]["question"]}, "id": f"call-{i}"} for i, name in enumerate(names)])
            else:
                message = AIMessage(content="Fixture answer supported by the returned tool results.")
            return ChatResult(generations=[ChatGeneration(message=message)])
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: FixtureModel())
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if "/genie/" in request.url.path:
            return stream_response(completed("There are 7 categories, including Road Bikes."))
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=records())
        return httpx.Response(200, json={"choices": [{"message": {"content": "Edward Jones: November 2025 to February 2026."}}]})
    agent = agent_with(handler)
    alice, bob, factory, model, _ = setup
    monkeypatch.setattr(model, "stream", agent.stream)
    cid = create(alice)
    response = alice.post(f"/api/conversations/{cid}/messages", json={"content": CASES[index]["question"]})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    tools = events[-1]["assistant"]["tools"]
    assert {t["name"] for t in tools} == set(names)
    assert all(t["status"] == "completed" for t in tools)
    assert alice.get("/api/bootstrap").json()["conversations"][0]["messages"][-1]["tools"] == tools
    assert bob.get("/api/bootstrap").json()["conversations"] == []
    assert len(requests) == (3 if case == "combined" else 1 if case in ("categories", "count") else 2)
    assert alice.delete(f"/api/conversations/{cid}").status_code == 204
    with factory() as db:
        assert db.scalars(select(ToolRun)).all() == []
