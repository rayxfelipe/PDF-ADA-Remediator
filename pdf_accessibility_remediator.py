from __future__ import annotations

import argparse
import html
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ContentStream,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from pdf_accessibility_audit import AuditReport, DISCLAIMER, audit_pdf, read_json

AUDIT_REPORT_PREFIX = "accessibility-report-"


@dataclass(frozen=True)
class RemediationItem:
    check_id: str
    requirement: str
    status: str
    details: str
    source_requirement: str


@dataclass(frozen=True)
class RemediationReport:
    source_file: str
    remediated_file: str
    generated_at: str
    before_score: int
    after_score: int
    successful: int
    failed: int
    manual_review: int
    items: list[RemediationItem]
    after_audit: AuditReport


def _resolve(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _page_has_image(page: Any) -> bool:
    resources = _resolve(page.get("/Resources"))
    if not isinstance(resources, DictionaryObject):
        return False
    xobjects = _resolve(resources.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return False
    return any(
        isinstance(_resolve(value), DictionaryObject) and _resolve(value).get("/Subtype") == "/Image"
        for value in xobjects.values()
    )


def _xobject_subtype(page: Any, name: Any) -> Any:
    resources = _resolve(page.get("/Resources"))
    if not isinstance(resources, DictionaryObject):
        return None
    xobjects = _resolve(resources.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return None
    xobject = _resolve(xobjects.get(name))
    return xobject.get("/Subtype") if isinstance(xobject, DictionaryObject) else None


def _tag_untagged_document(writer: PdfWriter) -> bool:
    """Add a baseline structure tree to an untagged image or mixed-content PDF."""
    pages = list(writer.pages)
    page_text = [(page.extract_text() or "").strip() for page in pages]
    if not pages or not any(text or _page_has_image(page) for page, text in zip(pages, page_text)):
        return False
    image_only = all(not text and _page_has_image(page) for page, text in zip(pages, page_text))

    structure_root = DictionaryObject({NameObject("/Type"): NameObject("/StructTreeRoot")})
    structure_root_ref = writer._add_object(structure_root)
    document_element = DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Document"),
        NameObject("/P"): structure_root_ref,
        NameObject("/K"): ArrayObject(),
    })
    document_ref = writer._add_object(document_element)
    parent_tree_numbers = ArrayObject()

    for page_index, page in enumerate(pages):
        page_ref = page.indirect_reference
        if page_ref is None:
            raise ValueError("Unable to reference a page while creating the PDF structure tree.")

        content = ContentStream(page.get_contents(), writer)
        page_elements = ArrayObject()

        def add_element(role: str) -> int:
            mcid = len(page_elements)
            element = DictionaryObject({
                NameObject("/Type"): NameObject("/StructElem"),
                NameObject("/S"): NameObject(role),
                NameObject("/P"): document_ref,
                NameObject("/Pg"): page_ref,
                NameObject("/K"): NumberObject(mcid),
            })
            element_ref = writer._add_object(element)
            document_element[NameObject("/K")].append(element_ref)
            page_elements.append(element_ref)
            return mcid

        if image_only:
            mcid = add_element("/Figure")
            content.operations.insert(0, (
                [NameObject("/Figure"), DictionaryObject({NameObject("/MCID"): NumberObject(mcid)})],
                b"BDC",
            ))
            content.operations.append(([], b"EMC"))
        else:
            tagged_operations: list[tuple[Any, bytes]] = []
            artifact_open = False
            text_open = False

            def open_artifact() -> None:
                nonlocal artifact_open
                if not artifact_open:
                    tagged_operations.append(([NameObject("/Artifact")], b"BMC"))
                    artifact_open = True

            def close_artifact() -> None:
                nonlocal artifact_open
                if artifact_open:
                    tagged_operations.append(([], b"EMC"))
                    artifact_open = False

            for operands, operator in content.operations:
                if operator == b"BT":
                    close_artifact()
                    mcid = add_element("/P")
                    tagged_operations.append((
                        [NameObject("/P"), DictionaryObject({NameObject("/MCID"): NumberObject(mcid)})],
                        b"BDC",
                    ))
                    tagged_operations.append((operands, operator))
                    text_open = True
                elif operator == b"ET" and text_open:
                    tagged_operations.append((operands, operator))
                    tagged_operations.append(([], b"EMC"))
                    text_open = False
                elif operator == b"Do" and not text_open and operands and _xobject_subtype(page, operands[0]) == "/Image":
                    close_artifact()
                    mcid = add_element("/Figure")
                    tagged_operations.extend((
                        ([NameObject("/Figure"), DictionaryObject({NameObject("/MCID"): NumberObject(mcid)})], b"BDC"),
                        (operands, operator),
                        ([], b"EMC"),
                    ))
                else:
                    if not text_open:
                        open_artifact()
                    tagged_operations.append((operands, operator))

            if text_open:
                tagged_operations.append(([], b"EMC"))
            close_artifact()
            content.operations = tagged_operations

        page.replace_contents(content)
        page[NameObject("/StructParents")] = NumberObject(page_index)
        page[NameObject("/Tabs")] = NameObject("/S")

        parent_tree_numbers.extend((NumberObject(page_index), page_elements))

    parent_tree = DictionaryObject({NameObject("/Nums"): parent_tree_numbers})
    structure_root[NameObject("/K")] = document_ref
    structure_root[NameObject("/ParentTree")] = writer._add_object(parent_tree)
    structure_root[NameObject("/ParentTreeNextKey")] = NumberObject(len(pages))

    mark_info = _resolve(writer._root_object.get("/MarkInfo"))
    if not isinstance(mark_info, DictionaryObject):
        mark_info = DictionaryObject()
        writer._root_object[NameObject("/MarkInfo")] = mark_info
    mark_info[NameObject("/Marked")] = BooleanObject(True)
    mark_info[NameObject("/Suspects")] = BooleanObject(False)
    writer._root_object[NameObject("/StructTreeRoot")] = structure_root_ref
    return True


def pdf_name_from_report(audit_json: str | Path) -> str | None:
    """Return the PDF filename encoded by accessibility-report-<file_name>.json."""
    report_name = Path(audit_json).name
    if not report_name.lower().startswith(AUDIT_REPORT_PREFIX) or not report_name.lower().endswith(".json"):
        return None
    file_name = report_name[len(AUDIT_REPORT_PREFIX):-len(".json")].strip()
    if not file_name:
        return None
    return file_name if file_name.lower().endswith(".pdf") else f"{file_name}.pdf"


def resolve_source_pdf(
    audit_json: str | Path,
    audit_report: AuditReport,
    source_pdf: str | Path | None = None,
) -> Path:
    """Resolve the PDF explicitly, from the report filename, or from its JSON metadata."""
    report_path = Path(audit_json).expanduser().resolve()
    if source_pdf is not None:
        return Path(source_pdf).expanduser().resolve()

    encoded_name = pdf_name_from_report(report_path)
    candidates: list[Path] = []
    if encoded_name:
        candidates.extend((report_path.parent / encoded_name, Path.cwd() / encoded_name))

    reported_path = Path(audit_report.file).expanduser()
    if reported_path.is_absolute():
        candidates.append(reported_path)
    else:
        candidates.extend((report_path.parent / reported_path, Path.cwd() / reported_path))

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved

    expected = encoded_name or Path(audit_report.file).name or "<file_name>.pdf"
    raise FileNotFoundError(
        f"PDF for audit report not found. Place {expected} beside {report_path.name} "
        "or specify it with --pdf."
    )


def remediate_from_json(
    audit_json: str | Path,
    output_path: str | Path,
    default_language: str = "en-US",
    source_pdf: str | Path | None = None,
) -> RemediationReport:
    """Remediate the source PDF identified by an audit JSON report."""
    before = read_json(audit_json)
    source = resolve_source_pdf(audit_json, before, source_pdf)
    destination = Path(output_path).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Audited PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError("The audit JSON source must be a PDF file.")
    if source == destination:
        raise ValueError("The remediated output must not overwrite the source PDF.")

    before_by_id = {item.check_id: item for item in before.findings}
    language_check = before_by_id.get("ACR-DOC-005") or before_by_id.get("DOC-003")
    title_check = before_by_id.get("ACR-DOC-006") or before_by_id.get("DOC-004")
    if language_check is None or title_check is None:
        raise ValueError("Audit JSON is missing the language or title check.")

    reader = PdfReader(str(source), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("The PDF is encrypted and cannot be remediated without a password.") from exc

    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    root = writer._root_object

    if language_check.status != "pass":
        root[NameObject("/Lang")] = TextStringObject(default_language)
    if title_check.status != "pass":
        title = source.stem.replace("_", " ").replace("-", " ").strip() or "Accessible document"
        writer.add_metadata({"/Title": title})

    if root.get("/StructTreeRoot") is None:
        _tag_untagged_document(writer)

    viewer_prefs = _resolve(root.get("/ViewerPreferences"))
    if not isinstance(viewer_prefs, DictionaryObject):
        viewer_prefs = DictionaryObject()
        root[NameObject("/ViewerPreferences")] = viewer_prefs
    viewer_prefs[NameObject("/DisplayDocTitle")] = BooleanObject(True)

    if root.get("/StructTreeRoot") is not None:
        for page in writer.pages:
            page[NameObject("/Tabs")] = NameObject("/S")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        writer.write(stream)

    after = audit_pdf(destination)
    after_by_id = {item.check_id: item for item in after.findings}
    items: list[RemediationItem] = []
    for original in before.findings:
        updated = after_by_id.get(original.check_id)
        if original.status == "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "passed",
                "The rule passed before remediation and remains unchanged.",
                original.source_requirement,
            ))
        elif original.status in {"not_applicable", "skipped"}:
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "not_applicable",
                original.details,
                original.source_requirement,
            ))
        elif original.status == "manual" or (updated is not None and updated.status == "manual"):
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "manual",
                "This requirement needs human judgment and assistive-technology testing.",
                original.source_requirement,
            ))
        elif updated is not None and updated.status == "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "success",
                f"Updated successfully. New result: {updated.details}",
                original.source_requirement,
            ))
        else:
            details = "The check was not present in the post-remediation audit." if updated is None else f"{updated.details} {updated.remediation}"
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "failed",
                f"Not safely remediated automatically. {details}",
                original.source_requirement,
            ))

    return RemediationReport(
        source_file=str(source),
        remediated_file=str(destination),
        generated_at=datetime.now(timezone.utc).isoformat(),
        before_score=before.score,
        after_score=after.score,
        successful=sum(item.status == "success" for item in items),
        failed=sum(item.status == "failed" for item in items),
        manual_review=sum(item.status == "manual" for item in items),
        items=items,
        after_audit=after,
    )


