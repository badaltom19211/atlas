import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import select

from .database import ToolRun
from .databricks_client import DatabricksHTTP
from .genie import GenieAgent, GenieFailure
from .notebook_agent import source_metadata, contract_records
from .routed_agent import HYBRID_TOOL, RoutedAgent
from .test_app import setup, create
from .test_notebook_agent import configured, fixtures, search_result


def configuration():
    return replace(configured(), genie_agent_id='a' * 32)


def sse(*events):
    return httpx.Response(200, headers={'Content-Type': 'text/event-stream'},
                          text=': heartbeat\n\n' + ''.join('data: ' + json.dumps(event) + '\n\n' for event in events))


def completed(text='There are 12 active contracts.'):
    return {'type': 'response.completed', 'response': {
        'id': 'response-one', 'conversation_id': 'conversation-one', 'status': 'completed', 'output': [
            {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'private internal reasoning'}]},
            {'type': 'function_call', 'name': 'execute_sql', 'arguments': json.dumps({'query': 'SELECT count(*) FROM contracts'})},
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]},
        ]}}


def plan_response(route, genie_question='Active contract count?', contract_question='Non-payment notice?'):
    return httpx.Response(200, json={'choices': [{'message': {'tool_calls': [{
        'id': 'route-call', 'type': 'function', 'function': {'name': 'plan_data_sources', 'arguments': json.dumps({
            'route': route, 'genie_question': genie_question if route in ('genie', 'both') else '',
            'contract_question': contract_question if route in ('contracts', 'both') else '',
        })},
    }]}}]})


