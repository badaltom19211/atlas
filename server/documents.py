"""Read contract PDFs through Files API with the current user's permissions."""
import re
from urllib.parse import quote

import anyio
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .citations import safe_volume_pdf_path
from .databricks_client import DatabricksHTTP


async def close_download(client, response=None):
    # A browser may close the tab while bytes are still arriving.
    with anyio.CancelScope(shield=True):
        try:
            if response is not None:
                await response.aclose()
        finally:
            await client.aclose()


class PDFStream(StreamingResponse):
    def __init__(self, client, upstream, filename):
        self.client, self.upstream = client, upstream
        headers = {key: upstream.headers[key] for key in
                   ('content-length', 'content-range', 'last-modified', 'accept-ranges')
                   if key in upstream.headers}
        headers.update({'Content-Disposition': "inline; filename*=UTF-8''" + quote(filename, safe=''),
                        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        super().__init__(upstream.aiter_raw(), status_code=upstream.status_code,
                         media_type='application/pdf', headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await close_download(self.client, self.upstream)


async def document_pdf(request, settings, token):
    paths = request.query_params.getlist('path')
    path = safe_volume_pdf_path(paths[0]) if len(paths) == 1 else None
    if not path or any(key != 'path' for key in request.query_params):
        raise HTTPException(400, 'Choose a PDF from the configured contract document folder.')
    if settings.auth_mode != 'local' and not token:
        raise HTTPException(401, 'Sign in through Databricks to open this document.')

    byte_range = request.headers.get('range')
    if byte_range:
        match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', byte_range)
        if not match or not any(match.groups()):
            raise HTTPException(416, 'A single valid byte range is required.')
        start, end = match.groups()
        if (start and end and int(start) > int(end)) or (not start and int(end) == 0):
            raise HTTPException(416, 'The requested byte range is invalid.')

    http = DatabricksHTTP(settings, token=token)
    client, upstream = http.client(), None
    try:
        headers = await http.headers()
        headers.update({'Accept': 'application/pdf', 'Accept-Encoding': 'identity'})
        if byte_range:
            headers['Range'] = byte_range
        upstream = await client.send(client.build_request(
            'GET', '/api/2.0/fs/files' + quote(path, safe='/'), headers=headers), stream=True)
        errors = {
            401: 'Databricks authorization expired. Reopen the app and sign in again.',
            403: 'Document access denied. Check the app files user-authorization scope and your READ VOLUME permission.',
            404: 'This contract PDF could not be found.',
            416: 'The requested byte range is unavailable.',
            429: 'Document access is temporarily rate limited. Please try again.',
        }
        if upstream.status_code in errors:
            raise HTTPException(upstream.status_code, errors[upstream.status_code])
        if upstream.status_code not in (200, 206):
            raise HTTPException(502, 'The document service could not return this PDF. Please try again.')
        # Never follow provider redirects or copy its cookies/credentials to the browser.
        if upstream.headers.get('content-encoding', 'identity') != 'identity':
            raise HTTPException(502, 'The document service returned an unsupported transfer encoding.')
        return PDFStream(client, upstream, path.rsplit('/', 1)[-1])
    except BaseException as error:
        await close_download(client, upstream)
        if isinstance(error, httpx.TimeoutException):
            raise HTTPException(504, 'The document service timed out. Please try again.') from None
        if isinstance(error, httpx.HTTPError):
            raise HTTPException(502, 'The document service is unavailable. Please try again.') from None
        raise
