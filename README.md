# PDF Accessibility Screening and Remediation

This is a **standalone Python application** that audits PDF files for common accessibility barriers and applies a limited set of deterministic remediations. The local workflow runs entirely on the user's computer and does not require Azure, an LLM, Microsoft Agent Framework, an API key, or an internet connection after its Python dependencies are installed.

The application uses **rules-based logic**, not generative AI. Its audit rules inspect the PDF object structure, metadata, extractable text, images, forms, and navigation features through `pypdf`. Its remediation rules make only predefined, non-destructive changes that can be applied safely without inventing document meaning.

## Accessibility-rule basis

The encoded screening policy was derived from a project-specific source document named `ADA Title II Web Accessibility.docx`. That document identifies PDF documents as in scope, calls for full PDF/UA conformance, references WCAG 2.1 Level AA and Section 508, and identifies requirements including:

- Text alternatives for non-text content
- Keyboard navigation and operation
- A minimum 4.5:1 text color-contrast ratio
- Semantic PDF structure consistent with PDF/UA expectations

The source policy document is intentionally excluded from this public repository. Its relevant screening requirements are represented in the application as named rules, and every finding identifies the source requirement used by that rule.

The automated audit reports the same 32 named rule areas shown by the Acrobat accessibility report: document properties, page-content tagging, forms, alternate text, tables, lists, and heading nesting. Each rule is reported as pass, fail, manual review, skipped, or not applicable. The checks are independently implemented with `pypdf`; they do not invoke or reproduce Adobe's proprietary checker, so results can differ where Acrobat uses undocumented logic.

The remediator can set a missing default language, add title metadata derived from the filename, enable display of the document title, and select structure-based tab order. For an untagged document, it can add a baseline structure tree that tags text objects as paragraphs, image draws as figures, and layout graphics as artifacts. Image-only pages receive a page-level Figure tag. It does not generate OCR text or alternate-text meaning, infer headings or tables, change visual contrast, or make legal compliance determinations.

### Acrobat-aligned rule coverage

| Category | Rules reported | Automatic remediation |
| --- | --- | --- |
| Document | Accessibility permission flag, Image-only PDF, Tagged PDF, Logical Reading Order, Primary language, Title, Bookmarks, Color contrast | Adds baseline tags, language, title, and title-display preference. OCR, bookmarks, reading order, permissions, and contrast remain unresolved or manual when they fail. |
| Page Content | Tagged content, Tagged annotations, Tab order, Character encoding, Tagged multimedia, Screen flicker, Scripts, Timed responses, Navigation links | Tags baseline page content and sets structure-based tab order. Annotation, encoding, multimedia, script, timing, flicker, and link issues are reported but are not rewritten automatically. |
| Forms | Tagged form fields, Field descriptions | Validates field tagging and accessible names. It does not invent missing field descriptions or restructure form widgets. |
| Alternate Text | Figures alternate text, Nested alternate text, Associated with content, Hides annotation, Other elements alternate text | Validates structure and associations. It does not invent meaningful alternate text. |
| Tables | Rows, TH and TD, Headers, Regularity, Summary | Validates existing table tags. It does not infer or rebuild table semantics. |
| Lists | List items, Lbl and LBody | Validates existing list hierarchy. It does not infer or rebuild lists. |
| Headings | Appropriate nesting | Validates heading-level order. It does not infer headings from visual formatting. |

The remediation results report includes every rule, including rules that already passed, were remediated, remain unresolved, require manual review, were skipped, or do not apply. A reported rule is not necessarily an automatically repairable rule.

> This tool is an automated screening and limited-remediation utility. It does not certify ADA, PDF/UA, WCAG, or Section 508 compliance and is not legal advice. Full conformance cannot be established by these automated checks. A qualified human review with assistive technology is required.

## Setup

Create and activate a Python 3.10+ virtual environment, then install dependencies:

    pip install -r requirements.txt

No Azure subscription, LLM, API key, or Microsoft Agent Framework configuration is required for the local three-script workflow.

## Run the complete workflow

    python pdf_accessibility_workflow.py "path/to/document.pdf"

The workflow uses three separate programs:

1. `pdf_accessibility_audit.py` audits the source PDF and writes JSON plus HTML reports.
2. `pdf_accessibility_remediator.py` accepts that JSON report and creates a remediated PDF copy.
3. `pdf_accessibility_workflow.py` runs the audit, opens its report, and waits. It invokes the remediator only after the user applies the generated audit or uploads a valid third-party remediation JSON report.

