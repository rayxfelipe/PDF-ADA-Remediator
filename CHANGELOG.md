# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Separate each mapped WCAG automated result from its coverage completeness so additional-review limitations no longer erase deterministic passes or failures.
- Add partial-coverage deterministic checks for strict PDF structural parsing (WCAG 4.1.1) and declared structure-element language tags (WCAG 3.1.2).
- Expand safe remediation to populate missing form `/TU` tooltips from existing `/TM` or `/Contents` values only when every missing tooltip has a source value.
- Raise the deterministic contract to audit schema 6, checker 2.3.0, and ruleset 2026.10.3.
- Classify every WCAG 2.1 Level A/AA criterion as pass, fail, not applicable, or out of scope instead of using ambiguous manual/not-tested states.
- Add a document evidence inventory and criterion-level policy rationales with relevant W3C PDF technique identifiers.
- Exclude not-applicable and out-of-scope checks from the automated accessibility score.
- Require inherited non-empty form-field `/TU` descriptions; field names no longer count as descriptions.
- Compare declared document language with seeded, confidence-gated deterministic language detection before reporting a pass or changing `/Lang`.
- Reject generic, numbered, authoring-tool, and filename-like metadata titles, including `Scanned Document`.
- Treat absent images, annotations, links, forms, scripts, media, tables, lists, and headings as not applicable instead of vacuous passes.
- Add typed 400, 413, and 422 PDF input errors for malformed requests, oversized uploads, and unreadable PDF content.
- Expire inactive standalone workflow sessions and delete only application-owned remediated files.
- Audit Azure Function uploads before blob persistence and add expiration metadata to job blobs.
- Add a generic external corpus runner that writes per-file JSON plus summary JSON/CSV with commit, runtime, dependency, source-hash, and repeatability evidence.
- Allow container builds to receive standard pip index and trusted-host build arguments without hardcoding an organization-specific package feed.
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
- Decommission the former AI checker fork deployment, checker-only container images, and checker-exclusive Microsoft Foundry resource group; the deterministic checker/remediator remains independently deployed.
- Removed automatic baseline structure generation that inferred paragraphs, figures, and artifacts from PDF drawing operators.

### Fixed

- Return a deterministic failure for missing or invalid document `/Lang` before evaluating whether text-language detection is conclusive.
- Prefer mapped pass/fail outcomes over out-of-scope subchecks while retaining the limitation as additional-review coverage.
- Read request bodies in bounded chunks, drain oversized uploads without retaining them, and return HTTP 413 instead of closing the connection early.
- Reject oversized files in the standalone browser before upload and make the 20 MB limit configurable with `PDF_MAX_UPLOAD_BYTES`.
- Set structure-based tab order only for an applicable failed tab-order check, not for a not-applicable check.
- Interpret `/MarkInfo /Marked = false` as false instead of relying on `BooleanObject` truthiness.
- Do not accept generic metadata such as `PowerPoint Presentation` as a meaningful document title.
- Reject empty structure trees and marked content without valid structure-element mappings.
- Reject empty, corrupt, truncated, password-protected, and zero-page PDFs with explicit client errors.
- Correct W3C PDF technique references for title, links, keyboard forms, headings, and structural checks.
- Show only the source filename in reports instead of exposing the server or workstation path.

### Security

- Continue processing uploaded source PDFs in temporary storage without adding customer documents to repository history.
- Prevent caller-supplied reports from controlling executable remediation actions.
