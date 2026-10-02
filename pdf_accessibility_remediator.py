from __future__ import annotations

import argparse
import html
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    BooleanObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    TextStringObject,
)

from pdf_accessibility_audit import AuditReport, DISCLAIMER, REMEDIATION_REPORTS_DIR, audit_pdf, read_json

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
    source_score: int
    before_score: int
    after_score: int
    source_summary: dict[str, int]
    before_summary: dict[str, int]
    after_summary: dict[str, int]
    successful: int
    failed: int
    manual_review: int
    items: list[RemediationItem]
    after_audit: AuditReport
    source_notes: list[str] = field(default_factory=list)
    manual_tasks: list[str] = field(default_factory=list)


LEGACY_CHECK_ID_MAP = {
    "DOC-001": "ACR-DOC-003",
    "DOC-002": "ACR-DOC-003",
    "DOC-003": "ACR-DOC-005",
    "DOC-004": "ACR-DOC-006",
    "DOC-005": "ACR-DOC-006",
    "NAV-001": "ACR-DOC-007",
    "CONT-001": "ACR-PAGE-004",
    "CONT-002": "ACR-DOC-002",
    "IMG-001": "ACR-ALT-001",
    "FORM-001": "ACR-FORM-002",
    "MAN-001": "ACR-DOC-004",
    "MAN-002": "ACR-HEAD-001",
    "MAN-003": "ACR-TABLE-003",
    "MAN-004": "ACR-DOC-008",
    "MAN-005": "ACR-PAGE-009",
    "MAN-006": "ACR-ALT-001",
    "MAN-007": "ACR-FORM-001",
    "MAN-008": "ACR-FORM-002",
}


def _resolve(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


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
    local_before = audit_pdf(source)
    local_before_by_id = {item.check_id: item for item in local_before.findings}

    if language_check.status != "pass":
        root[NameObject("/Lang")] = TextStringObject(default_language)

    viewer_prefs = _resolve(root.get("/ViewerPreferences"))
    if not isinstance(viewer_prefs, DictionaryObject):
        viewer_prefs = DictionaryObject()
        root[NameObject("/ViewerPreferences")] = viewer_prefs
    existing_title = str(getattr(reader.metadata, "title", "") or "").strip()
    if existing_title:
        viewer_prefs[NameObject("/DisplayDocTitle")] = BooleanObject(True)

    if local_before_by_id["ACR-DOC-003"].status == "pass":
        for page in writer.pages:
            page[NameObject("/Tabs")] = NameObject("/S")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        writer.write(stream)

    after = audit_pdf(destination)
    after_by_id = {item.check_id: item for item in after.findings}

    def local_finding(original: Any, findings: dict[str, Any]) -> Any:
        return findings.get(LEGACY_CHECK_ID_MAP.get(original.check_id, original.check_id))

    items: list[RemediationItem] = []
    for original in before.findings:
        previous = local_finding(original, local_before_by_id)
        updated = local_finding(original, after_by_id)
        guidance = f" Source evidence: {original.details} Recommended follow-up: {original.remediation}"
        if updated is None:
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "manual",
                "This imported rule is not assessed by the local post-remediation verifier; its source result remains unresolved." + guidance,
                original.source_requirement,
            ))
        elif original.status == "pass" and updated.status == "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "passed",
                "The imported pass agrees with the local post-remediation check." + guidance,
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
        elif original.status == "manual" or updated.status == "manual":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "manual",
                "This requirement needs human judgment, object-level inspection, or assistive-technology testing." + guidance,
                original.source_requirement,
            ))
        elif original.status == "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "failed",
                f"The imported pass conflicts with the local post-remediation result ({updated.status}); it is not treated as verified." + guidance,
                original.source_requirement,
            ))
        elif updated.status == "pass" and previous is not None and previous.status != "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "success",
                f"The same local check changed from {previous.status} to pass. New result: {updated.details}" + guidance,
                original.source_requirement,
            ))
        elif updated.status == "pass":
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "manual",
                "The external report and the local pre-remediation check disagree, so no repair is claimed." + guidance,
                original.source_requirement,
            ))
        else:
            items.append(RemediationItem(
                original.check_id,
                original.requirement,
                "failed",
                f"Not safely remediated automatically. {updated.details} {updated.remediation}" + guidance,
                original.source_requirement,
            ))

    return RemediationReport(
        source_file=str(source),
        remediated_file=str(destination),
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_score=before.score,
        before_score=local_before.score,
        after_score=after.score,
        source_summary=dict(before.summary),
        before_summary=dict(local_before.summary),
        after_summary=dict(after.summary),
        successful=sum(item.status == "success" for item in items),
        failed=sum(item.status == "failed" for item in items),
        manual_review=sum(item.status == "manual" for item in items),
        items=items,
        after_audit=after,
        source_notes=before.source_notes,
        manual_tasks=before.manual_tasks,
    )