The complete workflow:

1. Preserves the original PDF.
2. Writes and displays the audit report without creating a remediated PDF.
3. Writes `reports/audits/accessibility-report-<file_name>.json` as the contract between the two stages.
4. Waits for the user to apply the generated audit or upload a third-party remediation JSON report in the browser.
5. Validates uploaded JSON and saves it under `reports/incoming`.
6. Only after either remediation action, creates `reports/remediated/<original-name>_remediated.pdf`, re-audits it, and displays the remediation results.

Local report files are organized as follows:

```text
reports/
├── incoming/       External audit/remediation JSON used as input
├── audits/         Locally generated audit JSON and HTML
└── remediated/     Remediated PDFs and remediation HTML reports
```

The entire `reports/` tree is excluded from Git because reports and PDFs can contain customer information.

## Workflow Diagram

The JSON audit report is the handoff contract between auditing and remediation. Customers can generate it with the included rules-based auditor or supply a compatible report from another application. The standalone remediator reads that persisted JSON together with the associated source PDF. It never overwrites the source PDF: when remediation is requested, it creates a new copy and then re-audits that copy to document successful, unresolved, and manual-review items.

```mermaid
flowchart LR
    A["Source PDF"] --> B["Rules-based audit"]
    B --> C["reports/audits/accessibility-report-&lt;file_name&gt;.json"]
    B --> D["reports/audits/accessibility-report.html"]

    X["Compatible external auditor"] --> Y["reports/incoming/external-report.json"]

    C --> E{"Customer requests remediation?"}
    Y --> G
    E -- "No" --> F["No PDF changes"]
    E -- "Yes" --> G["Standalone remediator"]
    A --> G
    G --> H["reports/remediated/&lt;file_name&gt;_remediated.pdf"]
    H --> I["reports/remediated/&lt;file_name&gt;-remediation.html"]

    A -. "Original preserved" .-> H
```

The two input paths shown above are supported as follows:

- **Included audit path:** `pdf_accessibility_audit.py` inspects the source PDF and writes both the JSON contract and an HTML report.
- **External audit path:** another application may provide either the canonical JSON contract or the supported Markdown-report JSON format. Store these inputs under `reports/incoming` and use `--pdf` when the source PDF cannot be resolved from a canonical report name or stored path.
- **Approval boundary:** the complete interactive workflow offers **Yes, apply remediation** for the generated audit and **Upload remediation JSON file** for a third-party report. Either action is an explicit remediation request. Running the standalone remediator is also an explicit request.
- **Output behavior:** local audit artifacts are written under `reports/audits`, while remediated PDFs and result reports are written under `reports/remediated`. The original remains unchanged.
- **Verification:** the remediated copy is audited again, and the resulting HTML report identifies remediated, unresolved, and manual-review findings.

Keep the terminal running while viewing the report. Press Ctrl+C when finished. Use `--no-open` to print the local report URL without automatically opening the browser.

The browser upload accepts JSON files up to 5 MB. The report must satisfy either the canonical `findings` schema or the supported 32-rule Markdown-report schema. Invalid uploads are rejected and removed; duplicate filenames receive a unique suffix rather than replacing an existing incoming report. The uploaded report controls which findings are remediated, while the PDF selected when the workflow started remains the source document.

Automatic remediation applies only deterministic PDF/UA-related updates supported by the source policy: default language, title metadata, title display preference, structured tab order, and baseline paragraph, figure, and artifact tagging for untagged documents. After remediation, all 32 rules appear in the result report as already passed, remediated, unresolved, manual, skipped, or not applicable. The application does **not** invent OCR text or meaningful text alternatives, infer tables/headings, alter visual contrast, or certify ADA compliance.

Run only the audit:

    python pdf_accessibility_audit.py "document.pdf" --no-open

Run only remediation, using the audit JSON:

    python pdf_accessibility_remediator.py "reports/incoming/accessibility-report-document.json" --pdf "pdf_files/document.pdf" --no-open

The audit command writes its HTML and JSON outputs under `reports/audits`. The remediation command writes the new PDF and its HTML result under `reports/remediated`. Explicit output options still override these defaults.

Default local outputs are:

- `reports/audits/accessibility-report.html`
- `reports/audits/accessibility-report-<file_name>.json`
- `reports/remediated/<file_name>_remediated.pdf`
- `reports/remediated/<file_name>-remediation.html` for the standalone remediator
- `reports/remediated/accessibility-report-remediation.html` for the complete workflow

