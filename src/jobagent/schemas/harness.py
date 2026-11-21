"""Contracts for the CV PDF check."""

from typing import Annotated

from pydantic import Field

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString


class ResumeHeader(ContractModel):
    """Identity lines the person supplies for the top of the page.

    Name, contact details and job intent are not claims about experience. They are
    allowed only verbatim and only above the first item, and the report records
    their digest so the exemption stays visible.
    """

    lines: Annotated[list[NonEmptyString], Field(min_length=1)]


class PdfCheckReport(ContractModel):
    resume_id: NonEmptyString
    resume_digest: Digest
    pdf_digest: Digest
    page_count: Annotated[int, Field(ge=0)]
    passed: bool
    issues: list[str] = Field(default_factory=list)
    header_digest: Digest | None = None
