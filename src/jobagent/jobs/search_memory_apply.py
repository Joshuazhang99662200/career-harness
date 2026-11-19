"""Apply published search memory to the next round's search parameters.

Greeting and workflow memories are reported and left unused. Nothing here
searches, writes a shared table, or sends.
"""

from collections.abc import Sequence
from typing import Literal

from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import (
    AppliedSearchParameters,
    PublishedMemory,
    SearchParameterChange,
    SearchParameters,
)

ParameterName = Literal["keywords", "role_directions", "exclusions"]


def _append(
    values: list[str],
    additions: Sequence[str],
    *,
    parameter: ParameterName,
    memory: PublishedMemory,
    changes: list[SearchParameterChange],
) -> None:
    for value in additions:
        if value in values:
            continue
        values.append(value)
        changes.append(
            SearchParameterChange(
                op="add",
                parameter=parameter,
                value=value,
                memory_id=memory.memory_id,
                source_event_id=memory.source_event_id,
                job_id=memory.job_id,
                reason=memory.reason,
            )
        )


def apply_search_memory(
    base: SearchParameters,
    memories: Sequence[PublishedMemory],
    *,
    candidate_id: str,
) -> AppliedSearchParameters:
    base = SearchParameters.model_validate(base.model_dump())
    keywords = list(base.keywords)
    directions = list(base.role_directions)
    exclusions = list(base.exclusions)
    changes: list[SearchParameterChange] = []
    ignored: list[str] = []
    for memory in memories:
        memory = PublishedMemory.model_validate(memory.model_dump())
        if memory.candidate_id != candidate_id:
            raise ContractValidationError("Search memory belongs to another candidate.")
        if memory.kind != "search":
            ignored.append(memory.memory_id)
            continue
        _append(keywords, memory.keywords, parameter="keywords", memory=memory, changes=changes)
        _append(
            directions,
            memory.role_directions,
            parameter="role_directions",
            memory=memory,
            changes=changes,
        )
        _append(
            exclusions, memory.exclusions, parameter="exclusions", memory=memory, changes=changes
        )
        for excluded in memory.exclusions:
            if excluded not in keywords:
                continue
            keywords.remove(excluded)
            changes.append(
                SearchParameterChange(
                    op="remove",
                    parameter="keywords",
                    value=excluded,
                    memory_id=memory.memory_id,
                    source_event_id=memory.source_event_id,
                    job_id=memory.job_id,
                    reason=memory.reason,
                )
            )
    if not keywords:
        raise ContractValidationError("Search memory removed every keyword; keep a base term.")
    return AppliedSearchParameters(
        candidate_id=candidate_id,
        before=base,
        after=SearchParameters(
            keywords=keywords, role_directions=directions, exclusions=exclusions
        ),
        changes=changes,
        ignored_memory_ids=ignored,
    )
