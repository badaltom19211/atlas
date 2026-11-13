import io
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.workspace import ExportFormat, ObjectInfo, ObjectType
from fastapi.testclient import TestClient

from . import glossary_assets
from .app import create_app
from .config import Settings
from .databricks_client import DatabricksHTTP, app_workspace_client
from .deep_agent import DeepContractAgent
from .glossary_assets import load_glossary_runtime, workspace_folder
from .test_app import setup, create
from .test_config import configured
from .test_deep_agent import Fixture, agent, ask

ROOT = '/Users/team/business_glossary'
ASSETS = {
    'business_glossary.json': b'[{"business_term":"enterprise license","consolidated_definition":"GLOSSARY_FIXTURE"}]',
    'glossary_loader.py': b'import json\ndef load_glossary(path):\n    with open(path) as f: return json.load(f)\n',
    'enrichment.py': (b'def enrich_question(query, glossary):\n'
                      b'    return {"has_matches":True,"primary_matches":glossary,"glossary_context":{"primary":glossary,"related":[]}}\n'),
}


class WorkspaceFixture:
    def __init__(self, assets=None):
        self.workspace = self
        self.assets = dict(ASSETS if assets is None else assets)
        self.downloads, self.lists = [], []

    def list(self, parent, *, recursive):
        assert recursive is False
        self.lists.append(parent)
        entries = {}
        for name in self.assets:
            path = ROOT + '/' + name
            if not path.startswith(parent + '/'):
                continue
            child = path[len(parent) + 1:].split('/')[0]
            entries[parent + '/' + child] = ObjectType.DIRECTORY if '/' in path[len(parent) + 1:] else ObjectType.FILE
        return [ObjectInfo(path=path, object_type=kind) for path, kind in entries.items()]

    def download(self, path, *, format):
        assert format == ExportFormat.AUTO
        self.downloads.append(path)
        return io.BytesIO(self.assets[path[len(ROOT) + 1:]])


def settings(**values):
    return Settings(auth_mode='databricks-app', databricks_host='https://workspace.example.test',
                    glossary_workspace_dir='/Workspace' + ROOT, **values)


def test_workspace_glossary_calls_real_functions_and_is_used_by_both_sources(caplog):
    caplog.set_level(logging.INFO, logger='uvicorn.error.glossary')
    workspace = WorkspaceFixture()
    runtime = load_glossary_runtime(settings(), workspace)
    folder = Path(runtime.cache.name)
    try:
        fixture = Fixture()
        model = agent(fixture)
        model.glossary = runtime.enricher
        _, output = ask(model)
        assert output['glossary_status'] == 'completed'
        assert output['glossary_terms'] == ['enterprise license']
        for path, body, token in fixture.calls:
            assert token == 'Bearer user-token'
            if '/genie/' in path:
                assert 'GLOSSARY_FIXTURE' in body['input'][0]['content'][0]['text']
            if path.endswith('/query'):
                assert 'GLOSSARY_FIXTURE' in body['query_text']
        assert len(workspace.downloads) == 3 and len(runtime.revision) == 16
        assert 'Workspace glossary ready' in caplog.text and 'GLOSSARY_FIXTURE' not in caplog.text
        assert folder.is_dir()
    finally:
        runtime.close()
    assert not folder.exists()


def test_new_startup_fetches_changed_files_but_running_instance_keeps_its_version():
    workspace = WorkspaceFixture()
    old = load_glossary_runtime(settings(), workspace)
    workspace.assets['business_glossary.json'] = b'[{"business_term":"updated term"}]'
    new = load_glossary_runtime(settings(), workspace)
    try:
        assert old.enricher.question('question')[1]['terms'] == ['enterprise license']
        assert new.enricher.question('question')[1]['terms'] == ['updated term']
        assert new.revision != old.revision
    finally:
        old.close()
        new.close()


def test_workspace_download_includes_python_packages_and_json_but_not_other_files():
    workspace = WorkspaceFixture({**ASSETS,
        'glossary_helpers/__init__.py': b'from .definitions import DATA\n',
        'glossary_helpers/definitions.py': b'DATA = [{"business_term":"helper term"}]\n',
        'glossary_helpers/extra.json': b'{}',
        '.env': b'PRIVATE_VALUE',
        'enrichment.py': b'from glossary_helpers import DATA\ndef enrich_question(q, g):\n    return {"has_matches":True,"primary_matches":DATA,"glossary_context":{"primary":DATA}}\n',
    })
    runtime = load_glossary_runtime(settings(), workspace)
    try:
        assert runtime.enricher.question('question')[1]['terms'] == ['helper term']
        assert len(workspace.downloads) == 6
        assert not (Path(runtime.cache.name) / '.env').exists()
    finally:
        runtime.close()


