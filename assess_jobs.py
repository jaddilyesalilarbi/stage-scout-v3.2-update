#!/usr/bin/env python3
"""Classify saved offers or evaluate a fixed real-data review sample, offline."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import tempfile

from assessment_cache import update_assessments
from build_dashboard import load_jobs, assessment_profile
from enrichment_state import atomic_json, replace_file

ROOT = Path(__file__).resolve().parent


def evaluate(fixture, destination, profile=None):
    review = json.loads(Path(fixture).read_text(encoding='utf-8'))
    cases = review['cases']
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Evaluation sample contains duplicate IDs')
    assessments, _ = update_assessments(cases, profile=profile)
    rows = []
    for case in cases:
        result = assessments[case['id']]
        expected = case['expected_pdm']
        if isinstance(expected, str):
            expected = [expected]
        missing = sorted(set(case.get('expected_categories', [])) - set(result['technical_categories']))
        rows.append(dict(id=case['id'], company=case['company'], title=case['title'],
            stratum=case.get('stratum', ''), expected_pdm=' | '.join(expected),
            actual_pdm=result['pdm_potential'], pdm_agreement=result['pdm_potential'] in expected,
            expected_categories=' | '.join(case.get('expected_categories', [])),
            actual_categories=' | '.join(result['technical_categories']),
            missing_expected_categories=' | '.join(missing), technical_score=result['technical_score'],
            technical_expected=case.get('technical_expected', ''), confidence=result['pdm_confidence'],
            automatic_reason=result['pdm_reason'], independent_review=case.get('review_reason', ''),
            source_mission_quote=case.get('mission_quote', ''),
            needs_review=result['needs_human_review'] or result['pdm_potential'] not in expected or bool(missing)))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', newline='', encoding='utf-8-sig', dir=destination.parent,
            suffix='.tmp', delete=False) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['id'])
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(stream.name)
    replace_file(temporary, destination)
    summary = dict(total=len(rows), pdm_agreement=sum(row['pdm_agreement'] for row in rows),
        all_expected_categories=sum(not row['missing_expected_categories'] for row in rows),
        needs_review=sum(row['needs_review'] for row in rows),
        strata=dict(Counter(row['stratum'] for row in rows)),
        note='Comparison with independent engineering estimates on a fixed real-data sample; not an academic eligibility guarantee.')
    atomic_json(destination.with_suffix('.summary.json'), summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--force', action='store_true', help='Recalculate every automatic assessment; retain manual corrections')
    parser.add_argument('--evaluate', type=Path, help='Evaluate only the frozen review sample before historical classification')
    parser.add_argument('--output', type=Path, default=Path('data/job-assessment-evaluation.csv'))
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = root / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if args.evaluate:
        result = evaluate(args.evaluate, root / args.output, assessment_profile(config))
    else:
        _, result = update_assessments(load_jobs(root / 'data/jobs.csv'), root / 'data/job_assessments.json',
                                       profile=assessment_profile(config), force=args.force)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result.get('cache_error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
