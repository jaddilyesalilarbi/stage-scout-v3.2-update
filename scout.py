#!/usr/bin/env python3
"""Stage Scout: public internship discovery, ranking and tracking.

No authenticated site scraping, no automatic applications, no personal data sent.
Optional API credentials are read from environment variables only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from selection_filters import (classify_location, excluded_summer, geography_excluded)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
FIELDS = [
    "id", "first_seen", "last_seen", "status", "score", "company", "title",
    "location", "language", "kind", "duration", "source", "verification", "posted_at",
    "url", "why", "warnings", "description_excerpt"
]
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "StageScout/1.0 (public jobs APIs, contact via GitHub project)", "Accept": "application/json"})
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.75, status_forcelist=[429, 500, 502, 503, 504]
)))


def fold(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def clean_html(value: object) -> str:
    s = html.unescape(str(value or ""))
    s = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def get_json(url: str, params: dict | None = None) -> dict | list:
    response = SESSION.get(url, params=params, timeout=18)
    response.raise_for_status()
    return response.json()


def make_job(company: str, title: str, location: str, url: str,
             description: str, source: str, posted_at: str = "", kind_hint: str = "",
             verification: str = "published_board", language: str = "") -> dict:
    return {
        "company": str(company or "").strip(),
        "title": str(title or "").strip(),
        "location": str(location or "").strip(),
        "url": str(url or "").strip(),
        "description": clean_html(description),
        "source": source,
        "posted_at": str(posted_at or ""),
        "kind_hint": str(kind_hint or ""),
        "verification": verification,
        "language": str(language or "").strip(),
    }


def fetch_ashby(board: dict) -> list[dict]:
    name = board["id"]
    body = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{name}",
                    {"includeCompensation": "true"})
    jobs = []
    for p in body.get("jobs", []):
        if p.get("isListed") is False:
            continue
        url = p.get("jobUrl") or p.get("applyUrl")
        if not url:
            continue
        jobs.append(make_job(
            board["name"], p.get("title", ""), p.get("location", ""), url,
            p.get("descriptionPlain") or p.get("descriptionHtml", ""),
            "Ashby", kind_hint=p.get("employmentType", "")
        ))
    return jobs


def fetch_greenhouse(board: dict) -> list[dict]:
    body = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board['id']}/jobs",
        {"content": "true"}
    )
    return [make_job(
        board["name"], p.get("title", ""), (p.get("location") or {}).get("name", ""),
        p.get("absolute_url", ""), p.get("content", ""), "Greenhouse",
        posted_at=p.get("updated_at", "")
    ) for p in body.get("jobs", []) if p.get("absolute_url")]


def fetch_lever(board: dict, max_pages: int = 3) -> list[dict]:
    jobs = []
    base = board.get("region", "global")
    host = "api.eu.lever.co" if base == "eu" else "api.lever.co"
    for page in range(max_pages):
        rows = get_json(f"https://{host}/v0/postings/{board['id']}",
                        {"mode": "json", "skip": page * 100, "limit": 100})
        if not isinstance(rows, list):
            break
        for p in rows:
            categories = p.get("categories") or {}
            lists = " ".join(str(li.get("content", "")) for li in p.get("lists", []))
            jobs.append(make_job(
                board["name"], p.get("text", ""), categories.get("location", ""),
                p.get("hostedUrl") or p.get("applyUrl", ""),
                " ".join([p.get("descriptionPlain", ""), lists, p.get("additionalPlain", "")]),
                "Lever", kind_hint=categories.get("commitment", "")
            ))
        if len(rows) < 100:
            break
    return jobs


def fetch_arbeitnow(pages: int = 2) -> list[dict]:
    jobs = []
    for page in range(1, pages + 1):
        body = get_json("https://www.arbeitnow.com/api/job-board-api", {"page": page})
        for p in body.get("data", []):
            jobs.append(make_job(
                p.get("company_name", ""), p.get("title", ""), p.get("location", ""),
                p.get("url", ""), p.get("description", ""), "Arbeitnow",
                posted_at=p.get("created_at", ""),
                kind_hint=" ".join(p.get("job_types", []) or []),
                verification="third_party_listing"
            ))
        if not (body.get("links") or {}).get("next"):
            break
    return jobs


def chosen_searches(config: dict, per_day: int) -> list[dict]:
    queries = config.get("google_jobs_queries") or []
    if not queries:
        return []
    # Rotating daily subsets avoid consuming the entire monthly free search quota.
    start = (date.today().toordinal() * per_day) % len(queries)
    return [queries[(start + offset) % len(queries)] for offset in range(min(per_day, len(queries)))]


def fetch_serpapi(config: dict) -> list[dict]:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return []
    jobs = []
    count = int(config.get("serpapi_searches_per_day", 5))
    for query in chosen_searches(config, count):
        try:
            body = get_json("https://serpapi.com/search.json", {
                "engine": "google_jobs", "q": query["q"],
                "location": query.get("location", "Paris, France"),
                "hl": "en", "api_key": key
            })
            if body.get("error"):
                print(f"[WARN] SerpApi: {body['error']}", file=sys.stderr)
                continue
            for p in body.get("jobs_results", []):
                options = p.get("apply_options") or []
                # Prefer links to the employer's website rather than social/aggregator sites.
                direct = next((o.get("link") for o in options
                               if o.get("link") and not any(s in fold(o.get("title", ""))
                               for s in ("linkedin", "indeed", "glassdoor"))), None)
                url = direct or next((o.get("link") for o in options if o.get("link")), None)
                if not url:
                    continue
                ext = p.get("detected_extensions") or {}
                jobs.append(make_job(
                    p.get("company_name", ""), p.get("title", ""), p.get("location", ""),
                    url, p.get("description", ""), "Google Jobs / SerpApi",
                    posted_at=ext.get("posted_at", ""),
                    kind_hint=ext.get("schedule_type", ""),
                    verification="search_index_unverified"
                ))
        except Exception as exc:
            print(f"[WARN] SerpApi {query['q']!r}: {exc}", file=sys.stderr)
    return jobs


def fetch_adzuna(config: dict) -> list[dict]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    jobs = []
    for query in config.get("adzuna_queries", []):
        country = query.get("country", "fr")
        try:
            body = get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", {
                "app_id": app_id, "app_key": app_key, "results_per_page": 30,
                "what": query["what"], "sort_by": "date",
                "content-type": "application/json"
            })
            for p in body.get("results", []):
                jobs.append(make_job(
                    (p.get("company") or {}).get("display_name", ""),
                    p.get("title", ""),
                    (p.get("location") or {}).get("display_name", ""),
                    p.get("redirect_url", ""), p.get("description", ""), "Adzuna",
                    posted_at=p.get("created", ""),
                    verification="third_party_listing"
                ))
        except Exception as exc:
            print(f"[WARN] Adzuna {country}/{query['what']!r}: {exc}", file=sys.stderr)
    return jobs



def _scalar(value: object) -> str:
    """Turn optional pandas/Pydantic fields into safe display strings."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    if isinstance(value, (list, dict, tuple, set)):
        return " ".join(_scalar(v) for v in value.values()) if isinstance(value, dict) else " ".join(_scalar(v) for v in value)
    result = str(value).strip()
    return "" if result.casefold() in ("none", "nan", "nat", "<na>") else result


