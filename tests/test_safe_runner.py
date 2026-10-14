"""Offline safeguards for cancellation and per-source scan planning."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_safe


class SafeRunnerTests(unittest.TestCase):
    def test_daily_plan_spreads_sources(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        tasks = run_safe.make_tasks(config)
        counts = {stage: sum(t[0] == stage for t in tasks) for stage in {t[0] for t in tasks}}
        self.assertEqual(counts.get("direct"), 2)
        self.assertEqual(counts.get("ats"), 4)
        self.assertEqual(counts.get("jobspy"), 6)
        self.assertEqual(counts.get("discovery"), 8)

    def test_timeout_is_recorded_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(run_safe.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 3)):
                jobs, errors, status = run_safe.run_one(
                    "ats", "test provider", "greenhouse", ROOT / "config.json",
                    Path(tmp) / "result.json", 3)
        self.assertEqual(jobs, [])
        self.assertEqual(status, "timeout")
        self.assertTrue(any("test provider" in error for error in errors))

    def test_one_jobspy_search_per_worker(self):
        cfg = {"jobspy": {"enabled": True, "sites": ["indeed"], "queries": [
            {"search_term": "irrelevant", "location": "Paris"}], "searches_per_day": 8}}
        spec = {"search_term": "mechanical intern", "location": "Lausanne"}
        with patch.object(run_safe.scout, "fetch_jobspy", return_value=([{"title": "Mechanical Intern"}], [])) as f:
            jobs, errors = run_safe.perform_worker("jobspy", spec, cfg)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(errors, [])
        params = f.call_args.args[0]["jobspy"]
        self.assertEqual(params["queries"], [spec])
        self.assertEqual(params["searches_per_day"], 1)

    def test_raw_input_consolidation_without_network(self):
        example = json.loads((ROOT / "tests" / "sample_jobs.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            raw = folder / "raw.json"
            raw.write_text(json.dumps({"jobs": example, "errors": ["TIMEOUT ATS provider"],
                                       "source_health": {"timed_out": 1}}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scout.py"),
                                     "--config", str(ROOT / "config.json"),
                                     "--raw-input", str(raw), "--output", str(folder / "out")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            stats = json.loads((folder / "out" / "last_run.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["source_health"]["timed_out"], 1)
            self.assertEqual(stats["matches"], 2)
            self.assertEqual(stats["errors"], ["TIMEOUT ATS provider"])


if __name__ == "__main__":
    unittest.main()
