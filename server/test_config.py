import pytest

from .auth import user_id
from .config import Settings


def configured(host):
    return Settings(auth_mode='databricks-app', databricks_host=host,
                    lakebase_endpoint='projects/atlas/branches/production/endpoints/primary',
                    pg_host='database.example.test', pg_user='app-principal',
                    genie_agent_id='fixture-genie', project_index='catalog.schema.projects',
                    agent_model='fixture-agent', rag_endpoint='fixture-rag')


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
