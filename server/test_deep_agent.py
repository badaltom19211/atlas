import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from .app import create_app
from .citations import check_citations, document_sources, safe_source_url
from .databricks_client import DatabricksHTTP
from .deep_agent import DeepContractAgent, MERGE_PROMPT, RAG_PROMPT
from .query_metadata import clean_metadata
from .test_app import setup, create
from .test_notebook_agent import configured, search_result
from .test_routed_agent import completed, sse


def completion(text):
    return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})


def genie_event():
    event = completed()
    output = event['response']['output']
    output[1].update(call_id='query-1', arguments=json.dumps({
        'title': 'Active contracts', 'sql': 'SELECT count(*) FROM catalog.schema.contracts'}))
    output.append({'type': 'function_call_output', 'call_id': 'query-1',
                   'output': '| count |\n| --- |\n| 12 |'})
    return event


class Fixture:
    def __init__(self, failure=None, final='There are 12 active contracts [G1]. Non-payment requires 30 days notice [D1].'):
        self.calls, self.failure, self.final = [], failure, final

    def __call__(self, request):
        body = json.loads(request.content)
        path = request.url.path
        self.calls.append((path, body, request.headers['authorization']))
        if '/genie/' in path:
            return httpx.Response(403) if self.failure in ('genie', 'both') else sse(genie_event())
        if path.endswith('/embeddings') or '/fixture-embedding/' in path:
            return httpx.Response(403) if self.failure in ('contracts', 'both') else httpx.Response(200, json={'data': [{'embedding': [.1, .2]}]})
        if path.endswith('/query'):
            result = search_result()
            if self.failure == 'empty':
                result['result']['data_array'] = []
            return httpx.Response(200, json=result)
        system, user = body['messages'][0]['content'], body['messages'][1]['content']
        if system.startswith('Extract contract search metadata'):
            if self.failure == 'metadata':
                return completion('malformed JSON')
            return completion(json.dumps({'vendor_name': ['Fixture Vendor'], 'topics': ['termination'],
                                          'requested_fields': ['expiry_date'] if 'Also the end date' in user else ['notice_period']}))
        if system.startswith('Classify whether'):
            return completion('{"follow_up": true}')
        if system.startswith('Rewrite ONLY'):
            return completion('What is the expiry date of the Fixture Vendor agreement?')
        if system == RAG_PROMPT:
            return completion('Non-payment requires 30 days notice [D1].')
        assert system.startswith(MERGE_PROMPT)
        return completion(self.final)


def agent(fixture, **changes):
    settings = replace(configured(), model_api='gateway', genie_agent_id='a' * 32, rag_top_k=20, **changes)
    return DeepContractAgent(settings, DatabricksHTTP(settings, token='user-token', transport=httpx.MockTransport(fixture)))


def ask(model, question='Fixture Vendor notice and active contract count?', history=None):
    return asyncio.run(model.answer([*(history or []), {'role': 'user', 'content': question}]))


def test_notebook_workflow_calls_both_once_reranks_and_merges_with_valid_sources():
    fixture = Fixture()
    answer, output = ask(agent(fixture))
    assert output['workflow'] == 'deep_agent_v1'
    assert output['source_status'] == {'genie': 'completed', 'contracts': 'completed'}
    assert '[G1]' in answer and '[D1]' in answer and 'private internal reasoning' not in json.dumps(output) + answer
    assert output['query_metadata']['vendor_name'] == ['Fixture Vendor']
    paths = [c[0] for c in fixture.calls]
    assert sum('/genie/' in p for p in paths) == 1
    assert sum(p.endswith('/query') for p in paths) == 1
    query = next(body for path, body, _ in fixture.calls if path.endswith('/query'))
    assert query['num_results'] == 20 and query['query_type'] == 'HYBRID'
    assert query['reranker']['parameters']['columns_to_rerank'] == ['contextualized_text', 'document_title', 'section_title']
    assert 'Search metadata:' in query['query_text']
    assert all(token == 'Bearer user-token' for _, _, token in fixture.calls)
    models = [body['model'] for path, body, _ in fixture.calls if '/ai-gateway/' in path]
    assert 'system.ai.gte-large-en' in models and 'system.ai.meta-llama-3-3-70b-instruct' in models
    assert output['references'][0]['sql'] == 'SELECT count(*) FROM catalog.schema.contracts'
    assert output['references'][1]['used_in_answer'] is True
    assert output['references'][2]['used_in_answer'] is False


def test_optional_serving_transport_keeps_the_same_new_workflow():
    fixture = Fixture()
    model = agent(fixture)
    model.settings = replace(model.settings, model_api='serving')
    answer, _ = ask(model)
    assert '[D1]' in answer
    assert not any('/ai-gateway/' in path for path, _, _ in fixture.calls)
    assert any('/serving-endpoints/fixture-answer/' in path for path, _, _ in fixture.calls)


def test_genie_runs_while_metadata_and_document_search_execute():
    started = asyncio.Event()
    fixture = Fixture()
    async def handler(request):
        if '/genie/' in request.url.path:
            await asyncio.wait_for(started.wait(), 1)
        if request.url.path.endswith('/query'):
            started.set()
        return fixture(request)
    ask(agent(handler))
    assert started.is_set()


