"""Mock drive.file.bitable_record_changed_v1 signals. No Bitable and no send."""

import copy
import json
from pathlib import Path

import pytest

from jobagent.digest import text_digest
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.jobs.search_memory_apply import apply_search_memory
from jobagent.jobs.search_plan import plan_searches
from jobagent.jobs.shared_send_gate import shared_send_decision
from jobagent.memory.signal import SignalInbox
from jobagent.memory.signal_compile import SignalCompiler
from jobagent.schemas.memory_signal import (
    AttributionRequest,
    CurrentSharedProjection,
    JobSignalContext,
    MemoryDraft,
    OperatorDirectory,
    SearchParameters,
    SignalAttribution,
    WatchedJobFields,
)

FIXTURE = Path(__file__).parent / "fixtures" / "drive_file_bitable_record_changed_v1.json"
FIELDS = WatchedJobFields(
    table_id="tbl_jobs_fixture",
    match_grade_field_id="fld_match_grade",
    progress_field_id="fld_progress",
    greeting_field_id="fld_greeting",
)
OPERATORS = OperatorDirectory(
    bot_open_ids=["ou_bot_fixture"],
    human_open_ids=["ou_human_fixture"],
)
DATA_JD = "Synthetic JD: data platform engineer, owns pipelines."
DATA_GREETING = "Original greeting about pipelines."
OTHER_JD = "Synthetic JD: retail floor associate, unrelated to the data role."
OTHER_GREETING = "Original greeting about retail shifts."
CONTEXTS = {
    "rec_job_data": JobSignalContext(
        candidate_id="CAND_FIXTURE",
        record_id="rec_job_data",
        job_id="JOB_DATA_PLATFORM",
        jd_text=DATA_JD,
        generated_greeting=DATA_GREETING,
        title="Data Platform Engineer",
        company="Synthetic Co",
        role_direction="data platform",
    ),
    "rec_job_other": JobSignalContext(
        candidate_id="CAND_FIXTURE",
        record_id="rec_job_other",
        job_id="JOB_RETAIL_FLOOR",
        jd_text=OTHER_JD,
        generated_greeting=OTHER_GREETING,
        title="Retail Associate",
        company="Other Synthetic",
        role_direction="retail floor",
    ),
}


def _base() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


def _event(
    event_id: str,
    record_id: str,
    field_id: str,
    before: str,
    after: str,
    *,
    open_id: str = "ou_human_fixture",
    omit_operator: bool = False,
    omit_before: bool = False,
    omit_field_value: bool = False,
) -> dict[str, object]:
    payload = copy.deepcopy(_base())
    header = payload["header"]
    event = payload["event"]
    assert isinstance(header, dict)
    assert isinstance(event, dict)
    header["event_id"] = event_id
    if omit_operator:
        event.pop("operator_id", None)
    else:
        operator = event["operator_id"]
        assert isinstance(operator, dict)
        operator["open_id"] = open_id
    action = {
        "record_id": record_id,
        "action": "record_edited",
        "before_value": [{"field_id": field_id, "field_value": before}],
        "after_value": [{"field_id": field_id, "field_value": after}],
    }
    if omit_before:
        action.pop("before_value")
    if omit_field_value:
        action["before_value"] = [{"field_id": field_id}]
    event["action_list"] = [action]
    return payload


