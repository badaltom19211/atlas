"""Load trusted, deployment-configured glossary code from Workspace once per app start.

The remote folder is application code. Only the deployed setting selects it;
chat input, user tokens and model output never select files to import.
"""
import hashlib
import logging
import time
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from databricks.sdk.service.workspace import ExportFormat, ObjectType

from .databricks_client import app_workspace_client
from .glossary import GlossaryEnricher, load_enricher

# Inherit Uvicorn's configured INFO handler so readiness is visible in App logs.
logger = logging.getLogger('uvicorn.error.glossary')
REQUIRED = {'business_glossary.json', 'glossary_loader.py', 'enrichment.py'}
MAX_FILE_BYTES = 5_000_000
MAX_TOTAL_BYTES = 20_000_000
MAX_OBJECTS = 128
MAX_FILES = 64
MAX_DEPTH = 5
DOWNLOAD_SECONDS = 90


def workspace_folder(value):
    """Accept the notebook /Workspace path or the Workspace API /Users path."""
    path = value.strip().rstrip('/')
    if path.startswith('/Workspace/'):
        path = path[len('/Workspace'):]
    if (not path.startswith('/') or path == '/Workspace' or len(path) > 2000
            or any(char in path for char in ('\\', '\x00', ':'))
            or any(part in ('', '.', '..') for part in path.split('/')[1:])):
        raise ValueError('ATLAS_GLOSSARY_WORKSPACE_DIR must be an absolute workspace folder, not a URL or relative path.')
    return path


def _snapshot(workspace, root, directory):
    """Download a bounded Python/JSON tree before executing any module."""
    pending, files, seen = [root], {}, set()
    deadline = time.monotonic() + DOWNLOAD_SECONDS

    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError('Glossary download exceeded the startup budget.')

    while pending:
        budget()
        parent = pending.pop()
        for item in workspace.workspace.list(parent, recursive=False):
            budget()
            path = workspace_folder(item.path or '')
            relative = PurePosixPath(path).relative_to(root)
            # Reject traversal, duplicates, and objects outside the requested folder.
            if (str(PurePosixPath(path).parent) != parent or path in seen
                    or len(relative.parts) > MAX_DEPTH):
                raise ValueError('Unexpected glossary workspace entry.')
            seen.add(path)
            if len(seen) > MAX_OBJECTS:
                raise ValueError('Glossary folder has too many objects.')
            if item.object_type == ObjectType.DIRECTORY:
                pending.append(path)
            elif item.object_type == ObjectType.FILE and relative.suffix in ('.py', '.json'):
                files[relative.as_posix()] = path
                if len(files) > MAX_FILES:
                    raise ValueError('Glossary folder has too many code/data files.')
    if not REQUIRED.issubset(files):
        raise ValueError('The glossary folder must contain all three required workspace files.')

    total, digest = 0, hashlib.sha256()
    for relative, remote in sorted(files.items()):
        budget()
        with workspace.workspace.download(remote, format=ExportFormat.AUTO) as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('Glossary assets exceed the size budget.')
        # Files must be text, and the entire tree must be ready before importing.
        data.decode('utf-8-sig')
        target = directory.joinpath(*PurePosixPath(relative).parts)
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Glossary asset escaped its cache directory.')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest.update(relative.encode() + b'\x00' + data + b'\x00')
    budget()
    return digest.hexdigest()[:16], len(files)


class GlossaryRuntime:
    def __init__(self, enricher, cache=None, revision=None):
        self.enricher, self.cache, self.revision = enricher, cache, revision

    def close(self):
        if self.cache is not None:
            self.cache.cleanup()
            self.cache = None


def load_glossary_runtime(settings, workspace=None):
    """A failed refresh never imports partial files or reuses a prior snapshot."""
    if settings.glossary_dir and settings.glossary_workspace_dir:
        raise ValueError('Configure either local or workspace glossary assets, not both.')
    if not settings.glossary_workspace_dir:
        return GlossaryRuntime(load_enricher(settings.glossary_dir))
    cache = None
    try:
        root = workspace_folder(settings.glossary_workspace_dir)
        workspace = workspace if workspace is not None else app_workspace_client(settings)
        cache = TemporaryDirectory(prefix='aia-glossary-')
        revision, count = _snapshot(workspace, root, Path(cache.name))
        enricher = load_enricher(cache.name)
        if enricher.status != 'ready':
            raise ImportError('Shared glossary functions could not be loaded.')
        logger.info('Workspace glossary ready (revision=%s, files=%s).', revision, count)
        return GlossaryRuntime(enricher, cache, revision)
    except Exception as error:
        if cache is not None:
            cache.cleanup()
        # Provider messages may include paths or private code; log only the type.
        logger.warning('Workspace glossary unavailable (%s). Check folder read access for the app service principal, '
                       'the three required files and Python dependencies; restart to retry. Using the original question.',
                       type(error).__name__)
        return GlossaryRuntime(GlossaryEnricher('unavailable'))
