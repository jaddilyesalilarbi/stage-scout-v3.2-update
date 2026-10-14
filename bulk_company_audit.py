#!/usr/bin/env python3
"""One-off full-company ATS audit in GitHub Actions matrix shards.

All *enabled* CSV companies are attempted. "Attempted" means only that a
lookup/fetch was tried. It is not proof that a website was scanned. Confirmed
scrapes are clearly distinguished from directory-only matches and errors.

This script never guesses a careers URL. It only persists URLs returned by an
ATS adapter after a successful fetch (and only unambiguous directory matches).
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote_plus

from company_watchlist import company_key, load_watchlist, valid_public_url

ROOT = Path(__file__).resolve().parent
SHARDS_DEFAULT = 16
TIMEOUT_DEFAULT = 24


def active_targets(root: Path) -> tuple[list[dict], list[dict]]:
    all_rows = load_watchlist(root / 'companies.csv')
    active = sorted((r for r in all_rows if r['enabled']),
                    key=lambda r: (r['country'] not in {'FR', 'CH'}, r['country'], r['name'].casefold()))
    config_path = root / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    direct = {company_key(str(row.get('name', ''))): str(row.get('url', '')).strip()
              for row in config.get('company_careers', []) if isinstance(row, dict)}
    results = []
    for row in active:
        out = dict(row)
        if not out.get('careers_url') and valid_public_url(direct.get(out['key'], '')):
            out['careers_url'] = direct[out['key']]
            out['url_origin'] = 'config_direct'
        else:
            out['url_origin'] = 'csv' if out.get('careers_url') else 'directory'
        results.append(out)
    return results, all_rows


def worker(target: dict, result_path: Path) -> int:
    from company_watchlist import scan_target
    try:
        jobs, errors, info = scan_target(target)
    except Exception as exc:
        jobs, errors, info = [], [f'{type(exc).__name__}: {exc}'], {
            'outcome': 'error', 'message': f'{type(exc).__name__}: {str(exc)[:160]}',
            'resolved_url': '', 'candidate_urls': [], 'raw_postings': 0,
        }
    result_path.write_text(json.dumps({'jobs': jobs, 'errors': errors, 'scan_info': info},
                                      ensure_ascii=False), encoding='utf-8')
    return 0


def scan_one(root: Path, target: dict, timeout: int, scratch: Path) -> dict:
    label = target['name']
    result_path = scratch / 'result.json'
    result_path.unlink(missing_ok=True)
    cmd = [sys.executable, '-u', str(root / 'bulk_company_audit.py'),
           '--worker', '--target-json', json.dumps(target, ensure_ascii=False),
           '--result', str(result_path)]
    start = time.monotonic()
    status = 'completed'
    jobs: list[dict] = []
    errors: list[str] = []
    info = {'outcome': 'error', 'message': 'Aucun résultat du worker',
            'resolved_url': '', 'candidate_urls': [], 'raw_postings': 0}
    try:
        proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True,
                              errors='replace', timeout=timeout, check=False)
        if proc.returncode != 0:
            status = 'failed'
            info['message'] = f'Worker code {proc.returncode}: {proc.stderr[-160:]}'
        elif not result_path.exists():
            status = 'failed'
        else:
            data = json.loads(result_path.read_text(encoding='utf-8'))
            jobs = data.get('jobs', [])
            errors = data.get('errors', [])
            info = data.get('scan_info') or info
            if not isinstance(jobs, list) or not isinstance(errors, list) or not isinstance(info, dict):
                raise ValueError('Unexpected worker output')
            if errors:
                status = 'error'
    except subprocess.TimeoutExpired:
        status = 'timeout'
        info = {'outcome': 'timeout', 'message': f'Délai de {timeout} secondes dépassé',
                'resolved_url': '', 'candidate_urls': [], 'raw_postings': 0}
    except (OSError, ValueError, TypeError) as exc:
        status = 'failed'
        info = {'outcome': 'error', 'message': f'{type(exc).__name__}: {str(exc)[:160]}',
                'resolved_url': '', 'candidate_urls': [], 'raw_postings': 0}
    return {'stage': 'watchlist', 'name': label, 'country': target['country'],
            'input_url': target.get('careers_url') or '', 'url_origin': target.get('url_origin', ''),
            'status': status, 'count': len(jobs),
            'duration_seconds': round(time.monotonic() - start, 1),
            'scan_info': info, 'errors': errors, 'jobs': jobs}


def run_shard(root: Path, index: int, count: int, timeout: int, outdir: Path) -> Path:
    if count < 1 or not (0 <= index < count):
        raise ValueError('Shard index must be between 0 and shards-1')
    active, _ = active_targets(root)
    subset = active[index::count]
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='stage_scout_bulk_') as temp:
        for j, target in enumerate(subset, 1):
            print(f'[AUDIT {index+1}/{count} - {j}/{len(subset)}] {target["name"]}', flush=True)
            row = scan_one(root, target, timeout, Path(temp))
            results.append(row)
            outcome = row['scan_info'].get('outcome') or row['status']
            print(f'  => {outcome}, {row["count"]} annonces, {row["duration_seconds"]}s', flush=True)
    result = {'shard': index, 'shards': count, 'targets_total': len(active),
              'run_date': date.today().isoformat(), 'results': results}
    path = outdir / f'part-{index:02d}.json'
    path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(f'[DONE] {len(results)} entreprises tentées. Fichier: {path}', flush=True)
    return path


def google_search_url(name: str) -> str:
    return 'https://www.google.com/search?q=' + quote_plus(f'{name} careers jobs recrutement site officiel')


def audit_csv(root: Path, data_dir: Path, statuses: dict[str, dict], all_rows: list[dict]) -> None:
    path = data_dir / 'company-url-audit.csv'
    fields = ['name', 'country', 'enabled', 'outcome', 'last_attempt', 'entered_careers_url',
              'candidate_ats_url', 'verified_scan_url', 'raw_postings', 'search_for_careers', 'message']
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=';')
        writer.writeheader()
        for target in all_rows:
            row = statuses.get(target['key'], {})
            info = row.get('scan_info') or {}
            candidates = info.get('candidate_urls') or []
            if not isinstance(candidates, list):
                candidates = []
            outcome = (info.get('outcome') or row.get('status') or
                       ('disabled' if not target['enabled'] else 'missing_result'))
            writer.writerow({
                'name': target['name'], 'country': target['country'],
                'enabled': 'yes' if target['enabled'] else 'no',
                'outcome': outcome, 'last_attempt': date.today().isoformat() if row else '',
                'entered_careers_url': target.get('careers_url') or '',
                'candidate_ats_url': ' | '.join(str(url) for url in candidates[:4]),
                'verified_scan_url': info.get('resolved_url') if outcome == 'scanned' else '',
                'raw_postings': info.get('raw_postings', row.get('count', '')) if row else '',
                'search_for_careers': google_search_url(target['name']),
                'message': str(info.get('message') or '')[:280],
            })


def fill_verified_urls(root: Path, statuses: dict[str, dict], all_rows: list[dict]) -> int:
    """Write back only unambiguous boards whose fetch succeeded; never guess."""
    path = root / 'companies.csv'
    updated = []
    count = 0
    for target in all_rows:
        record = {field: '' for field in ('name', 'country', 'careers_url', 'enabled', 'notes')}
        record.update({
            'name': target['name'], 'country': target['country'],
            'careers_url': target.get('careers_url') or '',
            'enabled': 'yes' if target['enabled'] else 'no', 'notes': target.get('notes') or '',
        })
        status = statuses.get(target['key'], {})
        info = status.get('scan_info') or {}
        url = str(info.get('resolved_url') or '')
        candidates = info.get('candidate_urls') or []
        # Never overwrite user-supplied URLs, or auto-confirm ambiguous lookups.
        if (not record['careers_url'] and info.get('outcome') == 'scanned'
                and len(candidates) == 1 and valid_public_url(url)):
            record['careers_url'] = url
            count += 1
        updated.append(record)
    with io.StringIO(newline='') as buffer:
        writer = csv.DictWriter(buffer, fieldnames=list(updated[0]) if updated else
                                ['name', 'country', 'careers_url', 'enabled', 'notes'])
        writer.writeheader()
        writer.writerows(updated)
        new = buffer.getvalue()
    # Preserve user file if there are no new verified URLs. A no-op audit should
    # not create an unnecessary CSV diff (or change its delimiter).
    if count:
        path.write_text(new, encoding='utf-8-sig')
    return count


def merge_results(root: Path, parts_dir: Path, output_dir: Path, expected_shards: int) -> dict:
    from coverage_report import write_coverage
    active, all_rows = active_targets(root)
    expected = {target['key'] for target in active}
    parts = sorted(parts_dir.glob('part-*.json'))
    by_shard: dict[int, dict] = {}
    for path in parts:
        part = json.loads(path.read_text(encoding='utf-8'))
        index = part.get('shard')
        if not isinstance(index, int) or index in by_shard:
            raise ValueError(f'Duplicate/invalid shard in {path}')
        if part.get('shards') != expected_shards or part.get('targets_total') != len(active):
            raise ValueError(f'Shard {index} was generated from a different companies.csv')
        by_shard[index] = part
    if set(by_shard) != set(range(expected_shards)):
        raise ValueError(f'Missing shards. Expected {expected_shards}; got {sorted(by_shard)}')

    statuses: dict[str, dict] = {}
    jobs: list[dict] = []
    errors: list[str] = []
    for part in by_shard.values():
        for row in part['results']:
            key = company_key(row.get('name', ''))
            if key in statuses or key not in expected:
                raise ValueError(f'Unexpected duplicate or unknown company: {row.get("name")}')
            statuses[key] = row
            jobs.extend(row.get('jobs') or [])
            errors.extend(row.get('errors') or [])
    if set(statuses) != expected:
        missing = expected - set(statuses)
        raise ValueError(f'Incomplete audit: {len(missing)} targets missing: {sorted(missing)[:10]}')
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / 'company-url-audit.csv'
    # Create audit snapshot from user-entered URL state, before autopopulating
    # the verified URLs, so the difference is visible in the report.
    audit_csv(root, output_dir, statuses, all_rows)
    url_count = fill_verified_urls(root, statuses, all_rows)

    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    health = {'attempted': len(statuses),
              'completed': sum(row['status'] == 'completed' for row in statuses.values()),
              'timed_out': sum(row['status'] == 'timeout' for row in statuses.values()),
              'failed_or_error': sum(row['status'] in {'error', 'failed'} for row in statuses.values()),
              'skipped_budget': 0, 'total_sources_planned': len(statuses),
              'sources': [{k: v for k, v in row.items() if k not in {'jobs', 'errors'}}
                          for row in statuses.values()]}
    if jobs:
        with tempfile.TemporaryDirectory(prefix='stage_scout_bulk_merge_') as scratch:
            raw_path = Path(scratch) / 'raw.json'
            raw_path.write_text(json.dumps({'jobs': jobs, 'errors': errors, 'source_health': health},
                                            ensure_ascii=False), encoding='utf-8')
            cmd = [sys.executable, '-u', str(root / 'scout.py'), '--config', str(root / 'config.json'),
                   '--output', str(output_dir), '--raw-input', str(raw_path)]
            print(f'[MATCH] Filtering {len(jobs)} board postings', flush=True)
            result = subprocess.run(cmd, cwd=root, check=False)
            if result.returncode:
                raise RuntimeError(f'Scout filtering failed with exit code {result.returncode}')
    else:
        print('[INFO] No board postings fetched. Leaving existing jobs.csv and last_run.json untouched.', flush=True)

    write_coverage(root, output_dir, config, health['sources'])
    audit_counts = Counter((row.get('scan_info') or {}).get('outcome') or row['status']
                           for row in statuses.values())
    summary = {'date': date.today().isoformat(), 'total': len(all_rows),
               'enabled': len(active), 'attempted': len(statuses),
               'disabled': len(all_rows)-len(active),
               'outcomes': dict(sorted(audit_counts.items())),
               'new_verified_urls_written_to_companies_csv': url_count,
               'raw_jobs_fetched': len(jobs),
               'report': str(csv_path.relative_to(root)) if csv_path.is_relative_to(root) else csv_path.name}
    (output_dir / 'bulk-audit-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('[SUMMARY] '+json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit ALL enabled companies, in parallel GitHub Actions shards')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--shard', type=int)
    parser.add_argument('--shards', type=int, default=SHARDS_DEFAULT)
    parser.add_argument('--timeout', type=int, default=TIMEOUT_DEFAULT)
    parser.add_argument('--outdir', type=Path, default=Path('bulk-parts'))
    parser.add_argument('--merge', action='store_true')
    parser.add_argument('--parts-dir', type=Path, default=Path('bulk-parts'))
    parser.add_argument('--output', type=Path, default=Path('data'))
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--target-json')
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.worker:
        if not args.target_json or not args.result:
            parser.error('Worker requires --target-json and --result')
        return worker(json.loads(args.target_json), args.result)
    if args.merge:
        merge_results(root, (root / args.parts_dir).resolve(),
                      (root / args.output).resolve(), args.shards)
        return 0
    if args.shard is None:
        parser.error('Provide --shard INDEX or --merge')
    run_shard(root, args.shard, args.shards, args.timeout, (root / args.outdir).resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