def _ats_to_dict(entry: object) -> dict:
    """Normalize an ats-scrapers Job model or an already-normalized dataset row."""
    if isinstance(entry, dict):
        return entry
    if hasattr(entry, "model_dump"):
        return entry.model_dump(mode="json")
    if hasattr(entry, "dict"):
        return entry.dict()
    return {name: getattr(entry, name, None) for name in (
        "company", "title", "location", "url", "apply_url", "description",
        "posted_at", "employment_type", "commitment", "ats_type"
    )}


def normalize_ats(entry: object, *, direct: bool = False, company: str = "") -> dict | None:
    data = _ats_to_dict(entry)
    url = _scalar(data.get("apply_url")) or _scalar(data.get("url"))
    title = _scalar(data.get("title"))
    if not (url.startswith(("http://", "https://")) and title):
        return None
    ats = _scalar(data.get("ats_type"))
    return make_job(
        company or _scalar(data.get("company")), title,
        _scalar(data.get("location")), url,
        _scalar(data.get("description")),
        source="ATS direct" if direct else "ATS dataset" + (" / " + ats if ats else ""),
        posted_at=_scalar(data.get("posted_at")),
        kind_hint=_scalar(data.get("employment_type")) + " " + _scalar(data.get("commitment")),
        verification="published_board" if direct else "hosted_dataset_unverified",
        language=_scalar(data.get("language")),
    )


def fetch_ats_direct(careers: list[dict]) -> tuple[list[dict], list[str]]:
    """Fetch directly from supported public careers URLs; no login/browser scraping."""
    from ats_scrapers import get_scraper_for_url
    results, errors = [], []
    for item in careers:
        company, url = _scalar(item.get("name")), _scalar(item.get("url"))
        if not url:
            continue
        try:
            scraper = get_scraper_for_url(url)
            batch = scraper.fetch()
            count = 0
            for entry in batch:
                job = normalize_ats(entry, direct=True, company=company)
                if job:
                    results.append(job)
                    count += 1
            print(f"[INFO] ATS direct {company or url}: {count} published postings")
        except Exception as exc:
            errors.append(f"ATS direct {company or url}: {type(exc).__name__}: {exc}")
    return results, errors


def company_key(name: str) -> str:
    """Conservative name matching to avoid visiting lookalike employers."""
    s = re.sub(r"[^a-z0-9]+", " ", fold(name))
    words = s.split()
    while words and words[-1] in {"sa", "sas", "ag", "gmbh", "ltd", "inc", "corp", "limited"}:
        words.pop()
    return " ".join(words)


