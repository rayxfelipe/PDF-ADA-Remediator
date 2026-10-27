from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol


class FindingLike(Protocol):
    @property
    def check_id(self) -> str: ...

    @property
    def status(self) -> str: ...


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
    coverage: str
    check_ids: tuple[str, ...]
    rationale: str
    techniques: tuple[str, ...]


@dataclass(frozen=True)
class WcagComparison:
    criterion: str
    name: str
    level: str
    applicability: str
    test_method: str
    before_status: str
    after_status: str
    coverage: str
    completion: str
    check_ids: tuple[str, ...]
    rationale: str
    techniques: tuple[str, ...]


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
    "ACR-DOC-007": ("2.4.1",),
    "ACR-DOC-008": ("1.4.3",),
    "ACR-DOC-009": ("4.1.1",),
    "ACR-DOC-010": ("3.1.2",),
    "ACR-PAGE-001": ("1.3.1", "1.3.2"),
    "ACR-PAGE-002": ("1.3.1", "4.1.2"),
    "ACR-PAGE-003": ("2.1.1", "2.4.3"),
    "ACR-PAGE-006": ("2.3.1",),
    "ACR-PAGE-007": ("2.1.1", "2.1.2", "4.1.2"),
    "ACR-PAGE-008": ("2.2.1", "2.2.2"),
    "ACR-PAGE-009": ("2.4.4",),
    "ACR-FORM-001": ("1.3.1", "4.1.2"),
    "ACR-FORM-002": ("3.3.2", "4.1.2"),
    "ACR-ALT-001": ("1.1.1",),
    "ACR-ALT-002": ("1.1.1",),
    "ACR-ALT-003": ("1.1.1",),
    "ACR-ALT-004": ("1.1.1",),
    "ACR-ALT-005": ("1.1.1",),
    "ACR-TABLE-001": ("1.3.1",),
    "ACR-TABLE-002": ("1.3.1",),
    "ACR-TABLE-003": ("1.3.1",),
    "ACR-TABLE-004": ("1.3.1",),
    "ACR-LIST-001": ("1.3.1",),
    "ACR-LIST-002": ("1.3.1",),
    "ACR-HEAD-001": ("1.3.1", "2.4.6"),
}

RULE_TEST_METHOD = {
    "ACR-DOC-004": "Manual",
    "ACR-DOC-008": "Manual",
    "ACR-DOC-009": "Mixed",
    "ACR-DOC-010": "Mixed",
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
    "not_applicable": "Not applicable",
    "out_of_scope": "Out of scope for automated testing",
}

WCAG_COMPLETION_LABELS = {
    "automatically_remediated": "Automatically remediated and verified",
    "already_passed": "Already passed",
    "not_remediated": "Not remediated",
    "not_applicable": "Not applicable",
    "out_of_scope": "Out of scope for automated testing",
}

