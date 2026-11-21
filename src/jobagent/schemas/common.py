"""Shared serialized contracts used across JobAgent domains."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^sha256:.+")]
# Memory contracts key published memory by person and by job record.
CandidateId = Annotated[str, Field(pattern=r"^CAND_[A-Z0-9_]+$")]
JobId = Annotated[str, Field(pattern=r"^JOB_[A-Z0-9_]+$")]


class ContractModel(BaseModel):
    """Strict base for public, versioned JobAgent contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["1.0"] = "1.0"
