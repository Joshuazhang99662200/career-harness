"""Native record history must not guess which of multiple edits caused a Workflow row."""

from jobagent.memory.history_match import match_history, parse_history_page
from jobagent.schemas.memory_signal import OperatorDirectory

OPERATORS = OperatorDirectory(human_open_ids=["ou_human_fixture"])


def test_two_sequential_edits_on_one_field_remain_ambiguous_without_event_correlation() -> None:
    page = parse_history_page({
        "items": [
            {
                "rev": 41,
                "create_time": 1795161600,
                "activity_type": "update",
                "operator": {"open_id": "ou_human_fixture", "name": "Human"},
                "field_changes": [{"field_id": "flddtn4pvI", "before": "C", "after": "B"}],
            },
            {
                "rev": 42,
                "create_time": 1795165200,
                "activity_type": "update",
                "operator": {"open_id": "ou_human_fixture", "name": "Human"},
                "field_changes": [{"field_id": "flddtn4pvI", "before": "B", "after": "A"}],
            },
        ],
        "has_more": False,
    })
    result = match_history(
        [page],
        record_id="rec_job_fixture",
        field_id="flddtn4pvI",
        operators=OPERATORS,
    )
    assert result.state == "unknown"
    assert result.reason == "ambiguous_field_change"
    assert result.grants_learning is False
    assert result.before_value is None
    assert result.after_value is None


def test_one_unique_human_field_change_can_be_attributed() -> None:
    page = parse_history_page({
        "items": [{
            "rev": 43,
            "create_time": 1795168800,
            "activity_type": "update",
            "operator": {"open_id": "ou_human_fixture", "name": "Human"},
            "field_changes": [{"field_id": "flddtn4pvI", "before": "B", "after": "A"}],
        }],
        "has_more": False,
    })
    result = match_history(
        [page],
        record_id="rec_job_fixture",
        field_id="flddtn4pvI",
        operators=OPERATORS,
    )
    assert result.state == "matched"
    assert result.reason == "matched_human"
    assert result.grants_learning is True
    assert result.before_value == "B"
    assert result.after_value == "A"
