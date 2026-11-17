import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from poc.micro_app import web
from server.config import Settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, 'Settings', lambda: Settings(auth_mode='databricks-app', databricks_host='https://workspace.example.test',
        genie_agent_id='a'*32, contract_index='catalog.schema.projects', mlflow_experiment_id='', model_api='gateway'))
    monkeypatch.setattr(web, 'Config', lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(web, 'WorkspaceClient', lambda **kwargs: SimpleNamespace(current_user=SimpleNamespace(
        me=lambda: SimpleNamespace(id='alice', active=True, display_name='Alice', user_name='alice@example.test'))))
    class Agent:
        def __init__(self, *args, **kwargs): pass
        async def answer(self, messages): return 'Answer.', {'references': []}
        async def stream(self, messages):
            yield {'type': 'progress', 'stage': 'searching'}
            yield {'type': 'tool', 'tool': {'status': 'completed', 'output': json.dumps({'custom_outputs': {'references': [{'id': 'G1'}]}})}}
            yield 'Supported answer.'
    monkeypatch.setattr(web, 'KoantekPocAgent', Agent)
    with TestClient(web.build_app(), headers={'x-forwarded-access-token': 'fixture', 'x-atlas-request': '1'}) as client:
        yield client


def test_progress_response_retains_sources_and_json_compatibility(client):
    body = {'question': 'Question?', 'session_id': 'one'}
    response = client.post('/api/chat', json=body, headers={'Accept': 'application/x-ndjson'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0] == {'type': 'progress', 'stage': 'searching'}
    assert events[-1]['type'] == 'done'
    assert events[-1]['custom_outputs']['references'] == [{'id': 'G1'}]
    assert not any(e.get('type') == 'tool' for e in events)
    assert client.post('/api/chat', json=body).json()['answer'] == 'Answer.'


def test_auth_and_request_verification_still_apply_to_stream(client):
    body = {'question': 'Question?', 'session_id': 'one'}
    assert client.post('/api/chat', json=body, headers={'x-forwarded-access-token': ''}).status_code == 401
    assert client.post('/api/chat', json=body, headers={'x-atlas-request': ''}).status_code == 403