# criterion: (policy mode, evidence key, rationale, W3C PDF technique IDs)
WCAG_POLICY = {
    "1.1.1": ("mapped", "", "Images and figures can be checked for tags and text alternatives.", ("PDF1", "PDF4")),
    "1.2.1": ("out_of_scope_if", "dynamic_content", "Prerecorded audio or video alternatives require media interpretation.", ()),
    "1.2.2": ("out_of_scope_if", "dynamic_content", "Caption accuracy and synchronization require media interpretation.", ()),
    "1.2.3": ("out_of_scope_if", "dynamic_content", "Audio descriptions and media alternatives require semantic review.", ()),
    "1.2.4": ("out_of_scope_if", "dynamic_content", "Live caption behavior cannot be established from static PDF objects.", ()),
    "1.2.5": ("out_of_scope_if", "dynamic_content", "Audio-description adequacy requires semantic review.", ()),
    "1.3.1": ("mapped", "", "Tagging, forms, tables, lists, and headings provide machine-testable structural evidence.", ("PDF6", "PDF9", "PDF10", "PDF12", "PDF21")),
    "1.3.2": ("mapped", "", "Structure order is testable, but meaningful reading-order quality remains interpretive.", ("PDF3",)),
    "1.3.3": ("out_of_scope", "", "Instructions based on shape, position, or sound require semantic interpretation.", ()),
    "1.3.4": ("not_applicable", "", "Page orientation is controlled by the PDF reader for a stand-alone PDF.", ()),
    "1.3.5": ("out_of_scope_if", "fields", "PDF fields do not expose HTML autocomplete purposes; field purpose is semantic.", ()),
    "1.4.1": ("out_of_scope", "", "Determining whether color alone conveys meaning requires visual and semantic review.", ()),
    "1.4.2": ("out_of_scope_if", "dynamic_content", "Audio-control behavior requires media playback testing.", ()),
    "1.4.3": ("mapped", "", "Reliable contrast measurement requires rendering and visual context not implemented here.", ()),
    "1.4.4": ("out_of_scope", "", "Text-resize behavior requires rendered-viewer testing.", ()),
    "1.4.5": ("out_of_scope_if", "images", "Distinguishing informative images of text from other images requires interpretation.", ("PDF7",)),
    "1.4.10": ("out_of_scope", "", "Reflow quality requires rendered-viewer and semantic structure testing.", ()),
    "1.4.11": ("out_of_scope", "", "Non-text contrast requires rendered visual analysis.", ()),
    "1.4.12": ("out_of_scope", "", "Text-spacing behavior requires rendered-viewer testing.", ()),
    "1.4.13": ("out_of_scope_if", "dynamic_content", "Hover or focus content requires interactive viewer testing.", ()),
    "2.1.1": ("out_of_scope_if", "interactive_controls", "Interactive controls can be inventoried, but complete keyboard operation requires execution.", ("PDF23",)),
    "2.1.2": ("out_of_scope_if", "interactive_controls", "Interactive controls can be inventoried, but keyboard-trap behavior requires execution.", ()),
    "2.1.4": ("out_of_scope_if", "scripts", "Character-key shortcut behavior requires script execution.", ()),
    "2.2.1": ("mapped", "", "Potential timing mechanisms can be detected, but their behavior requires execution.", ()),
    "2.2.2": ("mapped", "", "Potential moving or timed content can be detected, but controls require execution.", ()),
    "2.3.1": ("mapped", "", "Potential dynamic content can be detected, but flash thresholds require playback analysis.", ()),
    "2.4.1": ("mapped", "", "Multi-page documents can be checked for tagged headings that support bypass navigation.", ("PDF9",)),
    "2.4.2": ("mapped", "", "Metadata title quality and title-bar display are machine-testable.", ("PDF18",)),
    "2.4.3": ("mapped", "", "Focusable annotations can be checked for structure-based tab order.", ("PDF3",)),
    "2.4.4": ("mapped", "", "Link annotations can be checked for accessible text or contents.", ("PDF11", "PDF13")),
    "2.4.5": ("not_applicable", "", "Multiple ways applies to sets of web pages, not a stand-alone PDF.", ("PDF2",)),
    "2.4.6": ("mapped", "", "Existing tagged headings can be checked for non-empty, valid levels.", ("PDF9",)),
    "2.4.7": ("out_of_scope_if", "interactive_controls", "Focus-indicator behavior for document controls requires interactive viewer testing.", ()),
    "2.5.1": ("out_of_scope_if", "interactive_controls", "Multipoint gesture behavior requires interactive execution.", ()),
    "2.5.2": ("out_of_scope_if", "interactive_controls", "Pointer cancellation behavior requires interactive execution.", ()),
    "2.5.3": ("out_of_scope_if", "interactive_controls", "Visible-label comparison requires rendered text-to-control association.", ()),
    "2.5.4": ("out_of_scope_if", "interactive_controls", "Motion-actuation behavior requires interactive execution.", ()),
    "3.1.1": ("mapped", "", "The declared BCP 47 language can be compared with deterministic text-language evidence.", ("PDF16",)),
    "3.1.2": ("mapped", "", "Declared structure-element language changes can be validated, while detecting omitted changes still requires passage-level review.", ("PDF19",)),
    "3.2.1": ("out_of_scope_if", "interactive_controls", "Changes on focus require interactive execution.", ()),
    "3.2.2": ("out_of_scope_if", "interactive_controls", "Changes on input require interactive execution.", ()),
    "3.2.3": ("not_applicable", "", "Consistent navigation applies across a set of documents or pages, not one stand-alone PDF.", ()),
    "3.2.4": ("not_applicable", "", "Consistent identification applies across a set of documents or pages.", ()),
    "3.3.1": ("out_of_scope_if", "fields_or_actions", "Error-identification behavior requires form execution and semantic review.", ()),
    "3.3.2": ("mapped", "", "Form fields can be checked for inherited non-empty tooltips.", ("PDF10",)),
    "3.3.3": ("out_of_scope_if", "fields_or_actions", "Error-suggestion adequacy requires form execution and semantic review.", ()),
    "3.3.4": ("out_of_scope_if", "fields_or_actions", "Error-prevention behavior requires transactional form execution.", ()),
    "4.1.1": ("mapped", "", "Strict parsing detects deterministic structural failures; an independent validator is still required for complete coverage.", ()),
    "4.1.2": ("mapped", "", "Widgets, links, tags, and accessible names provide machine-testable name-role-value evidence.", ("PDF10", "PDF12")),
    "4.1.3": ("out_of_scope_if", "dynamic_content", "Status-message behavior requires interactive execution and assistive-technology observation.", ()),
}


