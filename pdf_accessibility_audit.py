from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject


@dataclass(frozen=True)
class Finding:
    check_id: str
    category: str
    requirement: str
    status: str
    severity: str
    details: str
    remediation: str
    pages: list[int] | None = None
    source_requirement: str = ""


@dataclass(frozen=True)
class AuditReport:
    file: str
    generated_at: str
    page_count: int
    score: int
    rating: str
    standard_basis: list[str]
    disclaimer: str
    summary: dict[str, int]
    findings: list[Finding]


WEIGHTS = {"critical": 10, "high": 7, "medium": 4, "low": 1}
SOURCE_DOCUMENT = "ADA Title II Web Accessibility.docx"
SOURCE_REQUIREMENTS = {
    "scope": "Scope and Applicability — PDF documents are in scope for public-entity web accessibility.",
    "pdfua": "Scope and Applicability table — PDF Documents: PDF/UA, Full conformance.",
    "alt": "Key Rules and Accessibility Targets — Provide text alternatives for any non-text content.",
    "keyboard": "Key Rules and Accessibility Targets — Content must be navigable via a keyboard interface.",
    "contrast": "Key Rules and Accessibility Targets — Color contrast ratio must be at least 4.5:1.",
}
DISCLAIMER = (
    "This automated screening does not certify ADA compliance and is not legal advice. "
    f"The screening policy is derived from {SOURCE_DOCUMENT}, which requires full PDF/UA "
    "conformance for PDF documents and identifies text alternatives, keyboard navigation, "
    "and a minimum 4.5:1 color-contrast ratio as accessibility targets. "
    "Items marked Manual review require testing by a qualified reviewer and assistive-technology users."
)


