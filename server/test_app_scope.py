"""App-only gating: no notebook edits, no sticky greeting state, no fabricated sources."""
import asyncio
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from . import app_scope as scope
from . import deep_agent_v1 as notebook_module
from .agent_runtime import EmptySpan
from .app import create_app
from .config import Settings
from .databricks_errors import DatabricksRequestError, NotebookCallError
from .notebook_bridge import NotebookChatAgent
from .test_app import setup, create
from .test_direct_notebook import notebook, allow_contract_scope


def run(question, history=None, **kwargs):
    return scope.call_contract_assistant(question, token='private-user-token', history=history or [],
        settings=Settings(databricks_host='https://workspace.example.test'),
        user_id='alice', session_id='alice:chat', **kwargs)


def exchange(question, result):
    return [{'role': 'user', 'content': question},
            {'role': 'assistant', 'content': result['answer'],
             'app_scope_intent': result['custom_outputs']['app_scope_intent']}]


@pytest.mark.parametrize('question', ['Hi', 'HII', 'hiiii!', 'HELLO!', ' Hey AIA. ', 'Good morning', 'Hello there'])
def test_greeting_never_calls_model_or_notebook(monkeypatch, question):
    def forbidden(*args, **kwargs):
        pytest.fail('Greeting must not call a model or the notebook')
    monkeypatch.setattr(scope, '_classify_with_model', forbidden)
    monkeypatch.setattr(notebook_module, 'contract_assistant', forbidden)
    result = run(question)
    assert result['answer'] == scope.GREETING_REPLY
    assert result['custom_outputs']['references'] == [] and result['custom_outputs']['sources'] == []
    assert result['custom_outputs']['notebook_called'] is False


@pytest.mark.parametrize('question', ['What are MSCI contract fees?', 'Hii, what are MSCI contract fees?'])
def test_valid_question_after_hii_calls_unchanged_notebook_once(monkeypatch, question):
    decisions, calls = [], []
    def classify(question, previous, settings, token, cancel):
        decisions.append((question, previous, token))
        return 'contract'
    monkeypatch.setattr(scope, '_classify_with_model', classify)
    source = {'id': 'D1', 'kind': 'document', 'used_in_answer': True}
    original = {'answer': 'Original notebook answer.', 'custom_outputs': {'sources': [], 'references': [source], 'trace_id': 'notebook-trace'}}
    def invoke(query, **kwargs):
        calls.append((query, kwargs))
        return original
    monkeypatch.setattr(notebook_module, 'contract_assistant', invoke)
    greeting = run('HII')
    result = run(question, exchange('HII', greeting))
    assert decisions == [(question, None, 'private-user-token')]
    assert len(calls) == 1 and calls[0][0] == question
    assert calls[0][1]['history'] == [] and calls[0][1]['token'] == 'private-user-token'
    assert calls[0][1]['session_id'] == 'alice:chat' and calls[0][1]['user_id'] == 'alice'
    assert result['answer'] == original['answer'] and result['custom_outputs']['references'] == [source]
    assert result['custom_outputs']['trace_id'] == 'notebook-trace' and result['custom_outputs']['notebook_called']
    assert 'app_scope_intent' not in original['custom_outputs']  # Do not mutate notebook output.


def test_hii_then_contract_reaches_real_notebook_tools(notebook, allow_contract_scope):
    history = exchange('HII', run('HII'))
    result = run('Acme notice and count?', history)
    assert result['custom_outputs']['notebook_called'] is True
    assert {r['kind'] for r in result['custom_outputs']['references']} == {'genie', 'document'}
    assert result['answer'] == 'There are 12 contracts. Notice is 30 days.'


def test_unrelated_then_contract_is_not_sticky(monkeypatch):
    decisions, calls = [], []
    def classify(question, *args):
        decisions.append(question)
        return 'out_of_scope' if 'China' in question else 'contract'
    monkeypatch.setattr(scope, '_classify_with_model', classify)
    monkeypatch.setattr(notebook_module, 'contract_assistant', lambda question, **kwargs:
        calls.append(question) or {'answer': 'Contract answer', 'custom_outputs': {}})
    question = 'Who is the president of China?'
    result = run(question)
    assert result['answer'] == scope.OUT_OF_SCOPE_REPLY and calls == []
    assert result['custom_outputs']['references'] == []
    second = run('MSCI contract fees?', exchange(question, result))
    assert second['custom_outputs']['notebook_called'] and calls == ['MSCI contract fees?']
    assert decisions == [question, 'MSCI contract fees?']


def test_contract_context_survives_greeting_without_rewriting_question(monkeypatch):
    prior = [{'role': 'user', 'content': 'MSCI term?'}, {'role': 'assistant', 'content': 'Two years.',
             'notebook_query': 'MSCI contract term?', 'app_scope_intent': 'contract'}]
    seen = []
    monkeypatch.setattr(scope, '_classify_with_model', lambda q, p, *args: seen.append(p) or 'contract')
    def invoke(question, **kwargs):
        assert question == 'And its fees?' and kwargs['history'] == prior
        return {'answer': 'Fees', 'custom_outputs': {}}
    monkeypatch.setattr(notebook_module, 'contract_assistant', invoke)
    run('And its fees?', prior + exchange('HII', run('HII')))
    assert seen == [{'question': 'MSCI contract term?', 'answer': 'Two years.'}]


def mock_gateway(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(scope.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))


