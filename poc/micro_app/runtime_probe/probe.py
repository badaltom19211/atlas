"""Small, authenticated-platform runtime probe. Contains no data or credentials.

The Databricks app ingress must enforce sign-in. This deliberately has no model,
history API, or public network probe. Use before attempting the full AIA app.
"""
import asyncio
import json
import os
import sys
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
BOOT_ID = str(uuid4())
STARTED = time.monotonic()


@app.get('/api/probe')
def probe(request: Request):
    return {
        'poc': 'aia-micro-poc', 'python': sys.version.split()[0],
        'boot_id': BOOT_ID, 'uptime_seconds': round(time.monotonic() - STARTED, 2),
        # Booleans only; never disclose token or secret values.
        'forwarded_user_token_present': bool(request.headers.get('x-forwarded-access-token')),
        'app_credentials_present': bool(os.getenv('DATABRICKS_CLIENT_ID') and os.getenv('DATABRICKS_CLIENT_SECRET')),
    }


@app.get('/api/probe/stream')
async def stream():
    async def events():
        for step in range(3):
            yield json.dumps({'step': step, 'boot_id': BOOT_ID}) + '\n'
            await asyncio.sleep(1)
    return StreamingResponse(events(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})


@app.get('/', response_class=HTMLResponse)
def home():
    return '''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIA Micro App POC</title><style>body{font:16px system-ui;max-width:760px;margin:60px auto;padding:24px;color:#17243b}
h1{color:#d90042}pre{background:#f7f7fa;padding:20px;white-space:pre-wrap;border-radius:12px}</style></head>
<body><h1>AIA Micro App POC</h1><p>Python + FastAPI runtime check. Synthetic output only.</p>
<pre id="result">Checking runtime…</pre><pre id="stream">Checking incremental response…\n</pre>
<script>async function run(){let r=await fetch('/api/probe');document.querySelector('#result').textContent=JSON.stringify(await r.json(),null,2);
let s=await fetch('/api/probe/stream');let reader=s.body.getReader();let decoder=new TextDecoder();
while(true){let{value,done}=await reader.read();if(done)break;document.querySelector('#stream').textContent+=decoder.decode(value,{stream:true})}}
run().catch(e=>document.querySelector('#result').textContent=String(e));</script></body></html>'''


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('DATABRICKS_APP_PORT', '8000')), access_log=False)