class RecordingAttributor:
    """Fixture stand-in for the host model. It can only echo the request it was given."""

    def __init__(self) -> None:
        self.requests: list[AttributionRequest] = []

    def attribute(self, request: AttributionRequest) -> SignalAttribution:
        self.requests.append(request)
        signal = request.signal
        shared = {
            "signal_id": signal.signal_id,
            "event_id": signal.event_id,
            "record_id": signal.record_id,
            "jd_digest": request.jd_digest,
            "original_greeting_digest": request.original_greeting_digest,
            "input_digest": request.input_digest,
        }
        if signal.preference == "Matching Preference / Calibration":
            drafts = [
                MemoryDraft(
                    kind="matching",
                    reason=(
                        f"Human changed match grade from {signal.before_value} "
                        f"to {signal.after_value}."
                    ),
                    notes=[f"{signal.before_value}->{signal.after_value}"],
                )
            ]
            if signal.after_value == "A" and request.role_direction:
                drafts.append(
                    MemoryDraft(
                        kind="search",
                        reason=(
                            f"Grade rose to A for {request.role_direction}; "
                            "prefer this role direction in the next search."
                        ),
                        keywords=[request.role_direction],
                        role_directions=[request.role_direction],
                        exclusions=["retail floor"],
                    )
                )
        elif signal.preference == "Greeting Preference":
            drafts = [
                MemoryDraft(
                    kind="greeting",
                    reason="Human rewrote the generated greeting.",
                    notes=[signal.after_value],
                )
            ]
        else:
            drafts = [
                MemoryDraft(
                    kind="workflow",
                    reason=(
                        "Human changed processing progress; "
                        "this is operational, not a search keyword."
                    ),
                    notes=[f"{signal.before_value}->{signal.after_value}"],
                )
            ]
        return SignalAttribution(**shared, drafts=drafts)


def _inbox() -> SignalInbox:
    return SignalInbox(FIELDS, OPERATORS)


def test_human_changes_match_grade_from_b_to_a() -> None:
    result = _inbox().receive(_base())
    assert result.send_dispatched is False
    assert len(result.human_signals) == 1
    signal = result.human_signals[0]
    assert signal.before_value == "B"
    assert signal.after_value == "A"
    assert signal.preference == "Matching Preference / Calibration"
    assert signal.record_id == "rec_job_data"
    assert signal.event_id == "evt_grade_b_to_a"
    assert signal.create_time == "1608725989000"
    assert signal.update_time == 1717040601
    assert signal.operator_open_id == "ou_human_fixture"
    assert result.observations[0].operator_kind == "human"
    assert result.observations[0].value_state == "present"


def test_human_edits_greeting() -> None:
    result = _inbox().receive(
        _event(
            "evt_greeting",
            "rec_job_data",
            FIELDS.greeting_field_id,
            DATA_GREETING,
            "Shorter greeting focused on pipeline ownership.",
        )
    )
    signal = result.human_signals[0]
    assert signal.preference == "Greeting Preference"
    assert signal.before_value == DATA_GREETING
    assert signal.after_value == "Shorter greeting focused on pipeline ownership."


def test_human_edits_progress_as_workflow_not_search() -> None:
    result = _inbox().receive(
        _event(
            "evt_progress",
            "rec_job_data",
            FIELDS.progress_field_id,
            "待评估",
            "招呼语初稿",
        )
    )
    assert result.human_signals[0].preference == "Workflow / Operational Preference"
    compiler = SignalCompiler(CONTEXTS, RecordingAttributor())
    compiled = compiler.compile(result.human_signals)
    assert {item.kind for item in compiled.memories} == {"workflow"}
    assert compiled.memories[0].keywords == []
    applied = apply_search_memory(
        SearchParameters(keywords=["backend engineer", "retail floor"]),
        compiled.memories,
        candidate_id="CAND_FIXTURE",
    )
    assert applied.after.keywords == ["backend engineer", "retail floor"]
    assert applied.changes == []
    assert applied.ignored_memory_ids == [compiled.memories[0].memory_id]


def test_bot_write_is_not_a_human_signal() -> None:
    result = _inbox().receive(
        _event(
            "evt_bot_grade",
            "rec_job_data",
            FIELDS.match_grade_field_id,
            "B",
            "A",
            open_id="ou_bot_fixture",
        )
    )
    assert result.human_signals == []
    assert result.observations[0].operator_kind == "bot"
    compiled = SignalCompiler(CONTEXTS, RecordingAttributor()).compile(result.human_signals)
    assert compiled.memories == []