def _resolve(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _catalog(reader: PdfReader) -> DictionaryObject:
    root = _resolve(reader.trailer.get("/Root"))
    return root if isinstance(root, DictionaryObject) else DictionaryObject()


def _text(value: Any) -> str:
    value = _resolve(value)
    return str(value).strip() if value is not None else ""


def _walk_structure(value: Any, visited: set[tuple[int, int]] | None = None) -> Iterable[DictionaryObject]:
    """Yield structure dictionaries without following every PDF object graph edge."""
    visited = visited or set()
    if isinstance(value, IndirectObject):
        key = (value.idnum, value.generation)
        if key in visited:
            return
        visited.add(key)
        value = value.get_object()

    if isinstance(value, DictionaryObject):
        yield value
        child = value.get("/K")
        if child is not None:
            yield from _walk_structure(child, visited)
    elif isinstance(value, (ArrayObject, list, tuple)):
        for item in value:
            yield from _walk_structure(item, visited)


def _outline_count(reader: PdfReader) -> int:
    def count(items: Any) -> int:
        if not isinstance(items, list):
            return 0
        return sum(count(item) if isinstance(item, list) else 1 for item in items)

    try:
        return count(reader.outline)
    except Exception:
        return 0


def _page_image_count(page: Any) -> int:
    try:
        resources = _resolve(page.get("/Resources"))
        if not isinstance(resources, DictionaryObject):
            return 0
        xobjects = _resolve(resources.get("/XObject"))
        if not isinstance(xobjects, DictionaryObject):
            return 0
        return sum(
            1
            for obj in xobjects.values()
            if isinstance(_resolve(obj), DictionaryObject) and _resolve(obj).get("/Subtype") == "/Image"
        )
    except Exception:
        return 0


def _finding(
    check_id: str,
    category: str,
    requirement: str,
    status: str,
    severity: str,
    details: str,
    remediation: str,
    pages: list[int] | None = None,
    source_requirement: str = SOURCE_REQUIREMENTS["pdfua"],
) -> Finding:
    return Finding(check_id, category, requirement, status, severity, details, remediation, pages, source_requirement)


def audit_pdf(pdf_path: str | Path) -> AuditReport:
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Input must be a PDF file.")

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("The PDF is encrypted and cannot be audited without a password.") from exc

    root = _catalog(reader)
    page_count = len(reader.pages)
    findings: list[Finding] = []

    # Document-level semantics
    mark_info = _resolve(root.get("/MarkInfo"))
    marked = isinstance(mark_info, DictionaryObject) and bool(mark_info.get("/Marked"))
    findings.append(_finding(
        "DOC-001", "Document", "Tagged PDF", "pass" if marked else "fail", "critical",
        "The catalog identifies the document as tagged." if marked else "The catalog does not set /MarkInfo /Marked to true.",
        "Create a properly tagged PDF and verify the tag tree in an accessibility checker."
    ))

    struct_root = root.get("/StructTreeRoot")
    has_structure = struct_root is not None
    findings.append(_finding(
        "DOC-002", "Document", "Logical structure tree", "pass" if has_structure else "fail", "critical",
        "A structure tree is present." if has_structure else "No /StructTreeRoot was found.",
        "Add and validate semantic tags for headings, paragraphs, lists, tables, links, and figures."
    ))

    language = _text(root.get("/Lang"))
    findings.append(_finding(
        "DOC-003", "Document", "Default document language", "pass" if language else "fail", "high",
        f"Document language is {language}." if language else "No default document language is declared.",
        "Set the document language (for example, en-US) and identify language changes in the content."
    ))

    metadata = reader.metadata
    title = _text(getattr(metadata, "title", None) if metadata else None)
    findings.append(_finding(
        "DOC-004", "Document", "Meaningful document title", "pass" if title else "fail", "medium",
        f"Metadata title: {title}" if title else "The document metadata has no title.",
        "Add a concise, meaningful title in the PDF document properties."
    ))

    viewer_prefs = _resolve(root.get("/ViewerPreferences"))
    display_title = isinstance(viewer_prefs, DictionaryObject) and bool(viewer_prefs.get("/DisplayDocTitle"))
    findings.append(_finding(
        "DOC-005", "Document", "Display document title", "pass" if display_title else "warning", "low",
        "Viewer preference DisplayDocTitle is enabled." if display_title else "DisplayDocTitle is not enabled.",
        "Configure the initial view to display the document title rather than the file name."
    ))

    outline_count = _outline_count(reader)
    outline_status = "not_applicable" if page_count < 10 else ("pass" if outline_count else "warning")
    findings.append(_finding(
        "NAV-001", "Navigation", "Bookmarks for long documents", outline_status, "medium",
        f"Found {outline_count} bookmark(s)." if outline_count else (
            "Fewer than 10 pages; bookmarks are not required by this screening rule."
            if page_count < 10 else "No bookmarks were found in this long document."
        ),
        "Add hierarchical bookmarks that reflect the document's major sections."
    ))

    # Extractability and likely scanned pages
    no_text_pages: list[int] = []
    scanned_pages: list[int] = []
    extraction_errors: list[int] = []
    image_count = 0
    for page_number, page in enumerate(reader.pages, start=1):
        page_images = _page_image_count(page)
        image_count += page_images
        try:
            extracted = (page.extract_text() or "").strip()
        except Exception:
            extracted = ""
            extraction_errors.append(page_number)
        if not extracted:
            no_text_pages.append(page_number)
            if page_images > 0:
                scanned_pages.append(page_number)

    if extraction_errors:
        extract_status = "fail"
        extract_details = f"Text extraction failed on {len(extraction_errors)} page(s)."
    elif no_text_pages:
        extract_status = "warning"
        extract_details = f"No extractable text was found on {len(no_text_pages)} page(s)."
    else:
        extract_status = "pass"
        extract_details = "Extractable text was found on every page."
    findings.append(_finding(
        "CONT-001", "Content", "Text is extractable", extract_status, "high", extract_details,
        "Ensure meaningful content is real text, uses embedded Unicode fonts, and is included in the tag tree.",
        extraction_errors or no_text_pages or None,
    ))
    findings.append(_finding(
        "CONT-002", "Content", "Scanned pages have OCR", "warning" if scanned_pages else "pass", "high",
        f"{len(scanned_pages)} image-only page(s) may require OCR." if scanned_pages else "No image-only pages were detected.",
        "Run OCR, correct recognition errors, and add a verified semantic tag structure.",
        scanned_pages or None,
    ))

    # Figure alternatives in the structure tree
    figures = 0
    figures_without_alt = 0
    if has_structure:
        for element in _walk_structure(struct_root):
            if _text(element.get("/S")).lstrip("/") == "Figure":
                figures += 1
                if not (_text(element.get("/Alt")) or _text(element.get("/ActualText"))):
                    figures_without_alt += 1
    if figures_without_alt:
        figure_status = "fail"
        figure_details = f"Found {figures} tagged figure(s); {figures_without_alt} lack /Alt or /ActualText."
    elif figures:
        figure_status = "pass"
        figure_details = f"Found {figures} tagged figure(s), each with /Alt or /ActualText."
    elif image_count:
        figure_status = "warning"
        figure_details = f"Found {image_count} image object(s), but no tagged Figure elements; text alternatives cannot be verified."
    else:
        figure_status = "not_applicable"
        figure_details = "No image objects or tagged Figure elements were found."
    findings.append(_finding(
        "IMG-001", "Images", "Tagged figures have alternate text", figure_status, "high",
        figure_details,
        "Add concise equivalent text to informative figures and mark decorative images as artifacts.",
        source_requirement=SOURCE_REQUIREMENTS["alt"],
    ))

    # Interactive form descriptions
    try:
        fields = reader.get_fields() or {}
    except Exception:
        fields = {}
    missing_descriptions = [
        str(name) for name, field in fields.items()
        if isinstance(field, dict) and not (_text(field.get("/TU")) or _text(field.get("/T")))
    ]
    form_status = "not_applicable" if not fields else ("pass" if not missing_descriptions else "fail")
    findings.append(_finding(
        "FORM-001", "Forms", "Form controls have accessible names", form_status, "high",
        f"Found {len(fields)} field(s); {len(missing_descriptions)} lack a tooltip or field name." if fields else "No AcroForm fields were found.",
        "Give every form control a unique, descriptive tooltip/name and verify keyboard order and error handling.",
        source_requirement=SOURCE_REQUIREMENTS["keyboard"],
    ))

    # Essential checks that require human judgment
    manual_checks = [
        ("MAN-001", "Structure", "Tag accuracy and reading order", "critical", "Verify tags match the visual content and reading order is logical.", SOURCE_REQUIREMENTS["pdfua"]),
        ("MAN-002", "Structure", "Heading hierarchy", "high", "Verify headings are descriptive and levels do not skip illogically.", SOURCE_REQUIREMENTS["pdfua"]),
        ("MAN-003", "Tables", "Table headers and associations", "high", "Verify data tables use TH/TD tags, scope or header associations, and regular structures.", SOURCE_REQUIREMENTS["pdfua"]),
        ("MAN-004", "Visual", "Minimum 4.5:1 color contrast", "high", "Measure text contrast and confirm a ratio of at least 4.5:1.", SOURCE_REQUIREMENTS["contrast"]),
        ("MAN-005", "Links", "Descriptive link purpose", "medium", "Verify each link communicates its purpose in context and is correctly tagged.", SOURCE_REQUIREMENTS["pdfua"]),
        ("MAN-006", "Content", "Meaningful text alternatives", "high", "Judge whether text alternatives convey the purpose of every item of non-text content.", SOURCE_REQUIREMENTS["alt"]),
        ("MAN-007", "Forms", "Keyboard navigation and operation", "high", "Test tab order and confirm that all form controls can be reached and operated with a keyboard.", SOURCE_REQUIREMENTS["keyboard"]),
        ("MAN-008", "Assistive technology", "Keyboard and screen-reader usability", "critical", "Test keyboard-only interaction and representative screen readers such as NVDA, JAWS, or VoiceOver.", SOURCE_REQUIREMENTS["keyboard"]),
    ]
    findings.extend(
        _finding(check_id, category, requirement, "manual", severity, "Automated inspection cannot determine this requirement.", remediation, source_requirement=source)
        for check_id, category, requirement, severity, remediation, source in manual_checks
    )

    score = _calculate_score(findings)
    rating = "Good automated result" if score >= 90 else "Needs review" if score >= 70 else "Significant barriers detected"
    summary = {status: sum(item.status == status for item in findings) for status in ("pass", "fail", "warning", "manual", "not_applicable")}
    return AuditReport(
        file=str(path),
        generated_at=datetime.now(timezone.utc).isoformat(),
        page_count=page_count,
        score=score,
        rating=rating,
        standard_basis=[
            f"Controlling local requirements: {SOURCE_DOCUMENT}",
            SOURCE_REQUIREMENTS["pdfua"],
            SOURCE_REQUIREMENTS["alt"],
            SOURCE_REQUIREMENTS["keyboard"],
            SOURCE_REQUIREMENTS["contrast"],
            "The source document references WCAG 2.1 Level AA and Section 508 in its title and executive summary.",
        ],
        disclaimer=DISCLAIMER,
        summary=summary,
        findings=findings,
    )


def _calculate_score(findings: list[Finding]) -> int:
    automated = [item for item in findings if item.status not in {"manual", "not_applicable"}]
    possible = sum(WEIGHTS[item.severity] for item in automated)
    earned = sum(
        WEIGHTS[item.severity] * ({"pass": 1.0, "warning": 0.5, "fail": 0.0}[item.status])
        for item in automated
    )
    return round(100 * earned / possible) if possible else 0


def write_json(report: AuditReport, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_json(input_path: str | Path) -> AuditReport:
    """Load and validate an audit report produced by :func:`write_json`."""
    path = Path(input_path).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        findings = [Finding(**item) for item in data.pop("findings")]
        return AuditReport(findings=findings, **data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Invalid audit JSON report: {path}") from exc


def write_html(report: AuditReport, output_path: str | Path, remediation_url: str | None = None, csrf_token: str = "") -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    e = html.escape
    labels = {"pass": "Pass", "fail": "Fail", "warning": "Warning", "manual": "Manual review", "not_applicable": "N/A"}
    rows = []
    for item in report.findings:
        pages = f" Pages: {', '.join(map(str, item.pages))}." if item.pages else ""
        rows.append(f"""
        <article class="finding {e(item.status)}" aria-labelledby="{e(item.check_id)}-title">
          <div class="finding-head"><span class="badge">{e(labels[item.status])}</span><span class="severity">{e(item.severity.title())}</span><span class="check-id">{e(item.check_id)}</span></div>
          <h3 id="{e(item.check_id)}-title">{e(item.requirement)}</h3>
          <p><strong>Source requirement:</strong> {e(item.source_requirement)}</p>
          <p><strong>Result:</strong> {e(item.details + pages)}</p>
          <p><strong>Recommended action:</strong> {e(item.remediation)}</p>
        </article>""")

        remediation_panel = ""
        if remediation_url:
                remediation_panel = f"""
<section class="panel action" aria-labelledby="remediate-heading">
    <h2 id="remediate-heading">Apply automatic remediation?</h2>
    <p>A new PDF will be created; the source file will not be changed. Safe metadata and viewer fixes will be applied. A fully image-only document can also receive a minimal Document and Figure structure so its existing page content is tagged. OCR, alternate-text meaning, detailed semantic tagging, reading order, tables, and visual contrast require additional remediation or human review.</p>
    <form method="post" action="{html.escape(remediation_url, quote=True)}" onsubmit="return confirm('Create a remediated copy now? The original will not be overwritten.');">
        <input type="hidden" name="token" value="{html.escape(csrf_token, quote=True)}">
        <button type="submit">Yes, apply remediation</button>
    </form>
</section>"""

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF Accessibility Screening Report</title>
<style>
:root{{--ink:#172033;--muted:#596579;--paper:#fff;--canvas:#f3f6fa;--blue:#1456a0;--pass:#176b45;--fail:#a12622;--warn:#8a5700;--manual:#5f3b91;--border:#d7dee8}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{width:min(1100px,calc(100% - 2rem));margin:2rem auto 4rem}} header,.panel,.finding{{background:var(--paper);border:1px solid var(--border);border-radius:12px;box-shadow:0 3px 14px #1720330d}}
header{{padding:2rem;border-top:6px solid var(--blue)}} h1{{font-size:clamp(1.8rem,4vw,2.7rem);line-height:1.15;margin:.2rem 0}} h2{{margin-top:2.2rem}} h3{{margin:.6rem 0 .3rem;font-size:1.15rem}}
.eyebrow,.check-id{{color:var(--muted);font-weight:700;letter-spacing:.06em;text-transform:uppercase;font-size:.78rem}} .file{{overflow-wrap:anywhere;color:var(--muted)}}
.score-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1rem;margin:1.2rem 0}} .metric{{padding:1rem;background:#f8fafc;border:1px solid var(--border);border-radius:10px}} .metric strong{{display:block;font-size:1.75rem}} .metric span{{color:var(--muted)}}
.panel{{padding:1.2rem 1.4rem;margin:1.2rem 0}} .notice{{border-left:5px solid var(--warn)}} .finding{{padding:1.1rem 1.3rem;margin:.8rem 0;border-left:6px solid var(--border)}}
.finding.pass{{border-left-color:var(--pass)}} .finding.fail{{border-left-color:var(--fail)}} .finding.warning{{border-left-color:var(--warn)}} .finding.manual{{border-left-color:var(--manual)}}
.finding-head{{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}} .badge,.severity{{display:inline-block;border-radius:999px;padding:.17rem .62rem;font-size:.78rem;font-weight:800}} .badge{{background:#e8edf4}} .pass .badge{{background:#d9f3e7;color:#0f5a39}} .fail .badge{{background:#fde3e1;color:#841d19}} .warning .badge{{background:#fff0cb;color:#724700}} .manual .badge{{background:#eee4fa;color:#503078}} .severity{{border:1px solid var(--border)}}
p{{margin:.38rem 0}} a{{color:var(--blue)}} button{{margin-top:1rem;padding:.75rem 1.15rem;border:0;border-radius:8px;background:var(--blue);color:#fff;font:inherit;font-weight:750;cursor:pointer}} button:hover{{background:#0d417d}} button:focus-visible{{outline:3px solid #f5b942;outline-offset:3px}} .action{{border-left:5px solid var(--blue)}} footer{{color:var(--muted);margin-top:2rem}} @media print{{body{{background:#fff}}main{{width:100%;margin:0}}header,.panel,.finding{{box-shadow:none;break-inside:avoid}}.action{{display:none}}}}
</style>
</head>
<body><main>
<header><div class="eyebrow">Automated accessibility screening</div><h1>PDF Accessibility Report</h1><p class="file">{e(report.file)}</p>
<div class="score-grid">
<div class="metric"><strong>{report.score}/100</strong><span>Automated score</span></div><div class="metric"><strong>{report.page_count}</strong><span>Pages</span></div>
<div class="metric"><strong>{report.summary['fail']}</strong><span>Failures</span></div><div class="metric"><strong>{report.summary['warning']}</strong><span>Warnings</span></div><div class="metric"><strong>{report.summary['manual']}</strong><span>Manual checks</span></div>
</div><p><strong>{e(report.rating)}</strong></p></header>
<section class="panel notice" aria-labelledby="limitations"><h2 id="limitations">Scope and limitations</h2><p>{e(report.disclaimer)}</p></section>
<section class="panel" aria-labelledby="basis"><h2 id="basis">Evaluation basis</h2><ul>{''.join(f'<li>{e(item)}</li>' for item in report.standard_basis)}</ul><p>Generated {e(report.generated_at)}</p></section>
{remediation_panel}
<section aria-labelledby="findings"><h2 id="findings">Detailed findings</h2>{''.join(rows)}</section>
<footer><p>Prioritize failed critical and high-severity findings, then complete every manual review with assistive technology.</p></footer>
</main></body></html>"""
    path.write_text(html_doc, encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen a PDF for common accessibility barriers.")
    parser.add_argument("pdf", help="Path to the PDF to evaluate")
    parser.add_argument("--output", "-o", default="accessibility-report.html", help="HTML report path")
    parser.add_argument("--json", dest="json_output", help="JSON report path; defaults to accessibility-report-<file_name>.json")
    parser.add_argument("--no-open", action="store_true", help="Do not open the HTML report in a browser")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        report = audit_pdf(args.pdf)
        html_path = write_html(report, args.output)
        source = Path(args.pdf).expanduser().resolve()
        json_output = args.json_output or f"accessibility-report-{source.stem}.json"
        json_path = write_json(report, json_output)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unable to audit PDF: {exc}", file=sys.stderr)
        return 1

    print(f"Accessibility score: {report.score}/100 — {report.rating}")
    print(f"Failures: {report.summary['fail']}; warnings: {report.summary['warning']}; manual reviews: {report.summary['manual']}")
    print(f"HTML report: {html_path}")
    print(f"JSON report: {json_path}")
    if not args.no_open:
        webbrowser.open(html_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
