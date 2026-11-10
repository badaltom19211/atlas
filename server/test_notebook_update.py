import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from .citations import document_sources, prepare_source_display, without_model_sources
from .genie import GenieAgent, genie_evidence, has_result_rows
from .glossary import GlossaryEnricher, load_enricher
from .test_deep_agent import Fixture, agent, ask, genie_event
from .test_routed_agent import sse

HOST = 'https://workspace.example.test'
FOLDER = HOST + '/explore/data/volumes/catalog/schema/contracts?volumePath=%2FVolumes%2Fcatalog%2Fschema%2Fcontracts%2FInput%2F&o=123'


def record(**values):
    return {'document_title': 'Agreement', 'section_title': 'Termination', 'page_start': 4, 'page_end': 5,
            'contextualized_text': 'Notice is 30 days.', 'citation': f'[Vendor & Co - signed.pdf | p. 4]({FOLDER})', **values}


def test_document_file_links_use_real_filename_preserve_params_and_pages():
    sources, context = document_sources([record(), record(page_start=8, page_end=None)], HOST)
    assert len(sources) == 2 and sources[0]['document'] == 'Vendor & Co - signed.pdf'
    url = urlsplit(sources[0]['url'])
    assert parse_qs(url.query) == {'volumePath': ['/Volumes/catalog/schema/contracts/Input/Vendor & Co - signed.pdf'], 'o': ['123']}
    assert sources[0]['pages'] == 'p. 4-5' and sources[1]['pages'] == 'p. 8'
    assert '[D1]' in context and '[D2]' in context
    assert 'Vendor & Co · Termination' in sources[0]['label']


@pytest.mark.parametrize('filename', ['../secret.pdf', 'folder/file.pdf', 'folder\\file.pdf'])
def test_document_link_does_not_traverse_a_volume_path(filename):
    sources, _ = document_sources([record(file_name=filename)], HOST)
    assert sources[0]['url'] == FOLDER


def test_document_link_keeps_existing_file_and_never_guesses_missing_filename():
    direct = HOST + '/explore/data/volumes/catalog/schema/contracts?volumePath=%2FVolumes%2Fcatalog%2Fschema%2Fcontracts%2FInput%2Fknown.pdf'
    for url in (direct, FOLDER):
        sources, _ = document_sources([record(citation=f'[Agreement]({url})')], HOST)
        assert sources[0]['url'] == url
    sources, _ = document_sources([record(citation='[doc.pdf](https://evil.example/file)')], HOST)
    assert sources[0]['url'] is None


def test_missing_pages_and_identical_titles_do_not_merge_distinct_files():
    sources, _ = document_sources([record(file_name='one.pdf', page_start=None, page_end=None),
                                   record(file_name='two.pdf', page_start=None, page_end=None)], HOST)
    assert len(sources) == 2 and sources[0]['pages'] == ''
    assert sources[0]['url'] != sources[1]['url']


def test_citation_tags_are_hidden_but_usage_and_paragraphs_are_preserved():
    sources = [{'id': name} for name in ('G1', 'D1', 'D2', 'D3')]
    answer = 'Count 12 [G1].\n\nNotice 30 days [D1], [D2] and [D3]. More detail [D1].'
    body = prepare_source_display(answer, sources)
    assert body == 'Count 12.\n\nNotice 30 days. More detail.'
    assert sources[1]['citation_count'] == 2 and sources[1]['citation_order'] == 1
    with pytest.raises(ValueError):
        prepare_source_display('Invented [D99].', sources)
    assert without_model_sources('A fact [D1].\n\n**Sources**\n[D2] unrelated') == 'A fact [D1].'


@pytest.mark.parametrize('table,expected', [
    ('Title\n| count |\n| --- |\n| 0 |', True),
    ('| name |\n| :---: |\n| Vendor |', True),
    ('| name |\n| --- |\n\nNo rows returned.', False),
    ('No rows returned.', False), ('Error: denied', False),
])
def test_only_actual_result_rows_qualify_for_sql_sources(table, expected):
    assert has_result_rows(table) is expected


def test_genie_pairs_query_output_ids_and_keeps_empty_results_marked():
    event = genie_event()
    items = event['response']['output']
    result = items[-1]
    result['id'] = result.pop('call_id') + '_output'
    model = agent(lambda request: sse(event))
    _, detail = asyncio.run(GenieAgent(model.settings, model.http).answer('Count?', include_evidence=True))
    assert detail['references'][0]['sql'].startswith('SELECT count(*)')
    assert detail['references'][0]['has_rows'] is True
    result['output'] = '| name |\n| --- |'
    sources, _ = genie_evidence(items, 'No matching rows.', model.settings, 'c')
    assert sources[0]['has_rows'] is False


