#!/usr/bin/env python3
"""Merge a CSV of company names into config.json priority_companies."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

KEYS = ("company", "company_name", "entreprise", "name", "societe")


def read_names(filepath: Path) -> list[str]:
    with filepath.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    index = next((i for i, c in enumerate(header) if c in KEYS), None)
    start = 1 if index is not None else 0
    column = index if index is not None else 0
    return [row[column].strip() for row in rows[start:]
            if len(row) > column and row[column].strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    path = Path(args.config)
    config = json.loads(path.read_text(encoding="utf-8"))
    names = config.get("priority_companies", []) + read_names(Path(args.csv_file))
    seen = set()
    unique = []
    for name in names:
        if name.casefold() not in seen:
            unique.append(name)
            seen.add(name.casefold())
    config["priority_companies"] = unique
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(unique)} unique company priorities to {path}")


if __name__ == "__main__":
    main()
