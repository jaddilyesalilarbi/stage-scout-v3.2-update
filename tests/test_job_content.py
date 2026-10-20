"""Regression tests for link roles and lossless source descriptions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scout
from build_dashboard import load_jobs


class JobContentTests(unittest.TestCase):
    def test_jobspy_keeps_listing_separate_from_direct_application(self):
        job = scout.normalize_jobspy(dict(title='Mechanical intern', company='ACME',
            job_url='https://indeed.test/viewjob?jk=1',
            job_url_direct='https://employer.test/1/apply'))
        self.assertEqual(job['url'], 'https://indeed.test/viewjob?jk=1')
        self.assertEqual(job['description_url'], 'https://indeed.test/viewjob?jk=1')
        self.assertEqual(job['apply_url'], 'https://employer.test/1/apply')

    def test_application_only_is_not_presented_as_description(self):
        job = scout.normalize_ats(dict(title='Intern', apply_url='https://x.test/apply'))
        self.assertEqual(job['description_url'], '')
        self.assertEqual(job['apply_url'], 'https://x.test/apply')

    def test_invalid_application_does_not_hide_valid_listing(self):
        job = scout.normalize_ats(dict(title='Intern', url='https://x.test/job', apply_url='bad'))
        self.assertIsNotNone(job)
        self.assertEqual(job['description_url'], 'https://x.test/job')
        self.assertEqual(job['apply_url'], '')

    def test_known_application_suffixes_are_resolved_conservatively(self):
        cases = [('https://jobs.lever.co/acme/123/apply?x=1', 'https://jobs.lever.co/acme/123?x=1'),
                 ('https://hemeriagroup.recruitee.com/o/stage/c/new', 'https://hemeriagroup.recruitee.com/o/stage'),
                 ('https://jobs.ashbyhq.com/acme/123/application', 'https://jobs.ashbyhq.com/acme/123')]
        for apply_url, listing in cases:
            with self.subTest(apply_url=apply_url):
                job = scout.normalize_ats(dict(title='Intern', url=apply_url, apply_url=apply_url))
                self.assertEqual(job['description_url'], listing)
                self.assertEqual(job['apply_url'], apply_url)

    def test_ashby_preserves_both_urls(self):
        with patch.object(scout, 'get_json', return_value={'jobs': [dict(title='Intern',
                jobUrl='https://x.test/job', applyUrl='https://x.test/apply', descriptionPlain='Complete text')]}):
            job = scout.fetch_ashby({'id': 'acme', 'name': 'ACME'})[0]
        self.assertEqual(job['description_url'], 'https://x.test/job')
        self.assertEqual(job['apply_url'], 'https://x.test/apply')

    def test_lever_preserves_all_description_sections(self):
        with patch.object(scout, 'get_json', return_value=[dict(text='Intern',
                hostedUrl='https://x.test/job', applyUrl='https://x.test/apply',
                openingPlain='Opening', descriptionPlain='Main body',
                lists=[dict(text='Requirements', content='<li>CAD</li>')],
                additionalPlain='Closing')]):
            job = scout.fetch_lever({'id': 'acme', 'name': 'ACME'})[0]
        self.assertEqual(job['apply_url'], 'https://x.test/apply')
        for text in ['Opening', 'Main body', 'Requirements', 'CAD', 'Closing']:
            self.assertIn(text, job['description'])

    def record(self, text):
        job = scout.make_job('ACME', 'Mechanical design intern', 'Paris, France',
                             'https://x.test/job', text, 'Lever')
        scored = scout.analyze(job, {'minimum_score': 0})
        return dict(scored, id='stable-id')

    def test_long_description_round_trip_and_dashboard(self):
        text = 'Missions\n' + 'Simulation mécanique, matériaux. ' * 6000 + '\nFIN'
        row = scout.as_record(self.record(text), None, '2026-10-20')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            scout.write_rows(path, [row])
            restored = scout.load_rows(path)['stable-id']
            rendered = load_jobs(path)[0]
        self.assertTrue(restored['description'].endswith('FIN'))
        self.assertGreater(len(restored['description']), 131072)
        self.assertEqual(rendered['description'], restored['description'])
        self.assertEqual(len(restored['description_excerpt']), 300)

    def test_refresh_preserves_full_text_and_custom_tracking(self):
        old = dict(scout.as_record(self.record('Complete ' * 200), None, '2026-10-01'),
                   status='Applied', favorite='yes', note='Contact', custom='keep')
        new = scout.as_record(self.record('Short summary'), old, '2026-10-20')
        for key in ['id', 'first_seen', 'status', 'favorite', 'note', 'custom', 'description']:
            self.assertEqual(new[key], old[key], key)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            scout.write_rows(path, [new])
            self.assertEqual(scout.load_rows(path)['stable-id']['custom'], 'keep')

    def test_escaped_html_preserves_paragraphs_without_showing_tags(self):
        job = scout.make_job('ACME', 'Intern', '', 'https://x.test/job',
            '&lt;p&gt;Missions&lt;/p&gt;&lt;ul&gt;&lt;li&gt;CAD&lt;/li&gt;&lt;/ul&gt;', 'Greenhouse')
        self.assertIn('Missions\n', job['description'])
        self.assertNotIn('<p>', job['description'])
        self.assertIn('• CAD', job['description'])

    def test_failed_csv_write_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_bytes(b'id,title\nold,Keep me\n')
            before = path.read_bytes()
            with patch.object(scout.csv.DictWriter, 'writerows', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    scout.write_rows(path, [dict(id='new')])
            self.assertEqual(path.read_bytes(), before)

    def test_missing_official_body_can_use_collected_duplicate_body(self):
        official = dict(source='ATS direct', description='', description_url='https://x.test/job')
        dataset = dict(source='ATS dataset / lever', description='Full source body',
                       description_source='ATS dataset / lever', description_status='source_provided')
        job = scout.prefer(official, dataset)
        self.assertEqual(job['source'], 'ATS direct')
        self.assertEqual(job['description'], 'Full source body')
        self.assertEqual(job['description_source'], 'ATS dataset / lever')
        self.assertEqual(job['description_url'], 'https://x.test/job')

    def test_truncated_official_copy_does_not_discard_full_body_or_application(self):
        official = dict(source='ATS direct', description='First section', description_url='https://x.test/job')
        direct = dict(source='Lever', description='First section\nFull responsibilities and qualifications',
                      apply_url='https://x.test/apply')
        job = scout.prefer(official, direct)
        self.assertEqual(job['source'], 'ATS direct')
        self.assertTrue(job['description'].endswith('qualifications'))
        self.assertEqual(job['description_source'], 'Lever')
        self.assertEqual(job['apply_url'], 'https://x.test/apply')

    def test_adzuna_snippet_marked_partial(self):
        with patch.dict('os.environ', {'ADZUNA_APP_ID': 'test', 'ADZUNA_APP_KEY': 'test'}), \
             patch.object(scout, 'get_json', return_value={'results': [dict(title='Intern',
                 redirect_url='https://x.test/redirect', description='Short snippet')]}):
            job = scout.fetch_adzuna({'adzuna_queries': [{'what': 'intern'}]})[0]
        self.assertEqual(job['description_status'], 'partial')

    def test_legacy_dashboard_keeps_unverified_link_and_excerpt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text('id,url,description_excerpt\nold,https://x.test/unknown,Legacy text\n', encoding='utf-8')
            job = load_jobs(path)[0]
        self.assertEqual(job['url'], 'https://x.test/unknown')
        self.assertEqual(job['description_url'], '')
        self.assertEqual(job['apply_url'], '')
        self.assertEqual(job['description'], '')

    def test_unsafe_urls_filtered_in_all_link_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            scout.write_rows(path, [dict(id='x', url='javascript:alert(1)',
                description_url='https://', apply_url='javascript:alert(2)')])
            job = load_jobs(path)[0]
        self.assertEqual([job['url'], job['description_url'], job['apply_url']], ['', '', ''])

    def test_url_only_identity_preserves_legacy_application_hash(self):
        job = scout.normalize_ats(dict(company='', title='Intern', location='Paris',
            url='https://x.test/job', apply_url='https://x.test/apply'))
        legacy = dict(job, url='https://x.test/apply')
        legacy.pop('_identity_url', None)
        self.assertEqual(scout.job_identity(job), scout.job_identity(legacy))
