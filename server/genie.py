"""Genie Agent-mode API adapter; only final answers and bounded provenance leave it."""
import asyncio
import json
from urllib.parse import quote

from .databricks_client import sse_events
from .notebook_agent import extract_text


class GenieFailure(RuntimeError):
    pass


class GenieAgent:
    def __init__(self, settings, http):
        self.settings, self.http = settings, http

    async def answer(self, question):
        agent_id = quote(self.settings.genie_agent_id, safe='')
        path = f'/api/2.0/genie/agents/{agent_id}/responses'
        payload = {'input': [{'type': 'message', 'role': 'user',
                             'content': [{'type': 'input_text', 'text': question}]}]}
        # Each request gets a fresh Genie conversation. The router resolves
        # follow-ups from this user's Atlas history into a standalone question.
        conversation_id, response_id, terminal = None, None, False
        try:
            async with self.http.client() as client:
                headers = await self.http.headers()
                headers['Accept'] = 'text/event-stream'
                async with client.stream('POST', path, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for data in sse_events(response.aiter_lines()):
                        if data == '[DONE]':
                            break
                        event = json.loads(data)
                        current = event.get('response') or {}
                        conversation_id = current.get('conversation_id') or conversation_id
                        response_id = current.get('id') or response_id
                        if event.get('type') in ('response.failed', 'response.incomplete', 'error') or event.get('error'):
                            terminal = True
                            raise GenieFailure('Genie could not complete the request.')
                        if event.get('type') == 'response.completed':
                            terminal = True
                            if current.get('status') != 'completed' or current.get('error'):
                                raise GenieFailure('Genie could not complete the request.')
                            output = current.get('output') or []
                            answer = '\n'.join(extract_text(item.get('content')) for item in output
                                               if item.get('type') == 'message' and item.get('role') == 'assistant').strip()
                            if not answer or len(answer) > 60000:
                                raise GenieFailure('Genie returned no usable final answer.')
                            # Never expose reasoning items or raw provider errors.
                            queries = []
                            for item in output:
                                if item.get('type') != 'function_call' or item.get('name') != 'execute_sql':
                                    continue
                                try:
                                    args = json.loads(item.get('arguments') or '{}')
                                    sql = args.get('query') or args.get('sql') if isinstance(args, dict) else None
                                except (ValueError, TypeError):
                                    continue
                                if isinstance(sql, str) and len(queries) < 4:
                                    queries.append({'sql': sql[:2000], 'truncated': len(sql) > 2000})
                            return answer, {
                                'agent_id': self.settings.genie_agent_id,
                                'conversation_id': str(conversation_id)[:100] if conversation_id else None,
                                'response_id': str(response_id)[:100] if response_id else None,
                                'queries': queries,
                            }
            raise GenieFailure('Genie stream ended before a final answer.')
        finally:
            # A disconnected SSE stream does not stop Genie server-side. Try the
            # documented cancel API on timeout, stop, or a truncated connection.
            if not terminal and conversation_id and response_id:
                cancel_path = (f'/api/2.0/genie/agents/{agent_id}/conversations/'
                               f'{quote(str(conversation_id), safe="")}/responses/'
                               f'{quote(str(response_id), safe="")}/cancel')
                try:
                    async with asyncio.timeout(5):
                        await self.http.post(cancel_path, {})
                except Exception:
                    pass
