from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class FindingLike(Protocol):
    check_id: str
    status: str


@dataclass(frozen=True)
class WcagCriterion:
    criterion: str
    name: str
    level: str


@dataclass(frozen=True)
class WcagResult:
    criterion: str
    name: str
    level: str
    applicability: str
    test_method: str
    status: str
    check_ids: tuple[str, ...]


@dataclass(frozen=True)
class WcagComparison:
    criterion: str
    name: str
    level: str
    applicability: str
    test_method: str
    before_status: str
    after_status: str
    completion: str
    check_ids: tuple[str, ...]


WCAG_STANDARD = "WCAG 2.1 Level AA"

WCAG_21_AA_CRITERIA = (
    WcagCriterion("1.1.1", "Non-text Content", "A"),
    WcagCriterion("1.2.1", "Audio-only and Video-only (Prerecorded)", "A"),
    WcagCriterion("1.2.2", "Captions (Prerecorded)", "A"),
    WcagCriterion("1.2.3", "Audio Description or Media Alternative (Prerecorded)", "A"),
    WcagCriterion("1.2.4", "Captions (Live)", "AA"),
    WcagCriterion("1.2.5", "Audio Description (Prerecorded)", "AA"),
    WcagCriterion("1.3.1", "Info and Relationships", "A"),
    WcagCriterion("1.3.2", "Meaningful Sequence", "A"),
    WcagCriterion("1.3.3", "Sensory Characteristics", "A"),
    WcagCriterion("1.3.4", "Orientation", "AA"),
    WcagCriterion("1.3.5", "Identify Input Purpose", "AA"),
    WcagCriterion("1.4.1", "Use of Color", "A"),
    WcagCriterion("1.4.2", "Audio Control", "A"),
    WcagCriterion("1.4.3", "Contrast (Minimum)", "AA"),
    WcagCriterion("1.4.4", "Resize Text", "AA"),
    WcagCriterion("1.4.5", "Images of Text", "AA"),
    WcagCriterion("1.4.10", "Reflow", "AA"),
    WcagCriterion("1.4.11", "Non-text Contrast", "AA"),
    WcagCriterion("1.4.12", "Text Spacing", "AA"),
    WcagCriterion("1.4.13", "Content on Hover or Focus", "AA"),
    WcagCriterion("2.1.1", "Keyboard", "A"),
    WcagCriterion("2.1.2", "No Keyboard Trap", "A"),
    WcagCriterion("2.1.4", "Character Key Shortcuts", "A"),
    WcagCriterion("2.2.1", "Timing Adjustable", "A"),
    WcagCriterion("2.2.2", "Pause, Stop, Hide", "A"),
    WcagCriterion("2.3.1", "Three Flashes or Below Threshold", "A"),
    WcagCriterion("2.4.1", "Bypass Blocks", "A"),
    WcagCriterion("2.4.2", "Page Titled", "A"),
    WcagCriterion("2.4.3", "Focus Order", "A"),
    WcagCriterion("2.4.4", "Link Purpose (In Context)", "A"),
    WcagCriterion("2.4.5", "Multiple Ways", "AA"),
    WcagCriterion("2.4.6", "Headings and Labels", "AA"),
    WcagCriterion("2.4.7", "Focus Visible", "AA"),
    WcagCriterion("2.5.1", "Pointer Gestures", "A"),
    WcagCriterion("2.5.2", "Pointer Cancellation", "A"),
    WcagCriterion("2.5.3", "Label in Name", "A"),
    WcagCriterion("2.5.4", "Motion Actuation", "A"),
    WcagCriterion("3.1.1", "Language of Page", "A"),
    WcagCriterion("3.1.2", "Language of Parts", "AA"),
    WcagCriterion("3.2.1", "On Focus", "A"),
    WcagCriterion("3.2.2", "On Input", "A"),
    WcagCriterion("3.2.3", "Consistent Navigation", "AA"),
    WcagCriterion("3.2.4", "Consistent Identification", "AA"),
    WcagCriterion("3.3.1", "Error Identification", "A"),
    WcagCriterion("3.3.2", "Labels or Instructions", "A"),
    WcagCriterion("3.3.3", "Error Suggestion", "AA"),
    WcagCriterion("3.3.4", "Error Prevention (Legal, Financial, Data)", "AA"),
    WcagCriterion("4.1.1", "Parsing", "A"),
    WcagCriterion("4.1.2", "Name, Role, Value", "A"),
    WcagCriterion("4.1.3", "Status Messages", "AA"),
)

