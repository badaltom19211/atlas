"""Run explicit live POC checks; CLI OAuth stays in memory, evidence stays out of Git.

python poc/micro_app/live_probe.py --output <sanitized-results.json>
Set DATABRICKS_CLI_PATH if the Databricks CLI is not on PATH.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import time
from uuid import uuid4

import requests
from databricks.sdk import WorkspaceClient

HOST = 'https://dbc-f2d0e557-3d47.cloud.databricks.com'
URL = 'https://aia-micro-poc-7474654589961519.aws.databricksapps.com'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default='genie-react-workspace')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stream', action='store_true', help='Measure live workflow progress delivery.')
    parser.add_argument('--visualizations', action='store_true', help='Also verify chart rows and greeting behavior.')
    args = parser.parse_args()
    workspace = WorkspaceClient(profile=args.profile)
    if workspace.config.host.rstrip('/') != HOST:
        raise ValueError('This probe is restricted to the Koantek POC workspace.')
    headers = workspace.config.authenticate()
    headers['x-atlas-request'] = '1'
    if args.stream:
        headers['Accept'] = 'application/x-ndjson'
    me = requests.get(URL + '/api/me', headers=headers, timeout=60)
    assert me.status_code == 200, f'Identity endpoint returned {me.status_code}: {me.text[:300]}'
    anonymous = requests.get(URL + '/api/me', timeout=30, allow_redirects=False)
    assert anonymous.status_code in (302, 303, 401, 403), 'Anonymous identity access was not denied.'
    index = requests.get(URL, headers=headers, timeout=30)
    assert index.status_code == 200 and 'id="root"' in index.text
    script = re.search(r'src="([^"]+\.js)"', index.text)
    assert script and requests.get(URL + script[1], headers=headers, timeout=30).status_code == 200
    checks = {'identity_verified': True, 'anonymous_http': anonymous.status_code,
              'react_html_and_bundle_http': 200, 'history_mode': me.json()['history'], 'cases': []}

    def ask(name, question, expected, history=None):
        start = time.monotonic()
        response = requests.post(URL + '/api/chat', headers=headers, timeout=210, stream=args.stream,
                                 json={'question': question, 'history': history or [], 'session_id': str(uuid4())})
        record = {'case': name, 'http': response.status_code, 'wall_seconds': round(time.monotonic()-start, 2)}
        if response.status_code != 200:
            record['error'] = response.json().get('detail', 'Request failed')
            print(json.dumps(record), flush=True)
            return record, None
        if args.stream:
            progress, body = [], None
            try:
                for line in response.iter_lines(chunk_size=1):
                    if not line: continue
                    event = json.loads(line)
                    if event.get('type') == 'progress':
                        progress.append({'stage': event['stage'], 'seconds': round(time.monotonic()-start, 2)})
                    elif event.get('type') == 'done': body = event
                    elif event.get('type') == 'error': record['error'] = event['message']
            finally:
                response.close()
            record['progress'] = progress
            record['wall_seconds'] = round(time.monotonic()-start, 2)
            expected_stages = ['queued', 'understanding', 'searching', 'composing', 'sources'] if expected else ['queued', 'understanding']
            record['progress_passed'] = [p['stage'] for p in progress] == expected_stages and progress[0]['seconds'] < record['wall_seconds']
            if body is None:
                print(json.dumps(record), flush=True)
                return record, None
        else:
            body = response.json()
        meta = body['custom_outputs']
        refs = meta.get('references', [])
        record.update(app_seconds=body['elapsed_seconds'], selected_tools=meta['selected_tools'],
                      failed_tools=meta.get('failed_tools', []),
                      source_kinds=sorted({s['kind'] for s in refs if s.get('used_in_answer')}),
                      used_source_count=sum(bool(s.get('used_in_answer')) for s in refs),
                      sql_sources=sum(bool(s.get('sql')) for s in refs),
                      follow_up=meta.get('is_follow_up'), boot_id=body['boot_id'])
        record['routing_passed'] = sorted(record['selected_tools']) == sorted(expected)
        tables = meta.get('genie_results', [])
        record['result_table_count'] = len(tables)
        record['result_row_counts'] = [len(table['rows']) for table in tables]
        record['result_tables_cited'] = all(any(ref.get('id') == table['id'] and ref.get('used_in_answer') for ref in refs) for table in tables)
        if name == 'chart':
            def chart_ready(table):
                rows, columns = table['rows'], table['columns']
                if table['truncated'] or len(columns) < 2 or not 2 <= len(rows) <= 12:
                    return False
                for column in range(len(columns)):
                    if all(re.fullmatch(r'\d+(?:\.\d+)?', row[column].replace(',', '')) for row in rows):
                        if any(len({row[index] for row in rows}) == len(rows) for index in range(len(columns)) if index != column):
                            return True
                return False
            record['chart_rows_passed'] = any(chart_ready(table) for table in tables)
        if name in ('bike_count', 'mixed'):
            record['expected_count_7_found'] = bool(re.search(r'\b(7|seven)\b', body['answer'], re.I))
        if name == 'followup':
            record['subject_retained'] = 'edward' in meta.get('standalone_question', '').lower()
        print(json.dumps(record), flush=True)
        # Both console and report omit business answers, SQL and individual row values.
        return record, body

    with ThreadPoolExecutor(max_workers=2) as pool:
        count = pool.submit(ask, 'bike_count', 'How many distinct bike categories are in the bike-store dataset?', ['genie'])
        document = pool.submit(ask, 'document', 'What was the time period for the Edward Jones project?', ['projects'])
        count_record, _ = count.result()
        document_record, document_body = document.result()
    checks['cases'].extend([count_record, document_record])
    if document_body:
        followup, _ = ask('followup', 'What was that project about?', ['projects'],
                          [{'role': 'user', 'content': 'What was the time period for the Edward Jones project?'},
                           {'role': 'assistant', 'content': document_body['answer'],
                            'notebook_query': document_body['custom_outputs']['notebook_query']}])
        checks['cases'].append(followup)
    mixed, _ = ask('mixed', 'How many bike categories are there, and what projects are documented in the project index?', ['genie', 'projects'])
    checks['cases'].append(mixed)
    if args.visualizations:
        with ThreadPoolExecutor(max_workers=2) as pool:
            chart = pool.submit(ask, 'chart', 'Show the number of products grouped by bike category, including all category names and product counts.', ['genie'])
            greeting = pool.submit(ask, 'greeting', 'Hi', [])
            checks['cases'].extend([chart.result()[0], greeting.result()[0]])
    checks['all_passed'] = len(checks['cases']) == (6 if args.visualizations else 4) and all(
        r['http'] == 200 and r.get('routing_passed') and not r.get('failed_tools')
        and (r.get('used_source_count', 0) > 0 or r['case'] == 'greeting') and r.get('expected_count_7_found', True)
        and r.get('result_tables_cited', False) and r.get('chart_rows_passed', True)
        and r.get('subject_retained', True) and r.get('progress_passed', True) for r in checks['cases'])
    checks['not_tested'] = ['Lakebase integration (resource attachment rejected)', 'MLflow trace ingestion',
                            'second real user identity isolation', 'browser visual QA', 'load testing']
    args.output.write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(json.dumps({'all_passed': checks['all_passed'], 'report': str(args.output)}), flush=True)
    if not checks['all_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
