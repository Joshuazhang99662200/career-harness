"""Worker send decisions come from a fresh shared read. SQLite approval is not authority."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.bridge.feishu_gateway import FeishuGateway
from jobagent.bridge.worker import WorkerGateway
from jobagent.errors import ApprovalRequiredError
from jobagent.jobs.shared_send_gate import current_work_decision
from jobagent.schemas.feishu import FeishuConfig, FeishuRecord, SharedSendPolicy
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_worker import MANIFEST, TEXT, MutableShared, gateway, prepare, ready_record


def _claims(gw: WorkerGateway) -> int:
    with gw.database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM worker_send_claims").fetchone()
    assert row is not None
    return int(row[0])


def test_leftover_sqlite_approval_does_not_send_when_the_table_is_unapproved(
    tmp_path: Path,
) -> None:
    gw = gateway(tmp_path, shared="unapproved")
    batch_id = prepare(gw, approve=True)
    with pytest.raises(ApprovalRequiredError) as caught:
        gw.claim_greeting(batch_id, "local_test", "W1")
    assert caught.value.details["reason"] == "unapproved"
    assert caught.value.details["send_dispatched"] is False
    assert SqliteOutreachRepository(gw.database).get_approval(batch_id) is not None
    assert _claims(gw) == 0


def test_missing_or_unready_progress_does_not_send(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw, approve=True)
    assert isinstance(gw.shared, MutableShared)
    gw.shared.replace(progress=["NOT_READY"])
    with pytest.raises(ApprovalRequiredError) as unready:
        gw.claim_greeting(batch_id, "local_test", "W1")
    assert unready.value.details["reason"] == "progress_not_ready"
    gw.shared.replace(progress=None)
    with pytest.raises(ApprovalRequiredError) as missing:
        gw.claim_greeting(batch_id, "local_test", "W1")
    assert missing.value.details["reason"] == "progress_missing"
    assert _claims(gw) == 0


def test_current_shared_approval_does_not_require_a_local_approval_row(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw, approve=False)
    claim = gw.claim_greeting(batch_id, "local_test", "W1")
    assert claim.item.text == TEXT
    assert claim.shared_record_id == "rec_synthetic_job"
    assert claim.approval_channel.value == "shared_table"
    assert SqliteOutreachRepository(gw.database).get_approval(batch_id) is None


def test_gateway_get_is_reread_before_authorize(tmp_path: Path) -> None:
    transport = Transport()
    config = FeishuConfig.model_validate({
        "base_token": "BASE_SYNTHETIC",
        "identity": "user",
        "executable": "synthetic-lark.exe",
        "timeout_seconds": 8,
        "tables": {"jobs": {
            "table_id": "tblSynthetic",
            "fields": {"approval": "fldH", "progress": "fldP", "greeting": "fldG"},
            "writable": {"execution": ["progress"]},
            "material_fields": ["greeting"],
            "approved_values": ["APPROVED_SYNTHETIC"],
        }},
    })
    base = gateway(tmp_path, shared="off")
    worker = WorkerGateway(
        base.database,
        manifests=[MANIFEST],
        clock=base.clock,
        shared=_GatewayReader(FeishuGateway(config, transport), "jobs"),
        shared_record_id="recSynthetic",
        send_policy=SharedSendPolicy(
            approved_values=["APPROVED_SYNTHETIC"], ready_progress=["READY_SYNTHETIC"]
        ),
    )
    batch_id = prepare(worker, approve=True)
    before = len(transport.calls)
    claim = worker.claim_greeting(batch_id, "local_test", "W1")
    assert len(transport.calls) > before
    assert "+record-get" in transport.calls[-1]
    transport.current = matrix(approval="WAIT")
    with pytest.raises(ApprovalRequiredError) as caught:
        worker.authorize_greeting(claim.task_id, "W1")
    assert caught.value.details["reason"] == "unapproved"
    assert caught.value.details["send_dispatched"] is False


def test_a_generated_greeting_is_not_approval() -> None:
    decision = current_work_decision(
        ready_record(approval="WAIT", greeting=TEXT),
        SharedSendPolicy(
            approved_values=["APPROVED_SYNTHETIC"], ready_progress=["READY_SYNTHETIC"]
        ),
    )
    assert decision.greeting == TEXT
    assert decision.reason == "unapproved"
    assert decision.business_allowed is False
    assert decision.send_dispatched is False


def test_cli_fixture_refuses_sqlite_approval_until_the_file_is_current(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.app import app

    gw = gateway(tmp_path, shared="off")
    batch_id = prepare(gw, approve=True)
    fixture = tmp_path / "current.json"
    fixture.write_text(ready_record(approval="WAIT").model_dump_json(), encoding="utf-8")
    args = [
        "worker", "claim-greeting", batch_id, "--platform", "local_test", "--session", "W1",
        "--database", str(gw.database.path), "--record-id", "rec_synthetic_job",
        "--shared-fixture", str(fixture), "--approved", "APPROVED_SYNTHETIC",
        "--ready-progress", "READY_SYNTHETIC",
    ]
    refused = CliRunner().invoke(app, args)
    body = json.loads(refused.stdout)
    assert refused.exit_code == 1
    assert body["error"]["code"] == "APPROVAL_REQUIRED"
    assert body["error"]["details"]["reason"] == "unapproved"
    fixture.write_text(ready_record().model_dump_json(), encoding="utf-8")
    assert SqliteOutreachRepository(gw.database).acquire_lease(
        "local_test", "W1", now=datetime.now(UTC), ttl_seconds=1800
    )
    allowed = CliRunner().invoke(app, args)
    assert allowed.exit_code == 0, allowed.stdout
    claim = json.loads(allowed.stdout)
    assert claim["item"]["text"] == TEXT
    assert claim["approval_channel"] == "shared_table"


class Transport:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.current = matrix()

    def call(self, argv: list[str]) -> dict[str, object]:
        self.calls.append(argv)
        if "+field-list" in argv:
            return SCHEMA
        if "+record-get" in argv:
            return self.current
        raise AssertionError(argv)


class _GatewayReader:
    def __init__(self, feishu: FeishuGateway, table: str) -> None:
        self.feishu = feishu
        self.table = table

    def current(self, record_id: str) -> FeishuRecord:
        return self.feishu.get(self.table, record_id)


SCHEMA = {
    "fields": [
        {"id": "fldH", "name": "批准状态", "type": "select", "multiple": False,
         "options": [{"name": "APPROVED_SYNTHETIC"}, {"name": "WAIT"}]},
        {"id": "fldP", "name": "处理进度", "type": "select", "multiple": False,
         "options": [{"name": "READY_SYNTHETIC"}, {"name": "NOT_READY"}]},
        {"id": "fldG", "name": "招呼语", "type": "text"},
    ],
    "total": 3,
}


def matrix(
    approval: str = "APPROVED_SYNTHETIC", progress: str = "READY_SYNTHETIC"
) -> dict[str, object]:
    return {
        "field_id_list": ["fldH", "fldP", "fldG"],
        "data": [[[approval], [progress], TEXT]],
        "record_id_list": ["recSynthetic"],
        "has_more": False,
        "rev": 7,
    }