@pytest.mark.parametrize('path', ['../team', 'https://workspace/folder', '/Users/a/../other',
                                  '/Users//team', '/Workspace', '/', '/Users/a\\b'])
def test_workspace_path_rejects_relative_urls_and_traversal(path):
    with pytest.raises(ValueError):
        workspace_folder(path)


def test_workspace_and_api_paths_are_equivalent_and_two_sources_are_rejected():
    assert workspace_folder('/Workspace' + ROOT + '/') == workspace_folder(ROOT) == ROOT
    with pytest.raises(RuntimeError, match='only one'):
        replace(configured('https://workspace.example.test'), glossary_dir='local', glossary_workspace_dir=ROOT).validate()


@pytest.mark.parametrize('fault', ['missing', 'denied', 'oversize', 'total', 'traversal', 'objects', 'import'])
def test_unavailable_assets_never_execute_partial_code_or_expose_provider_messages(fault, tmp_path, monkeypatch, caplog):
    workspace = WorkspaceFixture()
    # Track exactly the temporary directories owned by this loader.
    from tempfile import TemporaryDirectory
    folders = []
    def temporary(**kwargs):
        cache = TemporaryDirectory(dir=tmp_path, **kwargs)
        folders.append(Path(cache.name))
        return cache
    monkeypatch.setattr(glossary_assets, 'TemporaryDirectory', temporary)
    marker = tmp_path / 'imported.txt'
    workspace.assets['enrichment.py'] = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("executed")\n').encode()
    if fault == 'missing':
        del workspace.assets['glossary_loader.py']
    elif fault == 'denied':
        def denied(*args, **kwargs):
            raise PermissionDenied('SECRET_PROVIDER_DETAIL')
        workspace.download = denied
    elif fault == 'oversize':
        monkeypatch.setattr(glossary_assets, 'MAX_FILE_BYTES', 10)
    elif fault == 'total':
        monkeypatch.setattr(glossary_assets, 'MAX_TOTAL_BYTES', 10)
    elif fault == 'traversal':
        workspace.assets['../outside.py'] = b'raise RuntimeError("never run")'
    elif fault == 'objects':
        monkeypatch.setattr(glossary_assets, 'MAX_OBJECTS', 2)
    else:
        workspace.assets['enrichment.py'] = b'raise ImportError("SECRET_PROVIDER_DETAIL")'
    runtime = load_glossary_runtime(settings(), workspace)
    assert runtime.enricher.question('Original') == ('Original', {'status': 'unavailable', 'terms': []})
    assert not marker.exists() and all(not folder.exists() for folder in folders)
    assert 'SECRET_PROVIDER_DETAIL' not in caplog.text
    assert 'unavailable' in caplog.text


def test_hosted_workspace_assets_force_app_oauth_not_user_credentials(monkeypatch):
    monkeypatch.setattr('databricks.sdk.core.Config', lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr('databricks.sdk.WorkspaceClient', lambda **kwargs: SimpleNamespace(**kwargs))
    config = app_workspace_client(settings()).config
    assert config.auth_type == 'oauth-m2m' and config.host == 'https://workspace.example.test'
    assert not hasattr(config, 'token') and not hasattr(config, 'profile')


def test_startup_loads_once_and_chats_keep_separate_user_tokens(setup, monkeypatch):
    _, _, factory, _, _ = setup
    workspace, fixture = WorkspaceFixture(), Fixture()
    calls = []
    def shared_client(config):
        calls.append(config)
        return workspace
    monkeypatch.setattr(glossary_assets, 'app_workspace_client', shared_client)
    def request_agent(config, http, glossary):
        return DeepContractAgent(config, DatabricksHTTP(config, token=http.token, transport=httpx.MockTransport(fixture)), glossary)
    monkeypatch.setattr('server.app.DeepContractAgent', request_agent)
    async def identity(request):
        name = request.headers['x-test-user']
        return SimpleNamespace(id=name, name=name, email=name + '@example.test', token='token-' + name)
    config = replace(agent(Fixture()).settings, glossary_workspace_dir='/Workspace' + ROOT)
    app = create_app(replace(config, agent_workflow='adapted'), factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-atlas-request': '1', 'x-test-user': 'alice'}) as client:
        assert len(calls) == 1 and len(workspace.downloads) == 3
        for name in ('alice', 'bob'):
            client.headers['x-test-user'] = name
            fixture.calls.clear()
            cid = create(client)
            response = client.post(f'/api/conversations/{cid}/messages', json={'content': 'Enterprise license notice?'})
            done = json.loads(response.text.splitlines()[-1])
            assert done['type'] == 'done', response.text
            assert all(token == 'Bearer token-' + name for _, _, token in fixture.calls)
            assert len(client.get('/api/bootstrap').json()['conversations']) == 1
        assert len(calls) == 1 and len(workspace.downloads) == 3
