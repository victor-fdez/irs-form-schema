# IRS Form Schema

Versioned, machine-readable field maps for programmatically filling IRS PDF
forms.

IRS fillable PDFs often expose internal field names such as
`topmostSubform[0].Page1[0].f1_14[0]`. This project catalogs those fields,
assigns stable human-readable names such as
`taxpayer_first_name_middle_initial`, and produces a renamed PDF that can be
filled with ordinary PDF tooling.

The long-term goal is to build a complete, revision-aware repository of IRS
forms that applications can discover, inspect, and fill without reverse
engineering each PDF independently.

> [!IMPORTANT]
> This project helps populate PDF fields. It does not calculate taxes, validate
> a return against IRS rules, sign forms, or electronically file them.

## What Is Included

Each form revision is stored as a self-contained dataset:

```text
forms/<form-id>/<revision>/
|-- source.pdf                # Original PDF downloaded from the IRS
|-- source.json               # Source URL, title, revision, and processing time
|-- fields.csv                # Full extracted field catalog
|-- field_map.csv             # Friendly names mapped to original PDF field names
|-- renamed.pdf               # Fillable PDF using the friendly field names
|-- example_name_address.pdf  # Generated smoke-test PDF
|-- example_page1.png         # Preview of the smoke test
`-- verification.json         # Machine-readable verification results
```

For example:

```text
forms/1040/2025/
forms/1042-s/2026/
forms/w-8ben/rev-2021-october/
```

The current dataset covers the individual Form 1040 family, common credits and
schedules, Forms W-4 and W-9, taxpayer identification and certification forms,
Form 1042 and related withholding forms, and the W-8 certificate family. See
[`manifest/forms.csv`](manifest/forms.csv) for the source list.

## Quick Start

### Requirements

- Python 3.10 or newer
- [`pypdf`](https://pypi.org/project/pypdf/)
- `pdftk`
- Poppler tools: `pdftotext` and `pdftoppm`

On macOS with Homebrew:

```sh
brew install pdftk-java poppler
python3 -m pip install pypdf
```

On Debian or Ubuntu:

```sh
sudo apt-get install pdftk-java poppler-utils
python3 -m pip install pypdf
```

### Process One Manifest Form

```sh
python3 scripts/process_form.py 1040 --repo-root "$PWD"
```

The script downloads the form, detects its revision, extracts its fields,
creates friendly names, writes the renamed PDF, fills an example, renders its
first page, and records the verification result.

To process a form that is not yet in the manifest:

```sh
python3 scripts/irs_pdf_field_tool.py \
  --form-id 1099-nec \
  --title "Form 1099-NEC" \
  --url "https://www.irs.gov/pub/irs-pdf/f1099nec.pdf" \
  --repo-root "$PWD"
```

Use `--revision <revision>` when automatic revision detection is not sufficient.

### Process The Full Manifest

```sh
python3 scripts/process_manifest.py \
  --jobs 2 \
  --skip-existing-ok \
  --repo-root "$PWD"
```

You can also process only selected form IDs:

```sh
python3 scripts/process_manifest.py \
  --jobs 2 \
  --repo-root "$PWD" \
  1040 w-9 w-8ben
```

## Fill A Renamed Form

The generated `renamed.pdf` can be filled using its friendly field names:

```python
from pathlib import Path

from pypdf import PdfReader, PdfWriter

source = Path("forms/1040/2025/renamed.pdf")
destination = Path("filled-1040.pdf")

values = {
    "taxpayer_first_name_middle_initial": "JANE A",
    "taxpayer_last_name": "EXAMPLE",
    "taxpayer_ssn": "123456789",
    "taxpayer_street": "123 EXAMPLE STREET",
    "taxpayer_apt": "APT 4",
    "taxpayer_city_state_zip": "DENVER",
    "p1_state": "CO",
    "p1_zip_code": "80202",
}

reader = PdfReader(source)
writer = PdfWriter()
writer.append(reader)

for page in writer.pages:
    writer.update_page_form_field_values(
        page,
        values,
        auto_regenerate=True,
    )

