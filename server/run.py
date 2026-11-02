"""One server serves the built React UI and all API routes."""
import os
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .app import create_app
from .config import Settings
from .database import Base


def build_app():
    settings = Settings()
    settings.validate()
    factory = None
    if settings.history_backend == 'sqlite':
        root = Path(__file__).resolve().parents[1] / '.local-preview'
        root.mkdir(exist_ok=True)
        engine = create_engine('sqlite:///' + (root / 'history.db').as_posix(), connect_args={'check_same_thread': False})
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
    return create_app(settings, session_factory=factory)


if __name__ == '__main__':
    settings = Settings()
    uvicorn.run(build_app(), host='127.0.0.1' if settings.auth_mode == 'local' else '0.0.0.0',
                port=int(os.getenv('DATABRICKS_APP_PORT', '8000')), server_header=False, access_log=False)
