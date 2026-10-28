from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from langdetect import DetectorFactory, LangDetectException, detect_langs
from pypdf import PdfReader
from pypdf.constants import UserAccessPermissions
from pypdf.errors import EmptyFileError, FileNotDecryptedError, PdfReadError, PdfStreamError
from pypdf.generic import ArrayObject, BooleanObject, ContentStream, DictionaryObject, IndirectObject

from pdf_accessibility_policy import (
    WCAG_STANDARD,
    WCAG_STATUS_LABELS,
    WcagResult,
    build_wcag_results,
    summarize_wcag,
    wcag_determination,
)
from pdf_accessibility_ui import APP_STYLES, app_footer, app_header


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
    schema_version: int
    checker_version: str
    ruleset_version: str
    file: str
    source_sha256: str
    generated_at: str
    page_count: int
    score: int
    rating: str
    standard_basis: list[str]
    disclaimer: str
    evidence: dict[str, int | float | str | bool]
    summary: dict[str, int]
    findings: list[Finding]
    wcag_standard: str
    wcag_determination: str
    wcag_summary: dict[str, int]
    wcag_results: list[WcagResult]


WEIGHTS = {"critical": 10, "high": 7, "medium": 4, "low": 1}
AUDIT_SCHEMA_VERSION = 6
CHECKER_VERSION = "2.3.0"
RULESET_VERSION = "2026.10.3"
ACROBAT_RULE_IDS = (
    "ACR-DOC-001", "ACR-DOC-002", "ACR-DOC-003", "ACR-DOC-004",
    "ACR-DOC-005", "ACR-DOC-006", "ACR-DOC-007", "ACR-DOC-008",
    "ACR-DOC-009", "ACR-DOC-010",
    "ACR-PAGE-001", "ACR-PAGE-002", "ACR-PAGE-003", "ACR-PAGE-004",
    "ACR-PAGE-005", "ACR-PAGE-006", "ACR-PAGE-007", "ACR-PAGE-008",
    "ACR-PAGE-009", "ACR-FORM-001", "ACR-FORM-002", "ACR-ALT-001",
    "ACR-ALT-002", "ACR-ALT-003", "ACR-ALT-004", "ACR-ALT-005",
    "ACR-TABLE-001", "ACR-TABLE-002", "ACR-TABLE-003", "ACR-TABLE-004",
    "ACR-TABLE-005", "ACR-LIST-001", "ACR-LIST-002", "ACR-HEAD-001",
)
AUDIT_REPORTS_DIR = Path("reports") / "audits"
INCOMING_REPORTS_DIR = Path("reports") / "incoming"
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
    "Criteria marked Out of scope require capabilities or judgment beyond this automated application."
)
DetectorFactory.seed = 0
BCP47_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class PdfInputError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def _pdf_boolean(value: Any) -> bool:
    value = _resolve(value)
    if isinstance(value, BooleanObject):
        return bool(value.value)
    return value is True


def is_meaningful_title(title: str, source_path: str | Path) -> bool:
    normalized = " ".join(title.casefold().split())
    source_stem = " ".join(Path(source_path).stem.replace("_", " ").replace("-", " ").casefold().split())
    generic_titles = {
        "document",
        "document1",
        "microsoft word",
        "powerpoint presentation",
        "presentation",
        "scanned document",
        "slide 1",
        "untitled",
    }
    authoring_prefixes = ("microsoft word -", "microsoft powerpoint -")
    filename_suffixes = (".pdf", ".doc", ".docx", ".ppt", ".pptx")
    compact = re.sub(r"[\s._-]+", "", normalized)
    placeholder_number = re.fullmatch(r"(?:document|doc|scan|slide)\d+", compact)
    return (
        len(normalized) >= 4
        and normalized not in generic_titles
        and normalized != source_stem
        and not normalized.startswith(authoring_prefixes)
        and not normalized.endswith(filename_suffixes)
        and placeholder_number is None
    )


def _detect_document_language(text: str) -> tuple[str, float] | None:
    sample = " ".join(text.split())[:20000]
    if sum(character.isalpha() for character in sample) < 40:
        return None
    try:
        candidates = detect_langs(sample)
    except LangDetectException:
        return None
    if not candidates or candidates[0].prob < 0.90:
        return None
    return candidates[0].lang.casefold(), round(candidates[0].prob, 4)


def _language_primary(value: str) -> str:
    return value.split("-", 1)[0].casefold()


def _inherited_text(value: Any, key: str) -> str:
    visited: set[tuple[int, int]] = set()
    while value is not None:
        if isinstance(value, IndirectObject):
            reference = (value.idnum, value.generation)
            if reference in visited:
                return ""
            visited.add(reference)
        value = _resolve(value)
        if not isinstance(value, DictionaryObject):
            return ""
        text = _text(value.get(key))
        if text:
            return text
        value = value.get("/Parent")
    return ""