@pytest.mark.parametrize('failed,final', [
    ('genie', 'The notice period is 30 days [D1].'),
    ('contracts', 'There are 12 active contracts [G1].'),
])
def test_partial_failures_keep_citations_and_explicit_missing_source(failed, final):
    fixture = Fixture(failed, final)
    answer, output = ask(agent(fixture))
    assert 'unavailable' in answer and 'could not be checked' in answer
    assert output['source_status'][failed] == 'error'
    assert not any(s['kind'] == ('genie' if failed == 'genie' else 'document') for s in output['references'])


def test_both_failed_never_calls_answer_model_to_guess():
    fixture = Fixture('both')
    with pytest.raises(RuntimeError, match='Neither'):
        ask(agent(fixture))
    assert not any(body.get('messages', [{}])[0].get('content', '').startswith(MERGE_PROMPT) for _, body, _ in fixture.calls)


def test_metadata_failure_uses_original_question_without_fabricated_hints():
    _, output = ask(agent(Fixture('metadata')))
    assert output['query_metadata'] == {} and output['metadata_status'] == 'unavailable'
    assert 'Search metadata:' not in output['rag_query']


def test_followup_uses_persisted_context_but_only_latest_requested_fields():
    fixture = Fixture(final='The expiry date is unspecified in the retrieved information [D1].')
    _, output = ask(agent(fixture), 'Also the end date?', [
        {'role': 'user', 'content': 'What is the notice period for Fixture Vendor?'},
        {'role': 'assistant', 'content': 'The notice period is 30 days [D1].'},
    ])
    assert output['is_follow_up'] is True
    assert output['query_metadata']['requested_fields'] == ['expiry_date']
    genie = next(body for path, body, _ in fixture.calls if '/genie/' in path)
    assert genie['input'][0]['content'][0]['text'] == 'What is the expiry date of the Fixture Vendor agreement?'
    assert 'conversation_id' not in genie


@pytest.mark.parametrize('bad_answer', ['Count is 12 [G99].', 'Count is 12.', '<sup>1</sup>Count is 12 [G1].'])
def test_invalid_citations_fail_after_one_repair_without_requerying_sources(bad_answer):
    fixture = Fixture(final=bad_answer)
    with pytest.raises(ValueError):
        ask(agent(fixture))
    assert sum('/genie/' in path for path, _, _ in fixture.calls) == 1
    assert sum(path.endswith('/query') for path, _, _ in fixture.calls) == 1
    assert sum(body.get('messages', [{}])[0].get('content', '').startswith(MERGE_PROMPT) for _, body, _ in fixture.calls) == 2


def test_no_sources_never_invokes_synthesis():
    fixture = Fixture()
    def handler(request):
        if '/genie/' in request.url.path:
            return httpx.Response(403)
        if request.url.path.endswith('/query'):
            return httpx.Response(200, json={'result': {'data_array': []}})
        return fixture(request)
    answer, output = ask(agent(handler))
    assert 'could not find supporting information' in answer
    assert output['references'] == []
    assert not any(body.get('messages', [{}])[0].get('content', '').startswith(MERGE_PROMPT) for _, body, _ in fixture.calls)


def test_metadata_validation_keeps_false_zero_and_drops_hallucinated_subjects_dates():
    metadata = clean_metadata({'vendor_name': ['Invented'], 'contract_reference': ['FAKE_12345'],
                               'expiry_date_to': '2029-01-01', 'requested_fields': ['expiry_date', 'secret'],
                               'auto_renewal': False, 'min_contract_value': 0, 'max_contract_value': float('inf')},
                              'What is the expiry date?')
    assert metadata == {'auto_renewal': False, 'min_contract_value': 0, 'requested_fields': ['expiry_date']}


def test_sources_are_safe_and_missing_pages_are_not_invented():
    host = 'https://workspace.example.test'
    for value in ['javascript:alert(1)', 'https://evil.example/test', 'https://user:secret@workspace.example.test/file', 'https://workspace.example.test:4430/file']:
        assert safe_source_url(value, host) is None
    records = [{'document_title': 'Agreement', 'contextualized_text': 'Text', 'page_start': None,
                'citation': '[Agreement](javascript:alert(1))'}]
    sources, _ = document_sources(records, host)
    assert sources[0]['url'] is None and sources[0]['pages'] == ''
    with pytest.raises(ValueError):
        check_citations('Fact [D99]', sources)


def test_actual_api_uses_new_workflow_user_token_and_reloads_private_sources(setup, monkeypatch):
    _, _, factory, _, _ = setup
    fixture = Fixture()
    config = agent(fixture).settings
    async def identity(request):
        name = request.headers.get('x-test-user', 'alice')
        return SimpleNamespace(id=name, name=name, email=name+'@example.test', token=name+'-token')
    monkeypatch.setattr('server.app.DatabricksHTTP', lambda settings, token: DatabricksHTTP(
        settings, token=token, transport=httpx.MockTransport(fixture)))
    app = create_app(config, factory, testing=True, identity_resolver=identity)
    with TestClient(app, headers={'x-test-user': 'alice', 'x-atlas-request': '1'}) as alice:
        cid = create(alice)
        response = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Fixture Vendor notice and count?'})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [event['type'] for event in events] == ['delta', 'done']
        saved = events[-1]['assistant']
        assert saved['tools'] == [] and saved['custom_outputs']['workflow'] == 'deep_agent_v1'
        assert alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1] == saved
        assert all(token == 'Bearer alice-token' for _, _, token in fixture.calls)
        assert alice.get('/api/bootstrap', headers={'x-test-user': 'bob'}).json()['conversations'] == []
