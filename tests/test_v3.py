"""V3: language exclusions, ATS directory discovery and source-wide search."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scout

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text(encoding='utf-8'))


def sample(title, description, location='Zurich, Switzerland', language=''):
    return scout.make_job('Test Industry', title, location, 'https://jobs.example.test/123',
                          description, 'ATS dataset', language=language, kind_hint='intern')


class LanguageTests(unittest.TestCase):
    def test_excludes_german_job_title(self):
        self.assertTrue(scout.language_excluded(sample('Praktikum Maschinenbau', 'Structural design, CAD and testing.'), CONFIG))

    def test_excludes_explicit_locale_even_if_title_english(self):
        self.assertTrue(scout.language_excluded(sample('Mechanical Design Intern', 'CAD design work.', language='de-DE'), CONFIG))

    def test_excludes_german_prose(self):
        job = sample('Mechanical Engineering Intern', (
            'Wir suchen dich fur unser Team im Bereich Entwicklung und Konstruktion. '
            'Deine Aufgaben sind die Mitarbeit an Projekten und Konstruktionen, sowie '
            'die Prufung von Materialien und technischen Zeichnungen. '
            'Du hast Kenntnisse und Erfahrung im Bereich Maschinenbau, '
            'du kannst dich selbststandig einbringen und unsere Arbeit verbessern. '
        ) * 3)
        self.assertTrue(scout.language_excluded(job, CONFIG))

    def test_english_listing_in_switzerland_passes(self):
        job = sample('Mechanical Design Intern',
                     'We are seeking a mechanical engineering intern to design CAD components and work with composite structures for a six-month internship in Zurich.',
                     language='en')
        self.assertFalse(scout.language_excluded(job, CONFIG))
        self.assertIsNotNone(scout.analyze(job, CONFIG))

    def test_mandatory_german_rejected(self):
        job = sample('Mechanical Engineering Intern', 'CAD and FEA. Fluent German required.')
        self.assertTrue(scout.language_excluded(job, CONFIG))

    def test_german_optional_is_allowed(self):
        job = sample('Mechanical Engineering Intern', 'CAD and FEA. German is a plus, English mandatory.')
        self.assertFalse(scout.language_excluded(job, CONFIG))

    def test_english_or_german_allowed(self):
        job = sample('Mechanical Engineering Intern', 'Applicants need fluency in English or German.')
        self.assertFalse(scout.language_excluded(job, CONFIG))


class DiscoveryTests(unittest.TestCase):
    def test_company_name_exactness(self):
        self.assertEqual(scout.company_key('Airbus AG'), scout.company_key('Airbus'))
        self.assertNotEqual(scout.company_key('Airbus Defence'), scout.company_key('Airbus'))

    def test_discovers_only_exact_company(self):
        jobs = [{'company': 'Airbus', 'title': 'Mechanical Intern', 'location': 'Paris',
                 'apply_url': 'https://example.com/jobs/1', 'description': 'Intern CAD projects',
                 'ats_type': 'greenhouse'}]
        calls = []
        class FakeFrame:
            def to_dict(self, how):
                return [
                    {'name': 'Airbus Parts', 'url': 'https://jobs.ashbyhq.com/notairbus'},
                    {'name': 'Airbus AG', 'url': 'https://jobs.ashbyhq.com/airbus'},
                ]
        def scraper_for_url(url):
            calls.append(url)
            return SimpleNamespace(fetch=lambda: jobs)
        fake = SimpleNamespace(find_company=lambda *args, **kwargs: FakeFrame(),
                               get_scraper_for_url=scraper_for_url)
        config = {'company_discovery': {'enabled': True, 'companies_per_day': 1},
                  'priority_companies': ['Airbus'], 'company_careers': []}
        with patch.dict(sys.modules, {'ats_scrapers': fake}):
            batch, errors = scout.fetch_discovered_careers(config)
        self.assertEqual(len(batch), 1)
        self.assertEqual(errors, [])
        self.assertEqual(calls, ['https://jobs.ashbyhq.com/airbus'])
        self.assertEqual(batch[0]['source'], 'ATS company discovery')

    def test_source_sweep_searches_all_related_internships(self):
        frame = pd.DataFrame([
            {'company': 'A', 'title': 'Mechanical Intern', 'location': 'Paris',
             'apply_url': 'https://jobs.example.test/1', 'description': 'CAD design', 'employment_type': 'intern'},
            {'company': 'B', 'title': 'Stage ingénieur essais', 'location': 'Lyon',
             'apply_url': 'https://jobs.example.test/2', 'description': 'Testing of prototypes', 'employment_type': 'intern'},
            {'company': 'C', 'title': 'Software Intern', 'location': 'Lyon',
             'apply_url': 'https://jobs.example.test/3', 'description': 'Frontend Javascript programming', 'employment_type': 'intern'},
            {'company': 'D', 'title': 'Mechanical Engineer', 'location': 'Paris',
             'apply_url': 'https://jobs.example.test/4', 'description': 'Full time CAD', 'employment_type': 'full-time'},
        ])
        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def load(self, *, ats):
                self.provider = ats
                return frame
        fake = SimpleNamespace(Client=FakeClient)
        config = {'ats_dataset': {'providers': ['greenhouse'], 'providers_per_day': 1,
                                  'max_candidates_per_provider': 2000}}
        with patch.dict(sys.modules, {'ats_scrapers': fake}):
            jobs, errors = scout.fetch_ats_source_sweep(config)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(errors, [])
        self.assertEqual({j['title'] for j in jobs}, {'Mechanical Intern', 'Stage ingénieur essais'})


if __name__ == '__main__':
    unittest.main()
