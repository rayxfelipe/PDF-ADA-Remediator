# Customer Accessibility Validation - September 21, 2026

> **Historical record:** This validation describes the former external-report integration. That integration was removed on 2026-10-06. The current application performs its own deterministic audit, remediation planning, remediation, and verification without accepting another application's report as input.

## Purpose

This record captures the repository-relevant results of customer testing performed on September 21, 2026, the resulting implementation changes, and the work that remains dependent on another application or qualified human review.

The customer evaluated PDF-ADA-Remediator at commit `3f42f850493876f5d4f0b31f21be0b1968bf47ef`. The fixes documented here were developed later on `feature/ada-checker-remediation-poc`.

No customer PDF, full customer report, credentials, or other sensitive payload is stored in this document.

## Test context

- The workflow combined a PDF Accessibility Checker report with PDF-ADA-Remediator.
- The manual JSON handoff, PDF upload, confirmation, result display, and PDF retrieval worked.
- The checker report was based partly on extracted text and rendered pages without complete object-level inspection.
- The evaluation distinguished the required WCAG 2.1 Level A and AA baseline from voluntary WCAG 2.2 Level A and AA targets and supporting Acrobat-style checks.
- The evaluation did not include a new checker run on the output, Adobe Acrobat comparison, PAC or veraPDF validation, screen-reader testing, or a complete manual WCAG assessment.

## Implementation disposition

| Customer finding | Disposition | Repository change | Verification | Remaining dependency |
| --- | --- | --- | --- | --- |
| `1-6` became `[1, 6]` and `1, 3-5` became `[1, 3, 5]`. | Fixed | External page ranges are expanded to every page in each range. | Regression test covers `1, 3-5` as `[1, 3, 4, 5]`. | None. |
| Source severity and WCAG or best-practice distinctions were replaced by generic local values. | Fixed | Findings retain the source severity label and standards or best-practice text in addition to the normalized local severity. | Import regression test verifies both fields. | The checker must continue providing these columns. |
| Overall evidence qualifications and the eight-item manual queue were lost downstream. | Fixed | Imported evidence and standards notes plus the complete manual verification queue are structured and displayed in audit and remediation reports. | The repository's production-shaped report imports three notes and all eight tasks. | Completion of the tasks remains human work. |
| Additional rules such as Language of Parts were silently omitted. | Fixed | Additional status rows are retained with generated `EXT-*` identifiers and flow into follow-up reporting. | Regression test imports `EXT-LANGUAGE-OF-PARTS`. | The cross-application contract should eventually define permanent shared identifiers. |
| Detailed remediation advice was not retained in final outcomes. | Fixed | Outcome details include source evidence and the original recommended follow-up. | Regression coverage and generated report inspection. | None. |
| Imported score and post-remediation score used different assessment bases. | Fixed | The application runs the local audit on both the source and output for the displayed before/after comparison; the input report score is separate. | Regression test verifies the score sources. | Checker and remediator scores remain distinct assessments. |
| Rules already passing locally were reported as successful repairs. | Fixed | A success requires the same local rule to change from non-passing before remediation to passing afterward. Checker disagreements become manual or unresolved. | Regression tests cover disagreement and same-basis outcomes. | A shared evidence-resolution policy is still needed. |
| Imported passes could conflict with local manual or failed results. | Fixed | The final outcome no longer treats an imported pass as verified when the local post-audit disagrees. | Outcome regression coverage. | Qualified review may still be required to resolve the disagreement. |
| Character encoding passed when extraction merely completed without an exception. | Fixed conservatively | Successful extraction now results in manual verification; extraction errors remain failures. | Regression tests verify manual disposition. | Font `/ToUnicode`, object-level, visual-text, and assistive-technology verification. |
| A numeric filename replaced a meaningful title or was used as the title. | Fixed | Existing meaningful titles are preserved and title display is enabled. Missing titles are not invented from filenames. | Tests cover title preservation and absence. | A content owner must author a missing meaningful title. |
| Baseline tagging produced only Document, P, and Figure elements and could artifact-wrap meaningful Form XObject content. | Removed | Automatic semantic structure inference was removed. The remediator does not claim to infer document semantics from PDF drawing operations. | Regression test verifies no invented structure tree. | A qualified PDF remediation tool or specialist must create semantic structure. |
| Empty structure trees and arbitrary marked content could receive tagging passes. | Fixed | Tagged-document validation requires structure elements, a parent tree, and mapped MCIDs for non-artifact content. | Regression test rejects an empty structure tree. | Full PDF/UA validation still requires specialized validation and review. |
| Legacy finding IDs did not match current post-audit IDs. | Fixed | Supported legacy IDs map to current Acrobat-aligned checks for outcome comparison. | Covered by outcome matching logic and the full test suite. | Long-term schema versioning remains desirable. |
| A report naming another PDF was accepted by the browser workflow. | Fixed | Browser and API paths compare the report filename with the uploaded PDF and reject mismatches. | API mismatch regression test and shared validator. | Stronger content identity could be added to a future handoff schema. |
| A payload slightly larger than 5 MiB was accepted because multipart overhead was included in the allowance. | Fixed | The decoded JSON payload itself is limited to exactly 5 MiB; multipart framing is handled separately. | Boundary regression test. | None. |
| Malformed report JSON returned HTTP 500. | Fixed | Invalid report content and filename mismatches return HTTP 400; unexpected processing failures remain HTTP 500. | Parser tests, compilation, and workflow-path inspection. | An HTTP integration test harness could strengthen coverage. |
| Unknown rule names were silently ignored. | Fixed | Additional valid status rows are retained instead of ignored. Unknown statuses and duplicate rows are still rejected. | Additional-rule regression test. | Shared rule identifiers remain an integration goal. |

