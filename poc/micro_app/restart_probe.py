"""Offline cold-restart probe; synthetic users/providers and disposable SQLite only.

Run from the repository root: python poc/micro_app/restart_probe.py
This verifies existing API durability across two Python processes, NOT deployment
to Databricks Micro Apps, real OAuth, Lakebase networking, or model correctness.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def phase(action, directory):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from server.app import create_app
    from server.config import Settings
    from server.database import Base
    from server.notebook_bridge import previous_turn

    path = Path(directory)
    engine = create_engine('sqlite:///' + (path / 'history.db').as_posix(),
                           connect_args={'check_same_thread': False})

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    if action == 'create':
        Base.metadata.create_all(engine)

    async def identity(request):
        subject = request.headers.get('x-poc-user')
        if subject not in ('alice', 'bob'):
            raise HTTPException(401, 'Synthetic test identity required')
        return SimpleNamespace(id=subject, name=subject, email=subject + '@example.test', token='fixture-only')

    class FixtureAgent:
        context = None

        async def stream(self, messages, style):
            self.context = messages
            metadata = {'sources': [], 'workflow': 'notebook_chat', 'source_display': 'grouped',
                        'notebook_query': 'What is the notice period for SAMPLE-001?',
                        'references': [{'id': 'D1', 'kind': 'document', 'label': 'Sample.pdf',
                                        'document': 'Sample.pdf', 'page_start': 2, 'page_end': 2,
                                        'url': None, 'used_in_answer': True}]}
            yield {'type': 'tool', 'tool': {'id': 'fixture-evidence', 'name': 'deep_contract_agent',
                   'status': 'completed', 'input': '{}', 'output': json.dumps({'custom_outputs': metadata})}}
            yield 'Synthetic test answer: 30 days.'

    model = FixtureAgent()
    settings = Settings(auth_mode='local', history_backend='sqlite', agent_workflow='notebook',
                        databricks_host='https://workspace.example.test', mlflow_experiment_id='',
                        glossary_dir='', glossary_workspace_dir='')
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(settings, factory, model, testing=True, identity_resolver=identity)
    headers = {'x-poc-user': 'alice', 'x-atlas-request': '1'}

    def successful(response, expected=200):
        assert response.status_code == expected, f'Unexpected HTTP {response.status_code}: {response.text}'
        return response.json()

    with TestClient(app, headers=headers) as client:
        if action == 'create':
            cid = successful(client.post('/api/conversations', json={'title': 'Micro App restart POC'}), 201)['id']
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': 'SAMPLE-001 notice period?'})
            assert response.status_code == 200
            result = json.loads(response.text.splitlines()[-1])
            assert result['type'] == 'done'
            mid = result['assistant']['id']
            successful(client.patch(f'/api/messages/{mid}', json={'feedback': 'up', 'saved': True}))
            note = successful(client.post(f'/api/messages/{mid}/comments', json={'text': 'Synthetic private note'}), 201)
            (path / 'ids.json').write_text(json.dumps({'cid': cid, 'mid': mid, 'note': note['id'], 'pid': os.getpid()}))
            checks = ['conversation_created', 'answer_evidence_vote_bookmark_note_persisted']
        else:
            ids = json.loads((path / 'ids.json').read_text())
            assert ids['pid'] != os.getpid(), 'The restart must use a different process.'
            conversations = successful(client.get('/api/bootstrap'))['conversations']
            assert len(conversations) == 1 and conversations[0]['id'] == ids['cid']
            messages = conversations[0]['messages']
            assert len(messages) == 2 and messages[-1]['id'] == ids['mid']
            answer = messages[-1]
            assert answer['feedback'] == 'up' and answer['saved'] is True
            assert answer['comments'][0]['id'] == ids['note']
            assert answer['custom_outputs']['references'][0]['page_start'] == 2
            checks = ['new_process_restored_history', 'restored_sources_feedback_bookmark_and_note']
            bob = {'x-poc-user': 'bob'}
            assert successful(client.get('/api/bootstrap', headers=bob))['conversations'] == []
            for method, route, body in [
                ('patch', f"/api/conversations/{ids['cid']}", {'title': 'Unauthorized'}),
                ('delete', f"/api/conversations/{ids['cid']}", None),
                ('post', f"/api/conversations/{ids['cid']}/messages", {'content': 'Unauthorized'}),
                ('patch', f"/api/messages/{ids['mid']}", {'feedback': 'down', 'saved': False}),
                ('post', f"/api/messages/{ids['mid']}/comments", {'text': 'Unauthorized'}),
                ('delete', f"/api/comments/{ids['note']}", None),
            ]:
                assert client.request(method, route, json=body, headers=bob).status_code == 404
            checks.append('second_user_cannot_list_or_modify_first_users_history')
            response = client.post(f"/api/conversations/{ids['cid']}/messages", json={'content': 'And renewal?'})
            assert json.loads(response.text.splitlines()[-1])['type'] == 'done'
            question, previous = previous_turn(model.context)
            assert question == 'And renewal?'
            assert previous['query'] == 'What is the notice period for SAMPLE-001?'
            assert previous['answer'] == 'Synthetic test answer: 30 days.'
            checks.append('followup_receives_persisted_resolved_subject_after_restart')
            cid = successful(client.post('/api/conversations', json={'title': 'Fresh conversation'}), 201)['id']
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': 'New topic'})
            assert json.loads(response.text.splitlines()[-1])['type'] == 'done'
            assert previous_turn(model.context) == ('New topic', None)
            checks.append('new_conversation_has_no_previous_context')
    engine.dispose()
    return checks


if __name__ == '__main__':
    if len(sys.argv) == 3:
        print(json.dumps(phase(sys.argv[1], sys.argv[2])))
    else:
        checks = []
        with tempfile.TemporaryDirectory(prefix='aia-micro-poc-') as directory:
            for action in ('create', 'verify'):
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), action, directory],
                                     cwd=ROOT, capture_output=True, text=True, timeout=60)
                if run.returncode:
                    raise RuntimeError(f'{action} phase failed:\n{run.stderr}\n{run.stdout}')
                checks.extend(json.loads(run.stdout.strip().splitlines()[-1]))
        print(json.dumps({'status': 'passed', 'scope': 'offline two-process API restart; SQLite and fixture providers',
                          'checks': checks, 'not_tested': ['Micro App deployment', 'Databricks SSO', 'Lakebase connectivity',
                                                        'Genie or Vector Search', 'MLflow ingestion', 'platform cold-start latency']}, indent=2))
