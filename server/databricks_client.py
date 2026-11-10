"""Shared SDK authentication; never send credentials to the React client."""
import asyncio
import httpx

from .databricks_errors import check_databricks_response


def workspace_client(settings):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.core import Config
    return WorkspaceClient(config=Config(host=settings.databricks_host,
                           profile=settings.databricks_profile or None,
                           http_timeout_seconds=15, retry_timeout_seconds=20))


class DatabricksHTTP:
    def __init__(self, settings, workspace=None, transport=None, token=None):
        self.settings = settings
        self.token = token
        self.workspace = workspace or (None if token else workspace_client(settings))
        self.transport = transport

    async def headers(self):
        headers = {'Authorization': 'Bearer ' + self.token} if self.token else dict(await asyncio.to_thread(self.workspace.config.authenticate))
        headers["Content-Type"] = "application/json"
        return headers

    def bearer_token(self):
        if self.token:
            return self.token
        authorization = self.workspace.config.authenticate().get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise RuntimeError("Databricks bearer authentication is unavailable.")
        return token

    def client(self):
        return httpx.AsyncClient(base_url=self.settings.databricks_host.rstrip("/"),
                                 timeout=httpx.Timeout(120, connect=15),
                                 transport=self.transport, follow_redirects=False)

    async def post(self, path, payload):
        async with self.client() as client:
            response = await client.post(path, headers=await self.headers(), json=payload)
            check_databricks_response(response, payload)
            return response.json()


async def sse_events(lines):
    """Parse complete SSE frames, including comments and multi-line data fields."""
    data = []
    async for line in lines:
        if line == "":
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield "\n".join(data)
