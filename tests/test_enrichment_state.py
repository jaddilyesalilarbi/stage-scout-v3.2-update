import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enrichment_state import input_signature, overlay, atomic_json, load_state


class EnrichmentStateTests(unittest.TestCase):
    def row(self):
        return dict(id='stable', company='ACME', title='Mechanical intern', location='Paris',
                    url='https://x.test/apply', status='Applied', first_seen='2026-01-01',
                    score='70', description_excerpt='Old text', note='Call', favorite='yes')

    def result(self, row):
        return dict(id='stable', input_signature=input_signature(row), outcome='enriched',
                    description_status='complete', availability='open', confidence='high',
                    detail_url='https://x.test/job', apply_url='https://x.test/apply',
                    description='Complete official body ' * 40, source='Official API',
                    checked_at='2026-10-20T12:00:00+00:00', error='')

    def test_overlay_preserves_identity_and_tracking_without_mutation(self):
        row = self.row()
        original = copy.deepcopy(row)
        updated = overlay(row, self.result(row))
        for key in ['id', 'status', 'first_seen', 'score', 'url', 'note', 'favorite']:
            self.assertEqual(updated[key], row[key], key)
        self.assertEqual(row, original)
        self.assertEqual(updated['detail_url'], 'https://x.test/job')
        self.assertTrue(updated['description'].startswith('Complete official body'))

    def test_changed_source_does_not_accept_old_cached_content(self):
        row = self.row()
        result = self.result(row)
        row['url'] = 'https://new.test/new-post'
        updated = overlay(row, result)
        self.assertEqual(updated['url'], row['url'])
        self.assertNotIn('Complete official body', updated.get('description', ''))
        self.assertEqual(updated['enrichment_outcome'], 'stale')

    def test_mismatch_never_overwrites_description_or_activates_links(self):
        row = self.row()
        result = dict(self.result(row), outcome='mismatch', confidence='none')
        updated = overlay(row, result)
        self.assertEqual(updated.get('description', ''), '')
        self.assertEqual(updated['description_excerpt'], 'Old text')
        self.assertEqual(updated['detail_url'], '')
        self.assertEqual(updated['apply_url'], '')

    def test_expired_offers_remain_with_tracking(self):
        row = self.row()
        result = dict(self.result(row), outcome='expired', availability='expired')
        updated = overlay(row, result)
        self.assertEqual(updated['id'], 'stable')
        self.assertEqual(updated['availability'], 'expired')
        self.assertEqual(updated['apply_url'], '')
        self.assertTrue(updated['description'].startswith('Complete official body'))

    def test_failed_recheck_keeps_previously_verified_body_as_archive(self):
        row = self.row()
        result = dict(self.result(row), outcome='inaccessible', confidence='none', description='',
                      archived_content=self.result(row))
        updated = overlay(row, result)
        self.assertTrue(updated['description'].startswith('Complete official body'))
        self.assertEqual(updated['description_status'], 'archived')
        self.assertEqual(updated['detail_url'], '')

    def test_atomic_checkpoint_can_be_reloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            state = {'version': 1, 'results': {'stable': self.result(self.row())}}
            atomic_json(path, state)
            self.assertEqual(load_state(path), state)
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_state(path)

    def test_temporary_windows_reader_lock_is_retried_without_losing_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            state = {'version': 1, 'results': {}}
            real_replace = Path.replace
            attempts = []
            def locked_once(source, target):
                attempts.append(1)
                if len(attempts) == 1:
                    raise PermissionError('Windows reader still holds destination')
                return real_replace(source, target)
            with patch('enrichment_state.Path.replace', autospec=True, side_effect=locked_once):
                atomic_json(path, state)
            self.assertEqual(load_state(path), state)
            self.assertEqual(len(attempts), 2)
