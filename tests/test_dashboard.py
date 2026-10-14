from __future__ import annotations

import csv
from pathlib import Path
import re
import tempfile
import unittest

from build_dashboard import build, infer_country, load_jobs

ROOT = Path(__file__).resolve().parents[1]

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'dashboard-src').mkdir()
        for file in ['index.template.html', 'style.css', 'app.js']:
            (self.root / 'dashboard-src' / file).write_bytes((ROOT / 'dashboard-src' / file).read_bytes())

    def tearDown(self): self.tmp.cleanup()

    def write_jobs(self, rows):
        fields = ['id','first_seen','last_seen','status','score','company','title','location','kind','duration','source','verification','posted_at','url','why','warnings','description_excerpt']
        with (self.root / 'data' / 'jobs.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_countries_codes(self):
        self.assertEqual(infer_country('Zurich, ch'), 'Suisse')
        self.assertEqual(infer_country('Paris, France'), 'France')
        self.assertEqual(infer_country('Eindhoven, NL'), 'Pays-Bas')
        self.assertEqual(infer_country(''), 'Non precise')

    def test_600_rows_rendered_in_output(self):
        self.write_jobs([dict(id=str(i), first_seen='2026-10-14', score=90, company='Swiss Engineering', title=f'Intern {i}', location='Lausanne, CH', url=f'https://example.com/{i}') for i in range(600)])
        html = build(self.root).read_text('utf-8')
        self.assertIn('"total":600', html)
        self.assertIn('"id":"599"', html)
        self.assertEqual(html.count('"company":"Swiss Engineering"'), 600)
        self.assertIn('job-list', html)
        self.assertIn('export-track', html)

    def test_protects_against_embedded_script_and_bad_urls(self):
        self.write_jobs([dict(id='abc', company='</script><script>alert(1)</script>', title='Mechanical intern', score=70, url='javascript:alert(1)', description_excerpt='<script>evil</script>')])
        html = build(self.root).read_text('utf-8')
        self.assertNotIn('</script><script>alert(1)</script>', html)
        self.assertIn('<\\/script>', html)
        self.assertNotIn('javascript:alert(1)', html)

    def test_missing_data_errors_loudly(self):
        with self.assertRaisesRegex(FileNotFoundError, 'jobs.csv'):
            load_jobs(self.root/'data'/'jobs.csv')

    def test_filters_duplicate_ids_and_nonnumeric_scores(self):
        self.write_jobs([dict(id='a', company='A', title='First', score='abc'),dict(id='a', company='A', title='Duplicate', score=101)])
        jobs=load_jobs(self.root/'data'/'jobs.csv')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['score'], 0)
        self.assertEqual(jobs[0]['title'],'First')

if __name__ == '__main__': unittest.main()