def _name_tree_count(value: Any) -> int:
    value = _resolve(value)
    if not isinstance(value, DictionaryObject):
        return 0
    names = _resolve(value.get("/Names"))
    count = len(names) // 2 if isinstance(names, (ArrayObject, list, tuple)) else 0
    kids = _resolve(value.get("/Kids"))
    if isinstance(kids, (ArrayObject, list, tuple)):
        count += sum(_name_tree_count(item) for item in kids)
    return count


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


def _page_content_is_tagged(page: Any, reader: PdfReader, mapped_mcids: set[int]) -> bool:
    try:
        operations = ContentStream(page.get_contents(), reader).operations
    except Exception:
        return False
    marked_contexts: list[bool] = []
    content_operators = {b"Tj", b"TJ", b"'", b'"', b"Do", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"sh", b"INLINE IMAGE"}
    for operands, operator in operations:
        if operator == b"BMC":
            marked_contexts.append(bool(operands and operands[0] == "/Artifact"))
        elif operator == b"BDC":
            if operands and operands[0] == "/Artifact":
                marked_contexts.append(True)
                continue
            properties = _resolve(operands[1]) if len(operands) > 1 else None
            mcid = properties.get("/MCID") if isinstance(properties, DictionaryObject) else None
            marked_contexts.append(isinstance(mcid, int) and not isinstance(mcid, bool) and int(mcid) in mapped_mcids)
        elif operator == b"EMC":
            if marked_contexts:
                marked_contexts.pop()
        elif operator in content_operators and (not marked_contexts or not marked_contexts[-1]):
            return False
    return True


def _mapped_mcids_by_page(reader: PdfReader, nodes: list[tuple[DictionaryObject, str]]) -> dict[int, set[int]]:
    page_ids = {
        page.indirect_reference.idnum: page_number
        for page_number, page in enumerate(reader.pages, start=1)
        if page.indirect_reference is not None
    }
    mapped: dict[int, set[int]] = {page_number: set() for page_number in range(1, len(reader.pages) + 1)}

    def collect(value: Any) -> set[int]:
        if isinstance(value, IndirectObject):
            resolved = value.get_object()
            if isinstance(resolved, DictionaryObject) and resolved.get("/Type") == "/StructElem":
                return set()
            value = resolved
        if isinstance(value, int) and not isinstance(value, bool):
            return {int(value)}
        if isinstance(value, DictionaryObject):
            mcid = value.get("/MCID")
            return {int(mcid)} if isinstance(mcid, int) and not isinstance(mcid, bool) else set()
        if isinstance(value, (ArrayObject, list, tuple)):
            return set().union(*(collect(item) for item in value)) if value else set()
        return set()

    for element, _ in nodes:
        page_ref = element.get("/Pg")
        if isinstance(page_ref, IndirectObject):
            page_number = page_ids.get(page_ref.idnum)
            if page_number is not None:
                mapped[page_number].update(collect(element.get("/K")))
    return mapped


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


def _strict_pdf_validation(path: Path) -> tuple[bool, str]:
    try:
        reader = PdfReader(str(path), strict=True)
        page_count = len(reader.pages)
        root = _catalog(reader)
        if not root:
            return False, "Strict parsing found no valid document catalog."
        return True, f"Strict parsing opened a valid catalog and {page_count} page(s)."
    except (PdfReadError, PdfStreamError, EOFError, ValueError, TypeError) as exc:
        return False, f"Strict parsing failed: {type(exc).__name__}: {exc}"