def fetch_discovered_careers(config: dict) -> tuple[list[dict], list[str]]:
    """Look up target employers by exact name in the ATS public directory.

    Only accept exact, normalized-name matches. The directory lookup can return
    fuzzy substrings; those MUST NOT trigger scraping a different employer.
    """
    settings = config.get("company_discovery") or {}
    if not settings.get("enabled", False):
        return [], []
    from ats_scrapers import find_company, get_scraper_for_url
    names = config.get("priority_companies", [])
    count = max(0, int(settings.get("companies_per_day", 10)))
    chosen = chosen_searches({"google_jobs_queries": names}, count)
    max_matches = max(1, min(3, int(settings.get("max_exact_matches_per_company", 2))))
    known_urls = {str(item.get("url", "")).rstrip("/").lower()
                  for item in config.get("company_careers", [])}
    scanned = set()
    results, errors = [], []
    for name in chosen:
        try:
            matches = find_company(name, limit=30).to_dict("records")
            exact = [row for row in matches
                     if company_key(str(row.get("name", ""))) == company_key(name)
                     and len(company_key(name)) >= 3]
            if not exact:
                print(f"[INFO] Company directory: no exact match for {name}")
                continue
            for row in exact[:max_matches]:
                url = _scalar(row.get("url"))
                if not url.startswith(("https://", "http://")):
                    continue
                if url.rstrip("/").lower() in known_urls or url in scanned:
                    continue
                scanned.add(url)
                scraper = get_scraper_for_url(url)
                batch = scraper.fetch()
                found = 0
                for entry in batch:
                    job = normalize_ats(entry, direct=True, company=name)
                    if job:
                        job["source"] = "ATS company discovery"
                        results.append(job)
                        found += 1
                print(f"[INFO] Discovered company {name}: {found} official postings via {url}")
        except Exception as exc:
            errors.append(f"Company discovery {name}: {type(exc).__name__}: {exc}")
    return results, errors


def ats_query_plan(settings: dict) -> list[dict]:
    """Generate a source-balanced rotation over search terms and ATS providers.

    Provider-first full-data queries are expensive; use source-specific slices.
    Every combination is eventually visited rather than repeating 2 fixed ones.
    """
    explicit = settings.get("queries") or []
    if explicit:
        return explicit
    terms = settings.get("terms") or []
    providers = settings.get("providers") or []
    limit = int(settings.get("limit", 180))
    return [
        {"query": term, "ats": providers[(i + shift) % len(providers)], "limit": limit}
        for shift in range(len(providers))
        for i, term in enumerate(terms)
    ] if terms and providers else []


def fetch_ats_source_sweep(config: dict) -> tuple[list[dict], list[str]]:
    """Sweep complete public ATS *source slices*, not one title keyword at a time.

    A provider's dataset is downloaded once per run, filtered in vectorized
    pandas operations, and discarded before the next provider. This covers
    many title variants without downloading the multi-GB all-sources snapshot.
    """
    from ats_scrapers import Client
    settings = config.get("ats_dataset") or {}
    providers = settings.get("providers", [])
    per_day = max(0, int(settings.get("providers_per_day", 4)))
    cap = max(100, int(settings.get("max_candidates_per_provider", 2000)))
    chosen = chosen_searches({"google_jobs_queries": providers}, per_day)
    results, errors = [], []
    print(f"[INFO] ATS source sweep: {len(chosen)} provider(s) today, {len(providers)} in cycle")
    title_criteria = (r"intern|stage|stagiaire|trainee|co.op|thesis|pdm|pfe|"
                      r"masterarbeit|abschlussarbeit|prakti|work.student")
    relevance_criteria = (
        r"mechan|mecan|mécan|mechatron|mecatron|structur|composit|simulation|"
        r"system|integrat|robot|aerospace|aeronaut|aéronaut|space|manufactur|"
        r"industrial|validat|testing|essais|test engineer|prototype|product develop|"
        r"conception|design engineer|r&d|thermal|thermi|cfd|materiaux|matériaux|"
        r"finite element|ingenieur|ingénieur|hydrogen|hydrog|energy|énergie|"
        r"quality engineering|precision engineering|production"
    )
    # Import only in live mode: offline sample/tests don't need a large dependency.
    with Client(prefer_parquet=False) as client:
        for provider in chosen:
            try:
                frame = client.load(ats=provider)
                if frame.empty or "title" not in frame.columns:
                    print(f"[INFO] ATS source {provider}: empty")
                    continue
                title = frame["title"].fillna("").astype(str)
                candidates = frame[title.str.contains(title_criteria, case=False, regex=True)]
                if "employment_type" in frame.columns:
                    by_type = frame["employment_type"].fillna("").astype(str).str.lower().eq("intern")
                    candidates = frame[title.str.contains(title_criteria, case=False, regex=True) | by_type]
                if candidates.empty:
                    print(f"[INFO] ATS source {provider}: no internships")
                    continue
                title_rel = candidates["title"].fillna("").astype(str).str.contains(
                    relevance_criteria, case=False, regex=True)
                if "description" in candidates.columns:
                    desc_rel = candidates["description"].fillna("").astype(str).str.contains(
                        relevance_criteria, case=False, regex=True)
                    relevant = candidates[title_rel | desc_rel]
                else:
                    relevant = candidates[title_rel]
                if len(relevant) > cap:
                    # Prefer a role-focused title to a generic internship description;
                    # keep high-relevance postings even when a source is huge.
                    relevant = relevant.assign(_title_relevance=title_rel.reindex(relevant.index))
                    relevant = relevant.sort_values("_title_relevance", ascending=False).head(cap)
                selected = 0
                for row in relevant.to_dict("records"):
                    job = normalize_ats(row)
                    if job:
                        results.append(job)
                        selected += 1
                print(f"[INFO] ATS source {provider}: {len(frame)} public rows; "
                      f"{len(candidates)} internships; {selected} related listings")
            except Exception as exc:
                errors.append(f"ATS source sweep {provider}: {type(exc).__name__}: {exc}")
    return results, errors


