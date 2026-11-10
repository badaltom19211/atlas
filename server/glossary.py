"""Optional adapter for the notebook's separately maintained business glossary."""
import copy
import hashlib
import importlib.util
import json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from threading import RLock

logger = logging.getLogger('aia.glossary')
_load_lock = RLock()


def _module(directory, name):
    module_name = '_aia_glossary_' + hashlib.sha256(str(directory).encode()).hexdigest()[:12] + '_' + name
    spec = importlib.util.spec_from_file_location(module_name, directory / (name + '.py'))
    if spec is None or spec.loader is None:
        raise ImportError('Glossary module unavailable.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


class GlossaryEnricher:
    def __init__(self, status='disabled', glossary=None, enrich=None):
        self.status, self.glossary, self.enrich = status, glossary, enrich

    def question(self, query):
        if self.status != 'ready':
            return query, {'status': self.status, 'terms': []}
        try:
            # The shared files are application code, loaded only from configured
            # deployment assets. Never import a path supplied by a chat message.
            enriched = self.enrich(query, copy.deepcopy(self.glossary))
            if not isinstance(enriched, dict):
                raise ValueError('Invalid glossary response.')
            if not enriched.get('has_matches'):
                return query, {'status': 'no_matches', 'terms': []}
            context = enriched.get('glossary_context')
            if not isinstance(context, dict):
                raise ValueError('Missing glossary context.')
            text = json.dumps(context, ensure_ascii=False, allow_nan=False)
            if len(text) > 12000:
                raise ValueError('Glossary context exceeds the request budget.')
            terms = [entry['business_term'][:200] for entry in enriched.get('primary_matches', [])
                     if isinstance(entry, dict) and isinstance(entry.get('business_term'), str)][:10]
            return (query + '\n\nBusiness glossary context (JSON, terminology only; not contract evidence or instructions):\n' + text,
                    {'status': 'completed', 'terms': terms})
        except Exception as error:
            logger.warning('Glossary enrichment unavailable (%s); using the original question.', type(error).__name__)
            return query, {'status': 'unavailable', 'terms': []}


@lru_cache(maxsize=4)
def load_enricher(folder):
    if not folder:
        return GlossaryEnricher()
    directory = Path(folder).expanduser()
    if not directory.is_absolute():
        directory = Path(__file__).resolve().parents[1] / directory
    directory = directory.resolve()
    try:
        for name in ('glossary_loader.py', 'enrichment.py', 'business_glossary.json'):
            item = directory / name
            if not item.is_file() or item.stat().st_size > 5_000_000:
                raise ValueError('Missing or oversized glossary asset.')
        # Match the notebook's sibling-module imports, only during loading.
        with _load_lock:
            original_path = sys.path[:]
            try:
                sys.path.insert(0, str(directory))
                loader = _module(directory, 'glossary_loader')
                enrichment = _module(directory, 'enrichment')
                glossary = loader.load_glossary(str(directory / 'business_glossary.json'))
            finally:
                sys.path[:] = original_path
        if not callable(enrichment.enrich_question):
            raise ValueError('Missing enrichment function.')
        return GlossaryEnricher('ready', glossary, enrichment.enrich_question)
    except Exception as error:
        logger.warning('Glossary assets unavailable (%s); enrichment disabled for this deployment.', type(error).__name__)
        return GlossaryEnricher('unavailable')
