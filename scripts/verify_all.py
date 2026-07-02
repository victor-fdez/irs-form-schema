#!/usr/bin/env python3
"""Summarize generated form verification reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    reports = sorted((repo_root / "forms").glob("*/*/verification.json"))
    summary = []
    for report in reports:
        data = json.loads(report.read_text(encoding="utf-8"))
        summary.append(
            {
                "form_id": data.get("form_id"),
                "revision": data.get("revision"),
                "status": data.get("status"),
                "field_count": data.get("field_count"),
                "renamed_field_count": data.get("renamed_field_count"),
                "example_value_count": data.get("example_value_count"),
                "path": report.relative_to(repo_root).as_posix(),
            }
        )
    (repo_root / "manifest" / "verification_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if all(item["status"] == "ok" for item in summary) else 2


if __name__ == "__main__":
    raise SystemExit(main())
