"""CLI for the CV PDF: render the final CV text and check the PDF text."""

import json
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.harness.pdf import check_pdf
from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.resume import ResumeDocument

harness_app = typer.Typer(help="Render a CV PDF and check that its text matches the final CV text.")


def _fail(error: JobAgentError | ValidationError) -> Never:
    message = error.message if isinstance(error, JobAgentError) else "Invalid run contract."
    typer.echo(json.dumps({"error": {"message": message}}))
    raise typer.Exit(1)


@harness_app.command("check-pdf")
def check_pdf_command(
    resume_path: Path,
    pdf_path: Path,
    max_pages: Annotated[int, typer.Option("--max-pages", min=1)] = 2,
    header_path: Annotated[
        Path | None,
        typer.Option("--header", help="JSON {lines: [...]} allowed verbatim above the items."),
    ] = None,
) -> None:
    try:
        resume = ResumeDocument.model_validate_json(resume_path.read_bytes())
        header = (
            None
            if header_path is None
            else ResumeHeader.model_validate_json(header_path.read_bytes())
        )
        report = check_pdf(resume, pdf_path, max_pages=max_pages, header=header)
        typer.echo(report.model_dump_json(indent=2))
        if not report.passed:
            raise typer.Exit(1)
    except (JobAgentError, ValidationError) as error:
        _fail(error)
    except OSError:
        typer.echo(json.dumps({"error": {"message": "Resume file unavailable."}}))
        raise typer.Exit(1) from None


@harness_app.command("render")
def render(
    resume_path: Annotated[Path, typer.Argument(help="Final ResumeDocument JSON.")],
    header_path: Annotated[Path, typer.Argument(help='ResumeHeader JSON: {"lines": [...]}.')],
    pdf: Annotated[Path | None, typer.Option("--pdf", help="Where to write the PDF.")] = None,
    docx: Annotated[
        Path | None, typer.Option("--docx", help="Where to write the Word file.")
    ] = None,
    font: Annotated[
        str | None,
        typer.Option("--font", help="A TTF/TTC path; 'none' for Helvetica; default: a CJK font."),
    ] = None,
    bold_font: Annotated[str | None, typer.Option("--bold-font")] = None,
    word_font: Annotated[str, typer.Option("--word-font")] = "DengXian",
    summary_section: Annotated[
        list[str] | None, typer.Option("--summary-section", help="Sections set as paragraphs.")
    ] = None,
    max_pages: Annotated[int, typer.Option("--max-pages", min=1)] = 1,
) -> None:
    """Lay out the final CV text as PDF and/or Word, then run the PDF text gate.

    Layout only: every visible line is a header line or verbatim item text. A Word
    file cannot be checked directly; export it to PDF and run `harness check-pdf`.
    """
    from jobagent.rendering.resume import (
        DEFAULT_SUMMARY_SECTIONS,
        default_cjk_font,
        render_docx,
        render_pdf,
    )
    try:
        if pdf is None and docx is None:
            raise ContractValidationError("Choose at least one output: --pdf or --docx.")
        try:
            resume = ResumeDocument.model_validate_json(resume_path.read_bytes())
            header = ResumeHeader.model_validate_json(header_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The resume or header file could not be read.",
                details={"resume": resume_path.name, "header": header_path.name},
            ) from None
        sections = set(summary_section) if summary_section else DEFAULT_SUMMARY_SECTIONS
        result: dict[str, object] = {"resume_id": resume.id}
        if pdf is not None:
            regular, bold = font, bold_font
            if font is None:
                found = default_cjk_font()
                if found is None:
                    raise ContractValidationError(
                        "No CJK font was found; pass --font with a TTF/TTC path."
                    )
                regular, bold = found
            elif font.lower() == "none":
                regular, bold = None, None
            render_pdf(
                resume,
                header,
                pdf,
                font_path=regular,
                bold_font_path=bold,
                summary_sections=sections,
            )
            report = check_pdf(resume, pdf, max_pages=max_pages, header=header)
            result.update({"pdf": str(pdf), "check": report.model_dump(mode="json")})
        if docx is not None:
            render_docx(resume, header, docx, font_name=word_font, summary_sections=sections)
            result["docx"] = str(docx)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        check = result.get("check")
        if isinstance(check, dict) and not check.get("passed"):
            raise typer.Exit(code=1)
    except JobAgentError as error:
        _fail(error)
