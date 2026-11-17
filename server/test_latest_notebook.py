"""Regression coverage for the 16 November notebook and streamed UI progress."""
import asyncio
import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from .agent_runtime import RequestRuntime, bind_runtime
from .citations import check_citations, prepare_source_display
from .config import Settings
from .notebook_bridge import NotebookChatAgent
from .test_direct_notebook import notebook, invoke_chat, payload
from .test_app import setup, create


@pytest.mark.parametrize('tags', ['【G1】 and ［D1］', '[G1, D1]', '【G1; D1】'])
def test_unicode_citations_reach_ui_metadata_and_notebook_source_list(notebook, monkeypatch, tags):
    class Agent:
        def invoke(self, data, **kwargs):
            notebook.search_contracts.invoke({'query': data['messages'][0]['content']})
            return {'messages': [SimpleNamespace(content='Contract facts ' + tags + '.')]}
    monkeypatch.setattr(notebook, 'build_contract_agent', lambda: Agent())
    result = invoke_chat(notebook, payload())
    references = result['custom_outputs']['references']
    assert {s['id'] for s in references if s['used_in_answer']} == {'G1', 'D1'}
    assert result['custom_outputs']['citation_status'] == 'reported'
    assert references[0]['sql'].startswith('SELECT')
    assert references[1]['document'] == 'Acme.pdf'
    assert references[1]['page_start'] == 4
    assert result['answer'] == 'Contract facts.'


def test_wide_unknown_ids_still_rejected_and_list_is_not_evidence():
    refs = [{'id': 'D1'}]
    with pytest.raises(ValueError, match='not retrieved'):
        check_citations('Fact 【D99】.', refs)
    assert prepare_source_display('First 【D1】.\n\nSecond ［D1］.', refs) == 'First.\n\nSecond.'
    assert refs[0]['citation_count'] == 2


def test_latest_notebook_reasoning_settings_reach_all_model_calls(monkeypatch):
    from . import deep_agent_v1 as notebook
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    runtime = RequestRuntime(Settings(agent_model='system.ai.gpt-oss-120b', reasoning_effort='medium'), 'fixture', 'alice')
    runtime.oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    monkeypatch.setattr(notebook, 'ChatOpenAI', lambda **kwargs: calls.append(kwargs) or 'llm')
    monkeypatch.setattr(notebook, 'create_deep_agent', lambda **kwargs: 'agent')
    with bind_runtime(runtime):
        notebook._llm_json('system', 'query')
        notebook.generate_answer([])
        notebook.build_contract_agent()
        assert all(c['extra_body'] == {'reasoning_effort': 'medium'} for c in calls)
        runtime.settings = replace(runtime.settings, agent_model='system.ai.meta-llama-3-3-70b-instruct', reasoning_effort='')
        assert notebook.reasoning_options() == {}


def test_progress_is_streamed_before_answer_and_is_not_persisted_as_a_tool(monkeypatch):
    from . import deep_agent_v1 as notebook
    def chat(question, **kwargs):
        kwargs['progress']('understanding')
        kwargs['progress']('searching')
        kwargs['progress']('composing')
        kwargs['progress']('sources')
        return {'answer': 'Answer.', 'custom_outputs': {'sources': [], 'references': []}}
    monkeypatch.setattr(notebook, 'contract_assistant', chat)
    async def run():
        agent = NotebookChatAgent(Settings(), token='fixture', user_id='alice', conversation_id='one')
        items = [item async for item in agent.stream([{'role': 'user', 'content': 'Question'}])]
        stages = [x['stage'] for x in items if isinstance(x, dict) and x.get('type') == 'progress']
        assert stages == ['queued', 'understanding', 'searching', 'composing', 'sources']
        assert items[-1] == 'Answer.'
        assert agent.progress is None
    asyncio.run(run())


def test_stream_cancellation_stops_progress_without_releasing_an_active_worker(monkeypatch):
    from . import deep_agent_v1 as notebook
    started, release = threading.Event(), threading.Event()
    seen = {}
    def chat(question, **kwargs):
        seen.update(kwargs)
        started.set()
        release.wait(5)
        kwargs['progress']('sources')  # A late callback after disconnect must be harmless.
        return {'answer': 'done', 'custom_outputs': {}}
    monkeypatch.setattr(notebook, 'contract_assistant', chat)
    async def run():
        slots = asyncio.Semaphore(1)
        agent = NotebookChatAgent(Settings(), token='fixture', user_id='alice', conversation_id='one', slots=slots)
        async def consume():
            return [x async for x in agent.stream([{'role': 'user', 'content': 'Question'}])]
        task = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert seen['cancel'].is_set() and slots.locked()
            assert agent.progress is None
        finally:
            release.set()
        await asyncio.wait_for(slots.acquire(), 5)
        slots.release()
    asyncio.run(run())


def test_progress_and_sources_survive_http_and_history_reload(setup, monkeypatch):
    client, _, _, model, _ = setup
    metadata = {'sources': [], 'source_display': 'grouped', 'references': [
        {'id': 'D1', 'kind': 'document', 'document': 'Contract.pdf', 'label': 'Contract',
         'used_in_answer': True, 'page_start': 4, 'page_end': 4, 'url': None}]}
    async def stream(messages, style):
        yield {'type': 'progress', 'stage': 'searching'}
        yield {'type': 'progress', 'stage': 'arbitrary private provider text'}
        yield {'type': 'tool', 'tool': {'id': 'call', 'name': 'deep_contract_agent', 'status': 'completed',
               'input': '{}', 'output': json.dumps({'custom_outputs': metadata})}}
        yield 'Supported answer.'
    monkeypatch.setattr(model, 'stream', stream)
    cid = create(client)
    response = client.post(f'/api/conversations/{cid}/messages', json={'content': 'Question'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0] == {'type': 'progress', 'stage': 'searching'}
    assert 'arbitrary private' not in response.text
    assert events[-1]['assistant']['custom_outputs'] == metadata
    restored = client.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert restored['custom_outputs'] == metadata
    assert restored['tools'] == []
