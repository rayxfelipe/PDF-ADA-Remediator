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
- A document evidence inventory
- Evidence and remediation guidance

Every remediation report includes:

- Source and output SHA-256 values
- Checker and ruleset versions
- Before and after summaries
- Planned and verified actions
- Rule-level outcomes
- Explicit out-of-scope outcomes
- A complete WCAG 2.1 Level A/AA coverage matrix
- Explicit mappings from WCAG criteria to deterministic application checks
- Policy rationale and relevant W3C PDF technique identifiers
- Pre- and post-remediation checkpoints
- Four result states: pass, fail, not applicable, and out of scope
- Separate automated-result and coverage fields so an additional-review limitation cannot erase a deterministic pass or failure
- An automated determination that remains incomplete while deterministic failures remain and separately identifies out-of-scope coverage

The numerical result is labeled an **automated accessibility score**. It measures the deterministic checks implemented by this application and must not be interpreted as a WCAG compliance percentage.

## Scope

The checker reports 34 Acrobat-aligned and deterministic validation rule areas covering:

- Document properties
- Page content and navigation
- Forms
- Alternate text
- Tables
- Lists
- Heading nesting
- Strict PDF structural parsing
- Declared language changes in structure elements

The rules are independently implemented with `pypdf`. They do not invoke or reproduce Adobe's proprietary checker, so results can differ where Adobe uses undocumented logic.

The remediator currently applies only these deterministic changes:

- Set or correct the default document language only when repeatable text-language evidence is sufficiently strong.
- Enable title display when a meaningful title already exists.
- Set structure-based page tab order when the existing structure tree passes local validation.
- Propagate an existing form mapping name (`/TM`) or widget contents value into a missing tooltip (`/TU`) only when every missing tooltip has a source value.

The remediator does not:

- Invent document titles.
- Accept generic titles such as `PowerPoint Presentation` as meaningful.
- Accept placeholders such as `Scanned Document`, numbered scan names, or filename-like titles as meaningful.
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
In-memory browser sessions expire after one hour by default, and their application-owned remediated files are deleted. Set `WORKFLOW_SESSION_TTL_SECONDS` to change the timeout.

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
The request body is read in bounded chunks. Oversized request bodies are consumed without being retained and return HTTP 413 consistently; the browser also rejects files above the configured limit before upload. Set `PDF_MAX_UPLOAD_BYTES` to change the default 20 MB limit.

Set `REMEDIATOR_API_KEY` to require the same value in the `X-Remediator-Key` request header. Leaving the setting empty is suitable only for local development.

## Current Azure deployment

The staging/pilot App Service is available at:

<https://app-ada-remediator-poc-33f3poc.azurewebsites.net>

The deployed standalone browser workflow runs `pdf_accessibility_workflow.py` from the immutable container image:

- Image: `crpdfadastaging33f3.azurecr.io/pdf-ada-remediator:wcag6-8e0c1a9`
- Digest: `sha256:f929ade6a2cedbcfdaa03286fa9dbf195a0c3bb429fa5e0790a26e51c4d0db64`
- Checker version: `2.3.0`
- Ruleset version: `2026.10.3`
- Audit schema: `6`

Release validation completed on October 27, 2026:

- 24 unit and integration tests passed.
- All 42 external source PDFs passed two-run audit, WCAG matrix, source-hash, output-hash, and reported-hash repeatability checks.
- All 76 tagged-set records passed the same repeatability and hash checks.
- The production container built and ran as the non-root `app` user.
- Live health, audit, remediation, and remediated-PDF download checks succeeded.
- The live report exposes checker `2.3.0`, ruleset `2026.10.3`, additional-review coverage, and corrected missing-language failures.
- A PDF exactly at the 20 MB payload limit was accepted; a PDF one byte over the limit returned HTTP 413.

The deployment uses the existing App Service managed identity for ACR access. No customer corpus files or generated corpus reports are stored in this repository.

## Azure Functions

[function_app.py](./function_app.py) provides an alternative Azure Functions hosting surface:

1. Upload and deterministically audit a PDF.
2. Store the active job's source PDF in private blob storage.
3. Require the job token before remediation or download.
4. Re-audit the stored source immediately before remediation.
5. Return a verified remediated PDF.