def test_duplicate_event_is_not_learned_twice() -> None:
    inbox = _inbox()
    payload = _base()
    first = inbox.receive(payload)
    second = inbox.receive(copy.deepcopy(payload))
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.human_signals == first.human_signals
    attributor = RecordingAttributor()
    compiler = SignalCompiler(CONTEXTS, attributor)
    compiler.compile([*first.human_signals, *second.human_signals])
    assert attributor.requests.__len__() == 1
    assert compiler.calls == 1


def test_same_event_id_with_different_content_is_rejected() -> None:
    inbox = _inbox()
    inbox.receive(_base())
    changed = _base()
    event = changed["event"]
    assert isinstance(event, dict)
    action_list = event["action_list"]
    assert isinstance(action_list, list)
    action = action_list[0]
    assert isinstance(action, dict)
    after = action["after_value"]
    assert isinstance(after, list)
    cell = after[0]
    assert isinstance(cell, dict)
    cell["field_value"] = "C"
    with pytest.raises(ContractValidationError):
        inbox.receive(changed)


def test_missing_operator_or_before_after_is_unknown() -> None:
    missing_operator = _inbox().receive(
        _event("evt_no_operator", "rec_job_data", FIELDS.match_grade_field_id, "B", "A",
               omit_operator=True)
    )
    assert missing_operator.human_signals == []
    assert missing_operator.observations[0].operator_kind == "unknown"
    assert missing_operator.observations[0].operator_open_id is None

    missing_before = _inbox().receive(
        _event("evt_no_before", "rec_job_data", FIELDS.match_grade_field_id, "B", "A",
               omit_before=True)
    )
    assert missing_before.human_signals == []
    assert missing_before.observations[0].value_state == "unknown"
    assert missing_before.observations[0].before_value is None

    missing_value = _inbox().receive(
        _event("evt_no_value", "rec_job_data", FIELDS.greeting_field_id, "old", "new",
               omit_field_value=True)
    )
    assert missing_value.human_signals == []
    assert missing_value.observations[0].value_state == "unknown"


def test_unrecognized_operator_is_unknown_rather_than_human() -> None:
    result = _inbox().receive(
        _event("evt_stranger", "rec_job_data", FIELDS.match_grade_field_id, "B", "A",
               open_id="ou_unlisted")
    )
    assert result.observations[0].operator_kind == "unknown"
    assert result.human_signals == []


def test_gpt_associates_the_record_jd_and_original_greeting() -> None:
    attributor = RecordingAttributor()
    signal = _inbox().receive(_base()).human_signals[0]
    SignalCompiler(CONTEXTS, attributor).compile([signal])
    request = attributor.requests[0]
    assert request.signal.record_id == "rec_job_data"
    assert request.job_id == "JOB_DATA_PLATFORM"
    assert request.jd_text == DATA_JD
    assert request.jd_digest == text_digest(DATA_JD)
    assert request.generated_greeting == DATA_GREETING
    assert request.original_greeting_digest == text_digest(DATA_GREETING)
    assert request.jd_text != OTHER_JD
    assert request.generated_greeting != OTHER_GREETING


