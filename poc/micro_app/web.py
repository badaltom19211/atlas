"""Session-only Micro App POC. Real Databricks OBO; no database fallback.

History is held only by the current browser page and explicitly passed per call.
The production API and its Lakebase requirement remain unchanged.
"""
import asyncio
import os
import re
import time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
import uvicorn

from server.config import Settings
from server.databricks_errors import public_failure
from .koantek_agent import KoantekPocAgent


class Turn(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=16000)
    notebook_query: str | None = Field(default=None, max_length=16000)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=12000)
    history: list[Turn] = Field(default_factory=list, max_length=6)
    session_id: str = Field(pattern=r'^[a-zA-Z0-9-]{1,64}$')


def build_app():
    settings = Settings()
    if settings.auth_mode != 'databricks-app' or urlparse(settings.databricks_host).scheme != 'https':
        raise RuntimeError('POC requires a Databricks HTTPS workspace and Databricks app auth.')
    if not re.fullmatch(r'[0-9a-fA-F]{32}', settings.genie_agent_id):
        raise RuntimeError('Configure the Koantek Genie ID.')
    if settings.model_api != 'gateway' or not re.fullmatch(r'[^.\s/]+\.[^.\s/]+\.[^.\s/]+', settings.contract_index):
        raise RuntimeError('POC requires a project index and gateway model.')
    if settings.mlflow_experiment_id:
        raise RuntimeError('MLflow is not part of the session-only POC.')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    slots = asyncio.Semaphore(2)
    boot, started = str(uuid4()), time.monotonic()

    @app.middleware('http')
    async def security(request: Request, call_next):
        size = request.headers.get('content-length')
        if size and (not size.isdigit() or int(size) > 150000):
            return Response('Request too large', status_code=413)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('x-atlas-request') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
                return Response('Request verification failed', status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    async def identity(request: Request):
        token = request.headers.get('x-forwarded-access-token')
        if not token:
            raise HTTPException(401, 'Sign in through Databricks and approve the App Space access.')
        def verify():
            client = WorkspaceClient(config=Config(host=settings.databricks_host, token=token, auth_type='pat',
                                                    http_timeout_seconds=15, retry_timeout_seconds=15))
            return client.current_user.me()
        try:
            user = await asyncio.to_thread(verify)
        except Exception:
            raise HTTPException(401, 'Databricks sign-in could not be verified.') from None
        if not user.id or user.active is False:
            raise HTTPException(401, 'An active Databricks user is required.')
        return user, token

    @app.get('/api/me')
    def me(auth=Depends(identity)):
        user, _ = auth
        return {'name': user.display_name or user.user_name or 'You', 'history': 'session-only',
                'boot_id': boot, 'uptime_seconds': round(time.monotonic() - started, 2)}

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'mode': 'koantek-session-poc', 'boot_id': boot}

    @app.post('/api/chat')
    async def chat(body: Question, auth=Depends(identity)):
        if not body.question.strip():
            raise HTTPException(422, 'Question must not be blank.')
        user, token = auth
        if sum(len(turn.content) + len(turn.notebook_query or '') for turn in body.history) > 100000:
            raise HTTPException(422, 'Conversation context is too large.')
        messages = [turn.model_dump(exclude_none=True) for turn in body.history]
        messages.append({'role': 'user', 'content': body.question})
        agent = KoantekPocAgent(settings, token=token, user_id=str(user.id),
                               conversation_id=body.session_id, slots=slots)
        start = time.monotonic()
        try:
            async with asyncio.timeout(settings.agent_timeout_seconds):
                answer, metadata = await agent.answer(messages)
        except Exception as error:
            raise HTTPException(502, public_failure(error)) from None
        return {'answer': answer, 'custom_outputs': metadata,
                'elapsed_seconds': round(time.monotonic() - start, 2), 'boot_id': boot}

    root = Path(__file__).resolve().parents[2] / 'dist'
    app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')

    @app.get('/')
    def index():
        return FileResponse(root / 'index.html')
    return app


if __name__ == '__main__':
    uvicorn.run(build_app(), host='0.0.0.0', port=int(os.getenv('DATABRICKS_APP_PORT', '8000')), access_log=False)
