"""Dream batch scope and complete search snapshots. Mock transport only."""

import json
from pathlib import Path

import pytest

from jobagent.bridge.shared_memory import SharedMemoryService
from jobagent.errors import ContractValidationError
from jobagent.memory.snapshot import decode_source_signal_ids
from jobagent.schemas.shared_memory import (
    DreamBatchComplete,
    DreamBatchStart,
    FetchMemoryPin,
    SearchRoundInput,
    SignalPreferenceDelta,
)
from tests.bridge.test_shared_memory_alignment import FakeBase, config, service

CUTOFF = "2026-11-20T12:00:00+00:00"
JOB = "JOB_DATA_PLATFORM"


def _ready(
    base: FakeBase,
    record_id: str,
    changed_at: str,
    *,
    before: str = "C",
    after: str = "B",
    operator: str = "ou_human_fixture",
    title: str = "Data Platform Engineer",
) -> None:
    base.signals[record_id] = {
        "source_table": "tbl0m4LpWgeGuZEd",
        "source_record_id": "rec_job_data",
        "job_title": title,
        "field_name": "匹配档位",
        "field_id": "flddtn4pvI",
        "signal_type": "matching_correction",
        "memory_domain": "search_match",
        "learning_status": "pending_dream",
        "signal_id": None,
        "source_context": None,
        "operator_id": operator,
        "operator_name": "Synthetic Human",
        "changed_at": changed_at,
        "before_value": before,
        "after_value": after,
    }


def _delta(
    signal_id: str,
    reason: str,
    *,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    exclude: list[str] | None = None,
    drop_exclusion: list[str] | None = None,
) -> SignalPreferenceDelta:
    return SignalPreferenceDelta(
        signal_record_id=signal_id,
        add_keywords=list(add or []),
        remove_keywords=list(remove or []),
        add_exclusions=list(exclude or []),
        remove_exclusions=list(drop_exclusion or []),
        reason=reason,
    )


def _start(store: SharedMemoryService, size: int, cutoff: str = CUTOFF):
    return store.start_dream_batch(DreamBatchStart(
        candidate_id="CAND_FIXTURE", batch_size=size, cutoff=cutoff,
    ))


def _finish(store: SharedMemoryService, snapshot, deltas: list[SignalPreferenceDelta]):
    return store.complete_dream_batch(DreamBatchComplete(
        snapshot=snapshot, deltas=deltas, job_id=JOB,
    ))


def _round() -> SearchRoundInput:
    return SearchRoundInput(
        candidate_id="CAND_FIXTURE",
        keywords=["backend engineer"],
        hard_constraints={"cities": ["Shanghai"]},
        queries_per_site_per_round=2,
        top_per_query=30,
        search_frequency="synthetic-weekly",
    )


def test_new_edit_after_dream_starts_stays_out_of_the_frozen_batch() -> None:
    base, store = service()
    _ready(base, "rec_early", "2026-11-20T08:00:00+00:00")
    _ready(base, "rec_bot", "2026-11-20T08:30:00+00:00", operator="ou_bot_fixture", after="A")
    _ready(base, "rec_late_clock", "2026-11-20T13:00:00+00:00", before="A", after="S")
    snapshot = _start(store, 10)
    assert snapshot.signal_ids == ["rec_early"]
    assert snapshot.resumed is False
    assert snapshot.quiet_window_seconds is None
    _ready(base, "rec_after_start", "2026-11-20T08:05:00+00:00", before="B", after="A")
    assert "rec_after_start" not in snapshot.signal_ids
    result = _finish(store, snapshot, [_delta("rec_early", "Early grade.", add=["backend"])])
    assert result.verified is True
    assert base.signals["rec_after_start"]["learning_status"] == "pending_dream"
    assert base.signals["rec_bot"]["learning_status"] == "pending_dream"
    assert base.signals["rec_late_clock"]["learning_status"] == "pending_dream"


