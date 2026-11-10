# Release Notes

Customer-visible improvements to the PDF Accessibility Checker and Remediator. Version numbers below identify the application checker, not WCAG success criteria.

For current capabilities and limitations, see the [project overview](README.md). Implementation details and validation evidence are in the [developer guide](docs/developer-guide.md); earlier engineering notes remain in the [technical archive](docs/archive/technical-change-history.md).

## Unreleased

### Documentation

- Simplify the project overview around trying the app, understanding results, current limitations, and file handling.
- Separate developer guidance and historical records from the customer-facing introduction.
- Organize release notes around changes that matter to users.

## Checker version 2.4.1 - November 9, 2026

### Safer automatic fixes

- Require stronger evidence before treating an existing PDF structure as tagged or enabling structure-based navigation.
- Stop turning internal form mapping names into field descriptions; only use validated descriptive content.
- Reject language-detection results that conflict with the document's Chinese, Japanese, or Korean script.

### More accurate results

- Detect scanned or image-only pages even when other pages contain readable text.
- Recognize bookmarks when checking prerequisites for bypass navigation in multi-page documents.
- Reject more generic or technical-identifier titles, while allowing meaningful titles to match descriptive filenames. Renaming a PDF no longer changes its title result.
- Label partial-coverage passes explicitly and improve the accessibility of report tables.

### More reliable uploads

- Return an explicit unauthorized response for oversized API requests with missing or incorrect keys instead of a gateway error.

This build was deployed to the pilot on November 9, 2026. The upload-to-download workflow and oversized unauthorized requests were verified through the live site. These changes do not add LLM remediation, OCR, full structural validation, or semantic reading-order verification.

## Checker version 2.4.0 - October 28, 2026

### Clearer remediation reports

- Explain which detected issues have supported fixes, which need existing document evidence, and which remain outside the available automation.
- Verify that applied fixes succeed, existing automated passes do not regress, and repeating remediation adds no further changes.
- Preserve the original file bytes when no supported fix is available.

### Additional evidence-based repairs

- Add repairs for existing tagging declarations and unambiguous language-tag formatting. Version 2.4.1 subsequently tightened the tagging safeguards.

## Earlier updates

These highlights summarize earlier development; they are not new capabilities in the latest release.

- Establish a standalone PDF workflow that performs its own checks, applies supported fixes, and checks the output again, without requiring another tool's report.
- Add coverage reporting for all 50 WCAG 2.1 Level A and AA success criteria, with explicit limitations and separate not-applicable and out-of-scope results.
- Improve language, title, form-description, and PDF-structure checks, and stop treating missing content as an automatic pass.
- Add clearer errors for oversized, empty, corrupt, and unsupported PDFs, along with session expiration and cleanup.
- Improve navigation between upload, audit, and remediation reports.
- Remove speculative automatic tagging rather than claim that inferred structure was verified.

The [historical technical notes](docs/archive/technical-change-history.md) retain the original implementation-level change record.
