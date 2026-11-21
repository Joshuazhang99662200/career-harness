"""The final CV text the PDF check compares against.

GM writes this from the materials md and the original CV. Whether the content is
true is settled in the Bitable: the person approves or rejects it, and Dream
learns from the trace. This contract only fixes the text and its order.
"""

from typing import Annotated

from pydantic import Field

from jobagent.schemas.common import ContractModel, NonEmptyString

ResumeItemId = Annotated[str, Field(pattern=r"^ITEM_[A-Z0-9_]+$")]
ResumeId = Annotated[str, Field(pattern=r"^RESUME_[A-Z0-9_]+$")]


class ResumeItem(ContractModel):
    id: ResumeItemId
    section: NonEmptyString
    text: NonEmptyString


class ResumeDocument(ContractModel):
    id: ResumeId
    items: Annotated[list[ResumeItem], Field(min_length=1)]
