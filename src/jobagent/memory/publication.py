"""Map a PublishedMemory draft onto one production memory table. No model call."""

import json
from collections.abc import Mapping
from typing import Never

from pydantic import JsonValue, ValidationError

from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import PublishedMemory
from jobagent.schemas.shared_memory import (
    GREETING_MEMORY_FIELDS,
    SEARCH_MEMORY_FIELDS,
    StoredMemoryRow,
)


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _reject("Memory publication lists must be strings.")
    return list(value)


def publication_body(values: Mapping[str, object], signal_record_id: str) -> dict[str, object]:
    record_id = values.get("record_id", values.get("job_record_id"))
    return {
        "kind": values.get("kind"),
        "preference": values.get("preference"),
        "candidate_id": values.get("candidate_id"),
        "source_signal_record_id": signal_record_id,
        "source_signal_id": values.get("source_signal_id"),
        "job_record_id": record_id,
        "job_id": values.get("job_id"),
        "reason": values.get("reason"),
        "keywords": _string_list(values.get("keywords", [])),
        "role_directions": _string_list(values.get("role_directions", [])),
        "exclusions": _string_list(values.get("exclusions", [])),
        "notes": _string_list(values.get("notes", [])),
        "jd_digest": values.get("jd_digest"),
    }


def published_memory_id(values: Mapping[str, object], signal_record_id: str) -> str:
    identity = canonical_digest(publication_body(values, signal_record_id))
    return "MEM_" + identity[7:27].upper()


def memory_jd_digest(sources: list[tuple[str, str]]) -> str:
    """Provenance for one published memory. This is not a hash of preferences.

    One source job stores ``text_digest`` of that job's JD text. Several source
    jobs store the canonical digest of each source record and that JD's digest.
    Keywords, role directions and exclusions are not inputs.
    """
    if not sources:
        _reject("JD digest needs at least one source job with JD text.")
    ordered = sorted(sources, key=lambda item: item[0])
    if len({record_id for record_id, _text in ordered}) != len(ordered):
        _reject("JD digest sources must be unique records.")
    for record_id, jd_text in ordered:
        if not record_id or not isinstance(jd_text, str) or not jd_text.strip():
            _reject("JD digest needs the source record and its JD text.")
    if len(ordered) == 1:
        return text_digest(ordered[0][1])
    return canonical_digest({
        "source_context": [
            {"source_record_id": record_id, "jd_digest": text_digest(jd_text)}
            for record_id, jd_text in ordered
        ]
    })


def assert_publishable(memory: PublishedMemory) -> str:
    """Return the production table key. Workflow memory has no table."""
    memory = PublishedMemory.model_validate(memory.model_dump())
    if memory.kind == "workflow":
        _reject("Workflow context has no memory table and is not published.")
    search_fields = bool(memory.keywords or memory.role_directions or memory.exclusions)
    if memory.kind == "search":
        if not search_fields or memory.preference != "Matching Preference / Calibration":
            _reject("Search memory must name a keyword, role direction or exclusion.")
        return "search_memory"
    if memory.kind == "matching":
        if search_fields or not memory.notes:
            _reject("Matching memory cannot change search parameters.")
        if memory.preference != "Matching Preference / Calibration":
            _reject("Matching memory does not match the edited field class.")
        return "search_memory"
    if memory.kind == "greeting":
        if search_fields or not memory.notes:
            _reject("Greeting memory cannot change search parameters.")
        if memory.preference != "Greeting Preference":
            _reject("Greeting memory does not match the edited field class.")
        return "greeting_memory"
    _reject("Workflow context has no memory table and is not published.")


