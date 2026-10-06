# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Make the deterministic PDF audit the sole authority for remediation planning and verification.
- Accept the source PDF directly in the remediator CLI and PDF-only API.
- Add schema, checker, and ruleset versions plus source SHA-256 to deterministic audit reports.
- Add source/output SHA-256 values and verified object-level actions to remediation reports.
- Treat successful text extraction as insufficient evidence of valid character encoding; object-level or assistive-technology verification is now required.
- Preserve meaningful existing document titles while rejecting generic titles and titles that duplicate the filename.
- Set structure-based tab order only when the source document has a structure tree that passes local validation.
- Require a remediation success to show that the same local check changed from a non-passing result before remediation to a pass afterward.

### Removed

- Remove external audit-report and Markdown-report inputs from remediation.
- Remove the third-party remediation-report upload and report-driven API contract.
- Remove imported-checker scoring, evidence, manual queues, and compatibility rule mappings.
- Removed automatic baseline structure generation that inferred paragraphs, figures, and artifacts from PDF drawing operators.

### Fixed

- Interpret `/MarkInfo /Marked = false` as false instead of relying on `BooleanObject` truthiness.
- Do not accept generic metadata such as `PowerPoint Presentation` as a meaningful document title.
- Reject empty structure trees and marked content without valid structure-element mappings.

### Security

- Continue processing uploaded source PDFs in temporary storage without adding customer documents to repository history.
- Prevent caller-supplied reports from controlling executable remediation actions.
