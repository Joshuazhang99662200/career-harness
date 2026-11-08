"""The panel's selection queue, kept by the repository: it survives reloads, grants
nothing, and an item leaves it only after its send was verified by exact readback."""

import json

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.console.execution import create_execution_batch
from jobagent.console.selection import read_selection, save_selection
from jobagent.schemas.console_host import HostSelectionRequest
from jobagent.schemas.outreach import OutreachResult
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.console.test_execution_batches import (
    LATER,
    PIPE,
    approve_from_panel,
    audit,
    build,
    confirm,
    read_back,
)


def change(path, operation, contacts, *, version=None, candidate="CAND_TEST"):
    if version is None:
        version = read_selection(path, candidate).version
    request = HostSelectionRequest(
        candidate_id=candidate, expected_version=version, operation=operation,
        contact_ids=contacts,
    )
    return save_selection(path, request, now=LATER)


def test_selection_starts_empty_and_persists(tmp_path):
    path = build(tmp_path)
    empty = read_selection(path, "CAND_TEST")
    assert (empty.version, empty.contact_ids) == (0, [])

    receipt = change(path, "select", [PIPE])
    assert receipt.status == "saved" and receipt.selection.contact_ids == [PIPE]
    again = read_selection(path, "CAND_TEST")  # a fresh read, as after a reload
    assert again.contact_ids == [PIPE] and again.version == 1
    assert read_selection(path, "CAND_OTHER").contact_ids == []


def test_operations_on_the_visible_rows(tmp_path):
    path = build(tmp_path)
    assert change(path, "select_visible", [PIPE]).selection.contact_ids == [PIPE]
    assert change(path, "invert_visible", [PIPE]).selection.contact_ids == []
    assert change(path, "invert_visible", [PIPE]).selection.contact_ids == [PIPE]
    assert change(path, "clear_visible", [PIPE]).selection.contact_ids == []
    change(path, "select", [PIPE])
    assert change(path, "deselect", [PIPE]).selection.contact_ids == []
    change(path, "select", [PIPE])
    assert change(path, "clear_all", []).selection.contact_ids == []


def test_a_stale_or_foreign_change_is_refused_without_writing(tmp_path):
    path = build(tmp_path)
    change(path, "select", [PIPE])
    stale = change(path, "clear_all", [], version=0)
    assert stale.status == "rejected" and stale.selection.contact_ids == [PIPE]
    foreign = change(path, "select", ["PIPE_00000000000000B2"])
    assert foreign.status == "rejected"
    other = change(path, "select", [PIPE], candidate="CAND_OTHER")
    assert other.status == "rejected"
    assert read_selection(path, "CAND_TEST").contact_ids == [PIPE]


def test_selecting_grants_nothing(tmp_path):
    path = build(tmp_path)
    change(path, "select", [PIPE])
    store = SqliteOutreachRepository(Database(path))
    assert [b.batch_id for b in store.list_batches()] == ["OBATCH_FIXTURE"]
    assert store.get_approval("OBATCH_FIXTURE") is None


def test_only_a_verified_send_leaves_the_selection(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    change(path, "select", [PIPE])
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    confirm(path, batch)
    sent = audit(path, OutreachResult.SENT)
    # Sent but not read back: unknown, so it stays selected until checked.
    assert read_selection(path, "CAND_TEST").contact_ids == [PIPE]
    read_back(path, sent)
    assert read_selection(path, "CAND_TEST").contact_ids == []
    # Choosing it again later is the person's new choice and is kept.
    change(path, "select", [PIPE])
    assert read_selection(path, "CAND_TEST").contact_ids == [PIPE]


def test_a_failed_send_stays_selected(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    change(path, "select", [PIPE])
    confirm(path, create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER))
    audit(path, OutreachResult.FAILED, reason="对方已关闭沟通")
    assert read_selection(path, "CAND_TEST").contact_ids == [PIPE]


def test_cli_round_trip(tmp_path):
    path = build(tmp_path)
    runner, db = CliRunner(), ["--database", str(path)]
    request = tmp_path / "select.json"
    request.write_text(json.dumps({
        "candidate_id": "CAND_TEST", "expected_version": 0, "operation": "select",
        "contact_ids": [PIPE],
    }), encoding="utf-8")
    saved = runner.invoke(app, ["console", "select", str(request), *db])
    assert saved.exit_code == 0, saved.stdout
    assert json.loads(saved.stdout)["selection"]["contact_ids"] == [PIPE]
    shown = runner.invoke(app, ["console", "selection", "--candidate", "CAND_TEST", *db])
    assert json.loads(shown.stdout) == {
        "candidate_id": "CAND_TEST", "version": 1, "contact_ids": [PIPE],
    }
    stale = runner.invoke(app, ["console", "select", str(request), *db])
    assert stale.exit_code == 1 and json.loads(stale.stdout)["status"] == "rejected"
