from __future__ import annotations

import argparse
import html
import json
import re
import sys
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject


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
ACROBAT_RULE_IDS = (
    "ACR-DOC-001", "ACR-DOC-002", "ACR-DOC-003", "ACR-DOC-004",
    "ACR-DOC-005", "ACR-DOC-006", "ACR-DOC-007", "ACR-DOC-008",
    "ACR-PAGE-001", "ACR-PAGE-002", "ACR-PAGE-003", "ACR-PAGE-004",
    "ACR-PAGE-005", "ACR-PAGE-006", "ACR-PAGE-007", "ACR-PAGE-008",
    "ACR-PAGE-009", "ACR-FORM-001", "ACR-FORM-002", "ACR-ALT-001",
    "ACR-ALT-002", "ACR-ALT-003", "ACR-ALT-004", "ACR-ALT-005",
    "ACR-TABLE-001", "ACR-TABLE-002", "ACR-TABLE-003", "ACR-TABLE-004",
    "ACR-TABLE-005", "ACR-LIST-001", "ACR-LIST-002", "ACR-HEAD-001",
)
EXTERNAL_RULE_SPECS = (
    ("ACR-DOC-001", "Document", "Accessibility permission flag", "high"),
    ("ACR-DOC-002", "Document", "Image-only PDF", "critical"),
    ("ACR-DOC-003", "Document", "Tagged PDF", "critical"),
    ("ACR-DOC-004", "Document", "Logical Reading Order", "critical"),
    ("ACR-DOC-005", "Document", "Primary language", "high"),
    ("ACR-DOC-006", "Document", "Title", "medium"),
    ("ACR-DOC-007", "Document", "Bookmarks", "medium"),
    ("ACR-DOC-008", "Document", "Color contrast", "high"),
    ("ACR-PAGE-001", "Page Content", "Tagged content", "critical"),
    ("ACR-PAGE-002", "Page Content", "Tagged annotations", "high"),
    ("ACR-PAGE-003", "Page Content", "Tab order", "high"),
    ("ACR-PAGE-004", "Page Content", "Character encoding", "high"),
    ("ACR-PAGE-005", "Page Content", "Tagged multimedia", "medium"),
    ("ACR-PAGE-006", "Page Content", "Screen flicker", "high"),
    ("ACR-PAGE-007", "Page Content", "Scripts", "high"),
    ("ACR-PAGE-008", "Page Content", "Timed responses", "high"),
    ("ACR-PAGE-009", "Page Content", "Navigation links", "medium"),
    ("ACR-FORM-001", "Forms", "Tagged form fields", "high"),
    ("ACR-FORM-002", "Forms", "Field descriptions", "high"),
    ("ACR-ALT-001", "Alternate Text", "Figures alternate text", "high"),
    ("ACR-ALT-002", "Alternate Text", "Nested alternate text", "medium"),
    ("ACR-ALT-003", "Alternate Text", "Associated with content", "high"),
    ("ACR-ALT-004", "Alternate Text", "Hides annotation", "high"),
    ("ACR-ALT-005", "Alternate Text", "Other elements alternate text", "high"),
    ("ACR-TABLE-001", "Tables", "Rows", "high"),
    ("ACR-TABLE-002", "Tables", "TH and TD", "high"),
    ("ACR-TABLE-003", "Tables", "Headers", "high"),
    ("ACR-TABLE-004", "Tables", "Regularity", "high"),
    ("ACR-TABLE-005", "Tables", "Summary", "low"),
    ("ACR-LIST-001", "Lists", "List items", "high"),
    ("ACR-LIST-002", "Lists", "Lbl and LBody", "high"),
    ("ACR-HEAD-001", "Headings", "Appropriate nesting", "high"),
)
AUDIT_REPORTS_DIR = Path("reports") / "audits"
REMEDIATION_REPORTS_DIR = Path("reports") / "remediated"
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


def _structure_nodes(value: Any) -> list[tuple[DictionaryObject, str]]:
    nodes: list[tuple[DictionaryObject, str]] = []
    visited: set[tuple[int, int]] = set()

    def walk(item: Any, parent_role: str = "") -> None:
        if isinstance(item, IndirectObject):
            key = (item.idnum, item.generation)
            if key in visited:
                return
            visited.add(key)
            item = item.get_object()
        if isinstance(item, DictionaryObject):
            role = _text(item.get("/S")).lstrip("/")
            if role:
                nodes.append((item, parent_role))
                parent_role = role
            child = item.get("/K")
            if child is not None:
                walk(child, parent_role)
        elif isinstance(item, (ArrayObject, list, tuple)):
            for child in item:
                walk(child, parent_role)

    walk(value)
    return nodes


