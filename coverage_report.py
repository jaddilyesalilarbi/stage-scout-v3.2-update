"""Maintain an auditable company coverage timeline without false scan claims."""
from __future__ import annotations
from datetime import date
import json
from pathlib import Path
from company_watchlist import load_watchlist, company_key


def company_index(config: dict, registry_path: Path) -> list[dict]:
    """All tracked targets: CSV, direct config and legacy discovery targets."""
    rows = {}
    for item in config.get("priority_companies", []):
        if not isinstance(item, str) or not company_key(item):
            continue
        key = company_key(item)
        rows.setdefault(key, {"key": key, "name": item, "country": "",
                              "careers_url": "", "enabled": True,
                              "origin": "directory_priority", "notes": ""})
    for item in config.get("company_careers", []):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        key = company_key(name)
        rows[key] = {"key": key, "name": name, "country": "",
                     "careers_url": item.get("url") or "", "enabled": True,
                     "origin": "config_direct", "notes": ""}
    for item in load_watchlist(registry_path):
        key = item["key"]
        inherited_url = rows.get(key, {}).get("careers_url", "")
        rows[key] = {"key": key, "name": item["name"], "country": item["country"],
                     "careers_url": item["careers_url"] or inherited_url,
                     "enabled": item["enabled"], "origin": "csv_watchlist", "notes": item["notes"],
                     "url_valid": item["url_valid"]}
    return sorted(rows.values(), key=lambda x: (x["country"] not in ("FR", "CH"), x["country"], x["name"].casefold()))


def merge_coverage(config: dict, registry_path: Path, previous: dict | None = None,
                   source_statuses: list[dict] | None = None, today: str | None = None) -> dict:
    """Update only employers attempted by this run. Never infer coverage from ATS dataset."""
    previous = previous or {}
    stamp = today or date.today().isoformat()
    old = {x.get("key"): x for x in previous.get("companies", []) if x.get("key")}
    companies = []
    for item in company_index(config, registry_path):
        old_row = old.get(item["key"], {})
        row = {**item}
        previous_url = (old_row.get("careers_url") or "").rstrip("/").casefold()
        current_url = (row.get("careers_url") or "").rstrip("/").casefold()
        stable = previous_url == current_url
        if stable:
            for k in ("last_attempt", "last_success", "last_outcome", "last_method",
                      "last_jobs", "last_resolved_url", "last_message"):
                if k in old_row:
                    row[k] = old_row[k]
        else:
            row["last_message"] = "URL modifiée depuis le dernier contrôle : nouveau scan attendu"
        companies.append(row)
    by_key = {c["key"]: c for c in companies}

    for entry in source_statuses or []:
        kind = entry.get("stage")
        if kind not in {"watchlist", "direct", "discovery"}:
            continue
        key = company_key(str(entry.get("name") or ""))
        row = by_key.get(key)
        if not row:
            continue
        state = entry.get("status")
        if state == "skipped_budget":
            continue  # no actual attempt
        row["last_attempt"] = stamp
        row["last_method"] = kind
        if kind == "watchlist":
            details = entry.get("scan_info") or {}
            outcome = details.get("outcome") or ("timeout" if state == "timeout" else "error")
            row["last_outcome"] = outcome
            row["last_jobs"] = details.get("raw_postings", entry.get("count", 0))
            row["last_resolved_url"] = details.get("resolved_url") or ""
            row["last_message"] = details.get("message") or ("Délai dépassé" if state == "timeout" else "")
            if outcome == "scanned":
                row["last_success"] = stamp
        elif kind == "direct":
            row["last_outcome"] = "scanned" if state == "completed" else ("timeout" if state == "timeout" else "error")
            row["last_jobs"] = entry.get("count", 0)
            row["last_resolved_url"] = row.get("careers_url") or ""
            row["last_message"] = "Site ATS interrogé directement" if state == "completed" else "Échec de la requête ATS directe"
            if state == "completed":
                row["last_success"] = stamp
        else:
            # Existing discovery's 0 results are ambiguous: the lookup may only
            # have checked a directory. Do NOT count zero as an actual board scan.
            row["last_outcome"] = "directory_result" if state == "completed" and entry.get("count", 0) else ("lookup_only" if state == "completed" else "error")
            row["last_jobs"] = entry.get("count", 0)
            row["last_message"] = "Offres reçues par découverte ATS" if entry.get("count", 0) else "Recherche annuaire seulement ; scan non confirmé"
            if entry.get("count", 0) and state == "completed":
                row["last_success"] = stamp
    return {"updated_at": stamp, "explanation": "Direct ATS scans are distinct from directory lookups and aggregate-provider searches.",
            "companies": companies}


def load_coverage(root: Path) -> dict:
    path = root / "data" / "coverage.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_coverage(root: Path, output: Path, config: dict, sources: list[dict] | None) -> Path:
    current = load_coverage(output.parent) if output.parent == root else (json.loads((output / "coverage.json").read_text(encoding="utf-8")) if (output / "coverage.json").exists() else {})
    registry_path = root / "companies.csv"
    merged = merge_coverage(config, registry_path, current, sources)
    output.mkdir(parents=True, exist_ok=True)
    dest = output / "coverage.json"
    dest.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
