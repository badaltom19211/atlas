"""Actionable API failures without exposing provider bodies, URLs or credentials."""
import logging

import httpx

logger = logging.getLogger('aia.databricks')
GENERIC_FAILURE = 'The assistant could not complete the response. Check the app logs and try again.'


def operation_for(path, payload=None):
    # Labels and setting names are fixed strings, never values supplied by a provider.
    if path == '/ai-gateway/mlflow/v1/chat/completions':
        return 'AI Gateway chat model', 'ai-gateway', 'DATABRICKS_AGENT_MODEL'
    if path == '/ai-gateway/mlflow/v1/embeddings':
        return 'AI Gateway embedding model', 'ai-gateway', 'DATABRICKS_EMBEDDING_MODEL'
    if path.startswith('/api/2.0/vector-search/indexes/') and path.endswith('/query'):
        return 'Vector Search index query', 'vector-search', 'DATABRICKS_CONTRACT_INDEX'
    if path.startswith('/api/2.0/genie/agents/'):
        return ('Genie cancellation' if path.endswith('/cancel') else 'Genie response'), 'genie', 'DATABRICKS_GENIE_AGENT_ID'
    if path.startswith('/serving-endpoints/') and path.endswith('/invocations'):
        if isinstance(payload, dict) and 'input' in payload:
            return 'Model Serving embedding', 'model-serving', 'DATABRICKS_EMBEDDING_ENDPOINT'
        return 'Model Serving chat', 'model-serving', 'DATABRICKS_ANSWER_ENDPOINT'
    return 'Databricks API', None, None


class DatabricksRequestError(httpx.HTTPStatusError):
    def __init__(self, response, payload=None):
        self.operation, self.scope, self.setting = operation_for(response.request.url.path, payload)
        self.status = response.status_code
        super().__init__(f'{self.operation} failed (HTTP {self.status}).',
                         request=response.request, response=response)

    def public_message(self):
        prefix = f'{self.operation} failed (HTTP {self.status}).'
        if self.status == 401:
            return prefix + ' Open the app in a fresh Databricks sign-in session and approve any requested access.'
        if self.status == 403:
            scope = f' the app\'s {self.scope} scope and consent, and' if self.scope else ''
            return prefix + f' Check{scope} your permission to use this resource.'
        if self.status == 404:
            setting = f' {self.setting} and' if self.setting else ''
            return prefix + f' Check{setting} whether this resource and API are available in this workspace.'
        if self.status == 429:
            return prefix + ' The service is rate limited. Wait briefly before trying again.'
        if self.status >= 500:
            return prefix + ' The Databricks service could not complete the request. Try again later.'
        return prefix + ' Ask the app owner to check the request configuration for this service.'


def check_databricks_response(response, payload=None):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        error = DatabricksRequestError(response, payload)
        logger.warning('Databricks request failed: operation=%s; HTTP=%s; scope=%s; setting=%s',
                       error.operation, error.status, error.scope or 'unknown', error.setting or 'unknown')
        # No response text, model input, request URL, token or raw exception in logs.
        raise error from None


class ContractSourcesUnavailable(RuntimeError):
    def __init__(self, errors):
        super().__init__('Neither contract source is available.')
        self.errors = tuple(errors)


class NotebookCallError(RuntimeError):
    LABELS = {'authentication': 'Notebook user authentication',
              'workflow': 'Notebook workflow', 'genie': 'Genie response',
              'documents': 'Contract document search', 'tracing': 'MLflow experiment access'}

    def __init__(self, stage, status):
        self.stage = stage if stage in self.LABELS else 'workflow'
        self.status = status if isinstance(status, int) else None
        super().__init__(self.public_message())
        logger.warning('Notebook call failed: stage=%s; HTTP=%s', self.stage, self.status or 'unknown')

    def public_message(self):
        label = self.LABELS[self.stage]
        status = f' (HTTP {self.status})' if self.status else ''
        if self.stage == 'tracing':
            return f'{label} failed{status}. Check the experiment resource and app service principal permissions.'
        if self.status in (401, 403):
            return f'{label} failed{status}. Check app scopes, sign-in consent, and your resource permissions.'
        return f'{label} failed{status}. Check the app configuration and try again.'


def known_failures(error):
    if isinstance(error, (DatabricksRequestError, NotebookCallError)):
        yield error
    elif isinstance(error, ContractSourcesUnavailable):
        for child in error.errors:
            yield from known_failures(child)
    elif isinstance(error, BaseExceptionGroup):
        # Follow-up metadata uses TaskGroup, which wraps the underlying API error.
        for child in error.exceptions:
            yield from known_failures(child)


def public_failure(error):
    messages = list(dict.fromkeys(item.public_message() for item in known_failures(error)))
    if messages:
        return ' '.join(messages[:3])
    if isinstance(error, ContractSourcesUnavailable):
        return 'Neither Genie nor contract document search could complete the request. Check the app logs and try again.'
    if isinstance(error, TimeoutError):
        return 'The response timed out. Try again with a narrower question.'
    return GENERIC_FAILURE
