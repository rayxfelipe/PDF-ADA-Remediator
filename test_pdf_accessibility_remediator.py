from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from corpus_regression import run_corpus
from pdf_accessibility_audit import (
    ACROBAT_RULE_IDS,
    WEIGHTS,
    PdfInputError,
    audit_pdf,
    is_meaningful_title,
    read_json,
    write_html,
    write_json,
)
from pdf_accessibility_policy import WCAG_21_AA_CRITERIA, build_wcag_results
from pdf_accessibility_remediator import remediate_pdf, write_remediation_html
from pdf_accessibility_workflow import (
    UPLOAD_PAGE,
    _attachment_header,
    _cleanup_expired_sessions,
    _parse_pdf_upload,
    _read_limited_body,
    _valid_api_key,
    remediate_api_payload,
)


def _image_only_writer() -> PdfWriter:
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    image = DecodedStreamObject()
    image.set_data(b"\x00")
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(1),
        NameObject("/Height"): NumberObject(1),
        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    image_ref = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref}),
    })
    content = DecodedStreamObject()
    content.set_data(b"q 72 0 0 72 0 0 cm /Im0 Do Q")
    page.replace_contents(content)
    return writer


def _mixed_content_writer() -> PdfWriter:
    writer = _image_only_writer()
    page = writer.pages[0]
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page["/Resources"][NameObject("/Font")] = DictionaryObject({
        NameObject("/F1"): writer._add_object(font),
    })
    content = DecodedStreamObject()
    content.set_data(
        b"0 0 72 72 re S "
        b"BT /F1 12 Tf 8 56 Td (Accessible text) Tj ET "
        b"q 20 0 0 20 8 8 cm /Im0 Do Q"
    )
    page.replace_contents(content)
    return writer


def _text_writer(text: str, language: str | None = None) -> PdfWriter:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 12 Tf 36 720 Td ({escaped}) Tj ET".encode("ascii"))
    page.replace_contents(content)
    if language:
        writer._root_object[NameObject("/Lang")] = TextStringObject(language)
    return writer


def _form_writer(
    tooltip: str | None,
    inherited: bool = False,
    mapping_name: str | None = None,
) -> PdfWriter:
    writer = _mixed_content_writer()
    page = writer.pages[0]
    widget = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Tx"),
        NameObject("/T"): TextStringObject("account_number"),
        NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(40), NumberObject(12)]),
    })
    widget_ref = writer._add_object(widget)
    field_ref = widget_ref
    if inherited:
        parent = DictionaryObject({
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("account_number"),
            NameObject("/Kids"): ArrayObject([widget_ref]),
        })
        if tooltip is not None:
            parent[NameObject("/TU")] = TextStringObject(tooltip)
        if mapping_name is not None:
            parent[NameObject("/TM")] = TextStringObject(mapping_name)
        parent_ref = writer._add_object(parent)
        widget[NameObject("/Parent")] = parent_ref
        field_ref = parent_ref
    elif tooltip is not None:
        widget[NameObject("/TU")] = TextStringObject(tooltip)
    if not inherited and mapping_name is not None:
        widget[NameObject("/TM")] = TextStringObject(mapping_name)
    page[NameObject("/Annots")] = ArrayObject([widget_ref])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([field_ref]),
    })
    return writer


