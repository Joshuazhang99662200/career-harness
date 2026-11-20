"""Apply the latest published search memory to one round. Does not fetch."""

from collections.abc import Sequence

from jobagent.errors import ContractValidationError
from jobagent.jobs.search_memory_apply import apply_search_memory
from jobagent.schemas.memory_signal import SearchParameters
from jobagent.schemas.shared_memory import SearchRoundInput, SearchRoundPlan, StoredMemoryRow


def plan_search_round(
    published: Sequence[StoredMemoryRow], round_input: SearchRoundInput
) -> SearchRoundPlan:
    round_input = SearchRoundInput.model_validate(round_input.model_dump())
    rows = [StoredMemoryRow.model_validate(item.model_dump()) for item in published]
    for row in rows:
        if row.publication_status != "published" or row.memory.kind != "search":
            raise ContractValidationError(
                "Search round received memory that is not published search memory."
            )
        if row.memory.candidate_id != round_input.candidate_id:
            raise ContractValidationError("Search memory belongs to another candidate.")
    original = list(round_input.keywords)
    hard_constraints = dict(round_input.hard_constraints)
    if not rows:
        return SearchRoundPlan(
            candidate_id=round_input.candidate_id,
            original_keywords=original,
            keywords=list(original),
            additions=[],
            exclusions=list(round_input.exclusions),
            role_directions=list(round_input.role_directions),
            applied=False,
            hard_constraints=hard_constraints,
            queries_per_site_per_round=round_input.queries_per_site_per_round,
            top_per_query=round_input.top_per_query,
            search_frequency=round_input.search_frequency,
        )
    if len(rows) != 1:
        raise ContractValidationError(
            "More than one published search memory version is current; not applying either."
        )
    row = rows[0]
    applied = apply_search_memory(
        SearchParameters(
            keywords=list(original),
            role_directions=list(round_input.role_directions),
            exclusions=list(round_input.exclusions),
        ),
        [row.memory],
        candidate_id=round_input.candidate_id,
    )
    additions = [
        change.value
        for change in applied.changes
        if change.op == "add" and change.parameter == "keywords"
    ]
    return SearchRoundPlan(
        candidate_id=round_input.candidate_id,
        memory_version=row.version,
        memory_record_id=row.record_id,
        source_signal_record_id=row.source_signal_record_id,
        original_keywords=original,
        keywords=list(applied.after.keywords),
        additions=additions,
        exclusions=list(applied.after.exclusions),
        role_directions=list(applied.after.role_directions),
        applied=True,
        hard_constraints=hard_constraints,
        queries_per_site_per_round=round_input.queries_per_site_per_round,
        top_per_query=round_input.top_per_query,
        search_frequency=round_input.search_frequency,
    )
