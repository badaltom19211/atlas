"""Verify scope decisions stop work before agent construction, tools or follow-up extraction."""
import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from . import deep_agent_v1 as workflow
from .agent_runtime import RequestRuntime, bind_runtime, EmptySpan
from .app import create_app
from .config import Settings
from .databricks_errors import NotebookCallError
from .notebook_bridge import NotebookChatAgent, previous_turn
from .test_app import setup, create
from .test_direct_notebook import notebook


@pytest.fixture
def gated(monkeypatch):
    @contextmanager
    def runtime(settings, token, user_id, **kwargs):
        with bind_runtime(RequestRuntime(settings, token, user_id, **{k: v for k, v in kwargs.items() if v is not None})) as scoped:
            yield scoped
    monkeypatch.setattr(workflow, 'open_runtime', runtime)
    def forbidden(*args, **kwargs):
        pytest.fail('A guarded question must not construct an agent or call contract tools')
    for name in ('build_contract_agent', 'query_genie', 'query_rag', 'retrieve', 'embed_query',
                 'extract_followup_metadata', 'extract_query_metadata'):
        monkeypatch.setattr(workflow, name, forbidden)
    return workflow


def run_chat(question, history=None, **kwargs):
    return workflow.contract_assistant(question, token='fixture-token', history=history or [],
        settings=Settings(), user_id='alice', session_id='alice:chat', **kwargs)


def assert_fixed(result, text, intent):
    assert result['answer'] == text
    output = result['custom_outputs']
    assert output['request_intent'] == intent and output['retrieval_skipped'] is True
    assert output['references'] == [] and output['sources'] == []
    assert output['query_metadata'] == {} and output['glossary_terms'] == []
    assert output['citation_status'] == 'not_applicable' and not output['is_follow_up']


@pytest.mark.parametrize('question', ['Hi', 'HELLO!', ' Hey AIA. ', 'Good morning', 'Hello there'])
def test_greetings_need_no_model_or_retrieval(gated, monkeypatch, question):
    def forbidden(*args):
        pytest.fail('Simple greetings must not call any LLM')
    monkeypatch.setattr(gated, '_llm_json', forbidden)
    stages = []
    assert_fixed(run_chat(question, progress=stages.append), gated.GREETING_REPLY, 'greeting')
    assert stages == ['understanding']


@pytest.mark.parametrize('question', ['Who is the president of China?', 'Who is the prime minister of India?'])
@pytest.mark.parametrize('with_history', [False, True])
def test_unrelated_questions_stop_after_one_scope_call(gated, monkeypatch, question, with_history):
    calls, stages = [], []
    def classify(system, user):
        calls.append((system, user))
        # Even inconsistent extra fields must not trigger follow-up extraction/glossary.
        return {'request_intent': 'out_of_scope', 'follow_up': True,
                'standalone_question': 'MSCI fees?', 'glossary_terms': ['fees']}
    monkeypatch.setattr(gated, '_llm_json', classify)
    history = [{'role': 'user', 'content': 'MSCI term?'},
               {'role': 'assistant', 'content': 'Two years.', 'request_intent': 'contract'}] if with_history else []
    assert_fixed(run_chat(question, history, progress=stages.append), gated.OUT_OF_SCOPE_REPLY, 'out_of_scope')
    assert len(calls) == 1 and calls[0][0].startswith(gated.QUERY_UNDERSTANDING_PROMPT)
    assert question in calls[0][1] and stages == ['understanding']


@pytest.mark.parametrize('raw', [{}, None, [], {'request_intent': 'allow'}, {'request_intent': ['contract']}])
def test_missing_or_invalid_scope_never_falls_through(gated, monkeypatch, raw):
    monkeypatch.setattr(gated, '_llm_json', lambda *args: raw)
    assert_fixed(run_chat('What about it?'), gated.UNCLEAR_REPLY, 'unclear')


def test_scope_provider_permission_failure_is_not_a_fixed_refusal(gated, monkeypatch):
    def fail(*args):
        raise NotebookCallError('workflow', 403)
    monkeypatch.setattr(gated, '_llm_json', fail)
    with pytest.raises(NotebookCallError) as caught:
        run_chat('What are the MSCI fees?')
    assert caught.value.status == 403


def test_direct_ask_default_also_gates_scope(gated, monkeypatch):
    monkeypatch.setattr(gated, '_llm_json', lambda *args: {'request_intent': 'out_of_scope'})
    with bind_runtime(RequestRuntime(Settings(), 'token', 'alice')):
        result = gated.ask('What is the weather?', show=False)
    assert result['answer'] == gated.OUT_OF_SCOPE_REPLY and result['references'] == []


@pytest.mark.parametrize('question', ['Hi, what are MSCI contract fees?', 'Who is the president named in this contract?',
                                     'How many contracts expire in 2026?'])