class AccessibilityRemediationTests(unittest.TestCase):
    def test_audit_is_versioned_hash_bound_and_repeatable(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)

            first = audit_pdf(source)
            second = audit_pdf(source)

        self.assertEqual(first.schema_version, 6)
        self.assertEqual(first.checker_version, "2.3.0")
        self.assertEqual(first.ruleset_version, "2026.10.3")
        self.assertEqual(first.file, "source.pdf")
        self.assertEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(first.findings, second.findings)
        self.assertEqual(tuple(item.check_id for item in first.findings), ACROBAT_RULE_IDS)
        self.assertEqual(len(first.wcag_results), len(WCAG_21_AA_CRITERIA))
        self.assertEqual(len(first.wcag_results), 50)
        self.assertIn("Incomplete", first.wcag_determination)

    def test_audit_json_only_loads_local_structured_contract(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)
            original = audit_pdf(source)
            report_path = write_json(original, root / "audit.json")
            loaded = read_json(report_path)
            incompatible = root / "incompatible.json"
            incompatible.write_text(json.dumps({
                "fileName": "source.pdf",
                "remediationReport": "AI-generated report",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid audit JSON report"):
                read_json(incompatible)
            old_schema = root / "old-schema.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["schema_version"] = 5
            old_schema.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported schema version: 5"):
                read_json(old_schema)

        self.assertEqual(loaded.source_sha256, original.source_sha256)

    def test_remediation_uses_local_audit_and_verifies_language(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            output = root / "output.pdf"
            with source.open("wb") as stream:
                _text_writer(
                    "This permit application contains clear instructions for residents "
                    "who need to submit documents and request a city inspection."
                ).write(stream)

            result = remediate_pdf(source, output)
            remediated = PdfReader(output)

        self.assertEqual(remediated.trailer["/Root"]["/Lang"], "en-US")
        self.assertNotEqual(result.source_sha256, result.output_sha256)
        self.assertEqual(result.source_file, "source.pdf")
        self.assertEqual(result.remediated_file, "output.pdf")
        action = next(item for item in result.actions if item.action_id == "set-document-language")
        self.assertEqual(action.result, "verified")
        language = next(item for item in result.items if item.check_id == "ACR-DOC-005")
        self.assertEqual(language.status, "success")
        wcag_language = next(item for item in result.wcag_results if item.criterion == "3.1.1")
        self.assertEqual(wcag_language.before_status, "fail")
        self.assertEqual(wcag_language.after_status, "pass")
        self.assertEqual(wcag_language.completion, "automatically_remediated")

    def test_language_match_mismatch_and_insufficient_evidence(self) -> None:
        english = (
            "This public notice explains how residents can submit an application, "
            "request assistance, and receive information about the review process."
        )
        with TemporaryDirectory() as folder:
            root = Path(folder)
            matching = root / "matching.pdf"
            mismatching = root / "mismatching.pdf"
            short = root / "short.pdf"
            with matching.open("wb") as stream:
                _text_writer(english, "en-US").write(stream)
            with mismatching.open("wb") as stream:
                _text_writer(english, "fr").write(stream)
            with short.open("wb") as stream:
                _text_writer("Short text", "en-US").write(stream)

            matching_status = next(item for item in audit_pdf(matching).findings if item.check_id == "ACR-DOC-005")
            mismatching_status = next(item for item in audit_pdf(mismatching).findings if item.check_id == "ACR-DOC-005")
            short_status = next(item for item in audit_pdf(short).findings if item.check_id == "ACR-DOC-005")

        self.assertEqual(matching_status.status, "pass")
        self.assertEqual(mismatching_status.status, "fail")
        self.assertEqual(short_status.status, "out_of_scope")

    def test_missing_or_invalid_language_fails_without_detection_evidence(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            missing = root / "missing.pdf"
            invalid = root / "invalid.pdf"
            with missing.open("wb") as stream:
                _text_writer("Short text").write(stream)
            with invalid.open("wb") as stream:
                _text_writer("Short text", "not_a_language").write(stream)

            missing_finding = next(
                item for item in audit_pdf(missing).findings
                if item.check_id == "ACR-DOC-005"
            )
            invalid_finding = next(
                item for item in audit_pdf(invalid).findings
                if item.check_id == "ACR-DOC-005"
            )

        self.assertEqual(missing_finding.status, "fail")
        self.assertIn("No default language", missing_finding.details)
        self.assertEqual(invalid_finding.status, "fail")
        self.assertIn("not a valid", invalid_finding.details)

    def test_mapped_wcag_outcome_is_not_erased_by_review_coverage(self) -> None:
        findings = [
            SimpleNamespace(check_id="ACR-DOC-003", status="pass"),
            SimpleNamespace(check_id="ACR-PAGE-001", status="pass"),
            SimpleNamespace(check_id="ACR-PAGE-002", status="not_applicable"),
            SimpleNamespace(check_id="ACR-FORM-001", status="not_applicable"),
            SimpleNamespace(check_id="ACR-TABLE-001", status="pass"),
            SimpleNamespace(check_id="ACR-TABLE-002", status="pass"),
            SimpleNamespace(check_id="ACR-TABLE-003", status="pass"),
            SimpleNamespace(check_id="ACR-TABLE-004", status="out_of_scope"),
            SimpleNamespace(check_id="ACR-LIST-001", status="not_applicable"),
            SimpleNamespace(check_id="ACR-LIST-002", status="not_applicable"),
            SimpleNamespace(check_id="ACR-HEAD-001", status="not_applicable"),
        ]

        result = next(
            item for item in build_wcag_results(findings, {"tables": 1})
            if item.criterion == "1.3.1"
        )

        self.assertEqual(result.status, "pass")
        self.assertEqual(result.coverage, "additional_review")

    def test_pdf_validity_has_a_machine_result_and_review_coverage(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "valid.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)

            report = audit_pdf(source)

        finding = next(item for item in report.findings if item.check_id == "ACR-DOC-009")
        criterion = next(item for item in report.wcag_results if item.criterion == "4.1.1")
        self.assertEqual(finding.status, "pass")
        self.assertEqual(criterion.status, "pass")
        self.assertEqual(criterion.coverage, "additional_review")
        self.assertGreater(report.wcag_summary["additional_review"], 0)

    def test_preserves_meaningful_title_and_enables_title_display(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "permit.pdf"
            output = root / "output.pdf"
            writer = _mixed_content_writer()
            writer.add_metadata({"/Title": "Permit Instructions"})
            with source.open("wb") as stream:
                writer.write(stream)

            result = remediate_pdf(source, output)
            remediated = PdfReader(output)

        self.assertEqual(remediated.metadata.title, "Permit Instructions")
        self.assertTrue(remediated.trailer["/Root"]["/ViewerPreferences"]["/DisplayDocTitle"])
        action = next(item for item in result.actions if item.action_id == "enable-document-title-display")
        self.assertEqual(action.result, "verified")

    def test_generic_title_is_not_accepted_or_enabled(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "slides.pdf"
            output = root / "output.pdf"
            writer = _mixed_content_writer()
            writer.add_metadata({"/Title": "PowerPoint Presentation"})
            with source.open("wb") as stream:
                writer.write(stream)

            before = audit_pdf(source)
            result = remediate_pdf(source, output)
            remediated = PdfReader(output)

        title = next(item for item in before.findings if item.check_id == "ACR-DOC-006")
        self.assertEqual(title.status, "fail")
        self.assertNotIn("/ViewerPreferences", remediated.trailer["/Root"])
        self.assertFalse(any(item.action_id == "enable-document-title-display" for item in result.actions))

    def test_title_heuristic_rejects_placeholders_and_filenames(self) -> None:
        rejected = (
            "Scanned Document",
            "Document1",
            "Slide 1",
            "scan-42",
            "permit.pdf",
            "Microsoft Word - permit",
            "abc",
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertFalse(is_meaningful_title(title, "permit.pdf"))
        self.assertTrue(is_meaningful_title("Residential Permit Instructions", "permit.pdf"))

    def test_form_description_requires_tu_and_supports_inheritance(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            name_only = root / "name-only.pdf"
            inherited_tooltip = root / "inherited-tooltip.pdf"
            with name_only.open("wb") as stream:
                _form_writer(None).write(stream)
            with inherited_tooltip.open("wb") as stream:
                _form_writer("Account number", inherited=True).write(stream)

            missing = next(
                item for item in audit_pdf(name_only).findings
                if item.check_id == "ACR-FORM-002"
            )
            described = next(
                item for item in audit_pdf(inherited_tooltip).findings
                if item.check_id == "ACR-FORM-002"
            )

        self.assertEqual(missing.status, "fail")
        self.assertEqual(described.status, "pass")

    def test_remediation_propagates_existing_form_mapping_names(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "form.pdf"
            output = root / "form-remediated.pdf"
            with source.open("wb") as stream:
                _form_writer(None, mapping_name="Account number").write(stream)

            report = remediate_pdf(source, output)
            fields = PdfReader(output).get_fields() or {}

        self.assertEqual(next(iter(fields.values()))["/TU"], "Account number")
        action = next(
            item for item in report.actions
            if item.action_id == "propagate-form-tooltips"
        )
        self.assertEqual(action.result, "verified")
        finding = next(
            item for item in report.after_audit.findings
            if item.check_id == "ACR-FORM-002"
        )
        self.assertEqual(finding.status, "pass")

    def test_absent_content_is_not_reported_as_pass(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "plain.pdf"
            with source.open("wb") as stream:
                _text_writer("Short text").write(stream)
            report = audit_pdf(source)

        statuses = {item.check_id: item.status for item in report.findings}
        for check_id in (
            "ACR-DOC-002",
            "ACR-PAGE-002",
            "ACR-PAGE-003",
            "ACR-PAGE-005",
            "ACR-PAGE-006",
            "ACR-PAGE-007",
            "ACR-PAGE-008",
            "ACR-PAGE-009",
            "ACR-FORM-001",
            "ACR-FORM-002",
        ):
            with self.subTest(check_id=check_id):
                self.assertEqual(statuses[check_id], "not_applicable")
        self.assertEqual(statuses["ACR-DOC-004"], "out_of_scope")
        self.assertEqual(statuses["ACR-DOC-008"], "out_of_scope")
        wcag_statuses = {item.status for item in report.wcag_results}
        self.assertEqual(wcag_statuses, {"pass", "fail", "not_applicable", "out_of_scope"})

    def test_score_excludes_not_applicable_and_out_of_scope_checks(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)
            report = audit_pdf(source)

        applicable = [item for item in report.findings if item.status in {"pass", "fail"}]
        possible = sum(WEIGHTS[item.severity] for item in applicable)
        earned = sum(WEIGHTS[item.severity] for item in applicable if item.status == "pass")
        self.assertEqual(report.score, round(100 * earned / possible))

    def test_marked_false_is_not_treated_as_tagged(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "marked-false.pdf"
            writer = _mixed_content_writer()
            element = DictionaryObject({
                NameObject("/Type"): NameObject("/StructElem"),
                NameObject("/S"): NameObject("/P"),
                NameObject("/K"): NumberObject(0),
            })
            writer._root_object[NameObject("/MarkInfo")] = DictionaryObject({
                NameObject("/Marked"): BooleanObject(False),
            })
            writer._root_object[NameObject("/StructTreeRoot")] = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/StructTreeRoot"),
                NameObject("/ParentTree"): writer._add_object(DictionaryObject()),
                NameObject("/K"): writer._add_object(element),
            }))
            with source.open("wb") as stream:
                writer.write(stream)

            report = audit_pdf(source)

        tagged = next(item for item in report.findings if item.check_id == "ACR-DOC-003")
        self.assertEqual(tagged.status, "fail")

    def test_does_not_invent_title_or_structure(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            output = root / "output.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)

            result = remediate_pdf(source, output)
            remediated = PdfReader(output)

        self.assertFalse(remediated.metadata.title)
        self.assertNotIn("/StructTreeRoot", remediated.trailer["/Root"])
        statuses = {item.check_id: item.status for item in result.items}
        self.assertEqual(statuses["ACR-DOC-003"], "failed")
        self.assertEqual(statuses["ACR-DOC-006"], "failed")

    def test_invalid_pdf_inputs_return_typed_errors(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            empty = root / "empty.pdf"
            corrupt = root / "corrupt.pdf"
            truncated = root / "truncated.pdf"
            encrypted = root / "encrypted.pdf"
            zero_page = root / "zero-page.pdf"
            empty.write_bytes(b"")
            corrupt.write_bytes(b"%PDF-1.7\nnot a real PDF")
            writer = _mixed_content_writer()
            data = BytesIO()
            writer.write(data)
            truncated.write_bytes(data.getvalue()[:40])
            protected = _mixed_content_writer()
            protected.encrypt("secret")
            with encrypted.open("wb") as stream:
                protected.write(stream)
            with zero_page.open("wb") as stream:
                PdfWriter().write(stream)

            for path, expected_status in (
                (empty, 400),
                (corrupt, 422),
                (truncated, 422),
                (encrypted, 422),
                (zero_page, 422),
            ):
                with self.subTest(path=path.name):
                    with self.assertRaises(PdfInputError) as raised:
                        audit_pdf(path)
                    self.assertEqual(raised.exception.status_code, expected_status)

    def test_reports_only_deterministic_source_and_output_results(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            output = root / "output.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)
            result = remediate_pdf(source, output)
            report_path = write_remediation_html(result, root / "result.html")
            document = report_path.read_text(encoding="utf-8")

        self.assertIn("Deterministic remediation run complete", document)
        self.assertIn("Remediation dashboard", document)
        self.assertIn('class="report-nav"', document)
        self.assertIn("WCAG 2.1 Level AA remediation matrix", document)
        self.assertIn("Audit and remediation checkpoints", document)
        self.assertIn("Automated accessibility score", document)
        self.assertIn("Out of scope for automated testing", document)
        self.assertIn("Rationale / techniques", document)
        self.assertIn("PDF18", document)
        self.assertIn("Source SHA-256", document)
        self.assertIn("Verified actions", document)
        self.assertNotIn("Not tested by this application", document)
        self.assertNotIn("Imported checker", document)
        self.assertNotIn("third-party", document.lower())

    def test_audit_page_has_no_external_report_upload(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            report = audit_pdf(source)
            html_path = write_html(report, Path(folder) / "report.html", "/remediate", "token-value", "/new")
            document = html_path.read_text(encoding="utf-8")

        self.assertIn("Yes, apply remediation", document)
        self.assertIn("Audit dashboard", document)
        self.assertIn('class="report-nav"', document)
        self.assertIn("WCAG 2.1 Level AA coverage", document)
        self.assertIn("WCAG automated determination", document)
        self.assertIn("Automated accessibility score", document)
        self.assertIn("Document evidence inventory", document)
        self.assertIn("Rationale / techniques", document)
        self.assertNotIn("Upload remediation JSON file", document)
        self.assertNotIn("upload-remediation", document)
        self.assertIn('href="/new">Home</a>', document)

    def test_deployed_workflow_uses_shared_dashboard_ui(self) -> None:
        self.assertIn("PDF Accessibility Checker and Remediator", UPLOAD_PAGE)
        self.assertIn('class="dropzone"', UPLOAD_PAGE)
        self.assertIn("Run Accessibility Audit", UPLOAD_PAGE)
        self.assertIn("COPY pdf_accessibility_ui.py ./", Path("Dockerfile.azure").read_text(encoding="utf-8"))
        self.assertIn("!pdf_accessibility_ui.py", Path(".dockerignore").read_text(encoding="utf-8"))

    def test_workflow_and_api_accept_pdf_without_report(self) -> None:
        boundary = "pdf-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"pdf\"; filename=\"../sample.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + b"%PDF-1.7\ncontent\n" + f"\r\n--{boundary}--\r\n".encode()
        filename, payload = _parse_pdf_upload(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(filename, "sample.pdf")
        self.assertEqual(payload, b"%PDF-1.7\ncontent\n")

        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            output_name, output = remediate_api_payload(source.name, source.read_bytes())

        self.assertEqual(output_name, "source_remediated.pdf")
        self.assertTrue(output.startswith(b"%PDF-"))
        self.assertNotIn("/Lang", PdfReader(BytesIO(output)).trailer["/Root"])

    def test_upload_errors_and_session_cleanup_are_explicit(self) -> None:
        with self.assertRaises(PdfInputError) as raised:
            _parse_pdf_upload("application/pdf", b"%PDF-1.7")
        self.assertEqual(raised.exception.status_code, 400)

        oversized = BytesIO(b"x" * 12)
        with self.assertRaises(PdfInputError) as raised:
            _read_limited_body(oversized, content_length=12, limit=8)
        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(oversized.tell(), 12)
        self.assertEqual(_read_limited_body(BytesIO(b"12345678"), 8, 8), b"12345678")

        with TemporaryDirectory() as folder:
            owned = Path(folder) / "owned.pdf"
            preserved = Path(folder) / "preserved.pdf"
            owned.write_bytes(b"owned")
            preserved.write_bytes(b"preserved")
            states = {
                "expired-owned": {
                    "last_access": 1.0,
                    "remediated_path": owned,
                    "owns_remediated_path": True,
                },
                "expired-external": {
                    "last_access": 1.0,
                    "remediated_path": preserved,
                    "owns_remediated_path": False,
                },
                "current": {"last_access": 95.0},
            }

            removed = _cleanup_expired_sessions(states, now=100.0, ttl_seconds=10)

            self.assertEqual(removed, 2)
            self.assertFalse(owned.exists())
            self.assertTrue(preserved.exists())
            self.assertEqual(list(states), ["current"])

    def test_corpus_runner_writes_reproducible_json_and_csv(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "inputs"
            outputs = root / "outputs"
            inputs.mkdir()
            with (inputs / "sample.pdf").open("wb") as stream:
                _mixed_content_writer().write(stream)

            result = run_corpus(inputs, outputs)
            saved = json.loads((outputs / "corpus-summary.json").read_text(encoding="utf-8"))

            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["checks"]["audit_repeatable"], "1/1")
            self.assertEqual(result["checks"]["output_sha_equal"], "1/1")
            self.assertTrue(result["git_commit"])
            self.assertIsInstance(result["git_worktree_dirty"], bool)
            self.assertRegex(result["application_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(result["python_version"])
            self.assertTrue(result["pypdf_version"])
            self.assertEqual(result["langdetect_version"], "1.0.9")
            self.assertEqual(result["checker_version"], "2.3.0")
            self.assertEqual(saved["rows"][0]["file"], "sample.pdf")
            self.assertTrue((outputs / "sample.pdf.json").is_file())
            self.assertTrue((outputs / "corpus-summary.csv").is_file())

    def test_api_key_and_attachment_header(self) -> None:
        self.assertTrue(_valid_api_key("", ""))
        self.assertTrue(_valid_api_key("poc-secret", "poc-secret"))
        self.assertFalse(_valid_api_key("poc-secret", "wrong-secret"))
        header = _attachment_header('report"\r\nInjected.pdf')
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("%22%0D%0A", header)


if __name__ == "__main__":
    unittest.main()