def audit_pdf(pdf_path: str | Path) -> AuditReport:
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise PdfInputError("Input must be a PDF file.", 400)
    if path.stat().st_size == 0:
        raise PdfInputError("The PDF is empty.", 400)

    try:
        reader = PdfReader(str(path), strict=False)
        was_encrypted = reader.is_encrypted
        if was_encrypted and not reader.decrypt(""):
            raise PdfInputError("The PDF is encrypted and cannot be opened without a password.")
        root = _catalog(reader)
        page_count = len(reader.pages)
    except PdfInputError:
        raise
    except (EmptyFileError, FileNotDecryptedError, PdfReadError, PdfStreamError, EOFError) as exc:
        raise PdfInputError("The PDF is corrupt, truncated, or otherwise unreadable.") from exc
    if page_count == 0:
        raise PdfInputError("The PDF contains no pages.")

    findings: list[Finding] = []
    mark_info = _resolve(root.get("/MarkInfo"))
    marked = isinstance(mark_info, DictionaryObject) and _pdf_boolean(mark_info.get("/Marked"))
    struct_root = root.get("/StructTreeRoot")
    has_structure = struct_root is not None
    language = _text(root.get("/Lang"))
    metadata = reader.metadata
    title = _text(getattr(metadata, "title", None) if metadata else None)
    viewer_prefs = _resolve(root.get("/ViewerPreferences"))
    display_title = isinstance(viewer_prefs, DictionaryObject) and _pdf_boolean(viewer_prefs.get("/DisplayDocTitle"))
    meaningful_title = is_meaningful_title(title, path)
    outline_count = _outline_count(reader)
    no_text_pages: list[int] = []
    scanned_pages: list[int] = []
    extraction_errors: list[int] = []
    text_chunks: list[str] = []
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
        else:
            text_chunks.append(extracted)
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
    field_values = list(fields.values()) if fields else widgets
    missing_descriptions = [
        str(name) for name, field in fields.items()
        if isinstance(field, dict) and not _inherited_text(field, "/TU")
    ]
    if not fields:
        missing_descriptions = [
            f"widget-{index}"
            for index, field in enumerate(widgets, start=1)
            if not _inherited_text(field, "/TU")
        ]
    field_count = len(field_values)
    detected_language = _detect_document_language("\n".join(text_chunks))
    language_valid = bool(language and BCP47_PATTERN.fullmatch(language))
    language_matches = bool(
        language_valid
        and detected_language
        and _language_primary(language) == detected_language[0]
    )
    strict_pdf_valid, strict_pdf_details = _strict_pdf_validation(path)
    structure_languages = [
        _text(element.get("/Lang"))
        for element, _ in nodes
        if _text(element.get("/Lang"))
    ]
    invalid_structure_languages = [
        value for value in structure_languages
        if not BCP47_PATTERN.fullmatch(value)
    ]
    names = _resolve(root.get("/Names"))
    embedded_files = _name_tree_count(names.get("/EmbeddedFiles")) if isinstance(names, DictionaryObject) else 0
    form_actions = sum(
        item.get("/A") is not None or item.get("/AA") is not None
        for item in widgets
    )
    image_only = bool(page_count) and len(scanned_pages) == page_count
    structure_root = _resolve(struct_root)
    has_parent_tree = isinstance(structure_root, DictionaryObject) and structure_root.get("/ParentTree") is not None
    fully_tagged = marked and has_structure and has_parent_tree and bool(nodes)
    mapped_mcids = _mapped_mcids_by_page(reader, nodes) if fully_tagged else {}
    tagged_pages = [
        number
        for number, page in enumerate(reader.pages, 1)
        if _page_content_is_tagged(page, reader, mapped_mcids.get(number, set()))
    ] if fully_tagged else []
    tabs_pages = [number for number, page in enumerate(reader.pages, 1) if page.get("/Tabs") == "/S"]
    tagged_annotations = [item for item in annotations if item.get("/StructParent") is not None]
    permissions = reader.user_access_permissions
    accessibility_allowed = not was_encrypted or (
        permissions is not None and bool(permissions & UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS)
    )

    def add(check_id: str, category: str, name: str, status: str, severity: str, details: str, remediation: str, pages: list[int] | None = None, source: str = SOURCE_REQUIREMENTS["pdfua"]) -> None:
        findings.append(_finding(check_id, category, name, status, severity, details, remediation, pages, source))

    add("ACR-DOC-001", "Document", "Accessibility permission flag", "pass" if accessibility_allowed else "fail", "high", "The document permits assistive-technology text and graphics extraction." if accessibility_allowed else "The encrypted document does not grant assistive-technology extraction permission.", "Remove security restrictions that prevent assistive-technology access.")
    add("ACR-DOC-002", "Document", "Image-only PDF", "not_applicable" if not image_count else ("fail" if image_only else "pass"), "critical", f"All {page_count} page(s) are image-only." if image_only else (f"Found {image_count} image object(s), and extractable text is also present." if image_count else "No image objects were detected; image-only testing does not apply."), "Run OCR and verify the recognized text and reading order.", scanned_pages or None)
    add("ACR-DOC-003", "Document", "Tagged PDF", "pass" if fully_tagged else "fail", "critical", "The catalog identifies a tagged document with a structure tree." if fully_tagged else "The document lacks a complete tagged-document declaration and structure tree.", "Create and validate a semantic structure tree.")
    add("ACR-DOC-004", "Document", "Logical Reading Order", "out_of_scope", "critical", "Reading-order quality requires semantic and assistive-technology review.", "Verify the tag order against the intended visual and spoken order.")
    if not language:
        language_status = "fail"
        language_details = (
            f"No default language is declared; detected {detected_language[0]} "
            f"with confidence {detected_language[1]:.2f}."
            if detected_language
            else "No default language is declared, and there is insufficient text to infer one safely."
        )
    elif not language_valid:
        language_status = "fail"
        language_details = f"Declared language '{language}' is not a valid supported BCP 47 tag."
    elif detected_language is None:
        language_status = "out_of_scope"
        language_details = (
            f"Declared language '{language}' is valid, but insufficient extractable text "
            "was available to verify that it matches the document."
        )
    elif not language_matches:
        language_status = "fail"
        language_details = f"Declared language '{language}' does not match detected {detected_language[0]} ({detected_language[1]:.2f})."
    else:
        language_status = "pass"
        language_details = f"Declared language '{language}' matches detected {detected_language[0]} ({detected_language[1]:.2f})."
    add("ACR-DOC-005", "Document", "Primary language", language_status, "high", language_details, "Set a valid BCP 47 document language that matches the document text.")
    add("ACR-DOC-006", "Document", "Title", "pass" if meaningful_title and display_title else "fail", "medium", f"Meaningful metadata title is '{title}' and title display is enabled." if meaningful_title and display_title else ("The metadata title is generic or duplicates the filename." if title and not meaningful_title else "A meaningful metadata title and title-bar display preference are both required."), "Add a meaningful title and display it in the title bar.")
    has_tagged_headings = any(role.startswith("H") and role[1:].isdigit() for role, _, _ in roles)
    add("ACR-DOC-007", "Document", "Tagged headings", "not_applicable" if page_count == 1 else ("pass" if has_tagged_headings else "fail"), "medium", "Tagged headings provide bypass navigation." if has_tagged_headings else ("This is a single-page PDF; bypass-block testing does not apply." if page_count == 1 else f"No tagged headings were found in this multi-page document; {outline_count} bookmark(s) were inventoried separately."), "Add a valid tagged heading structure for multi-page documents.")
    add("ACR-DOC-008", "Document", "Color contrast", "out_of_scope", "high", "Static object inspection cannot reliably establish rendered visual contrast.", "Measure foreground/background contrast using a qualified rendering process.", source=SOURCE_REQUIREMENTS["contrast"])
    add("ACR-DOC-009", "Document", "PDF structural validity", "pass" if strict_pdf_valid else "fail", "high", strict_pdf_details, "Repair structural parsing errors and validate the result with an independent PDF validator.")
    if invalid_structure_languages:
        language_parts_status = "fail"
        language_parts_details = (
            f"Found {len(invalid_structure_languages)} invalid structure language tag(s): "
            f"{', '.join(invalid_structure_languages)}."
        )
    elif structure_languages:
        language_parts_status = "pass"
        language_parts_details = f"Validated {len(structure_languages)} declared structure language tag(s)."
    elif text_chunks:
        language_parts_status = "out_of_scope"
        language_parts_details = "No structure language changes are declared; omitted language changes require passage-level review."
    else:
        language_parts_status = "not_applicable"
        language_parts_details = "No extractable text was available for language-of-parts testing."
    add("ACR-DOC-010", "Document", "Language of parts", language_parts_status, "medium", language_parts_details, "Declare valid /Lang values on structure elements when the human language changes.")

    add("ACR-PAGE-001", "Page Content", "Tagged content", "pass" if len(tagged_pages) == page_count and page_count else "fail", "critical", f"All {page_count} page(s) have marked content." if len(tagged_pages) == page_count and page_count else f"Marked-content coverage was verified on {len(tagged_pages)} of {page_count} page(s).", "Associate meaningful page content with structure elements and mark layout content as artifacts.")
    add("ACR-PAGE-002", "Page Content", "Tagged annotations", "not_applicable" if not annotations else ("pass" if len(tagged_annotations) == len(annotations) else "fail"), "high", f"{len(tagged_annotations)} of {len(annotations)} annotation(s) are structure-associated." if annotations else "No annotations were detected; annotation tagging does not apply.", "Associate each meaningful annotation with the structure tree.")
    focusable = links + widgets
    add("ACR-PAGE-003", "Page Content", "Tab order", "not_applicable" if not focusable else ("pass" if len(tabs_pages) == page_count and fully_tagged else "fail"), "high", f"All {page_count} page(s) use valid structure order." if focusable and len(tabs_pages) == page_count and fully_tagged else ("No focusable annotations were detected; tab-order testing does not apply." if not focusable else f"Structure-based tab order is set on {len(tabs_pages)} of {page_count} page(s), tagged={fully_tagged}."), "Set page tab order to use a valid document structure.")
    add("ACR-PAGE-004", "Page Content", "Character encoding", "fail" if extraction_errors else "out_of_scope", "high", "Text extraction failed on one or more pages." if extraction_errors else "Text extraction completed, but Unicode mapping accuracy requires an independent validator or assistive-technology review.", "Use embedded Unicode-compatible fonts and valid character mappings.", extraction_errors or None)
    add("ACR-PAGE-005", "Page Content", "Tagged multimedia", "not_applicable" if not media else ("pass" if all(item.get("/StructParent") is not None for item in media) else "fail"), "medium", f"Found {len(media)} multimedia annotation(s)." if media else "No multimedia objects were detected; multimedia tagging does not apply.", "Tag multimedia and provide accessible alternatives.")
    add("ACR-PAGE-006", "Page Content", "Screen flicker", "out_of_scope" if media or has_scripts else "not_applicable", "high", "Dynamic content is present; flash-threshold testing requires playback analysis." if media or has_scripts else "No dynamic multimedia or scripts were detected; flash testing does not apply.", "Verify dynamic content with a qualified playback-analysis process.")
    add("ACR-PAGE-007", "Page Content", "Scripts and keyboard behavior", "out_of_scope" if has_scripts else "not_applicable", "high", "Scripts are present and require interactive keyboard testing." if has_scripts else "No scripts were detected; script keyboard testing does not apply.", "Remove inaccessible scripts or provide an accessible equivalent.")
    add("ACR-PAGE-008", "Page Content", "Timed responses", "out_of_scope" if has_scripts or media else "not_applicable", "high", "Dynamic content may impose timing and requires interactive testing." if has_scripts or media else "No scripts or media capable of imposing timed responses were detected.", "Allow users to extend, disable, or avoid time limits.")
    link_missing_text = [
        item for item in links
        if not (_text(item.get("/Contents")) or _text(item.get("/TU")))
    ]
    add("ACR-PAGE-009", "Page Content", "Link purpose", "not_applicable" if not links else ("fail" if link_missing_text else "pass"), "medium", f"Found {len(links)} link annotation(s); {len(link_missing_text)} lack accessible contents." if links else "No link annotations were detected; link-purpose testing does not apply.", "Provide meaningful link contents or tagged link text.")

    add("ACR-FORM-001", "Forms", "Tagged form fields", "not_applicable" if not widgets else ("pass" if all(item.get("/StructParent") is not None for item in widgets) else "fail"), "high", f"Found {len(widgets)} form widget(s)." if widgets else "No form widgets were detected; form tagging does not apply.", "Associate each form widget with a Form structure element.", source=SOURCE_REQUIREMENTS["keyboard"])
    add("ACR-FORM-002", "Forms", "Field descriptions", "not_applicable" if not field_count else ("pass" if not missing_descriptions else "fail"), "high", f"Found {field_count} field(s); {len(missing_descriptions)} lack an inherited non-empty /TU tooltip." if field_count else "No form fields were detected; field descriptions do not apply.", "Give every form control a unique descriptive /TU tooltip.", source=SOURCE_REQUIREMENTS["keyboard"])

    alt_elements = [element for _, element, _ in roles if _text(element.get("/Alt")) or _text(element.get("/ActualText"))]
    nested_alt = [element for element in alt_elements if any(_text(child.get("/Alt")) or _text(child.get("/ActualText")) for child in _walk_structure(element.get("/K")))]
    alt_without_content = [element for element in alt_elements if element.get("/K") is None]
    alt_hiding_annotation = [element for element in alt_elements if _contains_object_reference(element.get("/K"))]
    other_alt_missing = [element for role, element, _ in roles if role in {"Formula", "Form"} and not (_text(element.get("/Alt")) or _text(element.get("/ActualText")))]
    add("ACR-ALT-001", "Alternate Text", "Figures alternate text", "not_applicable" if not figures and not image_count else ("pass" if figures and not figures_without_alt else "fail"), "high", f"Found {len(figures)} tagged figure(s); {len(figures_without_alt)} lack alternate text." if figures else f"Found {image_count} image object(s) without verifiable Figure tags.", "Add concise equivalent text to informative figures and artifact decorative images.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-002", "Alternate Text", "Nested alternate text", "not_applicable" if not alt_elements else ("fail" if nested_alt else "pass"), "medium", f"Found {len(nested_alt)} element(s) with nested alternate text." if alt_elements else "No alternate-text elements were detected; nested-alt testing does not apply.", "Keep alternate text on the appropriate outermost semantic element.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-003", "Alternate Text", "Associated with content", "not_applicable" if not alt_elements else ("fail" if alt_without_content else "pass"), "high", f"Found {len(alt_without_content)} alternate-text element(s) without associated content." if alt_elements else "No alternate-text elements were detected; association testing does not apply.", "Associate alternate text with actual marked content.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-004", "Alternate Text", "Hides annotation", "not_applicable" if not alt_elements else ("fail" if alt_hiding_annotation else "pass"), "high", f"Found {len(alt_hiding_annotation)} alternate-text element(s) containing annotation references." if alt_elements else "No alternate-text elements were detected; annotation-hiding testing does not apply.", "Move annotation objects outside alternate-text containers.", source=SOURCE_REQUIREMENTS["alt"])
    add("ACR-ALT-005", "Alternate Text", "Other elements alternate text", "not_applicable" if not any(role in {"Formula", "Form"} for role, _, _ in roles) else ("fail" if other_alt_missing else "pass"), "high", f"Found {len(other_alt_missing)} non-Figure element(s) missing alternate text." if any(role in {"Formula", "Form"} for role, _, _ in roles) else "No Formula or Form structure elements were detected; this check does not apply.", "Add equivalent text to formulas and other non-text semantic elements.", source=SOURCE_REQUIREMENTS["alt"])

    table_roles = [(role, element, parent) for role, element, parent in roles if role in {"Table", "THead", "TBody", "TFoot", "TR", "TH", "TD"}]
    tables = [element for role, element, _ in table_roles if role == "Table"]
    invalid_rows = [element for role, element, parent in table_roles if role == "TR" and parent not in {"Table", "THead", "TBody", "TFoot"}]
    invalid_cells = [element for role, element, parent in table_roles if role in {"TH", "TD"} and parent != "TR"]
    header_count = sum(role == "TH" for role, _, _ in table_roles)
    add("ACR-TABLE-001", "Tables", "Rows", "not_applicable" if not tables else ("fail" if invalid_rows else "pass"), "high", f"Found {len(tables)} table(s) and {len(invalid_rows)} invalid row parent(s)." if tables else "No tagged tables were detected.", "Place each TR under Table, THead, TBody, or TFoot.")
    add("ACR-TABLE-002", "Tables", "TH and TD", "not_applicable" if not tables else ("fail" if invalid_cells else "pass"), "high", f"Found {len(invalid_cells)} cell(s) outside TR elements." if tables else "No tagged tables were detected.", "Place each TH and TD directly under a TR.")
    add("ACR-TABLE-003", "Tables", "Headers", "not_applicable" if not tables else ("pass" if header_count else "fail"), "high", f"Found {header_count} table header cell(s)." if tables else "No tagged tables were detected.", "Add TH cells and valid header associations.")
    add("ACR-TABLE-004", "Tables", "Regularity", "not_applicable" if not tables else "out_of_scope", "high", "No tagged tables were detected." if not tables else "Spans and row/column regularity require semantic table analysis.", "Verify consistent rows, columns, spans, and header associations.")
    add("ACR-TABLE-005", "Tables", "Summary", "not_applicable" if not tables else "out_of_scope", "low", "No tagged tables were detected." if not tables else "Table-summary quality requires semantic analysis and is not mapped to an automated WCAG result.", "Add a summary when needed to explain a complex table.")

    lists = [element for role, element, _ in roles if role == "L"]
    invalid_items = [element for role, element, parent in roles if role == "LI" and parent != "L"]
    invalid_list_parts = [element for role, element, parent in roles if role in {"Lbl", "LBody"} and parent != "LI"]
    add("ACR-LIST-001", "Lists", "List items", "not_applicable" if not lists else ("fail" if invalid_items else "pass"), "high", f"Found {len(lists)} list(s) and {len(invalid_items)} invalid LI parent(s)." if lists else "No tagged lists were detected.", "Place each LI directly under an L element.")
    add("ACR-LIST-002", "Lists", "Lbl and LBody", "not_applicable" if not lists else ("fail" if invalid_list_parts else "pass"), "high", f"Found {len(invalid_list_parts)} Lbl/LBody element(s) outside LI." if lists else "No tagged lists were detected.", "Place Lbl and LBody elements directly under LI.")

    heading_levels = [int(role[1:]) for role, _, _ in roles if len(role) == 2 and role.startswith("H") and role[1].isdigit()]
    heading_skip = any(current > previous + 1 for previous, current in zip(heading_levels, heading_levels[1:]))
    add("ACR-HEAD-001", "Headings", "Appropriate nesting", "not_applicable" if not heading_levels else ("fail" if heading_skip else "pass"), "high", f"Heading sequence: {', '.join(f'H{level}' for level in heading_levels)}." if heading_levels else "No tagged headings were detected.", "Use descriptive headings with levels that do not skip illogically.")

    evidence: dict[str, int | float | str | bool] = {
        "pages": page_count,
        "text_pages": page_count - len(no_text_pages),
        "image_only_pages": len(scanned_pages),
        "images": image_count,
        "figures": len(figures),
        "annotations": len(annotations),
        "links": len(links),
        "widgets": len(widgets),
        "fields": field_count,
        "scripts": int(has_scripts),
        "media": len(media),
        "dynamic_content": len(media) + int(has_scripts) + form_actions + embedded_files,
        "interactive_controls": len(links) + len(widgets) + int(has_scripts),
        "fields_or_actions": field_count + form_actions,
        "form_actions": form_actions,
        "embedded_files": embedded_files,
        "tables": len(tables),
        "lists": len(lists),
        "headings": len(heading_levels),
        "bookmarks": outline_count,
        "declared_language": language,
        "detected_language": detected_language[0] if detected_language else "",
        "language_confidence": detected_language[1] if detected_language else 0,
        "structure_language_tags": len(structure_languages),
        "invalid_structure_language_tags": len(invalid_structure_languages),
        "strict_pdf_valid": strict_pdf_valid,
    }
    score = _calculate_score(findings)
    rating = "Good automated result" if score >= 90 else "Needs review" if score >= 70 else "Significant barriers detected"
    summary = {status: sum(item.status == status for item in findings) for status in ("pass", "fail", "not_applicable", "out_of_scope")}
    wcag_results = build_wcag_results(findings, evidence)
    wcag_summary = summarize_wcag(wcag_results)
    return AuditReport(
        schema_version=AUDIT_SCHEMA_VERSION,
        checker_version=CHECKER_VERSION,
        ruleset_version=RULESET_VERSION,
        file=path.name,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
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
        evidence=evidence,
        summary=summary,
        findings=findings,
        wcag_standard=WCAG_STANDARD,
        wcag_determination=wcag_determination(wcag_summary),
        wcag_summary=wcag_summary,
        wcag_results=wcag_results,
    )


