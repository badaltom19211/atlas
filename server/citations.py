"""Bounded source catalogs; citations are data, never executable HTML."""
import re
from urllib.parse import urlsplit

from .notebook_agent import pages

TAG = re.compile(r'\[\s*([GD]\d+(?:\s*[,;]\s*[GD]\d+)*)\s*\]')


def safe_source_url(value, host):
    if not isinstance(value, str) or len(value) > 1024 or re.search(r'[\s<>"\\]', value):
        return None
    try:
        url, origin = urlsplit(value), urlsplit(host)
        if url.scheme == 'https' and url.hostname == origin.hostname and url.port == origin.port and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return None


def document_sources(records, host):
    sources, ids, excerpts = [], {}, []
    for record in records:
        citation = re.fullmatch(r'\[(.*?)\]\((.*)\)', record.get('citation') or '', re.DOTALL)
        title = str(record.get('document_title') or record.get('file_name') or 'Contract')[:240]
        section = str(record.get('section_title') or '')[:160]
        location = pages(record)
        url = safe_source_url(citation.group(2), host) if citation else None
        # Do not merge identical titles from different documents/links.
        key = (title, section, location, url, record.get('file_name'))
        if key not in ids:
            ids[key] = f'D{len(ids) + 1}'
            sources.append({'id': ids[key], 'kind': 'document',
                            'label': ' · '.join(x for x in (title, section, location) if x)[:300],
                            'url': url, 'pages': location})
        excerpts.append(f'[{ids[key]}] {title} | {section} | {location}\n{record["contextualized_text"]}')
    return sources, '\n\n---\n\n'.join(excerpts)


def check_citations(answer, sources):
    known = {source['id'] for source in sources}
    used = {identifier for match in TAG.finditer(answer) for identifier in re.findall(r'[GD]\d+', match[1])}
    if used - known:
        raise ValueError('The answer cited evidence that was not retrieved.')
    # Reject notebook HTML and model-created URLs. React constructs links from
    # the validated catalog, and facts retain their original [G#]/[D#] IDs.
    if re.search(r'<\s*/?\s*[a-zA-Z][^>]*>|\]\([^)]*\)|https?://', answer):
        raise ValueError('The answer must use catalog citation IDs, not HTML or URLs.')
    return used
