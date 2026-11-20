"""Source modes from notebook v7, configured through the shared deployment settings."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

import contract_agent_config as defaults
from .agent_runtime import RequestRuntime, bind_runtime, current_runtime
from .config import Settings
from .databricks_errors import NotebookCallError
from .notebook_output import format_result
from .test_config import configured
from .test_direct_notebook import notebook


@pytest.mark.parametrize('genie,rag', [(True, True), (True, False), (False, True)])
@pytest.mark.parametrize('followup', [False, True])
def test_source_mode_reaches_tool_and_owned_result(notebook, monkeypatch, genie, rag, followup):
    calls, tool_outputs = [], []
    def query_genie(query):
        calls.append(('genie', current_runtime().user_id))
        assert genie, 'Disabled Genie was called'
        return '12 contracts [G1]', [{'id': 'G1', 'sql': 'SELECT count(*) FROM contracts'}]
    def query_rag(query):
        calls.append(('documents', current_runtime().user_id))
        assert rag, 'Disabled RAG was called'
        return '30 days [D1]', [{'id': 'D1', 'document': 'Terms.pdf', 'page': 4}]
    monkeypatch.setattr(notebook, 'query_genie', query_genie)
    monkeypatch.setattr(notebook, 'query_rag', query_rag)
    def build(**kwargs):
        assert kwargs == {'use_genie': genie, 'use_rag': rag}
        def invoke(data, **kwargs):
            tool_outputs.append(notebook.search_contracts.invoke({'query': 'Acme fees?'}))
            answer = ' '.join((['12 contracts [G1].'] if genie else []) + (['30 days [D1].'] if rag else []))
            return {'messages': [SimpleNamespace(content=answer)]}
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(notebook, 'build_contract_agent', build)
    history = [{'role': 'user', 'content': 'Acme term?'},
               {'role': 'assistant', 'content': 'Two years.', 'in_scope': True}] if followup else []
    result = notebook.contract_assistant('And fees?' if followup else 'Acme fees?', token='fixture', history=history,
        settings=Settings(use_genie=genie, use_rag=rag), user_id='alice', session_id='alice:one')
    expected = ({'genie'} if genie else set()) | ({'documents'} if rag else set())
    assert {name for name, owner in calls} == expected
    assert all(owner == 'alice' for _, owner in calls)
    assert ('RESULT SET A' in tool_outputs[0]) is genie
    assert ('RESULT SET B' in tool_outputs[0]) is rag
    output = result['custom_outputs']
    assert output['use_genie'] is genie and output['use_rag'] is rag
    assert output['is_follow_up'] is followup
    assert {r['id'][0] for r in output['references']} == ({'G'} if genie else set()) | ({'D'} if rag else set())


def test_per_call_override_and_request_agent_cache_are_isolated(notebook, monkeypatch):
    built = []
    def build(**kwargs):
        item = SimpleNamespace(owner=current_runtime().user_id, flags=kwargs)
        built.append(item)
        return item
    monkeypatch.setattr(notebook, 'build_contract_agent', build)
    settings = Settings(use_genie=True, use_rag=False)
    for owner in ('alice', 'bob'):
        with bind_runtime(RequestRuntime(settings, 'fixture', owner)):
            first = notebook.get_contract_agent()
            assert notebook.get_contract_agent() is first
            override = notebook.get_contract_agent(False, True)
            assert override is not first
            assert override.owner == first.owner == owner
    assert len(built) == 4 and built[0] is not built[2]


def test_both_sources_disabled_stops_before_classification(notebook, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail('Invalid source mode reached the model')
    monkeypatch.setattr(notebook, 'understand_query', forbidden)
    with pytest.raises(ValueError, match='At least one source'):
        notebook.chat('Hi', token='fixture', history=[], settings=Settings(), user_id='alice', session_id='one',
                      use_genie=False, use_rag=False)


def test_prompts_and_request_tuning_reach_models_and_retrieval(monkeypatch):
    from . import deep_agent_v1 as nb
    calls, agents, searches = [], [], []
    settings = Settings(use_genie=False, use_rag=True, agent_temperature=.2, rag_temperature=.3,
        json_temperature=.4, rag_max_tokens=1700, json_max_tokens=700, rag_top_k=7, rag_query_type='ANN')
    runtime = RequestRuntime(settings, 'fixture-token', 'alice')
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    runtime.oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    runtime.vs_index = SimpleNamespace(similarity_search=lambda **kwargs: searches.append(kwargs) or
                                     {'manifest': {'columns': []}, 'result': {'data_array': []}})
    monkeypatch.setattr(nb, 'embed_query', lambda query: [.1])
    monkeypatch.setattr(nb, 'ChatOpenAI', lambda **kwargs: calls.append(kwargs) or 'llm')
    monkeypatch.setattr(nb, 'create_deep_agent', lambda **kwargs: agents.append(kwargs) or 'agent')
    with bind_runtime(runtime):
        nb._llm_json('system', 'question')
        nb.generate_answer([])
        nb.build_contract_agent()
        nb.retrieve('question')
    assert [(c['temperature'], c.get('max_tokens')) for c in calls] == [(.4, 700), (.3, 1700), (.2, None)]
    assert agents[0]['system_prompt'] == nb.build_pipeline_prompt(False, True)
    assert '[D1]' in agents[0]['system_prompt'] and '[G1]' not in agents[0]['system_prompt']
    assert nb.build_pipeline_prompt(True, True) == nb.PIPELINE_PROMPT
    assert '[G1]' in nb.build_pipeline_prompt(True, False) and '[D1]' not in nb.build_pipeline_prompt(True, False)
    assert searches[0]['num_results'] == 7 and searches[0]['query_type'] == 'ANN'
    assert searches[0]['columns'] == list(settings.rag_columns)


@pytest.mark.parametrize('genie,stage', [(True, 'genie'), (False, 'documents')])
def test_only_enabled_source_failure_is_an_error(genie, stage):
    runtime = RequestRuntime(Settings(use_genie=genie, use_rag=not genie), 'fixture', 'alice')
    runtime.failures[stage] = NotebookCallError(stage, 403)
    with pytest.raises(NotebookCallError):
        format_result({'answer': 'No facts'}, 'Question', runtime)


def test_single_source_config_does_not_require_disabled_resource():
    settings = replace(configured('https://workspace.example.test'), agent_workflow='notebook', model_api='gateway')
    replace(settings, use_genie=False, genie_agent_id='').validate()
    replace(settings, use_rag=False, contract_index='', embedding_model='').validate()
    with pytest.raises(RuntimeError, match='At least one'):
        replace(settings, use_genie=False, use_rag=False).validate()


def test_shared_defaults_and_explicit_env_overrides(monkeypatch):
    for name in ('DATABRICKS_CONTRACT_INDEX', 'DATABRICKS_VECTOR_SEARCH_ENDPOINT', 'ATLAS_GENIE_TIMEOUT_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.contract_index == defaults.VS_INDEX
    assert settings.vector_search_endpoint == defaults.VS_ENDPOINT
    assert settings.genie_timeout_seconds == defaults.GENIE_TIMEOUT_S == 300
    assert not any(hasattr(defaults, name) for name in ('TOKEN', 'w', 'HOST', 'USER'))
    monkeypatch.setenv('DATABRICKS_CONTRACT_INDEX', 'other.schema.index')
    monkeypatch.setenv('ATLAS_USE_RAG', 'false')
    assert Settings().contract_index == 'other.schema.index' and Settings().use_rag is False
    monkeypatch.setenv('ATLAS_USE_RAG', 'typo')
    with pytest.raises(RuntimeError, match='true or false'):
        Settings()
