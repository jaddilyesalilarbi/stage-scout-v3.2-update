import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def run_migration(self, path, *args):
        return subprocess.run([sys.executable, str(ROOT / 'migrate_job_content.py'),
                               '--jobs', str(path), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8')

    def test_dry_run_is_offline_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,url,description_excerpt\nold,https://jobs.lever.co/acme/1/apply,Old text\n', encoding='utf-8')
            before = path.read_bytes()
            result = self.run_migration(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            self.assertEqual(json.loads(result.stdout)['changed'], 1)
            self.assertFalse(json.loads(result.stdout)['applied'])

    def test_apply_preserves_all_records_tracking_and_backup_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,company,title,location,url,status,first_seen,last_seen,description_excerpt,note,favorite,custom\n'
                'old,ACME,Mechanical intern,Paris,https://x.test/1/apply,Applied,2026-01-01,2026-10-01,Old text,Call,yes,keep\n'
                'other,Other,Summer intern,USA,https://x.test/2,Ignored,2026-01-02,2026-09-01,Other text,,,keep2\n', encoding='utf-8')
            before = path.read_bytes()
            raw = Path(folder) / 'raw.json'
            raw.write_text(json.dumps({'jobs': [dict(company='ACME', title='Mechanical intern', location='Paris',
                url='https://x.test/1', description_url='https://x.test/1', apply_url='https://x.test/1/apply',
                description='Complete body ' * 50, source='ATS direct')]}), encoding='utf-8')
            result = self.run_migration(path, '--raw-input', raw, '--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(Path(summary['backup']).read_bytes(), before)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r['id'] for r in rows], ['old', 'other'])
            for key, value in dict(status='Applied', first_seen='2026-01-01', last_seen='2026-10-01',
                                   note='Call', favorite='yes', custom='keep').items():
                self.assertEqual(rows[0][key], value)
            self.assertEqual(rows[0]['description_url'], 'https://x.test/1')
            self.assertTrue(rows[0]['description'].startswith('Complete body'))
            self.assertEqual(rows[1]['description_excerpt'], 'Other text')
            self.assertEqual(rows[1]['description'], '')
            self.assertEqual(rows[1]['description_url'], '')
            self.assertEqual(rows[1]['url'], 'https://x.test/2')
            after = path.read_bytes()
            second = self.run_migration(path, '--raw-input', raw, '--apply')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout)['changed'], 0)
            self.assertEqual(path.read_bytes(), after)

    def test_duplicate_ids_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,url\na,https://x.test/1\na,https://x.test/2\n', encoding='utf-8')
            before = path.read_bytes()
            result = self.run_migration(path, '--apply')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), before)

    def test_limit_only_updates_requested_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,url\na,https://jobs.lever.co/acme/1/apply\nb,https://jobs.lever.co/acme/2/apply\n', encoding='utf-8')
            result = self.run_migration(path, '--limit', 1, '--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                a, b = csv.DictReader(stream)
            self.assertEqual(a['description_url'], 'https://jobs.lever.co/acme/1')
            self.assertEqual(b['description_url'], '')
            result = self.run_migration(path, '--offset', 1, '--limit', 1, '--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                a, b = csv.DictReader(stream)
            self.assertEqual(b['description_url'], 'https://jobs.lever.co/acme/2')

    def test_conflicting_candidates_are_reported_and_not_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,company,title,location,url\na,ACME,Intern,Paris,https://x.test/old\n', encoding='utf-8')
            raw = Path(folder) / 'raw.json'
            raw.write_text(json.dumps({'jobs': [dict(company='ACME', title='Intern', location='Paris',
                description_url=f'https://x.test/{i}', description=f'Body {i}') for i in (1, 2)]}), encoding='utf-8')
            result = self.run_migration(path, '--raw-input', raw, '--apply')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['ambiguous'], ['a'])
            with path.open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['description'], '')


if __name__ == '__main__':
    unittest.main()