def test_gpt_publishes_search_matching_and_greeting_memory() -> None:
    inbox = _inbox()
    grade = inbox.receive(_base()).human_signals
    greeting = inbox.receive(
        _event("evt_greeting", "rec_job_data", FIELDS.greeting_field_id,
               DATA_GREETING, "Shorter greeting focused on pipeline ownership.")
    ).human_signals
    progress = inbox.receive(
        _event("evt_progress", "rec_job_data", FIELDS.progress_field_id, "待评估", "招呼语初稿")
    ).human_signals
    compiled = SignalCompiler(CONTEXTS, RecordingAttributor()).compile(
        [*grade, *greeting, *progress]
    )
    kinds = {item.kind for item in compiled.memories}
    assert {"search", "matching", "greeting", "workflow"} <= kinds
    search = next(item for item in compiled.memories if item.kind == "search")
    matching = next(item for item in compiled.memories if item.kind == "matching")
    greeting_memory = next(item for item in compiled.memories if item.kind == "greeting")
    workflow = next(item for item in compiled.memories if item.kind == "workflow")
    assert search.preference == "Matching Preference / Calibration"
    assert search.keywords == ["data platform"]
    assert search.job_id == "JOB_DATA_PLATFORM"
    assert search.jd_digest == text_digest(DATA_JD)
    assert matching.notes == ["B->A"]
    assert greeting_memory.preference == "Greeting Preference"
    assert greeting_memory.keywords == []
    assert workflow.preference == "Workflow / Operational Preference"
    assert workflow.keywords == []
    assert "not a search keyword" in workflow.reason


def test_next_round_consumer_changes_search_parameters() -> None:
    compiled = SignalCompiler(CONTEXTS, RecordingAttributor()).compile(
        _inbox().receive(_base()).human_signals
    )
    progress = SignalCompiler(CONTEXTS, RecordingAttributor()).compile(
        _inbox().receive(
            _event("evt_progress", "rec_job_data", FIELDS.progress_field_id, "待评估", "招呼语初稿")
        ).human_signals
    )
    base = SearchParameters(keywords=["backend engineer", "retail floor"])
    applied = apply_search_memory(
        base, [*compiled.memories, *progress.memories], candidate_id="CAND_FIXTURE"
    )
    assert applied.after.keywords == ["backend engineer", "data platform"]
    assert applied.after.role_directions == ["data platform"]
    assert applied.after.exclusions == ["retail floor"]
    added = next(change for change in applied.changes if change.op == "add"
                 and change.parameter == "keywords")
    removed = next(change for change in applied.changes if change.op == "remove")
    assert added.value == "data platform"
    assert added.source_event_id == "evt_grade_b_to_a"
    assert "Grade rose to A for data platform" in added.reason
    assert removed.value == "retail floor"
    assert removed.reason == added.reason
    assert progress.memories[0].memory_id in applied.ignored_memory_ids
    before_plan = plan_searches(base.keywords, "boss", runs=[], hits=[], tiers={}, per_site=2)
    after_plan = plan_searches(
        applied.after.keywords, "boss", runs=[], hits=[], tiers={}, per_site=2
    )
    assert [item.term for item in before_plan.chosen] == ["backend engineer", "retail floor"]
    assert [item.term for item in after_plan.chosen] == ["backend engineer", "data platform"]


def test_unapproved_job_does_not_trigger_send() -> None:
    received = _inbox().receive(_base())
    assert received.send_dispatched is False
    assert received.human_signals[0].grants_send is False
    missing = shared_send_decision(
        CurrentSharedProjection(record_id="rec_job_data", progress="招呼语初稿", approval=None),
        approved_values=["已批准"],
    )
    unapproved = shared_send_decision(
        CurrentSharedProjection(record_id="rec_job_data", progress="招呼语初稿", approval="未批准"),
        approved_values=["已批准"],
    )
    looks_approved = shared_send_decision(
        CurrentSharedProjection(record_id="rec_job_data", progress="招呼语初稿", approval="已批准"),
        approved_values=["已批准"],
    )
    assert missing.reason == "approval_missing"
    assert unapproved.reason == "unapproved"
    assert looks_approved.reason == "signal_path_does_not_send"
    assert missing.send_dispatched is unapproved.send_dispatched is False
    assert looks_approved.allowed is False
    assert looks_approved.send_dispatched is False


