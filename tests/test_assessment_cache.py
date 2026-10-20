import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from assessment_cache import update_assessments, input_hash


class AssessmentCacheTests(unittest.TestCase):
    def jobs(self):
        return [dict(id='stable', title='Mechanical intern', company='ACME', location='Paris, France',
            description='Design a mechanical prototype and validate its performance with experimental tests.',
            description_status='complete', status='Applied', first_seen='2026-01-01', score=70)]

    def test_cache_reuses_results_and_invalidates_changed_body(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            jobs = self.jobs()
            before = copy.deepcopy(jobs)
            first, summary = update_assessments(jobs, path)
            self.assertEqual(summary['classified'], 1)
            contents = path.read_bytes()
            with patch('assessment_cache.classify', side_effect=AssertionError('Cache was not reused')):
                second, summary = update_assessments(jobs, path)
            self.assertEqual(summary['reused'], 1)
            self.assertEqual(first, second)
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual(jobs, before)
            jobs[0]['description'] += ' Develop a new finite element model.'
            third, summary = update_assessments(jobs, path)
            self.assertEqual(summary['classified'], 1)
            self.assertNotEqual(first['stable']['input_hash'], third['stable']['input_hash'])

    def test_force_preserves_manual_override_and_all_historical_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            update_assessments(self.jobs(), path)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['assessments']['stable']['manual_override'] = {'pdm_potential': 'medium', 'reason': 'Check autonomy'}
            data['assessments']['old-id'] = {'manual_override': {'pdm_potential': 'low'}, 'input_hash': 'old'}
            path.write_text(json.dumps(data), encoding='utf-8')
            current, summary = update_assessments(self.jobs(), path, force=True)
            self.assertEqual(current['stable']['manual_override']['pdm_potential'], 'medium')
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertIn('old-id', saved['assessments'])
            self.assertEqual(set(current), {'stable'})
            self.assertEqual(summary['total'], 1)

    def test_failed_one_record_is_uncertain_and_other_records_continue(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            jobs = self.jobs() + [dict(self.jobs()[0], id='second')]
            import assessment_cache
            real_classify = assessment_cache.classify
            def classify(row, profile=None):
                if row['id'] == 'stable':
                    raise ValueError('One malformed record')
                return real_classify(row, profile)
            with patch('assessment_cache.classify', side_effect=classify):
                current, summary = update_assessments(jobs, path)
            self.assertEqual(set(current), {'stable', 'second'})
            self.assertEqual(current['stable']['pdm_potential'], 'uncertain')
            self.assertIn('One malformed record', current['stable']['error'])
            self.assertEqual(summary['errors'], 1)

    def test_profile_and_rules_version_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            first, _ = update_assessments(self.jobs(), path, profile={'duration_months': [5, 6]})
            second, _ = update_assessments(self.jobs(), path, profile={'duration_months': [3, 4]})
            self.assertNotEqual(first['stable']['input_hash'], second['stable']['input_hash'])
            with patch('assessment_cache.RULES_VERSION', 'future-rules'):
                third, summary = update_assessments(self.jobs(), path, profile={'duration_months': [3, 4]})
            self.assertEqual(summary['classified'], 1)
            self.assertNotEqual(second['stable']['input_hash'], third['stable']['input_hash'])

    def test_corrupt_cache_is_not_overwritten_and_build_can_continue(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            path.write_text('{bad cache', encoding='utf-8')
            before = path.read_bytes()
            current, summary = update_assessments(self.jobs(), path)
            self.assertIn('stable', current)
            self.assertFalse(summary['persisted'])
            self.assertTrue(summary['cache_error'])
            self.assertEqual(path.read_bytes(), before)

    def test_hash_ignores_tracking_and_old_score(self):
        row = self.jobs()[0]
        changed = dict(row, status='Interview', score=99, favorite=True, note='Call', selection_decision='retained')
        self.assertEqual(input_hash(row), input_hash(changed))

    def test_structured_duration_and_start_change_invalidate_cache(self):
        row = self.jobs()[0]
        self.assertNotEqual(input_hash(row), input_hash(dict(row, duration='3 months')))
        self.assertNotEqual(input_hash(row), input_hash(dict(row, start_date='2027-02-01')))

    def test_malformed_cached_enum_is_recomputed_without_losing_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'job_assessments.json'
            row = self.jobs()[0]
            path.write_text(json.dumps({'schema_version': 1, 'assessments': {'stable': {
                'input_hash': input_hash(row), 'pdm_potential': [],
                'manual_override': {'pdm_potential': 'medium'}}}}), encoding='utf-8')
            current, summary = update_assessments([row], path)
            self.assertEqual(summary['classified'], 1)
            self.assertEqual(current['stable']['manual_override']['pdm_potential'], 'medium')
            self.assertIsInstance(current['stable']['pdm_potential'], str)
