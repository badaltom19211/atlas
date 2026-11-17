"""Genie display metadata: real SQL rows, request isolation and history persistence."""
import json

from .agent_runtime import RequestRuntime, ScopedTracing, bind_runtime
from .config import Settings
from .genie_results import parse_table, capture_genie_results, bounded_results
from .notebook_output import format_result
from .test_app import setup, create

TABLE = '| Status | Count |\n| :--- | ---: |\n| Active | 12 |\n| Expired | 3 |'
RESULT = ('Genie answer:\nA narrative is not chart data.\n\nGenie query results:\n[G1] Genie query: Contracts by status\n' + TABLE,
          [{'id': 'G1', 'title': 'Contracts by status', 'sql': 'SELECT status, count(*) FROM contracts GROUP BY status'}])
REF = {'id': 'G1', 'kind': 'genie', 'used_in_answer': True}


def test_only_sql_result_blocks_supply_rows_and_original_values_are_preserved():
    result = capture_genie_results(RESULT)
    assert result == [{'id': 'G1', 'title': 'Contracts by status', 'columns': ['Status', 'Count'], 'rows': [['Active', '12'], ['Expired', '3']], 'truncated': False}]
    assert capture_genie_results(('Genie answer:\n' + TABLE, RESULT[1])) == []
    assert capture_genie_results((RESULT[0], [{'id': 'G1'}])) == []
    assert parse_table('| Vendor | Amount |\n|---|---|\n| Acme \\| UK | $1,200.50 |')['rows'] == [['Acme | UK', '$1,200.50']]


def test_multiple_queries_nulls_empty_and_partial_results():
    text = RESULT[0] + '\n\n[G2] Genie query: Empty\n| Status |\n| --- |'
    result = capture_genie_results((text, RESULT[1] + [{'id': 'G2', 'sql': 'SELECT status FROM empty'}]))
    assert len(result) == 2 and result[1]['rows'] == []
    assert parse_table(TABLE + '\n| Unknown | null |')['rows'][-1] == ['Unknown', 'null']
    assert parse_table(TABLE + '\n| ... | ... |')['truncated']
    assert parse_table(TABLE + '\nShowing first 2 of 30 rows')['truncated']
    assert parse_table(TABLE + '\n| malformed |')['truncated']
    assert parse_table('No result available.') is None
    many = '|Name|Count|\n|---|---|\n' + '\n'.join(f'|Vendor {i}|{i}|' for i in range(201))
    assert len(parse_table(many)['rows']) == 200 and parse_table(many)['truncated']


def test_capture_is_scoped_and_does_not_change_notebook_tool_return():
    trace = ScopedTracing()
    @trace.trace(name='genie_query', span_type='TOOL')
    def query(): return RESULT
    alice = RequestRuntime(Settings(), 'alice-token', 'alice')
    bob = RequestRuntime(Settings(), 'bob-token', 'bob')
    with bind_runtime(alice):
        assert query() is RESULT
    assert alice.genie_results[0]['rows'][0] == ['Active', '12']
    assert bob.genie_results == []


def test_results_only_follow_cited_queries_and_fit_receipt_budget():
    data = capture_genie_results(RESULT)
    assert bounded_results(data, [{**REF, 'used_in_answer': False}], 20000) == []
    bounded = bounded_results([{**data[0], 'rows': [['X' * 1000, '1']] * 200}], [REF], 1000)
    assert len(json.dumps(bounded)) <= 1000 and bounded[0]['truncated']
    assert bounded_results(data, [REF], 0) == []
    runtime = RequestRuntime(Settings(), 'token', 'alice', genie_results=data)
    result = format_result({'answer': '12 active contracts', 'references': [REF]}, 'Count?', runtime)
    assert result['custom_outputs']['genie_results'] == data
    runtime.failures['genie'] = RuntimeError('not exposed')
    assert 'genie_results' not in format_result({'answer': 'Document answer', 'references': [REF]}, 'Count?', runtime)['custom_outputs']


def test_actual_notebook_tool_capture_with_tracing_disabled(monkeypatch):
    from . import deep_agent_v1 as notebook
    event = {'type': 'response.completed', 'response': {'conversation_id': 'chat', 'output': [
        {'type': 'function_call', 'call_id': 'q1', 'arguments': json.dumps({'sql': RESULT[1][0]['sql'], 'title': 'Contracts by status'})},
        {'type': 'function_call_output', 'call_id': 'q1', 'output': TABLE},
    ]}}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self, **kwargs): yield 'data: ' + json.dumps(event)
    monkeypatch.setattr(notebook.requests, 'post', lambda *args, **kwargs: Response())
    runtime = RequestRuntime(Settings(), 'token', 'alice')
    with bind_runtime(runtime):
        text, sources = notebook.query_genie('Count by status?')
    assert TABLE in text and sources[0]['id'] == 'G1'
    assert runtime.genie_results == capture_genie_results(RESULT)


def test_sql_results_persist_with_owned_messages_and_saved_responses(setup, monkeypatch):
    alice, bob, _, model, _ = setup
    cid = create(alice)
    data = capture_genie_results(RESULT)
    async def stream(*args):
        yield {'type': 'tool', 'tool': {'id': 'result', 'name': 'deep_contract_agent', 'status': 'completed', 'input': '{}',
               'output': json.dumps({'custom_outputs': {'sources': [], 'genie_results': data}})}}
        yield 'There are 12 active contracts.'
    monkeypatch.setattr(model, 'stream', stream)
    response = alice.post(f'/api/conversations/{cid}/messages', json={'content': 'Count by status?'})
    done = json.loads(response.text.splitlines()[-1])['assistant']
    assert done['custom_outputs']['genie_results'] == data
    assert alice.patch('/api/messages/' + done['id'], json={'feedback': None, 'saved': True}).status_code == 200
    loaded = alice.get('/api/bootstrap').json()['conversations'][0]['messages'][-1]
    assert loaded['custom_outputs']['genie_results'] == data and loaded['saved']
    assert bob.get('/api/bootstrap').json()['conversations'] == []
