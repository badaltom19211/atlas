import asyncio
import json
import logging

import httpx
import pytest

from .databricks_client import DatabricksHTTP
from .databricks_errors import DatabricksRequestError, public_failure
from .genie import GenieAgent
from .test_app import setup, create
from .test_deep_agent import Fixture, agent
from .test_notebook_agent import configured


@pytest.mark.parametrize('path,payload,label,setting', [
    ('/ai-gateway/mlflow/v1/chat/completions', {}, 'AI Gateway chat model', 'DATABRICKS_AGENT_MODEL'),
    ('/ai-gateway/mlflow/v1/embeddings', {}, 'AI Gateway embedding model', 'DATABRICKS_EMBEDDING_MODEL'),
    ('/api/2.0/vector-search/indexes/private-index/query', {}, 'Vector Search index query', 'DATABRICKS_CONTRACT_INDEX'),
    ('/serving-endpoints/private-model/invocations', {'input': ['private-prompt']}, 'Model Serving embedding', 'DATABRICKS_EMBEDDING_ENDPOINT'),
    ('/serving-endpoints/private-model/invocations', {'messages': []}, 'Model Serving chat', 'DATABRICKS_ANSWER_ENDPOINT'),
])
def test_identifies_api_without_logging_private_content(path, payload, label, setting, caplog):
    caplog.set_level(logging.WARNING)
    def handler(request):
        assert request.headers['authorization'] == 'Bearer private-token'
        return httpx.Response(403, json={'message': 'private-provider-error', 'token': 'private-token'})
    http = DatabricksHTTP(configured(), token='private-token', transport=httpx.MockTransport(handler))
    with pytest.raises(DatabricksRequestError) as failure:
        asyncio.run(http.post(path + '?secret=private-query', payload))
    message = public_failure(failure.value)
    assert label in message and 'HTTP 403' in message
    assert label in caplog.text and setting in caplog.text
    for secret in ['private-token', 'private-provider-error', 'private-query', 'private-index', 'private-model', 'private-prompt']:
        assert secret not in caplog.text + message + str(failure.value)


def test_genie_stream_http_errors_use_same_safe_diagnostics(caplog):
    model = agent(lambda request: httpx.Response(403, text='private-genie-error'))
    with pytest.raises(DatabricksRequestError) as failure:
        asyncio.run(GenieAgent(model.settings, model.http).answer('Private question'))
    assert 'Genie response failed (HTTP 403)' in public_failure(failure.value)
    assert 'scope=genie' in caplog.text and 'private-genie-error' not in caplog.text


@pytest.mark.parametrize('status,expected', [
    (400, 'request configuration'), (401, 'fresh Databricks sign-in'),
    (403, 'scope and consent'), (404, 'DATABRICKS_AGENT_MODEL'),
    (429, 'rate limited'), (503, 'Try again later'),
])
def test_errors_distinguish_access_configuration_and_capacity(status, expected):
    response = httpx.Response(status, request=httpx.Request('POST', 'https://workspace.example.test/ai-gateway/mlflow/v1/chat/completions'))
    assert expected in public_failure(DatabricksRequestError(response))


def test_followup_taskgroup_preserves_safe_failure_without_raw_exception():
    error = DatabricksRequestError(httpx.Response(403, request=httpx.Request('POST', 'https://workspace.example.test/ai-gateway/mlflow/v1/chat/completions')))
    wrapped = ExceptionGroup('private-group-message', [error, RuntimeError('private-exception')])
    assert public_failure(wrapped) == public_failure(error)
    assert 'private-exception' not in public_failure(RuntimeError('private-exception'))


@pytest.mark.parametrize('stage', ['chat', 'both_sources'])
def test_actual_chat_saves_actionable_error_and_releases_lease(setup, monkeypatch, caplog, stage):
    alice, bob, factory, model, _ = setup
    fixture = Fixture()
    def handler(request):
        path = request.url.path
        failed = path.endswith('/chat/completions') if stage == 'chat' else '/genie/' in path or path.endswith('/embeddings')
        return httpx.Response(403, text='private-upstream-error') if failed else fixture(request)
    monkeypatch.setattr(model, 'stream', agent(handler).stream)
    cid = create(alice)
    result = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Contract count?'})
    events = [json.loads(line) for line in result.text.splitlines()]
    assert result.status_code == 200  # Streaming headers precede the eventual model failure.
    assert events[-1]['type'] == 'error'
    failure = events[-1]['message']
    assert 'HTTP 403' in failure and 'ai-gateway' in failure
    if stage == 'chat':
        assert 'AI Gateway chat model' in failure
    else:
        assert 'Genie response' in failure and 'AI Gateway embedding model' in failure
    saved = alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert saved['content'] == failure and saved['status'] == 'error'
    assert bob.get('/api/bootstrap').json()['conversations'] == []
    assert 'private-upstream-error' not in result.text + json.dumps(saved) + caplog.text
    # The failure must not leave this conversation locked.
    monkeypatch.setattr(model, 'stream', agent(Fixture()).stream)
    retry = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Contract count?'})
    assert json.loads(retry.text.splitlines()[-1])['type'] == 'done'
