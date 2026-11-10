# PDF Accessibility Checker and Remediator

Find accessibility issues in a PDF, apply supported automatic fixes, and download a checked copy with a before-and-after report.

The application helps you understand what improved and which issues remain. It is an accessibility screening and repair tool, not a certification of compliance.

## Try the app

**[Open the test app](https://app-ada-remediator-poc-33f3poc.azurewebsites.net)**

The hosted pilot uses **checker version 2.4.1**, verified on November 9, 2026. This is the application's version number, not a WCAG success criterion.

1. **Upload a PDF** using the file picker or drag and drop. The default limit is 20 MB.
2. **Review the accessibility report** to see detected issues and coverage limitations.
3. **Choose to apply supported fixes.** The app creates a separate copy rather than overwriting your original.
4. **Review the results and download the PDF.** The app checks the output again and reports verified changes and remaining issues.
5. Use **Home / New upload** to clear the active session and start another document.

## What it can do today

- Check document properties, navigation, forms, image descriptions, and aspects of headings, lists, tables, and PDF structure.
- Apply supported fixes to language settings, title display, form descriptions, and navigation settings when sufficient evidence already exists in the document.
- Repair an existing tagging declaration when the required supporting structure is already present; this does not create missing tags.
- Show before-and-after findings and a coverage summary for the 50 WCAG 2.1 Level A and AA success criteria.
- Identify remaining failures and areas that the current automated checks cannot fully assess.

Not every detected issue can be repaired automatically. If no supported fix is available, the downloaded copy remains unchanged.

## Understand the results

| Result | Meaning |
|--------|---------|
| Pass | The implemented automated checks passed. |
| Pass (partial coverage) | The implemented checks passed, but they do not fully assess the requirement. |
| Fail | An implemented check found an issue. |
| Not applicable | The relevant content or feature was not detected. |
| Out of scope | The app does not have a supported automated assessment for this area. |

**The accessibility score is not a compliance percentage.** A passing automated result does not establish that a PDF is fully accessible or conforms to WCAG, PDF/UA, Section 508, or ADA requirements.

The current release does not generate missing image descriptions, document titles, semantic tags, or searchable text for scanned pages. It also does not fully verify reading order, visual contrast, or assistive-technology usability. Qualified accessibility and assistive-technology review remains necessary for a complete evaluation.

## Privacy and file handling

The browser workflow processes uploads in temporary storage and active-session memory. Remediated copies remain on the server until session reset or expired-session cleanup. Inactive sessions are eligible for cleanup after one hour by default; cleanup runs on subsequent browser requests, not at a guaranteed deletion time.

Download your result before selecting **Home / New upload**, which clears the session and removes its app-managed output. The current release makes no AI model calls. Use only documents approved for upload to the shared test environment.

Local command-line tools and the alternative Azure Functions workflow have different storage behavior. See the [developer guide](docs/developer-guide.md) for details.

## What's next

LLM-assisted remediation is planned, starting with image descriptions generated from visual and document context. The goal is to address missing information that cannot be repaired using existing document evidence alone.

These capabilities are **not available in the current release**. Planned work includes validation of generated content, repeatable results through caching, and a record of how each AI-assisted change was produced.

## More information

- [Release notes](CHANGELOG.md) - customer-visible improvements by release.
- [Developer guide](docs/developer-guide.md) - local setup, command-line tools, API, technical coverage, deployment evidence, and testing.

This tool supports accessibility work; it does not provide legal advice or certify standards conformance.
