from io import BytesIO
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from pdf_accessibility_audit import ACROBAT_RULE_IDS, audit_pdf, read_json, write_html, write_json
from pdf_accessibility_remediator import remediate_from_json
from pdf_accessibility_workflow import (
    MAX_REMEDIATION_JSON_BYTES,
    _parse_api_remediation_upload,
    _parse_pdf_upload,
    _parse_remediation_upload,
    _attachment_header,
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


class AccessibilityRemediationTests(unittest.TestCase):
    def test_audit_and_remediation_cover_every_acrobat_rule(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "mixed.pdf"
            writer = _mixed_content_writer()
            with source.open("wb") as stream:
                writer.write(stream)

            before = audit_pdf(source)
            audit_path = write_json(before, root / "accessibility-report-mixed.json")
            result = remediate_from_json(audit_path, root / "mixed-remediated.pdf", source_pdf=source)

        self.assertEqual(tuple(item.check_id for item in before.findings), ACROBAT_RULE_IDS)
        self.assertEqual(len(result.items), len(ACROBAT_RULE_IDS))
        self.assertEqual(len(result.after_audit.findings), len(ACROBAT_RULE_IDS))
        statuses = {item.check_id: item.status for item in result.items}
        self.assertEqual(statuses["ACR-DOC-003"], "failed")
        self.assertEqual(statuses["ACR-DOC-005"], "success")
        self.assertEqual(statuses["ACR-DOC-006"], "failed")
        self.assertEqual(statuses["ACR-PAGE-001"], "failed")
        self.assertEqual(statuses["ACR-PAGE-003"], "failed")
        self.assertEqual(statuses["ACR-PAGE-004"], "manual")
        self.assertEqual(statuses["ACR-ALT-001"], "failed")

    def test_converts_external_markdown_report(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "external.pdf"
            writer = _image_only_writer()
            with source.open("wb") as stream:
                writer.write(stream)
            canonical = audit_pdf(source)
            rows = ["| Rule | Severity | Status |", "|---|---|---|"]
            for finding in canonical.findings:
                status = "Needs manual check" if finding.status == "manual" else "Failed" if finding.status == "fail" else "Passed"
                rows.append(f"| {finding.requirement} | Major | {status} |")
            rows.extend([
                "### Failures table",
                "| Rule | Severity | Pages | Count | Tag path/object | WCAG / Best Practice | Remediation |",
                "|---|---|---:|---:|---|---|---|",
                "| Primary language (/Lang on Catalog) | Critical | All | 1 | Catalog /Lang | WCAG 3.1.1 | Set /Lang to en-US. |",
            ])
            report_path = root / "external-report.json"
            report_path.write_text(json.dumps({
                "fileName": source.name,
                "remediationReport": "**File name:** external.pdf - 1 page\n\n" + "\n".join(rows),
            }), encoding="utf-8")

            converted = read_json(report_path)

        self.assertEqual(tuple(item.check_id for item in converted.findings), ACROBAT_RULE_IDS)
        self.assertEqual(converted.page_count, 1)
        language = next(item for item in converted.findings if item.check_id == "ACR-DOC-005")
        self.assertEqual(language.status, "fail")
        self.assertEqual(language.remediation, "Set /Lang to en-US.")

    def test_converts_id_prefixed_bullet_summary_rows(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "external.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            canonical = audit_pdf(source)
            rows = []
            for finding in canonical.findings:
                status = "Needs manual check" if finding.status == "manual" else "Failed" if finding.status == "fail" else "Passed"
                rows.append(f"- D1 {finding.requirement} | Major | {status}")
            report_path = root / "external-report.json"
            report_path.write_text(json.dumps({
                "fileName": source.name,
                "remediationReport": "\n".join(rows),
            }), encoding="utf-8")

            converted = read_json(report_path)

        self.assertEqual(tuple(item.check_id for item in converted.findings), ACROBAT_RULE_IDS)

    def test_converts_em_dash_summary_rows_with_status_qualifiers(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "external.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            canonical = audit_pdf(source)
            rows = []
            for index, finding in enumerate(canonical.findings, start=1):
                status = "Needs manual check" if finding.status == "manual" else "Failed" if finding.status == "fail" else "Passed"
                qualifier = " [inferred - Tier B]" if status == "Failed" else ""
                rows.append(f"- D{index} {finding.requirement} — Major — {status}{qualifier}")
            report_path = root / "external-report.json"
            report_path.write_text(json.dumps({
                "fileName": source.name,
                "remediationReport": "\n".join(rows),
            }), encoding="utf-8")

            converted = read_json(report_path)

        self.assertEqual(tuple(item.check_id for item in converted.findings), ACROBAT_RULE_IDS)

    def test_preserves_additional_rules_ranges_and_manual_queue(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "external.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            canonical = audit_pdf(source)
            rows = ["| Rule | Severity | Status |", "|---|---|---|"]
            for finding in canonical.findings:
                status = "Needs manual check" if finding.status == "manual" else "Failed" if finding.status == "fail" else "Passed"
                rows.append(f"| {finding.requirement} | Major | {status} |")
            rows.extend([
                "| Language of Parts | Critical | Failed |",
                "",
                "### Failures table",
                "| Rule | Severity | Pages | Count | Tag path/object | WCAG / Best Practice | Remediation |",
                "|---|---|---:|---:|---|---|---|",
                "| Language of Parts | Critical | 1, 3-5 | 4 | Structure spans | **REQUIRED — WCAG 3.1.2** | Mark language changes. |",
                "",
                "### Manual Verification Queue",
                "1. **Assistive technology:** Verify language changes are announced.",
            ])
            report_path = root / "external-report.json"
            report_path.write_text(json.dumps({
                "fileName": source.name,
                "remediationReport": (
                    "**Overall Status:** CONFORMANCE NOT ESTABLISHED.\n\n"
                    "**Standards Applied:** WCAG 2.1 A and AA.\n\n"
                    + "\n".join(rows)
                ),
            }), encoding="utf-8")

            converted = read_json(report_path)

        additional = next(item for item in converted.findings if item.requirement == "Language of Parts")
        self.assertEqual(additional.check_id, "EXT-LANGUAGE-OF-PARTS")
        self.assertEqual(additional.pages, [1, 3, 4, 5])
        self.assertEqual(additional.source_severity, "Critical")
        self.assertEqual(additional.source_requirement, "REQUIRED — WCAG 3.1.2")
        self.assertEqual(len(converted.findings), len(ACROBAT_RULE_IDS) + 1)
        self.assertIn("CONFORMANCE NOT ESTABLISHED", converted.source_notes[0])
        self.assertEqual(converted.manual_tasks, ["Assistive technology: Verify language changes are announced."])

    def test_report_includes_external_remediation_upload(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            report = audit_pdf(source)
            html_path = write_html(report, Path(folder) / "report.html", "/remediate", "token-value", "/upload-remediation", "/new")
            document = html_path.read_text(encoding="utf-8")

        self.assertIn("Yes, apply remediation", document)
        self.assertIn("Upload remediation JSON file", document)
        self.assertIn('action="/upload-remediation"', document)
        self.assertIn('enctype="multipart/form-data"', document)
        self.assertIn('href="/new">Home</a>', document)

    def test_workflow_parses_pdf_upload_in_memory(self) -> None:
        boundary = "pdf-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"pdf\"; filename=\"../sample.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + b"%PDF-1.7\ncontent\n" + f"\r\n--{boundary}--\r\n".encode("utf-8")

        filename, payload = _parse_pdf_upload(f"multipart/form-data; boundary={boundary}", body)

        self.assertEqual(filename, "sample.pdf")
        self.assertEqual(payload, b"%PDF-1.7\ncontent\n")

    def test_parses_remediation_upload_in_memory(self) -> None:
        boundary = "test-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"token\"\r\n\r\ntoken-value\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"remediation_json\"; filename=\"..\\external.json\"\r\n"
            "Content-Type: application/json\r\n\r\n"
            "{\"findings\": []}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        token, filename, payload = _parse_remediation_upload(f"multipart/form-data; boundary={boundary}", body)

        self.assertEqual(token, "token-value")
        self.assertEqual(filename, "external.json")
        self.assertEqual(payload, b'{"findings": []}')

    def test_rejects_remediation_payload_over_exact_limit(self) -> None:
        boundary = "large-report"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"token\"\r\n\r\ntoken-value\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"remediation_json\"; filename=\"report.json\"\r\n"
            "Content-Type: application/json\r\n\r\n"
        ).encode() + (b"x" * (MAX_REMEDIATION_JSON_BYTES + 1)) + f"\r\n--{boundary}--\r\n".encode()

        with self.assertRaisesRegex(ValueError, "exceeds"):
            _parse_remediation_upload(f"multipart/form-data; boundary={boundary}", body)

    def test_api_remediates_matching_pdf_and_report_without_persisting(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            report = audit_pdf(source)
            report_path = write_json(report, Path(folder) / "audit.json")

            output_name, output = remediate_api_payload(
                source.name,
                source.read_bytes(),
                report_path.read_bytes(),
            )

        self.assertEqual(output_name, "source_remediated.pdf")
        self.assertTrue(output.startswith(b"%PDF-"))
        self.assertEqual(PdfReader(BytesIO(output)).trailer["/Root"]["/Lang"], "en-US")

    def test_preserves_meaningful_title_and_enables_title_display(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "250471000001745.pdf"
            writer = _mixed_content_writer()
            writer.add_metadata({"/Title": "Permit Instructions"})
            with source.open("wb") as stream:
                writer.write(stream)
            report_path = write_json(audit_pdf(source), root / "audit.json")
            output = root / "output.pdf"

            result = remediate_from_json(report_path, output, source_pdf=source)
            remediated = PdfReader(output)

        self.assertEqual(remediated.metadata.title, "Permit Instructions")
        self.assertTrue(remediated.trailer["/Root"]["/ViewerPreferences"]["/DisplayDocTitle"])
        title_item = next(item for item in result.items if item.check_id == "ACR-DOC-006")
        self.assertEqual(title_item.status, "success")

    def test_does_not_invent_title_or_semantic_tags(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "250471000001745.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)
            report_path = write_json(audit_pdf(source), root / "audit.json")
            output = root / "output.pdf"

            result = remediate_from_json(report_path, output, source_pdf=source)
            remediated = PdfReader(output)

        self.assertFalse(remediated.metadata.title)
        self.assertNotIn("/StructTreeRoot", remediated.trailer["/Root"])
        statuses = {item.check_id: item.status for item in result.items}
        self.assertEqual(statuses["ACR-DOC-003"], "failed")
        self.assertEqual(statuses["ACR-DOC-006"], "failed")

    def test_uses_same_local_basis_for_before_and_after_scores(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)
            local_before = audit_pdf(source)
            imported_findings = [
                replace(item, status="fail") if item.check_id == "ACR-PAGE-004" else item
                for item in local_before.findings
            ]
            imported = replace(local_before, score=30, findings=imported_findings)
            report_path = write_json(imported, root / "audit.json")

            result = remediate_from_json(report_path, root / "output.pdf", source_pdf=source)

        self.assertEqual(result.source_score, 30)
        self.assertEqual(result.before_score, local_before.score)
        encoding = next(item for item in result.items if item.check_id == "ACR-PAGE-004")
        self.assertEqual(encoding.status, "manual")

    def test_empty_structure_tree_does_not_pass_tagging(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "empty-structure.pdf"
            writer = _mixed_content_writer()
            writer._root_object[NameObject("/MarkInfo")] = DictionaryObject({
                NameObject("/Marked"): BooleanObject(True),
            })
            writer._root_object[NameObject("/StructTreeRoot")] = writer._add_object(DictionaryObject({
                NameObject("/Type"): NameObject("/StructTreeRoot"),
                NameObject("/ParentTree"): writer._add_object(DictionaryObject()),
            }))
            with source.open("wb") as stream:
                writer.write(stream)

            report = audit_pdf(source)

        statuses = {item.check_id: item.status for item in report.findings}
        self.assertEqual(statuses["ACR-DOC-003"], "fail")
        self.assertEqual(statuses["ACR-PAGE-001"], "fail")

    def test_api_rejects_report_for_different_pdf(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _image_only_writer().write(stream)
            report = replace(audit_pdf(source), file="different.pdf")
            report_path = write_json(report, Path(folder) / "audit.json")

            with self.assertRaisesRegex(ValueError, "does not match"):
                remediate_api_payload(source.name, source.read_bytes(), report_path.read_bytes())

    def test_parses_api_remediation_multipart(self) -> None:
        boundary = "api-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"source.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode() + b"%PDF-1.7\ncontent\n" + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"remediation_report\"; filename=\"report.json\"\r\n"
            "Content-Type: application/json\r\n\r\n"
            '{"fileName":"source.pdf","remediationReport":"report"}'
            f"\r\n--{boundary}--\r\n"
        ).encode()

        filename, pdf, report = _parse_api_remediation_upload(
            f"multipart/form-data; boundary={boundary}", body
        )

        self.assertEqual(filename, "source.pdf")
        self.assertEqual(pdf, b"%PDF-1.7\ncontent\n")
        self.assertIn(b'"fileName":"source.pdf"', report)

    def test_api_rejects_duplicate_multipart_fields(self) -> None:
        boundary = "duplicate-boundary"
        file_part = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"source.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n%PDF-1.7\n"
        )
        report_part = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"remediation_report\"\r\n\r\n{{}}\r\n"
        )
        body = (file_part + "\r\n" + file_part + "\r\n" + report_part + f"--{boundary}--\r\n").encode()

        with self.assertRaisesRegex(ValueError, "one PDF"):
            _parse_api_remediation_upload(f"multipart/form-data; boundary={boundary}", body)

    def test_api_key_is_optional_but_enforced_when_configured(self) -> None:
        self.assertTrue(_valid_api_key("", ""))
        self.assertTrue(_valid_api_key("poc-secret", "poc-secret"))
        self.assertFalse(_valid_api_key("poc-secret", "wrong-secret"))

    def test_attachment_header_encodes_untrusted_filename(self) -> None:
        header = _attachment_header('report"\r\nInjected.pdf')

        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("%22%0D%0A", header)


if __name__ == "__main__":
    unittest.main()