"""Resumable enrichment snapshots, kept separate from the daily scan's CSV."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from job_content import merge_content, safe_url

SIGNATURE_FIELDS = ('id', 'company', 'title', 'location', 'url', 'description_url', 'apply_url')


def input_signature(row):
    value = {key: row.get(key, '') for key in SIGNATURE_FIELDS}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
            prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    replace_file(temporary, path)


def replace_file(temporary, path):
    # Windows can briefly deny a rename while an antivirus or reader closes the
    # destination. Keep the old checkpoint intact and retry the same temp file.
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


def load_state(path):
    if not Path(path).exists():
        return {'version': 1, 'results': {}}
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(state, dict) or state.get('version') != 1
            or not isinstance(state.get('results'), dict)
            or any(not isinstance(value, dict) for value in state['results'].values())):
        raise ValueError('Invalid enrichment checkpoint; refusing to overwrite it')
    return state


def overlay(row, result):
    """Project verified content without changing IDs, tracking or daily scan data."""
    updated = dict(row)
    if not result:
        return updated
    if result.get('id') != row.get('id') or result.get('input_signature') != input_signature(row):
        updated.update(enrichment_outcome='stale', availability='unknown',
                       enrichment_error='Source changed since verification; retry required',
                       enrichment_confidence='none')
        return updated
    outcome = result.get('outcome', 'error')
    updated.update(enrichment_outcome=outcome, availability=result.get('availability', 'unknown'),
                   enrichment_checked_at=result.get('checked_at', ''),
                   enrichment_error=result.get('error', ''),
                   enrichment_confidence=result.get('confidence', 'none'))
    # A failed lookup never upgrades an old URL into a verified detail page.
    updated.update(detail_url='', description_url='', apply_url='')
    archived = result.get('archived_content') or {}
    if archived.get('confidence') == 'high' and archived.get('description'):
        updated.update(merge_content(dict(description=archived['description'],
            description_source=archived.get('source', ''), description_status='archived'), row))
        updated.update(detail_url='', description_url='', apply_url='')
    if outcome in ('enriched', 'expired') and result.get('confidence') == 'high':
        body = result.get('description') or ''
        content = merge_content(dict(description=body,
            description_source=result.get('source', ''),
            description_status=result.get('description_status', 'partial'),
            description_url=safe_url(result.get('detail_url')),
            apply_url=safe_url(result.get('apply_url'))), row)
        updated.update(content)
        updated['detail_url'] = safe_url(result.get('detail_url'))
        updated['description_url'] = updated['detail_url']
        updated['apply_url'] = safe_url(result.get('apply_url'))
    if result.get('availability') == 'expired':
        updated['apply_url'] = ''
    return updated


def utc_now():
    return datetime.now(timezone.utc).isoformat()
