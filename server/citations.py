"""Bounded source catalogs; citations are data, never executable HTML."""
import re
from collections import Counter
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .notebook_agent import page_number, pages

TAG = re.compile(r'\[\s*([GD]\d+(?:\s*[,;]\s*[GD]\d+)*)\s*\]')
TAG_RUN = re.compile(r'[ \t]*' + TAG.pattern + r'(?:[ \t]*(?:[,;]|and)?[ \t]*' + TAG.pattern + r')*')


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


def document_file_url(value, filename, host):
    """Turn a known volume-folder citation into a file link, never guess a filename."""
    safe = safe_source_url(value, host)
    if not safe or not isinstance(filename, str) or not filename.lower().endswith('.pdf'):
        return safe
    if any(char in filename for char in ('/', '\\', '\x00')) or filename in ('.', '..'):
        return safe
    url = urlsplit(safe)
    params = parse_qsl(url.query, keep_blank_values=True)
    paths = [path for key, path in params if key == 'volumePath']
    if len(paths) != 1 or not paths[0].startswith('/Volumes/') or not paths[0].endswith('/'):
        return safe
    params = [(key, path + filename if key == 'volumePath' else path) for key, path in params]
    return safe_source_url(urlunsplit(url._replace(query=urlencode(params, quote_via=quote))), host) or safe


def short_document(value):
    name = re.sub(r'\.pdf$', '', value, flags=re.I)
    return re.sub(r'(\s*-\s*signed)+$', '', name, flags=re.I).strip(' -_')


def document_sources(records, host):
    sources, ids, excerpts = [], {}, []
    for record in records:
        citation = re.fullmatch(r'\[(.*?)\]\((.*)\)', record.get('citation') or '', re.DOTALL)
        citation_name = citation.group(1).split(' | ')[0].strip() if citation else ''
        candidates = [record.get('file_name'), citation_name, record.get('document_title')]
        filename = next((name.strip() for name in candidates if isinstance(name, str) and name.strip().lower().endswith('.pdf')), '')
        document = str(filename or record.get('document_title') or citation_name or 'Contract')[:512]
        title = short_document(document)[:240]
        section = str(record.get('section_title') or '')[:160]
        location = pages(record)
        url = document_file_url(citation.group(2), filename, host) if citation else None
        # Do not merge identical titles from different documents/links.
        key = (document, section, location, url, record.get('file_name'))
        if key not in ids:
            ids[key] = f'D{len(ids) + 1}'
            sources.append({'id': ids[key], 'kind': 'document',
                            'label': ' · '.join(x for x in (title, section, location) if x)[:300],
                            'url': url, 'pages': location, 'document': document, 'section': section,
                            'page_start': page_number(record.get('page_start')),
                            'page_end': page_number(record.get('page_end'))})
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


def without_model_sources(answer):
    # The application owns the source list. Do not count a model's appended list
    # as citations supporting the answer itself.
    return re.split(r'(?im)^\s*(?:#{1,6}[ \t]+)?(?:\*\*)?(?:Sources?|References?)(?:\*\*)?[ \t]*:?[ \t]*(?:\n|$)', answer, maxsplit=1)[0].rstrip()


def prepare_source_display(answer, sources):
    """Keep provenance in metadata while showing clean prose, as in the new notebook."""
    used = check_citations(answer, sources)
    ids = [identifier for match in TAG.finditer(answer) for identifier in re.findall(r'[GD]\d+', match[1])]
    counts = Counter(ids)
    for source in sources:
        source['used_in_answer'] = source['id'] in used
        source['citation_count'] = counts[source['id']]
        source['citation_order'] = ids.index(source['id']) if source['id'] in used else len(ids)
    body = TAG_RUN.sub('', answer)
    body = re.sub(r'[ \t]+([.,;:!?)])', r'\1', body)
    return re.sub(r'[ \t]{2,}', ' ', body).strip()
