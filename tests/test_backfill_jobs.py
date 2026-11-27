import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import backfill_jobs

import requests
from backfill_jobs import run


class BackfillTests(unittest.TestCase):
    def prepare(self, root):
        (root / 'data').mkdir()
        path = root / 'data/jobs.csv'
        path.write_text('id,company,title,location,url,first_seen,status,score,note\n'
            'a,ACME,Mechanical intern,Paris,https://x.test/1,2026-01-01,Applied,70,Call\n'
            'b,ACME,Structures intern,Lyon,https://x.test/2,2026-01-02,Ignored,80,Keep\n'
            'c,ACME,Test intern,Lille,https://x.test/3,2026-01-03,To review,90,Note\n', encoding='utf-8')
        return path

    def complete(self, row, http):
        return dict(outcome='enriched', confidence='high', description_status='complete',
                    availability='open', detail_url=row['url'], apply_url=row['url'] + '/apply',
                    description='Real official body ' * 30, source='Fixture API', error='')

    def test_full_run_backups_audit_resume_and_original_csv_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.prepare(root)
            before = path.read_bytes()
            calls = []
            def retrieve(row, http):
                calls.append(row['id'])
                if row['id'] == 'b':
                    return dict(outcome='expired', availability='expired', confidence='high')
                if row['id'] == 'c':
                    raise requests.Timeout('Read timed out')
                return self.complete(row, http)
            with patch('backfill_jobs.retrieve', side_effect=retrieve):
                summary = run(root, workers=2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(summary['total'], 3)
            self.assertEqual(summary['processed'], 3)
            self.assertEqual(summary['complete_descriptions'], 1)
            self.assertEqual(summary['expired'], 1)
            self.assertEqual(summary['remaining'], 0)
            self.assertEqual(len(list(root.glob('.backfill-backups/*/jobs.csv'))), 1)
            with (root / 'data/job-enrichment-audit.csv').open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual([r['id'] for r in csv.DictReader(stream)], ['a', 'b', 'c'])
            calls.clear()
            with patch('backfill_jobs.retrieve', side_effect=lambda row, http: (calls.append(row['id']) or self.complete(row, http))):
                resumed = run(root, workers=2)
            self.assertEqual(calls, ['c'])
            self.assertEqual(resumed['complete_descriptions'], 2)
            self.assertEqual(path.read_bytes(), before)
            state = json.loads((root / 'data/job-enrichment-state.json').read_text(encoding='utf-8'))
            self.assertEqual(set(state['results']), {'a', 'b', 'c'})
            self.assertEqual(state['results']['c']['attempts'], 2)

    def test_interrupt_keeps_completed_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.prepare(root)
            before = path.read_bytes()
            def interrupted(row, http):
                if row['id'] == 'b':
                    raise KeyboardInterrupt()
                return self.complete(row, http)
            with patch('backfill_jobs.retrieve', side_effect=interrupted):
                summary = run(root, workers=1)
            self.assertTrue(summary['interrupted'])
            state = json.loads((root / 'data/job-enrichment-state.json').read_text(encoding='utf-8'))
            self.assertEqual(set(state['results']), {'a'})
            with patch('backfill_jobs.retrieve', side_effect=self.complete):
                summary = run(root, workers=1)
            self.assertEqual(summary['remaining'], 0)
            self.assertEqual(path.read_bytes(), before)

    def test_deadline_does_not_falsely_mark_unattempted_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            with patch('backfill_jobs.retrieve') as retrieve:
                summary = run(root, workers=1, max_seconds=0)
            retrieve.assert_not_called()
            self.assertEqual(summary['processed'], 0)
            self.assertEqual(summary['remaining'], 3)

    def test_duplicate_ids_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.prepare(root)
            path.write_text(path.read_text().replace('b,ACME', 'a,ACME'), encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                run(root)
            self.assertEqual(path.read_bytes(), before)

    def test_failed_forced_retry_preserves_previously_recovered_body(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            with patch('backfill_jobs.retrieve', side_effect=self.complete):
                run(root, workers=1)
            with patch('backfill_jobs.retrieve', side_effect=requests.Timeout('Temporarily unavailable')):
                run(root, workers=1, retry=True)
            state = json.loads((root / 'data/job-enrichment-state.json').read_text(encoding='utf-8'))
            self.assertTrue(state['results']['a']['archived_content']['description'].startswith('Real official body'))

    def test_shorter_success_keeps_previous_body_in_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            with patch('backfill_jobs.retrieve', side_effect=self.complete):
                run(root, workers=1)
            with patch('backfill_jobs.retrieve', side_effect=lambda row, http: dict(self.complete(row, http), description='New shorter body')):
                run(root, workers=1, retry=True)
            state = json.loads((root / 'data/job-enrichment-state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['results']['a']['description'], 'New shorter body')
            self.assertTrue(state['results']['a']['archived_content']['description'].startswith('Real official body'))

    def test_budgeted_resume_prioritizes_never_attempted_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            clock, calls = [0], []
            def failure(row, http):
                calls.append(row['id'])
                clock[0] += 2
                return dict(outcome='inaccessible')
            with patch('backfill_jobs.retrieve', side_effect=failure), \
                 patch('backfill_jobs.time.monotonic', side_effect=lambda: clock[0]):
                for _ in range(3):
                    run(root, workers=1, max_seconds=1)
            self.assertEqual(calls, ['a', 'b', 'c'])

    def test_checkpoint_write_failure_reports_only_durable_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare(root)
            real_write = backfill_jobs.atomic_json
            def disk_full(path, value):
                if path.name == 'job-enrichment-state.json' and value.get('results'):
                    raise OSError('Disk full')
                return real_write(path, value)
            with patch('backfill_jobs.retrieve', side_effect=self.complete), \
                 patch('backfill_jobs.atomic_json', side_effect=disk_full):
                with self.assertRaises(OSError):
                    run(root, workers=1)
            summary = json.loads((root / 'data/job-enrichment-summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['processed'], 0)
            self.assertEqual(summary['remaining'], 3)
            self.assertIn('Disk full', summary['run_error'])
