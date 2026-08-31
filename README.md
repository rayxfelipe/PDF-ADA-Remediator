# PDF Accessibility Screening

A Python command-line tool that screens a PDF for common accessibility barriers and creates an accessible HTML report. The screening rules are derived from a local policy source named `ADA Title II Web Accessibility.docx`. Every report finding identifies the applicable policy requirement. The source policy document and input PDFs are intentionally excluded from this repository; they are not required at runtime because the relevant screening rules are encoded in the application.

The source document requires full PDF/UA conformance for PDFs and specifically requires text alternatives for non-text content, keyboard navigation, and at least 4.5:1 color contrast. The tool screens PDF structure, language, title metadata, bookmarks, extractable text, scanned pages, figure alternatives, and form names as machine-checkable PDF/UA indicators. Keyboard operation, semantic accuracy, alternative-text quality, and contrast remain manual checks.

> This tool does not certify ADA, PDF/UA, WCAG, or Section 508 compliance and is not legal advice. Full conformance cannot be established by these automated checks. A qualified human review with assistive technology is required.

## Setup

Create and activate a Python 3.10+ virtual environment, then install dependencies:

    pip install -r requirements.txt

No Azure subscription, LLM, API key, or Microsoft Agent Framework configuration is required for the local three-script workflow.

## Run the complete workflow

    python pdf_accessibility_workflow.py "path/to/document.pdf"

The workflow uses three separate programs:

1. `pdf_accessibility_audit.py` audits the source PDF and writes JSON plus HTML reports.
2. `pdf_accessibility_remediator.py` accepts that JSON report and creates a remediated PDF copy.
3. `pdf_accessibility_workflow.py` runs the audit, opens its report, and waits. It invokes the remediator with the persisted JSON only after the **Yes, apply remediation** button is clicked.

The complete workflow:

1. Preserves the original PDF.
2. Writes and displays the audit report without creating a remediated PDF.
3. Writes `accessibility-report.json` as the contract between the two stages.
4. Waits for explicit confirmation in the browser.
5. Only after confirmation, creates `<original-name>_remediated.pdf`, re-audits it, and displays the remediation results.

Keep the terminal running while viewing the report. Press Ctrl+C when finished. Use `--no-open` to print the local report URL without automatically opening the browser.

Automatic remediation applies only deterministic PDF/UA-related updates supported by the source policy: default language, title metadata, title display preference, and structured tab order where a real structure tree exists. It does **not** pretend that an untagged PDF is tagged, invent text alternatives, infer tables/headings, alter visual contrast, or certify ADA compliance. The remediation report cites the controlling source requirement and identifies unsuccessful and manual work.

Run only the audit:

    python pdf_accessibility_audit.py "document.pdf" --output "reports/audit.html" --json "reports/audit.json" --no-open

Run only remediation, using the audit JSON:

    python pdf_accessibility_remediator.py "reports/audit.json" --output "reports/document_remediated.pdf" --report "reports/remediation.html" --no-open

Choose all complete-workflow output paths:

    python pdf_accessibility_workflow.py "document.pdf" --audit-json "reports/audit.json" --audit-report "reports/audit.html" --remediated-output "reports/document_remediated.pdf" --remediation-report "reports/remediation.html" --no-open

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
