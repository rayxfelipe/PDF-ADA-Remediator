from io import BytesIO
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from pdf_accessibility_remediator import _tag_image_only_document


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


class ImageOnlyTaggingTests(unittest.TestCase):
    def test_adds_persisted_structure_and_marked_content(self) -> None:
        writer = _image_only_writer()

        self.assertTrue(_tag_image_only_document(writer))

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

        self.assertFalse(_tag_image_only_document(writer))
        self.assertIsNone(writer._root_object.get("/StructTreeRoot"))


if __name__ == "__main__":
    unittest.main()