def test_other_fields_and_other_tables_do_not_become_signals() -> None:
    payload = _event("evt_reason", "rec_job_data", "fld_match_reason", "old reason", "new reason")
    result = _inbox().receive(payload)
    assert result.human_signals == []
    assert result.ignored_field_ids == ["fld_match_reason"]
    other_table = _base()
    event = other_table["event"]
    assert isinstance(event, dict)
    event["table_id"] = "tbl_other"
    assert _inbox().receive(other_table).human_signals == []


def test_attribution_must_cite_the_supplied_jd_and_cannot_reclass_progress() -> None:
    signal = _inbox().receive(
        _event("evt_progress", "rec_job_data", FIELDS.progress_field_id, "待评估", "招呼语初稿")
    ).human_signals[0]

    class SearchOnProgress:
        def attribute(self, request: AttributionRequest) -> SignalAttribution:
            return SignalAttribution(
                signal_id=request.signal.signal_id,
                event_id=request.signal.event_id,
                record_id=request.signal.record_id,
                jd_digest=request.jd_digest,
                original_greeting_digest=request.original_greeting_digest,
                input_digest=request.input_digest,
                drafts=[MemoryDraft(kind="search", reason="invented", keywords=["secret"])],
            )

    with pytest.raises(InvalidProviderOutputError):
        SignalCompiler(CONTEXTS, SearchOnProgress()).compile([signal])

    grade = _inbox().receive(_base()).human_signals[0]

    class WrongJd:
        def attribute(self, request: AttributionRequest) -> SignalAttribution:
            return SignalAttribution(
                signal_id=request.signal.signal_id,
                event_id=request.signal.event_id,
                record_id=request.signal.record_id,
                jd_digest=text_digest(OTHER_JD),
                original_greeting_digest=request.original_greeting_digest,
                input_digest=request.input_digest,
                drafts=[MemoryDraft(kind="matching", reason="wrong source", notes=["B->A"])],
            )

    with pytest.raises(InvalidProviderOutputError):
        SignalCompiler(CONTEXTS, WrongJd()).compile([grade])