The Azure Functions workflow does not call or depend on another checker application. The current pilot endpoint above uses the standalone App Service workflow rather than this Functions entry point.
Job blobs include an expiration timestamp and are covered by the storage lifecycle policy. Set `PDF_JOB_TTL_HOURS` to change the metadata timestamp; the deployed lifecycle policy remains the deletion authority.

## Current release behavior

- Checker version: `2.3.0`
- Ruleset version: `2026.10.3`
- Audit schema: `6`
- Missing or invalid document `/Lang` values fail even when language detection is inconclusive.
- Mapped deterministic WCAG results are reported independently from additional-review coverage.
- Strict PDF structural parsing contributes a partial-coverage machine result for WCAG 4.1.1.
- Declared structure-element language tags contribute a partial-coverage machine result for WCAG 3.1.2.
- Visual and semantic criteria remain out of scope when the application lacks a reliable renderer, OCR comparison, passage detector, or visible-label association; they are not relabeled as passing.

Validation completed on October 27, 2026:

- 24 unit and integration tests passed.
- Pylance reported no diagnostics in the modified production modules.
- Python compilation and Azure Function import checks passed.
- The production container ran as the non-root `app` user.
- Container health returned HTTP 200.
- A PDF exactly at the 20 MB payload limit returned HTTP 303 after audit; a PDF one byte over the limit returned HTTP 413.
- All 42 external source PDFs and all 76 tagged-set records passed the two-run repeatability and hash gates with zero errors.

## Deterministic behavior

For identical PDF bytes and the same checker and ruleset versions:

- Source SHA-256 remains identical.
- Findings and summaries remain identical.
- The same remediation plan is produced.
- Repeated remediation produces the same logical PDF-object changes.

Generation timestamps differ, but repeated runs with the same runtime and dependency versions are expected to produce identical findings, WCAG matrices, remediation plans, and output hashes.

## Run an external corpus regression

Keep customer PDFs and manifests outside the repository. Point the generic runner at that external directory:

```powershell
python corpus_regression.py `
  --input-dir "C:\path\to\external-corpus" `
  --out "reports\corpus"
```

Use `--manifest "C:\path\to\manifest.json"` when only listed files should run. A manifest is a JSON list of relative paths, objects with a `file` property, or records whose first value is the relative path.

The runner audits and remediates every file twice and writes:

- One JSON record per source PDF
- `corpus-summary.json`
- `corpus-summary.csv`
- Git commit, dirty-worktree state, application-code fingerprint, Python, `pypdf`, `langdetect`, schema, checker, and ruleset versions
- Source hashes and audit, matrix, remediation-output, and reported-hash repeatability checks

The default `reports` directory is ignored by Git.

## Tests

Run the complete test suite:

```powershell
python -m unittest -v
```

The tests cover:

- Stable 34-rule output
- Repeated deterministic audits
- Source hashing and contract versions
- Language match, mismatch, missing/invalid declaration precedence, insufficient-evidence, and remediation behavior
- Meaningful-title handling
- Placeholder and filename-like title rejection
- Correct not-applicable and out-of-scope classification
- Inherited form-field `/TU` validation
- Safe `/TM` or `/Contents` to `/TU` propagation with post-remediation verification
- Separation of automated WCAG outcomes from additional-review coverage
- Strict PDF structural-validation results
- Exact and oversized upload-body handling
- Typed empty, corrupt, truncated, encrypted, and zero-page PDF errors
- Session expiration and application-owned output cleanup
- External corpus JSON/CSV and repeatability output
- Correct `/MarkInfo /Marked = false` handling
- Preservation of source structure and metadata
- PDF-only workflow and API behavior
- Verified remediation reporting

## Privacy

The `.gitignore` excludes PDFs, generated reports, local settings, virtual environments, and machine-specific validation artifacts. Do not commit customer documents, report outputs containing customer content, secrets, or credentials.

## Disclaimer

This tool performs automated accessibility screening and limited deterministic remediation. It does not certify legal or standards conformance and is not legal advice. Qualified human review and assistive-technology testing are required.
