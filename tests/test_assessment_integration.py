"""Exercise the real CSV -> enrichment -> assessment -> static dashboard path."""
import csv
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from build_dashboard import build
from enrichment_state import input_signature

ROOT = Path(__file__).resolve().parents[1]


class AssessmentIntegrationTests(unittest.TestCase):
    def test_enrichment_is_classified_and_changed_jobs_only_are_recomputed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'dashboard-src').mkdir()
            for filename in ('app.js', 'style.css', 'index.template.html'):
                (root / 'dashboard-src' / filename).write_bytes((ROOT / 'dashboard-src' / filename).read_bytes())
            rows = [dict(id='stable', title='Engineering internship', company='ACME', location='Paris, FR',
                         description_excerpt='Company presentation only.', url='https://example.com/jobs/1')]
            path = root / 'data/jobs.csv'
            def write_rows():
                with path.open('w', newline='', encoding='utf-8-sig') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            write_rows()
            original = path.read_bytes()
            result = dict(id='stable', input_signature=input_signature(rows[0]), confidence='high', outcome='enriched',
                          description='Missions: Design a mechanical prototype and validate its performance with experimental tests.',
                          description_status='complete', description_url='https://example.com/jobs/1')
            state_path = root / 'data/job-enrichment-state.json'
            state_path.write_text(json.dumps({'version': 1, 'results': {'stable': result}}), encoding='utf-8')
            (root / 'config.json').write_text(json.dumps({'priority_companies': ['ACME']}), encoding='utf-8')
            html = build(root).read_text(encoding='utf-8')
            data = json.loads(re.search(r'<script type="application/json" id="job-data">(.*?)</script>', html, re.S)[1])
            job = data['jobs'][0]
            self.assertEqual(job['id'], 'stable')
            self.assertTrue(job['priority_company'])
            self.assertEqual(job['assessment']['pdm_potential'], 'high')
            self.assertIn('Mechanical Design', job['assessment']['technical_categories'])
            self.assertEqual(path.read_bytes(), original)
            cache = root / 'data/job_assessments.json'
            before = cache.read_bytes()
            with patch('assessment_cache.classify', side_effect=AssertionError('Unexpected reclassification')):
                build(root)
            self.assertEqual(cache.read_bytes(), before)
            rows.append(dict(rows[0], id='new', title='New internship'))
            write_rows()
            build(root)
            records = json.loads(cache.read_text(encoding='utf-8'))['assessments']
            self.assertEqual(set(records), {'stable', 'new'})
            self.assertEqual(records['stable'], json.loads(before)['assessments']['stable'])

    def test_publication_workflows_persist_classification(self):
        for name in ('daily-scout', 'build-dashboard', 'bulk-company-audit', 'enrich-existing-jobs', 'reclassify-jobs'):
            text = (ROOT / '.github/workflows' / (name + '.yml')).read_text(encoding='utf-8')
            with self.subTest(workflow=name):
                self.assertIn('python build_dashboard.py', text)
                self.assertIn('git add', text)
                self.assertRegex(text, r'git add[^\n]*data/job_assessments.json')
                self.assertIn('group: daily-stage-scout', text)
        publish = (ROOT / '.github/workflows/publish-dashboard.yml').read_text(encoding='utf-8')
        self.assertIn('- Reclassify jobs', publish)
