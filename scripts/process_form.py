#!/usr/bin/env python3
"""Process one form listed in manifest/forms.csv."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from irs_pdf_field_tool import process


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("form_id")
    parser.add_argument("--revision", default="auto")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    manifest = repo_root / "manifest" / "forms.csv"
    with manifest.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = next((item for item in rows if item["form_id"] == args.form_id), None)
    if row is None:
        known = ", ".join(item["form_id"] for item in rows)
        raise SystemExit(f"Unknown form_id {args.form_id!r}. Known form IDs: {known}")

    result = process(row["form_id"], row["url"], row["title"], repo_root, args.revision)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
