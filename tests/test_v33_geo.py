"""Regression tests for free-text ATS location country codes and historic cleanup."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scout
from selection_filters import classify_location, geography_excluded

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def job(location: str, title="Mechanical Design Intern") -> dict:
    return scout.make_job(
        "Example Engineering", title, location,
        "https://jobs.example.test/offer/123",
        "Mechanical CAD design, assembly and testing. Six month internship.",
        "ATS dataset / smartrecruiters", kind_hint="Intern",
    )


class LocationCodeTests(unittest.TestCase):
    def test_common_lowercase_iso2_outside_europe(self):
        locations = (
            "Ho Chi Minh City, vn",
            "Hemaraj Eastern Seaboard Industrial Estate, RAYONG, th",
            "Hanoi, VN", "Bangkok, TH", "Manila, ph",
            "Kuala Lumpur, my", "Jakarta, id", "Taipei, tw",
            "Singapore, sg", "Tokyo, jp", "Seoul, kr",
            "Phnom Penh, kh", "Bangladesh, bd", "Dubai, ae",
            "Sydney, au", "Auckland, nz", "San Jose, us",
            "Sao Paulo, br", "Montreal, ca", "Chennai, in",
            "Porto Alegre, BR", "Remote (VN)", "Remote - TH",
            "Global / JP", "VN", "th", "Ho Chi Minh City, Vn",
        )
        for loc in locations:
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "outside")
                self.assertTrue(geography_excluded(job(loc), CONFIG))
                self.assertIsNone(scout.analyze(job(loc), CONFIG))

    def test_iso3_codes(self):
        locations = ("Ho Chi Minh City, VNM", "Rayong, tha", "Tokyo, JPN",
                     "Shanghai, CHN", "New York, USA", "Singapore, SGP",
                     "Sydney, AUS", "Remote / CAN")
        for loc in locations:
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "outside")

    def test_locations_without_country_codes(self):
        for loc in ("Ho Chi Minh City", "Rayong", "Hanoi", "Bangkok",
                    "Kuala Lumpur", "Manila", "Cebu", "Chonburi", "Nagoya"):
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "outside")

    def test_lowercase_europe_codes_retained(self):
        locations = ("Paris, fr", "Zurich, ch", "Amsterdam, nl", "London, gb",
                     "Lausanne, CHE", "Geneva, CH", "Berlin, DEU",
                     "Munich, de", "Brussels, be", "Oslo, no",
                     "Belgrade, rs", "Prague, cz", "Rome, it",
                     "Lisbon, pt", "Helsinki, fi", "Kosovo, XK")
        for loc in locations:
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "europe")
                self.assertFalse(geography_excluded(job(loc), CONFIG))

    def test_duplicate_city_names_country_wins(self):
        for loc in ("Paris, tx", "London, ON", "Geneva, IL",
                    "Paris, Vietnam", "Paris, vn", "London, ca"):
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "outside")

    def test_multi_country_location_remains_mixed(self):
        for loc in ("Paris, France / Ho Chi Minh City, vn",
                    "London, GB / Bangkok, th",
                    "Remote FR, USA / Zurich, CH"):
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "mixed")
                self.assertFalse(geography_excluded(job(loc), CONFIG))

    def test_ambiguous_remote_is_not_guessed(self):
        for loc in ("Remote", "Worldwide", "Flexible location", "Work in"):
            with self.subTest(location=loc):
                self.assertEqual(classify_location(loc), "unknown")
                self.assertFalse(geography_excluded(job(loc), CONFIG))


class HistoricCleanupTests(unittest.TestCase):
    def test_existing_csv_cleaned_when_no_new_jobs(self):
        allowed = job("Lausanne, CH")
        old_outside_a = job("Ho Chi Minh City, vn")
        old_outside_b = job("Hemaraj Eastern Seaboard Industrial Estate, RAYONG, th")
        status_records = []
        for item in (allowed, old_outside_a, old_outside_b):
            analyzed = scout.analyze(allowed, CONFIG)
            record = scout.as_record(dict(analyzed,
                                          id=scout.job_identity(item),
                                          location=item["location"]), None, "2026-10-12")
            record["status"] = "Applied"
            status_records.append(record)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            scout.write_rows(output / "jobs.csv", status_records)
            (output / "incoming.json").write_text(json.dumps({
                "jobs": [], "errors": [], "source_health": {}
            }), encoding="utf-8")
            with patch.object(sys, "argv", ["scout.py", "--raw-input",
                                             str(output / "incoming.json"),
                                             "--output", str(output)]):
                self.assertEqual(scout.main(), 0)
            rows = scout.load_rows(output / "jobs.csv")
            self.assertEqual(len(rows), 1)
            only_row = next(iter(rows.values()))
            self.assertEqual(only_row["location"], "Lausanne, CH")
            self.assertEqual(only_row["status"], "Applied")
            stats = json.loads((output / "last_run.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["new"], 0)
            self.assertEqual(stats["history_removed"]["geography"], 2)


if __name__ == "__main__":
    unittest.main()
