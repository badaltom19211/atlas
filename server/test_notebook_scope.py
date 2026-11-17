"""Latest notebook routing, with fixture providers and the existing app identity boundary."""
import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from .agent_runtime import RequestRuntime, bind_runtime, EmptySpan
from .app import create_app
from .config import Settings
from .notebook_bridge import NotebookChatAgent
from .test_app import setup, create
from .test_direct_notebook import notebook


def chat(workflow, question, history=None, **kwargs):
    return workflow.contract_assistant(question, token='alice-token', history=history or [], settings=Settings(),
        user_id='alice', session_id='alice:one', **kwargs)


@pytest.fixture
def scoped(notebook, monkeypatch):
    @contextmanager
    def runtime(settings, token, user_id, **kwargs):
        with bind_runtime(RequestRuntime(settings, token, user_id,
                          **{k: v for k, v in kwargs.items() if v is not None})) as scoped_runtime:
            yield scoped_runtime
    monkeypatch.setattr(notebook, 'open_runtime', runtime)
    return notebook


@pytest.mark.parametrize('question,message_type', [('HII', 'greeting'), ('Thanks!', 'thanks'),
    ('Bye', 'goodbye'), ('What can you do?', 'help')])
def test_small_talk_returns_notebook_reply_without_model_agent_or_sources(scoped, monkeypatch, question, message_type):
    def forbidden(*args, **kwargs): pytest.fail('Small talk must not call model or Deep Agent')
    monkeypatch.setattr(scoped, '_llm_json', forbidden)
    monkeypatch.setattr(scoped, 'build_contract_agent', forbidden)
    stages = []
    result = chat(scoped, question, progress=stages.append)
    output = result['custom_outputs']
    assert result['answer'] == scoped.SMALL_TALK_ANSWERS[message_type]
    assert output['message_type'] == message_type and output['in_scope'] is False
    assert output['classification_status'] == 'rule' and output['references'] == []
    assert stages == ['understanding']


def test_off_topic_stops_before_metadata_agent_and_retrieval(scoped, monkeypatch):
    calls = []
    def classify(*args):
        calls.append(args)
        return {'in_scope': False, 'message_type': 'off_topic', 'follow_up': False}
    monkeypatch.setattr(scoped, '_llm_json', classify)
    def forbidden(*args, **kwargs): pytest.fail('Out-of-scope request reached the agent/tools')
    for name in ('build_contract_agent', 'extract_followup_metadata', 'query_genie', 'query_rag'):
        monkeypatch.setattr(scoped, name, forbidden)
    result = chat(scoped, 'Who is the president of China?')
    assert len(calls) == 1 and result['answer'] == scoped.OUT_OF_SCOPE_ANSWER
    assert result['custom_outputs']['classification_status'] == 'ok'
    assert result['custom_outputs']['references'] == []


@pytest.mark.parametrize('question', ['Acme contract fees?', 'Hii, what are Acme contract fees?'])
def test_hii_then_valid_question_calls_existing_tools_with_one_understanding(scoped, monkeypatch, question):
    original, calls = scoped._llm_json, []
    def model(system, user):
        if system.startswith(scoped.QUERY_UNDERSTANDING_PROMPT): calls.append(user)
        return original(system, user)
    monkeypatch.setattr(scoped, '_llm_json', model)
    greeting = chat(scoped, 'HII')
    history = [{'role': 'user', 'content': 'HII'}, {'role': 'assistant', 'content': greeting['answer'],
               'in_scope': False, 'message_type': 'greeting'}]
    result = chat(scoped, question, history)
    assert len(calls) == 1 and calls[0].startswith('Previous turn: none')
    assert result['answer'] == 'There are 12 contracts. Notice is 30 days.'
    assert {r['kind'] for r in result['custom_outputs']['references']} == {'genie', 'document'}
    assert result['custom_outputs']['in_scope'] is True


@pytest.mark.parametrize('mode', ['exception', 'invalid_json'])
def test_notebook_fallback_is_preserved_and_visible(scoped, monkeypatch, mode):
    original, calls = scoped._llm_json, []
    def model(system, user):
        if system.startswith(scoped.QUERY_UNDERSTANDING_PROMPT):
            calls.append(user)
            if mode == 'exception': raise ValueError('private-provider-body-secret')
            return {}
        return original(system, user)
    monkeypatch.setattr(scoped, '_llm_json', model)
    result = chat(scoped, 'Who is the president of China?')
    assert len(calls) == 2 and result['custom_outputs']['classification_status'] == 'fallback'
    assert result['custom_outputs']['in_scope'] is True  # Deliberate uploaded-notebook policy, not the old app gate.
    assert result['custom_outputs']['references']
    assert 'private-provider-body-secret' not in json.dumps(result)