def test_jobs_search_plan_uses_published_search_memory(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.app import app
    from jobagent.schemas.memory_signal import PublishedMemoryFile

    compiled = SignalCompiler(CONTEXTS, RecordingAttributor()).compile(
        _inbox().receive(_base()).human_signals
    )
    memory = tmp_path / "memory.json"
    context = tmp_path / "filter.json"
    database = tmp_path / "jobagent.sqlite3"
    memory.write_text(
        PublishedMemoryFile(memories=compiled.memories).model_dump_json(), encoding="utf-8"
    )
    context.write_text(
        json.dumps({"preferred_search_terms": ["backend engineer", "retail floor"]}),
        encoding="utf-8",
    )
    runner = CliRunner()
    common = [
        "jobs", "search-plan", "--filter-context", str(context), "--database", str(database),
        "--per-site", "2", "--site", "boss",
    ]
    plain = runner.invoke(app, common)
    assert plain.exit_code == 0, plain.stdout
    plain_body = json.loads(plain.stdout)
    assert [item["term"] for item in plain_body["boss"]["chosen"]] == [
        "backend engineer", "retail floor",
    ]
    changed = runner.invoke(app, [*common, "--candidate", "CAND_FIXTURE", "--search-memory",
                                   str(memory)])
    assert changed.exit_code == 0, changed.stdout
    body = json.loads(changed.stdout)
    assert [item["term"] for item in body["plans"]["boss"]["chosen"]] == [
        "backend engineer", "data platform",
    ]
    reasons = [item["reason"] for item in body["search_memory"]["boss"]["changes"]]
    assert any("Grade rose to A for data platform" in reason for reason in reasons)


def test_cli_fixture_updates_search_parameters_without_sending(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.app import app
    from jobagent.memory.signal_compile import build_request
    from jobagent.schemas.memory_signal import (
        AppliedSearchParameters,
        AttributionFile,
        CurrentSharedProjection,
        HumanSignalFile,
        JobContextFile,
        PublishedMemoryFile,
        SendGateDecision,
        SignalReceiveResult,
    )

    runner = CliRunner()
    event = tmp_path / "event.json"
    fields = tmp_path / "fields.json"
    operators = tmp_path / "operators.json"
    receipt = tmp_path / "receipt.json"
    event.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    fields.write_text(FIELDS.model_dump_json(), encoding="utf-8")
    operators.write_text(OPERATORS.model_dump_json(), encoding="utf-8")
    args = [
        "memory", "signal-receive", "--event", str(event), "--fields", str(fields),
        "--operators", str(operators), "--receipt", str(receipt),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    received = SignalReceiveResult.model_validate_json(first.stdout)
    assert received.human_signals[0].after_value == "A"
    assert received.send_dispatched is False

    request = build_request(received.human_signals[0], CONTEXTS["rec_job_data"])
    attribution = RecordingAttributor().attribute(request)
    signals = tmp_path / "signals.json"
    contexts = tmp_path / "contexts.json"
    attributions = tmp_path / "attributions.json"
    learned = tmp_path / "learned.json"
    signals.write_text(HumanSignalFile(signals=received.human_signals).model_dump_json(),
                       encoding="utf-8")
    contexts.write_text(JobContextFile(contexts=[CONTEXTS["rec_job_data"]]).model_dump_json(),
                        encoding="utf-8")
    attributions.write_text(AttributionFile(attributions=[attribution]).model_dump_json(),
                            encoding="utf-8")
    compiled = runner.invoke(app, [
        "memory", "signal-compile", "--signals", str(signals), "--contexts", str(contexts),
        "--attributions", str(attributions), "--learned", str(learned),
    ])
    assert compiled.exit_code == 0, compiled.stdout
    published = PublishedMemoryFile.model_validate_json(learned.read_text(encoding="utf-8"))
    assert {item.kind for item in published.memories} >= {"search", "matching"}

    base = tmp_path / "base.json"
    base.write_text(
        SearchParameters(keywords=["backend engineer", "retail floor"]).model_dump_json(),
        encoding="utf-8",
    )
    applied_run = runner.invoke(app, [
        "memory", "apply-search", "--candidate", "CAND_FIXTURE", "--base", str(base),
        "--memories", str(learned),
    ])
    assert applied_run.exit_code == 0, applied_run.stdout
    applied = AppliedSearchParameters.model_validate_json(applied_run.stdout)
    assert applied.after.keywords == ["backend engineer", "data platform"]
    assert any(change.value == "data platform" and "Grade rose to A" in change.reason
               for change in applied.changes)

    projection = tmp_path / "projection.json"
    projection.write_text(
        CurrentSharedProjection(
            record_id="rec_job_data", progress="招呼语初稿", approval="未批准"
        ).model_dump_json(),
        encoding="utf-8",
    )
    gate = runner.invoke(app, [
        "memory", "send-gate", "--projection", str(projection), "--approved", "已批准",
    ])
    assert gate.exit_code == 0, gate.stdout
    decision = SendGateDecision.model_validate_json(gate.stdout)
    assert decision.reason == "unapproved"
    assert decision.send_dispatched is False

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout
    assert SignalReceiveResult.model_validate_json(second.stdout).duplicate is True
    again = runner.invoke(app, [
        "memory", "signal-compile", "--signals", str(signals), "--contexts", str(contexts),
        "--attributions", str(attributions), "--learned", str(learned),
    ])
    assert again.exit_code == 0, again.stdout
    assert PublishedMemoryFile.model_validate_json(
        learned.read_text(encoding="utf-8")
    ).memories == published.memories


def test_missing_job_context_is_not_invented() -> None:
    signal = _inbox().receive(_base()).human_signals[0]
    compiled = SignalCompiler({}, RecordingAttributor()).compile([signal])
    assert compiled.memories == []
    assert compiled.unassociated_signal_ids == [signal.signal_id]
