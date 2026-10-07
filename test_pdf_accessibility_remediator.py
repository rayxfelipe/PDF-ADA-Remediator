from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from pdf_accessibility_audit import ACROBAT_RULE_IDS, audit_pdf, read_json, write_html, write_json
from pdf_accessibility_remediator import remediate_pdf, write_remediation_html
from pdf_accessibility_workflow import (
    UPLOAD_PAGE,
    _attachment_header,
    _parse_pdf_upload,
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
    def test_audit_is_versioned_hash_bound_and_repeatable(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)

            first = audit_pdf(source)
            second = audit_pdf(source)

        self.assertEqual(first.schema_version, 3)
        self.assertEqual(first.checker_version, "2.0.0")
        self.assertEqual(first.ruleset_version, "2026.10")
        self.assertEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(first.findings, second.findings)
        self.assertEqual(tuple(item.check_id for item in first.findings), ACROBAT_RULE_IDS)

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

        self.assertEqual(loaded.source_sha256, original.source_sha256)

    def test_remediation_uses_local_audit_and_verifies_language(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            output = root / "output.pdf"
            with source.open("wb") as stream:
                _mixed_content_writer().write(stream)

            result = remediate_pdf(source, output)
            remediated = PdfReader(output)

        self.assertEqual(remediated.trailer["/Root"]["/Lang"], "en-US")
        self.assertNotEqual(result.source_sha256, result.output_sha256)
        action = next(item for item in result.actions if item.action_id == "set-document-language")
        self.assertEqual(action.result, "verified")
        language = next(item for item in result.items if item.check_id == "ACR-DOC-005")
        self.assertEqual(language.status, "success")

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

        self.assertIn("Deterministic remediation complete", document)
        self.assertIn("Remediation dashboard", document)
        self.assertIn('class="report-nav"', document)
        self.assertIn("Source SHA-256", document)
        self.assertIn("Verified actions", document)
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
        self.assertEqual(PdfReader(BytesIO(output)).trailer["/Root"]["/Lang"], "en-US")

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