def test_invalid_then_valid_classification_retries_without_calling_agent(scoped, monkeypatch):
    replies = iter([{}, {'in_scope': False, 'message_type': 'off_topic'}])
    monkeypatch.setattr(scoped, '_llm_json', lambda *args: next(replies))
    result = chat(scoped, 'Who is the president of China?')
    assert result['custom_outputs']['classification_status'] == 'ok'
    assert result['answer'] == scoped.OUT_OF_SCOPE_ANSWER


def test_known_uploaded_non_ascii_greeting_rule_is_not_silently_rewritten(scoped):
    # Follow-up item for the notebook developer: preserve this documented limitation for now.
    assert scoped.rule_based_message_type('HII, अनुबंध की समाप्ति कब है?') == 'greeting'
    assert scoped.rule_based_message_type('Hii, what are Acme fees?') is None


def test_last_contract_context_survives_small_talk_and_uses_stored_subject(scoped, monkeypatch):
    original, inputs = scoped._llm_json, []
    def model(system, user):
        if system.startswith(scoped.QUERY_UNDERSTANDING_PROMPT): inputs.append(user)
        return original(system, user)
    monkeypatch.setattr(scoped, '_llm_json', model)
    history = [{'role': 'user', 'content': 'And fees?'}, {'role': 'assistant', 'content': 'USD 100.',
                'notebook_query': 'Acme contract fees?', 'in_scope': True, 'message_type': 'contract'},
               {'role': 'user', 'content': 'Thanks!'}, {'role': 'assistant', 'content': scoped.SMALL_TALK_ANSWERS['thanks'],
                'in_scope': False, 'message_type': 'thanks'}]
    result = chat(scoped, 'And renewal?', history)
    assert inputs[0].startswith('Previous question: Acme contract fees?')
    assert result['custom_outputs']['is_follow_up'] is True and not hasattr(scoped, 'CHAT_SESSIONS')


def test_fixed_reply_uses_one_notebook_trace_without_app_scope(scoped, monkeypatch):
    monkeypatch.setattr(scoped, '_llm_json', lambda *args: {'in_scope': False, 'message_type': 'off_topic'})
    spans, tags = [], {}
    class Tracing:
        @contextmanager
        def start_span(self, name, **kwargs):
            spans.append(name)
            span = EmptySpan(); span.trace_id = 'notebook-trace'
            yield span
        def update_current_trace(self, **kwargs): tags.update(kwargs.get('tags', {}))
    result = chat(scoped, 'Who is the president of China?', tracing=Tracing())
    assert spans == ['contract_assistant', 'query_understanding']
    assert tags['message_type'] == 'off_topic' and result['custom_outputs']['trace_id'] == 'notebook-trace'


def test_fixed_reply_stream_has_no_search_progress(scoped):
    async def collect():
        agent = NotebookChatAgent(Settings(), token='fixture', user_id='alice', conversation_id='one')
        return [item async for item in agent.stream([{'role': 'user', 'content': 'HII'}])]
    items = asyncio.run(collect())
    assert [x['stage'] for x in items if isinstance(x, dict) and x.get('type') == 'progress'] == ['queued', 'understanding']
    assert items[-1] == scoped.SMALL_TALK_ANSWERS['greeting']


def test_api_persists_notebook_routing_and_keeps_owned_contract_context(setup, scoped, monkeypatch):
    _, _, factory, _, _ = setup
    original, inputs = scoped._llm_json, []
    def model(system, user):
        if system.startswith(scoped.QUERY_UNDERSTANDING_PROMPT): inputs.append(user)
        return original(system, user)
    monkeypatch.setattr(scoped, '_llm_json', model)
    async def identity(request):
        name = request.headers['x-test-user']
        return SimpleNamespace(id=name, name=name, email=name+'@example.test', token='fixture')
    app = create_app(Settings(auth_mode='local', history_backend='sqlite', databricks_host='https://workspace.example.test'),
                     factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-atlas-request': '1', 'x-test-user': 'alice'}) as client:
        cid = create(client)
        for query in ('HII', 'Acme fees?', 'Thanks!', 'And renewal?'):
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': query})
            done = json.loads(response.text.splitlines()[-1])
            assert done['type'] == 'done', response.text
            assert done['assistant']['custom_outputs']['in_scope'] is (query not in ('HII', 'Thanks!'))
        assert len(inputs) == 2 and inputs[-1].startswith('Previous question: Acme fees?')
        messages = client.get('/api/bootstrap').json()['conversations'][0]['messages']
        assert len(messages) == 8 and messages[1]['custom_outputs']['classification_status'] == 'rule'
        assert client.get('/api/bootstrap', headers={'x-test-user': 'bob'}).json()['conversations'] == []
