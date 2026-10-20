#!/usr/bin/env python3
"""Offline, opt-in content migration. A dry run never writes or fetches data."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

from job_content import CONTENT_FIELDS, merge_content, split_links
from scout import job_identity

ROOT = Path(__file__).resolve().parent


def migrate(path, raw_input=None, *, apply=False, limit=25, offset=0):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    ids = [row.get('id') for row in rows]
    if any(not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('Missing or duplicate IDs: migration refused; jobs.csv is unchanged')
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError('Malformed CSV: migration refused')
    candidates = []
    if raw_input:
        payload = json.loads(raw_input.read_text(encoding='utf-8'))
        candidates = payload.get('jobs', []) if isinstance(payload, dict) else payload
        if not isinstance(candidates, list) or any(not isinstance(job, dict) for job in candidates):
            raise ValueError('raw-input must contain a list of normalized jobs')
    by_id, by_identity = {}, {}
    for job in candidates:
        if job.get('id'):
            by_id.setdefault(job['id'], []).append(job)
        if all(job.get(key) for key in ('company', 'title', 'location')):
            by_identity.setdefault(job_identity(job), []).append(job)
    changed, matched, ambiguous = [], [], []
    batch = rows[offset:offset + limit]
    for index, row in enumerate(batch, start=offset):
        matches = by_id.get(row['id'], [])
        if not matches and all(row.get(key) for key in ('company', 'title', 'location')):
            matches = by_identity.get(job_identity(row), [])
        # Distinct postings sharing a title/location need manual resolution.
        unique = {json.dumps(job, sort_keys=True, ensure_ascii=False) for job in matches}
        candidate = matches[0] if len(unique) == 1 else None
        if len(unique) > 1:
            ambiguous.append(row['id'])
        content = merge_content(candidate or {}, row)
        if not row.get('description') and not (candidate or {}).get('description'):
            content.update(description_source='', description_status='legacy_excerpt')
        # Legacy URLs are ambiguous. Only recover a listing from known ATS paths.
        if not content['description_url'] and not content['apply_url']:
            listing, application = split_links('', row.get('url'))
            if listing:
                content.update(description_url=listing, apply_url=application)
        updated = {**row, **content}
        if candidate:
            matched.append(row['id'])
        if any(updated.get(key, '') != row.get(key, '') for key in updated):
            changed.append(row['id'])
        rows[index] = updated
    backup = None
    if apply and changed:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.with_name(f'{path.name}.pre-v43-{stamp}.bak')
        with path.open('rb') as source, backup.open('xb') as dest:
            shutil.copyfileobj(source, dest)
        # Keep every original column, row order, ID and tracking field.
        fields = list(dict.fromkeys(fields + CONTENT_FIELDS))
        if 'description_excerpt' not in fields:
            fields.append('description_excerpt')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                dir=path.parent, prefix=f'{path.name}.', suffix='.tmp', delete=False) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            temporary = Path(stream.name)
        temporary.replace(path)
    return dict(total=len(rows), offset=offset, inspected=len(batch), changed=len(changed),
                changed_ids=changed, matched=matched, ambiguous=ambiguous,
                applied=bool(apply and changed), backup=str(backup) if backup else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=Path, default=ROOT / 'data' / 'jobs.csv')
    parser.add_argument('--raw-input', type=Path, help='Previously collected normalized jobs JSON; no network access')
    parser.add_argument('--limit', type=int, default=25, help='Maximum historical rows to inspect (default: 25)')
    parser.add_argument('--offset', type=int, default=0, help='First historical row to inspect (default: 0)')
    parser.add_argument('--apply', action='store_true', help='Write changes after creating an exact backup')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    if args.offset < 0:
        parser.error('--offset must not be negative')
    summary = migrate(args.jobs, args.raw_input, apply=args.apply, limit=args.limit, offset=args.offset)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
