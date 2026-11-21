"""Stable failures shared by the remaining JobAgent commands."""

from collections.abc import Mapping
from typing import Any, ClassVar


class JobAgentError(Exception):
    """Base error with a machine-readable code and structured details."""

    code: ClassVar[str] = "JOBAGENT_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class ContractValidationError(JobAgentError):
    code = "CONTRACT_VALIDATION_ERROR"