def test_genie_never_substitutes_chat_link_for_missing_or_failed_sql():
    model = agent(Fixture())
    for result in ('', '{"error":"private detail"}'):
        items = genie_event()['response']['output']
        items[-1]['output'] = result
        sources, evidence = genie_evidence(items, 'Unsupported count 999.', model.settings, 'c')
        assert sources == [] and '999' not in evidence and 'private detail' not in evidence


def test_genie_can_return_sql_results_without_a_natural_language_summary():
    event = genie_event()
    event['response']['output'] = [item for item in event['response']['output'] if item['type'] != 'message']
    model = agent(lambda request: sse(event))
    _, detail = asyncio.run(GenieAgent(model.settings, model.http).answer('Count?', include_evidence=True))
    assert detail['references'][0]['has_rows'] is True


def test_updated_index_query_needs_only_notebooks_seven_columns():
    fixture = Fixture()
    def handler(request):
        response = fixture(request)
        if request.url.path.endswith('/query'):
            data = response.json()
            columns = [c['name'] for c in data['manifest']['columns']]
            selected = [columns.index(name) for name in json.loads(request.content)['columns']]
            data['manifest']['columns'] = [data['manifest']['columns'][i] for i in selected]
            data['result']['data_array'] = [[row[i] for i in selected] for row in data['result']['data_array']]
            import httpx
            return httpx.Response(200, json=data)
        return response
    answer, output = ask(agent(handler))
    assert '30 days' in answer and output['source_status']['contracts'] == 'completed'


def test_glossary_is_optional_and_invalid_enrichment_never_blocks_the_question(tmp_path):
    assert load_enricher('').question('Question')[1]['status'] == 'disabled'
    assert load_enricher(str(tmp_path)).question('Question') == ('Question', {'status': 'unavailable', 'terms': []})
    enricher = GlossaryEnricher('ready', [], lambda query, data: {'has_matches': False})
    assert enricher.question('Question')[1]['status'] == 'no_matches'
    enricher = GlossaryEnricher('ready', [], lambda query, data: {'has_matches': True})
    assert enricher.question('Question') == ('Question', {'status': 'unavailable', 'terms': []})


def test_shared_glossary_modules_load_without_bundling_company_data(tmp_path):
    (tmp_path / 'business_glossary.json').write_text('[{"business_term":"enterprise license"}]', encoding='utf-8')
    (tmp_path / 'glossary_loader.py').write_text('import json\ndef load_glossary(path):\n    return json.load(open(path))\n', encoding='utf-8')
    (tmp_path / 'enrichment.py').write_text('def enrich_question(query, glossary):\n    return {"has_matches":True,"primary_matches":glossary,"glossary_context":{"primary":glossary,"related":[]}}\n', encoding='utf-8')
    question, metadata = load_enricher(str(tmp_path)).question('Which enterprise licenses?')
    assert 'Business glossary context' in question and metadata['terms'] == ['enterprise license']


def test_glossary_reaches_both_sources_but_cannot_invent_metadata_or_source_ids():
    fixture = Fixture()
    model = agent(fixture)
    model.glossary = GlossaryEnricher('ready', [], lambda query, data: {
        'has_matches': True, 'primary_matches': [{'business_term': 'enterprise license'}],
        'glossary_context': {'primary': [{'consolidated_definition': 'DEFINITION_FIXTURE'}], 'related': []}})
    _, output = ask(model, 'Which enterprise licenses?')
    genie = next(body for path, body, _ in fixture.calls if '/genie/' in path)
    assert 'DEFINITION_FIXTURE' in genie['input'][0]['content'][0]['text']
    query = next(body for path, body, _ in fixture.calls if path.endswith('/query'))
    assert 'DEFINITION_FIXTURE' in query['query_text']
    metadata = next(body for _, body, _ in fixture.calls if body.get('messages', [{}])[0].get('content', '').startswith('Extract contract search metadata'))
    assert 'DEFINITION_FIXTURE' not in metadata['messages'][1]['content']
    assert output['glossary_status'] == 'completed' and output['glossary_terms'] == ['enterprise license']
    assert all(s['kind'] in ('document', 'genie') for s in output['references'])
