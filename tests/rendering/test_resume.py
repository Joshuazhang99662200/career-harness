# ruff: noqa: RUF001  -- Chinese resume text carries full-width punctuation by design.
from pathlib import Path

import pytest

from jobagent.harness.pdf import check_pdf
from jobagent.rendering.resume import layout, render_docx, render_pdf
from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.resume import ResumeItem
from tests.harness.test_pdf import resume

docx = pytest.importorskip("docx")


def resume_document():  # type: ignore[no-untyped-def]
    def item(item_id: str, section: str, text: str) -> ResumeItem:
        return ResumeItem(id=item_id, section=section, text=text)

    return resume().model_copy(
        update={
            "items": [
                item("ITEM_SUMMARY", "Summary", "Product lead for agent platforms."),
                item("ITEM_ACME_ROLE", "Experience", "Acme | Product Lead | 2025.07 - 2026.09"),
                item(
                    "ITEM_ACME_SKILL", "Experience", "Skill layer: built a skill contract system."
                ),
                item("ITEM_EDU", "Education", "Example University | BEc | 2019.09 - 2021.06"),
            ]
        }
    )


HEADER = ResumeHeader(lines=["Ada Lovelace", "ada@example.com\tShanghai"])


def test_layout_turns_items_into_headings_role_lines_and_bullets() -> None:
    blocks = layout(resume_document(), summary_sections={"Summary"})

    assert [(block.kind, block.text) for block in blocks] == [
        ("heading", "Summary"),
        ("paragraph", "Product lead for agent platforms."),
        ("heading", "Experience"),
        ("role", "Acme | Product Lead | 2025.07 - 2026.09"),
        ("bullet", "Skill layer: built a skill contract system."),
        ("heading", "Education"),
        ("bullet", "Example University | BEc | 2019.09 - 2021.06"),
    ]
    assert blocks[4].lead == "Skill layer:"


def test_rendered_pdf_passes_the_text_gate(tmp_path: Path) -> None:
    document = resume_document()
    path = tmp_path / "resume.pdf"

    render_pdf(document, HEADER, path, font_path=None, summary_sections={"Summary"})

    report = check_pdf(document, path, max_pages=1, header=HEADER)
    assert report.passed, report.issues


def test_rendered_docx_keeps_the_final_text_in_order(tmp_path: Path) -> None:
    document = resume_document()
    path = tmp_path / "resume.docx"

    render_docx(document, HEADER, path, font_name="Arial", summary_sections={"Summary"})

    paragraphs = [p.text for p in docx.Document(str(path)).paragraphs if p.text.strip()]
    assert paragraphs[0] == "Ada Lovelace"
    assert paragraphs[1] == "ada@example.com\tShanghai"
    assert paragraphs[2:] == [
        block.text for block in layout(document, summary_sections={"Summary"})
    ]


def test_cjk_font_bullets_survive_text_extraction(tmp_path: Path) -> None:
    from jobagent.rendering.resume import default_cjk_font

    fonts = default_cjk_font()
    if fonts is None:
        pytest.skip("no CJK font on this machine")
    document = resume().model_copy(
        update={
            "items": [
                ResumeItem(
                    id="ITEM_A_ROLE", section="工作经历", text="某公司｜产品负责人｜2025.07 – 至今"
                ),
                ResumeItem(
                    id="ITEM_A_SKILL", section="工作经历", text="Skill 化底座：把提示词沉淀为模块。"
                ),
            ]
        }
    )
    path = tmp_path / "cjk.pdf"

    render_pdf(document, HEADER, path, font_path=fonts[0], bold_font_path=fonts[1])

    report = check_pdf(document, path, max_pages=1, header=HEADER)
    assert report.passed, report.issues