def test_contract_questions_still_reach_real_tool_and_sources(notebook, monkeypatch, question):
    original = notebook._llm_json
    calls = []
    def model(system, user):
        calls.append((system, user))
        return original(system, user)
    monkeypatch.setattr(notebook, '_llm_json', model)
    result = run_chat(question)
    assert any(user.endswith(question) for system, user in calls if system.startswith(notebook.QUERY_UNDERSTANDING_PROMPT))
    assert result['custom_outputs']['request_intent'] == 'contract'
    assert result['custom_outputs']['retrieval_skipped'] is False
    assert {s['kind'] for s in result['custom_outputs']['references']} == {'genie', 'document'}


def test_scope_reply_does_not_replace_last_contract_context(notebook, monkeypatch):
    original = notebook._llm_json
    inputs = []
    def model(system, user):
        if system.startswith(notebook.QUERY_UNDERSTANDING_PROMPT):
            inputs.append(user)
        return original(system, user)
    monkeypatch.setattr(notebook, '_llm_json', model)
    history = [{'role': 'user', 'content': 'MSCI contract term?'},
               {'role': 'assistant', 'content': 'Two years.', 'request_intent': 'contract', 'notebook_query': 'MSCI term?'},
               {'role': 'user', 'content': 'Hi'},
               {'role': 'assistant', 'content': notebook.GREETING_REPLY, 'request_intent': 'greeting'},
               {'role': 'user', 'content': 'Who is the president of China?'},
               {'role': 'assistant', 'content': notebook.OUT_OF_SCOPE_REPLY, 'request_intent': 'out_of_scope'}]
    result = run_chat('And its fees?', history)
    assert result['custom_outputs']['is_follow_up'] is True
    assert inputs[0].startswith('Previous question: MSCI term?\nPrevious answer: Two years.')
    assert 'president' not in inputs[0]
    assert previous_turn(history + [{'role': 'user', 'content': 'And its fees?'}])[1]['query'] == 'MSCI term?'


def test_stream_has_no_search_stages_or_sources_for_unrelated_question(gated, monkeypatch):
    monkeypatch.setattr(gated, '_llm_json', lambda *args: {'request_intent': 'out_of_scope'})
    async def collect():
        agent = NotebookChatAgent(Settings(), token='token', user_id='alice', conversation_id='chat')
        return [item async for item in agent.stream([{'role': 'user', 'content': 'Who is the president of China?'}])]
    events = asyncio.run(collect())
    assert [e['stage'] for e in events if isinstance(e, dict) and e['type'] == 'progress'] == ['queued', 'understanding']
    assert events[-1] == gated.OUT_OF_SCOPE_REPLY


def test_root_trace_records_scope_and_skipped_retrieval(gated, monkeypatch):
    monkeypatch.setattr(gated, '_llm_json', lambda *args: {'request_intent': 'out_of_scope'})
    spans, tags = [], {}
    class Tracing:
        @contextmanager
        def start_span(self, name, **kwargs):
            spans.append(name)
            span = EmptySpan()
            span.trace_id = 'trace-scope'
            yield span
        def update_current_trace(self, **kwargs):
            tags.update(kwargs.get('tags', {}))
    result = run_chat('Who is the president of China?', tracing=Tracing())
    assert result['custom_outputs']['trace_id'] == 'trace-scope'
    assert spans == ['contract_assistant', 'contract_chat', 'query_understanding']
    assert tags['request_intent'] == 'out_of_scope' and tags['retrieval_skipped'] == 'true'


def test_api_persists_and_forwards_scope_metadata_for_owned_history(setup, monkeypatch):
    _, _, factory, _, _ = setup
    seen = []
    async def execute(self, data):
        seen.append(data)
        intent = 'greeting' if data['question'] == 'Hi' else 'contract'
        return 'Fixture answer.', {'references': [], 'sources': [], 'request_intent': intent,
            'retrieval_skipped': intent == 'greeting', 'notebook_query': data['question']}
    monkeypatch.setattr(NotebookChatAgent, '_execute', execute)
    async def identity(request):
        name = request.headers['x-test-user']
        return SimpleNamespace(id=name, name=name, email=name + '@example.test', token='fixture')
    settings = Settings(auth_mode='local', history_backend='sqlite', databricks_host='https://workspace.example.test')
    app = create_app(settings, factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-atlas-request': '1', 'x-test-user': 'alice'}) as client:
        cid = create(client)
        for query in ('MSCI term?', 'Hi', 'And its fees?'):
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': query})
            event = json.loads(response.text.splitlines()[-1])
            assert event['type'] == 'done', response.text
            assert event['assistant']['custom_outputs']['request_intent'] == ('greeting' if query == 'Hi' else 'contract')
        assert seen[-1]['previous']['query'] == 'MSCI term?'
        assert seen[-1]['history'][-1]['request_intent'] == 'greeting'
        assert client.get('/api/bootstrap', headers={'x-test-user': 'bob'}).json()['conversations'] == []
