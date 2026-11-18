"""Bounded source catalogs; citations are data, never executable HTML."""
import re
from collections import Counter
import posixpath
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .notebook_agent import page_number, pages

TAG = re.compile(r'\[\s*([GD]\d+(?:\s*[,;]\s*[GD]\d+)*)\s*\]')
TAG_RUN = re.compile(r'[ \t]*' + TAG.pattern + r'(?:[ \t]*(?:[,;]|and)?[ \t]*' + TAG.pattern + r')*')
FULLWIDTH_BRACKETS = str.maketrans({'【': '[', '】': ']', '［': '[', '］': ']'})


def normalize_citation_tags(answer):
    """GPT-OSS can emit wide brackets; normalize before validation and counting."""
    return (answer or '').translate(FULLWIDTH_BRACKETS)


# Contract PDFs are served by this app (GET PDF_ROUTE?path=...), because Catalog
# Explorer cannot open a single volume file ("directory not found") and the
# Files API forces a download that needs a bearer token.
PDF_ROUTE = '/api/documents/pdf'
PDF_ROOT = '/Volumes/dev_diamonddaas/raw/aia/AIAIMSG/MO_Contract_Mgt/Input/'


def safe_volume_pdf_path(value):
    """Return a normalized PDF path under PDF_ROOT, or None."""
    if not isinstance(value, str) or not value or len(value) > 1024 or re.search(r'[\x00-\x1f\x7f\\]', value):
        return None
    if re.search(r'%(?:2e|2f|5c|00)', value, re.I):
        return None
    if '..' in value.split('/'):
        return None
    path = posixpath.normpath(value)
    if not path.startswith(PDF_ROOT) or not path.lower().endswith('.pdf') or path == PDF_ROOT.rstrip('/'):
        return None
    return path


def pdf_link(path):
    path = safe_volume_pdf_path(path)
    return PDF_ROUTE + '?path=' + quote(path, safe='/') if path else None


def volume_pdf_link(link, filename=None):
    """Catalog Explorer link (volumePath = folder or file, '+' or %20) or a /Volumes
    path -> same-origin app PDF route. Returns None if no safe PDF path is found."""
    if not isinstance(link, str) or not link:
        return None
    if link.startswith(PDF_ROUTE + '?'):
        paths = [p for k, p in parse_qsl(urlsplit(link).query) if k == 'path']
        return pdf_link(paths[0]) if len(paths) == 1 else None
    if link.startswith('/Volumes/'):
        # This is a file path, not a form-encoded URL: preserve literal +, # and %.
        path = link
    else:
        try:
            paths = [p for k, p in parse_qsl(urlsplit(link).query, keep_blank_values=True) if k == 'volumePath']
        except ValueError:
            return None
        if len(paths) != 1:
            return None
        path = paths[0]
    if path.endswith('/') and isinstance(filename, str) and filename.strip():
        name = filename.strip()
        if '/' in name or '\\' in name or name in ('.', '..'):
            return None
        path += name
    return pdf_link(path)


def safe_source_url(value, host):
    if isinstance(value, str) and value.startswith(PDF_ROUTE + '?'):
        return volume_pdf_link(value)
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
    """Turn a known volume citation into the app PDF route, never guess a filename."""
    local = isinstance(value, str) and value.startswith(('/Volumes/', PDF_ROUTE + '?'))
    safe = value if local else safe_source_url(value, host)
    if not safe:
        return None
    route = volume_pdf_link(safe, filename if isinstance(filename, str) and filename.lower().endswith('.pdf') else None)
    if route:
        return route
    if local:
        return None
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
    answer = normalize_citation_tags(answer)
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
    answer = normalize_citation_tags(answer)
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