def fetch_ats_dataset(config: dict) -> tuple[list[dict], list[str]]:
    """Query the library's *hosted* ATS dataset for open-ended discovery.

    Small rotated slices keep daily network traffic and GitHub Actions time bounded.
    The publisher's dataset may lag behind company postings: always recheck.
    """
    from ats_scrapers import search
    settings = config.get("ats_dataset") or {}
    if settings.get("scan_mode") == "source_sweep":
        return fetch_ats_source_sweep(config)
    queries = ats_query_plan(settings)
    per_day = max(0, int(settings.get("searches_per_day", 2)))
    results, errors = [], []
    print(f"[INFO] ATS search rotation: {len(queries)} combinations, {per_day} requested per day")
    for spec in chosen_searches({"google_jobs_queries": queries}, per_day):
        term, provider = spec.get("query", ""), spec.get("ats", "")
        if not term:
            continue
        try:
            kwargs = {"query": term, "limit": int(spec.get("limit", 150))}
            if provider:
                kwargs["ats"] = provider
            if spec.get("location"):
                kwargs["location"] = spec["location"]
            frame = search(**kwargs)
            count = 0
            for entry in frame.to_dict("records"):
                job = normalize_ats(entry)
                if job:
                    results.append(job)
                    count += 1
            print(f"[INFO] ATS dataset {provider or 'all'}/{term!r}: {count} entries")
        except Exception as exc:
            errors.append(f"ATS dataset {provider}/{term}: {type(exc).__name__}: {exc}")
    return results, errors


def normalize_jobspy(entry: dict) -> dict | None:
    url = _scalar(entry.get("job_url_direct")) or _scalar(entry.get("job_url"))
    title = _scalar(entry.get("title"))
    if not (title and url.startswith(("http://", "https://"))):
        return None
    location = ", ".join(part for part in (
        _scalar(entry.get("city")), _scalar(entry.get("state")),
        _scalar(entry.get("country"))
    ) if part)
    return make_job(
        _scalar(entry.get("company")), title, location, url,
        _scalar(entry.get("description")),
        source="JobSpy / " + _scalar(entry.get("site")),
        posted_at=_scalar(entry.get("date_posted")),
        kind_hint=_scalar(entry.get("job_type")),
        verification="third_party_listing",
        language=_scalar(entry.get("language")),
    )


def europe_jobspy_queries(queries: list[dict]) -> list[dict]:
    """Keep non-European search tasks out of the daily rotation itself.

    This acts even when a user preserves their original v3.1 config.json.
    Unknown search geographies are retained to preserve discovery coverage.
    """
    return [query for query in queries
            if classify_location(query.get("country_indeed", "")) != "outside"
            and classify_location(query.get("location", "")) != "outside"]


def fetch_jobspy(config: dict) -> tuple[list[dict], list[str]]:
    """Search public job boards via JobSpy; no authentication or account automation."""
    from jobspy import scrape_jobs
    settings = config.get("jobspy") or {}
    queries = europe_jobspy_queries(settings.get("queries") or [])
    per_day = max(0, int(settings.get("searches_per_day", 2)))
    results, errors = [], []
    for spec in chosen_searches({"google_jobs_queries": queries}, per_day):
        term = spec.get("search_term", "")
        if not term:
            continue
        try:
            frame = scrape_jobs(
                site_name=settings.get("sites", ["indeed"]),
                search_term=term,
                location=spec.get("location", "France"),
                country_indeed=spec.get("country_indeed", "France"),
                results_wanted=int(spec.get("results_wanted", 25)),
                verbose=0,
            )
            count = 0
            for entry in frame.to_dict("records"):
                job = normalize_jobspy(entry)
                if job:
                    results.append(job)
                    count += 1
            print(f"[INFO] JobSpy {term!r}: {count} entries")
        except Exception as exc:
            errors.append(f"JobSpy {term!r}: {type(exc).__name__}: {exc}")
    return results, errors


