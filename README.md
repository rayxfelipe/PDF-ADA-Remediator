# Deterministic PDF Accessibility Checker and Remediator

This repository contains a standalone Python application that deterministically checks PDF files, applies a limited set of safe remediations, and verifies the resulting PDF with the same ruleset.

The application does not require an LLM, Microsoft Foundry, an external accessibility service, or an external audit report. Its findings and remediation decisions are derived directly from the uploaded PDF through `pypdf`.

## Architecture

```text
PDF intake
  -> deterministic PDF inspection
  -> structured findings
  -> local remediation plan
  -> deterministic remediation
  -> deterministic reinspection
  -> verified before/after report
```

The source PDF is the only remediation input. Audit JSON is an output artifact and is never accepted as executable remediation instructions.

Every audit report includes:

- Schema version
- Checker version
- Ruleset version
- Source filename
- Source SHA-256
- Page count
- Stable rule identifiers
- Structured findings
- Evidence and remediation guidance

Every remediation report includes:

- Source and output SHA-256 values
- Checker and ruleset versions
- Before and after summaries
- Planned and verified actions
- Rule-level outcomes
- Items requiring human review

## Scope

The checker reports 32 Acrobat-aligned accessibility rule areas covering:

- Document properties
- Page content and navigation
- Forms
- Alternate text
- Tables
- Lists
- Heading nesting

The rules are independently implemented with `pypdf`. They do not invoke or reproduce Adobe's proprietary checker, so results can differ where Adobe uses undocumented logic.

The remediator currently applies only these deterministic changes:

- Add a missing default document language.
- Enable title display when a meaningful title already exists.
- Set structure-based page tab order when the existing structure tree passes local validation.

The remediator does not:

- Invent document titles.
- Accept generic titles such as `PowerPoint Presentation` as meaningful.
- Generate semantic tags.
- Generate OCR text.
- Invent alternate text.
- Infer tables, lists, or headings from visual formatting.
- Alter visual contrast.
- Claim ADA, WCAG, PDF/UA, or Section 508 conformance.

Human and assistive-technology review remains necessary for semantic quality, reading order, usability, and complete conformance evaluation.

## Requirements

- Python 3.10 or newer
- Dependencies in `requirements.txt`

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run the browser workflow

```powershell
python pdf_accessibility_workflow.py
```

The workflow:

1. Starts a local HTTP server.
2. Accepts a PDF upload.
3. Runs the deterministic checker.
4. Displays the audit report.
5. Waits for explicit approval.
6. Builds a remediation plan from the same local audit.
7. Writes a remediated copy without overwriting the source.
8. Rechecks the output and displays verified results.

The browser interface uses a consistent, accessible dashboard across the upload, audit, and remediation steps. It includes drag-and-drop PDF selection, progress and error states, summary metrics, section navigation, detailed finding cards, verified before-and-after outcomes, and print or download actions. The shared presentation layer is defined in `pdf_accessibility_ui.py`; it does not restore any dependency on the retired external checker.

Use `--no-open` to prevent the browser from opening automatically:

```powershell
python pdf_accessibility_workflow.py --no-open
```

Uploaded source PDFs and temporary reports are held only for the active workflow session. The local workflow persists only the remediated output under `reports/remediated`.

## Run the checker

```powershell
python pdf_accessibility_audit.py "document.pdf" --no-open
```

Default outputs:

- `reports/audits/accessibility-report.html`
- `reports/audits/accessibility-report-<file_name>.json`

## Run remediation

Remediation accepts the source PDF directly:

```powershell
python pdf_accessibility_remediator.py "document.pdf" --no-open
```

Optional arguments:

```powershell
python pdf_accessibility_remediator.py "document.pdf" `
  --output "reports/remediated/document_remediated.pdf" `
  --report "reports/remediated/document-remediation.html" `
  --language "en-US" `
  --no-open
```

No audit JSON or third-party report is accepted as remediation input.

## PDF-only remediation API

The local workflow exposes `POST /api/remediate`. The request uses `multipart/form-data` with one field:

- `pdf`: source PDF, up to 20 MB

The endpoint audits, remediates, and verifies the PDF locally. It returns the remediated file as `application/pdf`.

Set `REMEDIATOR_API_KEY` to require the same value in the `X-Remediator-Key` request header. Leaving the setting empty is suitable only for local development.

## Azure Functions

[function_app.py](./function_app.py) provides the Azure-hosted browser workflow:

1. Upload and deterministically audit a PDF.
2. Store the active job's source PDF in private blob storage.
3. Require the job token before remediation or download.
4. Re-audit the stored source immediately before remediation.
5. Return a verified remediated PDF.

The Azure workflow does not call or depend on another checker application.

## Deterministic behavior

For identical PDF bytes and the same checker and ruleset versions:

- Source SHA-256 remains identical.
- Findings and summaries remain identical.
- The same remediation plan is produced.
- Repeated remediation produces the same logical PDF-object changes.

Generation timestamps and serialized PDF bytes can differ when a PDF library rewrites a document. Verification therefore compares identified source/output hashes and rule-level object evidence rather than assuming byte-for-byte equality.

## Tests

Run the complete test suite:

```powershell
python -m unittest -v
```

The tests cover:

- Stable 32-rule output
- Repeated deterministic audits
- Source hashing and contract versions
- Language remediation
- Meaningful-title handling
- Generic-title rejection
- Correct `/MarkInfo /Marked = false` handling
- Preservation of source structure and metadata
- PDF-only workflow and API behavior
- Verified remediation reporting

## Privacy

The `.gitignore` excludes PDFs, generated reports, local settings, virtual environments, and machine-specific validation artifacts. Do not commit customer documents, report outputs containing customer content, secrets, or credentials.

## Disclaimer

This tool performs automated accessibility screening and limited deterministic remediation. It does not certify legal or standards conformance and is not legal advice. Qualified human review and assistive-technology testing are required.