RULE_WCAG_MAP = {
    "ACR-DOC-002": ("1.1.1",),
    "ACR-DOC-003": ("1.3.1", "1.3.2", "4.1.2"),
    "ACR-DOC-004": ("1.3.2",),
    "ACR-DOC-005": ("3.1.1",),
    "ACR-DOC-006": ("2.4.2",),
    "ACR-DOC-007": ("2.4.5",),
    "ACR-DOC-008": ("1.4.3",),
    "ACR-PAGE-001": ("1.3.1", "1.3.2"),
    "ACR-PAGE-002": ("1.3.1", "4.1.2"),
    "ACR-PAGE-003": ("2.4.3",),
    "ACR-PAGE-004": ("1.3.1", "4.1.2"),
    "ACR-PAGE-006": ("2.3.1",),
    "ACR-PAGE-007": ("2.1.1", "2.1.2", "4.1.2"),
    "ACR-PAGE-008": ("2.2.1", "2.2.2"),
    "ACR-PAGE-009": ("2.4.4", "3.2.3"),
    "ACR-FORM-001": ("1.3.1", "4.1.2"),
    "ACR-FORM-002": ("2.4.6", "3.3.2", "4.1.2"),
    "ACR-ALT-001": ("1.1.1",),
    "ACR-ALT-002": ("1.1.1",),
    "ACR-ALT-003": ("1.1.1",),
    "ACR-ALT-004": ("1.1.1",),
    "ACR-ALT-005": ("1.1.1",),
    "ACR-TABLE-001": ("1.3.1",),
    "ACR-TABLE-002": ("1.3.1",),
    "ACR-TABLE-003": ("1.3.1",),
    "ACR-TABLE-004": ("1.3.1",),
    "ACR-TABLE-005": ("1.3.1",),
    "ACR-LIST-001": ("1.3.1",),
    "ACR-LIST-002": ("1.3.1",),
    "ACR-HEAD-001": ("1.3.1", "2.4.6"),
}

RULE_TEST_METHOD = {
    "ACR-DOC-004": "Manual",
    "ACR-DOC-008": "Manual",
    "ACR-PAGE-004": "Mixed",
    "ACR-PAGE-006": "Mixed",
    "ACR-PAGE-007": "Mixed",
    "ACR-PAGE-008": "Mixed",
    "ACR-PAGE-009": "Mixed",
    "ACR-TABLE-004": "Manual",
    "ACR-TABLE-005": "Not covered",
}

WCAG_STATUS_LABELS = {
    "pass": "Passed",
    "fail": "Failed",
    "manual": "Manual verification required",
    "not_tested": "Not tested by this application",
    "not_applicable": "Not applicable",
}

WCAG_COMPLETION_LABELS = {
    "automatically_remediated": "Automatically remediated and verified",
    "already_passed": "Already passed",
    "not_remediated": "Not remediated",
    "manual_review": "Manual verification required",
    "not_tested": "Not tested by this application",
    "not_applicable": "Not applicable",
    "verified_pass": "Passed after verification",
}


def _criterion_rule_ids(criterion: str) -> tuple[str, ...]:
    return tuple(check_id for check_id, criteria in RULE_WCAG_MAP.items() if criterion in criteria)


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_tested"
    if "fail" in statuses:
        return "fail"
    if "skipped" in statuses:
        return "not_tested"
    if "manual" in statuses or "warning" in statuses:
        return "manual"
    if "pass" in statuses:
        return "pass"
    if all(status == "not_applicable" for status in statuses):
        return "not_applicable"
    return "not_tested"


def _test_method(check_ids: tuple[str, ...]) -> str:
    if not check_ids:
        return "Not covered"
    methods = {RULE_TEST_METHOD.get(check_id, "Automated") for check_id in check_ids}
    if methods == {"Automated"}:
        return "Automated"
    if methods == {"Manual"}:
        return "Manual"
    if methods == {"Not covered"}:
        return "Not covered"
    return "Mixed"


def build_wcag_results(findings: Iterable[FindingLike]) -> list[WcagResult]:
    findings_by_id = {item.check_id: item for item in findings}
    results: list[WcagResult] = []
    for item in WCAG_21_AA_CRITERIA:
        check_ids = _criterion_rule_ids(item.criterion)
        statuses = [findings_by_id[check_id].status for check_id in check_ids if check_id in findings_by_id]
        status = _aggregate_status(statuses)
        applicability = "undetermined" if not check_ids else (
            "not_applicable" if status == "not_applicable" else "applicable"
        )
        results.append(WcagResult(
            item.criterion,
            item.name,
            item.level,
            applicability,
            _test_method(check_ids),
            status,
            check_ids,
        ))
    return results


def summarize_wcag(results: Iterable[WcagResult]) -> dict[str, int]:
    items = list(results)
    return {
        status: sum(item.status == status for item in items)
        for status in ("pass", "fail", "manual", "not_tested", "not_applicable")
    }


def compare_wcag(before: Iterable[WcagResult], after: Iterable[WcagResult]) -> list[WcagComparison]:
    before_by_id = {item.criterion: item for item in before}
    comparisons: list[WcagComparison] = []
    for updated in after:
        original = before_by_id[updated.criterion]
        if updated.status == "not_applicable":
            completion = "not_applicable"
        elif updated.status == "not_tested":
            completion = "not_tested"
        elif updated.status == "manual":
            completion = "manual_review"
        elif updated.status == "fail":
            completion = "not_remediated"
        elif original.status == "pass":
            completion = "already_passed"
        elif original.status != "pass" and updated.status == "pass":
            completion = "automatically_remediated"
        else:
            completion = "verified_pass"
        comparisons.append(WcagComparison(
            updated.criterion,
            updated.name,
            updated.level,
            updated.applicability,
            updated.test_method,
            original.status,
            updated.status,
            completion,
            updated.check_ids,
        ))
    return comparisons


def wcag_determination(summary: dict[str, int]) -> str:
    if summary.get("fail", 0):
        return "Incomplete — deterministic failures remain"
    if summary.get("manual", 0) or summary.get("not_tested", 0):
        return "Incomplete — manual or unsupported criteria remain"
    return "Ready for qualified conformance review"
