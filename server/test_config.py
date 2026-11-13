import pytest
from dataclasses import replace

from .auth import user_id
from .config import Settings


def configured(host):
    return Settings(agent_workflow='adapted', auth_mode='databricks-app', databricks_host=host,
                    model_api='serving', genie_agent_id='a' * 32,
                    lakebase_endpoint='projects/atlas/branches/production/endpoints/primary',
                    pg_host='database.example.test', pg_user='app-principal',
                    contract_index='catalog.schema.contracts',
                    embedding_endpoint='fixture-embedding', answer_endpoint='fixture-answer')


def test_databricks_app_hostname_preserves_local_history_identity():
    hosted = configured('workspace.cloud.databricks.com')
    local = configured('https://workspace.cloud.databricks.com')
    hosted.validate()
    assert hosted.databricks_host == local.databricks_host
    assert user_id(hosted, '123') == user_id(local, '123')


@pytest.mark.parametrize('host', [
    'http://workspace.example.test',
    'https://user:secret@workspace.example.test',
    'https://workspace.example.test/path',
    'https://workspace.example.test?token=value',
    '',
])
def test_invalid_workspace_origins_remain_rejected(host):
    with pytest.raises(RuntimeError, match='HTTPS workspace origin'):
        configured(host).validate()


@pytest.mark.parametrize('field,value', [
    ('contract_index', ''), ('embedding_endpoint', ''), ('answer_endpoint', ''),
    ('contract_index', 'REPLACE_WITH_TARGET_CATALOG_SCHEMA_INDEX'),
    ('contract_index', 'not-qualified'), ('rag_top_k', 0), ('rag_top_k', 21),
    ('rag_history_messages', -1), ('rag_history_messages', 21),
])
def test_invalid_contract_configuration_is_rejected(field, value):
    with pytest.raises(RuntimeError):
        replace(configured('https://workspace.example.test'), **{field: value}).validate()


def test_old_genie_settings_do_not_configure_contract_workflow(monkeypatch):
    monkeypatch.setenv('DATABRICKS_GENIE_AGENT_ID', 'old-genie')
    monkeypatch.setenv('DATABRICKS_PROJECT_INDEX', 'old.schema.index')
    settings = replace(configured('https://workspace.example.test'), contract_index='')
    with pytest.raises(RuntimeError, match='DATABRICKS_CONTRACT_INDEX'):
        settings.validate()


@pytest.mark.parametrize('agent_id', ['not-an-id', 'abc', 'REPLACE_WITH_TARGET_GENIE_AGENT_ID', 'a' * 33])
def test_invalid_genie_configuration_is_rejected(agent_id):
    with pytest.raises(RuntimeError):
        replace(configured('https://workspace.example.test'), genie_agent_id=agent_id).validate()


def test_new_workflow_requires_genie_and_accepts_notebook_gateway_models():
    settings = configured('https://workspace.example.test')
    with pytest.raises(RuntimeError, match='GENIE_AGENT_ID'):
        replace(settings, genie_agent_id='').validate()
    replace(settings, model_api='gateway', embedding_endpoint='', answer_endpoint='', rag_top_k=20).validate()


@pytest.mark.parametrize('changes', [
    {'model_api': 'invalid'}, {'model_api': 'gateway', 'agent_model': ''},
    {'model_api': 'gateway', 'embedding_model': 'REPLACE_WITH_MODEL'},
])
def test_invalid_model_transport_is_rejected(changes):
    with pytest.raises(RuntimeError):
        replace(configured('https://workspace.example.test'), **changes).validate()