INTERNSHIP_SIGNALS = (
    "intern", "stage", "stagiaire", "stages", "praktikum", "praktikant", "praktikantin",
    "master thesis", "masters thesis", "masterarbeit", "abschlussarbeit", "diplomarbeit",
    "projet de master", "pdm", "pfe", "co-op", "cooperative education", "traineeship"
)
ROLE_GROUPS = [
    ("design mec.", ("mechanical", "mecanique", "mechanik", "mechanical design", "konstruktion", "cad", "solidworks", "catia"), 16),
    ("integration", ("system integration", "systems integration", "systems engineering", "integration systeme", "mechatronic", "mecatron", "assembly"), 14),
    ("structures", ("structural", "structurel", "composite", "finite element", "fea", "fem", "simulation"), 14),
    ("essais", ("testing", "validation", "qualification", "test engineer", "instrumentation", "prototype"), 10),
    ("industrialisation", ("manufacturing", "industrialisation", "industrialization", "production engineering", "production quality", "process engineering"), 10),
    ("industrie", ("aerospace", "spacecraft", "aviation", "robotic", "energy systems", "hydrogen", "hydrofoil", "precision engineering"), 7),
    ("thermique", ("thermal", "thermique", "thermodynam", "heat transfer", "fluid mechanics", "cfd", "propulsion"), 9),
    ("materiaux", ("materials engineering", "materiaux", "additive manufacturing", "material science", "metal forming", "tribology"), 7),
]
BAD_TITLE = (
    "marketing", "finance", "accounting", "sales", "customer success", "legal",
    "human resources", "software developer", "web developer", "frontend", "backend",
    "machine learning", "data scientist", "business development", "talent acquisition",
    "product owner", "product management", "product operations"
)
VISA_RISKS = (
    "u.s. citizen", "us citizen", "us person", "u.s. person", "security clearance",
    "itar", "nationality requirement"
)


def looks_like_intern(job: dict) -> bool:
    title = fold(job.get("title"))
    job_type = fold(job.get("kind_hint"))
    return any(signal in title for signal in INTERNSHIP_SIGNALS) or any(
        signal in job_type for signal in ("intern", "stage", "praktikum", "trainee"))


def clearly_obsolete_cycle(title: str, today: date | None = None) -> bool:
    """Skip positions explicitly labeled for a season that has already ended.

    This is deliberately conservative: a listing without a clear season/year must
    be checked on the official site rather than treated as closed.
    """
    today = today or date.today()
    value = fold(title)
    years = [int(x) for x in re.findall(r"\b20\d{2}\b", value)]
    if not years:
        return False
    if max(years) < today.year:
        return True
    if min(years) > today.year:
        return False
    if any(term in value for term in ("summer", "sommer", "ete")) and today.month >= 9:
        return True
    if any(term in value for term in ("spring", "printemps", "fruhjahr")) and today.month >= 7:
        return True
    return False


def role_classification(job: dict) -> str:
    title = fold(job["title"])
    desc = fold(job.get("description", ""))
    thesis_words = ("master thesis", "masters thesis", "masterarbeit", "abschlussarbeit",
                    "projet de master", "master's thesis")
    if any(word in title for word in thesis_words):
        return "Master thesis / PDM"
    if any(word in desc for word in thesis_words):
        return "Stage (PDM possible: confirm with EPFL)"
    return "Stage (PDM not confirmed)"


GERMAN_TITLE_TERMS = re.compile(
    r"\b(?:praktikum|praktikant(?:in)?|werkstudent(?:in)?|masterarbeit|abschlussarbeit|"
    r"diplomarbeit|maschinenbau|entwicklungsingenieur|konstrukteur|konstrukteurin|"
    r"konstruktionsentwicklung|fertigungstechnik|produktionsplanung)\b|"
    r"\b(?:im bereich|fur unser|fur die|wir suchen|deine aufgaben)\b"
)
GERMAN_PROSE_WORDS = {
    "wir", "suchen", "dich", "unser", "unsere", "unserem", "mit", "und",
    "fur", "bereich", "kenntnisse", "anforderungen", "aufgaben", "freuen",
    "bewerbung", "sowie", "erfahrung", "eine", "einen", "deine", "einer",
    "selbststandig", "arbeit", "abgeschlossenes"
}


def infer_language(job: dict) -> str:
    cached = job.get("_stage_language_cache")
    if cached:
        return cached
    language = _infer_language_uncached(job)
    job["_stage_language_cache"] = language
    return language


def _infer_language_uncached(job: dict) -> str:
    """Prefer publisher locale; otherwise conservative prose detection.

    If detection cannot confidently identify the language, return 'unknown'
    and retain the job, avoiding loss of useful English listings.
    """
    raw = fold(job.get("language", "")).replace("_", "-")
    if raw in ("german", "deutsch") or raw == "de" or raw.startswith("de-"):
        return "de"
    if raw in ("english", "en") or raw.startswith("en-"):
        return "en"
    if raw in ("french", "francais", "fr") or raw.startswith("fr-"):
        return "fr"
    if raw:
        return raw.split("-")[0][:2]

    title = fold(job.get("title", ""))
    if GERMAN_TITLE_TERMS.search(title):
        return "de"
    description = clean_html(job.get("description", ""))
    if len(description) < 110:
        return "unknown"
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
        ranked = detect_langs(description[:4500])
        if ranked and ranked[0].prob >= 0.93:
            return ranked[0].lang
    except (ImportError, ValueError, RuntimeError):
        pass
    words = re.findall(r"[a-z]{2,}", fold(description))
    if len(words) >= 22 and len(set(words) & GERMAN_PROSE_WORDS) >= 5:
        return "de"
    return "unknown"


