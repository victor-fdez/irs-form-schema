#!/usr/bin/env python3
"""Process forms from manifest/forms.csv with bounded concurrency."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def run_form(repo_root: Path, form_id: str) -> dict:
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "process_form.py"),
        form_id,
        "--repo-root",
        str(repo_root),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    result = {
        "form_id": form_id,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "status": "failed",
    }
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            result.update(parsed)
            result["status"] = parsed.get("status", "failed")
        except json.JSONDecodeError:
            pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--skip-existing-ok", action="store_true")
    parser.add_argument("form_ids", nargs="*")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    manifest = repo_root / "manifest" / "forms.csv"
    with manifest.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    wanted = set(args.form_ids)
    form_ids = [row["form_id"] for row in rows if not wanted or row["form_id"] in wanted]
    if args.skip_existing_ok:
        filtered = []
        for form_id in form_ids:
            reports = sorted((repo_root / "forms" / form_id).glob("*/verification.json"))
            if reports and all(json.loads(report.read_text()).get("status") == "ok" for report in reports):
                continue
            filtered.append(form_id)
        form_ids = filtered

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
        futures = {executor.submit(run_form, repo_root, form_id): form_id for form_id in form_ids}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({k: result.get(k) for k in ("form_id", "revision", "status", "returncode", "field_count")}))

    results.sort(key=lambda item: item["form_id"])
    summary_path = repo_root / "manifest" / "last_run_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(result.get("status") == "ok" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
