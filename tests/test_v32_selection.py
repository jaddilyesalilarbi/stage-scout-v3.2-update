"""Europe-only selection, short summer programs, and historical cleanup."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scout
from selection_filters import classify_location, excluded_summer, geography_excluded

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def job(title="Mechanical Design Intern", location="Paris, France", description="Six month structural CAD engineering internship."):
    return scout.make_job("Example Engineering", title, location,
                          "https://jobs.example.test/job/123", description,
                          "Ashby", kind_hint="Intern")


class EuropeSelectionTests(unittest.TestCase):
    def test_france_and_switzerland(self):
        for loc in ("Paris, France", "Geneva, Switzerland", "Zurich, CH",
                    "Lyon", "Lausanne", "Basel, Schweiz"):
            with self.subTest(loc=loc):
                self.assertEqual(classify_location(loc), "europe")
                self.assertFalse(geography_excluded(job(location=loc), CONFIG))

    def test_uk_and_other_non_eu_countries(self):
        for loc in ("London, United Kingdom", "Oxford, England", "Oslo, Norway",
                    "Reykjavik, Iceland", "Dublin, Ireland", "Germany", "Barcelona, Spain"):
            with self.subTest(loc=loc):
                self.assertEqual(classify_location(loc), "europe")

    def test_north_america_and_asia(self):
        for loc in ("Alameda, CA", "San Francisco, USA", "Boston, MA",
                    "Toronto, Canada", "Singapore", "Mumbai, India", "Tokyo, Japan",
                    "Sydney, Australia", "California"):
            with self.subTest(loc=loc):
                self.assertTrue(geography_excluded(job(location=loc), CONFIG))
                self.assertIsNone(scout.analyze(job(location=loc), CONFIG))

    def test_same_city_name_overseas(self):
        for loc in ("Paris, TX", "London, ON", "Paris, Texas", "Berlin, Connecticut",
                    "Geneva, IL", "London, Ontario", "Wilmington, DE"):
            with self.subTest(loc=loc):
                self.assertEqual(classify_location(loc), "outside")

    def test_remote_restriction(self):
        self.assertEqual(classify_location("Remote - US only"), "outside")
        self.assertEqual(classify_location("Remote across the EU"), "europe")
        self.assertEqual(classify_location("Remote - worldwide"), "unknown")

    def test_unknown_kept_and_flagged(self):
        item = scout.analyze(job(location="Remote"), CONFIG)
        self.assertIsNotNone(item)
        self.assertIn("confirm the position is based in Europe", item["warnings"])

    def test_mixed_kept_with_warning(self):
        item = scout.analyze(job(location="Paris, France / Boston, USA"), CONFIG)
        self.assertIsNotNone(item)
        self.assertIn("confirm a European work location", item["warnings"])

    def test_unknown_can_be_strict(self):
        config = dict(CONFIG, geography_filter={'enabled': True, 'keep_unknown_locations': False})
        self.assertIsNone(scout.analyze(job(location=""), config))


class SummerSelectionTests(unittest.TestCase):
    def test_summer_internship_any_year(self):
        for title in ("Mechanical Design Summer Internship", "Summer 2026 Mechanical Intern",
                      "Summer 2027 - Mechanical Engineering Internship",
                      "Mechanical Intern - Summer 2028", "Stage d'ete 2027 - conception mecanique"):
            with self.subTest(title=title):
                self.assertTrue(excluded_summer(job(title=title), CONFIG))
                self.assertIsNone(scout.analyze(job(title=title), CONFIG))

    def test_summer_2027_start_months_in_title(self):
        for title in ("Mechanical Design Intern - June 2027", "Master Thesis Mechanical - July 2027",
                      "Stage ingenieur mecanique 2027-08", "Mechanical Intern August 2027"):
            with self.subTest(title=title):
                self.assertTrue(excluded_summer(job(title=title), CONFIG))

    def test_summer_2027_start_dates_in_description(self):
        for desc in ("Start date: July 2027. Structural design and tests.",
                     "Stage de conception: debut 01/07/2027, pour 6 mois.",
                     "Available from 2027-06-15, CAD engineering tasks.",
                     "Starting June 1, 2027, 6 months engineering internship."):
            with self.subTest(desc=desc):
                self.assertTrue(excluded_summer(job(description=desc), CONFIG))

    def test_other_dates_not_filtered(self):
        for desc in ("Start January 2027 for six months.",
                     "Start October 2026 for six months.",
                     "Must graduate in June 2027; placement starts January 2027."):
            with self.subTest(desc=desc):
                self.assertFalse(excluded_summer(job(description=desc), CONFIG))

    def test_ordinary_summer_project_not_labeled_summer_internship(self):
        desc = "Thermal analysis of summer heat gain. Starting October 2026."
        self.assertFalse(excluded_summer(job(description=desc), CONFIG))


class CleanupTests(unittest.TestCase):
    def test_reports_and_history_are_filtered_preserving_valid_status(self):
        keep = job()
        summer = job(title="Mechanical Design Summer Internship")
        overseas = job(location="Alameda, California", title="Mechanical CAD Intern")
        valid_id = scout.job_identity(keep)
        old_valid = scout.analyze(keep, CONFIG)
        old_valid['id'] = valid_id
        status = scout.as_record(old_valid, None, '2026-10-10')
        status['status'] = 'Applied'
        old_summer = scout.as_record(dict(old_valid, id=scout.job_identity(summer),
                                       title=summer['title'], location=summer['location']), None, '2026-10-10')
        old_overseas = scout.as_record(dict(old_valid, id=scout.job_identity(overseas),
                                         title=overseas['title'], location=overseas['location']), None, '2026-10-10')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            scout.write_rows(out / 'jobs.csv', [status, old_summer, old_overseas])
            (out / 'input.json').write_text(json.dumps({'jobs': [keep, summer, overseas],
                                                       'errors': [], 'source_health': {}}), encoding='utf-8')
            arguments = ['scout.py', '--raw-input', str(out / 'input.json'), '--output', str(out)]
            with patch.object(sys, 'argv', arguments):
                self.assertEqual(scout.main(), 0)
            records = scout.load_rows(out / 'jobs.csv')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[valid_id]['status'], 'Applied')
            stats = json.loads((out / 'last_run.json').read_text(encoding='utf-8'))
            self.assertEqual(stats['excluded_by_summer'], 1)
            self.assertEqual(stats['excluded_outside_europe'], 1)
            self.assertEqual(stats['history_removed']['summer'], 1)
            self.assertEqual(stats['history_removed']['geography'], 1)
            report = (out / 'latest.md').read_text(encoding='utf-8')
            self.assertIn('Mechanical Design Intern', report)
            self.assertNotIn('Summer Internship', report)

    def test_jobspy_searches_are_europe_only(self):
        self.assertTrue(CONFIG['jobspy']['queries'])
        allowed = {q['country_indeed'] for q in scout.europe_jobspy_queries(CONFIG['jobspy']['queries'])}
        self.assertNotIn('USA', allowed)
        self.assertNotIn('Canada', allowed)
        self.assertNotIn('Singapore', allowed)
        self.assertNotIn('Australia', allowed)


if __name__ == '__main__':
    unittest.main()
