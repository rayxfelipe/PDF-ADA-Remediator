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
    ACROBAT_RULE_IDS,
    AuditReport,
    BCP47_PATTERN,
    DISCLAIMER,
    REMEDIATION_REPORTS_DIR,
    _pdf_boolean,
    audit_pdf,
    is_meaningful_title,
)
from pdf_accessibility_policy import (
    WCAG_COMPLETION_LABELS,
    WCAG_STATUS_LABELS,
    WcagComparison,
    compare_wcag,
    summarize_wcag,
    wcag_determination,
)
from pdf_accessibility_ui import APP_STYLES, app_footer, app_header


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
    automation: str
    automation_reason: str
    evidence_needed: str
    human_action: str


@dataclass(frozen=True)
class RemediationCapability:
    check_id: str
    requirement: str
    classification: str
    reason: str
    evidence_needed: str
    human_action: str


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
    out_of_scope: int
    actions: list[RemediationAction]
    items: list[RemediationItem]
    capabilities: list[RemediationCapability]
    remediation_summary: dict[str, int]
    after_audit: AuditReport
    wcag_determination: str
    wcag_summary: dict[str, int]
    wcag_results: list[WcagComparison]
    checkpoints: list[dict[str, str]]


@dataclass(frozen=True)
class _PlannedAction:
    action_id: str
    rule_id: str
    target: str
    before: str | None
    after: str


EVIDENCE_DEPENDENT_RULES = {
    "ACR-DOC-003",
    "ACR-DOC-005",
    "ACR-DOC-006",
    "ACR-DOC-010",
    "ACR-PAGE-003",
    "ACR-FORM-002",
}
MANUAL_ONLY_RULES = {
    "ACR-DOC-001",
    "ACR-DOC-002",
    "ACR-DOC-008",
    "ACR-DOC-009",
    "ACR-PAGE-004",
    "ACR-PAGE-005",
    "ACR-PAGE-006",
    "ACR-PAGE-007",
    "ACR-PAGE-008",
    "ACR-TABLE-004",
    "ACR-TABLE-005",
}
PROHIBITED_AUTOMATION_RULES = set(ACROBAT_RULE_IDS) - EVIDENCE_DEPENDENT_RULES - MANUAL_ONLY_RULES
EVIDENCE_REQUIREMENTS = {
    "ACR-DOC-003": "A structure tree, parent tree, and existing structure elements must already be present.",
    "ACR-DOC-005": "High-confidence extracted-language evidence must identify the document's primary language.",
    "ACR-DOC-006": "A meaningful metadata title that does not duplicate the filename must already exist.",
    "ACR-DOC-010": "Every invalid declared structure-language tag must have one unambiguous BCP 47 normalization.",
    "ACR-PAGE-003": "The document must already have a complete structure tree before structure-based tab order can be enabled.",
    "ACR-FORM-002": "Every missing tooltip must have an existing non-empty /TM or /Contents value.",
}

if (
    EVIDENCE_DEPENDENT_RULES
    | MANUAL_ONLY_RULES
    | PROHIBITED_AUTOMATION_RULES
) != set(ACROBAT_RULE_IDS):
    raise RuntimeError("The remediation policy must classify every audit rule.")


