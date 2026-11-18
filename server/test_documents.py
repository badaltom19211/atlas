"""PDF links must stay within the contract folder and the requesting user's access."""
import asyncio
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from . import documents
from .citations import PDF_ROOT, PDF_ROUTE, document_file_url, pdf_link, safe_volume_pdf_path
from .config import Settings
from .databricks_client import DatabricksHTTP
from .notebook_output import normalize_sources
from .test_app import setup


PDF = b'%PDF-1.7\nfixture document\n%%EOF'
PATH = PDF_ROOT + 'Vendor + Co #1 – signed.pdf'


class FileBytes(httpx.AsyncByteStream):
    def __init__(self, data=PDF):
        self.data, self.closed = data, False

    async def __aiter__(self):
        yield self.data[:8]
        yield self.data[8:]

    async def aclose(self):
        self.closed = True


def wire(monkeypatch, handler):
    monkeypatch.setattr(documents, 'DatabricksHTTP', lambda settings, token:
                        DatabricksHTTP(settings, token=token, transport=httpx.MockTransport(handler)))


def test_pdf_stream_uses_each_user_token_and_preserves_file_name(setup, monkeypatch):
    alice, bob, *_ = setup
    calls, streams = [], []
    def provider(request):
        calls.append(request)
        stream = FileBytes()
        streams.append(stream)
        return httpx.Response(200, stream=stream, headers={
            'Content-Type': 'application/octet-stream', 'Content-Length': str(len(PDF)),
            'Set-Cookie': 'provider-secret=private', 'Authorization': 'private-provider-token'})
    wire(monkeypatch, provider)
    for client in (alice, bob):
        response = client.get(pdf_link(PATH))
        assert response.status_code == 200 and response.content == PDF
        assert response.headers['content-type'] == 'application/pdf'
        assert response.headers['content-disposition'] == "inline; filename*=UTF-8''" + quote(PATH.rsplit('/', 1)[-1], safe='')
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'set-cookie' not in response.headers and 'authorization' not in response.headers
    assert [r.headers['authorization'] for r in calls] == ['Bearer test-alice', 'Bearer test-bob']
    assert all(r.url.host == 'workspace.example.test' for r in calls)
    assert all(unquote(r.url.raw_path.decode()) == '/api/2.0/fs/files' + PATH for r in calls)
    assert all(not r.url.query for r in calls)
    assert all(s.closed for s in streams)


def test_pdf_byte_ranges_are_forwarded_and_streams_closed(setup, monkeypatch):
    alice, *_ = setup
    stream = FileBytes(PDF[2:9])
    def provider(request):
        assert request.headers['range'] == 'bytes=2-8'
        return httpx.Response(206, stream=stream, headers={
            'Content-Range': f'bytes 2-8/{len(PDF)}', 'Content-Length': '7'})
    wire(monkeypatch, provider)
    response = alice.get(pdf_link(PATH), headers={'Range': 'bytes=2-8'})
    assert response.status_code == 206 and response.content == PDF[2:9]
    assert response.headers['content-range'] == f'bytes 2-8/{len(PDF)}'
    assert stream.closed


def test_invalid_paths_ranges_and_anonymous_requests_never_fetch(setup, monkeypatch):
    alice, *_ = setup
    wire(monkeypatch, lambda request: pytest.fail('Must not contact Files API'))
    invalid = ['', '/etc/secrets.pdf', PDF_ROOT + '../secret.pdf', PDF_ROOT + '%2e%2e/secret.pdf',
               PDF_ROOT + 'text.html', PDF_ROOT + 'bad\\name.pdf', PDF_ROOT + 'bad\r\nname.pdf',
               PDF_ROOT.replace('/Input/', '/Input-other/') + 'secret.pdf']
    for path in invalid:
        assert alice.get(PDF_ROUTE, params={'path': path}).status_code == 400
    assert alice.get(PDF_ROUTE).status_code == 400
    assert alice.get(PDF_ROUTE, params=[('path', PATH), ('path', PATH)]).status_code == 400
    assert alice.get(PDF_ROUTE, params={'path': PATH, 'url': 'https://evil.test'}).status_code == 400
    assert alice.get(pdf_link(PATH), headers={'x-test-user': ''}).status_code == 401
    for value in ('bytes=0-1,4-5', 'bytes=-', 'bytes=9-2', 'bytes=-0', 'items=0-5'):
        assert alice.get(pdf_link(PATH), headers={'Range': value}).status_code == 416


@pytest.mark.parametrize('status, expected', [(401, 401), (403, 403), (404, 404), (416, 416),
                                              (429, 429), (302, 502), (500, 502)])
def test_provider_errors_are_safe_and_redirects_are_not_followed(setup, monkeypatch, status, expected):
    alice, *_ = setup
    calls, stream = [], FileBytes(b'private upstream message and token')
    def provider(request):
        calls.append(request)
        return httpx.Response(status, stream=stream, headers={'Location': 'https://evil.example/private'})
    wire(monkeypatch, provider)
    response = alice.get(pdf_link(PATH))
    assert response.status_code == expected
    assert 'private' not in response.text and 'evil.example' not in response.text
    assert len(calls) == 1 and stream.closed


def test_timeout_has_a_readable_message(setup, monkeypatch):
    alice, *_ = setup
    def provider(request):
        raise httpx.ReadTimeout('private upstream details', request=request)
    wire(monkeypatch, provider)
    response = alice.get(pdf_link(PATH))
    assert response.status_code == 504 and 'private' not in response.text


def test_hosted_pdf_never_falls_back_to_app_credentials(monkeypatch):
    request = Request({'type': 'http', 'query_string': ('path=' + quote(PATH)).encode(), 'headers': []})
    monkeypatch.setattr(documents, 'DatabricksHTTP', lambda *a, **k: pytest.fail('No app-owner fallback'))
    with pytest.raises(HTTPException) as error:
        asyncio.run(documents.document_pdf(request, Settings(auth_mode='databricks-app'), None))
    assert error.value.status_code == 401


def test_notebook_document_links_use_pdf_route_without_altering_notebook():
    host = 'https://workspace.example.test'
    name = PATH.rsplit('/', 1)[-1]
    link = host + '/explore/data/volumes/dev_diamonddaas/raw/aia?volumePath=' + quote(PATH, safe='')
    ref = normalize_sources([{'id': 'D1', 'label': 'Contract, p. 4', 'document': name,
                              'link': link, 'page': 4}], host)[0]
    assert ref['url'] == pdf_link(PATH) and ref['page_start'] == 4
    assert parse_qs(urlsplit(ref['url']).query)['path'] == [PATH]
    folder_link = host + '/explore/data/volumes/dev_diamonddaas/raw/aia?volumePath=' + quote(PDF_ROOT, safe='')
    assert document_file_url(folder_link, name, host) == ref['url']
    assert document_file_url(PATH, name, host) == ref['url']
    assert document_file_url(link.replace(host, 'https://evil.example'), name, host) is None
    assert safe_volume_pdf_path(PATH) == PATH


def test_pdf_connection_closes_when_browser_disconnects():
    closed = []
    class Upstream:
        status_code, headers = 200, {}
        async def aiter_raw(self):
            yield PDF
        async def aclose(self): closed.append('response')
    class Client:
        async def aclose(self): closed.append('client')
    async def run():
        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('browser disconnected')
        async def receive(): return {'type': 'http.disconnect'}
        response = documents.PDFStream(Client(), Upstream(), 'contract.pdf')
        with pytest.raises(Exception):
            await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
    asyncio.run(run())
    assert closed == ['response', 'client']
