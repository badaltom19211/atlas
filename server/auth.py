"""Databricks App user authorization; local development uses the CLI identity.

Tokens stay on the server and are scoped to a single request/agent instance.
Lakebase uses the app identity; every history query checks the signed-in owner.
"""
import asyncio
import hashlib
import json
from types import SimpleNamespace

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from .database import User
from .databricks_client import workspace_client


def user_id(settings, subject):
    # Preserve the IDs already used when the local chats were migrated to Lakebase.
    return 'databricks-local:' + hashlib.sha256(json.dumps([settings.databricks_host.rstrip('/'), str(subject)]).encode()).hexdigest()


def install_auth(app, settings, database, identity_resolver=None):
    local_workspace = None

    async def resolve(request):
        nonlocal local_workspace
        if identity_resolver is not None:
            return await identity_resolver(request)
        if settings.auth_mode == 'local':
            if local_workspace is None:
                local_workspace = await asyncio.to_thread(workspace_client, settings)
            workspace, token = local_workspace, None
        else:
            token = request.headers.get('x-forwarded-access-token', '')
            if not token:
                raise HTTPException(401, 'Open AIA through Databricks and allow the requested user authorization scopes.')
            # Verify the token against the configured workspace. Never identify users
            # from a browser-supplied email/name header or fall back to the app owner.
            workspace = WorkspaceClient(config=Config(host=settings.databricks_host, token=token, auth_type='pat',
                                                       http_timeout_seconds=15, retry_timeout_seconds=20))
        try:
            identity = await asyncio.to_thread(workspace.current_user.me)
        except Exception:
            raise HTTPException(401, 'Databricks authentication failed. Sign in again.') from None
        if not identity.id or identity.active is False:
            raise HTTPException(401, 'An active Databricks user is required.')
        return SimpleNamespace(id=str(identity.id), name=identity.display_name or identity.user_name or 'You',
                               email=identity.user_name or '', token=token)

    @app.middleware('http')
    async def local_boundary(request, call_next):
        if settings.auth_mode == 'local':
            if not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient') or request.url.hostname not in ('localhost', '127.0.0.1', 'testserver'):
                return Response('Local development only', status_code=403)
        return await call_next(request)

    async def current(request: Request, db=Depends(database)):
        if request.cookies.get('atlas_signed_out') == '1':
            raise HTTPException(401, 'Sign in to continue.')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            # A custom header cannot be submitted by cross-origin forms. No CORS
            # permission is granted by this app. Reject explicit cross-site requests.
            if request.headers.get('x-atlas-request') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
                raise HTTPException(403, 'Request verification failed. Reload and try again.')
        identity = await resolve(request)
        key = user_id(settings, identity.id)
        user = db.get(User, key)
        if user is None:
            user = User(id=key, name=identity.name[:250], email=identity.email[:320])
            db.add(user)
            db.commit()
        return SimpleNamespace(user_id=key, token=identity.token)

    @app.get('/api/auth/login')
    async def login(request: Request):
        await resolve(request)
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie('atlas_signed_out', path='/', secure=settings.secure_cookies, httponly=True, samesite='lax')
        return response

    @app.post('/api/auth/logout', status_code=204)
    def logout(session=Depends(current)):
        response = Response(status_code=204)
        response.set_cookie('atlas_signed_out', '1', path='/', secure=settings.secure_cookies, httponly=True, samesite='lax')
        return response

    return current
