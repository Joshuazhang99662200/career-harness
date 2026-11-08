"""Personal todos for asked first greetings, and the two answers the panel offers on them."""

from jobagent.bridge.panel_decisions import panel_materials, panel_operation
from jobagent.bridge.preference_memory import load_preference_events
from jobagent.console.host_state import host_state
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_panel_decisions import PIPE, TEXT, decision, record, setup


def todo_of(path):
    [todo] = host_state(path, "CAND_TEST").todos
    return todo


def answer(path, option, *, key="OP_TODO", note="", **changes):
    todo = todo_of(path)
    return record(path, decision(
        path, "answer_todo", key=key, note=note, todo_id=todo.todo_id, option_id=option,
        revision=todo.material_revision, **changes,
    ))


def test_an_asked_greeting_is_one_pending_personal_todo(tmp_path):
    path, _ = setup(tmp_path)
    item = SqliteOutreachRepository(Database(path)).get_batch("OBATCH_FIXTURE").items[0]

    state = host_state(path, "CAND_TEST")
    [todo] = state.todos
    assert todo == host_state(path, "CAND_TEST").todos[0]  # stable across reads
    assert (todo.job_id, todo.contact_id) == ("fixture-role", PIPE)
    assert todo.material_revision == item.item_digest
    assert todo.material_revision == panel_materials(path, "CAND_TEST", PIPE)[0].revision
    assert todo.status == "pending" and todo.result is None
    assert todo.requires_person and todo.host_resolved
    assert todo.basis and any("Fixture Labs" in line for line in todo.basis)
    assert {o.option_id for o in todo.options} == {"revise", "hold"}
    assert all(o.consequence for o in todo.options)
    # Todos now come from the repository, so the panel may read them.
    assert state.sync.status != "unavailable"


def test_a_decided_greeting_resolves_its_todo(tmp_path):
    path, _ = setup(tmp_path)
    record(path, decision(path, "approve_material"))
    todo = todo_of(path)
    assert todo.status == "resolved" and "批准" in (todo.result or "")


def test_hold_registers_a_deferral_only(tmp_path):
    path, _ = setup(tmp_path)
    receipt = answer(path, "hold", note="先看看别的岗位")

    assert receipt.status == "saved" and receipt.event_id
    assert panel_operation(path, "CAND_TEST", "OP_TODO").event_id == receipt.event_id
    state = host_state(path, "CAND_TEST")
    [todo] = state.todos
    assert todo.status == "resolved" and "暂缓" in (todo.result or "")
    [event] = state.jobs[0].events
    assert (event.event_id, event.kind) == (receipt.event_id, "answer_todo")
    assert event.option_id == "hold"
    assert event.todo_id == todo.todo_id and "先看看别的岗位" in event.detail
    # No approval, no send authority, no preference feedback; the greeting stays decidable.
    store = SqliteOutreachRepository(Database(path))
    assert [b.batch_id for b in store.list_batches()] == ["OBATCH_FIXTURE"]
    assert load_preference_events(path, "CAND_TEST") == []
    assert SqliteFeedbackRepository(Database(path)).decided_numbers("OBATCH_FIXTURE") == set()
    assert len(panel_materials(path, "CAND_TEST", PIPE)) == 1
    assert record(path, decision(path, "approve_material", key="OP_LATER")).status == "saved"
    # Reading again after the later approval still shows the earlier answer.
    assert [e.kind for e in host_state(path, "CAND_TEST").jobs[0].events] == [
        "answer_todo", "approve_material"
    ]


def test_a_rewrite_request_is_recorded_without_feedback_or_approval(tmp_path):
    path, _ = setup(tmp_path)
    receipt = answer(path, "revise", note="开头太长; 强调评测经验")

    assert receipt.status == "saved" and "重写" in receipt.message
    todo = todo_of(path)
    assert todo.status == "resolved" and "重写" in (todo.result or "")
    [event] = host_state(path, "CAND_TEST").jobs[0].events
    assert event.option_id == "revise" and "强调评测经验" in event.detail
    assert load_preference_events(path, "CAND_TEST") == []
    assert SqliteOutreachRepository(Database(path)).get_approval("OBATCH_FIXTURE") is None


def test_replay_and_conflicting_answers(tmp_path):
    path, _ = setup(tmp_path)
    first = answer(path, "hold")
    assert answer(path, "hold").event_id == first.event_id  # same key, same answer
    assert answer(path, "revise").status == "rejected"  # same key, different answer
    # The todo is resolved now, so a fresh answer on it is refused.
    assert answer(path, "revise", key="OP_SECOND").status == "rejected"


def test_stale_or_foreign_answers_are_rejected(tmp_path):
    path, _ = setup(tmp_path)
    todo = todo_of(path)
    cases = [
        {"todo_id": "TODO_UNKNOWN"},
        {"option_id": "approve"},
        {"revision": "sha256:" + "0" * 64},
        {"body": "Edited words."},
        {"candidate_id": "CAND_OTHER"},
        {"todo_id": None},
    ]
    for number, changes in enumerate(cases):
        data = {"todo_id": todo.todo_id, "option_id": "hold", "revision": todo.material_revision}
        data.update(changes)
        receipt = record(path, decision(path, "answer_todo", key=f"OP_{number}", **data))
        assert receipt.status == "rejected", changes
    assert host_state(path, "CAND_TEST").jobs[0].events == []
    assert todo_of(path).status == "pending"


def test_no_asked_greetings_means_no_todos(tmp_path):
    path, _ = setup(tmp_path)
    assert host_state(path, "CAND_OTHER").todos == []
    assert TEXT  # the fixture's asked greeting belongs to CAND_TEST only


def test_cli_chain_todo_hold_read_back_and_reopen(tmp_path):
    """The host adapter's path: host-state -> decide answer_todo -> operation -> host-state."""
    import json

    from typer.testing import CliRunner

    from jobagent.cli.app import app

    path, _ = setup(tmp_path)
    runner = CliRunner()
    db = ["--database", str(path)]

    def state():
        result = runner.invoke(app, ["console", "host-state", "--candidate", "CAND_TEST", *db])
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    [todo] = state()["todos"]
    assert todo["status"] == "pending"
    request = decision(
        path, "answer_todo", key="OP_CLI_HOLD", todo_id=todo["todo_id"], option_id="hold",
        revision=todo["material_revision"], note="",
    )
    request_path = tmp_path / "answer.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    decided = runner.invoke(
        app, ["console", "decide", str(request_path), "--actor", "OWNER_SYNTHETIC", *db]
    )
    assert decided.exit_code == 0, decided.stdout
    receipt = json.loads(decided.stdout)
    read = runner.invoke(
        app, ["console", "operation", "OP_CLI_HOLD", "--candidate", "CAND_TEST", *db]
    )
    assert json.loads(read.stdout)["event_id"] == receipt["event_id"]

    first, reopened = state(), state()
    assert first == reopened  # reopening reads the same saved facts
    [todo] = first["todos"]
    assert todo["status"] == "resolved" and "暂缓" in todo["result"]
    [event] = first["jobs"][0]["events"]
    assert (event["event_id"], event["option_id"]) == (receipt["event_id"], "hold")
    assert [r["event_id"] for r in first["receipts"]] == [receipt["event_id"]]
