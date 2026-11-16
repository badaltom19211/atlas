from contextlib import contextmanager
from types import SimpleNamespace
import json

import pytest

from poc.micro_app import koantek_agent as agent
from server.databricks_errors import NotebookCallError


def test_project_results_use_manifest_order_and_bound_excerpts():
    result = {'manifest': {'columns': [{'name': 'pk'}, {'name': 'full_text'}, {'name': 'score'}]},
              'result': {'data_array': [['sample-project', 'x' * 13000, 0.9]]}}
    assert agent.project_records(result) == [{'id': 'D1', 'document': 'sample-project', 'text': 'x' * 12000}]


def test_project_index_mismatch_does_not_invent_documents():
    with pytest.raises(ValueError, match='full_text and pk'):
        agent.project_records({'manifest': {'columns': []}, 'result': {'data_array': []}})


@pytest.fixture
def runtime(monkeypatch):
    state = SimpleNamespace(selected=['genie', 'projects'], answer='Seven categories [G1]. A documented project [D1].',
                            understanding=[])
    settings = SimpleNamespace(agent_model='fixture-model')
    def generate(**kwargs):
        state.model_request = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=state.answer))])
    current = SimpleNamespace(host='https://workspace.example.test', token='fixture-token', settings=settings,
                              check=lambda: None,
                              oai=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=generate))))
    @contextmanager
    def open_runtime(*args, **kwargs):
        yield current
    def understand(question, previous_question, previous_answer):
        state.understanding.append((question, previous_question, previous_answer))
        return {'standalone_question': 'Resolved fixture question', 'follow_up': bool(previous_question)}
    monkeypatch.setattr(agent, 'open_runtime', open_runtime)
    monkeypatch.setattr(agent, 'understand_query', understand)
    monkeypatch.setattr(agent, 'choose_tools', lambda _: state.selected)
    monkeypatch.setattr(agent, 'query_genie', lambda _: ('7 categories', [{'id': 'G1', 'sql': 'SELECT 7', 'has_rows': True}]))
    monkeypatch.setattr(agent, 'retrieve_projects', lambda *_: ('A documented project',
                        [{'id': 'D1', 'kind': 'document', 'label': 'Sample', 'document': 'Sample',
                          'page_start': None, 'page_end': None, 'url': None}]))
    state.payload = {'token': 'fixture-token', 'user_id': 'fixture-user', 'question': 'Fixture question', 'previous': None}
    state.settings = settings
    return state


def test_mixed_sources_remain_distinct_and_pages_are_not_invented(runtime):
    result = agent.run_chat(runtime.payload, runtime.settings)
    refs = result['custom_outputs']['references']
    assert [source['kind'] for source in refs] == ['genie', 'document']
    assert refs[0]['sql'] == 'SELECT 7' and refs[1]['page_start'] is None
    assert all(source['used_in_answer'] for source in refs)
    assert '[G1]' not in result['answer']
    assert result['custom_outputs']['notebook_query'] == 'Resolved fixture question'
    assert 'not a complete inventory' in result['answer']


def test_failed_genie_is_explicit_and_has_no_fabricated_sql(runtime, monkeypatch):
    monkeypatch.setattr(agent, 'query_genie', lambda _: (_ for _ in ()).throw(RuntimeError('fixture failure')))
    runtime.answer = 'A documented project [D1].'
    result = agent.run_chat(runtime.payload, runtime.settings)
    assert 'Bike Store Genie is unavailable' in result['answer']
    assert [r['id'] for r in result['custom_outputs']['references']] == ['D1']
    assert result['custom_outputs']['failed_tools'] == ['genie']
    evidence = json.loads(runtime.model_request['messages'][1]['content'])
    assert evidence['unavailable_sources'] == ['genie']


def test_no_source_success_raises_instead_of_generating(runtime, monkeypatch):
    runtime.selected = ['projects']
    monkeypatch.setattr(agent, 'retrieve_projects', lambda *_: (_ for _ in ()).throw(RuntimeError('fixture failure')))
    with pytest.raises(NotebookCallError):
        agent.run_chat(runtime.payload, runtime.settings)
    assert not hasattr(runtime, 'model_request')


def test_unknown_citation_is_rejected(runtime):
    runtime.answer = 'An invented reference [D99].'
    with pytest.raises(ValueError, match='not retrieved'):
        agent.run_chat(runtime.payload, runtime.settings)


def test_followup_uses_explicit_previous_turn(runtime):
    runtime.payload['previous'] = {'query': 'Which project?', 'answer': 'Sample project.'}
    result = agent.run_chat(runtime.payload, runtime.settings)
    assert runtime.understanding == [('Fixture question', 'Which project?', 'Sample project.')]
    assert result['custom_outputs']['is_follow_up'] is True


def test_greeting_does_not_claim_data_or_call_answer_model(runtime):
    runtime.selected = []
    result = agent.run_chat(runtime.payload, runtime.settings)
    assert result['custom_outputs']['references'] == []
    assert not hasattr(runtime, 'model_request')