def requires_german(job: dict) -> bool:
    """Only reject a *mandatory* German requirement, not a nice-to-have."""
    desc = fold(job.get("description", ""))
    if re.search(r"\b(?:english or german|german or english)\b", desc):
        return False
    if re.search(r"\b(?:fluent|native|advanced|excellent|business fluent|c1|c2)\s+(?:in\s+)?german\b", desc):
        return True
    # Never let a requirement about *English* in a later clause turn an
    # optional German skill ("German a plus, English mandatory") into a hard stop.
    for match in re.finditer(r"\bgerman\b", desc):
        clause = re.split(r"[.,;]", desc[match.end():], maxsplit=1)[0][:55]
        if re.search(r"\b(?:required|mandatory|essential|must have|is necessary)\b", clause) \
                and not re.search(r"\b(?:not|required only as a plus|optional)\b", clause):
            return True
    if re.search(r"\bdeutschkenntnisse\b.{0,35}\b(?:erforderlich|vorausgesetzt|pflicht)\b", desc):
        return True
    return False


def language_excluded(job: dict, config: dict) -> bool:
    excluded = set(config.get("excluded_languages", ["de"]))
    return infer_language(job) in excluded or (config.get("exclude_required_german", True) and requires_german(job))


def analyze(job: dict, config: dict) -> dict | None:
    if (not job.get("url") or not job.get("title") or not looks_like_intern(job)
            or clearly_obsolete_cycle(job.get("title", ""))
            or language_excluded(job, config)
            or excluded_summer(job, config)
            or geography_excluded(job, config)):
        return None
    title, desc, loc = fold(job["title"]), fold(job.get("description")), fold(job.get("location"))
    if any(term in title for term in BAD_TITLE):
        return None
    score = 23
    reasons = []
    matches = []
    title_contrib = 0
    desc_contrib = 0
    for name, terms, points in ROLE_GROUPS:
        if any(term in title for term in terms):
            title_contrib += points
            matches.append(name)
        elif any(term in desc for term in terms):
            desc_contrib += max(3, points // 3)
            matches.append(name)
    score += min(42, title_contrib) + min(13, desc_contrib)
    if not matches:
        return None  # Internship in an unrelated field
    reasons.append(", ".join(matches[:4]))

    kind = role_classification(job)
    if kind == "Master thesis / PDM":
        score += 11
        reasons.append("explicit Master thesis")
    elif kind.startswith("Stage (PDM possible"):
        score += 5

    companies = [fold(x) for x in config.get("priority_companies", [])]
    company = fold(job.get("company"))
    if company and any(company == c or company in c or c in company for c in companies):
        score += 9
        reasons.append("priority company")

    # A one-line description of expected duration, if visible.
    duration = "Not specified"
    duration_patterns = (
        r"\b(5\s*[-/]\s*6|6\s*[-/]\s*7|six|6)\s*(months?|mois|monate)\b",
        r"\b(25|26)\s*weeks?\b"
    )
    combined = title + " " + desc
    if any(re.search(rx, combined) for rx in duration_patterns):
        score += 9
        duration = "5-7 months mentioned"
        reasons.append("~6 months")
    elif re.search(r"\b(2|3)\s*(months?|mois|monate)\b|\b(8|10|12)\s*weeks?\b", combined):
        score -= 7
        duration = "Short term mentioned"

    if any(term in loc for term in config.get("preferred_locations", [])):
        score += 5
        reasons.append("preferred location")
    elif not loc:
        score -= 2

    warnings = []
    location_status = classify_location(job.get("location", ""))
    if location_status == "unknown":
        warnings.append("Location not identified: confirm the position is based in Europe")
    elif location_status == "mixed":
        warnings.append("Several possible countries: confirm a European work location")
    if any(term in desc for term in VISA_RISKS):
        score -= 20
        warnings.append("Check nationality / security / export-control eligibility")
    if re.search(r"\b(c1|fluent|native|business fluent)\s+(german|deutsch)\b", desc):
        score -= 8
        warnings.append("Check German-language requirement")
    if job.get("verification") != "published_board":
        warnings.append("Confirm the opening on the employer's site")
    if kind != "Master thesis / PDM":
        warnings.append("EPFL thesis eligibility not confirmed")

    threshold = int(config.get("minimum_score", 35))
    if score < threshold:
        return None
    enriched = dict(job)
    enriched.update({
        "score": max(0, min(100, score)), "why": "; ".join(reasons),
        "warnings": "; ".join(warnings), "duration": duration,
        "kind": kind, "language": infer_language(job)
    })
    return enriched


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        qs = [(k, v) for k, v in parse_qsl(p.query)
              if k.lower() in ("job_id", "gh_jid", "id", "postingid")]
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", urlencode(qs), ""))
    except Exception:
        return url


def job_identity(job: dict) -> str:
    # Multiple job boards often copy one listing. Keep distinct locations separate.
    company = re.sub(r"\W+", "", fold(job["company"]))
    title = re.sub(r"\W+", "", fold(job["title"]))
    loc = re.sub(r"\W+", "", fold(job["location"]))
    if company and title:
        key = f"{company}|{title}|{loc}"
    else:
        key = canonical_url(job["url"])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:18]