def test_two_successive_edits_on_one_job_both_remain() -> None:
    base, store = service()
    _ready(base, "rec_cb", "2026-11-20T08:00:00+00:00", before="C", after="B")
    _ready(base, "rec_ba", "2026-11-20T09:00:00+00:00", before="B", after="A")
    snapshot = _start(store, 10)
    assert snapshot.signal_ids == ["rec_cb", "rec_ba"]
    result = _finish(store, snapshot, [
        _delta("rec_cb", "Grade moved from C to B.", add=["pipelines", "tier-b"]),
        _delta("rec_ba", "Grade moved from B to A.", remove=["tier-b"], add=["tier-a"]),
    ])
    assert result.verified is True
    assert result.learned_signal_ids == ["rec_cb", "rec_ba"]
    assert "pipelines" in result.keywords and "tier-a" in result.keywords
    assert "tier-b" not in result.keywords
    stored = next(iter(base.search_rows.values()))
    assert decode_source_signal_ids(str(stored["source_signal_id"])) == ["rec_cb", "rec_ba"]
    assert base.signals["rec_cb"]["learning_status"] == "learned"
    assert base.signals["rec_ba"]["learning_status"] == "learned"


def test_signals_beyond_batch_size_stay_pending() -> None:
    base, store = service()
    _ready(base, "rec_1", "2026-11-20T08:00:00+00:00")
    _ready(base, "rec_2", "2026-11-20T09:00:00+00:00", before="B", after="A")
    _ready(base, "rec_3", "2026-11-20T10:00:00+00:00", before="A", after="S")
    snapshot = _start(store, 2)
    assert snapshot.signal_ids == ["rec_1", "rec_2"]
    assert snapshot.overflow_signal_ids == ["rec_3"]
    assert base.signals["rec_3"]["source_context"] is None
    assert base.signals["rec_3"]["learning_status"] == "pending_dream"


def test_abnormal_exit_resumes_the_unfinished_batch_without_later_signals() -> None:
    base, store = service()
    _ready(base, "rec_open", "2026-11-20T08:00:00+00:00")
    first = _start(store, 10)
    restarted = SharedMemoryService(store.gateway, store.operators)
    _ready(base, "rec_during_outage", "2026-11-20T08:10:00+00:00", before="B", after="A")
    second = _start(restarted, 10)
    assert second.resumed is True
    assert second.batch_id == first.batch_id
    assert second.signal_ids == ["rec_open"]
    assert "rec_during_outage" not in second.signal_ids
    assert base.signals["rec_open"]["learning_status"] == "pending_dream"


def test_status_writeback_retry_uses_source_signal_ids_without_relearning() -> None:
    base, store = service()
    _ready(base, "rec_cb", "2026-11-20T08:00:00+00:00", before="C", after="B")
    _ready(base, "rec_ba", "2026-11-20T09:00:00+00:00", before="B", after="A")
    snapshot = _start(store, 10)
    deltas = [
        _delta("rec_cb", "First correction.", add=["pipelines"]),
        _delta("rec_ba", "Later correction.", add=["tier-a"]),
    ]
    base.fail_next_status_writes = 1
    failed = _finish(store, snapshot, deltas)
    assert failed.verified is False
    assert failed.pending_signal_ids
    assert len(base.search_rows) == 1
    assert any(row["learning_status"] == "pending_dream" for row in (
        base.signals["rec_cb"], base.signals["rec_ba"],
    ))
    creates = sum("+record-batch-create" in call for call in base.calls)
    recovered = _finish(store, snapshot, deltas)
    assert recovered.verified is True
    assert recovered.republished is False
    assert recovered.learned_signal_ids == ["rec_cb", "rec_ba"]
    assert len(base.search_rows) == 1
    assert sum("+record-batch-create" in call for call in base.calls) == creates
    stored_ids = next(iter(base.search_rows.values()))["source_signal_id"]
    assert decode_source_signal_ids(str(stored_ids)) == ["rec_cb", "rec_ba"]


