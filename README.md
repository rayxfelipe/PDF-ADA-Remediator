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
- A checker-to-remediator coverage inventory for all 34 deterministic checks
- Explicit automatic, evidence-dependent, manual/external, prohibited, already-passing, and not-applicable remediation classifications
- The evidence missing from each unfixed item and the human action required
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
- Propagate an existing widget contents value (`/Contents`) into a missing or invalid tooltip (`/TU`) only when every affected tooltip has a validated descriptive source value. Mapping names (`/TM`) are never used as labels.
- Set `/MarkInfo /Marked` only when a structure tree, parent tree, existing structure elements, and marked-content coverage on every page already prove that the document is tagged.
- Normalize invalid structure-element language tags only when their language identity is unambiguous, such as `en_US` to `en-US`.

Every remediation run rejects an output if the page count changes, an existing deterministic pass regresses, an applied action does not verify as passing, or a second remediation plan would make additional changes. When no safe action is available, the source bytes are copied unchanged.

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

### Latest customer-feedback follow-up

The checker and Azure pilot are now 2.4.1 (ruleset 2026.11.1). Partial-coverage criterion passes are explicitly labeled **Pass (partial coverage)** in both reports. Bookmarks can satisfy multi-page bypass-navigation prerequisites, any image-only page fails the image-only check even in a mixed document, and placeholder/filename titles and field labels are rejected more strictly.

Title validation rejects technical filename identifiers even after a PDF is renamed. Unlike a blanket filename-stem rejection, a descriptive title may match a descriptive filename; this avoids filename-dependent results and follows PDF18's descriptive-title requirement.

Language detection normalizes regional detector codes and rejects script-inconsistent CJK results. Inconclusive Chinese detection does not invent a language: a missing `/Lang` remains a failure.

The October 28 feedback also requests LLM-generated alt text, tagging, titles, OCR, broader machine checks, stronger independent PDF validation, and revised remediation capability classifications. Those capabilities are **not implemented in this follow-up**. The application still performs no model calls and must not be described as completing that entire prompt. A strict-parser pass is still only partial structural-validation coverage; reading-order semantics are not verified.

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

The browser interface uses a consistent, accessible dashboard across the upload, audit, and remediation steps. It includes drag-and-drop PDF selection, progress and error states, summary metrics, section navigation, detailed finding cards, verified before-and-after outcomes, and print or download actions. Audit and remediation reports provide **Home / New upload** at the top and **Home** at the bottom; both use the session-reset route so a new PDF can be selected immediately. The shared presentation layer is defined in `pdf_accessibility_ui.py`; it does not restore any dependency on the retired external checker.

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
The key is checked before body processing. Requests with a missing or wrong key are drained in bounded chunks without retaining their bodies before HTTP 401 is sent, including oversized requests. These request-handling changes require deployment and live-proxy smoke testing before they can be claimed as fixed on the hosted app.

## Verified Azure deployment (2.4.1)

The source changes for 2.4.1 described above have not been deployed. The following deployment details and live checks were last verified on October 28, 2026.

The staging/pilot App Service is available at:

<https://app-ada-remediator-poc-33f3poc.azurewebsites.net>

The deployed standalone browser workflow runs `pdf_accessibility_workflow.py` from the immutable container image:

- Image: `crpdfadastaging33f3.azurecr.io/pdf-ada-remediator:remed241-6587756`
- Digest: `sha256:31e15e4998fa3f988718211cd7e9d51119269f68bc514419f055f5826036b322`
- Application source commit: `6587756f70d015e9b152a821f542d0f8d5891394`
- Checker version: `2.4.1`
- Ruleset version: `2026.11.1`
- Audit schema: `6`

Release validation completed on November 9, 2026:

- All 36 local tests passed. The exact ACR-built production image additionally passed 35 production-compatible tests; only the Git-dependent development corpus-runner test was excluded from that container run.
- ACR build `ccx` succeeded using `Dockerfile.azure`. The pulled image ran as non-root `app` with Python 3.12.16 and pypdf 6.21.4; its dependency check passed.
- Live health, PDF upload, audit, approval, remediation report, download, and session reset succeeded using a synthetic PDF. The report exposed checker `2.4.1`, ruleset `2026.11.1`, and no-regression/idempotence checkpoints.
- The live downloaded PDF's SHA-256 matched direct remediation of the same input inside the exact production image.
- Missing and wrong API keys with 25 MB bodies both returned HTTP 401 through the live Azure proxy, not 502. A corrupt browser upload returned a readable HTTP 422.
- The local production-image API returned 413 for an authorized 25 MB body, 422 for a corrupt PDF, and 200 with the expected output hash for a valid PDF. Authorized live API checks were not run because the existing API key is protected by private Key Vault access; no secrets, access rules, or networking were changed.