def _annotations(reader: PdfReader) -> list[DictionaryObject]:
    result: list[DictionaryObject] = []
    for page in reader.pages:
        values = _resolve(page.get("/Annots"))
        if isinstance(values, (ArrayObject, list, tuple)):
            result.extend(value for item in values if isinstance((value := _resolve(item)), DictionaryObject))
    return result


def _has_javascript(root: DictionaryObject, reader: PdfReader) -> bool:
    names = _resolve(root.get("/Names"))
    if isinstance(names, DictionaryObject) and names.get("/JavaScript") is not None:
        return True
    if root.get("/OpenAction") is not None or root.get("/AA") is not None:
        return True
    return any(page.get("/AA") is not None for page in reader.pages)


def _page_content_is_tagged(page: Any, reader: PdfReader) -> bool:
    try:
        operations = ContentStream(page.get_contents(), reader).operations
    except Exception:
        return False
    marked_depth = 0
    content_operators = {b"Tj", b"TJ", b"'", b'"', b"Do", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"sh", b"INLINE IMAGE"}
    for _, operator in operations:
        if operator in {b"BMC", b"BDC"}:
            marked_depth += 1
        elif operator == b"EMC":
            marked_depth = max(0, marked_depth - 1)
        elif operator in content_operators and marked_depth == 0:
            return False
    return True


