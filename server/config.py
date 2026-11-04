"""Server-only configuration. No Databricks credential belongs in VITE_* settings."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


def env(name, default=''):
    return field(default_factory=lambda: os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    auth_mode: str = env('ATLAS_AUTH_MODE', 'databricks-app')
    databricks_host: str = env('DATABRICKS_HOST')
    databricks_profile: str = env('DATABRICKS_CONFIG_PROFILE')
    contract_index: str = env('DATABRICKS_CONTRACT_INDEX')
    embedding_endpoint: str = env('DATABRICKS_EMBEDDING_ENDPOINT')
    answer_endpoint: str = env('DATABRICKS_ANSWER_ENDPOINT')
    genie_agent_id: str = env('DATABRICKS_GENIE_AGENT_ID')
    rag_top_k: int = field(default_factory=lambda: int(os.getenv('ATLAS_RAG_TOP_K', '5')))
    rag_history_messages: int = field(default_factory=lambda: int(os.getenv('ATLAS_RAG_HISTORY_MESSAGES', '6')))
    agent_timeout_seconds: int = 150
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
        resources = (self.genie_agent_id, self.contract_index, self.embedding_endpoint,
                     self.answer_endpoint, self.lakebase_endpoint)
        if any('REPLACE_WITH_' in value for value in resources):
            raise RuntimeError('Replace the target-workspace placeholders in app.yaml before deploying.')
        if self.auth_mode not in ('local', 'databricks-app'):
            raise RuntimeError('ATLAS_AUTH_MODE must be local or databricks-app.')
        if self.auth_mode == 'local' and os.getenv('DATABRICKS_APP_NAME'):
            raise RuntimeError('Local authentication cannot run in a Databricks App.')
        url = urlparse(self.databricks_host)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise RuntimeError('DATABRICKS_HOST must be the HTTPS workspace origin.')
        if not all((self.contract_index, self.embedding_endpoint, self.answer_endpoint)):
            raise RuntimeError('Configure DATABRICKS_CONTRACT_INDEX, DATABRICKS_EMBEDDING_ENDPOINT and DATABRICKS_ANSWER_ENDPOINT.')
        if self.genie_agent_id and not re.fullmatch(r'[0-9a-fA-F]{32}', self.genie_agent_id):
            raise RuntimeError('DATABRICKS_GENIE_AGENT_ID must be the 32-character ID from /genie/rooms/<id>.')
        if not re.fullmatch(r'[^.\s/]+\.[^.\s/]+\.[^.\s/]+', self.contract_index):
            raise RuntimeError('DATABRICKS_CONTRACT_INDEX must be a catalog.schema.index name.')
        if not 1 <= self.rag_top_k <= 10 or not 0 <= self.rag_history_messages <= 20:
            raise RuntimeError('ATLAS_RAG_TOP_K must be 1-10 and ATLAS_RAG_HISTORY_MESSAGES must be 0-20.')
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
