from __future__ import annotations

import argparse
import hashlib
import html
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, IndirectObject, NameObject, TextStringObject

from pdf_accessibility_audit import (
    AuditReport,
    DISCLAIMER,
    REMEDIATION_REPORTS_DIR,
    audit_pdf,
    is_meaningful_title,
)


@dataclass(frozen=True)
class RemediationAction:
    action_id: str
    rule_id: str
    target: str
    before: str | None
    after: str
    result: str


@dataclass(frozen=True)
class RemediationItem:
    check_id: str
    requirement: str
    status: str
    details: str
    source_requirement: str


@dataclass(frozen=True)
class RemediationReport:
    schema_version: int
    source_file: str
    source_sha256: str
    remediated_file: str
    output_sha256: str
    generated_at: str
    checker_version: str
    ruleset_version: str
    before_score: int
    after_score: int
    before_summary: dict[str, int]
    after_summary: dict[str, int]
    successful: int
    failed: int
    manual_review: int
    actions: list[RemediationAction]
    items: list[RemediationItem]
    after_audit: AuditReport


@dataclass(frozen=True)
class _PlannedAction:
    action_id: str
    rule_id: str
    target: str
    before: str | None
    after: str


def _resolve(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _build_remediation_plan(
    reader: PdfReader,
    before: AuditReport,
    source: Path,
    default_language: str,
) -> list[_PlannedAction]:
    findings = {item.check_id: item for item in before.findings}
    root = _resolve(reader.trailer.get("/Root"))
    if not isinstance(root, DictionaryObject):
        raise ValueError("The PDF catalog is missing or invalid.")

    actions: list[_PlannedAction] = []
    language = root.get("/Lang")
    if findings["ACR-DOC-005"].status != "pass":
        actions.append(_PlannedAction(
            "set-document-language",
            "ACR-DOC-005",
            "/Root/Lang",
            str(_resolve(language)) if language is not None else None,
            default_language,
        ))

    title = str(getattr(reader.metadata, "title", "") or "").strip()
    if findings["ACR-DOC-006"].status != "pass" and is_meaningful_title(title, source):
        actions.append(_PlannedAction(
            "enable-document-title-display",
            "ACR-DOC-006",
            "/Root/ViewerPreferences/DisplayDocTitle",
            "false",
            "true",
        ))

    if findings["ACR-DOC-003"].status == "pass" and findings["ACR-PAGE-003"].status != "pass":
        actions.append(_PlannedAction(
            "set-structure-tab-order",
            "ACR-PAGE-003",
            "/Pages/*/Tabs",
            None,
            "/S",
        ))
    return actions


def _apply_plan(writer: PdfWriter, plan: list[_PlannedAction]) -> None:
    root = writer._root_object
    for action in plan:
        if action.action_id == "set-document-language":
            root[NameObject("/Lang")] = TextStringObject(action.after)
        elif action.action_id == "enable-document-title-display":
            viewer_prefs = _resolve(root.get("/ViewerPreferences"))
            if not isinstance(viewer_prefs, DictionaryObject):
                viewer_prefs = DictionaryObject()
                root[NameObject("/ViewerPreferences")] = viewer_prefs
            viewer_prefs[NameObject("/DisplayDocTitle")] = BooleanObject(True)
        elif action.action_id == "set-structure-tab-order":
            for page in writer.pages:
                page[NameObject("/Tabs")] = NameObject("/S")
        else:
            raise ValueError(f"Unsupported remediation action: {action.action_id}")


def _remediation_items(before: AuditReport, after: AuditReport) -> list[RemediationItem]:
    after_by_id = {item.check_id: item for item in after.findings}
    items: list[RemediationItem] = []
    for original in before.findings:
        updated = after_by_id[original.check_id]
        if original.status in {"not_applicable", "skipped"}:
            status = "not_applicable"
            details = original.details
        elif original.status == "manual" or updated.status == "manual":
            status = "manual"
            details = "This requirement needs human judgment or assistive-technology testing."
        elif original.status == "pass" and updated.status == "pass":
            status = "passed"
            details = updated.details
        elif original.status != "pass" and updated.status == "pass":
            status = "success"
            details = f"The deterministic check changed from {original.status} to pass. {updated.details}"
        else:
            status = "failed"
            details = f"Not safely remediated automatically. {updated.details} {updated.remediation}"
        items.append(RemediationItem(
            original.check_id,
            original.requirement,
            status,
            details,
            original.source_requirement,
        ))
    return items


def remediate_pdf(
    source_pdf: str | Path,
    output_path: str | Path,
    default_language: str = "en-US",
) -> RemediationReport:
    """Audit, remediate, and verify a PDF using only deterministic local evidence."""
    source = Path(source_pdf).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError("The source must be a PDF file.")
    if source == destination:
        raise ValueError("The remediated output must not overwrite the source PDF.")
    if not default_language.strip():
        raise ValueError("Default language must not be empty.")

    before = audit_pdf(source)
    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if source_sha256 != before.source_sha256:
        raise ValueError("The source PDF changed after it was audited.")

    reader = PdfReader(str(source), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("The PDF is encrypted and cannot be remediated without a password.") from exc

    plan = _build_remediation_plan(reader, before, source, default_language.strip())
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    _apply_plan(writer, plan)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        writer.write(stream)

    after = audit_pdf(destination)
    if after.page_count != before.page_count:
        raise ValueError("Verification failed because remediation changed the page count.")

    after_by_id = {item.check_id: item for item in after.findings}
    actions = [
        RemediationAction(
            item.action_id,
            item.rule_id,
            item.target,
            item.before,
            item.after,
            "verified" if after_by_id[item.rule_id].status == "pass" else "failed",
        )
        for item in plan
    ]
    items = _remediation_items(before, after)
    output_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    return RemediationReport(
        schema_version=3,
        source_file=str(source),
        source_sha256=source_sha256,
        remediated_file=str(destination),
        output_sha256=output_sha256,
        generated_at=datetime.now(timezone.utc).isoformat(),
        checker_version=before.checker_version,
        ruleset_version=before.ruleset_version,
        before_score=before.score,
        after_score=after.score,
        before_summary=dict(before.summary),
        after_summary=dict(after.summary),
        successful=sum(item.status == "success" for item in items),
        failed=sum(item.status == "failed" for item in items),
        manual_review=sum(item.status == "manual" for item in items),
        actions=actions,
        items=items,
        after_audit=after,
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
    action_rows = "".join(
        f"<li><strong>{e(item.action_id)}</strong>: {e(item.target)} changed from {e(item.before or 'not set')} to {e(item.after)} — {e(item.result)}.</li>"
        for item in report.actions
    ) or "<li>No safe automatic changes were available.</li>"
    download = f'<a class="button" href="{e(download_url, quote=True)}" download>Download remediated PDF</a>' if download_url else ""
    home = f'<p><a class="button secondary" href="{e(home_url, quote=True)}">Home</a></p>' if home_url else ""
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF Remediation Results</title><style>
:root{{--ink:#172033;--muted:#596579;--paper:#fff;--canvas:#f3f6fa;--blue:#1456a0;--pass:#176b45;--fail:#a12622;--manual:#5f3b91;--border:#d7dee8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(1000px,calc(100% - 2rem));margin:2rem auto 4rem}}header,.panel,.finding{{background:#fff;border:1px solid var(--border);border-radius:12px;box-shadow:0 3px 14px #1720330d;padding:1.3rem}}header{{border-top:6px solid var(--blue)}}h1{{line-height:1.15}}.file,code{{overflow-wrap:anywhere;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1rem;margin:1rem 0}}.metric{{padding:1rem;background:#f8fafc;border:1px solid var(--border);border-radius:10px}}.metric strong{{display:block;font-size:1.7rem}}.finding{{margin:.8rem 0;border-left:6px solid var(--border)}}.finding.success{{border-left-color:var(--pass)}}.finding.failed{{border-left-color:var(--fail)}}.finding.manual{{border-left-color:var(--manual)}}.finding-head{{display:flex;gap:.6rem;align-items:center}}.badge{{border-radius:999px;padding:.17rem .62rem;font-size:.78rem;font-weight:800;background:#e8edf4}}.success .badge{{background:#d9f3e7;color:#0f5a39}}.failed .badge{{background:#fde3e1;color:#841d19}}.manual .badge{{background:#eee4fa;color:#503078}}.check-id{{color:var(--muted);font-weight:700;font-size:.78rem}}.button{{display:inline-block;padding:.75rem 1.15rem;border-radius:8px;background:var(--blue);color:#fff;font-weight:750;text-decoration:none}}.secondary{{background:#44546a}}@media print{{body{{background:#fff}}header,.panel,.finding{{box-shadow:none;break-inside:avoid}}}}</style></head><body><main>{home}<header><p>Deterministic remediation complete</p><h1>PDF Remediation Results</h1><p class="file"><strong>Source:</strong> {e(report.source_file)}</p><p class="file"><strong>Output:</strong> {e(report.remediated_file)}</p><div class="grid"><div class="metric"><strong>{report.before_score} → {report.after_score}</strong><span>Score</span></div><div class="metric"><strong>{report.before_summary.get('pass', 0)} → {report.after_summary.get('pass', 0)}</strong><span>Passed</span></div><div class="metric"><strong>{report.before_summary.get('fail', 0)} → {report.after_summary.get('fail', 0)}</strong><span>Failed</span></div><div class="metric"><strong>{report.manual_review}</strong><span>Manual checks</span></div></div>{download}</header><section class="panel"><h2>Verification identity</h2><p>Checker {e(report.checker_version)}; ruleset {e(report.ruleset_version)}.</p><p><strong>Source SHA-256:</strong> <code>{e(report.source_sha256)}</code></p><p><strong>Output SHA-256:</strong> <code>{e(report.output_sha256)}</code></p></section><section class="panel"><h2>Verified actions</h2><ul>{action_rows}</ul></section><section class="panel"><h2>Scope and limitations</h2><p>{e(DISCLAIMER)}</p></section><section><h2>Remediation outcomes</h2>{rows}</section></main></body></html>"""
    path.write_text(document, encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministically audit, remediate, and verify a PDF.")
    parser.add_argument("pdf", help="Source PDF path")
    parser.add_argument("--output", "-o", help="Remediated PDF path; defaults under reports/remediated")
    parser.add_argument("--report", help="Remediation HTML report path; defaults under reports/remediated")
    parser.add_argument("--language", default="en-US", help="Default language used when the PDF declares none")
    parser.add_argument("--no-open", action="store_true", help="Do not open the remediation HTML report")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    source = Path(args.pdf).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else (REMEDIATION_REPORTS_DIR / f"{source.stem}_remediated.pdf").resolve()
    report_output = Path(args.report).expanduser().resolve() if args.report else (REMEDIATION_REPORTS_DIR / f"{source.stem}-remediation.html").resolve()
    try:
        result = remediate_pdf(source, output, args.language)
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