def _contains_object_reference(value: Any) -> bool:
    value = _resolve(value)
    if isinstance(value, DictionaryObject):
        if value.get("/Type") == "/OBJR":
            return True
        return _contains_object_reference(value.get("/K")) if value.get("/K") is not None else False
    if isinstance(value, (ArrayObject, list, tuple)):
        return any(_contains_object_reference(item) for item in value)
    return False


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
    was_encrypted = reader.is_encrypted
    if was_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("The PDF is encrypted and cannot be audited without a password.") from exc

    root = _catalog(reader)
    page_count = len(reader.pages)
    findings: list[Finding] = []
    mark_info = _resolve(root.get("/MarkInfo"))
    marked = isinstance(mark_info, DictionaryObject) and bool(mark_info.get("/Marked"))
    struct_root = root.get("/StructTreeRoot")
    has_structure = struct_root is not None
    language = _text(root.get("/Lang"))
    metadata = reader.metadata
    title = _text(getattr(metadata, "title", None) if metadata else None)
    viewer_prefs = _resolve(root.get("/ViewerPreferences"))
    display_title = isinstance(viewer_prefs, DictionaryObject) and bool(viewer_prefs.get("/DisplayDocTitle"))
    outline_count = _outline_count(reader)
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
    nodes = _structure_nodes(struct_root) if has_structure else []
    roles = [(_text(element.get("/S")).lstrip("/"), element, parent) for element, parent in nodes]
    figures = [element for role, element, _ in roles if role == "Figure"]
    figures_without_alt = [element for element in figures if not (_text(element.get("/Alt")) or _text(element.get("/ActualText")))]
    annotations = _annotations(reader)
    links = [item for item in annotations if item.get("/Subtype") == "/Link"]
    media = [item for item in annotations if item.get("/Subtype") in {"/Movie", "/Sound", "/RichMedia", "/Screen"}]
    widgets = [item for item in annotations if item.get("/Subtype") == "/Widget"]
    has_scripts = _has_javascript(root, reader)
    try:
        fields = reader.get_fields() or {}
    except Exception:
        fields = {}
    missing_descriptions = [
        str(name) for name, field in fields.items()
        if isinstance(field, dict) and not (_text(field.get("/TU")) or _text(field.get("/T")))
    ]
    image_only = bool(page_count) and len(scanned_pages) == page_count
    fully_tagged = marked and has_structure
    tagged_pages = [number for number, page in enumerate(reader.pages, 1) if _page_content_is_tagged(page, reader)] if fully_tagged else []
    tabs_pages = [number for number, page in enumerate(reader.pages, 1) if page.get("/Tabs") == "/S"]
    tagged_annotations = [item for item in annotations if item.get("/StructParent") is not None]
    permissions = reader.user_access_permissions
    accessibility_allowed = not was_encrypted or (
        permissions is not None and bool(permissions & UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS)
    )

    def add(check_id: str, category: str, name: str, status: str, severity: str, details: str, remediation: str, pages: list[int] | None = None, source: str = SOURCE_REQUIREMENTS["pdfua"]) -> None:
        findings.append(_finding(check_id, category, name, status, severity, details, remediation, pages, source))

    add("ACR-DOC-001", "Document", "Accessibility permission flag", "pass" if accessibility_allowed else "fail", "high", "The document permits assistive-technology text and graphics extraction." if accessibility_allowed else "The encrypted document does not grant assistive-technology extraction permission.", "Remove security restrictions that prevent assistive-technology access.")
    add("ACR-DOC-002", "Document", "Image-only PDF", "fail" if image_only else "pass", "critical", f"All {page_count} page(s) are image-only." if image_only else "The document is not entirely image-only.", "Run OCR and verify the recognized text and reading order.", scanned_pages or None)
    add("ACR-DOC-003", "Document", "Tagged PDF", "pass" if fully_tagged else "fail", "critical", "The catalog identifies a tagged document with a structure tree." if fully_tagged else "The document lacks a complete tagged-document declaration and structure tree.", "Create and validate a semantic structure tree.")
    add("ACR-DOC-004", "Document", "Logical Reading Order", "manual", "critical", "Reading-order quality requires human and assistive-technology review.", "Verify the tag order against the intended visual and spoken order.")
    add("ACR-DOC-005", "Document", "Primary language", "pass" if language else "fail", "high", f"Document language is {language}." if language else "No default document language is declared.", "Set the document language and identify language changes.")
    add("ACR-DOC-006", "Document", "Title", "pass" if title and display_title else "fail", "medium", f"Metadata title is '{title}' and title display is enabled." if title and display_title else "A metadata title and title-bar display preference are both required.", "Add a meaningful title and display it in the title bar.")
    add("ACR-DOC-007", "Document", "Bookmarks", "not_applicable" if page_count < 10 else ("pass" if outline_count else "fail"), "medium", f"Found {outline_count} bookmark(s)." if outline_count else ("Fewer than 10 pages; this rule does not apply." if page_count < 10 else "No bookmarks were found in this long document."), "Add hierarchical bookmarks for major sections.")
    add("ACR-DOC-008", "Document", "Color contrast", "manual", "high", "Static PDF inspection cannot reliably establish visual contrast for all content.", "Measure foreground/background contrast and correct failures.", source=SOURCE_REQUIREMENTS["contrast"])

    add("ACR-PAGE-001", "Page Content", "Tagged content", "pass" if len(tagged_pages) == page_count and page_count else "fail", "critical", f"All {page_count} page(s) have marked content." if len(tagged_pages) == page_count and page_count else f"Marked-content coverage was verified on {len(tagged_pages)} of {page_count} page(s).", "Associate meaningful page content with structure elements and mark layout content as artifacts.")
    add("ACR-PAGE-002", "Page Content", "Tagged annotations", "pass" if len(tagged_annotations) == len(annotations) else "fail", "high", f"{len(tagged_annotations)} of {len(annotations)} annotation(s) are structure-associated." if annotations else "No annotations require tagging.", "Associate each meaningful annotation with the structure tree.")
    add("ACR-PAGE-003", "Page Content", "Tab order", "pass" if len(tabs_pages) == page_count and page_count else "fail", "high", f"All {page_count} page(s) use structure order." if len(tabs_pages) == page_count and page_count else f"Structure-based tab order is set on {len(tabs_pages)} of {page_count} page(s).", "Set page tab order to use the document structure.")
    add("ACR-PAGE-004", "Page Content", "Character encoding", "fail" if extraction_errors else "pass", "high", "Text extraction completed without errors." if not extraction_errors else f"Text extraction failed on {len(extraction_errors)} page(s).", "Use embedded Unicode-compatible fonts and valid character mappings.", extraction_errors or None)
    add("ACR-PAGE-005", "Page Content", "Tagged multimedia", "pass" if not media or all(item.get("/StructParent") is not None for item in media) else "fail", "medium", f"Found {len(media)} multimedia annotation(s)." if media else "No multimedia objects require tagging.", "Tag multimedia and provide accessible alternatives.")
    add("ACR-PAGE-006", "Page Content", "Screen flicker", "manual" if media or has_scripts else "pass", "high", "Dynamic content requires manual flicker testing." if media or has_scripts else "No dynamic multimedia or scripts were detected.", "Verify that dynamic content does not flash above accessibility thresholds.")
    add("ACR-PAGE-007", "Page Content", "Scripts", "manual" if has_scripts else "pass", "high", "Scripts are present and require keyboard and assistive-technology testing." if has_scripts else "No document-level or page-level scripts were detected.", "Remove inaccessible scripts or provide an accessible equivalent.")
    add("ACR-PAGE-008", "Page Content", "Timed responses", "manual" if has_scripts else "pass", "high", "Scripts may impose timing and require manual testing." if has_scripts else "No scripts capable of imposing timed responses were detected.", "Allow users to extend, disable, or avoid time limits.")
    add("ACR-PAGE-009", "Page Content", "Navigation links", "manual" if links else "pass", "medium", f"Found {len(links)} link annotation(s); repetition and purpose require review." if links else "No link annotations require repetition review.", "Verify link purpose and remove unnecessarily repetitive navigation.")

    add("ACR-FORM-001", "Forms", "Tagged form fields", "pass" if not widgets or all(item.get("/StructParent") is not None for item in widgets) else "fail", "high", f"Found {len(widgets)} form widget(s)." if widgets else "No form widgets require tagging.", "Associate each form widget with a Form structure element.", source=SOURCE_REQUIREMENTS["keyboard"])
    add("ACR-FORM-002", "Forms", "Field descriptions", "pass" if not missing_descriptions else "fail", "high", f"Found {len(fields)} field(s); {len(missing_descriptions)} lack a tooltip or field name." if fields else "No form fields require descriptions.", "Give every form control a unique descriptive tooltip or name.", source=SOURCE_REQUIREMENTS["keyboard"])

    alt_elements = [element for _, element, _ in roles if _text(element.get("/Alt")) or _text(element.get("/ActualText"))]
    nested_alt = [element for element in alt_elements if any(_text(child.get("/Alt")) or _text(child.get("/ActualText")) for child in _walk_structure(element.get("/K")))]
    alt_without_content = [element for element in alt_elements if element.get("/K") is None]
    alt_hiding_annotation = [element for element in alt_elements if _contains_object_reference(element.get("/K"))]
    other_alt_missing = [element for role, element, _ in roles if role in {"Formula", "Form"} and not (_text(element.get("/Alt")) or _text(element.get("/ActualText")))]
    add("ACR-ALT-001", "Alternate Text", "Figures alternate text", "not_applicable" if not figures and not image_count else ("pass" if figures and not figures_without_alt else "fail"), "high", f"Found {len(figures)} tagged figure(s); {len(figures_without_alt)} lack alternate text." if figures else f"Found {image_count} image object(s) without verifiable Figure tags.", "Add concise equivalent text to informative figures and artifact decorative images.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-002", "Alternate Text", "Nested alternate text", "fail" if nested_alt else "pass", "medium", f"Found {len(nested_alt)} element(s) with nested alternate text." if nested_alt else "No nested alternate-text conflicts were detected.", "Keep alternate text on the appropriate outermost semantic element.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-003", "Alternate Text", "Associated with content", "fail" if alt_without_content else "pass", "high", f"Found {len(alt_without_content)} alternate-text element(s) without associated content." if alt_without_content else "Every detected alternate-text entry is associated with content.", "Associate alternate text with actual marked content.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-004", "Alternate Text", "Hides annotation", "fail" if alt_hiding_annotation else "pass", "high", f"Found {len(alt_hiding_annotation)} alternate-text element(s) containing annotation references." if alt_hiding_annotation else "No alternate text was found hiding annotation references.", "Move annotation objects outside alternate-text containers.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-005", "Alternate Text", "Other elements alternate text", "fail" if other_alt_missing else "pass", "high", f"Found {len(other_alt_missing)} non-Figure element(s) missing alternate text." if other_alt_missing else "No other tagged elements were found missing required alternate text.", "Add equivalent text to formulas and other non-text semantic elements.", source=SOURCE_REQUIREMENTS["alt"])

    table_roles = [(role, element, parent) for role, element, parent in roles if role in {"Table", "THead", "TBody", "TFoot", "TR", "TH", "TD"}]
    tables = [element for role, element, _ in table_roles if role == "Table"]
    invalid_rows = [element for role, element, parent in table_roles if role == "TR" and parent not in {"Table", "THead", "TBody", "TFoot"}]
    invalid_cells = [element for role, element, parent in table_roles if role in {"TH", "TD"} and parent != "TR"]
    header_count = sum(role == "TH" for role, _, _ in table_roles)
    add("ACR-TABLE-001", "Tables", "Rows", "not_applicable" if not tables else ("fail" if invalid_rows else "pass"), "high", f"Found {len(tables)} table(s) and {len(invalid_rows)} invalid row parent(s)." if tables else "No tagged tables were detected.", "Place each TR under Table, THead, TBody, or TFoot.")
    add("ACR-TABLE-002", "Tables", "TH and TD", "not_applicable" if not tables else ("fail" if invalid_cells else "pass"), "high", f"Found {len(invalid_cells)} cell(s) outside TR elements." if tables else "No tagged tables were detected.", "Place each TH and TD directly under a TR.")
    add("ACR-TABLE-003", "Tables", "Headers", "not_applicable" if not tables else ("pass" if header_count else "fail"), "high", f"Found {header_count} table header cell(s)." if tables else "No tagged tables were detected.", "Add TH cells and valid header associations.")
    add("ACR-TABLE-004", "Tables", "Regularity", "not_applicable" if not tables else "manual", "high", "No tagged tables were detected." if not tables else "Spans and row/column regularity require semantic table analysis.", "Verify consistent rows, columns, spans, and header associations.")
    add("ACR-TABLE-005", "Tables", "Summary", "not_applicable" if not tables else "skipped", "low", "No tagged tables were detected." if not tables else "Table-summary quality is not automatically evaluated.", "Add a summary when needed to explain a complex table.")

    lists = [element for role, element, _ in roles if role == "L"]
    invalid_items = [element for role, element, parent in roles if role == "LI" and parent != "L"]
    invalid_list_parts = [element for role, element, parent in roles if role in {"Lbl", "LBody"} and parent != "LI"]
    add("ACR-LIST-001", "Lists", "List items", "not_applicable" if not lists else ("fail" if invalid_items else "pass"), "high", f"Found {len(lists)} list(s) and {len(invalid_items)} invalid LI parent(s)." if lists else "No tagged lists were detected.", "Place each LI directly under an L element.")
    add("ACR-LIST-002", "Lists", "Lbl and LBody", "not_applicable" if not lists else ("fail" if invalid_list_parts else "pass"), "high", f"Found {len(invalid_list_parts)} Lbl/LBody element(s) outside LI." if lists else "No tagged lists were detected.", "Place Lbl and LBody elements directly under LI.")

    heading_levels = [int(role[1:]) for role, _, _ in roles if len(role) == 2 and role.startswith("H") and role[1].isdigit()]
    heading_skip = any(current > previous + 1 for previous, current in zip(heading_levels, heading_levels[1:]))
    add("ACR-HEAD-001", "Headings", "Appropriate nesting", "not_applicable" if not heading_levels else ("fail" if heading_skip else "pass"), "high", f"Heading sequence: {', '.join(f'H{level}' for level in heading_levels)}." if heading_levels else "No tagged headings were detected.", "Use descriptive headings with levels that do not skip illogically.")

    score = _calculate_score(findings)
    rating = "Good automated result" if score >= 90 else "Needs review" if score >= 70 else "Significant barriers detected"
    summary = {status: sum(item.status == status for item in findings) for status in ("pass", "fail", "warning", "manual", "skipped", "not_applicable")}
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
    automated = [item for item in findings if item.status not in {"manual", "skipped", "not_applicable"}]
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


