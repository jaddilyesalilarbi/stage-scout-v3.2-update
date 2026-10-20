#!/usr/bin/env python3
"""Build a self-contained browsing UI from Stage Scout's existing data/jobs.csv.

Uses only Python's standard library. Does not modify jobs.csv or config.json.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from coverage_report import load_coverage, merge_coverage
import re
from job_content import safe_url

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'jobs.csv'
LAST_RUN = ROOT / 'data' / 'last_run.json'
TEMPLATE = ROOT / 'dashboard-src' / 'index.template.html'
STYLE = ROOT / 'dashboard-src' / 'style.css'
SCRIPT = ROOT / 'dashboard-src' / 'app.js'
OUTPUT = ROOT / 'dashboard' / 'index.html'

COUNTRIES = {
    'al': 'Albanie', 'ad': 'Andorre', 'at': 'Autriche', 'be': 'Belgique', 'ba': 'Bosnie-Herzegovine',
    'bg': 'Bulgarie', 'hr': 'Croatie', 'cy': 'Chypre', 'cz': 'Tchequie', 'dk': 'Danemark',
    'ee': 'Estonie', 'fi': 'Finlande', 'fr': 'France', 'de': 'Allemagne', 'gr': 'Grece',
    'hu': 'Hongrie', 'is': 'Islande', 'ie': 'Irlande', 'it': 'Italie', 'lv': 'Lettonie',
    'li': 'Liechtenstein', 'lt': 'Lituanie', 'lu': 'Luxembourg', 'mt': 'Malte', 'mc': 'Monaco',
    'me': 'Montenegro', 'nl': 'Pays-Bas', 'mk': 'Macedoine du Nord', 'no': 'Norvege',
    'pl': 'Pologne', 'pt': 'Portugal', 'ro': 'Roumanie', 'sm': 'Saint-Marin',
    'rs': 'Serbie', 'sk': 'Slovaquie', 'si': 'Slovenie', 'es': 'Espagne', 'se': 'Suede',
    'ch': 'Suisse', 'tr': 'Turquie', 'ua': 'Ukraine', 'gb': 'Royaume-Uni', 'uk': 'Royaume-Uni',
    'va': 'Vatican', 'xk': 'Kosovo'
}
NAMES = {
    'france': 'France', 'switzerland': 'Suisse', 'suisse': 'Suisse', 'schweiz': 'Suisse',
    'germany': 'Allemagne', 'allemagne': 'Allemagne', 'deutschland': 'Allemagne',
    'united kingdom': 'Royaume-Uni', 'great britain': 'Royaume-Uni', 'uk': 'Royaume-Uni',
    'england': 'Royaume-Uni', 'scotland': 'Royaume-Uni', 'wales': 'Royaume-Uni',
    'netherlands': 'Pays-Bas', 'the netherlands': 'Pays-Bas', 'nederland': 'Pays-Bas',
    'belgium': 'Belgique', 'belgique': 'Belgique', 'italy': 'Italie', 'italie': 'Italie',
    'spain': 'Espagne', 'espana': 'Espagne', 'portugal': 'Portugal', 'austria': 'Autriche',
    'osterreich': 'Autriche', 'poland': 'Pologne', 'sweden': 'Suede', 'norway': 'Norvege',
    'denmark': 'Danemark', 'finland': 'Finlande', 'ireland': 'Irlande', 'luxembourg': 'Luxembourg',
    'czech republic': 'Tchequie', 'czechia': 'Tchequie', 'hungary': 'Hongrie',
    'romania': 'Roumanie', 'greece': 'Grece', 'greece': 'Grece'
}


def infer_country(location: str) -> str:
    """Best-effort label for browsing only, not a geographic eligibility filter."""
    loc = (location or '').strip()
    if not loc:
        return 'Non precise'
    # Prefer the last comma-delimited part to avoid false positives in street names.
    last = loc.split(',')[-1].strip().lower().replace('.', '')
    last = re.sub(r'\s+', ' ', last)
    if last in COUNTRIES:
        return COUNTRIES[last]
    if last in NAMES:
        return NAMES[last]
    last = re.sub(r'\s*\([^)]*\)\s*', '', last).strip()
    if last in COUNTRIES:
        return COUNTRIES[last]
    if last in NAMES:
        return NAMES[last]
    # Handle labels like "Zurich, Switzerland (Hybrid)".
    for key, label in NAMES.items():
        if re.search(r'(?<![a-z])' + re.escape(key) + r'(?![a-z])', loc.lower()):
            return label
    return 'Non precise'


def load_jobs(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f'Cannot find {path}. Run the scout first to generate data/jobs.csv.')
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    jobs = []
    seen = set()
    for row in records:
        job_id = (row.get('id') or '').strip()
        if not job_id:
            # Never use an unstable row number for saved review state.
            continue
        if job_id in seen:
            continue
        seen.add(job_id)
        url = safe_url(row.get('url'))
        try:
            score = max(0, min(100, int(float(row.get('score') or 0))))
        except (ValueError, TypeError):
            score = 0
        jobs.append({
            'id': job_id,
            'company': row.get('company') or '',
            'title': row.get('title') or '',
            'location': row.get('location') or '',
            'country': infer_country(row.get('location') or ''),
            'kind': row.get('kind') or '',
            'duration': row.get('duration') or '',
            'score': score,
            'source': row.get('source') or '',
            'verification': row.get('verification') or '',
            'posted_at': row.get('posted_at') or '',
            'first_seen': row.get('first_seen') or '',
            'last_seen': row.get('last_seen') or '',
            'status': row.get('status') or 'To review',
            'url': url,
            'description_url': safe_url(row.get('description_url')),
            'apply_url': safe_url(row.get('apply_url')),
            'description': row.get('description') or '',
            'description_source': row.get('description_source') or '',
            'description_status': row.get('description_status') or 'legacy_excerpt',
            'why': row.get('why') or '',
            'warnings': row.get('warnings') or '',
            'description_excerpt': row.get('description_excerpt') or '',
        })
    jobs.sort(key=lambda j: (-j['score'], j['company'].casefold(), j['title'].casefold()))
    return jobs


def build(root: Path = ROOT) -> Path:
    jobs = load_jobs(root / 'data' / 'jobs.csv')
    template = (root / 'dashboard-src' / 'index.template.html').read_text(encoding='utf-8')
    style = (root / 'dashboard-src' / 'style.css').read_text(encoding='utf-8')
    script = (root / 'dashboard-src' / 'app.js').read_text(encoding='utf-8')
    meta = {'generated_at': datetime.now(timezone.utc).isoformat(), 'total': len(jobs)}
    report = root / 'data' / 'last_run.json'
    if report.exists():
        try:
            run = json.loads(report.read_text(encoding='utf-8'))
            meta['scan_date'] = str(run.get('date') or '')
            meta['observed'] = run.get('observed')
        except (ValueError, OSError):
            pass
    # The coverage report keeps confirmed scans separate from unverified
    # company directory lookups; CSV edits appear after a dashboard-only build.
    config_path = root / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    previous = load_coverage(root)
    # One-time bootstrap from the previous 3.x run; it includes direct scans
    # but must not label empty directory lookups as completed board scans.
    bootstrap = None
    stamp = None
    if not previous and report.exists():
        try:
            last = json.loads(report.read_text(encoding='utf-8'))
            bootstrap = (last.get('source_health') or {}).get('sources', [])
            stamp = last.get('date')
        except (OSError, ValueError):
            pass
    coverage = merge_coverage(config, root / 'companies.csv', previous,
                              source_statuses=bootstrap, today=stamp)
    meta['company_targets'] = len(coverage['companies'])
    payload = json.dumps({'meta': meta, 'jobs': jobs, 'coverage': coverage['companies']}, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('</', '<\\/').replace('<!--', '<\\!--')
    output = template.replace('/*__CSS__*/', style).replace('/*__JS__*/', script).replace('__JOB_DATA_JSON__', payload)
    dest = root / 'dashboard' / 'index.html'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(output, encoding='utf-8')
    print(f'Wrote {dest} with {len(jobs)} jobs ({dest.stat().st_size // 1024} KB)')
    return dest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a standalone internship dashboard.')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.root.resolve())
