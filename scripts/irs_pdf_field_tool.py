#!/usr/bin/env python3
"""Download, rename, example-fill, and verify fillable IRS PDFs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, NameObject, TextStringObject


PYTHON = sys.executable
INHERITED_KEYS = ("/FT", "/Ff", "/DA", "/Q", "/MaxLen", "/DV", "/V", "/Opt")
SAMPLE_VALUES = {
    "first": "JANE",
    "last": "EXAMPLE",
    "name": "JANE EXAMPLE",
    "business": "EXAMPLE CONSULTING LLC",
    "street": "123 EXAMPLE STREET",
    "apt": "APT 4",
    "city": "DENVER",
    "state": "CO",
    "zip": "80202",
    "city_state_zip": "DENVER CO 80202",
    "country": "UNITED STATES",
    "tin": "123-45-6789",
    "ein": "12-3456789",
    "phone": "303-555-0100",
    "year_suffix": "25",
}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def slugify(text: str, default: str = "field") -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"\bsee instructions\b", "", text)
    text = re.sub(r"\bif any\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def all_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "Codex IRS PDF field tool"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"download did not return a PDF: {url}")
    dest.write_bytes(data)


def pdf_title(pdf: Path) -> str:
    try:
        reader = PdfReader(str(pdf))
        title = reader.metadata.title if reader.metadata else ""
        return title or ""
    except Exception:
        return ""


def revision_slug(pdf: Path, requested_revision: str = "auto") -> str:
    if requested_revision and requested_revision != "auto":
        return slugify(requested_revision)
    title = pdf_title(pdf)
    match = re.search(r"\bRev\.\s+([A-Za-z]+)\s+(\d{4})", title)
    if match:
        return f"rev-{match.group(2)}-{match.group(1).lower()}"
    match = re.search(r"\(([A-Za-z]+)\s+(\d{4})\)", title)
    if match:
        return f"rev-{match.group(2)}-{match.group(1).lower()}"
    match = re.search(r"^(\d{4})\s+", title)
    if match:
        return match.group(1)
    match = re.search(r"\((\d{4})\)", title)
    if match:
        return match.group(1)
    return "current"


def parse_pdftk_fields(pdf: Path) -> list[dict[str, Any]]:
    if not shutil.which("pdftk"):
        raise RuntimeError("pdftk is required for field inspection")
    proc = run(["pdftk", str(pdf), "dump_data_fields_utf8"])
    blocks = [b.strip() for b in proc.stdout.split("---") if b.strip()]
    fields: list[dict[str, Any]] = []
    for block in blocks:
        row: dict[str, Any] = defaultdict(list)
        for line in block.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                row[key].append(value)
        fields.append(row)
    return fields


def extract_xfa_template_fields(pdf: Path) -> list[dict[str, str]]:
    try:
        reader = PdfReader(str(pdf))
        acro = reader.trailer["/Root"].get("/AcroForm")
        if not acro:
            return []
        acro = acro.get_object()
        xfa = acro.get("/XFA")
        if not xfa:
            return []
        xfa = xfa.get_object() if hasattr(xfa, "get_object") else xfa
        packets: dict[str, bytes] = {}
        if isinstance(xfa, list):
            for i in range(0, len(xfa), 2):
                name = str(xfa[i])
                obj = xfa[i + 1].get_object()
                if hasattr(obj, "get_data"):
                    packets[name] = obj.get_data()
        if "template" not in packets:
            return []
        root = ET.fromstring(packets["template"])
    except Exception:
        return []

    fields: list[dict[str, str]] = []

    def walk(el: ET.Element) -> None:
        if local_name(el.tag) == "field":
            ui_el = next((child for child in el if local_name(child.tag) == "ui"), None)
            ui = local_name(list(ui_el)[0].tag) if ui_el is not None and list(ui_el) else ""
            items: list[str] = []
            for child in el:
                if local_name(child.tag) == "items":
                    for item in list(child):
                        text = all_text(item)
                        if text:
                            items.append(text)
            fields.append(
                {
                    "xfa_name": el.attrib.get("name", ""),
                    "ui": ui,
                    "caption": all_text(next((c for c in el if local_name(c.tag) == "caption"), None)),
                    "access": el.attrib.get("access", ""),
                    "presence": el.attrib.get("presence", ""),
                    "xfa_items": "|".join(items),
                }
            )
        for child in list(el):
            walk(child)

    walk(root)
    return fields


def original_path_slug(original: str) -> str:
    path = re.sub(r"\[(\d+)\]", r"_\1", original)
    path = path.replace("topmostSubform_0_", "")
    path = path.replace(".", "_")
    return slugify(path)


def common_friendly_name(row: dict[str, str], counts: Counter[str]) -> str | None:
    caption = row.get("caption", "")
    cap = slugify(caption, "")
    field_type = row.get("field_type", "")
    if field_type == "Button":
        if cap in {"yes", "no"}:
            return None
        if cap:
            return cap
        return None

    if cap in {"your_first_name_and_middle_initial", "first_name_and_middle_initial"}:
        return "taxpayer_first_name_middle_initial"
    if cap == "if_joint_return_spouses_first_name_and_middle_initial":
        return "spouse_first_name_middle_initial"
    if cap == "last_name":
        counts["last_name"] += 1
        return "taxpayer_last_name" if counts["last_name"] == 1 else "spouse_last_name"
    if "your_social_security_number" in cap:
        return "taxpayer_ssn"
    if "spouses_social_security_number" in cap:
        return "spouse_ssn"
    if cap.startswith("home_address_number_and_street"):
        return "taxpayer_street"
    if cap in {"apt_no", "apartment_no"}:
        return "taxpayer_apt"
    if cap.startswith("city_town_or_post_office"):
        return "taxpayer_city_state_zip"
    if cap == "foreign_country_name":
        return "taxpayer_foreign_country"
    if cap == "foreign_province_state_county":
        return "taxpayer_foreign_province_state_county"
    if cap == "foreign_postal_code":
        return "taxpayer_foreign_postal_code"
    if cap in {"name_shown_on_return", "name_s_shown_on_return"}:
        return "name_shown_on_return"
    if "name_of_u_s_person" in cap and "being_filed" in cap:
        return "taxpayer_name"
    if "taxpayer_identification_number" in cap or cap in {"tin", "identifying_number"}:
        return "taxpayer_tin"
    if cap.startswith("number_street_and_room_or_suite_no"):
        return "taxpayer_street"
    if cap == "city_or_town":
        return "taxpayer_city"
    if cap == "state_or_province":
        return "taxpayer_state_province"
    if "zip" in cap and "postal" in cap:
        return "taxpayer_postal_code"
    if cap == "country":
        return "taxpayer_country"
    if "name_of_individual_who_is_the_beneficial_owner" in cap:
        return "beneficial_owner_name"
    if "permanent_residence_address" in cap:
        return "permanent_residence_street"
    if "city_or_town_state_or_province" in cap and "postal" in cap:
        return "permanent_residence_city_state_postal"
    if "name_of_withholding_agent" in cap:
        return "withholding_agent_name"
    return None


def build_catalog(pdf: Path, form_id: str, work_dir: Path) -> list[dict[str, str]]:
    pdftk_fields = parse_pdftk_fields(pdf)
    xfa_fields = extract_xfa_template_fields(pdf)
    rows: list[dict[str, str]] = []
    for idx, pf in enumerate(pdftk_fields):
        name = pf.get("FieldName", [""])[0]
        page_match = re.search(r"\.Page(\d+)\[", name)
        xf = xfa_fields[idx] if idx < len(xfa_fields) else {}
        state_options = [o for o in pf.get("FieldStateOption", []) if o != "Off"]
        rows.append(
            {
                "form_id": form_id,
                "field_name": name,
                "page": page_match.group(1) if page_match else "",
                "field_type": pf.get("FieldType", [""])[0],
                "caption": xf.get("caption", ""),
                "state_options": "|".join(state_options),
                "xfa_items": xf.get("xfa_items", ""),
                "max_length": pf.get("FieldMaxLength", [""])[0] if pf.get("FieldMaxLength") else "",
                "field_flags": pf.get("FieldFlags", [""])[0],
                "access": xf.get("access", ""),
                "presence": xf.get("presence", ""),
                "justification": pf.get("FieldJustification", [""])[0],
            }
        )
    counts: Counter[str] = Counter()
    used: Counter[str] = Counter()
    for row in rows:
        page = row["page"] or "x"
        base = common_friendly_name(row, counts)
        if not base:
            caption_slug = slugify(row.get("caption", ""), "")
            if caption_slug and caption_slug not in {"yes", "no"}:
                base = f"p{page}_{caption_slug}"
            elif caption_slug in {"yes", "no"}:
                base = f"p{page}_{original_path_slug(row['field_name'])}_{caption_slug}"
            else:
                base = f"p{page}_{original_path_slug(row['field_name'])}"
        base = slugify(base)
        used[base] += 1
        row["friendly_name"] = base if used[base] == 1 else f"{base}_{used[base]}"

    catalog_path = work_dir / "fields.csv"
    map_path = work_dir / "field_map.csv"
    catalog_fields = [
        "form_id",
        "field_name",
        "friendly_name",
        "page",
        "field_type",
        "caption",
        "state_options",
        "xfa_items",
        "max_length",
        "field_flags",
        "access",
        "presence",
        "justification",
    ]
    with catalog_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=catalog_fields)
        writer.writeheader()
        writer.writerows(rows)
    with map_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "friendly_name",
                "original_field_name",
                "page",
                "field_type",
                "caption",
                "state_options",
                "max_length",
                "access",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "friendly_name": row["friendly_name"],
                    "original_field_name": row["field_name"],
                    "page": row["page"],
                    "field_type": row["field_type"],
                    "caption": row["caption"],
                    "state_options": row["state_options"],
                    "max_length": row["max_length"],
                    "access": row["access"],
                }
            )
    return rows


def inherited(obj: Any, key: str) -> Any:
    cur = obj
    depth = 0
    while cur is not None and depth < 12:
        if key in cur:
            return cur[key]
        parent = cur.get("/Parent")
        cur = parent.get_object() if parent else None
        depth += 1
    return None


def full_widget_name(widget: Any) -> str:
    parts: list[str] = []
    cur = widget
    depth = 0
    while cur is not None and depth < 12:
        title = cur.get("/T")
        if title is not None:
            parts.append(str(title))
        parent = cur.get("/Parent")
        cur = parent.get_object() if parent else None
        depth += 1
    return ".".join(reversed(parts))


def rename_pdf(pdf: Path, rows: list[dict[str, str]], work_dir: Path) -> Path:
    name_by_original = {row["field_name"]: row["friendly_name"] for row in rows}
    out = work_dir / "renamed.pdf"
    reader = PdfReader(str(pdf))
    writer = PdfWriter()
    writer.append(reader)
    try:
        writer.set_need_appearances_writer(True)
    except TypeError:
        writer.set_need_appearances_writer()

    new_fields = ArrayObject()
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots.get_object():
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            ft = inherited(annot, "/FT")
            if not ft:
                continue
            original = full_widget_name(annot)
            friendly = name_by_original.get(original, original_path_slug(original))
            for key in INHERITED_KEYS:
                value = inherited(annot, key)
                if value is not None:
                    annot[NameObject(key)] = value
            annot[NameObject("/T")] = TextStringObject(friendly)
            if "/Parent" in annot:
                del annot[NameObject("/Parent")]
            new_fields.append(ref)

    acro_ref = writer._root_object.get("/AcroForm")
    if not acro_ref:
        raise RuntimeError("No AcroForm found")
    acro = acro_ref.get_object()
    acro[NameObject("/Fields")] = new_fields
    acro[NameObject("/NeedAppearances")] = BooleanObject(True)
    if "/XFA" in acro:
        del acro[NameObject("/XFA")]
    with out.open("wb") as f:
        writer.write(f)
    return out


def value_for_example(row: dict[str, str]) -> str | None:
    if row.get("field_type") != "Text":
        return None
    friendly = row["friendly_name"]
    caption_slug = slugify(row.get("caption", ""), "")
    haystack = f"{friendly} {caption_slug}"
    if "calendar_year_suffix" in friendly or ("calendar_year" in haystack and "20" in row.get("caption", "")):
        return SAMPLE_VALUES["year_suffix"]
    if "first_name" in friendly:
        return SAMPLE_VALUES["first"]
    if "last_name" in friendly:
        return SAMPLE_VALUES["last"]
    if any(k in friendly for k in ("taxpayer_name", "beneficial_owner_name", "withholding_agent_name", "name_shown_on_return")):
        return SAMPLE_VALUES["name"]
    if "business_name" in friendly:
        return SAMPLE_VALUES["business"]
    if "apt" in friendly:
        return SAMPLE_VALUES["apt"]
    if "street" in friendly or "address" in friendly:
        return SAMPLE_VALUES["street"]
    if "city_state_zip" in friendly or "city_state_postal" in friendly:
        return SAMPLE_VALUES["city_state_zip"]
    if re.search(r"(^|_)city($|_)", friendly):
        return SAMPLE_VALUES["city"]
    if "state" in friendly or "province" in friendly:
        return SAMPLE_VALUES["state"]
    if "zip" in friendly or "postal" in friendly:
        return SAMPLE_VALUES["zip"]
    if "country" in friendly:
        return SAMPLE_VALUES["country"]
    if "ein" in friendly:
        return SAMPLE_VALUES["ein"]
    if "ssn" in friendly or "tin" in friendly or "identification_number" in friendly:
        return SAMPLE_VALUES["tin"]
    if "phone" in friendly:
        return SAMPLE_VALUES["phone"]
    if ("name" in caption_slug or "address" in caption_slug) and row.get("page") in {"", "1"}:
        return SAMPLE_VALUES["name"] if "name" in caption_slug else SAMPLE_VALUES["street"]
    return None


def clip_value(row: dict[str, str], value: str) -> str:
    max_len = row.get("max_length", "")
    if max_len.isdigit() and int(max_len) > 0:
        return value[: int(max_len)]
    return value


def fill_example(renamed_pdf: Path, rows: list[dict[str, str]], work_dir: Path) -> tuple[Path, dict[str, str]]:
    values: dict[str, str] = {}
    for row in rows:
        value = value_for_example(row)
        if value is not None:
            values[row["friendly_name"]] = clip_value(row, value)
    if not values:
        for row in rows:
            if row.get("field_type") == "Text":
                values[row["friendly_name"]] = clip_value(row, SAMPLE_VALUES["name"])
                break

    out = work_dir / "example_name_address.pdf"
    reader = PdfReader(str(renamed_pdf))
    writer = PdfWriter()
    writer.append(reader)
    try:
        writer.set_need_appearances_writer(True)
    except TypeError:
        writer.set_need_appearances_writer()
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=True)
    with out.open("wb") as f:
        writer.write(f)
    return out, values


def verify(form_id: str, revision: str, renamed_pdf: Path, example_pdf: Path, rows: list[dict[str, str]], values: dict[str, str], work_dir: Path) -> dict[str, Any]:
    repo_root = work_dir.parents[2]

    def repo_path(path: Path) -> str:
        return path.relative_to(repo_root).as_posix()

    renamed_dump = parse_pdftk_fields(renamed_pdf)
    example_dump = parse_pdftk_fields(example_pdf)
    renamed_names = {f.get("FieldName", [""])[0] for f in renamed_dump}
    example_values = {f.get("FieldName", [""])[0]: f.get("FieldValue", [""])[0] for f in example_dump}
    missing_names = [row["friendly_name"] for row in rows if row["friendly_name"] not in renamed_names]
    mismatches = {
        name: {"expected": value, "actual": example_values.get(name, "")}
        for name, value in values.items()
        if example_values.get(name, "") != value
    }
    text_found = False
    text_error = ""
    sample_terms = sorted({v for v in values.values() if v and len(v) >= 4}, key=len, reverse=True)
    if shutil.which("pdftotext"):
        proc = run(["pdftotext", "-layout", str(example_pdf), "-"], check=False)
        if proc.returncode == 0:
            text_found = any(term in proc.stdout for term in sample_terms[:8])
        else:
            text_error = proc.stderr.strip()
    else:
        text_error = "pdftotext not found"

    png_path = ""
    if shutil.which("pdftoppm"):
        prefix = work_dir / "example_page1"
        proc = run(
            ["pdftoppm", "-png", "-f", "1", "-l", "1", "-r", "120", "-singlefile", str(example_pdf), str(prefix)],
            check=False,
        )
        candidate = prefix.with_suffix(".png")
        if proc.returncode == 0 and candidate.exists():
            png_path = repo_path(candidate)

    result = {
        "form_id": form_id,
        "revision": revision,
        "field_count": len(rows),
        "renamed_field_count": len(renamed_names),
        "example_value_count": len(values),
        "missing_renamed_fields": missing_names,
        "example_value_mismatches": mismatches,
        "pdftotext_sample_found": text_found,
        "pdftotext_error": text_error,
        "renamed_pdf": repo_path(renamed_pdf),
        "example_pdf": repo_path(example_pdf),
        "page1_png": png_path,
        "status": "ok" if rows and not missing_names and not mismatches and text_found else "needs_review",
    }
    (work_dir / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def process(form_id: str, url: str, title: str, repo_root: Path, requested_revision: str) -> dict[str, Any]:
    staging_dir = repo_root / ".cache" / "downloads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_pdf = staging_dir / f"{form_id}.pdf"
    download(url, staged_pdf)
    revision = revision_slug(staged_pdf, requested_revision)
    work_dir = repo_root / "forms" / form_id / revision
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf = work_dir / "source.pdf"
    if not pdf.exists() or pdf.read_bytes() != staged_pdf.read_bytes():
        pdf.write_bytes(staged_pdf.read_bytes())
    source = {
        "form_id": form_id,
        "title": title,
        "source_url": url,
        "revision": revision,
        "pdf_title": pdf_title(pdf),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    (work_dir / "source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    rows = build_catalog(pdf, form_id, work_dir)
    if not rows:
        raise RuntimeError(f"No fillable fields found for {form_id}")
    renamed_pdf = rename_pdf(pdf, rows, work_dir)
    example_pdf, values = fill_example(renamed_pdf, rows, work_dir)
    result = verify(form_id, revision, renamed_pdf, example_pdf, rows, values, work_dir)
    result["title"] = title
    result["source_url"] = url
    result["work_dir"] = work_dir.relative_to(repo_root).as_posix()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--form-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--revision", default="auto")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    args = parser.parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    repo_root.mkdir(parents=True, exist_ok=True)
    result = process(args.form_id, args.url, args.title or args.form_id, repo_root, args.revision)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