def _external_rule_key(value: str) -> str:
    value = re.sub(r"\s*[\[(].*$", "", value).strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _markdown_rows(markdown: str) -> list[list[str]]:
    rows = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            rows.append(cells)
    return rows


def _source_requirement_for(check_id: str) -> str:
    if check_id.startswith("ACR-ALT-"):
        return SOURCE_REQUIREMENTS["alt"]
    if check_id.startswith("ACR-FORM-"):
        return SOURCE_REQUIREMENTS["keyboard"]
    if check_id == "ACR-DOC-008":
        return SOURCE_REQUIREMENTS["contrast"]
    return SOURCE_REQUIREMENTS["pdfua"]


def _read_external_markdown_report(data: dict[str, Any]) -> AuditReport:
    file_name = data.get("fileName")
    markdown = data.get("remediationReport")
    if not isinstance(file_name, str) or not file_name.strip() or not isinstance(markdown, str):
        raise ValueError("External report requires string fields 'fileName' and 'remediationReport'.")

    specs_by_key = {
        _external_rule_key(requirement): (check_id, category, requirement, severity)
        for check_id, category, requirement, severity in EXTERNAL_RULE_SPECS
    }
    status_map = {
        "passed": "pass",
        "failed": "fail",
        "needs manual check": "manual",
        "manual": "manual",
        "manual review": "manual",
        "not applicable": "not_applicable",
        "n/a": "not_applicable",
        "skipped": "skipped",
        "warning": "warning",
    }
    statuses: dict[str, str] = {}
    failure_details: dict[str, tuple[str, list[int] | None, str]] = {}
    for cells in _markdown_rows(markdown):
        if len(cells) == 3 and cells[0].lower() != "rule":
            key = _external_rule_key(cells[0])
            if key not in specs_by_key:
                continue
            status = status_map.get(cells[2].lower())
            if status is None:
                raise ValueError(f"Unsupported external status '{cells[2]}' for '{cells[0]}'.")
            if key in statuses:
                raise ValueError(f"Duplicate external rule '{cells[0]}'.")
            statuses[key] = status
        elif len(cells) == 7 and cells[0].lower() != "rule":
            key = _external_rule_key(cells[0])
            if key not in specs_by_key:
                continue
            page_numbers = [int(value) for value in re.findall(r"\d+", cells[2])]
            details = f"External evidence: {cells[4]}. Scope: {cells[2]}; count: {cells[3]}."
            failure_details[key] = (details, page_numbers or None, cells[6])

    missing = [requirement for _, _, requirement, _ in EXTERNAL_RULE_SPECS if _external_rule_key(requirement) not in statuses]
    if missing:
        raise ValueError(f"External report is missing {len(missing)} expected rule(s): {', '.join(missing)}")

    findings = []
    for check_id, category, requirement, severity in EXTERNAL_RULE_SPECS:
        key = _external_rule_key(requirement)
        status = statuses[key]
        detail, pages, remediation = failure_details.get(
            key,
            (f"External report result: {status.replace('_', ' ')}.", None, "Review this rule using the external report guidance."),
        )
        findings.append(Finding(
            check_id=check_id,
            category=category,
            requirement=requirement,
            status=status,
            severity=severity,
            details=detail,
            remediation=remediation,
            pages=pages,
            source_requirement=_source_requirement_for(check_id),
        ))

    page_match = re.search(r"\b(\d+)\s+pages?\b", markdown, re.IGNORECASE)
    page_count = int(page_match.group(1)) if page_match else 0
    score = _calculate_score(findings)
    summary = {status: sum(item.status == status for item in findings) for status in ("pass", "fail", "warning", "manual", "skipped", "not_applicable")}
    return AuditReport(
        file=file_name.strip(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        page_count=page_count,
        score=score,
        rating="Good automated result" if score >= 90 else "Needs review" if score >= 70 else "Significant barriers detected",
        standard_basis=["External accessibility remediation report converted to the local audit contract."],
        disclaimer=DISCLAIMER,
        summary=summary,
        findings=findings,
    )


def read_json(input_path: str | Path) -> AuditReport:
    """Load a canonical audit report or convert a supported external Markdown report."""
    path = Path(input_path).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "findings" not in data:
            return _read_external_markdown_report(data)
        findings = [Finding(**item) for item in data.pop("findings")]
        return AuditReport(findings=findings, **data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid audit JSON report: {path}") from exc


def write_html(report: AuditReport, output_path: str | Path, remediation_url: str | None = None, csrf_token: str = "") -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    e = html.escape
    labels = {"pass": "Pass", "fail": "Fail", "warning": "Warning", "manual": "Manual review", "skipped": "Skipped", "not_applicable": "N/A"}
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
    <p>A new PDF will be created; the source file will not be changed. Safe metadata and viewer fixes will be applied. An untagged document can also receive a baseline structure: text objects become paragraphs, images become figures, and layout graphics become artifacts. OCR, alternate-text meaning, detailed semantic tagging, reading order, tables, and visual contrast require additional remediation or human review.</p>
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
    parser.add_argument("--output", "-o", default=str(AUDIT_REPORTS_DIR / "accessibility-report.html"), help="HTML report path")
    parser.add_argument("--json", dest="json_output", help="JSON report path; defaults under reports/audits")
    parser.add_argument("--no-open", action="store_true", help="Do not open the HTML report in a browser")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        report = audit_pdf(args.pdf)
        html_path = write_html(report, args.output)
        source = Path(args.pdf).expanduser().resolve()
        json_output = args.json_output or AUDIT_REPORTS_DIR / f"accessibility-report-{source.stem}.json"
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