def write_remediation_html(
    report: RemediationReport,
    output_path: str | Path,
    download_url: str | None = None,
    home_url: str | None = None,
) -> Path:
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
    source_context = ""
    if report.source_notes or report.manual_tasks:
        notes = "".join(f"<li>{e(item)}</li>" for item in report.source_notes)
        tasks = "".join(f"<li>{e(item)}</li>" for item in report.manual_tasks)
        source_context = f"""<section class="panel"><h2>Imported report context</h2>
        {f'<h3>Evidence and standards notes</h3><ul>{notes}</ul>' if notes else ''}
        {f'<h3>Manual verification queue</h3><ol>{tasks}</ol>' if tasks else ''}</section>"""
    local_comparison = f"""<section class="panel"><h2>Same-basis before and after comparison</h2>
    <p>These values come from the local audit running the same rules on the original and remediated PDFs.</p>
    <div class="grid"><div class="metric"><strong>{report.before_score} → {report.after_score}</strong><span>Local score</span></div><div class="metric"><strong>{report.before_summary.get('pass', 0)} → {report.after_summary.get('pass', 0)}</strong><span>Passed</span></div><div class="metric"><strong>{report.before_summary.get('fail', 0)} → {report.after_summary.get('fail', 0)}</strong><span>Failed</span></div><div class="metric"><strong>{report.before_summary.get('manual', 0)} → {report.after_summary.get('manual', 0)}</strong><span>Manual checks</span></div></div></section>"""
    imported_context = f"""<section class="panel"><h2>Imported checker result</h2>
    <p>These values describe the uploaded input report. Do not compare them with the local output values above because checker implementation, evidence tier, and rule interpretation may differ.</p>
    <div class="grid"><div class="metric"><strong>{report.source_score}</strong><span>Input report score</span></div><div class="metric"><strong>{report.source_summary.get('pass', 0)}</strong><span>Input passes</span></div><div class="metric"><strong>{report.source_summary.get('fail', 0)}</strong><span>Input failures</span></div><div class="metric"><strong>{report.source_summary.get('manual', 0)}</strong><span>Input manual checks</span></div></div></section>"""
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF Remediation Results</title><style>
:root{{--ink:#172033;--muted:#596579;--paper:#fff;--canvas:#f3f6fa;--blue:#1456a0;--pass:#176b45;--fail:#a12622;--manual:#5f3b91;--border:#d7dee8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(1000px,calc(100% - 2rem));margin:2rem auto 4rem}}header,.panel,.finding{{background:#fff;border:1px solid var(--border);border-radius:12px;box-shadow:0 3px 14px #1720330d;padding:1.3rem}}header{{border-top:6px solid var(--blue)}}h1{{line-height:1.15}}.file{{overflow-wrap:anywhere;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1rem;margin:1rem 0}}.metric{{padding:1rem;background:#f8fafc;border:1px solid var(--border);border-radius:10px}}.metric strong{{display:block;font-size:1.7rem}}.finding{{margin:.8rem 0;border-left:6px solid var(--border)}}.finding.success{{border-left-color:var(--pass)}}.finding.failed{{border-left-color:var(--fail)}}.finding.manual{{border-left-color:var(--manual)}}.finding-head{{display:flex;gap:.6rem;align-items:center}}.badge{{border-radius:999px;padding:.17rem .62rem;font-size:.78rem;font-weight:800;background:#e8edf4}}.success .badge{{background:#d9f3e7;color:#0f5a39}}.failed .badge{{background:#fde3e1;color:#841d19}}.manual .badge{{background:#eee4fa;color:#503078}}.check-id{{color:var(--muted);font-weight:700;font-size:.78rem}}.button{{display:inline-block;padding:.75rem 1.15rem;border-radius:8px;background:var(--blue);color:#fff;font-weight:750;text-decoration:none}}.button:focus-visible{{outline:3px solid #f5b942;outline-offset:3px}}@media print{{body{{background:#fff}}header,.panel,.finding{{box-shadow:none;break-inside:avoid}}}}</style></head><body><main><header><p>Automatic remediation complete</p><h1>PDF Remediation Results</h1><p class="file"><strong>Source:</strong> {e(report.source_file)}</p><p class="file"><strong>New file:</strong> {e(report.remediated_file)}</p><div class="grid"><div class="metric"><strong>{report.successful}</strong><span>Remediated</span></div><div class="metric"><strong>{report.failed}</strong><span>Not remediated</span></div><div class="metric"><strong>{report.manual_review}</strong><span>Manual checks</span></div></div>{download}</header><section class="panel"><h2>Important limitation</h2><p>{e(DISCLAIMER)}</p><p>The original PDF was preserved. A successful item means the same local automated check changed from a non-passing result before remediation to a pass afterward; it does not mean the entire PDF is compliant.</p></section>{local_comparison}{imported_context}{source_context}<section><h2>Remediation outcomes</h2>{rows}</section></main></body></html>"""
    if home_url:
        home = f'<p><a class="button" href="{e(home_url, quote=True)}">Home</a></p>'
        document = document.replace("<body><main>", f"<body><main>{home}", 1)
    path.write_text(document, encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remediate a PDF using a JSON audit report.")
    parser.add_argument("audit_json", help="Audit JSON named accessibility-report-<file_name>.json")
    parser.add_argument("--pdf", help="Source PDF path; optional when its name is encoded in the report filename")
    parser.add_argument("--output", "-o", help="Remediated PDF path; defaults under reports/remediated")
    parser.add_argument("--report", help="Remediation HTML report path; defaults under reports/remediated")
    parser.add_argument("--language", default="en-US", help="Default language used when the audit reports none")
    parser.add_argument("--no-open", action="store_true", help="Do not open the remediation HTML report")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        audit_report = read_json(args.audit_json)
        source = resolve_source_pdf(args.audit_json, audit_report, args.pdf)
        output = Path(args.output).expanduser().resolve() if args.output else (REMEDIATION_REPORTS_DIR / f"{source.stem}_remediated.pdf").resolve()
        report_output = (
            Path(args.report).expanduser().resolve()
            if args.report
            else (REMEDIATION_REPORTS_DIR / f"{source.stem}-remediation.html").resolve()
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