def _json_list(values: list[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _parse_list(value: object) -> list[str]:
    if not isinstance(value, str):
        _reject("Memory list column is not text.")
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ContractValidationError("Memory list column is not valid JSON.") from error
    if not isinstance(loaded, list) or not all(isinstance(item, str) and item for item in loaded):
        _reject("Memory list column must be a JSON array of strings.")
    return list(loaded)


def memory_row_fields(
    memory: PublishedMemory,
    signal_record_id: str,
    *,
    version: str,
    publication_status: str,
    supersedes_version: str | None,
) -> dict[str, JsonValue]:
    memory = PublishedMemory.model_validate(memory.model_dump())
    if published_memory_id(memory.model_dump(), signal_record_id) != memory.memory_id:
        _reject("Memory id does not match the publication body.")
    body = publication_body(memory.model_dump(), signal_record_id)
    body["memory_id"] = memory.memory_id
    shared: dict[str, JsonValue] = {
        "memory_id": memory.memory_id,
        "version": version,
        "publication_status": publication_status,
        "kind": memory.kind,
        "preference": memory.preference,
        "candidate_id": memory.candidate_id,
        "source_signal_record_id": signal_record_id,
        "source_signal_id": memory.source_signal_id,
        "job_record_id": memory.record_id,
        "job_id": memory.job_id,
        "reason": memory.reason,
        "notes": _json_list(list(memory.notes)),
        "jd_digest": memory.jd_digest,
        # Previous version number on this same row. Not a second memory record.
        "supersedes_version": supersedes_version,
        "content_digest": canonical_digest(body),
    }
    if memory.kind == "greeting":
        return shared
    shared["keywords"] = _json_list(list(memory.keywords))
    shared["role_directions"] = _json_list(list(memory.role_directions))
    shared["exclusions"] = _json_list(list(memory.exclusions))
    return shared


def decode_memory_row(
    record_id: str, fields: Mapping[str, JsonValue], *, greeting: bool
) -> StoredMemoryRow:
    required = GREETING_MEMORY_FIELDS if greeting else SEARCH_MEMORY_FIELDS
    if any(name not in fields for name in required):
        _reject("Memory row is missing a semantic column.")
    keywords = [] if greeting else _parse_list(fields["keywords"])
    directions = [] if greeting else _parse_list(fields["role_directions"])
    exclusions = [] if greeting else _parse_list(fields["exclusions"])
    notes = _parse_list(fields["notes"])
    signal_record_id = fields["source_signal_record_id"]
    if not isinstance(signal_record_id, str) or not signal_record_id:
        _reject("Memory row is missing its source signal.")
    draft = {
        "kind": fields["kind"],
        "preference": fields["preference"],
        "candidate_id": fields["candidate_id"],
        "source_signal_id": fields["source_signal_id"],
        "record_id": fields["job_record_id"],
        "job_id": fields["job_id"],
        "reason": fields["reason"],
        "keywords": keywords,
        "role_directions": directions,
        "exclusions": exclusions,
        "notes": notes,
        "jd_digest": fields["jd_digest"],
    }
    memory_id = fields["memory_id"]
    if not isinstance(memory_id, str) or memory_id != published_memory_id(draft, signal_record_id):
        _reject("Memory id does not match the stored publication body.")
    body = publication_body(draft, signal_record_id)
    body["memory_id"] = memory_id
    digest = canonical_digest(body)
    if fields.get("content_digest") != digest:
        _reject("Memory row content digest does not match its columns.")
    try:
        memory = PublishedMemory.model_validate({
            **draft,
            "memory_id": memory_id,
            "source_event_id": signal_record_id,
        })
    except ValidationError as error:
        raise ContractValidationError(
            "Memory row does not match the publication contract."
        ) from error
    try:
        return StoredMemoryRow.model_validate({
            "record_id": record_id,
            "version": fields["version"],
            "publication_status": fields["publication_status"],
            "source_signal_record_id": signal_record_id,
            "memory": memory,
            "body_digest": digest,
        })
    except ValidationError as error:
        raise ContractValidationError("Memory version or publication status is invalid.") from error


def memory_field_names(kind: str) -> tuple[str, ...]:
    if kind == "greeting":
        return GREETING_MEMORY_FIELDS
    return SEARCH_MEMORY_FIELDS
