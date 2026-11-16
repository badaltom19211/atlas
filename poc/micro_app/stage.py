"""Create an allowlisted deployment snapshot in a NEW local output directory.

Run the POC UI build first, then: python poc/micro_app/stage.py <new-directory>
No .env, Git history, notebook exports, test data or credentials are included.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]

def stage(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a new directory; existing output is never overwritten.')
    frontend = ROOT / 'poc/micro_app/dist'
    if not (frontend / 'index.html').exists():
        raise ValueError('Build the POC frontend first.')
    destination.mkdir(parents=True)
    (destination / 'server').mkdir()
    for source in (ROOT / 'server').glob('*.py'):
        if not source.name.startswith('test_'):
            shutil.copy2(source, destination / 'server' / source.name)
    (destination / 'poc/micro_app').mkdir(parents=True)
    for name in ('__init__.py', 'web.py', 'koantek_agent.py'):
        shutil.copy2(ROOT / 'poc/micro_app' / name, destination / 'poc/micro_app' / name)
    shutil.copy2(ROOT / 'requirements.txt', destination / 'requirements.txt')
    shutil.copy2(ROOT / 'poc/micro_app/session-app.yaml', destination / 'app.yaml')
    shutil.copytree(frontend, destination / 'dist')
    print(f'Created session-only POC bundle: {destination}')

if __name__ == '__main__':
    stage(sys.argv[1])
