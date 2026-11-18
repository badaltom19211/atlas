"""Measure automatic Micro App wake-up without an explicit start or stop."""
import argparse
import json
import time
from pathlib import Path

import requests
from databricks.sdk import WorkspaceClient

HOST = 'https://dbc-f2d0e557-3d47.cloud.databricks.com'
URL = 'https://aia-micro-poc-7474654589961519.aws.databricksapps.com'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = WorkspaceClient(profile='genie-react-workspace')
    if workspace.config.host.rstrip('/') != HOST:
        raise ValueError('This probe is restricted to the Koantek POC.')
    app = workspace.apps.get('aia-micro-poc')
    report = {'initial_compute_state': app.compute_status.state.value, 'explicit_start_used': False,
              'checks': [], 'ready': False}
    headers = workspace.config.authenticate()
    start = time.monotonic()
    while time.monotonic() - start < 120:
        try:
            response = requests.get(URL + '/api/me', headers=headers, timeout=30, allow_redirects=False)
            record = {'http': response.status_code, 'seconds': round(time.monotonic() - start, 2)}
            if response.status_code == 200 and 'application/json' in response.headers.get('content-type', ''):
                body = response.json()
                if body.get('history') == 'session-only':
                    report.update(ready=True, boot_id=body['boot_id'], uptime_seconds=body['uptime_seconds'])
            report['checks'].append(record)
            print(json.dumps(record), flush=True)
        except requests.RequestException as error:
            report['checks'].append({'error_type': type(error).__name__, 'seconds': round(time.monotonic() - start, 2)})
        if report['ready']:
            break
        time.sleep(2)
    report['ready_after_seconds'] = round(time.monotonic() - start, 2)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    if not report['ready']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
