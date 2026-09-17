from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from pdf_accessibility_audit import ACROBAT_RULE_IDS, audit_pdf, read_json, write_json
from pdf_accessibility_remediator import _tag_untagged_document, remediate_from_json


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


class ImageOnlyTaggingTests(unittest.TestCase):
    def test_adds_persisted_structure_and_marked_content(self) -> None:
        writer = _image_only_writer()

        self.assertTrue(_tag_untagged_document(writer))

        output = BytesIO()
        writer.write(output)
        output.seek(0)
        reader = PdfReader(output)
        root = reader.trailer["/Root"].get_object()
        structure_root = root["/StructTreeRoot"].get_object()
        document = structure_root["/K"].get_object()
        figure = document["/K"][0].get_object()
        page = reader.pages[0]
        operations = ContentStream(page.get_contents(), reader).operations

        self.assertTrue(root["/MarkInfo"]["/Marked"])
        self.assertEqual(document["/S"], "/Document")
        self.assertEqual(figure["/S"], "/Figure")
        self.assertEqual(figure["/K"], 0)
        self.assertEqual(page["/StructParents"], 0)
        self.assertEqual(page["/Tabs"], "/S")
        self.assertEqual(structure_root["/ParentTree"].get_object()["/Nums"][0], 0)
        self.assertEqual(operations[0][1], b"BDC")
        self.assertEqual(operations[-1][1], b"EMC")

    def test_does_not_tag_pages_without_images(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)

        self.assertFalse(_tag_untagged_document(writer))
        self.assertIsNone(writer._root_object.get("/StructTreeRoot"))

    def test_tags_mixed_text_and_images_and_artifacts_layout(self) -> None:
        writer = _mixed_content_writer()

        self.assertTrue(_tag_untagged_document(writer))

        output = BytesIO()
        writer.write(output)
        output.seek(0)
        reader = PdfReader(output)
        root = reader.trailer["/Root"].get_object()
        structure_root = root["/StructTreeRoot"].get_object()
        document = structure_root["/K"].get_object()
        roles = [element.get_object()["/S"] for element in document["/K"]]
        parents = structure_root["/ParentTree"].get_object()["/Nums"][1]
        operations = ContentStream(reader.pages[0].get_contents(), reader).operations
        mcids = [int(operands[1]["/MCID"]) for operands, operator in operations if operator == b"BDC"]

        self.assertEqual(roles, ["/P", "/Figure"])
        self.assertEqual(len(parents), 2)
        self.assertEqual(mcids, [0, 1])
        self.assertIn(([NameObject("/Artifact")], b"BMC"), operations)
        self.assertIn("Accessible text", reader.pages[0].extract_text())

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
        self.assertEqual(statuses["ACR-DOC-003"], "success")
        self.assertEqual(statuses["ACR-DOC-005"], "success")
        self.assertEqual(statuses["ACR-DOC-006"], "success")
        self.assertEqual(statuses["ACR-PAGE-001"], "success")
        self.assertEqual(statuses["ACR-PAGE-003"], "success")
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


if __name__ == "__main__":
    unittest.main()