"""Normalize notebook references into the existing React/Lakebase response contract."""
import json
from .notebook_agent import page_number
from .citations import safe_source_url
from .agent_runtime import DisabledTracing


def normalize_sources(sources, host):
    references = []
    if len(sources) > 64:
        raise ValueError('Too many sources.')
    for source in sources:
        sid = source['id']
        kind = 'genie' if sid.startswith('G') else 'document'
        item = {'id': sid, 'kind': kind, 'label': str(source.get('label', sid))[:300],
                'url': safe_source_url(source.get('link'), host)}
        if kind == 'genie':
            sql = source.get('sql') or ''
            item.update(sql=sql[:16000], sql_truncated=len(sql) > 16000,
                        has_rows=bool(source.get('has_rows', False)))
        else:
            item.update(document=str(source.get('document') or item['label'])[:512],
                        page_start=page_number(source.get('page')), page_end=page_number(source.get('page')))
        references.append(item)
    return references


def format_result(result, question, runtime):
    if len(runtime.failures) == 2:
        raise next(iter(runtime.failures.values()))
    refs = result.get('references', [])
    answer = result['answer'].strip() or 'I could not find supporting information for this question in the contracts.'
    for stage in runtime.failures:
        answer += '\n\n' + ('Structured contract lookup' if stage == 'genie' else 'Contract document search') + ' is unavailable; those facts could not be checked.'
    output = {'sources': [], 'references': refs, 'source_display': 'grouped',
              'workflow': 'notebook_chat', 'is_follow_up': bool(result.get('is_follow_up')),
              'notebook_query': str(result.get('agent_query') or question)[:16000],
              'query_metadata': result.get('metadata') or {}, 'rag_query': (result.get('rag_query') or '')[:16000],
              'glossary_terms': result.get('glossary_terms', [])[:10],
              'glossary_status': getattr(runtime.glossary, 'status', 'disabled'),
              'citation_status': 'reported' if any(r.get('used_in_answer') for r in refs) else 'not_applicable',
              'tracing': 'disabled' if isinstance(runtime.tracing, DisabledTracing) else 'configured'}
    if len(json.dumps({'custom_outputs': output}, ensure_ascii=False, allow_nan=False)) > 63000 or len(answer) > 100000:
        raise ValueError('Notebook result exceeds storage limits.')
    return {'answer': answer, 'custom_outputs': output}
