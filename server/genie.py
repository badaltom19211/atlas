"""Genie Agent-mode API adapter; only final answers and bounded provenance leave it."""
import asyncio
import json
import re
from urllib.parse import quote

from .databricks_client import sse_events
from .databricks_errors import check_databricks_response
from .notebook_agent import extract_text


class GenieFailure(RuntimeError):
    pass


class GenieAgent:
    def __init__(self, settings, http):
        self.settings, self.http = settings, http

    async def answer(self, question, *, include_evidence=False):
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
                    check_databricks_response(response)
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
                            if len(answer) > 60000:
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
                            metadata = {
                                'agent_id': self.settings.genie_agent_id,
                                'conversation_id': str(conversation_id)[:100] if conversation_id else None,
                                'response_id': str(response_id)[:100] if response_id else None,
                                'queries': queries,
                            }
                            if include_evidence:
                                references, evidence = genie_evidence(output, answer, self.settings, conversation_id)
                                metadata.update(references=references, evidence=evidence)
                                if not answer and not references:
                                    raise GenieFailure('Genie returned no usable final answer or query results.')
                            elif not answer:
                                raise GenieFailure('Genie returned no usable final answer.')
                            return answer, metadata
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


def has_result_rows(text):
    """Only a Markdown table data row counts; COUNT(*) = 0 is still a data row."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines[1:], 1):
        cells = line.strip('|').split('|')
        if '|' in line and all(re.fullmatch(r'\s*:?-+:?\s*', cell) for cell in cells):
            return index + 1 < len(lines) and lines[index + 1].startswith('|')
    return False


def genie_evidence(output, answer, settings, conversation_id):
    """Only SQL results and final text become evidence; never reasoning items."""
    # The API pairs outputs by call_id; some payloads expose only <call_id>_output.
    outputs = {}
    for item in output:
        if item.get('type') != 'function_call_output' or item.get('status') in ('failed', 'error'):
            continue
        call_id = item.get('call_id')
        if not call_id and isinstance(item.get('id'), str) and item['id'].endswith('_output'):
            call_id = item['id'][:-7]
        if call_id:
            outputs[call_id] = item.get('output')
    root = settings.databricks_host.rstrip('/') + '/genie/rooms/' + quote(settings.genie_agent_id, safe='')
    link = root + '/chats/' + quote(str(conversation_id), safe='') if conversation_id else root
    sources, blocks = [], []
    for item in output:
        if item.get('type') != 'function_call' or item.get('name') != 'execute_sql' or len(sources) >= 4:
            continue
        try:
            args = json.loads(item.get('arguments') or '{}')
        except (ValueError, TypeError):
            continue
        sql = args.get('sql') or args.get('query') if isinstance(args, dict) else None
        result = outputs.get(item.get('call_id'))
        if not isinstance(sql, str) or not sql.strip() or not isinstance(result, str) or not result.strip():
            continue
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and (parsed.get('error') or parsed.get('status') in ('error', 'failed')):
                continue
        except ValueError:
            pass
        identifier = f'G{len(sources) + 1}'
        title = str(args.get('title') or 'Contract query')[:240]
        tables = sorted(set(t.replace('`', '') for t in re.findall(
            r'\b(?:FROM|JOIN)\s+([\w`]+\.[\w`]+\.[\w`]+)', sql, re.I)))[:5]
        source_link = link + '?gra_focus=' + quote(str(item.get('call_id')), safe='')
        sources.append({'id': identifier, 'kind': 'genie', 'label': title,
                        'url': source_link if len(source_link) <= 1024 else link,
                        'sql': sql.strip()[:4000], 'sql_truncated': len(sql.strip()) > 4000,
                        'has_rows': has_result_rows(result),
                        'tables': [table[:100] for table in tables]})
        blocks.append(f'[{identifier}] {title}\n{result[:8000]}')
    answer = re.sub(r'\\?\[\[\d+\]\([^)]*\)\\?\]', '', answer)
    if not sources:
        return [], 'Genie returned no SQL-backed results that can be cited. Do not infer structured facts from its summary.'
    return sources, 'Final Genie response (interpret with the query results):\n' + answer[:12000] + '\n\n' + '\n\n'.join(blocks)