def agent_with(handler, **settings):
    config = replace(configuration(), **settings)
    return RoutedAgent(config, http=DatabricksHTTP(config, token='test-user', transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize('route', ['genie', 'contracts', 'both'])
def test_routes_to_selected_sources_and_preserves_attribution(route):
    calls = []
    def handler(request):
        assert request.headers['authorization'] == 'Bearer test-user'
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if 'tools' in body:
            assert body['tool_choice']['function']['name'] == 'plan_data_sources'
            return plan_response(route)
        if '/genie/' in request.url.path:
            assert request.url.path == '/api/2.0/genie/agents/' + 'a' * 32 + '/responses'
            assert body['input'][0]['content'][0]['text'] == 'Active contract count?'
            return sse(completed())
        return fixtures(request)
    answer, metadata = asyncio.run(agent_with(handler).answer([{'role': 'user', 'content': 'Question'}]))
    assert metadata['route'] == route
    assert all(status == 'completed' for status in metadata['source_status'].values())
    assert len(calls) == {'genie': 2, 'contracts': 4, 'both': 5}[route]
    if route in ('genie', 'both'):
        assert '12 active contracts' in answer
        assert metadata['genie']['queries'][0]['sql'].startswith('SELECT')
    if route in ('contracts', 'both'):
        assert '30 days' in answer and len(metadata['sources']) == 2
    if route == 'both':
        assert answer.index('Structured data (Genie)') < answer.index('Contract documents')
    assert 'private internal reasoning' not in answer + json.dumps(metadata)


def test_follow_up_routing_receives_only_bounded_chat_and_resolves_retrieval_question():
    calls = []
    history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': f'Previous {i}'} for i in range(10)]
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if 'tools' in body:
            assert body['messages'][1:-1] == history[-6:]
            assert body['messages'][-1]['content'] == 'And this year?'
            return plan_response('genie', genie_question='Count active contracts for 2026.')
        assert body['input'][0]['content'][0]['text'] == 'Count active contracts for 2026.'
        assert 'conversation_id' not in body
        return sse(completed())
    asyncio.run(agent_with(handler).answer([*history, {'role': 'user', 'content': 'And this year?'}]))
    assert len(calls) == 2


@pytest.mark.parametrize('failure', ['missing', 'bad_json', 'unknown_tool', 'unknown_route', 'empty_query', 'multiple'])
def test_malformed_plan_cannot_bypass_tools_or_invent_answer(failure):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        response = plan_response('genie').json()
        message = response['choices'][0]['message']
        function = message['tool_calls'][0]['function']
        if failure == 'missing':
            message.pop('tool_calls')
            message['content'] = 'Invented count 999.'
        elif failure == 'bad_json':
            function['arguments'] = 'bad JSON'
        elif failure == 'unknown_tool':
            function['name'] = 'run_arbitrary_code'
        elif failure == 'multiple':
            message['tool_calls'] *= 2
        else:
            plan = json.loads(function['arguments'])
            plan['route' if failure == 'unknown_route' else 'genie_question'] = 'unknown' if failure == 'unknown_route' else ''
            function['arguments'] = json.dumps(plan)
        return httpx.Response(200, json=response)
    with pytest.raises(ValueError):
        asyncio.run(agent_with(handler).answer([{'role': 'user', 'content': 'Count?'}]))
    assert len(calls) == 1


@pytest.mark.parametrize('failed_source', ['genie', 'contracts'])
def test_mixed_failure_keeps_supported_answer_and_does_not_substitute_sources(failed_source):
    def handler(request):
        body = json.loads(request.content)
        if 'tools' in body:
            return plan_response('both')
        if '/genie/' in request.url.path:
            return httpx.Response(403, json={'secret': 'provider-detail'}) if failed_source == 'genie' else sse(completed())
        return httpx.Response(503, json={'secret': 'provider-detail'}) if failed_source == 'contracts' else fixtures(request)
    answer, metadata = asyncio.run(agent_with(handler).answer([{'role': 'user', 'content': 'Both'}]))
    assert metadata['source_status'][failed_source] == 'error'
    assert 'unavailable' in answer and 'provider-detail' not in answer + json.dumps(metadata)
    assert ('12 active contracts' in answer) == (failed_source != 'genie')
    assert ('30 days' in answer) == (failed_source != 'contracts')


@pytest.mark.parametrize('failure', ['http', 'failed', 'empty', 'truncated', 'malformed'])
def test_genie_failure_never_becomes_supported_data(failure):
    def handler(request):
        if failure == 'http':
            return httpx.Response(403)
        if failure == 'failed':
            return sse({'type': 'response.failed', 'response': {'status': 'failed'}})
        if failure == 'empty':
            return sse(completed(''))
        if failure == 'malformed':
            return httpx.Response(200, text='data: not-json\n\n')
        return sse({'type': 'response.created', 'response': {'status': 'in_progress'}})
    agent = agent_with(handler)
    with pytest.raises((GenieFailure, httpx.HTTPError, ValueError)):
        asyncio.run(GenieAgent(agent.settings, agent.http).answer('Count?'))


def test_incomplete_genie_stream_requests_cancellation_without_exposing_credentials():
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/cancel'):
            return httpx.Response(200, json={'status': 'CANCELLED'})
        return sse({'type': 'response.created', 'response': {
            'id': 'response-one', 'conversation_id': 'conversation-one', 'status': 'in_progress'}})
    agent = agent_with(handler)
    with pytest.raises(GenieFailure):
        asyncio.run(GenieAgent(agent.settings, agent.http).answer('Count?'))
    assert requests[-1].endswith('/conversations/conversation-one/responses/response-one/cancel')


def test_mixed_sources_are_saved_and_isolated_in_api_history(setup, monkeypatch):
    alice, bob, factory, model, _ = setup
    def handler(request):
        if 'tools' in json.loads(request.content):
            return plan_response('both')
        return sse(completed()) if '/genie/' in request.url.path else fixtures(request)
    monkeypatch.setattr(model, 'stream', agent_with(handler).stream)
    cid = create(alice)
    response = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Count and notice clauses?'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event['type'] for event in events] == ['delta', 'done']
    assistant = events[-1]['assistant']
    assert assistant['tools'] == [] and assistant['custom_outputs']['route'] == 'both'
    assert len(assistant['custom_outputs']['sources']) == 2
    assert assistant['custom_outputs']['genie']['agent_id'] == 'a' * 32
    assert alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1] == assistant
    assert bob.get('/api/bootstrap').json()['conversations'] == []
    with factory() as db:
        assert db.scalar(select(ToolRun)).name == HYBRID_TOOL


def test_combined_metadata_fits_existing_tool_record_budget():
    records = contract_records(search_result(), 5) * 5
    for record in records:
        for field in ('chunk_id', 'file_name', 'document_title', 'vendor_name', 'section_title', 'citation'):
            record[field] = 'x' * 20000
    metadata = {'sources': source_metadata(records, {1}), 'genie': {'queries': [{'sql': 'x' * 2000}] * 4}}
    assert len(json.dumps({'ok': True, 'custom_outputs': metadata}, ensure_ascii=False)) < 64000


def test_all_sources_failed_returns_error_instead_of_guessed_answer(setup, monkeypatch):
    alice, _, _, model, _ = setup
    def handler(request):
        return plan_response('both') if 'tools' in json.loads(request.content) else httpx.Response(403)
    monkeypatch.setattr(model, 'stream', agent_with(handler).stream)
    cid = create(alice)
    response = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Both sources'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'error' and not any(event['type'] == 'delta' for event in events)
    saved = alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert saved['status'] == 'error' and saved['custom_outputs']['sources'] == []


def test_source_timeout_keeps_the_other_result(monkeypatch):
    from .notebook_agent import ContractRAGAgent
    agent = agent_with(lambda _: plan_response('both'), agent_timeout_seconds=35.01)
    async def slow(*args):
        await asyncio.sleep(1)
    async def fast(*args):
        return 'Document answer.', {'sources': []}
    monkeypatch.setattr(GenieAgent, 'answer', slow)
    monkeypatch.setattr(ContractRAGAgent, 'answer', fast)
    answer, metadata = asyncio.run(agent.answer([{'role': 'user', 'content': 'Both'}]))
    assert 'Document answer.' in answer and 'Genie is unavailable' in answer
    assert metadata['source_status'] == {'genie': 'error', 'contracts': 'completed'}


def test_explicit_stop_cancels_remote_genie_after_created_event():
    calls = []
    class StoppedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            event = {'type': 'response.created', 'response': {'id': 'r', 'conversation_id': 'c', 'status': 'in_progress'}}
            yield ('data: ' + json.dumps(event) + '\n\n').encode()
            raise asyncio.CancelledError()
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/cancel'):
            return httpx.Response(200, json={'status': 'CANCELLED'})
        return httpx.Response(200, stream=StoppedStream())
    agent = agent_with(handler)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(GenieAgent(agent.settings, agent.http).answer('Count?'))
    assert calls[-1].endswith('/conversations/c/responses/r/cancel')
