#!/usr/bin/env python3
"""Stage Scout runner: one bounded subprocess per public-data source.

Why this exists: hosted ATS source slices and job-board requests can stall or
consume significant memory. A timed-out source must not erase results collected
from other sources, and the GitHub Actions log must show which source is active.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import scout

ROOT = Path(__file__).resolve().parent
DEFAULT_TIMEOUTS = {
    "direct": 40, "jobspy": 50, "discovery": 25, "ats": 80,
    "boards": 35, "arbeitnow": 40, "serpapi": 45, "adzuna": 45,
}
DEFAULT_STAGE_BUDGETS = {
    "direct": 90, "jobspy": 310, "discovery": 210, "ats": 330,
    "boards": 90, "arbeitnow": 45, "serpapi": 50, "adzuna": 50,
}


def selected(config: dict, items: list, n: int) -> list:
    return scout.chosen_searches({"google_jobs_queries": items}, max(0, n))


def make_tasks(config: dict) -> list[tuple[str, str, object]]:
    """Create bounded tasks with predictable rotation across days."""
    tasks = []
    if config.get("ats_direct_enabled", True):
        for item in config.get("company_careers", []):
            tasks.append(("direct", str(item.get("name") or item.get("url")), item))
    for item in config.get("boards", []):
        tasks.append(("boards", str(item.get("name") or item.get("id")), item))
    settings = config.get("jobspy", {})
    if settings.get("enabled", True):
        european_queries = scout.europe_jobspy_queries(settings.get("queries", []))
        q = selected(config, european_queries, int(settings.get("searches_per_day", 2)))
        for spec in q:
            tasks.append(("jobspy", f"{spec.get('search_term', '')} @ {spec.get('location', '')}", spec))
    settings = config.get("company_discovery", {})
    if settings.get("enabled", False):
        q = selected(config, config.get("priority_companies", []), int(settings.get("companies_per_day", 10)))
        for name in q:
            tasks.append(("discovery", str(name), name))
    settings = config.get("ats_dataset", {})
    if settings.get("enabled", True):
        if settings.get("scan_mode") == "source_sweep":
            q = selected(config, settings.get("providers", []), int(settings.get("providers_per_day", 4)))
            for provider in q:
                tasks.append(("ats", f"ATS provider: {provider}", provider))
        else:
            q = selected(config, scout.ats_query_plan(settings), int(settings.get("searches_per_day", 2)))
            for query in q:
                tasks.append(("ats", f"ATS search: {query.get('ats', '')} / {query.get('query', '')}", query))
    if config.get("arbeitnow_enabled", False):
        tasks.append(("arbeitnow", "Arbeitnow", None))
    if os.environ.get("SERPAPI_KEY") and int(config.get("serpapi_searches_per_day", 0)) > 0:
        tasks.append(("serpapi", "Google Jobs", None))
    if os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY") and config.get("adzuna_queries"):
        tasks.append(("adzuna", "Adzuna", None))
    return tasks


def perform_worker(kind: str, spec: object, config: dict) -> tuple[list[dict], list[str]]:
    """One source per process so per-source timeouts and memory limits work."""
    if kind == "direct":
        return scout.fetch_ats_direct([spec])
    if kind == "boards":
        board = spec
        methods = {"ashby": scout.fetch_ashby, "greenhouse": scout.fetch_greenhouse, "lever": scout.fetch_lever}
        fn = methods.get(board.get("type", ""))
        if not fn:
            return [], [f"Unknown board type for {board.get('name', '')}"]
        return fn(board), []
    if kind == "discovery":
        custom = deepcopy(config)
        custom["priority_companies"] = [spec]
        custom.setdefault("company_discovery", {})["companies_per_day"] = 1
        return scout.fetch_discovered_careers(custom)
    if kind == "ats":
        custom = deepcopy(config)
        settings = custom.setdefault("ats_dataset", {})
        if settings.get("scan_mode") == "source_sweep":
            settings["providers"] = [spec]
            settings["providers_per_day"] = 1
        else:
            settings["queries"] = [spec]
            settings["searches_per_day"] = 1
        return scout.fetch_ats_dataset(custom)
    if kind == "jobspy":
        custom = deepcopy(config)
        custom.setdefault("jobspy", {})["queries"] = [spec]
        custom["jobspy"]["searches_per_day"] = 1
        return scout.fetch_jobspy(custom)
    if kind == "arbeitnow":
        return scout.fetch_arbeitnow(config.get("arbeitnow_pages", 2)), []
    if kind == "serpapi":
        return scout.fetch_serpapi(config), []
    if kind == "adzuna":
        return scout.fetch_adzuna(config), []
    return [], [f"Unknown source: {kind}"]


def run_one(kind: str, label: str, spec: object, config_path: Path,
            result_file: Path, timeout: int) -> tuple[list[dict], list[str], str]:
    command = [sys.executable, "-u", str(ROOT / "run_safe.py"), "--worker", kind,
               "--spec", json.dumps(spec, ensure_ascii=False),
               "--result", str(result_file), "--config", str(config_path)]
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                   text=True, errors="replace", timeout=timeout,
                                   check=False)
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            snippet = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout
            print(snippet[-1200:], flush=True)
        return [], [f"TIMEOUT {kind} / {label}: exceeded {timeout}s; other sources will continue"], "timeout"
    if completed.stdout.strip():
        print(completed.stdout[-2000:].rstrip(), flush=True)
    if completed.stderr.strip():
        print("[SOURCE-LOG] " + completed.stderr[-1000:].rstrip(), flush=True)
    if completed.returncode != 0:
        return [], [f"FAILED {kind} / {label}: worker exited with code {completed.returncode}"], "failed"
    try:
        with result_file.open(encoding="utf-8") as f:
            result = json.load(f)
        jobs = result["jobs"]
        errors = result.get("errors", [])
        if not isinstance(jobs, list) or not isinstance(errors, list):
            raise ValueError("Unexpected worker result types")
        return jobs, errors, "completed" if not errors else "error"
    except Exception as exc:
        return [], [f"FAILED {kind} / {label}: cannot read result: {type(exc).__name__}: {exc}"], "failed"


def run_all(config_path: Path, output_dir: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    limits = config.get("scan_limits", {})
    max_seconds = max(60, int(limits.get("max_runtime_seconds", 960)))
    per_source = {**DEFAULT_TIMEOUTS, **limits.get("per_source_timeout_seconds", {})}
    stage_budgets = {**DEFAULT_STAGE_BUDGETS, **limits.get("stage_budgets_seconds", {})}
    tasks = make_tasks(config)
    print(f"[START] {len(tasks)} public sources scheduled; safety deadline {max_seconds}s", flush=True)
    jobs, errors, statuses = [], [], []
    start = time.monotonic()
    stage_elapsed = Counter()
    with tempfile.TemporaryDirectory(prefix="stage_scout_") as temp_dir:
        scratch = Path(temp_dir)
        for index, (kind, label, spec) in enumerate(tasks):
            elapsed = time.monotonic() - start
            allowed = min(int(per_source.get(kind, 45)),
                          int(stage_budgets.get(kind, 90) - stage_elapsed[kind]),
                          int(max_seconds - elapsed))
            if allowed < 3:
                reason = "global deadline" if max_seconds - elapsed < 3 else f"{kind} stage time budget"
                print(f"[SKIP] {kind}: {label} ({reason})", flush=True)
                statuses.append({"stage": kind, "name": label, "status": "skipped_budget", "count": 0})
                continue
            print(f"[SCAN {index + 1}/{len(tasks)}] {kind}: {label} (timeout {allowed}s)", flush=True)
            t0 = time.monotonic()
            batch, problem, status = run_one(kind, label, spec, config_path,
                                             scratch / f"part-{index}.json", allowed)
            duration = time.monotonic() - t0
            stage_elapsed[kind] += duration
            jobs.extend(batch)
            errors.extend(problem)
            statuses.append({"stage": kind, "name": label, "status": status,
                             "count": len(batch), "duration_seconds": round(duration, 1)})
            print(f"[RESULT] {kind}: {label} => {status}, {len(batch)} offers ({duration:.1f}s)", flush=True)
        health = {
            "attempted": sum(x["status"] != "skipped_budget" for x in statuses),
            "completed": sum(x["status"] == "completed" for x in statuses),
            "timed_out": sum(x["status"] == "timeout" for x in statuses),
            "failed_or_error": sum(x["status"] in ("failed", "error") for x in statuses),
            "skipped_budget": sum(x["status"] == "skipped_budget" for x in statuses),
            "total_sources_planned": len(statuses),
            "sources": statuses,
        }
        raw = scratch / "raw_jobs.json"
        raw.write_text(json.dumps({"jobs": jobs, "errors": errors, "source_health": health},
                                  ensure_ascii=False), encoding="utf-8")
        # Let the existing matching/history/report engine handle all sources at once.
        cmd = [sys.executable, "-u", str(ROOT / "scout.py"), "--config", str(config_path),
               "--output", str(output_dir), "--raw-input", str(raw)]
        print(f"[REPORT] Consolidating {len(jobs)} postings from {len(tasks)} planned sources", flush=True)
        result = subprocess.run(cmd, cwd=ROOT, check=False)
    if not jobs and errors:
        print("[WARN] No sources returned offers; check last_run.json and logs", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage Scout with per-source time budgets")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument("--worker", choices=list(DEFAULT_TIMEOUTS))
    parser.add_argument("--spec", default="null")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--show-plan", action="store_true", help="List daily sources without accessing the network")
    args = parser.parse_args()
    if args.worker:
        if args.result is None:
            parser.error("--result required for --worker")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        try:
            jobs, errors = perform_worker(args.worker, json.loads(args.spec), config)
        except Exception as exc:
            jobs, errors = [], [f"{args.worker}: {type(exc).__name__}: {exc}"]
        args.result.write_text(json.dumps({"jobs": jobs, "errors": errors}, ensure_ascii=False),
                               encoding="utf-8")
        return 0
    if args.show_plan:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        for kind, label, _ in make_tasks(config):
            print(f"{kind:10} {label}")
        return 0
    return run_all(args.config, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