def test_classifier_uses_explicit_user_and_configured_model(monkeypatch):
    received = []
    def handler(request):
        received.append((request, json.loads(request.content)))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"intent":"contract"}'}}]})
    mock_gateway(monkeypatch, handler)
    settings = Settings(databricks_host='https://workspace.example.test', agent_model='system.ai.gpt-oss-120b')
    for user in ('alice', 'bob'):
        assert scope._classify_with_model('MSCI fees?', None, settings, user + '-token', None) == 'contract'
    assert [req.headers['authorization'] for req, _ in received] == ['Bearer alice-token', 'Bearer bob-token']
    assert all(req.url.path == '/ai-gateway/mlflow/v1/chat/completions' for req, _ in received)
    assert all(body['model'] == settings.agent_model and body['reasoning_effort'] == 'medium' for _, body in received)
    assert all(json.loads(body['messages'][1]['content'])['new_message'] == 'MSCI fees?' for _, body in received)


@pytest.mark.parametrize('content', ['{}', 'not json', '{"intent":"allow"}', '{"intent":["contract"]}'])
def test_malformed_classification_errors_without_notebook(monkeypatch, content):
    def forbidden(*args, **kwargs): pytest.fail('Invalid classification must not invoke notebook')
    monkeypatch.setattr(notebook_module, 'contract_assistant', forbidden)
    mock_gateway(monkeypatch, lambda request: httpx.Response(200, json={'choices': [{'message': {'content': content}}]}))
    with pytest.raises(NotebookCallError) as error:
        run('MSCI fees?')
    assert error.value.stage == 'scope'


def test_scope_403_is_not_disguised_as_unrelated(monkeypatch):
    mock_gateway(monkeypatch, lambda request: httpx.Response(403, json={'private': 'do not expose'}))
    with pytest.raises(DatabricksRequestError) as error:
        run('MSCI fees?')
    assert error.value.status == 403 and 'do not expose' not in error.value.public_message()


def test_classifier_cancellation_never_reaches_notebook(monkeypatch):
    cancel = threading.Event()
    def classify(*args):
        cancel.set()
        return 'contract'
    monkeypatch.setattr(scope, '_classify_with_model', classify)
    def forbidden(*args, **kwargs): pytest.fail('Cancelled request must not start notebook')
    monkeypatch.setattr(notebook_module, 'contract_assistant', forbidden)
    with pytest.raises(asyncio.CancelledError): run('MSCI fees?', cancel=cancel)


def test_unrelated_stream_only_reports_understanding(monkeypatch):
    monkeypatch.setattr(scope, '_classify_with_model', lambda *args: 'out_of_scope')
    async def collect():
        agent = NotebookChatAgent(Settings(), token='fixture', user_id='alice', conversation_id='one')
        return [item async for item in agent.stream([{'role': 'user', 'content': 'Who is the president of China?'}])]
    items = asyncio.run(collect())
    assert [x['stage'] for x in items if isinstance(x, dict) and x.get('type') == 'progress'] == ['queued', 'understanding']
    assert items[-1] == scope.OUT_OF_SCOPE_REPLY


def test_fixed_reply_trace_is_app_scope_without_notebook_spans(monkeypatch):
    monkeypatch.setattr(scope, '_classify_with_model', lambda *args: 'out_of_scope')
    spans, tags = [], {}
    class Tracing:
        @contextmanager
        def start_span(self, name, **kwargs):
            spans.append(name)
            span = EmptySpan(); span.trace_id = 'scope-trace'
            yield span
        def update_current_trace(self, **kwargs): tags.update(kwargs['tags'])
    result = run('Who is the president of China?', tracing=Tracing())
    assert spans == ['app_scope'] and tags['route'] == 'fixed_reply'
    assert result['custom_outputs']['trace_id'] == 'scope-trace'


def test_api_hii_persists_but_is_excluded_from_next_contract_context(setup, monkeypatch, allow_contract_scope):
    _, _, factory, _, _ = setup
    seen = []
    def invoke(question, **kwargs):
        seen.append((question, kwargs['history']))
        return {'answer': 'Notebook answer', 'custom_outputs': {'sources': [], 'references': [], 'notebook_query': question}}
    monkeypatch.setattr(notebook_module, 'contract_assistant', invoke)
    async def identity(request):
        user = request.headers['x-test-user']
        return SimpleNamespace(id=user, name=user, email=user + '@example.test', token='fixture')
    app = create_app(Settings(auth_mode='local', history_backend='sqlite', databricks_host='https://workspace.example.test'),
                     factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-atlas-request': '1', 'x-test-user': 'alice'}) as client:
        cid = create(client)
        for query in ('HII', 'MSCI contract term?', 'HII', 'And its fees?'):
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': query})
            done = json.loads(response.text.splitlines()[-1])
            assert done['type'] == 'done', response.text
            assert done['assistant']['custom_outputs']['notebook_called'] is (query != 'HII')
        assert seen[0] == ('MSCI contract term?', [])
        assert [m['content'] for m in seen[1][1]] == ['MSCI contract term?', 'Notebook answer']
        messages = client.get('/api/bootstrap').json()['conversations'][0]['messages']
        assert len(messages) == 8  # Greetings remain visible in history.
        assert messages[1]['custom_outputs']['app_scope_intent'] == 'greeting'
        assert client.get('/api/bootstrap', headers={'x-test-user': 'bob'}).json()['conversations'] == []
