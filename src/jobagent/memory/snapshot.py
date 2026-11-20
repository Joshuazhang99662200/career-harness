"""Fold caller-supplied preference deltas into one complete search snapshot.

No model call. A newer delta replaces the preference it names. Exclusions
and keywords are not both kept for the same term.
"""

import json

from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import PublishedMemory
from jobagent.schemas.shared_memory import SignalPreferenceDelta


def _reject(message: str) -> None:
    raise ContractValidationError(message)


def encode_source_signal_ids(signal_ids: list[str]) -> str:
    if len(signal_ids) == 1:
        return signal_ids[0]
    return json.dumps(signal_ids, ensure_ascii=False, separators=(",", ":"))


def decode_source_signal_ids(value: str) -> list[str]:
    if not value.startswith("["):
        return [value]
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ContractValidationError("Memory source_signal_id is not a signal id list.") from error
    if (
        not isinstance(loaded, list)
        or not loaded
        or not all(isinstance(item, str) and item for item in loaded)
    ):
        _reject("Memory source_signal_id is not a signal id list.")
    return list(loaded)


def fold_search_snapshot(
    previous: PublishedMemory | None, deltas: list[SignalPreferenceDelta]
) -> tuple[list[str], list[str], list[str]]:
    """Return the full currently valid keyword, direction, and exclusion lists."""
    keywords = [] if previous is None else list(previous.keywords)
    directions = [] if previous is None else list(previous.role_directions)
    exclusions = [] if previous is None else list(previous.exclusions)
    for delta in deltas:
        _apply(keywords, delta.remove_keywords, delta.add_keywords)
        _apply(directions, delta.remove_role_directions, delta.add_role_directions)
        _apply(exclusions, delta.remove_exclusions, delta.add_exclusions)
        _drop_excluded(keywords, exclusions)
    _drop_excluded(keywords, exclusions)
    if not keywords and not directions and not exclusions:
        _reject("Search snapshot has no remaining keyword, direction, or exclusion.")
    return keywords, directions, exclusions


def _apply(values: list[str], removals: list[str], additions: list[str]) -> None:
    for item in removals:
        if item in values:
            values.remove(item)
    for item in additions:
        if item not in values:
            values.append(item)


def _drop_excluded(keywords: list[str], exclusions: list[str]) -> None:
    for item in exclusions:
        if item in keywords:
            keywords.remove(item)
