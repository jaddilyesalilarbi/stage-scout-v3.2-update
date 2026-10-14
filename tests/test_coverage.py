"""Offline regression tests for Stage Scout's employer coverage and CSV ingestion."""
from __future__ import annotations
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from company_watchlist import load_watchlist, selected_targets, valid_public_url, scan_target
from coverage_report import merge_coverage, company_index
from build_dashboard import build
import run_safe


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "companies.csv"
    def tearDown(self): self.tmp.cleanup()
    def write(self, text): self.path.write_text(text, encoding="utf-8-sig")

    def test_real_template_and_fr_ch_targets(self):
        rows = load_watchlist(ROOT / "companies.csv")
        self.assertGreaterEqual(len(rows), 35)
        self.assertTrue(all(item["country"] in {"FR", "CH"} for item in rows))
        self.assertTrue(all(item["enabled"] for item in rows))
        self.assertIn("ABB", [x["name"] for x in rows])

    def test_french_excel_csv_delimiter_and_unicode(self):
        self.write("name;country;careers_url;enabled;notes\nBühler;CH;https://jobs.example.com/buhler;oui;Check site\n")
        rows = load_watchlist(self.path)
        self.assertEqual(rows[0]["country"], "CH")
        self.assertEqual(rows[0]["careers_url"], "https://jobs.example.com/buhler")
        self.assertEqual(rows[0]["name"], "Bühler")

    def test_duplicate_and_bad_enabled_fail(self):
        self.write("name,country,careers_url,enabled,notes\nABB,CH,,yes,\nabb,CH,,yes,\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_watchlist(self.path)
        self.write("name,country,careers_url,enabled,notes\nABB,CH,,maybe,\n")
        with self.assertRaisesRegex(ValueError, "invalid enabled"):
            load_watchlist(self.path)

    def test_private_or_non_http_urls_rejected(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "http://localhost", "http://127.0.0.1/jobs", "http://foo.internal"):
            self.assertFalse(valid_public_url(url), url)
        self.assertTrue(valid_public_url("https://jobs.ashbyhq.com/company"))

    def test_rotation_covers_whole_registry(self):
        rows = load_watchlist(ROOT / "companies.csv")
        visited = set()
        for i in range(14):
            for row in selected_targets(rows, today=date(2026, 10, 14) + timedelta(days=i), max_per_day=10):
                visited.add(row["name"])
        self.assertEqual(visited, {row["name"] for row in rows})

    def test_disabled_not_scheduled(self):
        rows = [{"name":"One","country":"FR","enabled":True}, {"name":"Two","country":"CH","enabled":False}]
        result = selected_targets(rows,max_per_day=10)
        self.assertEqual([x["name"] for x in result], ["One"])


class ScanTests(unittest.TestCase):
    def test_direct_zero_is_successful_scan(self):
        fake_scraper = types.SimpleNamespace(fetch=lambda: [])
        mock_mod = types.SimpleNamespace(get_scraper_for_url=lambda u: fake_scraper,
                                          find_company=lambda name,limit: None)
        with patch.dict(sys.modules, {"ats_scrapers": mock_mod}):
            jobs, errors, info = scan_target({"name":"ABB","careers_url":"https://jobs.ashbyhq.com/abb"})
        self.assertEqual(jobs, [])
        self.assertEqual(errors, [])
        self.assertEqual(info["outcome"], "scanned")
        self.assertEqual(info["raw_postings"], 0)

    def test_lookup_without_match_not_a_scan(self):
        fake_find = lambda name, limit: types.SimpleNamespace(to_dict=lambda _: [])
        mock_mod = types.SimpleNamespace(get_scraper_for_url=lambda u: None, find_company=fake_find)
        with patch.dict(sys.modules, {"ats_scrapers": mock_mod}):
            jobs, errors, info = scan_target({"name":"Test Company","careers_url":""})
        self.assertEqual(info["outcome"], "not_found")
        self.assertFalse(jobs)

    def test_generic_url_rejected_when_connector_missing(self):
        def fail(url): raise ValueError("ATS URL not recognised")
        mock_mod = types.SimpleNamespace(get_scraper_for_url=fail,
                                          find_company=lambda name,limit: None)
        with patch.dict(sys.modules, {"ats_scrapers": mock_mod}):
            _, errors, info = scan_target({"name":"ABB","careers_url":"https://www.abb.com/careers"})
        self.assertEqual(info["outcome"], "unsupported_url")
        self.assertEqual(errors, [])


class CoverageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "companies.csv"
        self.path.write_text("name,country,careers_url,enabled,notes\nABB,CH,https://jobs.ashbyhq.com/abb,yes,\nTest Company,FR,,yes,\n", encoding="utf-8")
        self.config = {"priority_companies": ["ABB", "Test Company"]}
    def tearDown(self): self.tmp.cleanup()

    def test_only_actual_scrapes_count_as_scans(self):
        statuses = [
            {"stage":"watchlist","name":"ABB","status":"completed","count":0,"scan_info":{"outcome":"scanned","raw_postings":0,"resolved_url":"https://jobs.ashbyhq.com/abb"}},
            {"stage":"watchlist","name":"Test Company","status":"completed","count":0,"scan_info":{"outcome":"not_found","message":"No matching board"}}
        ]
        report = merge_coverage(self.config,self.path, source_statuses=statuses, today="2026-10-14")
        abb, other = report["companies"]
        self.assertEqual(abb["name"], "ABB")
        self.assertEqual(abb["last_success"], "2026-10-14")
        self.assertEqual(other["last_outcome"], "not_found")
        self.assertNotIn("last_success", other)

    def test_lookup_only_not_credited_as_success(self):
        statuses = [{"stage":"discovery","name":"ABB","status":"completed","count":0}]
        report = merge_coverage(self.config,self.path, source_statuses=statuses)
        self.assertEqual(report["companies"][0]["last_outcome"], "lookup_only")
        self.assertNotIn("last_success", report["companies"][0])

    def test_history_retained_and_changed_url_resets_scanned(self):
        first = merge_coverage(self.config,self.path,source_statuses=[
            {"stage":"watchlist","name":"ABB","status":"completed","count":2,"scan_info":{"outcome":"scanned","raw_postings":2}}],today="2026-10-14")
        second = merge_coverage(self.config,self.path,first,[],today="2026-10-15")
        self.assertEqual(second["companies"][0]["last_success"], "2026-10-14")
        self.path.write_text("name,country,careers_url,enabled,notes\nABB,CH,https://jobs.greenhouse.io/new,yes,\n", encoding="utf-8")
        third = merge_coverage(self.config,self.path,second,[],today="2026-10-16")
        self.assertNotIn("last_success", third["companies"][0])

    def test_runner_skips_disabled_and_legacy_duplicate(self):
        fake = self.config | {"company_careers": [{"name":"ABB","url":"https://jobs.ashbyhq.com/abb"}],
                              "company_discovery":{"enabled":True,"companies_per_day":8},
                              "jobspy":{"enabled":False},"ats_dataset":{"enabled":False}}
        tasks = run_safe.make_tasks(fake, registry_path=self.path)
        # User URL takes precedence; no duplicate legacy fetch.
        self.assertFalse(any(t[0] == "direct" and t[1] == "ABB" for t in tasks))
        self.assertEqual(sum(t[0] == "watchlist" and t[1] == "ABB" for t in tasks), 1)
        self.assertFalse(any(t[0] == "discovery" and t[1] in {"ABB", "Test Company"} for t in tasks))


class DashboardCoverageTests(unittest.TestCase):
    def test_dashboard_includes_csv_and_last_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'data').mkdir()
            (root/'dashboard-src').mkdir()
            for f in ['index.template.html','style.css','app.js']:
                (root/'dashboard-src'/f).write_bytes((ROOT/'dashboard-src'/f).read_bytes())
            (root/'config.json').write_text(json.dumps({"priority_companies":["ABB"]}), encoding="utf-8")
            (root/'companies.csv').write_text('name,country,careers_url,enabled,notes\nABB,CH,https://jobs.ashbyhq.com/abb,yes,\n', encoding="utf-8")
            with (root/'data'/'jobs.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=['id','company','title','score'])
                writer.writeheader(); writer.writerow({'id':'x1','company':'ABB','title':'Mechanical Intern','score':'75'})
            (root/'data'/'last_run.json').write_text(json.dumps({"date":"2026-10-14","source_health":{"sources":[
                {"stage":"direct","name":"ABB","status":"completed","count":3}
            ]}}),encoding='utf-8')
            html=build(root).read_text(encoding='utf-8')
            self.assertIn('id="tab-coverage"',html)
            self.assertIn('id="coverage-rows"',html)
            self.assertIn('"last_outcome":"scanned"',html)
            self.assertIn('"country":"CH"',html)
            self.assertIn('"id":"x1"',html)


if __name__ == '__main__': unittest.main()