## Intentionally unresolved findings

The following work cannot be completed reliably by this remediator alone:

- Establish complete coverage of every applicable WCAG 2.1 Level A and AA success criterion and conformance requirement.
- Document which WCAG 2.2 Level A and AA criteria are voluntary targets and how each is assessed.
- Establish the evidence required to resolve disagreements between the checker, remediator, Acrobat, PAC, veraPDF, and human review.
- Author semantic headings, tables, lists, links, figures, alternate text, reading order, and language changes.
- Run screen-reader, keyboard, reflow, text-spacing, contrast, and assistive-technology validation.
- Determine whether scripts, timing, flicker, annotations, and interactive behavior create accessibility barriers in a specific document.
- Rerun the upstream checker against the remediated output and distinguish original-document assessments from output-document assessments.
- Decide whether a source PDF should instead be provided as accessible HTML or recreated in an accessible source format.

## Cross-application contract recommendations

A future handoff schema should include:

1. A schema version and stable rule identifier for every finding.
2. Source filename plus a cryptographic source-document hash.
3. Assessment subject, distinguishing the original from a remediated output.
4. Assessment tool name and version.
5. Standard, criterion, level, and required-versus-voluntary classification.
6. Status, source severity, evidence confidence, and evidence method.
7. Complete page ranges and object references where available.
8. Remediation guidance and structured manual tasks.
9. Explicit fields for automated, inferred, and human-verified results.
10. A way to record disagreement and its resolution evidence.

## Verification evidence

The implementation was validated with:

```text
python -m unittest discover -v
python -m py_compile pdf_accessibility_audit.py pdf_accessibility_remediator.py pdf_accessibility_workflow.py function_app.py
git diff --check
```

Results:

- 19 tests passed.
- All changed Python modules compiled successfully.
- Diff hygiene checks passed.
- The repository's production-shaped external report imported 32 findings, three source-context notes, and eight manual verification tasks.
- End-to-end remediation completed against the repository fixture using temporary output.

## Traceability

- The changelog summarizes user-visible behavior under the Unreleased section.
- Regression tests provide executable acceptance criteria.
- The implementation pull request links the GitHub tracking issue for unresolved cross-application work.
- A release tag should be created only after review and merge so it identifies the reviewed implementation.
