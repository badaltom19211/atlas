"""Display data from actual Genie SQL results, without changing notebook reasoning."""
import json
import re

MAX_ROWS = 200
MAX_COLUMNS = 32


def _cells(line):
    line = line.strip().removeprefix('|')
    if line.endswith('|') and not line.endswith('\\|'):
        line = line[:-1]
    return [cell.strip().replace(r'\|', '|') for cell in re.split(r'(?<!\\)\|', line)]


def parse_table(text):
    """Keep exact display values; malformed/partial results must not become charts."""
    if not isinstance(text, str) or len(text) > 500000:
        return None
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if '|' not in lines[index - 1] or '|' not in lines[index]:
            continue
        separators = _cells(lines[index])
        if not separators or not all(re.fullmatch(r':?-{3,}:?', cell) for cell in separators):
            continue
        columns = _cells(lines[index - 1])
        if not 1 <= len(columns) <= MAX_COLUMNS or len(columns) != len(separators) or not all(columns):
            continue
        rows, truncated = [], False
        for line in lines[index + 1:]:
            if not line.strip() or '|' not in line:
                break
            cells = _cells(line)
            if len(cells) != len(columns) or any(cell in ('...', '…') for cell in cells):
                truncated = True
                break
            if len(rows) < MAX_ROWS:
                rows.append(cells)
            else:
                truncated = True
        # Provider notices are retained as a partial-result flag, never a fake data row.
        if re.search(r'(?i)\btruncated\b|\bshowing (?:only |the )?(?:first |top )?\d+|\b\d+ more rows\b', text):
            truncated = True
        return {'columns': columns, 'rows': rows, 'truncated': truncated}
    return None


def capture_genie_results(result):
    """Read the exported query_genie() return contract, not its narrative answer.

    The notebook returns SQL outputs in labelled blocks. Capture at the existing
    tool boundary so future notebook exports need no visualization code.
    """
    if not isinstance(result, tuple) or len(result) != 2:
        return []
    text, sources = result
    if not isinstance(text, str) or not isinstance(sources, list):
        return []
    _, separator, blocks = text.partition('\n\nGenie query results:\n')
    if not separator:
        return []
    markers = list(re.finditer(r'^\[(G\d+)\] Genie query: [^\n]*\n', blocks, re.M))
    by_id = {s.get('id'): s for s in sources if isinstance(s, dict) and s.get('sql')}
    results = []
    for index, marker in enumerate(markers):
        source = by_id.get(marker[1])
        if source is None:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(blocks)
        table = parse_table(blocks[marker.end():end])
        if table is not None:
            results.append({'id': marker[1], 'title': str(source.get('title') or source.get('label') or 'Query results')[:240], **table})
    return results


def bounded_results(results, references, budget):
    """Persist only cited data within the existing tool-receipt storage limit."""
    used = {ref['id'] for ref in references if ref.get('kind') == 'genie' and ref.get('used_in_answer')}
    selected = []
    for result in results:
        if result['id'] not in used:
            continue
        item = {**result, 'rows': list(result['rows'])}
        while item['rows'] and len(json.dumps(selected + [item], ensure_ascii=False)) > budget:
            item['rows'].pop()
            item['truncated'] = True
        if len(json.dumps(selected + [item], ensure_ascii=False)) <= budget:
            selected.append(item)
    return selected