Running the tools again for the same filename replaces the corresponding default output. Use the output options when each run must be retained separately.

An audit JSON generated by another application can be used when it follows the same JSON structure emitted by `pdf_accessibility_audit.py`. Store external inputs under `reports/incoming`. The remediator also accepts the external Markdown-report format used by `reports/incoming/T00700020111-remediation.json`:

```json
{
    "fileName": "document.pdf",
    "remediationReport": "| Rule | Severity | Status |\n|---|---|---|\n..."
}
```

The Markdown report must contain exactly one recognizable status row for each of the 32 supported rule areas. Rule names are normalized to the local `ACR-*` identifiers, statuses are converted to the local vocabulary, and details from the seven-column failures table are retained when present. Missing rules, duplicate rules, and unknown statuses are rejected instead of being inferred. Canonical JSON reports with a structured `findings` array continue to load unchanged.

When `--pdf` is omitted, name canonical reports using one of these forms so the remediator can infer the PDF filename:

- `accessibility-report-document.json` for `document.pdf`
- `accessibility-report-document.pdf.json` for `document.pdf`

If the PDF is elsewhere or the external JSON's stored `file` path came from another computer, provide the PDF explicitly:

    python pdf_accessibility_remediator.py "reports/incoming/accessibility-report-document.json" --pdf "pdf_files/document.pdf" --no-open

Output paths remain optional overrides:

    python pdf_accessibility_remediator.py "reports/incoming/accessibility-report-document.json" --pdf "pdf_files/document.pdf" --output "custom/document_remediated.pdf" --report "custom/remediation.html" --no-open

The remediator reads the persisted JSON file before opening and modifying the associated PDF. It does not rerun the original audit in place of that input. After writing the remediated copy, it audits the new copy to report which findings changed.

Choose all complete-workflow output paths:

    python pdf_accessibility_workflow.py "document.pdf" --audit-json "custom/audit.json" --audit-report "custom/audit.html" --remediated-output "custom/document_remediated.pdf" --remediation-report "custom/remediation.html" --no-open

## Exit codes

- `0`: audit completed, even if accessibility failures were found
- `1`: PDF parsing or unexpected audit error
- `2`: invalid input, inaccessible/encrypted PDF, or output error

The numerical score covers only automated checks. Manual-review items are excluded from the score and must not be treated as passed.

## Azure Functions deployment

The project also includes a Python v2 Azure Functions wrapper in `function_app.py`. It provides one function-key-protected route with actions for upload, audit, remediation, and download. Source PDFs and audit JSON reports are stored in a private `pdf-jobs` Blob container; the remediation action downloads both and passes the JSON to the remediator. A random per-job token is additionally required for remediation and download.

Required Function App settings:

- `PDF_STORAGE_ACCOUNT_URL`: Blob endpoint, such as `https://<account>.blob.core.windows.net`
- `PDF_CONTAINER_NAME`: defaults to `pdf-jobs`
- `PDF_MAX_UPLOAD_BYTES`: defaults to `20971520` (20 MB)
- `AzureWebJobsStorage__accountName`: hosting storage account name
- `AzureWebJobsStorage__credential`: `managedidentity`

The Function App's system-assigned identity requires **Storage Blob Data Contributor** on `pdf-jobs` for application files and on the hosting storage account for Functions host metadata and secrets. Do not retain an `AzureWebJobsStorage` account-key connection string when storage account key access is disabled. Open the endpoint using a Function or host key:

    https://<function-app>.azurewebsites.net/api/pdf-accessibility?code=<key>

Temporary job files contain uploaded documents. The deployed storage policy in `.azure/storage-lifecycle-policy.json` deletes block blobs under `pdf-jobs/` one day after their last modification without affecting the Function deployment package container.

## Repository privacy

The `.gitignore` excludes PDFs, Word policy documents, generated audit/remediation reports, virtual environments, local Function settings, and machine-specific deployment validation files. This prevents new customer documents and local credentials from being added accidentally. If files were tracked before these rules were added, remove them from the Git index before publishing.

The three runtime programs do not depend on test modules:

- `pdf_accessibility_audit.py`
- `pdf_accessibility_remediator.py`
- `pdf_accessibility_workflow.py`

Choose and add an appropriate `LICENSE` before making the repository public if others should be allowed to copy, modify, or redistribute the code.
