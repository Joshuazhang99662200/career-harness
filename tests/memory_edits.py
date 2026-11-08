"""Test helper: express "the model proposes this full rule set" as incremental edits."""

from typing import Any


def as_edits(current: list[Any], proposed: list[Any], fresh_ids: list[str]) -> list[dict]:
    """Edits that turn `current` into `proposed`: add new IDs, edit changed ones, retire the
    rest (citing the fresh events). Unchanged rules are simply not mentioned."""

    def plain(rule: Any) -> dict:
        return rule if isinstance(rule, dict) else rule.model_dump(mode="json")

    old = {plain(r)["rule_id"]: plain(r) for r in current}
    new = {plain(r)["rule_id"]: plain(r) for r in proposed}
    edits: list[dict] = []
    for rule_id, rule in new.items():
        if rule_id not in old:
            edits.append({"op": "add", "rule": rule})
        elif old[rule_id] != rule:
            edits.append({"op": "edit", "replaces": [rule_id], "rule": rule})
    gone = [rule_id for rule_id in old if rule_id not in new]
    if gone:
        edits.append({"op": "retire", "replaces": gone, "because_event_ids": fresh_ids})
    return edits
