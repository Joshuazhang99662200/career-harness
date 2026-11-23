import json
from copy import deepcopy
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.memory.human_trace import TraceRequest, plan_human_trace
from jobagent.setup.bootstrap import read_contract

CONTRACT = Path(__file__).parents[1] / "skills/job-hunting/references/feishu-schema-bootstrap.md"
TYPE = "drive.file.bitable_record_changed_v1"


def event(actor="ou_owner", revision=12, before="B", after="C", record="job-1",
          field="fld_grade", event_id=None):
    return {
        "schema": "2.0", "header": {"event_type": TYPE, "event_id": event_id or f"evt-{revision}",
                                   "app_id": "app-fixture", "tenant_key": "tenant-fixture"},
        "event": {
            "file_type": "bitable", "file_token": "base-fixture", "table_id": "jobs-fixture",
            "operator_id": {"open_id": actor}, "revision": revision, "update_time": 1795161600,
            "action_list": [{
                "record_id": record, "action": "record_edited",
                "before_value": [{"field_id": field, "field_value": json.dumps(before)}],
                "after_value": [{"field_id": field, "field_value": json.dumps(after)}],
            }],
        },
    }


def request(message=None, **changes):
    return {
        "event": event() if message is None else message,
        "app_id": "app-fixture", "tenant_key": "tenant-fixture",
        "base_token": "base-fixture", "jobs_table_id": "jobs-fixture",
        "operators": {"human_open_ids": ["ou_owner"], "bot_open_ids": ["ou_bot"]},
        "fields": {"匹配档位": "fld_grade", "批准状态": "fld_approval",
                   "处理进度": "fld_progress", "招呼语": "fld_greeting"},
        "rows_complete": True,
        **changes,
    }


def plan(message=None, **changes):
    return plan_human_trace(read_contract(CONTRACT), TraceRequest.model_validate(
        request(message, **changes),
    ))


@pytest.mark.parametrize("actor", ["ou_bot", "ou_collaborator", "", "Owner"])
def test_only_bound_owner_triggers_a_trace_before_any_storage_lookup(actor):
    result = plan(event(actor=actor), rows_complete=False)
    assert result.status == "operator_ignored"
    assert result.signal_ids == []
    assert result.writes == []


def test_conflicting_or_unbound_identity_never_triggers_a_trace():
    message = event()
    message["event"]["operator_id"]["union_id"] = "on_someone_else"
    result = plan(message, operators={
        "human_open_ids": ["ou_owner"], "human_union_ids": ["on_owner"],
    })
    assert result.status == "operator_ignored"
    assert plan(operators={}).status == "owner_required"
    assert plan(operators={"human_open_ids": ["ou_owner", "ou_other"]}).status == "owner_required"


def test_scope_and_watched_field_and_both_values_are_required():
    foreign = event()
    foreign["header"]["app_id"] = "other"
    assert plan(foreign).status == "scope_ignored"
    foreign = event()
    foreign["event"]["table_id"] = "other"
    assert plan(foreign).status == "scope_ignored"
    deleted = event()
    deleted["event"]["action_list"][0]["action"] = "record_deleted"
    assert plan(deleted).writes == []
    assert plan(event(field="fld_other")).writes == []
    absent = event()
    del absent["event"]["action_list"][0]["before_value"][0]["field_value"]
    assert plan(absent).writes == []


def test_owner_change_uses_a_verified_bot_baseline_and_final_owner_value():
    baseline = event(actor="ou_bot", revision=10, before=None, after="A")
    item = plan(event(), bot_events=[baseline]).writes[0]
    assert json.loads(item.fields["before_value"]) == "A"
    assert json.loads(item.fields["after_value"]) == "C"
    assert item.fields["event_id"] == "evt-12"
    assert item.fields["learning_status"] == "pending_dream"
    assert json.loads(item.fields["source_context"])["baseline_event_id"] == "evt-10"


