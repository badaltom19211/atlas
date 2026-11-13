"""Exercise the exported notebook functions with fixture providers, never live data."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from .app import create_app
from .config import Settings
from .notebook_bridge import NotebookChatAgent, previous_turn
from .notebook_output import normalize_sources
from .agent_runtime import RequestRuntime, bind_runtime, current_runtime, configure_tracing, DisabledTracing
from .databricks_errors import NotebookCallError
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import threading


def invoke_chat(workflow, payload):
    history = []
    if payload.get('previous'):
        history = [{'role': 'user', 'content': payload['previous']['query']},
                   {'role': 'assistant', 'content': payload['previous']['answer']}]
    return workflow.chat(payload['question'], token=payload.get('token', 'fixture-token'), history=history,
                         settings=Settings(databricks_host='https://workspace.example.test'),
                         user_id=payload.get('user_id', 'alice'), session_id=payload['session_id'])
from .test_app import setup, create


@pytest.fixture
def notebook(monkeypatch):
    from . import deep_agent_v1 as w
    @contextmanager
    def runtime(settings, token, user_id, **kwargs):
        with bind_runtime(RequestRuntime(settings, token, user_id)) as scoped:
            yield scoped
    monkeypatch.setattr(w, 'open_runtime', runtime)
    monkeypatch.setattr(w, '_llm_json', lambda system, query: {'follow_up': True} if system == w.FOLLOW_UP_PROMPT else {'vendor_name': ['Acme'], 'requested_fields': ['fees']})
    monkeypatch.setattr(w, 'query_genie', lambda query: ('12 contracts [G1]', [{'id': 'G1', 'label': 'Count', 'sql': 'SELECT count(*) FROM contracts', 'has_rows': True}]))
    monkeypatch.setattr(w, 'query_rag', lambda query: ('30 days [D1]', [{'id': 'D1', 'label': 'Acme p. 4', 'document': 'Acme.pdf', 'page': 4, 'link': current_runtime().host + '/file.pdf'}]))
    class Agent:
        def invoke(self, data, **kwargs):
            # Use the REAL notebook tool, parallel search, metadata and citation logic.
            w.search_contracts.invoke({'query': data['messages'][0]['content']})
            return {'messages': [SimpleNamespace(content='There are 12 contracts [G1]. Notice is 30 days [D1].')]}
    monkeypatch.setattr(w, '_test_original_builder', w.build_contract_agent, raising=False)
    monkeypatch.setattr(w, 'build_contract_agent', lambda: Agent())
    return w


def payload(**extra):
    return {'question': 'Acme notice and count?', 'session_id': 'alice:chat-1', 'previous': None, **extra}


def test_direct_chat_calls_notebook_tool_and_returns_react_sources(notebook):
    result = invoke_chat(notebook, payload())
    assert result['answer'] == 'There are 12 contracts. Notice is 30 days.'
    refs = result['custom_outputs']['references']
    assert [r['kind'] for r in refs] == ['genie', 'document']
    assert all(r['used_in_answer'] for r in refs)
    assert refs[0]['sql'] == 'SELECT count(*) FROM contracts'
    assert refs[1]['page_start'] == 4 and refs[1]['url'].endswith('/file.pdf')
    assert result['custom_outputs']['workflow'] == 'notebook_chat'
    with pytest.raises(LookupError):
        current_runtime()
    assert not hasattr(notebook, 'CHAT_SESSIONS')


def test_followup_restores_owned_history_and_cleans_memory(notebook):
    result = invoke_chat(notebook, payload(question='And its fees?', previous={'query': 'Acme term?', 'answer': 'Acme term is 2 years.'}))
    assert result['custom_outputs']['is_follow_up'] is True
    assert 'Acme' in result['custom_outputs']['notebook_query']
    with pytest.raises(LookupError):
        current_runtime()
    assert not hasattr(notebook, 'CHAT_SESSIONS')
    fresh = invoke_chat(notebook, payload(session_id='bob:chat-2'))
    assert fresh['custom_outputs']['is_follow_up'] is False


def test_unknown_citations_rejected_and_session_cleaned(notebook, monkeypatch):
    monkeypatch.setattr(notebook, 'build_contract_agent', lambda: SimpleNamespace(invoke=lambda *a, **kw: {'messages': [SimpleNamespace(content='Invented [D99].')]}))
    with pytest.raises(ValueError, match='not retrieved'):
        invoke_chat(notebook, payload())
    with pytest.raises(LookupError):
        current_runtime()
    assert not hasattr(notebook, 'CHAT_SESSIONS')


def test_both_sources_fail_without_fabricated_answer_or_private_error(notebook, monkeypatch):
    def fail(query):
        raise RuntimeError('private-provider-body-secret')
    monkeypatch.setattr(notebook, 'query_genie', lambda q: fail(q))
    monkeypatch.setattr(notebook, 'query_rag', lambda q: fail(q))
    def invoke(data, **kwargs):
        text = notebook.search_contracts.invoke({'query': 'Acme'})
        assert 'private-provider-body-secret' not in text
        return {'messages': [SimpleNamespace(content='Nothing found.')]}
    monkeypatch.setattr(notebook, 'build_contract_agent', lambda: SimpleNamespace(invoke=invoke))
    with pytest.raises(NotebookCallError):
        invoke_chat(notebook, payload())
    with pytest.raises(LookupError):
        current_runtime()
    assert not hasattr(notebook, 'CHAT_SESSIONS')


def test_missing_pages_and_external_links_not_invented():
    refs = normalize_sources([{'id': 'D1', 'label': 'Contract', 'link': 'https://evil.example/file'}], 'https://workspace.example.test')
    assert refs[0]['url'] is None and refs[0]['page_start'] is None


def test_previous_turn_uses_persisted_resolved_subject_and_skips_current_question():
    messages = [{'role': 'user', 'content': 'And fees?'}, {'role': 'assistant', 'content': '10 USD', 'notebook_query': 'And fees? (Acme contract)'}, {'role': 'user', 'content': 'And renewal?'}]
    q, prev = previous_turn(messages)
    assert q == 'And renewal?' and prev['query'] == 'And fees? (Acme contract)'
    assert previous_turn([{'role': 'user', 'content': 'Hi'}]) == ('Hi', None)


def test_cancel_signals_direct_call_and_holds_slot_until_thread_finishes(monkeypatch):
    from . import deep_agent_v1 as w
    started, release = threading.Event(), threading.Event()
    seen = {}
    def chat(question, **kwargs):
        seen.update(kwargs)
        started.set()
        release.wait(5)
        return {'answer': 'done', 'custom_outputs': {}}
    monkeypatch.setattr(w, 'chat', chat)
    async def run():
        slots = asyncio.Semaphore(1)
        agent = NotebookChatAgent(Settings(auth_mode='databricks-app'), token='private-user-token',
                                  user_id='alice', conversation_id='one', slots=slots)
        task = asyncio.create_task(agent.answer([{'role': 'user', 'content': 'Question'}]))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert seen['cancel'].is_set() and slots.locked()
            assert seen['token'] == 'private-user-token' and seen['history'] == []
        finally:
            release.set()
        await asyncio.wait_for(slots.acquire(), 5)
        slots.release()
    asyncio.run(run())


def test_hosted_missing_user_token_does_not_fall_back_to_service_principal():
    agent = NotebookChatAgent(Settings(auth_mode='databricks-app'), token=None, user_id='alice', conversation_id='one')
    with pytest.raises(RuntimeError, match='authentication'):
        asyncio.run(agent.answer([{'role': 'user', 'content': 'Question'}]))


def test_api_selects_direct_bridge_and_roundtrips_notebook_memory(setup, monkeypatch):
    _, _, factory, _, _ = setup
    seen = []
    async def execute(self, data):
        seen.append(data)
        return 'Fixture answer.', {'sources': [], 'references': [], 'workflow': 'notebook_chat', 'notebook_query': 'Acme fees'}
    monkeypatch.setattr(NotebookChatAgent, '_execute', execute)
    async def identity(request):
        name = request.headers['x-test-user']
        return SimpleNamespace(id=name, name=name, email=name+'@example.test', token=name+'-token')
    settings = Settings(auth_mode='local', history_backend='sqlite', databricks_host='https://workspace.example.test')
    app = create_app(settings, factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-atlas-request': '1', 'x-test-user': 'alice'}) as client:
        cid = create(client)
        for query in ['Acme fees?', 'And renewal?']:
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': query})
            done = json.loads(response.text.splitlines()[-1])
            assert done['type'] == 'done', response.text
            assert done['assistant']['custom_outputs']['workflow'] == 'notebook_chat'
        assert seen[0]['token'] == 'alice-token' and seen[0]['previous'] is None
        assert seen[1]['previous']['query'] == 'Acme fees'
        assert seen[0]['session_id'].endswith(':' + cid)
        assert client.get('/api/bootstrap', headers={'x-test-user': 'bob'}).json()['conversations'] == []


def test_direct_configuration_requires_gateway_and_numeric_experiment():
    from .test_config import configured
    settings = replace(configured('https://workspace.example.test'), agent_workflow='notebook')
    with pytest.raises(RuntimeError, match='requires'):
        settings.validate()
    replace(settings, model_api='gateway').validate()
    with pytest.raises(RuntimeError, match='experiment ID'):
        replace(settings, model_api='gateway', mlflow_experiment_id='bad').validate()


def test_notebook_builds_and_invokes_actual_deep_agent_graph(notebook, monkeypatch):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatResult, ChatGeneration
    class FixtureModel(BaseChatModel):
        @property
        def _llm_type(self):
            return 'fixture'
        def bind_tools(self, tools, **kwargs):
            return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(m, ToolMessage) for m in messages):
                message = AIMessage(content='There are 12 contracts [G1]. Notice is 30 days [D1].')
            else:
                message = AIMessage(content='', tool_calls=[{'name': 'search_contracts', 'args': {'query': 'Acme notice?'}, 'id': 'fixture-call', 'type': 'tool_call'}])
            return ChatResult(generations=[ChatGeneration(message=message)])
    monkeypatch.setattr(notebook, 'ChatOpenAI', lambda **kwargs: FixtureModel())
    monkeypatch.setattr(notebook, 'build_contract_agent', notebook._test_original_builder)
    result = invoke_chat(notebook, payload())
    assert result['answer'] == 'There are 12 contracts. Notice is 30 days.'
    assert len(result['custom_outputs']['references']) == 2


def test_tracing_disabled_without_experiment_does_not_create_one(monkeypatch):
    import mlflow
    monkeypatch.delenv('MLFLOW_EXPERIMENT_ID', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('An experiment must not be created implicitly')
    monkeypatch.setattr(mlflow, 'set_experiment', forbidden)
    assert isinstance(configure_tracing(Settings(mlflow_experiment_id='')), DisabledTracing)


def test_tracing_uses_explicit_experiment_and_app_auth(monkeypatch):
    import mlflow
    monkeypatch.setenv('MLFLOW_EXPERIMENT_ID', '12345')
    monkeypatch.setenv('ATLAS_AUTH_MODE', 'databricks-app')
    monkeypatch.setenv('DATABRICKS_CLIENT_ID', 'app-client')
    monkeypatch.setenv('DATABRICKS_CLIENT_SECRET', 'fixture-secret')
    monkeypatch.setenv('DATABRICKS_TOKEN', 'must-not-be-used-for-traces')
    monkeypatch.setenv('DATABRICKS_AUTH_TYPE', 'pat')
    called = []
    monkeypatch.setattr(mlflow, 'set_tracking_uri', lambda uri: called.append(uri))
    monkeypatch.setattr(mlflow, 'set_experiment', lambda **kwargs: called.append(kwargs))
    monkeypatch.setattr(mlflow.tracing, 'enable', lambda: None)
    monkeypatch.setattr(mlflow.openai, 'autolog', lambda **kwargs: None)
    monkeypatch.setattr(mlflow.tracing, 'disable_notebook_display', lambda: None)
    assert configure_tracing(Settings(auth_mode='databricks-app', mlflow_experiment_id='12345')) is mlflow
    import os
    assert os.environ['DATABRICKS_AUTH_TYPE'] == 'oauth-m2m'
    assert 'DATABRICKS_TOKEN' not in os.environ
    assert called == ['databricks', {'experiment_id': '12345'}]


def test_simultaneous_users_do_not_share_identity_or_history(notebook, monkeypatch):
    barrier = threading.Barrier(2)
    seen = []
    def genie(query):
        before = current_runtime().token
        barrier.wait(timeout=10)
        runtime = current_runtime()
        seen.append((runtime.user_id, before, runtime.token, query))
        return '12 contracts [G1]', [{'id': 'G1', 'label': 'Count', 'sql': 'SELECT 12', 'has_rows': True}]
    monkeypatch.setattr(notebook, 'query_genie', genie)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(invoke_chat, notebook, payload(user_id='alice', token='alice-token',
                        question='And fees?', previous={'query': 'Acme term?', 'answer': '2 years'}))
        b = pool.submit(invoke_chat, notebook, payload(user_id='bob', token='bob-token', session_id='bob:other'))
        alice, bob = a.result(), b.result()
    assert alice['custom_outputs']['is_follow_up'] and not bob['custom_outputs']['is_follow_up']
    assert sorted((user, before, after) for user, before, after, query in seen) == [
        ('alice', 'alice-token', 'alice-token'), ('bob', 'bob-token', 'bob-token')]
    assert all(('Conversation context' in query) == (user == 'alice') for user, _, _, query in seen)


def test_partial_source_failure_remains_visible(notebook, monkeypatch):
    monkeypatch.setattr(notebook, 'query_genie', lambda q: (_ for _ in ()).throw(RuntimeError('private')))
    def invoke(*args, **kwargs):
        notebook.search_contracts.invoke({'query': 'Acme'})
        return {'messages': [SimpleNamespace(content='Notice is 30 days [D1].')]}
    monkeypatch.setattr(notebook, 'build_contract_agent', lambda: SimpleNamespace(invoke=invoke))
    result = invoke_chat(notebook, payload())
    assert 'Structured contract lookup is unavailable' in result['answer']
    assert 'private' not in result['answer']
    assert [r['id'] for r in result['custom_outputs']['references']] == ['D1']


def test_exported_genie_parses_sql_with_request_identity(monkeypatch):
    from . import deep_agent_v1 as w
    settings = Settings(databricks_host='https://workspace.example.test', genie_agent_id='target-genie')
    event = {'type': 'response.completed', 'response': {'conversation_id': 'chat123', 'output': [
        {'type': 'function_call', 'call_id': 'sql1', 'arguments': json.dumps({'sql': 'SELECT count(*) FROM cat.sch.contracts', 'title': 'Count'})},
        {'type': 'function_call_output', 'call_id': 'sql1', 'output': '|count|\n|---|\n|7|'},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': '7 contracts'}]},
    ]}}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self, **kwargs): yield 'data: ' + json.dumps(event)
    def post(url, **kwargs):
        assert url == settings.databricks_host + '/api/2.0/genie/agents/target-genie/responses'
        assert kwargs['headers']['Authorization'] == 'Bearer user-token'
        assert kwargs['json']['input'][0]['content'][0]['text'] == 'Count?'
        return Response()
    monkeypatch.setattr(w.requests, 'post', post)
    with bind_runtime(RequestRuntime(settings, 'user-token', 'alice')):
        text, refs = w.query_genie('Count?')
    assert '7 contracts' in text
    assert refs[0]['sql'] == 'SELECT count(*) FROM cat.sch.contracts'
    assert refs[0]['tables'] == ['cat.sch.contracts'] and refs[0]['has_rows']
    assert '/target-genie/chats/chat123?' in refs[0]['link']


def test_runtime_uses_user_credentials_and_closes_clients(monkeypatch):
    import openai
    from databricks.vector_search.client import VectorSearchClient
    from .agent_runtime import open_runtime
    seen = []
    def openai_client(**kwargs):
        seen.append(('model', kwargs['api_key']))
        return SimpleNamespace()
    def search_client(self, **kwargs):
        seen.append(('search', kwargs['personal_access_token']))
    monkeypatch.setattr(openai, 'OpenAI', openai_client)
    monkeypatch.setattr(VectorSearchClient, '__init__', search_client)
    monkeypatch.setattr(VectorSearchClient, 'get_index', lambda self, **kwargs: SimpleNamespace(similarity_search=lambda **kw: {'rows': []}))
    with open_runtime(Settings(databricks_host='https://workspace.example.test'), 'alice-token', 'alice') as runtime:
        http = runtime.http
        runtime.vs_index.similarity_search(columns=['text'])
        assert current_runtime() is runtime
    assert seen == [('model', 'alice-token'), ('search', 'alice-token')]
    assert http.is_closed and runtime.token == '' and runtime.oai is None
    with pytest.raises(LookupError): current_runtime()
