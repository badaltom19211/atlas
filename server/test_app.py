import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .app import create_app
from .auth import user_id
from .config import Settings
from .database import Base, Conversation, Message


class FixtureAgent:
    contexts = None

    async def stream(self, messages, style):
        self.contexts = messages
        yield {'type': 'tool', 'tool': {'id': 'call', 'name': 'project_rag_tool', 'status': 'completed', 'input': '{}', 'output': '{"ok":true}'}}
        yield 'A supported fixture answer.'


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    async def identity(request):
        subject = request.headers.get('x-test-user')
        if subject not in ('alice', 'bob'):
            raise HTTPException(401, 'Sign in')
        return SimpleNamespace(id=subject, name=subject, email=subject + '@example.test', token='test-' + subject)
    model = FixtureAgent()
    settings = Settings(auth_mode='local', history_backend='sqlite', databricks_host='https://workspace.example.test')
    app = create_app(settings, factory, model, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-test-user': 'alice', 'x-atlas-request': '1'}) as alice, TestClient(app, headers={'x-test-user': 'bob', 'x-atlas-request': '1'}) as bob:
        yield alice, bob, factory, model, app
    engine.dispose()


def create(client):
    result = client.post('/api/conversations', json={'title': 'Integration check'})
    assert result.status_code == 201, result.text
    return result.json()['id']


def test_owner_isolation_history_feedback_notes_and_delete(setup):
    alice, bob, factory, _, app = setup
    cid = create(alice)
    ids = {'user_id': str(uuid4()), 'assistant_id': str(uuid4())}
    response = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Project period?', **ids})
    events = [json.loads(line) for line in response.text.splitlines()]
    result = events[-1]
    assert result['type'] == 'done' and result['assistant']['id'] == ids['assistant_id']
    assert result['user']['id'] == ids['user_id']
    mid = result['assistant']['id']
    assert alice.patch(f'/api/messages/{mid}', json={'feedback': 'up', 'saved': True}).status_code == 200
    note = alice.post(f'/api/messages/{mid}/comments', json={'text': 'Verified against source'}).json()
    loaded = alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert loaded['feedback'] == 'up' and loaded['saved'] and loaded['comments'] == [note]
    assert bob.get('/api/bootstrap').json()['conversations'] == []
    for method, path, body in [
        ('patch', f'/api/messages/{mid}', {'feedback': 'down', 'saved': False}),
        ('post', f'/api/messages/{mid}/comments', {'text': 'No access'}),
        ('post', f'/api/conversations/{cid}/messages', {'content': 'Read secret'}),
        ('patch', f'/api/conversations/{cid}', {'title': 'No access'}),
        ('delete', f'/api/conversations/{cid}', None),
        ('delete', f'/api/comments/{note["id"]}', None),
    ]:
        assert bob.request(method, path, json=body).status_code == 404
    assert alice.delete(f'/api/conversations/{cid}').status_code == 204
    with factory() as db:
        assert db.scalars(select(Message)).all() == []


def test_authentication_csrf_and_logout(setup):
    alice, _, _, _, app = setup
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/bootstrap').status_code == 401
    assert alice.post('/api/conversations', headers={'x-atlas-request': ''}, json={'title': 'No header'}).status_code == 403
    assert alice.post('/api/conversations', headers={'sec-fetch-site': 'cross-site'}, json={'title': 'Cross-site'}).status_code == 403
    assert alice.post('/api/auth/logout').status_code == 204
    assert alice.get('/api/bootstrap').status_code == 401
    assert alice.get('/api/auth/login', follow_redirects=False).status_code == 303
    assert alice.get('/api/bootstrap').status_code == 200


def test_regeneration_context_duplicate_ids_and_failures(setup, monkeypatch):
    alice, _, factory, model, _ = setup
    cid = create(alice)
    body = {'content': 'Original question', 'user_id': 'user-one', 'assistant_id': 'assistant-one'}
    assert alice.post(f'/api/conversations/{cid}/messages', json=body).status_code == 200
    assert alice.post(f'/api/conversations/{cid}/messages', json=body).status_code == 409
    alice.post(f'/api/conversations/{cid}/messages', json={'regenerate': True, 'assistant_id': 'assistant-two'})
    assert model.contexts == [{'role': 'user', 'content': 'Original question'}]
    async def failed(*args):
        yield {'type': 'tool', 'tool': {'id': 'pending', 'name': 'genie_structured_data_tool', 'status': 'running', 'input': '{}', 'output': ''}}
        raise RuntimeError('Sensitive provider detail')
    monkeypatch.setattr(model, 'stream', failed)
    result = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Count?', 'assistant_id': 'failed-answer'})
    assert 'Sensitive provider detail' not in result.text and '"type": "error"' in result.text
    last = alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert last['id'] == 'failed-answer' and last['status'] == 'error' and last['tools'][0]['status'] == 'error'
    with factory() as db:
        assert db.get(Conversation, cid).generation_started is None


def test_production_requires_verified_forwarded_token(setup, monkeypatch):
    _, _, factory, model, _ = setup
    settings = Settings(auth_mode='databricks-app', databricks_host='https://workspace.example.test')
    app = create_app(settings, factory, model, testing=True)
    seen = []
    def workspace(*, config):
        seen.append(config.token)
        return SimpleNamespace(current_user=SimpleNamespace(me=lambda: SimpleNamespace(id=config.token, display_name='Verified', user_name='verified@example.test', active=True)))
    monkeypatch.setattr('server.auth.WorkspaceClient', workspace)
    with TestClient(app) as client:
        assert client.get('/api/bootstrap', headers={'x-forwarded-email': 'owner@example.test'}).status_code == 401
        a = client.get('/api/bootstrap', headers={'x-forwarded-access-token': 'user-a'}).json()
        b = client.get('/api/bootstrap', headers={'x-forwarded-access-token': 'user-b'}).json()
    assert a['user']['id'] != b['user']['id'] and seen == ['user-a', 'user-b']
    assert a['user']['id'] == user_id(settings, 'user-a')
    assert 'user-a' not in json.dumps(a)


def test_local_mode_rejects_remote_connections(setup):
    _, _, _, _, app = setup
    with TestClient(app, base_url='http://untrusted.example', headers={'x-test-user': 'alice'}) as remote:
        assert remote.get('/api/bootstrap').status_code == 403