The previous `remed24-984700f` image remains available for rollback. No infrastructure was provisioned or changed.

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

## Current source and deployed behavior (2.4.1)

- Checker version: `2.4.1`
- Ruleset version: `2026.11.1`
- Audit schema: `6`
- Missing or invalid document `/Lang` values fail even when language detection is inconclusive.
- Mapped deterministic WCAG results are reported independently from additional-review coverage.
- Strict PDF structural parsing contributes a partial-coverage machine result for WCAG 4.1.1.
- Declared structure-element language tags contribute a partial-coverage machine result for WCAG 3.1.2.
- Remediation reports classify every deterministic check and state why automation is unavailable, what evidence is missing, and what a human should do.
- Existing structure metadata can be declared as tagged only when every page passes local marked-content coverage; this does not generate tags or establish full parent-tree integrity. Unambiguous structure-language tags can be normalized without guessing.
- Remediation verifies page-count preservation, no regression of existing passes, action success, and an empty second-pass plan.
- Visual and semantic criteria remain out of scope when the application lacks a reliable renderer, OCR comparison, passage detector, or visible-label association; they are not relabeled as passing.

Local validation completed on November 9, 2026:

- 36 automated tests passed; the modified production modules had no Pylance diagnostics.
- Of 174 unique available local PDFs, 173 readable files passed repeated audit/output, independent re-audit, idempotence, no-action byte-preservation, unchanged text/pages/content streams, and no-remediation-regression checks. One already-corrupt input was rejected before and after the changes.
- Source hashes were unchanged for all 173 readable inputs. Rendering/pixel comparisons were not performed.
- Local HTTP smoke tests returned 401 for 25 MB requests with missing or wrong API keys, 413 for an authorized 25 MB request, 200 for a valid PDF, and 422 with a readable error for a corrupt PDF. The valid response hash matched direct remediation.
- The available PDFs did not match the hashes in the latest 157-file customer manifest; these results are not a rerun of that exact corpus.
- Stricter checker rules can reduce pass counts compared with 2.4.0 by exposing prior false passes. This is separate from verifying that remediation itself does not regress a source pass under the same checker.
- The same 2.4.1 application build is deployed; live Azure proxy checks are documented in the deployment section above.

## Deterministic behavior

For identical PDF bytes and the same checker and ruleset versions:

- Source SHA-256 remains identical.
- Findings and summaries remain identical.
- The same remediation plan is produced.
- Independent remediation runs produce byte-identical outputs.
- A second remediation pass produces no actions and preserves the first output byte for byte.
- A no-action remediation preserves the source byte for byte.

Generation timestamps differ, but repeated runs with the same runtime and dependency versions produce identical findings, WCAG matrices, remediation plans, and output hashes.

## Run an external corpus regression

Keep customer PDFs and manifests outside tracked repository content. A local ignored context folder is also acceptable. Point the generic runner at the corpus directory:

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
- Validated `/Contents` to `/TU` propagation with post-remediation verification, and rejection of `/TM` as a label source
- CJK script-consistency guards and regional detector-code normalization
- Marked-content coverage before structure declaration or tab-order repair
- Mixed text/image-only pages and bookmark-based bypass-navigation prerequisites
- Partial-coverage report labels and captioned tables
- Separation of automated WCAG outcomes from additional-review coverage
- Strict PDF structural-validation results
- Exact and oversized upload-body handling, including draining unauthorized API requests before HTTP 401
- Typed empty, corrupt, truncated, encrypted, and zero-page PDF errors
- Session expiration and application-owned output cleanup
- External corpus JSON/CSV and repeatability output
- Correct `/MarkInfo /Marked = false` handling
- Preservation of source structure and metadata
- PDF-only workflow and API behavior
- Verified remediation reporting

## Privacy

The `.gitignore` excludes PDFs, generated reports, local settings, virtual environments, and machine-specific validation artifacts. The entire local `Evan Testing/` folder is ignored and is used only for development context; its emails, scripts, archives, and results are not repository content. Do not commit customer documents, report outputs containing customer content, secrets, or credentials.

## Disclaimer

This tool performs automated accessibility screening and limited deterministic remediation. It does not certify legal or standards conformance and is not legal advice. Qualified human review and assistive-technology testing are required.
