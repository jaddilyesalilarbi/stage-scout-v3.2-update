import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scout

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SAMPLES = json.loads((ROOT / "tests" / "sample_jobs.json").read_text(encoding="utf-8"))


class ScoutTests(unittest.TestCase):
    def test_related_internship(self):
        job = scout.analyze(SAMPLES[0], CONFIG)
        self.assertIsNotNone(job)
        self.assertGreater(job["score"], 50)
        self.assertIn("Stage", job["kind"])

    def test_master_thesis(self):
        job = scout.analyze(SAMPLES[1], CONFIG)
        self.assertEqual(job["kind"], "Master thesis / PDM")

    def test_unrelated_roles(self):
        self.assertIsNone(scout.analyze(SAMPLES[2], CONFIG))
        self.assertIsNone(scout.analyze(SAMPLES[3], CONFIG))

    def test_stale_summer_offers_filtered(self):
        self.assertTrue(scout.clearly_obsolete_cycle("Mechanical Intern Summer 2026", scout.date(2026, 10, 13)))
        self.assertFalse(scout.clearly_obsolete_cycle("Mechanical Intern Summer 2027", scout.date(2026, 10, 13)))

    def test_identity_stability(self):
        a = scout.job_identity(SAMPLES[0])
        b = dict(SAMPLES[0], url="https://example.org/tracking?utm_campaign=new")
        self.assertEqual(a, scout.job_identity(b))

    def test_prioritize_employer_ats(self):
        a = dict(SAMPLES[0], source="Ashby")
        b = dict(SAMPLES[0], source="Google Jobs / SerpApi")
        preferred = scout.prefer(a, b)
        self.assertEqual(preferred['source'], 'Ashby')
        self.assertEqual(preferred['url'], a['url'])

    def test_tracking_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.csv"
            job = scout.analyze(SAMPLES[0], CONFIG)
            job["id"] = scout.job_identity(job)
            row = scout.as_record(job, None, "2026-10-13")
            scout.write_rows(path, [row])
            data = scout.load_rows(path)
            self.assertEqual(data[job["id"]]["score"], str(job["score"]))
            self.assertEqual(data[job["id"]]["status"], "To review")

    def test_broken_offers_not_counted(self):
        job = dict(SAMPLES[0], url="")
        self.assertIsNone(scout.analyze(job, CONFIG))


if __name__ == "__main__":
    unittest.main()
