#!/usr/bin/env python3
"""Resume verified historical enrichment without rewriting the daily jobs.csv."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
from urllib.parse import urlparse

import requests

from enrichment_sources import retrieve
from enrichment_state import atomic_json, input_signature, load_state, utc_now, replace_file
from job_content import safe_url

ROOT = Path(__file__).resolve().parent
AUDIT_FIELDS = ['id', 'company', 'title', 'original_url', 'detail_url', 'apply_url',
    'description_status', 'availability', 'source', 'confidence', 'outcome',
    'checked_at', 'description_length', 'attempts', 'evidence', 'error']


class HttpClient:
    """Bounded requests, single-flight cache, and at most two requests per host."""
    def __init__(self):
        self.local = threading.local()
        self.lock = threading.Lock()
        self.hosts = {}
        self.cache = {}
        self.keys = {}

    def get(self, url, params=None):
        if not safe_url(url):
            raise ValueError('Invalid public URL')
        key = (url, json.dumps(params or {}, sort_keys=True))
        with self.lock:
            key_lock = self.keys.setdefault(key, threading.Lock())
            host_lock = self.hosts.setdefault(urlparse(url).hostname, threading.Semaphore(2))
        with key_lock:
            if key in self.cache:
                return self.cache[key]
            if not hasattr(self.local, 'session'):
                session = requests.Session()
                session.max_redirects = 5
                session.headers.update({'User-Agent': 'StageScout/4.3 (+https://github.com/jaddilyesalilarbi/stage-scout-v3.2-update)',
                                        'Accept': 'application/json,text/html;q=0.9'})
                self.local.session = session
            with host_lock:
                for attempt in range(2):
                    response = self.local.session.get(url, params=params, timeout=(6, 18))
                    if len(response.content) > 8 * 1024 * 1024:
                        raise ValueError('Response exceeds 8 MiB; skipped')
                    if response.status_code not in (429, 500, 502, 503, 504) or attempt:
                        break
                    retry_after = response.headers.get('Retry-After', '1')
                    # Do not retry earlier than the server permits.
                    try:
                        delay = max(1, float(retry_after))
                    except ValueError:
                        break
                    if delay > 10:
                        break
                    time.sleep(delay)
                time.sleep(0.2)
            if response.status_code == 200:
                self.cache[key] = response
            return response


@contextmanager
def writer_lock(root):
    directory = root / '.backfill-backups'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'writer.lock').open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if __import__('os').name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if __import__('os').name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    ids = [row.get('id') for row in rows]
    if (any(not key for key in ids) or len(ids) != len(set(ids))
            or any(None in row or None in row.values() for row in rows)):
        raise ValueError('Malformed history or missing/duplicate IDs; no data changed')
    return rows


def current_result(row, state):
    result = state['results'].get(row['id'], {})
    return result if result.get('input_signature') == input_signature(row) else {}


def already_done(row, state):
    result = current_result(row, state)
    return result.get('outcome') == 'expired' or (
        result.get('outcome') == 'enriched' and result.get('confidence') == 'high'
        and result.get('description_status') == 'complete' and result.get('description')
        and safe_url(result.get('detail_url')))


def family(row):
    url = row.get('description_url') or row.get('url') or row.get('apply_url', '')
    host = urlparse(url).hostname or ''
    for name in ('smartrecruiters', 'oraclecloud', 'icims', 'lever', 'ashbyhq', 'workable',
                 'recruitee', 'myworkdayjobs', 'indeed'):
        if name in host:
            return name
    if '/job/' in url:
        return 'successfactors-or-html'
    return 'other-html'


def reports(root, rows, state, *, interrupted=False, run_error=''):
    audit = []
    for row in rows:
        result = current_result(row, state)
        audit.append({**{key: result.get(key, '') for key in AUDIT_FIELDS},
            'id': row['id'], 'company': row.get('company', ''), 'title': row.get('title', ''),
            'original_url': result.get('original_url', row.get('url', '')),
            'outcome': result.get('outcome', 'pending'),
            'description_length': len(result.get('description') or '')})
    counts = Counter(row['outcome'] for row in audit)
    completed = [current_result(row, state) for row in rows]
    summary = dict(total=len(rows), processed=len(rows) - counts['pending'],
        complete_descriptions=sum(r.get('outcome') in ('enriched', 'expired') and r.get('description_status') == 'complete'
            and r.get('confidence') == 'high' and bool(r.get('description')) for r in completed),
        corrected_links=sum(r.get('outcome') == 'enriched' and bool(r.get('detail_url'))
            and r.get('detail_url') != r.get('original_url') for r in completed),
        expired=counts['expired'], not_found=counts['not_found'], remaining=counts['pending'],
        retryable=sum(counts[key] for key in ('error', 'inaccessible', 'mismatch', 'unsupported', 'not_found')),
        outcomes=dict(sorted(counts.items())), interrupted=interrupted, run_error=run_error, generated_at=utc_now(),
        input_sha256=hashlib.sha256((root / 'data/jobs.csv').read_bytes()).hexdigest(),
        note='Complete means verified structured body recovered, not an assumed full legacy excerpt. Remaining means never attempted or source changed; retryable attempts are counted separately.')
    path = root / 'data/job-enrichment-audit.csv'
    with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', newline='', dir=path.parent,
            prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
        writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(audit)
        temporary = Path(stream.name)
    replace_file(temporary, path)
    atomic_json(root / 'data/job-enrichment-summary.json', summary)
    return summary


def run(root=ROOT, *, workers=4, max_seconds=900, limit=None, ids=None, sample=False,
        retry=False, report_only=False):
    root = Path(root).resolve()
    rows = read_rows(root / 'data/jobs.csv')
    path = root / 'data/job-enrichment-state.json'
    with writer_lock(root):
        state = load_state(path)
        if report_only:
            return reports(root, rows, state)
        selected = [row for row in rows if (not ids or row['id'] in ids)
                    and (retry or not already_done(row, state))]
        # A short resumed run must reach new rows before revisiting old failures.
        selected.sort(key=lambda row: (bool(current_result(row, state)),
            int(current_result(row, state).get('attempts', 0)),
            current_result(row, state).get('checked_at', '')))
        if sample:
            groups = {}
            for row in selected:
                groups.setdefault(family(row), row)
            selected = list(groups.values())
        if limit is not None:
            selected = selected[:limit]
        if selected:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = root / '.backfill-backups' / stamp
            backup.mkdir(parents=True)
            shutil.copyfile(root / 'data/jobs.csv', backup / 'jobs.csv')
            if path.exists():
                shutil.copyfile(path, backup / path.name)
            state.setdefault('runs', []).append(dict(started_at=utc_now(), selected=len(selected),
                input_sha256=hashlib.sha256((root / 'data/jobs.csv').read_bytes()).hexdigest()))
            atomic_json(path, state)
        start = time.monotonic()
        http = HttpClient()
        iterator = iter(selected)
        pool = ThreadPoolExecutor(max_workers=workers)
        pending = {}
        interrupted = False
        run_error = ''
        try:
            while True:
                while len(pending) < workers and time.monotonic() - start < max_seconds:
                    row = next(iterator, None)
                    if row is None:
                        break
                    pending[pool.submit(retrieve, row, http)] = row
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in done:
                    row = pending.pop(future)
                    try:
                        result = future.result()
                    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                        result = dict(outcome='inaccessible' if isinstance(error, requests.RequestException) else 'error',
                                      availability='unknown', confidence='none', error=f'{type(error).__name__}: {error}')
                    except Exception as error:
                        result = dict(outcome='error', availability='unknown', confidence='none',
                                      error=f'{type(error).__name__}: {error}')
                    previous = state['results'].get(row['id'], {})
                    if previous.get('input_signature') == input_signature(row):
                        archived = previous.get('archived_content')
                        if (previous.get('confidence') == 'high' and previous.get('description')
                                and len(previous['description']) >= len((archived or {}).get('description') or '')):
                            archived = {key: previous.get(key, '') for key in (
                                'description', 'description_status', 'source', 'confidence', 'checked_at', 'detail_url', 'apply_url')}
                        if archived and (result.get('outcome') not in ('enriched', 'expired')
                                or len(archived.get('description') or '') > len(result.get('description') or '')):
                            result['archived_content'] = archived
                    result.update(id=row['id'], input_signature=input_signature(row),
                        original_url=previous.get('original_url') or row.get('url', ''),
                        original_urls=previous.get('original_urls') or {k: row.get(k, '') for k in ('url', 'description_url', 'apply_url')},
                        attempts=int(previous.get('attempts', 0)) + 1, checked_at=utc_now())
                    state['results'][row['id']] = result
                    atomic_json(path, state)
                    print(f"[ENRICH] {row['id']} {family(row)} => {result.get('outcome')} "
                          f"({len(result.get('description') or '')} chars)", flush=True)
        except KeyboardInterrupt:
            interrupted = True
            print('[STOP] Checkpoint retained; resume with the same command.', flush=True)
        except Exception as error:
            run_error = f'{type(error).__name__}: {error}'
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            # A complete per-record checkpoint is authoritative after interruption;
            # reports can always be rebuilt without making network requests.
            summary = reports(root, rows, load_state(path), interrupted=interrupted, run_error=run_error)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-seconds', type=int, default=900)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--ids', help='Comma-separated historical IDs')
    parser.add_argument('--sample', action='store_true', help='One remaining record per platform family')
    parser.add_argument('--retry', action='store_true', help='Also recheck completed or expired records')
    parser.add_argument('--report-only', action='store_true', help='Rebuild audit/summary without network requests')
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or args.max_seconds < 0 or (args.limit is not None and args.limit < 1):
        parser.error('workers must be 1..8; max-seconds >= 0; limit positive')
    summary = run(args.root, workers=args.workers, max_seconds=args.max_seconds, limit=args.limit,
                  ids=set(args.ids.split(',')) if args.ids else None, sample=args.sample,
                  retry=args.retry, report_only=args.report_only)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 130 if summary['interrupted'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
