"""CSV company registry and truthful, bounded ATS-company verification.

The CSV contains *targets*, not proof of scanning. A verified scan requires an
ATS scraper successfully fetching the company's public job board. Generic
career URLs may require a custom connector; never report them as scanned.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


def company_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    while words and words[-1] in {"sa", "sas", "ag", "gmbh", "ltd", "inc", "corp", "limited"}:
        words.pop()
    return " ".join(words)


CSV_FIELDS = ("name", "country", "careers_url", "enabled", "notes")
ENABLED_TRUE = {"1", "yes", "y", "oui", "true", "on", ""}
ENABLED_FALSE = {"0", "no", "n", "non", "false", "off"}


def valid_public_url(value: str) -> bool:
    """Only allow ordinary HTTPS/HTTP public hostnames (never a local URI)."""
    if not value or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme in {"https", "http"} and bool(host)
                and "." in host and host not in {"localhost", "127.0.0.1"}
                and not host.endswith((".local", ".internal"))
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


def load_watchlist(path: Path) -> list[dict]:
    """Read Excel-exportable UTF-8 CSV. Blank URL -> exact-name ATS discovery."""
    if not path.exists():
        return []
    # Excel in French locales commonly exports semicolon-separated CSV.
    content = path.read_text(encoding="utf-8-sig")
    header = content.splitlines()[0] if content.splitlines() else ""
    delimiter = ";" if header.count(";") > header.count(",") else ","
    with io.StringIO(content, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames or not {"name", "country", "careers_url"}.issubset(reader.fieldnames):
            raise ValueError(f"{path.name}: required columns: name,country,careers_url")
        targets, seen = [], set()
        for line_no, item in enumerate(reader, 2):
            name = (item.get("name") or "").strip()
            if not name or name.startswith("#"):
                continue
            key = company_key(name)
            if not key or key in seen:
                raise ValueError(f"{path.name}: duplicate or invalid name at row {line_no}: {name}")
            seen.add(key)
            enabled_raw = (item.get("enabled") or "").strip().lower()
            if enabled_raw not in ENABLED_TRUE | ENABLED_FALSE:
                raise ValueError(f"{path.name}: invalid enabled at row {line_no}: {enabled_raw}")
            url = (item.get("careers_url") or "").strip()
            targets.append({
                "name": name,
                "key": key,
                "country": (item.get("country") or "").strip().upper(),
                "careers_url": url,
                "url_valid": not url or valid_public_url(url),
                "enabled": enabled_raw not in ENABLED_FALSE,
                "notes": (item.get("notes") or "").strip(),
            })
        return targets


def selected_targets(targets: list[dict], *, today: date | None = None, max_per_day: int = 10) -> list[dict]:
    """Spread all enabled targets across days, FR/CH first within the cycle."""
    pool = [x for x in targets if x["enabled"]]
    pool.sort(key=lambda x: (x["country"] not in ("FR", "CH"), x["name"].casefold()))
    if not pool or max_per_day <= 0:
        return []
    count = min(max_per_day, len(pool))
    first = ((today or date.today()).toordinal() * count) % len(pool)
    return [pool[(first + i) % len(pool)] for i in range(count)]


def scan_target(target: dict) -> tuple[list[dict], list[str], dict]:
    """Scan a supplied ATS URL or discover a matching board (never a fuzzy employer)."""
    from ats_scrapers import find_company, get_scraper_for_url
    import scout

    name = target["name"]
    entered_url = target.get("careers_url") or ""
    info = {"outcome": "not_found", "method": "user_url" if entered_url else "directory",
            "resolved_url": "", "raw_postings": 0,
            "candidate_urls": [], "message": ""}
    if entered_url and not valid_public_url(entered_url):
        info.update(outcome="invalid_url", message="URL invalide : indiquer une adresse https:// publique")
        return [], [], info

    options = []
    if entered_url:
        options.append(entered_url)
    else:
        try:
            matches = find_company(name, limit=30).to_dict("records")
        except Exception as exc:
            info.update(outcome="error", message=f"Recherche annuaire en erreur: {type(exc).__name__}: {str(exc)[:130]}")
            return [], [f"Watchlist discovery {name}: {info['message']}"], info
        exact = [row for row in matches if company_key(str(row.get("name", ""))) == company_key(name)]
        options = [str(row.get("url", "")).strip() for row in exact
                   if valid_public_url(str(row.get("url", "")).strip())][:2]
        if not options:
            info["message"] = "Aucune URL ATS correspondant exactement à cette entreprise dans l'annuaire"
            return [], [], info

    # Persist discovered candidates for the manual follow-up audit, including
    # boards whose connector is missing. A candidate is not a verified scan.
    info["candidate_urls"] = list(dict.fromkeys(options))
    # Successful empty fetch counts as a scan with zero open postings.
    errors = []
    for url in options:
        try:
            scraper = get_scraper_for_url(url)
        except Exception as exc:
            info.update(outcome="unsupported_url", message=f"Connecteur ATS indisponible pour cette URL: {str(exc)[:140]}")
            continue
        try:
            items = scraper.fetch()
            results = []
            for item in items:
                job = scout.normalize_ats(item, direct=True, company=name)
                if job:
                    job["source"] = "ATS company watchlist"
                    results.append(job)
            info.update(outcome="scanned", resolved_url=url, raw_postings=len(results),
                        message="Page ATS publique parcourue")
            return results, [], info
        except Exception as exc:
            message = f"ATS fetch error: {type(exc).__name__}: {str(exc)[:140]}"
            errors.append(f"Watchlist {name}: {message}")
            info.update(outcome="error", message=message, resolved_url=url)
    return [], errors, info
