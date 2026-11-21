import pytest
from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.schemas.harness import ResumeHeader


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResumeHeader(lines=["Ada Lovelace"], surprise=True)


def test_domain_error_has_stable_code() -> None:
    error = ContractValidationError("The resume file could not be read.")
    assert error.code == "CONTRACT_VALIDATION_ERROR"