with destination.open("wb") as output:
    writer.write(output)
```

Inspect `field_map.csv` before filling a form. It documents the available field
names, field types, checkbox or radio-button states, maximum lengths, page
numbers, and captions extracted from the PDF.

## Field Data

`fields.csv` is the detailed extraction result. Its columns include:

| Column | Description |
| --- | --- |
| `form_id` | Repository form identifier |
| `field_name` | Original field name embedded in the IRS PDF |
| `friendly_name` | Generated human-readable field name |
| `page` | PDF page containing the field, when detectable |
| `field_type` | PDF field type, such as `Text` or `Button` |
| `caption` | Label extracted from the XFA template, when available |
| `state_options` | Valid non-off states for buttons |
| `xfa_items` | Choice values extracted from XFA |
| `max_length` | Maximum text length declared by the PDF |
| `field_flags` | Raw PDF field flags |
| `access` | XFA access setting |
| `presence` | XFA presence setting |
| `justification` | Text alignment declared by the field |

`field_map.csv` is a smaller, consumer-oriented view containing the information
most applications need to identify and fill a field.

Friendly names are generated from captions where possible. Well-known identity
and address fields receive consistent semantic names. Fields without useful
metadata receive deterministic page-and-path names such as
`p1_topmostsubform_0_page1_0_f1_04_0`. These fallback names are usable, but they
are good candidates for future manual curation.

## Revisions And Naming

Form IDs use lowercase kebab-case:

```text
1040
1040-schedule-c
1042-s
w-8ben
w-8ben-e
```

Every revision has a separate directory so a newly published IRS form does not
overwrite an older map. Revisions are represented as either a tax year or a
publication revision:

```text
2025
2026
rev-2024-march
rev-2025-december
```

## Verification

Run the repository-wide verification summary:

```sh
python3 scripts/verify_all.py --repo-root "$PWD"
```

The command writes `manifest/verification_summary.json` and exits nonzero if
any generated revision needs review.

A form revision is marked `ok` when:

- the source PDF exposes fillable fields;
- every generated friendly name exists in `renamed.pdf`;
- example values survive a fill-and-read round trip; and
- `pdftotext` finds at least one sample value in the example PDF.

This checks the mechanics of extraction, renaming, and filling. It does not
prove that every generated name has the correct tax meaning or that the
completed form is valid for filing.

## Add Or Update A Form

1. Add the form ID, title, category, and official IRS PDF URL to
   `manifest/forms.csv`.
2. Run `python3 scripts/process_form.py <form-id> --repo-root "$PWD"`.
3. Review `field_map.csv`, especially fallback names and button state options.
4. Open `example_name_address.pdf` or `example_page1.png` and inspect the
   rendered values.
5. Confirm that `verification.json` reports `"status": "ok"`.
6. Run `python3 scripts/verify_all.py --repo-root "$PWD"`.

When an IRS revision changes field meaning or layout, preserve the previous
revision and add the new output alongside it.

## Roadmap

- Expand the manifest toward complete IRS form coverage.
- Manually curate generated fallback names into stable semantic names.
- Publish a versioned schema for form and field metadata.
- Add a high-level API that accepts structured data and returns a filled PDF.
- Track field-level changes between IRS revisions.
- Add validation rules, required-field metadata, and repeatable field groups.
- Provide language-specific packages and generated types.
- Automate checks for newly published IRS revisions.

## Contributing

Contributions are especially useful for:

- adding missing forms or newer revisions;
- reviewing ambiguous generated field names;
- documenting checkbox, radio-button, and choice values;
- improving extraction across unusual IRS PDF structures; and
- adding fixtures and tests for regressions.

Please keep each mapping tied to the exact PDF revision it describes. Generated
verification passing is the baseline; human review of field meaning is still
valuable.

## Disclaimer

This project is not affiliated with or endorsed by the Internal Revenue
Service. It is provided for software-development and interoperability purposes,
not as tax, legal, or filing advice. Always verify completed forms against the
official IRS form and instructions for the applicable revision.
