"""Launch the existing React/API app with the explicitly separate Koantek POC agent."""
import os
import sys
import time
from uuid import uuid4

import uvicorn
from server.app import create_app
from server.config import Settings
from .koantek_agent import KoantekPocAgent


def build_app():
    settings = Settings()
    settings.validate()
    if settings.auth_mode != 'databricks-app' or settings.history_backend != 'lakebase':
        raise RuntimeError('The deployed POC requires Databricks user auth and Lakebase history.')
    if settings.pg_database != 'aia_micro_poc':
        raise RuntimeError('Use the separate aia_micro_poc database for this POC.')
    app = create_app(settings, notebook_agent_factory=KoantekPocAgent)
    boot, started = str(uuid4()), time.monotonic()

    @app.get('/api/poc/runtime')
    def runtime_info():
        return {'poc': 'koantek-bike-projects', 'python': sys.version.split()[0], 'boot_id': boot,
                'uptime_seconds': round(time.monotonic() - started, 2),
                'workflow': 'POC adapter; exported notebook Genie and follow-up functions',
                'history': 'separate Lakebase database', 'mlflow': 'not configured in this POC'}
    return app


if __name__ == '__main__':
    uvicorn.run(build_app(), host='0.0.0.0', port=int(os.getenv('DATABRICKS_APP_PORT', '8000')), access_log=False)