def test_muse_keeps_a_pinned_version_and_a_later_fetch_reads_the_latest() -> None:
    base, store = _publish_chain(service())
    pinned = store.pin_fetch_memory(_round())
    assert pinned.memory_version == "2"
    assert pinned.applied is True
    assert pinned.keywords == ["backend engineer", "backend", "data platform"]
    assert pinned.content_hash
    assert pinned.last_consumed_version == "2"
    assert pinned.hard_constraints == {"cities": ["Shanghai"]}
    assert pinned.top_per_query == 30
    assert pinned.grants_fetch is False
    _publish_one(store, base, "rec_v5", "2026-11-20T11:00:00+00:00", ["distributed systems"])
    held = store.continue_fetch(pinned, _round())
    assert held.memory_version == "2"
    assert held.content_hash == pinned.content_hash
    assert "distributed systems" not in held.keywords
    latest = store.pin_fetch_memory(_round())
    assert latest.memory_version == "3"
    assert latest.keywords == [
        "backend engineer", "backend", "data platform", "distributed systems",
    ]


def test_unread_intermediate_versions_remain_inside_the_latest_snapshot() -> None:
    _base, store = _publish_chain(service())
    _publish_one(store, _base, "rec_v5", "2026-11-20T11:00:00+00:00", ["distributed systems"])
    pinned = store.pin_fetch_memory(_round())
    assert pinned.memory_version == "3"
    stored = [row for row in _base.search_rows.values() if row["publication_status"] == "published"]
    assert len(stored) == 1
    keywords = json.loads(str(stored[0]["keywords"]))
    assert keywords == ["backend", "data platform", "distributed systems"]
    assert pinned.keywords[-3:] == ["backend", "data platform", "distributed systems"]


def test_direct_read_of_v6_contains_the_still_valid_history() -> None:
    base, store = _publish_chain(service())
    _publish_one(store, base, "rec_v5", "2026-11-20T11:00:00+00:00", ["distributed systems"])
    _publish_one(store, base, "rec_v6", "2026-11-20T11:30:00+00:00", ["ownership"])
    pinned = store.pin_fetch_memory(_round())
    assert pinned.memory_version == "4"
    keywords = json.loads(str(
        next(row["keywords"] for row in base.search_rows.values()
             if row["publication_status"] == "published")
    ))
    assert keywords == ["backend", "data platform", "distributed systems", "ownership"]


def test_wrong_content_hash_is_not_applied() -> None:
    base, store = _publish_chain(service())
    published = next(
        row for row in base.search_rows.values() if row["publication_status"] == "published"
    )
    published["content_digest"] = "sha256:" + ("0" * 64)
    with pytest.raises(ContractValidationError):
        store.pin_fetch_memory(_round())
    assert not any("+record-batch-update" in call or "+record-batch-create" in call
                   for call in base.calls[-3:])


def test_replaced_preference_is_not_applied_together_with_the_old_rule() -> None:
    base, store = service()
    _publish_one(store, base, "rec_old", "2026-11-20T08:00:00+00:00", ["retail floor"])
    _ready(base, "rec_new", "2026-11-20T10:00:00+00:00", before="B", after="A")
    snapshot = _start(store, 10)
    result = _finish(store, snapshot, [
        _delta(
            "rec_new",
            "Retail floor is no longer a target.",
            remove=["retail floor"],
            add=["data platform"],
            exclude=["retail floor"],
        ),
    ])
    assert result.verified is True
    assert "retail floor" not in result.keywords
    assert "data platform" in result.keywords
    assert "retail floor" in result.exclusions
    pinned = store.pin_fetch_memory(_round())
    assert "retail floor" not in pinned.keywords
    assert "data platform" in pinned.keywords
    assert "retail floor" in pinned.exclusions


def test_no_published_memory_keeps_the_caller_search_config() -> None:
    _base, store = service()
    pinned = store.pin_fetch_memory(_round())
    assert pinned.applied is False
    assert pinned.memory_version is None
    assert pinned.keywords == ["backend engineer"]
    assert pinned.hard_constraints == {"cities": ["Shanghai"]}
    assert pinned.queries_per_site_per_round == 2
    assert pinned.top_per_query == 30
    assert pinned.search_frequency == "synthetic-weekly"


