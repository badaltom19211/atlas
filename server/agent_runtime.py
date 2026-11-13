"""Request-scoped services for the importable notebook; no user credentials in globals."""
import asyncio
import contextvars
import copy
import functools
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from .databricks_errors import NotebookCallError


def provider_failure(stage, error):
    status = getattr(error, 'status_code', None)
    if status is None:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
    return NotebookCallError(stage, status)


class EmptySpan:
    def set_inputs(self, *args, **kwargs): pass
    def set_outputs(self, *args, **kwargs): pass
    def set_attribute(self, *args, **kwargs): pass
    def set_attributes(self, *args, **kwargs): pass


class DisabledTracing:
    enabled = False

    @contextmanager
    def start_span(self, **kwargs):
        yield EmptySpan()

    def get_current_active_span(self): return None
    def update_current_trace(self, **kwargs): pass


def configure_tracing(settings):
    """Once at app startup. User tokens are never assigned to the process environment."""
    if not settings.mlflow_experiment_id:
        return DisabledTracing()
    import mlflow
    try:
        if settings.auth_mode == 'databricks-app':
            if not os.environ.get('DATABRICKS_CLIENT_ID') or not os.environ.get('DATABRICKS_CLIENT_SECRET'):
                raise ValueError('Missing injected app credentials.')
            os.environ.pop('DATABRICKS_TOKEN', None)
            os.environ['DATABRICKS_AUTH_TYPE'] = 'oauth-m2m'
        mlflow.set_tracking_uri('databricks')
        mlflow.set_experiment(experiment_id=settings.mlflow_experiment_id)
        mlflow.tracing.enable()
        mlflow.tracing.disable_notebook_display()
        # Explicit notebook spans only: never auto-capture runtime objects/tokens.
        return mlflow
    except Exception as error:
        raise provider_failure('tracing', error) from None


@dataclass(repr=False)
class RequestRuntime:
    settings: object
    token: str
    user_id: str
    glossary: object = None
    tracing: object = field(default_factory=DisabledTracing)
    cancel: threading.Event = field(default_factory=threading.Event)
    failures: dict = field(default_factory=dict)
    agent: object = None
    oai: object = None
    vs_index: object = None
    http: object = None

    def __post_init__(self):
        self.host = self.settings.databricks_host.rstrip('/')
        self.gateway_url = self.host + '/ai-gateway/mlflow/v1'
        self.genie_url = self.host + '/api/2.0/genie/agents/' + self.settings.genie_agent_id + '/responses'
        self.deadline = time.monotonic() + self.settings.agent_timeout_seconds

    def check(self):
        if self.cancel.is_set():
            raise asyncio.CancelledError()
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Agent deadline exceeded.')

    def enrich_question(self, query):
        self.check()
        if self.glossary is None or self.glossary.status != 'ready':
            return {'has_matches': False, 'primary_matches': [], 'related_matches': []}
        return self.glossary.enrich(query, copy.deepcopy(self.glossary.glossary))


_CURRENT = contextvars.ContextVar('aia_notebook_request')


def current_runtime():
    return _CURRENT.get()


@contextmanager
def bind_runtime(runtime):
    marker = _CURRENT.set(runtime)
    try:
        yield runtime
    finally:
        _CURRENT.reset(marker)


class ScopedTracing:
    """Same explicit tracing calls as the notebook, resolved against this request."""
    def __getattr__(self, name):
        return getattr(current_runtime().tracing, name)

    def trace(self, *, name, span_type):
        def decorate(fn):
            @functools.wraps(fn)
            def traced(*args, **kwargs):
                with self.start_span(name=name, span_type=span_type) as span:
                    span.set_inputs({'args': args, 'kwargs': kwargs})
                    result = fn(*args, **kwargs)
                    span.set_outputs(result)
                    return result
            return traced
        return decorate


@contextmanager
def open_runtime(settings, token, user_id, *, glossary=None, tracing=None, cancel=None):
    """Create and close clients per call; all protected APIs use the explicit user token."""
    if not token:
        raise NotebookCallError('authentication', None)
    from openai import OpenAI
    import httpx
    from databricks.vector_search.client import VectorSearchClient
    runtime = RequestRuntime(settings, token, user_id, glossary,
                             tracing if tracing is not None else DisabledTracing(),
                             cancel if cancel is not None else threading.Event())
    with bind_runtime(runtime):
        runtime.http = httpx.Client(timeout=60)
        try:
            runtime.oai = OpenAI(api_key=token, base_url=runtime.gateway_url, timeout=60,
                                 max_retries=0, http_client=runtime.http)
            class UserIndex:
                def similarity_search(self, **kwargs):
                    runtime.check()
                    client = VectorSearchClient(workspace_url=runtime.host, personal_access_token=token, disable_notice=True)
                    index = client.get_index(index_name=settings.contract_index)
                    runtime.check()
                    result = index.similarity_search(**kwargs, total_retries=0)
                    runtime.check()
                    return result
            runtime.vs_index = UserIndex()
            yield runtime
        finally:
            runtime.http.close()
            runtime.agent = runtime.oai = runtime.vs_index = runtime.http = None
            runtime.token = ''