def _resolve(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _field_text(value: Any) -> str:
    value = _resolve(value)
    return str(value).strip() if value is not None else ""


def _inherited_field_text(value: Any, key: str) -> str:
    visited: set[tuple[int, int]] = set()
    while value is not None:
        if isinstance(value, IndirectObject):
            reference = (value.idnum, value.generation)
            if reference in visited:
                return ""
            visited.add(reference)
        field = _resolve(value)
        if not isinstance(field, DictionaryObject):
            return ""
        text = _field_text(field.get(key))
        if text:
            return text
        value = field.get("/Parent")
    return ""


def _form_fields(root: DictionaryObject) -> list[DictionaryObject]:
    acro_form = _resolve(root.get("/AcroForm"))
    fields = _resolve(acro_form.get("/Fields")) if isinstance(acro_form, DictionaryObject) else None
    if not isinstance(fields, (list, tuple)):
        return []

    results: list[DictionaryObject] = []
    visited: set[tuple[int, int]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, IndirectObject):
            reference = (value.idnum, value.generation)
            if reference in visited:
                return
            visited.add(reference)
        field = _resolve(value)
        if not isinstance(field, DictionaryObject):
            return
        if field.get("/FT") is not None:
            results.append(field)
        kids = _resolve(field.get("/Kids"))
        if isinstance(kids, (list, tuple)):
            for child in kids:
                visit(child)

    for field in fields:
        visit(field)
    return results


def _tooltip_candidates(root: DictionaryObject) -> tuple[int, list[tuple[DictionaryObject, str]]]:
    missing = 0
    candidates: list[tuple[DictionaryObject, str]] = []
    for field in _form_fields(root):
        if _inherited_field_text(field, "/TU"):
            continue
        missing += 1
        candidate = _field_text(field.get("/TM")) or _field_text(field.get("/Contents"))
        if len(candidate) >= 2:
            candidates.append((field, candidate))
    return missing, candidates


def _structure_elements(root: DictionaryObject) -> list[DictionaryObject]:
    struct_root = _resolve(root.get("/StructTreeRoot"))
    if not isinstance(struct_root, DictionaryObject):
        return []
    results: list[DictionaryObject] = []
    visited: set[tuple[int, int]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, IndirectObject):
            reference = (value.idnum, value.generation)
            if reference in visited:
                return
            visited.add(reference)
        value = _resolve(value)
        if isinstance(value, DictionaryObject):
            if value.get("/S") is not None:
                results.append(value)
            visit(value.get("/K"))
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(struct_root.get("/K"))
    return results


def _has_complete_structure_evidence(root: DictionaryObject) -> bool:
    struct_root = _resolve(root.get("/StructTreeRoot"))
    return (
        isinstance(struct_root, DictionaryObject)
        and struct_root.get("/ParentTree") is not None
        and bool(_structure_elements(root))
    )


def _normalize_language_tag(value: str) -> str | None:
    candidate = value.strip().replace("_", "-")
    if not BCP47_PATTERN.fullmatch(candidate):
        return None
    parts = candidate.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def _structure_language_candidates(
    root: DictionaryObject,
) -> tuple[int, list[tuple[DictionaryObject, str]]]:
    invalid = 0
    candidates: list[tuple[DictionaryObject, str]] = []
    for element in _structure_elements(root):
        language = _field_text(element.get("/Lang"))
        if not language or BCP47_PATTERN.fullmatch(language):
            continue
        invalid += 1
        normalized = _normalize_language_tag(language)
        if normalized is not None:
            candidates.append((element, normalized))
    return invalid, candidates


def _base_remediation_policy(check_id: str) -> tuple[str, str, str]:
    if check_id in EVIDENCE_DEPENDENT_RULES:
        return (
            "evidence_dependent",
            "This remediator changes the PDF only when existing document evidence makes the edit unambiguous.",
            EVIDENCE_REQUIREMENTS[check_id],
        )
    if check_id in MANUAL_ONLY_RULES:
        return (
            "manual_only",
            "This requirement needs a qualified external process or human review that this remediator does not perform.",
            "Independent validation, rendered or interactive review, or author confirmation is required.",
        )
    return (
        "prohibited",
        "Automatic repair is prohibited because it would create or reinterpret document semantics.",
        "Author-supplied intent and a qualified human review are required before editing the structure or content.",
    )


def _remediation_capabilities(
    before: AuditReport,
    plan: list[_PlannedAction],
) -> list[RemediationCapability]:
    planned_rules = {item.rule_id for item in plan}
    capabilities: list[RemediationCapability] = []
    for finding in before.findings:
        if finding.status == "pass":
            classification = "no_change_needed"
            reason = "The deterministic source check already passes."
            evidence_needed = "No additional remediation evidence is needed."
        elif finding.status == "not_applicable":
            classification = "not_applicable"
            reason = "The audited document does not contain content to which this check applies."
            evidence_needed = "No remediation evidence is needed unless the document content changes."
        elif finding.check_id in planned_rules:
            classification = "automatic_available"
            reason = "The document contains all evidence required for a bounded deterministic repair."
            evidence_needed = EVIDENCE_REQUIREMENTS[finding.check_id]
        else:
            classification, reason, evidence_needed = _base_remediation_policy(finding.check_id)
        capabilities.append(RemediationCapability(
            finding.check_id,
            finding.requirement,
            classification,
            reason,
            evidence_needed,
            finding.remediation,
        ))
    return capabilities


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
    mark_info = _resolve(root.get("/MarkInfo"))
    marked = (
        isinstance(mark_info, DictionaryObject)
        and _pdf_boolean(mark_info.get("/Marked"))
    )
    if (
        findings["ACR-DOC-003"].status == "fail"
        and not marked
        and _has_complete_structure_evidence(root)
    ):
        actions.append(_PlannedAction(
            "declare-existing-structure",
            "ACR-DOC-003",
            "/Root/MarkInfo/Marked",
            "false" if isinstance(mark_info, DictionaryObject) else None,
            "true",
        ))

    language = root.get("/Lang")
    detected_language = str(before.evidence.get("detected_language", ""))
    if findings["ACR-DOC-005"].status == "fail" and detected_language:
        target_language = (
            default_language
            if default_language.casefold().split("-", 1)[0] == detected_language
            else detected_language
        )
        actions.append(_PlannedAction(
            "set-document-language",
            "ACR-DOC-005",
            "/Root/Lang",
            str(_resolve(language)) if language is not None else None,
            target_language,
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

    if findings["ACR-DOC-003"].status == "pass" and findings["ACR-PAGE-003"].status == "fail":
        actions.append(_PlannedAction(
            "set-structure-tab-order",
            "ACR-PAGE-003",
            "/Pages/*/Tabs",
            None,
            "/S",
        ))

    missing_tooltips, tooltip_candidates = _tooltip_candidates(root)
    if (
        findings["ACR-FORM-002"].status == "fail"
        and missing_tooltips
        and len(tooltip_candidates) == missing_tooltips
    ):
        actions.append(_PlannedAction(
            "propagate-form-tooltips",
            "ACR-FORM-002",
            "/AcroForm/Fields/*/TU",
            f"{missing_tooltips} missing",
            f"{missing_tooltips} populated from existing /TM or /Contents values",
        ))

    invalid_languages, language_candidates = _structure_language_candidates(root)
    if (
        findings["ACR-DOC-010"].status == "fail"
        and invalid_languages
        and len(language_candidates) == invalid_languages
    ):
        actions.append(_PlannedAction(
            "normalize-structure-languages",
            "ACR-DOC-010",
            "/StructTreeRoot/**/Lang",
            f"{invalid_languages} invalid",
            f"{invalid_languages} normalized without changing language identity",
        ))
    return actions


def _apply_plan(writer: PdfWriter, plan: list[_PlannedAction]) -> None:
    root = writer._root_object
    for action in plan:
        if action.action_id == "declare-existing-structure":
            mark_info = _resolve(root.get("/MarkInfo"))
            if not isinstance(mark_info, DictionaryObject):
                mark_info = DictionaryObject()
                root[NameObject("/MarkInfo")] = mark_info
            mark_info[NameObject("/Marked")] = BooleanObject(True)
        elif action.action_id == "set-document-language":
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
        elif action.action_id == "propagate-form-tooltips":
            _, candidates = _tooltip_candidates(root)
            for field, tooltip in candidates:
                field[NameObject("/TU")] = TextStringObject(tooltip)
        elif action.action_id == "normalize-structure-languages":
            _, candidates = _structure_language_candidates(root)
            for element, language in candidates:
                element[NameObject("/Lang")] = TextStringObject(language)
        else:
            raise ValueError(f"Unsupported remediation action: {action.action_id}")


def _remediation_items(
    before: AuditReport,
    after: AuditReport,
    capabilities: list[RemediationCapability],
) -> list[RemediationItem]:
    after_by_id = {item.check_id: item for item in after.findings}
    capability_by_id = {item.check_id: item for item in capabilities}
    items: list[RemediationItem] = []
    for original in before.findings:
        updated = after_by_id[original.check_id]
        capability = capability_by_id[original.check_id]
        if original.status == "not_applicable":
            status = "not_applicable"
            details = original.details
        elif original.status == "out_of_scope" or updated.status == "out_of_scope":
            status = "out_of_scope"
            details = (
                f"{capability.reason} Evidence needed: {capability.evidence_needed} "
                f"Human action: {capability.human_action}"
            )
        elif original.status == "pass" and updated.status == "pass":
            status = "passed"
            details = updated.details
        elif original.status != "pass" and updated.status == "pass":
            status = "success"
            details = f"The deterministic check changed from {original.status} to pass. {updated.details}"
        else:
            status = "failed"
            details = (
                f"Not safely remediated automatically. {updated.details} "
                f"{capability.reason} Evidence needed: {capability.evidence_needed} "
                f"Human action: {capability.human_action}"
            )
        items.append(RemediationItem(
            original.check_id,
            original.requirement,
            status,
            details,
            original.source_requirement,
            capability.classification,
            capability.reason,
            capability.evidence_needed,
            capability.human_action,
        ))
    return items


def _verify_remediation(
    before: AuditReport,
    after: AuditReport,
    plan: list[_PlannedAction],
) -> None:
    if after.page_count != before.page_count:
        raise ValueError("Verification failed because remediation changed the page count.")
    after_by_id = {item.check_id: item for item in after.findings}
    regressions = [
        item.check_id
        for item in before.findings
        if item.status == "pass" and after_by_id[item.check_id].status != "pass"
    ]
    if regressions:
        raise ValueError(
            "Verification failed because existing passes regressed: "
            + ", ".join(regressions)
        )
    unverified = [
        item.rule_id
        for item in plan
        if after_by_id[item.rule_id].status != "pass"
    ]
    if unverified:
        raise ValueError(
            "Verification failed for remediation actions: "
            + ", ".join(unverified)
        )


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
    destination.parent.mkdir(parents=True, exist_ok=True)
    if plan:
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        _apply_plan(writer, plan)
        with destination.open("wb") as stream:
            writer.write(stream)
    else:
        destination.write_bytes(source_bytes)

    after = audit_pdf(destination)
    _verify_remediation(before, after, plan)
    follow_up_reader = PdfReader(str(destination), strict=False)
    follow_up_plan = _build_remediation_plan(
        follow_up_reader,
        after,
        destination,
        default_language.strip(),
    )
    if follow_up_plan:
        raise ValueError(
            "Verification failed because a second remediation pass would make additional changes: "
            + ", ".join(item.action_id for item in follow_up_plan)
        )

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
    capabilities = _remediation_capabilities(before, plan)
    remediation_summary = {
        status: sum(item.classification == status for item in capabilities)
        for status in (
            "automatic_available",
            "evidence_dependent",
            "manual_only",
            "prohibited",
            "no_change_needed",
            "not_applicable",
        )
    }
    items = _remediation_items(before, after, capabilities)
    output_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    wcag_results = compare_wcag(before.wcag_results, after.wcag_results)
    wcag_summary = summarize_wcag(after.wcag_results)
    determination = wcag_determination(wcag_summary)
    checkpoints = [
        {"stage": "Source received", "status": "Complete", "details": f"SHA-256 {source_sha256}"},
        {"stage": "Pre-remediation audit", "status": "Complete", "details": f"{before.summary.get('fail', 0)} deterministic failures; {before.summary.get('out_of_scope', 0)} out-of-scope checks"},
        {"stage": "Automatic remediation", "status": "Complete", "details": f"{len(actions)} safe action(s) applied and verified"},
        {"stage": "Post-remediation audit", "status": "Complete", "details": f"SHA-256 {output_sha256}; {after.summary.get('fail', 0)} deterministic failures remain"},
        {"stage": "No-regression verification", "status": "Passed", "details": "Page count was preserved and no existing deterministic pass regressed"},
        {"stage": "Idempotence verification", "status": "Passed", "details": "A second remediation plan contains no additional changes"},
        {"stage": "Additional-review coverage", "status": "Disclosed" if wcag_summary.get("additional_review", 0) else "None", "details": f"{wcag_summary.get('additional_review', 0)} criteria require review beyond their automated result"},
        {"stage": "WCAG 2.1 AA determination", "status": "Incomplete" if determination.startswith("Incomplete") else "Ready for review", "details": determination},
    ]
    return RemediationReport(
        schema_version=6,
        source_file=source.name,
        source_sha256=source_sha256,
        remediated_file=destination.name,
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
        out_of_scope=sum(item.status == "out_of_scope" for item in items),
        actions=actions,
        items=items,
        capabilities=capabilities,
        remediation_summary=remediation_summary,
        after_audit=after,
        wcag_determination=determination,
        wcag_summary=wcag_summary,
        wcag_results=wcag_results,
        checkpoints=checkpoints,
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
        "out_of_scope": "Out of scope",
        "passed": "Already passed",
        "not_applicable": "N/A or skipped",
    }
    capability_labels = {
        "automatic_available": "Automatic repair available",
        "evidence_dependent": "Needs document evidence",
        "manual_only": "Manual or external process",
        "prohibited": "Automatic repair prohibited",
        "no_change_needed": "Already passes",
        "not_applicable": "Not applicable",
    }
    rows = "".join(
        f"""<article class="finding {e(item.status)}"><div class="finding-head"><span class="badge">{e(labels[item.status])}</span><span class="check-id">{e(item.check_id)}</span></div><h4>{e(item.requirement)}</h4><p><strong>Source requirement:</strong> {e(item.source_requirement)}</p><p><strong>Automation classification:</strong> {e(capability_labels[item.automation])}</p><p>{e(item.details)}</p></article>"""
        for item in report.items
    )
    action_rows = "".join(
        f"<li><strong>{e(item.action_id)}</strong>: {e(item.target)} changed from {e(item.before or 'not set')} to {e(item.after)} — {e(item.result)}.</li>"
        for item in report.actions
    ) or "<li>No safe automatic changes were available.</li>"
    checkpoint_rows = "".join(
        f"""<li><span class="checkpoint-stage">{e(item['stage'])}</span><span class="checkpoint-status">{e(item['status'])}</span><span>{e(item['details'])}</span></li>"""
        for item in report.checkpoints
    )
    wcag_rows = "".join(
        f"""<tr><td><strong>{e(item.criterion)}</strong><br>Level {e(item.level)}</td><td>{e(item.name)}</td><td><span class="result-label result-{e(item.before_status)}">{e(WCAG_STATUS_LABELS[item.before_status])}</span></td><td><span class="result-label result-{e(item.after_status)}">{e(WCAG_STATUS_LABELS[item.after_status])}</span></td><td>{e(item.coverage.replace('_', ' ').title())}</td><td><span class="result-label result-{e(item.completion)}">{e(WCAG_COMPLETION_LABELS[item.completion])}</span></td><td>{e(item.rationale)}<br><code>{e(', '.join(item.techniques) or 'No PDF technique cited')}</code></td><td><code>{e(', '.join(item.check_ids) or 'No mapped check')}</code></td></tr>"""
        for item in report.wcag_results
    )
    capability_rows = "".join(
        f"""<tr><td><code>{e(item.check_id)}</code></td><td>{e(item.requirement)}</td><td><span class="result-label result-{e(item.classification)}">{e(capability_labels[item.classification])}</span></td><td>{e(item.reason)}</td><td>{e(item.evidence_needed)}</td><td>{e(item.human_action)}</td></tr>"""
        for item in report.capabilities
    )
    download = f'<a class="button" href="{e(download_url, quote=True)}" download>Download remediated PDF</a>' if download_url else ""
    home = f'<a class="button secondary" href="{e(home_url, quote=True)}">Home</a>' if home_url else ""
    top_home = (
        f'<div class="report-actions"><a class="button secondary" href="{e(home_url, quote=True)}" '
        'aria-label="Home: start a new PDF upload">Home / New upload</a></div>'
        if home_url
        else ""
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF Remediation Results</title><style>{APP_STYLES}</style></head>
<body>{app_header("PDF Accessibility Checker and Remediator", "Deterministic PDF audits and safe accessibility remediation")}
<main id="main-content" class="container"><article class="audit-dashboard">
<header class="report-hero"><p class="report-eyebrow">Deterministic remediation run complete</p><h2>Remediation dashboard</h2><p class="file"><strong>Source:</strong> {e(report.source_file)}</p><p class="file"><strong>Output:</strong> {e(report.remediated_file)}</p>{top_home}</header>
<nav class="report-nav" aria-label="Remediation report sections"><a href="#overview">Overview</a><a href="#checkpoints">Checkpoints</a><a href="#wcag">WCAG results</a><a href="#capabilities">Remediation coverage</a><a href="#actions">Verified actions</a><a href="#verification">Verification</a><a href="#outcomes">Detailed outcomes</a></nav>
<div class="report-content">
<section id="overview" class="report-section" aria-labelledby="overview-heading"><h3 id="overview-heading">Overview</h3>
<div class="report-kpis">
<div class="report-card report-kpi"><strong>{report.before_score} → {report.after_score}</strong><span>Automated accessibility score</span></div>
<div class="report-card report-kpi pass"><strong>{report.before_summary.get('pass', 0)} → {report.after_summary.get('pass', 0)}</strong><span>Passed</span></div>
<div class="report-card report-kpi fail"><strong>{report.before_summary.get('fail', 0)} → {report.after_summary.get('fail', 0)}</strong><span>Failed</span></div>
<div class="report-card report-kpi manual"><strong>{report.out_of_scope}</strong><span>Out-of-scope checks</span></div>
</div><div class="report-card status-banner"><strong>WCAG automated determination</strong>{e(report.wcag_determination)}. “Automatic remediation complete” does not mean the PDF conforms to WCAG 2.1 Level AA.</div></section>
<section id="checkpoints" class="report-section" aria-labelledby="checkpoints-heading"><h3 id="checkpoints-heading">Audit and remediation checkpoints</h3><div class="report-card"><ul class="checkpoint-list">{checkpoint_rows}</ul></div></section>
<section id="wcag" class="report-section" aria-labelledby="wcag-heading"><h3 id="wcag-heading">WCAG 2.1 Level AA remediation matrix</h3>
<div class="report-kpis">
<div class="report-card report-kpi pass"><strong>{report.wcag_summary.get('pass', 0)}</strong><span>Criteria passed</span></div>
<div class="report-card report-kpi fail"><strong>{report.wcag_summary.get('fail', 0)}</strong><span>Criteria failed</span></div>
<div class="report-card report-kpi manual"><strong>{report.wcag_summary.get('out_of_scope', 0)}</strong><span>Out of scope</span></div>
<div class="report-card report-kpi manual"><strong>{report.wcag_summary.get('additional_review', 0)}</strong><span>Additional review</span></div>
<div class="report-card report-kpi"><strong>{report.wcag_summary.get('not_applicable', 0)}</strong><span>Not applicable</span></div>
</div>
<div class="report-card"><table class="policy-table"><thead><tr><th scope="col">Criterion</th><th scope="col">Requirement</th><th scope="col">Before</th><th scope="col">After</th><th scope="col">Coverage</th><th scope="col">Completion</th><th scope="col">Rationale / techniques</th><th scope="col">Application checks</th></tr></thead><tbody>{wcag_rows}</tbody></table></div>
</section>
<section id="capabilities" class="report-section" aria-labelledby="capabilities-heading"><h3 id="capabilities-heading">Checker-to-remediator coverage</h3>
<p>This inventory classifies every deterministic check. Automatic repair is offered only when the PDF already contains enough evidence to make a bounded change without inventing content or semantics.</p>
<div class="report-kpis">
<div class="report-card report-kpi pass"><strong>{report.remediation_summary.get('automatic_available', 0)}</strong><span>Automatic repairs</span></div>
<div class="report-card report-kpi"><strong>{report.remediation_summary.get('evidence_dependent', 0)}</strong><span>Need evidence</span></div>
<div class="report-card report-kpi manual"><strong>{report.remediation_summary.get('manual_only', 0)}</strong><span>Manual or external</span></div>
<div class="report-card report-kpi fail"><strong>{report.remediation_summary.get('prohibited', 0)}</strong><span>Automation prohibited</span></div>
<div class="report-card report-kpi pass"><strong>{report.remediation_summary.get('no_change_needed', 0)}</strong><span>Already pass</span></div>
<div class="report-card report-kpi"><strong>{report.remediation_summary.get('not_applicable', 0)}</strong><span>Not applicable</span></div>
</div>
<div class="report-card"><table class="policy-table"><thead><tr><th scope="col">Check</th><th scope="col">Requirement</th><th scope="col">Classification</th><th scope="col">Why</th><th scope="col">Evidence needed</th><th scope="col">Human action</th></tr></thead><tbody>{capability_rows}</tbody></table></div>
</section>
<section id="actions" class="report-section" aria-labelledby="actions-heading"><h3 id="actions-heading">Verified actions</h3><div class="report-card action"><ul>{action_rows}</ul></div></section>
<section id="verification" class="report-section" aria-labelledby="verification-heading"><h3 id="verification-heading">Verification identity</h3>
<div class="report-card"><dl class="metadata"><div><dt>Checker and ruleset</dt><dd>{e(report.checker_version)} / {e(report.ruleset_version)}</dd></div><div><dt>Source SHA-256</dt><dd><code>{e(report.source_sha256)}</code></dd></div><div><dt>Output SHA-256</dt><dd><code>{e(report.output_sha256)}</code></dd></div></dl></div></section>
<section class="report-section" aria-labelledby="limitations-heading"><h3 id="limitations-heading">Scope and limitations</h3><div class="report-card notice"><p>{e(DISCLAIMER)}</p></div></section>
<section id="outcomes" class="report-section" aria-labelledby="outcomes-heading"><h3 id="outcomes-heading">Remediation outcomes</h3><div class="report-grid">{rows}</div></section>
<div class="report-actions">{download}{home}<button type="button" onclick="window.print()">Print or save as PDF</button></div>
</div></article></main>{app_footer()}</body></html>"""
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
