# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Compare pre-remediation and post-remediation scores using the same local audit implementation, while displaying the input report score separately.
- Preserve external report evidence notes, source severity labels, WCAG or best-practice distinctions, remediation guidance, and manual verification tasks.
- Retain additional external findings outside the 32 Acrobat-named rules using stable `EXT-*` identifiers.
- Treat successful text extraction as insufficient evidence of valid character encoding; object-level or assistive-technology verification is now required.
- Preserve meaningful existing document titles and enable title display without deriving replacement titles from filenames.
- Set structure-based tab order only when the source document has a structure tree that passes local validation.
- Require a remediation success to show that the same local check changed from a non-passing result before remediation to a pass afterward.

### Removed

- Removed automatic baseline structure generation that inferred paragraphs, figures, and artifacts from PDF drawing operators.

### Fixed

- Expand external page expressions such as `1-6` and `1, 3-5` into complete page lists.
- Reject empty structure trees and marked content without valid structure-element mappings.
- Match supported legacy finding identifiers to their current Acrobat-aligned checks during outcome reporting.
- Reject browser and API remediation reports that name a different source PDF.
- Enforce the exact 5 MiB remediation-report payload limit independently of multipart framing.
- Return client errors for malformed or mismatched uploaded reports instead of internal-server errors.

### Security

- Continue processing uploaded source PDFs and reports in temporary storage, without adding customer documents or report payloads to repository history.