def _calculate_score(findings: list[Finding]) -> int:
    automated = [item for item in findings if item.status in {"pass", "fail"}]
    possible = sum(WEIGHTS[item.severity] for item in automated)
    earned = sum(
        WEIGHTS[item.severity] * (1.0 if item.status == "pass" else 0.0)
        for item in automated
    )
    return round(100 * earned / possible) if possible else 0


def write_json(report: AuditReport, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_json(input_path: str | Path) -> AuditReport:
    """Load a deterministic audit report generated by this application."""
    path = Path(input_path).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != AUDIT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {data.get('schema_version')}")
        findings = [Finding(**item) for item in data.pop("findings")]
        wcag_results = [
            WcagResult(**{
                **item,
                "check_ids": tuple(item["check_ids"]),
                "techniques": tuple(item["techniques"]),
            })
            for item in data.pop("wcag_results")
        ]
        return AuditReport(findings=findings, wcag_results=wcag_results, **data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid audit JSON report: {path}: {exc}") from exc


def write_html(
    report: AuditReport,
    output_path: str | Path,
    remediation_url: str | None = None,
    csrf_token: str = "",
    home_url: str | None = None,
) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    e = html.escape
    labels = {"pass": "Pass", "fail": "Fail", "not_applicable": "N/A", "out_of_scope": "Out of scope"}
    evidence_rows = "".join(
        f"<tr><th scope=\"row\">{e(key.replace('_', ' ').title())}</th><td>{e(str(value))}</td></tr>"
        for key, value in report.evidence.items()
    )
    wcag_rows = "".join(
        f"""<tr><td><strong>{e(item.criterion)}</strong><br>Level {e(item.level)}</td><td>{e(item.name)}</td><td>{e(item.applicability.replace('_', ' ').title())}</td><td>{e(item.test_method)}</td><td><span class="result-label result-{e(item.status)}">{e(WCAG_STATUS_LABELS[item.status])}</span></td><td>{e(item.coverage.replace('_', ' ').title())}</td><td>{e(item.rationale)}<br><code>{e(', '.join(item.techniques) or 'No PDF technique cited')}</code></td><td><code>{e(', '.join(item.check_ids) or 'No mapped check')}</code></td></tr>"""
        for item in report.wcag_results
    )
    rows = []
    for item in report.findings:
        pages = f" Pages: {', '.join(map(str, item.pages))}." if item.pages else ""
        rows.append(f"""
        <article class="finding {e(item.status)}" aria-labelledby="{e(item.check_id)}-title">
          <div class="finding-head"><span class="badge">{e(labels[item.status])}</span><span class="severity">{e(item.severity.title())}</span><span class="check-id">{e(item.check_id)}</span></div>
          <h4 id="{e(item.check_id)}-title">{e(item.requirement)}</h4>
          <p><strong>Source requirement:</strong> {e(item.source_requirement)}</p>
          <p><strong>Result:</strong> {e(item.details + pages)}</p>
          <p><strong>Recommended action:</strong> {e(item.remediation)}</p>
        </article>""")

    remediation_panel = ""
    if remediation_url:
        remediation_panel = f"""
<section id="remediation" class="report-section report-card action" aria-labelledby="remediate-heading">
    <h3 id="remediate-heading">Apply automatic remediation?</h3>
    <p>A new PDF will be created; the source file will not be changed. Safe language, title-display, structure tab-order, and existing form-label propagation fixes will be applied when supported by the source document. OCR, alternate-text meaning, semantic tagging, reading order, tables, and visual contrast require additional remediation or human review.</p>
    <form method="post" action="{html.escape(remediation_url, quote=True)}" onsubmit="return confirm('Create a remediated copy now? The original will not be overwritten.');">
        <input type="hidden" name="token" value="{html.escape(csrf_token, quote=True)}">
        <button type="submit">Yes, apply remediation</button>
    </form>
</section>"""

    home_link = f'<a class="button secondary" href="{e(home_url, quote=True)}">Home</a>' if home_url else ""
    top_home_link = (
        f'<div class="report-actions"><a class="button secondary" href="{e(home_url, quote=True)}" '
        'aria-label="Home: start a new PDF upload">Home / New upload</a></div>'
        if home_url
        else ""
    )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF Accessibility Screening Report</title>
<style>{APP_STYLES}</style>
</head>
<body>{app_header("PDF Accessibility Checker and Remediator", "Deterministic PDF audits and safe accessibility remediation")}
<main id="main-content" class="container"><article class="audit-dashboard">
<header class="report-hero"><p class="report-eyebrow">PDF accessibility audit</p><h2>Audit dashboard</h2><p class="file">File: <strong>{e(report.file)}</strong></p>{top_home_link}</header>
<nav class="report-nav" aria-label="Audit report sections"><a href="#overview">Overview</a><a href="#evidence">Evidence</a><a href="#wcag">WCAG coverage</a><a href="#remediation">Remediation</a><a href="#evaluation">Evaluation basis</a><a href="#findings">Detailed findings</a></nav>
<div class="report-content">
<section id="overview" class="report-section" aria-labelledby="overview-heading"><h3 id="overview-heading">Overview</h3>
<div class="report-kpis">
<div class="report-card report-kpi"><strong>{report.score}/100</strong><span>Automated accessibility score</span></div>
<div class="report-card report-kpi"><strong>{report.page_count}</strong><span>Pages</span></div>
<div class="report-card report-kpi fail"><strong>{report.summary['fail']}</strong><span>Failures</span></div>
<div class="report-card report-kpi manual"><strong>{report.summary['out_of_scope']}</strong><span>Out-of-scope checks</span></div>
<div class="report-card report-kpi"><strong>{report.summary['not_applicable']}</strong><span>Not applicable</span></div>
</div><div class="report-card status-banner"><strong>WCAG automated determination</strong>{e(report.wcag_determination)}. Automated results do not establish full WCAG conformance.</div></section>
<section id="evidence" class="report-section" aria-labelledby="evidence-heading"><h3 id="evidence-heading">Document evidence inventory</h3><div class="report-card"><table class="policy-table"><tbody>{evidence_rows}</tbody></table></div></section>
<section id="wcag" class="report-section" aria-labelledby="wcag-heading"><h3 id="wcag-heading">{e(report.wcag_standard)} coverage</h3>
<div class="report-kpis">
<div class="report-card report-kpi pass"><strong>{report.wcag_summary.get('pass', 0)}</strong><span>Criteria passed</span></div>
<div class="report-card report-kpi fail"><strong>{report.wcag_summary.get('fail', 0)}</strong><span>Criteria failed</span></div>
<div class="report-card report-kpi manual"><strong>{report.wcag_summary.get('out_of_scope', 0)}</strong><span>Out of scope</span></div>
<div class="report-card report-kpi manual"><strong>{report.wcag_summary.get('additional_review', 0)}</strong><span>Additional review</span></div>
<div class="report-card report-kpi"><strong>{report.wcag_summary.get('not_applicable', 0)}</strong><span>Not applicable</span></div>
</div>
<div class="report-card"><table class="policy-table"><thead><tr><th scope="col">Criterion</th><th scope="col">Requirement</th><th scope="col">Applicability</th><th scope="col">Test method</th><th scope="col">Automated result</th><th scope="col">Coverage</th><th scope="col">Rationale / techniques</th><th scope="col">Application checks</th></tr></thead><tbody>{wcag_rows}</tbody></table></div>
</section>
{remediation_panel}
<section id="evaluation" class="report-section" aria-labelledby="evaluation-heading"><h3 id="evaluation-heading">Evaluation basis</h3>
<div class="report-card"><ul>{''.join(f'<li>{e(item)}</li>' for item in report.standard_basis)}</ul><dl class="metadata"><div><dt>Checker and ruleset</dt><dd>{e(report.checker_version)} / {e(report.ruleset_version)}</dd></div><div><dt>Source SHA-256</dt><dd><code>{e(report.source_sha256)}</code></dd></div><div><dt>Generated</dt><dd>{e(report.generated_at)}</dd></div></dl></div></section>
<section class="report-section" aria-labelledby="limitations"><h3 id="limitations">Scope and limitations</h3><div class="report-card notice"><p>{e(report.disclaimer)}</p></div></section>
<section id="findings" class="report-section" aria-labelledby="findings-heading"><h3 id="findings-heading">Detailed findings</h3><div class="report-grid">{''.join(rows)}</div></section>
<div class="report-actions">{home_link}<button type="button" onclick="window.print()">Print or save as PDF</button></div>
</div></article></main>{app_footer()}</body></html>"""
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
    print(f"Failures: {report.summary['fail']}; out of scope: {report.summary['out_of_scope']}; not applicable: {report.summary['not_applicable']}")
    print(f"HTML report: {html_path}")
    print(f"JSON report: {json_path}")
    if not args.no_open:
        webbrowser.open(html_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