def test_second_dream_start_resumes_instead_of_claiming_a_second_batch() -> None:
    import jobagent.cli.patrol as patrol

    patrol_source = Path(patrol.__file__).read_text(encoding="utf-8")
    assert "start_dream_batch" not in patrol_source
    assert "complete_dream_batch" not in patrol_source
    base, store = service()
    _ready(base, "rec_open", "2026-11-20T08:00:00+00:00")
    store._publish_claims.add(("CAND_FIXTURE", "dream-batch"))
    with pytest.raises(ContractValidationError, match="single-writer"):
        _start(store, 10)
    store._publish_claims.discard(("CAND_FIXTURE", "dream-batch"))
    first = _start(store, 10)
    second = _start(store, 10)
    assert second.resumed is True
    assert second.batch_id == first.batch_id
    assert second.signal_ids == first.signal_ids


def _publish_one(
    store: SharedMemoryService, base: FakeBase, record_id: str, changed_at: str, add: list[str],
) -> None:
    _ready(base, record_id, changed_at, before="B", after="A", title=record_id)
    snapshot = _start(store, 10)
    assert record_id in snapshot.signal_ids
    result = _finish(store, snapshot, [_delta(record_id, f"Add {add[0]}.", add=add)])
    assert result.verified is True, result


def _publish_chain(
    pair: tuple[FakeBase, SharedMemoryService],
) -> tuple[FakeBase, SharedMemoryService]:
    base, store = pair
    _publish_one(store, base, "rec_v3", "2026-11-20T08:00:00+00:00", ["backend"])
    _publish_one(store, base, "rec_v4", "2026-11-20T09:00:00+00:00", ["data platform"])
    return base, store


def test_pin_type_rejects_an_applied_pin_without_a_hash() -> None:
    with pytest.raises(ValueError):
        FetchMemoryPin(
            candidate_id="CAND_FIXTURE",
            memory_version="1",
            memory_record_id="rec_mem_1",
            content_hash=None,
            last_consumed_version="1",
            applied=True,
            original_keywords=["backend engineer"],
            keywords=["backend engineer"],
        )



def test_search_dream_excludes_greeting_and_workflow_signals() -> None:
    base, store = service()
    _ready(base, "rec_search", "2026-11-20T08:00:00+00:00")
    _ready(base, "rec_greeting", "2026-11-20T08:10:00+00:00")
    base.signals["rec_greeting"].update({
        "field_name": "招呼语",
        "field_id": "fld0jsS3ei",
        "signal_type": "greeting_revision",
        "memory_domain": "greeting",
    })
    _ready(base, "rec_workflow", "2026-11-20T08:20:00+00:00")
    base.signals["rec_workflow"].update({
        "field_name": "处理进度",
        "field_id": "fldarFiHsF",
        "signal_type": "workflow_outcome",
        "memory_domain": "workflow_context",
    })

    snapshot = _start(store, 10)
    assert snapshot.signal_ids == ["rec_search"]
    assert base.signals["rec_greeting"]["source_context"] is None
    assert base.signals["rec_workflow"]["source_context"] is None
    assert base.signals["rec_greeting"]["learning_status"] == "pending_dream"
    assert base.signals["rec_workflow"]["learning_status"] == "pending_dream"


def test_no_memory_fetch_pin_stays_unapplied_after_memory_is_published() -> None:
    base, store = service()
    pinned = store.pin_fetch_memory(_round())
    assert pinned.applied is False
    _ready(base, "rec_during_fetch", "2026-11-20T08:00:00+00:00")
    snapshot = _start(store, 10)
    _finish(store, snapshot, [
        _delta("rec_during_fetch", "Add a data platform direction.", add=["data platform"]),
    ])

    held = store.continue_fetch(pinned, _round())
    assert held == pinned
    assert held.applied is False
    assert held.memory_version is None
    assert held.keywords == ["backend engineer"]


