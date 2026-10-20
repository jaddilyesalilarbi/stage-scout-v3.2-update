import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_dashboard import load_jobs


class DashboardEnrichmentTests(unittest.TestCase):
    def test_sidecar_overlays_matching_record_without_rewriting_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            row = dict(id='stable', company='ACME', title='Intern', location='Paris',
                       url='https://example.com/old', description_url='', apply_url='',
                       description='Old body', status='Applied')
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            before = path.read_bytes()
            signature = hashlib.sha256(json.dumps({k: row.get(k, '') for k in
                ('id', 'company', 'title', 'location', 'url', 'description_url', 'apply_url')},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            result = dict(id='stable', input_signature=signature, original_url=row['url'],
                checked_at='2026-10-20T12:30:00+00:00', outcome='enriched',
                availability='open', description_status='complete',
                detail_url='https://example.com/confirmed', apply_url='https://example.com/apply',
                description='Full body <script>text</script>', source='Official ATS',
                confidence='high', evidence='Same ID', error='')
            sidecar = path.with_name('job-enrichment-state.json')
            sidecar.write_text(json.dumps({'version': 1, 'results': {'stable': result}}), encoding='utf-8')
            job = load_jobs(path)[0]
            self.assertEqual(job['description'], result['description'])
            self.assertEqual(job['detail_url'], result['detail_url'])
            self.assertEqual(job['description_url'], result['detail_url'])
            self.assertEqual(job['availability'], 'open')
            self.assertEqual(job['enrichment_outcome'], 'enriched')
            self.assertEqual(job['enrichment_checked_at'], result['checked_at'])
            self.assertEqual(job['enrichment_confidence'], 'high')
            self.assertEqual(job['status'], 'Applied')
            self.assertEqual(path.read_bytes(), before)

            # A source update invalidates the old match and keeps its own content.
            row['title'] = 'New source title'
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            fresh = load_jobs(path)[0]
            self.assertEqual(fresh['description'], 'Old body')
            self.assertEqual(fresh['enrichment_outcome'], 'stale')

    def test_absent_or_invalid_sidecar_preserves_legacy_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,url,description_url,description\nlegacy,https://example.com/old,https://example.com/detail,Old body\n', encoding='utf-8')
            for text in (None, '{bad json', '{"version":1,"results":[]}'):
                if text is not None:
                    path.with_name('job-enrichment-state.json').write_text(text, encoding='utf-8')
                job = load_jobs(path)[0]
                self.assertEqual(job['description'], 'Old body')
                self.assertEqual(job['detail_url'], 'https://example.com/detail')
                self.assertEqual(job['enrichment_outcome'], '')


if __name__ == '__main__':
    unittest.main()