def prefer(job_a: dict, job_b: dict) -> dict:
    # Prefer direct employer board URLs and fuller descriptions over aggregator copies.
    weight = {"ATS direct": 6, "ATS company discovery": 6, "Ashby": 5, "Greenhouse": 5, "Lever": 5,
              "Arbeitnow": 2, "Google Jobs / SerpApi": 1, "Adzuna": 1}
    def rank(job: dict) -> tuple[int, int]:
        source = job["source"]
        source_rank = 3 if source.startswith("ATS dataset") else (2 if source.startswith("JobSpy") else weight.get(source, 0))
        return (source_rank, len(job.get("description", "")))
    qa, qb = rank(job_a), rank(job_b)
    return job_a if qa >= qb else job_b


def as_record(job: dict, old: dict | None, today: str) -> dict:
    return {
        "id": job["id"], "first_seen": old.get("first_seen", today) if old else today,
        "last_seen": today, "status": old.get("status", "To review") if old else "To review",
        "score": job["score"], "company": job["company"], "title": job["title"],
        "location": job["location"], "language": job.get("language", "unknown"), "kind": job["kind"], "duration": job["duration"],
        "source": job["source"], "verification": job["verification"],
        "posted_at": job["posted_at"], "url": job["url"], "why": job["why"],
        "warnings": job["warnings"], "description_excerpt": job["description"][:300]
    }


def load_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        return {row["id"]: row for row in csv.DictReader(file) if row.get("id")}


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        out = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
        out.writeheader()
        out.writerows(rows)


def md_escape(s: str) -> str:
    return str(s).replace("|", "-").replace("[", "(").replace("]", ")")


def markdown_report(rows: list[dict], title: str, limit: int = 30) -> str:
    if not rows:
        return ""
    lines = [f"# {title}", "", f"Generated: {date.today().isoformat()}. Scores are heuristic, not admission probabilities.", ""]
    for i, job in enumerate(rows[:limit], 1):
        title_text = md_escape(job["title"])
        company = md_escape(job["company"])
        loc = md_escape(job["location"])
        lines += [f"{i}. **{job['score']}/100 - {company} - [{title_text}]({job['url']})**",
                  f"   - Location: {loc or 'Not provided'} | Language: {job.get('language', 'unknown')} | Type: {job['kind']} | Source: {job['source']}",
                  f"   - Why: {job['why']}"]
        if job.get("warnings"):
            lines.append(f"   - Check: {job['warnings']}")
        lines.append("")
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more offers in data/jobs.csv")
    return "\n".join(lines) + "\n"