def test_restart_after_partial_learned_write_restores_the_full_frozen_batch() -> None:
    base, store = service()
    _ready(base, "rec_cb", "2026-11-20T08:00:00+00:00", before="C", after="B")
    _ready(base, "rec_ba", "2026-11-20T09:00:00+00:00", before="B", after="A")
    snapshot = _start(store, 10)
    deltas = [
        _delta("rec_cb", "First correction.", add=["pipelines"]),
        _delta("rec_ba", "Later correction.", add=["tier-a"]),
    ]
    base.fail_next_status_writes = 1
    interrupted = _finish(store, snapshot, deltas)
    assert interrupted.verified is False
    assert base.signals["rec_cb"]["learning_status"] == "pending_dream"
    assert base.signals["rec_ba"]["learning_status"] == "learned"

    restarted = SharedMemoryService(store.gateway, store.operators)
    resumed = _start(restarted, 10)
    assert resumed.resumed is True
    assert resumed.signal_ids == ["rec_cb", "rec_ba"]
    recovered = _finish(restarted, resumed, deltas)
    assert recovered.verified is True
    assert recovered.republished is False
    assert recovered.learned_signal_ids == ["rec_cb", "rec_ba"]
    assert len(base.search_rows) == 1


def test_partial_batch_checkpoint_is_completed_on_resume() -> None:
    base, store = service()
    _ready(base, "rec_first", "2026-11-20T08:00:00+00:00")
    _ready(base, "rec_second", "2026-11-20T09:00:00+00:00", before="B", after="A")
    base.fail_after_source_context_writes = 1
    with pytest.raises(ContractValidationError, match="checkpoint"):
        _start(store, 10)

    restarted = SharedMemoryService(store.gateway, store.operators)
    resumed = _start(restarted, 10)
    assert resumed.resumed is True
    assert resumed.signal_ids == ["rec_first", "rec_second"]
    for signal_id in resumed.signal_ids:
        checkpoint = json.loads(str(base.signals[signal_id]["source_context"]))
        assert checkpoint["dream_batch"]["signal_ids"] == resumed.signal_ids


def test_empty_dream_batch_cannot_be_completed() -> None:
    _base, store = service()
    empty = _start(store, 10)
    assert empty.signal_ids == []
    with pytest.raises(ContractValidationError, match="empty"):
        _finish(store, empty, [])


def test_dream_cli_requires_an_explicit_operator_directory(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from jobagent.cli import feishu as feishu_cli
    from jobagent.cli.app import app
    from jobagent.schemas.memory_signal import OperatorDirectory
    from jobagent.schemas.shared_memory import DreamBatchStart

    base = FakeBase()
    _ready(base, "rec_cli", "2026-11-20T08:00:00+00:00")
    monkeypatch.setattr(feishu_cli, "LarkCliTransport", lambda _config: base)
    config_path = tmp_path / "feishu.json"
    config_path.write_text(config().model_dump_json(), encoding="utf-8")
    request_path = tmp_path / "dream-start.json"
    request_path.write_text(DreamBatchStart(
        candidate_id="CAND_FIXTURE",
        batch_size=10,
        cutoff=CUTOFF,
    ).model_dump_json(), encoding="utf-8")
    operators_path = tmp_path / "operators.json"
    operators_path.write_text(OperatorDirectory(
        human_open_ids=["ou_human_fixture"],
        bot_open_ids=["ou_bot_fixture"],
    ).model_dump_json(), encoding="utf-8")

    runner = CliRunner()
    args = [
        "memory", "dream-batch-start",
        "--config", str(config_path),
        "--request", str(request_path),
    ]
    missing = runner.invoke(app, args)
    assert missing.exit_code != 0
    completed = runner.invoke(app, [*args, "--operators", str(operators_path)])
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.output)["signal_ids"] == ["rec_cli"]