def _criterion_rule_ids(criterion: str) -> tuple[str, ...]:
    return tuple(check_id for check_id, criteria in RULE_WCAG_MAP.items() if criterion in criteria)


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "out_of_scope"
    if "fail" in statuses:
        return "fail"
    if "pass" in statuses:
        return "pass"
    if all(status == "not_applicable" for status in statuses):
        return "not_applicable"
    if "out_of_scope" in statuses:
        return "out_of_scope"
    return "out_of_scope"


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


def build_wcag_results(
    findings: Iterable[FindingLike],
    evidence: Mapping[str, int | float | str | bool],
) -> list[WcagResult]:
    findings_by_id = {item.check_id: item for item in findings}
    results: list[WcagResult] = []
    for item in WCAG_21_AA_CRITERIA:
        check_ids = _criterion_rule_ids(item.criterion)
        mode, evidence_key, rationale, techniques = WCAG_POLICY[item.criterion]
        statuses = [findings_by_id[check_id].status for check_id in check_ids if check_id in findings_by_id]
        if statuses:
            status = _aggregate_status(statuses)
        elif mode == "not_applicable":
            status = "not_applicable"
        elif mode == "out_of_scope":
            status = "out_of_scope"
        else:
            status = "out_of_scope" if evidence.get(evidence_key, 0) else "not_applicable"
        if status == "not_applicable":
            coverage = "not_applicable"
        elif (
            status == "out_of_scope"
            or mode != "mapped"
            or any(value == "out_of_scope" for value in statuses)
            or _test_method(check_ids) != "Automated"
        ):
            coverage = "additional_review"
        else:
            coverage = "complete"
        applicability = status if status in {"not_applicable", "out_of_scope"} else "applicable"
        results.append(WcagResult(
            item.criterion,
            item.name,
            item.level,
            applicability,
            _test_method(check_ids),
            status,
            coverage,
            check_ids,
            rationale,
            techniques,
        ))
    return results


def summarize_wcag(results: Iterable[WcagResult]) -> dict[str, int]:
    items = list(results)
    summary = {
        status: sum(item.status == status for item in items)
        for status in ("pass", "fail", "not_applicable", "out_of_scope")
    }
    summary["complete_coverage"] = sum(item.coverage == "complete" for item in items)
    summary["additional_review"] = sum(item.coverage == "additional_review" for item in items)
    return summary


def compare_wcag(before: Iterable[WcagResult], after: Iterable[WcagResult]) -> list[WcagComparison]:
    before_by_id = {item.criterion: item for item in before}
    comparisons: list[WcagComparison] = []
    for updated in after:
        original = before_by_id[updated.criterion]
        if updated.status == "not_applicable":
            completion = "not_applicable"
        elif updated.status == "out_of_scope":
            completion = "out_of_scope"
        elif updated.status == "fail":
            completion = "not_remediated"
        elif original.status == "pass":
            completion = "already_passed"
        elif original.status != "pass" and updated.status == "pass":
            completion = "automatically_remediated"
        else:
            completion = "already_passed"
        comparisons.append(WcagComparison(
            updated.criterion,
            updated.name,
            updated.level,
            updated.applicability,
            updated.test_method,
            original.status,
            updated.status,
            updated.coverage,
            completion,
            updated.check_ids,
            updated.rationale,
            updated.techniques,
        ))
    return comparisons


def wcag_determination(summary: dict[str, int]) -> str:
    if summary.get("fail", 0):
        return "Incomplete — deterministic failures remain"
    if summary.get("out_of_scope", 0) or summary.get("additional_review", 0):
        return "Passes all automated checks — additional-review coverage remains"
    return "Passes all automated WCAG 2.1 A/AA checks"
