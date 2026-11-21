
import pytest
from docx import Document
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from reportlab.pdfgen import canvas

from jobagent.harness.pdf import check_pdf
from tests.harness.test_pdf import render, variant


def test_pdf_rejects_internal_note_even_if_it_was_in_verified_text(tmp_path):
    document = variant()
    document.items[0].text = "Internal note: source needs owner confirmation."
    path = tmp_path / "resume.pdf"
    render(path, document.items[0].text)
    assert "internal_annotation" in check_pdf(document, path).issues


@pytest.mark.parametrize("extra", ["annotation", "attachment", "metadata"])
def test_pdf_rejects_non_employer_review_payload(tmp_path, extra):
    document = variant()
    path = tmp_path / "resume.pdf"
    render(path, document.items[0].text)
    writer = PdfWriter(clone_from=PdfReader(path))
    if extra == "annotation":
        writer.add_annotation(0, Text(rect=(10, 10, 100, 100), text="Reviewer comment"))
    elif extra == "attachment":
        writer.add_attachment("notes.txt", b"Private review notes")
    else:
        writer.add_metadata({"/Subject": "Internal note: private review context"})
    with path.open("wb") as output:
        writer.write(output)
    assert not check_pdf(document, path).passed


def test_pdf_preserves_normal_hyperlinks(tmp_path):
    document = variant()
    path = tmp_path / "resume.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(50, 700, document.items[0].text)
    pdf.linkURL("https://example.com", (50, 695, 200, 710))
    pdf.save()
    assert check_pdf(document, path).passed


def test_internal_software_name_is_not_a_review_annotation(tmp_path):
    document = variant()
    document.items[0].text = "Built an internal note-taking tool for research teams."
    path = tmp_path / "resume.pdf"
    render(path, document.items[0].text)
    assert check_pdf(document, path).passed


def test_pdf_link_cannot_hide_javascript_action(tmp_path):
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    document = variant()
    path = tmp_path / "resume.pdf"
    render(path, document.items[0].text)
    writer = PdfWriter(clone_from=PdfReader(path))
    annotation = {
        "/Type": "/Annot",
        "/Subtype": "/Link",
        "/Rect": [10, 10, 100, 100],
        "/A": DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("console.println('synthetic');"),
            }
        ),
    }
    writer.add_annotation(0, annotation)
    with path.open("wb") as output:
        writer.write(output)
    assert "pdf_active_content" in check_pdf(document, path).issues


def test_pdf_xmp_metadata_cannot_carry_internal_notes(tmp_path):
    from pypdf.generic import DecodedStreamObject, NameObject

    document = variant()
    path = tmp_path / "resume.pdf"
    render(path, document.items[0].text)
    writer = PdfWriter(clone_from=PdfReader(path))
    metadata = DecodedStreamObject()
    metadata.set_data(b"<metadata>Internal note: private review context</metadata>")
    metadata.update({NameObject("/Type"): NameObject("/Metadata")})
    writer.root_object[NameObject("/Metadata")] = metadata
    with path.open("wb") as output:
        writer.write(output)
    assert "internal_annotation" in check_pdf(document, path).issues


def _docx(path, text):
    document = Document()
    document.add_paragraph(text)
    document.save(path)
