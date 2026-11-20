"""Server-only configuration. No Databricks credential belongs in VITE_* settings."""
import os
import re
import math
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import contract_agent_config as defaults

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


def env(name, default=''):
    return field(default_factory=lambda: os.getenv(name, default))


def boolean_env(name, default=True):
    def read():
        value = os.getenv(name, str(default)).strip().lower()
        if value not in ('true', 'false'):
            raise RuntimeError(f'{name} must be true or false.')
        return value == 'true'
    return field(default_factory=read)


def columns_env(name, default):
    return field(default_factory=lambda: tuple(value.strip() for value in os.getenv(name, default).split(',') if value.strip()))


@dataclass(frozen=True)
class Settings:
    agent_workflow: str = env('ATLAS_AGENT_WORKFLOW', 'notebook')
    mlflow_experiment_id: str = env('MLFLOW_EXPERIMENT_ID')
    auth_mode: str = env('ATLAS_AUTH_MODE', 'databricks-app')
    databricks_host: str = env('DATABRICKS_HOST')
    databricks_profile: str = env('DATABRICKS_CONFIG_PROFILE')
    contract_index: str = env('DATABRICKS_CONTRACT_INDEX', defaults.VS_INDEX)
    embedding_endpoint: str = env('DATABRICKS_EMBEDDING_ENDPOINT')
    answer_endpoint: str = env('DATABRICKS_ANSWER_ENDPOINT')
    model_api: str = env('DATABRICKS_MODEL_API', 'gateway')
    agent_model: str = env('DATABRICKS_AGENT_MODEL', defaults.LLM_MODEL)
    reasoning_effort: str = env('DATABRICKS_REASONING_EFFORT')
    embedding_model: str = env('DATABRICKS_EMBEDDING_MODEL', defaults.EMBEDDING_MODEL)
    genie_agent_id: str = env('DATABRICKS_GENIE_AGENT_ID', defaults.GENIE_SPACE_ID)
    use_genie: bool = boolean_env('ATLAS_USE_GENIE', defaults.USE_GENIE)
    use_rag: bool = boolean_env('ATLAS_USE_RAG', defaults.USE_RAG)
    genie_timeout_seconds: int = field(default_factory=lambda: int(os.getenv('ATLAS_GENIE_TIMEOUT_SECONDS', str(defaults.GENIE_TIMEOUT_S))))
    agent_temperature: float = field(default_factory=lambda: float(os.getenv('ATLAS_AGENT_TEMPERATURE', str(defaults.AGENT_TEMPERATURE))))
    rag_temperature: float = field(default_factory=lambda: float(os.getenv('ATLAS_RAG_TEMPERATURE', str(defaults.RAG_TEMPERATURE))))
    rag_max_tokens: int = field(default_factory=lambda: int(os.getenv('ATLAS_RAG_MAX_TOKENS', str(defaults.RAG_MAX_TOKENS))))
    json_temperature: float = field(default_factory=lambda: float(os.getenv('ATLAS_JSON_TEMPERATURE', str(defaults.JSON_TEMPERATURE))))
    json_max_tokens: int = field(default_factory=lambda: int(os.getenv('ATLAS_JSON_MAX_TOKENS', str(defaults.JSON_MAX_TOKENS))))
    rag_query_type: str = env('ATLAS_RAG_QUERY_TYPE', defaults.RAG_QUERY_TYPE)
    rag_columns: tuple[str, ...] = columns_env('ATLAS_RAG_COLUMNS', ','.join(defaults.RAG_COLUMNS))
    rerank_columns: tuple[str, ...] = columns_env('ATLAS_RERANK_COLUMNS', ','.join(defaults.RERANK_COLUMNS))
    vector_search_endpoint: str = env('DATABRICKS_VECTOR_SEARCH_ENDPOINT', defaults.VS_ENDPOINT)
    agent_app_name: str = env('ATLAS_AGENT_APP_NAME', defaults.APP_NAME)
    agent_app_version: str = env('ATLAS_AGENT_APP_VERSION', defaults.APP_VERSION)
    glossary_dir: str = env('ATLAS_GLOSSARY_DIR')
    glossary_workspace_dir: str = env('ATLAS_GLOSSARY_WORKSPACE_DIR')
    rag_top_k: int = field(default_factory=lambda: int(os.getenv('ATLAS_RAG_TOP_K', str(defaults.RAG_TOP_K))))
    rag_history_messages: int = field(default_factory=lambda: int(os.getenv('ATLAS_RAG_HISTORY_MESSAGES', '6')))
    agent_timeout_seconds: int = field(default_factory=lambda: int(os.getenv('ATLAS_AGENT_TIMEOUT_SECONDS', '360')))
    history_backend: str = env('ATLAS_HISTORY_BACKEND', 'lakebase')
    lakebase_endpoint: str = env('LAKEBASE_ENDPOINT')
    pg_host: str = env('PGHOST')
    pg_database: str = env('PGDATABASE', 'databricks_postgres')
    pg_user: str = env('PGUSER')
    pg_port: int = field(default_factory=lambda: int(os.getenv('PGPORT', '5432')))
    pg_sslmode: str = 'verify-full'
    pg_sslrootcert: str = env('PGSSLROOTCERT', 'certifi')

    def __post_init__(self):
        # Databricks Apps injects a bare workspace hostname in DATABRICKS_HOST.
        # Keep one HTTPS origin for SDK calls, HTTP requests, and user identity keys.
        host = self.databricks_host.strip()
        if re.fullmatch(r'[A-Za-z0-9.-]+', host):
            host = 'https://' + host
        object.__setattr__(self, 'databricks_host', host)

    @property
    def secure_cookies(self):
        return self.auth_mode == 'databricks-app'

    def validate(self):
        if type(self.use_genie) is not bool or type(self.use_rag) is not bool or not (self.use_genie or self.use_rag):
            raise RuntimeError('At least one of ATLAS_USE_GENIE or ATLAS_USE_RAG must be true.')
        if self.agent_workflow == 'adapted' and not (self.use_genie and self.use_rag):
            raise RuntimeError('Source switches require ATLAS_AGENT_WORKFLOW=notebook.')
        for name, value in [('AGENT', self.agent_temperature), ('RAG', self.rag_temperature), ('JSON', self.json_temperature)]:
            if not math.isfinite(value) or not 0 <= value <= 2:
                raise RuntimeError(f'ATLAS_{name}_TEMPERATURE must be between 0 and 2.')
        if not 1 <= self.rag_max_tokens <= 32768 or not 1 <= self.json_max_tokens <= 32768:
            raise RuntimeError('ATLAS_RAG_MAX_TOKENS and ATLAS_JSON_MAX_TOKENS must be 1-32768.')
        if not 1 <= self.genie_timeout_seconds <= 300:
            raise RuntimeError('ATLAS_GENIE_TIMEOUT_SECONDS must be 1-300.')
        if not 1 <= self.agent_timeout_seconds <= 900:
            raise RuntimeError('ATLAS_AGENT_TIMEOUT_SECONDS must be 1-900.')
        if self.rag_query_type not in ('HYBRID', 'ANN'):
            raise RuntimeError('ATLAS_RAG_QUERY_TYPE must be HYBRID or ANN.')
        if not {'chunk_id', 'contextualized_text'}.issubset(self.rag_columns) or not self.rerank_columns or not set(self.rerank_columns).issubset(self.rag_columns):
            raise RuntimeError('RAG columns must include chunk_id, contextualized_text and all rerank columns.')
        if self.reasoning_effort not in ('', 'low', 'medium', 'high'):
            raise RuntimeError('DATABRICKS_REASONING_EFFORT must be low, medium, high or empty.')
        if self.agent_workflow not in ('notebook', 'adapted'):
            raise RuntimeError('ATLAS_AGENT_WORKFLOW must be notebook or adapted.')
        if self.agent_workflow == 'notebook' and self.model_api != 'gateway':
            raise RuntimeError('The direct notebook workflow requires DATABRICKS_MODEL_API=gateway.')
        if self.mlflow_experiment_id and not self.mlflow_experiment_id.isdigit():
            raise RuntimeError('MLFLOW_EXPERIMENT_ID must be an existing numeric experiment ID.')
        if self.glossary_dir and self.glossary_workspace_dir:
            raise RuntimeError('Set only one of ATLAS_GLOSSARY_DIR or ATLAS_GLOSSARY_WORKSPACE_DIR.')
        if self.glossary_workspace_dir:
            from .glossary_assets import workspace_folder
            workspace_folder(self.glossary_workspace_dir)
        models = ((self.agent_model, *([self.embedding_model] if self.use_rag else [])) if self.model_api == 'gateway'
                  else (self.answer_endpoint, *([self.embedding_endpoint] if self.use_rag else [])))
        resources = (*([self.genie_agent_id] if self.use_genie else []), *([self.contract_index] if self.use_rag else []), *models, self.lakebase_endpoint)
        if any('REPLACE_WITH_' in value for value in resources):
            raise RuntimeError('Replace the target-workspace placeholders in app.yaml before deploying.')
        if self.auth_mode not in ('local', 'databricks-app'):
            raise RuntimeError('ATLAS_AUTH_MODE must be local or databricks-app.')
        if self.auth_mode == 'local' and os.getenv('DATABRICKS_APP_NAME'):
            raise RuntimeError('Local authentication cannot run in a Databricks App.')
        url = urlparse(self.databricks_host)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise RuntimeError('DATABRICKS_HOST must be the HTTPS workspace origin.')
        if self.use_rag and not self.contract_index:
            raise RuntimeError('Configure DATABRICKS_CONTRACT_INDEX.')
        if self.model_api not in ('gateway', 'serving') or not all(models):
            raise RuntimeError('Set DATABRICKS_MODEL_API to gateway with AGENT_MODEL/EMBEDDING_MODEL, or serving with ANSWER_ENDPOINT/EMBEDDING_ENDPOINT.')
        if self.use_genie and not re.fullmatch(r'[0-9a-fA-F]{32}', self.genie_agent_id):
            raise RuntimeError('DATABRICKS_GENIE_AGENT_ID must be the 32-character ID from /genie/rooms/<id>.')
        if self.use_rag and not re.fullmatch(r'[^.\s/]+\.[^.\s/]+\.[^.\s/]+', self.contract_index):
            raise RuntimeError('DATABRICKS_CONTRACT_INDEX must be a catalog.schema.index name.')
        if not 1 <= self.rag_top_k <= 20 or not 0 <= self.rag_history_messages <= 20:
            raise RuntimeError('ATLAS_RAG_TOP_K must be 1-20 and ATLAS_RAG_HISTORY_MESSAGES must be 0-20.')
        if self.history_backend == 'lakebase':
            self.validate_database()
        elif self.history_backend != 'sqlite' or self.auth_mode != 'local':
            raise RuntimeError('SQLite is available only in local mode. Use Lakebase for deployment.')

    def validate_database(self):
        if not all((self.lakebase_endpoint, self.pg_host, self.pg_user, self.pg_database)):
            raise RuntimeError('Configure LAKEBASE_ENDPOINT, PGHOST, PGUSER and PGDATABASE.')
        if not re.fullmatch(r'projects/[^/]+/branches/[^/]+/endpoints/[^/]+', self.lakebase_endpoint):
            raise RuntimeError('LAKEBASE_ENDPOINT must be a project/branch/endpoint resource name.')
        if self.pg_sslmode != 'verify-full':
            raise RuntimeError('Lakebase must verify the database TLS certificate and hostname.')
