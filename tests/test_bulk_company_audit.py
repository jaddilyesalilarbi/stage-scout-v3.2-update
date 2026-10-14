"""Offline smoke tests for the one-off full employer audit."""
from __future__ import annotations

import csv
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bulk_company_audit as bulk
from company_watchlist import load_watchlist


class BulkCompanyAuditTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / 'companies.csv').write_text(
            'name,country,careers_url,enabled,notes\n'
            'ABB,CH,,yes,\n'
            'Airbus,FR,,yes,\n'
            'Contoso,FR,,yes,\n'
            'Disabled,US,,no,\n', encoding='utf-8-sig')
        (self.root / 'config.json').write_text(json.dumps({'company_careers': [
            {'name': 'ABB', 'url': 'https://jobs.ashbyhq.com/abb'}]}), encoding='utf-8')
        (self.root / 'data').mkdir()

    def tearDown(self):
        self.dir.cleanup()

    def test_every_active_company_once_and_legacy_url_reused(self):
        targets, all_targets = bulk.active_targets(self.root)
        self.assertEqual(len(targets), 3)
        self.assertEqual(len(all_targets), 4)
        self.assertEqual(targets[0]['name'], 'ABB')
        self.assertEqual(targets[0]['url_origin'], 'config_direct')
        self.assertEqual(targets[0]['careers_url'], 'https://jobs.ashbyhq.com/abb')
        parts = self.root / 'bulk-parts'
        def fake_scan(root, target, timeout, scratch):
            outcome = 'scanned' if target['name'] in {'ABB', 'Airbus'} else 'not_found'
            url = ('https://jobs.ashbyhq.com/' + target['name'].lower()) if outcome == 'scanned' else ''
            return {'stage': 'watchlist', 'name': target['name'], 'country': target['country'],
                    'status': 'completed', 'count': 0, 'duration_seconds': 0.0, 'jobs': [], 'errors': [],
                    'scan_info': {'outcome': outcome, 'resolved_url': url,
                                  'candidate_urls': [url] if url else [],
                                  'raw_postings': 0, 'message': ''}}
        with patch.object(bulk, 'scan_one', side_effect=fake_scan):
            for index in range(2):
                bulk.run_shard(self.root, index, 2, 10, parts)
        counts = [len(json.loads(path.read_text())['results']) for path in sorted(parts.glob('part-*.json'))]
        self.assertEqual(counts, [2, 1])
        out = bulk.merge_results(self.root, parts, self.root / 'data', expected_shards=2)
        self.assertEqual(out['enabled'], 3)
        self.assertEqual(out['attempted'], 3)
        self.assertEqual(out['outcomes']['scanned'], 2)
        self.assertEqual(out['outcomes']['not_found'], 1)
        self.assertEqual(out['new_verified_urls_written_to_companies_csv'], 2)
        rows = {row['name']:row for row in load_watchlist(self.root / 'companies.csv')}
        self.assertEqual(rows['Airbus']['careers_url'], 'https://jobs.ashbyhq.com/airbus')
        self.assertEqual(rows['Contoso']['careers_url'], '')
        self.assertFalse(rows['Disabled']['enabled'])
        coverage = json.loads((self.root / 'data' / 'coverage.json').read_text())
        stats = {row['name']: row for row in coverage['companies']}
        self.assertEqual(stats['Airbus']['last_outcome'], 'scanned')
        self.assertEqual(stats['Contoso']['last_outcome'], 'not_found')
        self.assertNotIn('last_success', stats['Contoso'])
        self.assertFalse((self.root / 'data' / 'jobs.csv').exists())
        with (self.root / 'data' / 'company-url-audit.csv').open(encoding='utf-8-sig', newline='') as handle:
            audit = list(csv.DictReader(handle, delimiter=';'))
        self.assertEqual(len(audit), 4)
        self.assertTrue(all(x['search_for_careers'].startswith('https://www.google.com/search?q=') for x in audit))

    def test_partial_shards_fail_loudly_instead_of_publishing_false_coverage(self):
        parts = self.root / 'bulk-parts'
        parts.mkdir()
        (parts/'part-00.json').write_text(json.dumps({
            'shard': 0, 'shards': 2, 'targets_total': 3, 'results': []}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Missing shards'):
            bulk.merge_results(self.root, parts, self.root/'data', expected_shards=2)

    def test_do_not_autofill_ambiguous_directory_board(self):
        targets = load_watchlist(self.root / 'companies.csv')
        status = {'stage':'watchlist','name':'Airbus','status':'completed',
                  'scan_info':{'outcome':'scanned','resolved_url':'https://jobs.ashbyhq.com/airbus',
                               'candidate_urls':['https://jobs.ashbyhq.com/airbus',
                                                 'https://boards.greenhouse.io/airbus']}}
        self.assertEqual(bulk.fill_verified_urls(self.root, {'airbus':status}, targets), 0)
        self.assertEqual(load_watchlist(self.root/'companies.csv')[1]['careers_url'], '')

    def test_timeout_reports_as_unscanned(self):
        target = {'name': 'Contoso', 'country':'FR', 'careers_url':''}
        with patch.object(bulk.subprocess, 'run', side_effect=bulk.subprocess.TimeoutExpired('x', 1)):
            with tempfile.TemporaryDirectory() as tmp:
                result = bulk.scan_one(self.root, target, 1, Path(tmp))
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['scan_info']['outcome'], 'timeout')
        self.assertEqual(result['count'], 0)


if __name__ == '__main__':
    unittest.main()