def test_owner_only_trace_preserves_explicit_null_and_rich_values_without_guessing():
    rich = [{"type": "text", "text": "notes"}]
    item = plan(event(before=None, after=rich)).writes[0]
    assert json.loads(item.fields["before_value"]) is None
    assert json.loads(item.fields["after_value"]) == rich
    assert item.fields["learning_status"] == "unknown"
    assert json.loads(item.fields["source_context"])["baseline_event_id"] is None


def saved(item):
    return {"signal_record_id": "trace-row", **item.fields}


def test_multiple_owner_edits_update_one_trace_and_duplicate_or_older_events_do_not_write():
    base = event(actor="ou_bot", revision=10, before=None, after="A")
    previous = plan(event(revision=11, before="A", after="B"), bot_events=[base]).writes[0]
    result = plan(event(revision=12, before="B", after="C"), rows=[saved(previous)])
    assert len(result.writes) == 1
    item = result.writes[0]
    assert item.signal_record_id == "trace-row"
    assert item.fields["signal_id"] == previous.fields["signal_id"]
    assert json.loads(item.fields["before_value"]) == "A"
    assert json.loads(item.fields["after_value"]) == "C"
    assert plan(event(), rows=[saved(item)]).writes == []
    assert plan(event(revision=11), rows=[saved(item)]).writes == []
    conflict = event(revision=13, event_id="evt-12")
    assert plan(conflict, rows=[saved(item)]).status == "trace_conflict"
    other_job = plan(event(record="job-2")).writes[0]
    assert other_job.fields["signal_id"] != item.fields["signal_id"]


def test_new_bot_value_becomes_the_baseline_and_reverting_is_context_only():
    baseline = event(actor="ou_bot", revision=10, before=None, after="A")
    first = plan(event(), bot_events=[baseline]).writes[0]
    new_bot = event(actor="ou_bot", revision=13, before="C", after="D")
    second = plan(event(revision=14, before="D", after="B"),
                  bot_events=[new_bot], rows=[saved(first)]).writes[0]
    final = plan(event(revision=15, before="B", after="D"),
                 rows=[saved(second)]).writes[0]
    assert json.loads(final.fields["before_value"]) == "D"
    assert json.loads(final.fields["after_value"]) == "D"
    assert final.fields["learning_status"] == "context_only"


@pytest.mark.parametrize(("field", "kind"), [
    ("fld_approval", "approval_decision"), ("fld_progress", "workflow_outcome"),
])
def test_owner_context_changes_do_not_create_preference_candidates(field, kind):
    result = plan(event(field=field), bot_events=[event(
        actor="ou_bot", revision=10, before=None, after="A", field=field,
    )]).writes[0]
    assert result.fields["signal_type"] == kind
    assert result.fields["learning_status"] == "context_only"


def test_lookup_requires_complete_rows_and_never_duplicates_an_ambiguous_trace():
    result = plan(rows_complete=False)
    assert result.status == "inspect_traces"
    assert len(result.signal_ids) == 1
    assert result.writes == []
    original = plan().writes[0]
    one = saved(original)
    two = {**one, "signal_record_id": "another-trace"}
    assert plan(event(revision=13), rows=[one, two]).status == "trace_conflict"


def test_bot_baseline_from_different_scope_or_role_is_not_accepted():
    wrong_table = event(actor="ou_bot", revision=10, after="A")
    wrong_table["event"]["table_id"] = "other"
    collaborator = event(actor="ou_other", revision=11, after="X")
    item = plan(bot_events=[wrong_table, collaborator]).writes[0]
    assert item.fields["learning_status"] == "unknown"
    assert json.loads(item.fields["before_value"]) == "B"


def test_cli_filters_bot_before_outputting_a_storage_lookup(tmp_path):
    payload = deepcopy(request(event(actor="ou_bot"), rows_complete=False))
    path = tmp_path / "synthetic-request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = CliRunner().invoke(app, [
        "feishu", "human-trace-plan", "--contract", str(CONTRACT), "--request", str(path),
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "operator_ignored"
    assert list(tmp_path.iterdir()) == [path]
