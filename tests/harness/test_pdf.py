import pytest
from pydantic import ValidationError
from reportlab.pdfgen import canvas

from jobagent.harness.pdf import check_pdf
from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.resume import ResumeDocument, ResumeItem


def resume() -> ResumeDocument:
    return ResumeDocument(
        id="RESUME_1",
        items=[ResumeItem(id="ITEM_1", section="experience", text="Led a platform migration.")],
    )


def render(path, text, *, pages=1):
    pdf = canvas.Canvas(str(path))
    pdf.drawString(50, 700, text)
    for _ in range(pages - 1):
        pdf.showPage()
        pdf.drawString(50, 700, "extra page")
    pdf.save()


def test_resume_document_carries_only_final_text_without_a_fact_ledger() -> None:
    assert set(ResumeItem.model_fields) == {"schema_version", "id", "section", "text"}
    assert set(ResumeDocument.model_fields) == {"schema_version", "id", "items"}
    with pytest.raises(ValidationError):
        ResumeDocument(id="RESUME_1", items=[])


def test_pdf_requires_all_final_text_and_rejects_extra_claims(tmp_path):
    path = tmp_path / "resume.pdf"
    document = resume()
    render(path, document.items[0].text)
    report = check_pdf(document, path)
    assert report.passed
    assert report.resume_id == "RESUME_1"
    render(path, "Managed 900 engineers.")
    assert not check_pdf(document, path).passed
    render(path, document.items[0].text + " Invented new growth.")
    assert not check_pdf(document, path).passed


def test_pdf_limits_pages(tmp_path):
    path = tmp_path / "resume.pdf"
    document = resume()
    render(path, document.items[0].text, pages=3)
    assert "page_limit" in check_pdf(document, path, max_pages=2).issues


def test_pdf_rejects_reordered_text_and_unreadable_file(tmp_path):
    path = tmp_path / "resume.pdf"
    document = resume()
    document.items.append(
        document.items[0].model_copy(update={"id": "ITEM_2", "text": "Built a Python service."})
    )
    render(path, document.items[1].text + " " + document.items[0].text)
    assert not check_pdf(document, path).passed
    path.write_bytes(b"invalid PDF")
    assert "unreadable_pdf" in check_pdf(document, path).issues


def render_lines(path, lines):
    pdf = canvas.Canvas(str(path))
    y = 760
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 20
    pdf.save()


def test_pdf_header_lines_are_allowed_only_verbatim_at_the_top(tmp_path):
    path = tmp_path / "resume.pdf"
    document = resume()
    header = ResumeHeader(lines=["Ada Lovelace", "ada@example.com | Engineer"])
    body = document.items[0].text

    render_lines(path, [*header.lines, body])
    report = check_pdf(document, path, header=header)
    assert report.passed
    assert report.header_digest is not None and report.header_digest.startswith("sha256:")

    assert "unapproved_or_extra_text" in check_pdf(document, path).issues
    render_lines(path, [body, *header.lines])
    assert not check_pdf(document, path, header=header).passed
    render_lines(path, ["Ada Lovelace", "ada@example.com | Staff Engineer", body])
    assert not check_pdf(document, path, header=header).passed


def test_pdf_allows_bullet_glyphs_but_no_other_decoration(tmp_path):
    path = tmp_path / "resume.pdf"
    document = resume()
    render(path, "· " + document.items[0].text)
    assert check_pdf(document, path).passed
    render(path, "NEW " + document.items[0].text)
    assert not check_pdf(document, path).passed