def search_all(config: dict) -> tuple[list[dict], list[str]]:
    jobs, errors = [], []
    for board in config.get("boards", []):
        fn = {"ashby": fetch_ashby, "greenhouse": fetch_greenhouse, "lever": fetch_lever}.get(board.get("type", ""))
        if not fn:
            errors.append(f"Unknown ATS type for {board.get('name')}")
            continue
        try:
            batch = fn(board)
            print(f"[INFO] {board['name']}: {len(batch)} published entries")
            jobs.extend(batch)
        except Exception as exc:
            errors.append(f"{board['name']}: {exc}")
    # New engine: scan the careers sites in the configured employer watchlist.
    if config.get("ats_direct_enabled", True):
        try:
            batch, errs = fetch_ats_direct(config.get("company_careers", []))
            jobs.extend(batch)
            errors.extend(errs)
        except Exception as exc:
            errors.append(f"ATS direct initialization: {exc}")
    if config.get("company_discovery", {}).get("enabled", False):
        try:
            batch, errs = fetch_discovered_careers(config)
            jobs.extend(batch)
            errors.extend(errs)
        except Exception as exc:
            errors.append(f"Company directory initialization: {exc}")
    if (config.get("ats_dataset") or {}).get("enabled", True):
        try:
            batch, errs = fetch_ats_dataset(config)
            jobs.extend(batch)
            errors.extend(errs)
        except Exception as exc:
            errors.append(f"ATS dataset initialization: {exc}")
    if (config.get("jobspy") or {}).get("enabled", True):
        try:
            batch, errs = fetch_jobspy(config)
            jobs.extend(batch)
            errors.extend(errs)
        except Exception as exc:
            errors.append(f"JobSpy initialization: {exc}")
    if config.get("arbeitnow_enabled", True):
        try:
            batch = fetch_arbeitnow(config.get("arbeitnow_pages", 2))
            print(f"[INFO] Arbeitnow: {len(batch)} entries")
            jobs.extend(batch)
        except Exception as exc:
            errors.append(f"Arbeitnow: {exc}")
    if os.environ.get("SERPAPI_KEY"):
        batch = fetch_serpapi(config)
        print(f"[INFO] Google Jobs: {len(batch)} entries")
        jobs.extend(batch)
    else:
        print("[INFO] SERPAPI_KEY absent: worldwide Google Jobs search disabled")
    if os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"):
        batch = fetch_adzuna(config)
        print(f"[INFO] Adzuna: {len(batch)} entries")
        jobs.extend(batch)
    else:
        print("[INFO] Adzuna credentials absent: Adzuna search disabled")
    return jobs, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Published internship monitoring")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--output", default=str(ROOT / "data"))
    parser.add_argument("--sample", action="store_true", help="Run with packaged sample jobs, no Internet")
    parser.add_argument("--raw-input", help="JSON file of jobs collected by the bounded runner")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    scan_health = {}
    if args.sample:
        with open(ROOT / "tests" / "sample_jobs.json", encoding="utf-8") as f:
            raw_jobs = json.load(f)
        errors = []
    elif args.raw_input:
        with open(args.raw_input, encoding="utf-8") as f:
            raw = json.load(f)
        raw_jobs = raw.get("jobs", [])
        errors = raw.get("errors", [])
        scan_health = raw.get("source_health", {})
        if not isinstance(raw_jobs, list) or not isinstance(errors, list):
            raise ValueError("Invalid raw-input: jobs and errors must be lists")
    else:
        raw_jobs, errors = search_all(config)
    filtered_languages = 0
    filtered_summer = 0
    filtered_geography = 0
    unverified_locations = 0
    best = {}
    for job in raw_jobs:
        if not job.get("url") or not job.get("title") or not looks_like_intern(job):
            continue
        if language_excluded(job, config):
            filtered_languages += 1
            continue
        if excluded_summer(job, config):
            filtered_summer += 1
            continue
        if geography_excluded(job, config):
            filtered_geography += 1
            continue
        if classify_location(job.get("location", "")) in ("unknown", "mixed"):
            unverified_locations += 1
        job["id"] = job_identity(job)
        current = best.get(job["id"])
        best[job["id"]] = prefer(current, job) if current else job
    ranked = []
    for job in best.values():
        scored = analyze(job, config)
        if scored:
            ranked.append(scored)
    ranked.sort(key=lambda j: (j["score"], j.get("posted_at", "")), reverse=True)
    history = load_rows(outdir / "jobs.csv")
    # Apply the CURRENT selection rules to historical records, too. Preserve
    # existing status/first_seen on offers still permitted by these rules.
    cleaned_history = {}
    history_removed = {"language": 0, "summer": 0, "geography": 0}
    for key, row in history.items():
        historic_job = {
            "title": row.get("title", ""),
            "description": row.get("description_excerpt", ""),
            "language": row.get("language", ""),
            "location": row.get("location", ""),
            "kind_hint": row.get("kind", ""),
        }
        if language_excluded(historic_job, config):
            history_removed["language"] += 1
        elif excluded_summer(historic_job, config):
            history_removed["summer"] += 1
        elif geography_excluded(historic_job, config):
            history_removed["geography"] += 1
        else:
            cleaned_history[key] = row
    history = cleaned_history
    today = date.today().isoformat()
    new = []
    for job in ranked:
        record = as_record(job, history.get(job["id"]), today)
        if job["id"] not in history:
            new.append(record)
        history[job["id"]] = record
    all_rows = sorted(history.values(), key=lambda r: (
        r.get("last_seen", ""), int(r.get("score") or 0)), reverse=True)
    write_rows(outdir / "jobs.csv", all_rows)
    (outdir / "latest.md").write_text(markdown_report(
        [as_record(job, history.get(job["id"]), today) for job in ranked],
        f"Currently observed internships ({len(ranked)})", 150
    ) or "No matching internships detected in available sources.\n", encoding="utf-8")
    (outdir / "new.md").write_text(markdown_report(new, f"New internships ({len(new)})", 20), encoding="utf-8")
    (outdir / "last_run.json").write_text(json.dumps({
        "date": today, "observed": len(raw_jobs), "matches": len(ranked),
        "new": len(new), "excluded_by_language": filtered_languages,
        "excluded_by_summer": filtered_summer,
        "excluded_outside_europe": filtered_geography,
        "location_unknown_or_mixed": unverified_locations,
        "history_removed": history_removed,
        "source_counts": dict(sorted(Counter(job.get("source", "unknown") for job in raw_jobs).items())),
        "source_health": scan_health,
        "errors": errors,
        "notes": "Third-party jobs must be rechecked on the official employer page."
    }, indent=2), encoding="utf-8")
    print(f"[DONE] Raw: {len(raw_jobs)} | Rejected language: {filtered_languages} | "
          f"Rejected summer: {filtered_summer} | Rejected outside Europe: {filtered_geography} | "
          f"Relevant: {len(ranked)} | New: {len(new)} | Errors: {len(errors)}")
    for error in errors:
        print(f"[WARN] {error}", file=sys.stderr)
    return 0 if raw_jobs or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
