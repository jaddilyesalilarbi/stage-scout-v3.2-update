import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scout


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        if orient != "records":
            raise AssertionError("Expected records")
        return self.rows


ATS_ROW = {
    "company": "Test Aerospace",
    "title": "Mechanical Design Intern",
    "location": "Geneva, Switzerland",
    "apply_url": "https://careers.example.test/job/123/apply",
    "url": "https://careers.example.test/job/123",
    "description": "CAD, integration, FEA, six months",
    "posted_at": "2026-10-01",
    "employment_type": "intern",
    "ats_type": "greenhouse",
}
JOBSPY_ROW = {
    "company": "Test Energy",
    "title": "Stage ingénieur conception mécanique",
    "city": "Paris",
    "state": "Ile-de-France",
    "country": "France",
    "job_url": "https://jobs.example.test/stage/1",
    "description": "Stage 6 mois sur des ensembles mécaniques",
    "site": "indeed",
    "date_posted": "2026-10-01",
    "job_type": "internship",
}


class IntegrationTests(unittest.TestCase):
    def test_ats_row_normalization(self):
        job = scout.normalize_ats(ATS_ROW)
        self.assertEqual(job["source"], "ATS dataset / greenhouse")
        self.assertEqual(job["url"], ATS_ROW["apply_url"])
        self.assertEqual(job["verification"], "hosted_dataset_unverified")

    def test_ats_direct_normalization(self):
        item = SimpleNamespace(model_dump=lambda mode: ATS_ROW)
        job = scout.normalize_ats(item, direct=True, company="Test Aerospace")
        self.assertEqual(job["source"], "ATS direct")
        self.assertEqual(job["verification"], "published_board")

    def test_ats_invalid_url_filtered(self):
        self.assertIsNone(scout.normalize_ats({**ATS_ROW, "apply_url": "bad", "url": ""}))

    def test_jobspy_row(self):
        job = scout.normalize_jobspy(JOBSPY_ROW)
        self.assertEqual(job["source"], "JobSpy / indeed")
        self.assertIn("Paris", job["location"])
        self.assertIsNotNone(scout.analyze(job, {"minimum_score": 20}))

    def test_ats_dataset_search_mock(self):
        fake = SimpleNamespace(search=lambda **kw: FakeFrame([ATS_ROW]))
        config = {"ats_dataset": {"queries": [
            {"query": "mechanical intern", "ats": "greenhouse", "limit": 100}
        ], "searches_per_day": 1}}
        with patch.dict(sys.modules, {"ats_scrapers": fake}):
            jobs, errors = scout.fetch_ats_dataset(config)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(errors, [])

    def test_jobspy_search_mock(self):
        fake = SimpleNamespace(scrape_jobs=lambda **kw: FakeFrame([JOBSPY_ROW]))
        config = {"jobspy": {"sites": ["indeed"], "queries": [
            {"search_term": "stage mecanique", "location": "Paris"}
        ], "searches_per_day": 1}}
        with patch.dict(sys.modules, {"jobspy": fake}):
            jobs, errors = scout.fetch_jobspy(config)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(errors, [])

    def test_company_watchlist_mock(self):
        scraper = SimpleNamespace(fetch=lambda: [ATS_ROW])
        fake = SimpleNamespace(get_scraper_for_url=lambda url: scraper)
        with patch.dict(sys.modules, {"ats_scrapers": fake}):
            jobs, errors = scout.fetch_ats_direct([
                {"name": "Test Aerospace", "url": "https://jobs.example.test"}
            ])
        self.assertEqual(jobs[0]["source"], "ATS direct")
        self.assertEqual(errors, [])

    def test_prefer_direct_over_aggregator(self):
        a = {"source": "ATS direct", "description": "."}
        b = {"source": "JobSpy / indeed", "description": "lots of text"}
        self.assertIs(scout.prefer(a, b), a)


if __name__ == "__main__":
    unittest.main()
