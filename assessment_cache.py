"""Versioned, incremental assessments; independent from source and tracking data."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import job_classifier
from job_classifier import classify, RULES_VERSION, PDM_LABELS, TECHNICAL_CATEGORIES
from enrichment_state import atomic_json

SCHEMA_VERSION = 1
INPUT_FIELDS = ('title', 'company', 'location', 'language', 'duration', 'start_date', 'description_status', 'structured')


def input_hash(job, profile=None):
    body = job.get('description') or job.get('description_excerpt') or ''
    source = Path(job_classifier.__file__).read_text(encoding='utf-8').replace('\r\n', '\n')
    payload = {'rules_version': RULES_VERSION, 'rules_hash': hashlib.sha256(source.encode()).hexdigest(),
               'profile': profile or {}, 'body': body,
               'fields': {key: job.get(key, '') for key in INPUT_FIELDS}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fallback_assessment(error):
    unknown = {'status': 'unknown', 'value': '', 'evidence': [], 'reason': 'Analyse indisponible.'}
    return dict(rules_version=RULES_VERSION, pdm_potential='uncertain', pdm_label=PDM_LABELS['uncertain'],
        pdm_explicit=False, pdm_reason='Analyse indisponible : examiner les missions manuellement.',
        pdm_confidence='low', missing_information=['Analyse des missions à vérifier'],
        technical_categories=['Other'], technical_score=0, technical_reasons=['Analyse indisponible.'],
        mission_evidence=[], constraints={key: dict(unknown) for key in (
            'duration', 'start_date', 'languages', 'location', 'education', 'eligibility')},
        constraint_status='unknown', needs_human_review=True, error=str(error))


def validate_assessment(record):
    if (not isinstance(record, dict) or not isinstance(record.get('pdm_potential'), str)
            or record['pdm_potential'] not in PDM_LABELS):
        raise ValueError('Invalid PDM assessment')
    score = record.get('technical_score')
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError('Invalid technical score')
    cats = record.get('technical_categories')
    if not isinstance(cats, list) or not cats or any(cat not in TECHNICAL_CATEGORIES for cat in cats):
        raise ValueError('Invalid technical categories')
    if not isinstance(record.get('pdm_reason'), str) or not isinstance(record.get('mission_evidence'), list):
        raise ValueError('Missing explanation or mission evidence')
    if record.get('pdm_confidence') not in ('high', 'medium', 'low'):
        raise ValueError('Invalid confidence')
    constraints = record.get('constraints')
    if not isinstance(constraints, dict) or any(
            not isinstance(value, dict) or value.get('status') not in ('compatible', 'incompatible', 'unknown')
            for value in constraints.values()):
        raise ValueError('Invalid constraints')
    return record


def load_cache(path):
    if not path or not Path(path).exists():
        return {'schema_version': SCHEMA_VERSION, 'assessments': {}}
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION
            or not isinstance(value.get('assessments'), dict)
            or any(not isinstance(record, dict) for record in value['assessments'].values())):
        raise ValueError('Invalid assessment cache; existing corrections were preserved')
    return value


def update_assessments(jobs, path=None, *, profile=None, force=False):
    """Classify changed inputs only and retain manual overrides and retired IDs."""
    cache_error = ''
    try:
        cache = load_cache(path)
    except (ValueError, OSError) as error:
        cache_error = str(error)
        cache = {'schema_version': SCHEMA_VERSION, 'assessments': {}}
    saved = dict(cache['assessments'])
    current = {}
    classified = reused = errors = 0
    for job in jobs:
        job_id = job.get('id')
        if not job_id or job_id in current:
            continue
        old = saved.get(job_id, {})
        fingerprint = input_hash(job, profile)
        try:
            if not force and old.get('input_hash') == fingerprint and not old.get('error'):
                validate_assessment(old)
                current[job_id] = old
                reused += 1
                continue
        except ValueError:
            pass
        try:
            record = validate_assessment(classify(dict(job), profile))
        except Exception as error:
            record = fallback_assessment(f'{type(error).__name__}: {error}')
            errors += 1
        record = {**record, 'id': job_id, 'input_hash': fingerprint,
                  'assessed_at': datetime.now(timezone.utc).isoformat()}
        # These are user-owned values, never classifier output.
        if isinstance(old.get('manual_override'), dict):
            record['manual_override'] = dict(old['manual_override'])
        saved[job_id] = current[job_id] = record
        classified += 1
    counts = Counter(record['pdm_potential'] for record in current.values())
    cats = Counter(cat for record in current.values() for cat in record['technical_categories'])
    summary = dict(total=len(current), classified=classified, reused=reused, errors=errors,
        pdm_counts={key: counts[key] for key in PDM_LABELS}, technical_categories=dict(sorted(cats.items())),
        uncertain=counts['uncertain'], needs_human_review=sum(bool(r.get('needs_human_review')) for r in current.values()),
        manual_overrides=sum(bool(r.get('manual_override')) for r in current.values()),
        rules_version=RULES_VERSION, persisted=bool(path and not cache_error), cache_error=cache_error)
    if path and not cache_error:
        # A cache hit must not rewrite dates or churn Git on every dashboard build.
        value = {**cache, 'schema_version': SCHEMA_VERSION, 'rules_version': RULES_VERSION,
                 'assessments': saved, 'profile': profile or {}}
        if value != cache:
            atomic_json(Path(path), value)
    return current, summary