def write_remediation_html(report: RemediationReport, output_path: str | Path, download_url: str | None = None) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    e = html.escape
    labels = {
        "success": "Remediated",
        "failed": "Not remediated",
        "manual": "Manual review",
        "passed": "Already passed",
        "not_applicable": "N/A or skipped",
    }
    rows = "".join(
        f"""<article class="finding {e(item.status)}"><div class="finding-head"><span class="badge">{e(labels[item.status])}</span><span class="check-id">{e(item.check_id)}</span></div><h3>{e(item.requirement)}</h3><p><strong>Source requirement:</strong> {e(item.source_requirement)}</p><p>{e(item.details)}</p></article>"""
        for item in report.items
    )
    download = f'<a class="button" href="{e(download_url, quote=True)}" download>Download remediated PDF</a>' if download_url else ""
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF Remediation Results</title><style>
:root{{--ink:#172033;--muted:#596579;--paper:#fff;--canvas:#f3f6fa;--blue:#1456a0;--pass:#176b45;--fail:#a12622;--manual:#5f3b91;--border:#d7dee8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(1000px,calc(100% - 2rem));margin:2rem auto 4rem}}header,.panel,.finding{{background:#fff;border:1px solid var(--border);border-radius:12px;box-shadow:0 3px 14px #1720330d;padding:1.3rem}}header{{border-top:6px solid var(--blue)}}h1{{line-height:1.15}}.file{{overflow-wrap:anywhere;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1rem;margin:1rem 0}}.metric{{padding:1rem;background:#f8fafc;border:1px solid var(--border);border-radius:10px}}.metric strong{{display:block;font-size:1.7rem}}.finding{{margin:.8rem 0;border-left:6px solid var(--border)}}.finding.success{{border-left-color:var(--pass)}}.finding.failed{{border-left-color:var(--fail)}}.finding.manual{{border-left-color:var(--manual)}}.finding-head{{display:flex;gap:.6rem;align-items:center}}.badge{{border-radius:999px;padding:.17rem .62rem;font-size:.78rem;font-weight:800;background:#e8edf4}}.success .badge{{background:#d9f3e7;color:#0f5a39}}.failed .badge{{background:#fde3e1;color:#841d19}}.manual .badge{{background:#eee4fa;color:#503078}}.check-id{{color:var(--muted);font-weight:700;font-size:.78rem}}.button{{display:inline-block;padding:.75rem 1.15rem;border-radius:8px;background:var(--blue);color:#fff;font-weight:750;text-decoration:none}}.button:focus-visible{{outline:3px solid #f5b942;outline-offset:3px}}@media print{{body{{background:#fff}}header,.panel,.finding{{box-shadow:none;break-inside:avoid}}}}</style></head><body><main><header><p>Automatic remediation complete</p><h1>PDF Remediation Results</h1><p class="file"><strong>Source:</strong> {e(report.source_file)}</p><p class="file"><strong>New file:</strong> {e(report.remediated_file)}</p><div class="grid"><div class="metric"><strong>{report.before_score} → {report.after_score}</strong><span>Automated score</span></div><div class="metric"><strong>{report.successful}</strong><span>Remediated</span></div><div class="metric"><strong>{report.failed}</strong><span>Not remediated</span></div><div class="metric"><strong>{report.manual_review}</strong><span>Manual checks</span></div></div>{download}</header><section class="panel"><h2>Important limitation</h2><p>{e(DISCLAIMER)}</p><p>The original PDF was preserved. A successful item means its specific automated check passed afterward; it does not mean the entire PDF is compliant.</p></section><section><h2>Remediation outcomes</h2>{rows}</section></main></body></html>"""
    path.write_text(document, encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remediate a PDF using a JSON audit report.")
    parser.add_argument("audit_json", help="Audit JSON named accessibility-report-<file_name>.json")
    parser.add_argument("--pdf", help="Source PDF path; optional when its name is encoded in the report filename")
    parser.add_argument("--output", "-o", help="Remediated PDF path; defaults beside the source PDF")
    parser.add_argument("--report", help="Remediation HTML report path; defaults beside the audit JSON")
    parser.add_argument("--language", default="en-US", help="Default language used when the audit reports none")
    parser.add_argument("--no-open", action="store_true", help="Do not open the remediation HTML report")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        audit_report = read_json(args.audit_json)
        source = resolve_source_pdf(args.audit_json, audit_report, args.pdf)
        output = Path(args.output).expanduser().resolve() if args.output else source.with_name(f"{source.stem}_remediated.pdf")
        audit_json_path = Path(args.audit_json).expanduser().resolve()
        report_output = (
            Path(args.report).expanduser().resolve()
            if args.report
            else audit_json_path.with_name(f"{audit_json_path.stem}-remediation.html")
        )
        result = remediate_from_json(args.audit_json, output, args.language, source)
        report_path = write_remediation_html(result, report_output)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unable to remediate PDF: {exc}", file=sys.stderr)
        return 1

    print(f"Remediated PDF: {result.remediated_file}")
    print(f"Accessibility score: {result.before_score} -> {result.after_score}")
    print(f"Remediation report: {report_path}")
    if not args.no_open:
        webbrowser.open(report_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
