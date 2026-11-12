from datetime import UTC, datetime

from tests.rules.test_evaluation import profile

BASE_VALUES = {
    "QUERIES_PER_SITE_PER_ROUND": 2,
    "TOP_PER_QUERY": 7,
    "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": 19,
    "DETAIL_CAP_PER_DAY": 37,
}

PLATFORMS = ["liepin", "ats_boards"]
METHODS = [
    {"kind": "mcp", "sites": ["liepin"], "how": "Liepin MCP job search through the call gateway"},
    {"kind": "agent_proposed", "sites": ["ats_boards"], "how": "Read Greenhouse/Ashby boards"},
]
SOURCING_VALUES = BASE_VALUES | {"SOURCING_PLATFORMS": PLATFORMS, "SOURCING_METHODS": METHODS}


def preparation(mode="ordinary_run", **changes):
    from jobagent.schemas.configuration import ConfigurationPreparationRequest

    return ConfigurationPreparationRequest(
        candidate_id="CAND_SYNTHETIC",
        task_id="TASK_SYNTHETIC",
        task_type="sourcing",
        mode=mode,
        **changes,
    )


def owner_request(**changes):
    from jobagent.schemas.dynamic_rules import OwnerChangeRequest

    data = dict(
        candidate_id="CAND_SYNTHETIC",
        names=["TOP_PER_QUERY"],
        owner_text="Change the per-query limit for my future tasks.",
        source_reference="synthetic owner message",
        actor_id="synthetic owner",
        requested_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    return OwnerChangeRequest.model_validate(data | changes)


def test_only_initial_setup_questions_for_missing_values():
    from jobagent.rules.preparation import prepare_configuration

    initial = prepare_configuration(preparation("initial_setup"), None, initialized=False)
    ordinary = prepare_configuration(preparation(), None, initialized=False)
    assert initial.ask_user and initial.status == "needs_user_decision"
    assert {field.name for field in initial.fields} == set(SOURCING_VALUES)
    # Platforms first; the per-platform method is asked once platforms are chosen.
    assert len(initial.questions) == 5
    assert any("SOURCING_PLATFORMS" in q for q in initial.questions)
    assert not any("SOURCING_METHODS" in q for q in initial.questions)
    assert not ordinary.ask_user and ordinary.questions == [] and not ordinary.ready
    assert ordinary.status == "blocked_by_missing_configuration"


def test_completed_first_form_needs_only_machine_initialization():
    from jobagent.rules.preparation import prepare_configuration

    result = prepare_configuration(
        preparation("initial_setup"), profile(SOURCING_VALUES), initialized=False
    )
    assert result.status == "ready_to_initialize" and result.can_initialize
    assert not result.ask_user and not result.ready


def test_initialized_profile_reuses_values_across_task_types_and_setup_requests():
    from jobagent.rules.preparation import prepare_configuration

    snapshot = profile(SOURCING_VALUES)
    for kind in ["sourcing", "research", "recovery", "new-task-type"]:
        request = preparation("initial_setup").model_copy(update={"task_type": kind})
        result = prepare_configuration(request, snapshot, initialized=True)
        assert result.mode == "ordinary_run" and result.ready
        assert not result.ask_user and result.questions == []
        assert result.rules_version == snapshot.version
        expected = SOURCING_VALUES if kind == "sourcing" else BASE_VALUES
        assert {field.name: field.value for field in result.fields} == expected


def test_missing_or_conflicting_ordinary_config_never_reopens_questions():
    from jobagent.rules.preparation import prepare_configuration

    missing = prepare_configuration(preparation(), profile({"TOP_PER_QUERY": 7}), initialized=True)
    conflict = prepare_configuration(
        preparation(conflicts=["source_policy_conflict"]),
        profile(SOURCING_VALUES),
        initialized=True,
    )
    unsupported = prepare_configuration(
        preparation(required_names=["FIRST_LAUNCH_MIN_JD"]),
        profile(SOURCING_VALUES | {"FIRST_LAUNCH_MIN_JD": 3}),
        initialized=True,
    )
    for result in [missing, conflict, unsupported]:
        assert not result.ask_user and not result.ready and result.questions == []
    assert missing.status == "blocked_by_missing_configuration"
    assert conflict.status == "blocked_by_conflict"
    assert unsupported.status == "unsupported_consumer"


def test_explicit_owner_change_asks_only_named_fields():
    from jobagent.rules.preparation import prepare_configuration

    denied = prepare_configuration(
        preparation("owner_requested_change"), profile(BASE_VALUES), initialized=True
    )
    accepted = prepare_configuration(
        preparation("owner_requested_change", owner_request=owner_request()),
        profile(BASE_VALUES),
        initialized=True,
    )
    assert not denied.ask_user and denied.status == "blocked_by_conflict"
    assert accepted.ask_user and not accepted.ready
    assert len(accepted.questions) == 1 and "TOP_PER_QUERY" in accepted.questions[0]
    assert "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND" not in accepted.questions[0]


def test_other_candidate_or_stale_version_cannot_become_ready():
    import pytest

    from jobagent.errors import ContractValidationError
    from jobagent.rules.preparation import prepare_configuration

    with pytest.raises(ContractValidationError, match="candidate"):
        prepare_configuration(
            preparation(), profile(BASE_VALUES, candidate_id="CAND_OTHER"), initialized=True
        )
    result = prepare_configuration(
        preparation(expected_version="sha256:old"), profile(BASE_VALUES), initialized=True
    )
    assert not result.ask_user and result.status == "blocked_by_conflict"


def test_future_owner_request_cannot_open_configuration_questions():
    from jobagent.rules.preparation import prepare_configuration

    result = prepare_configuration(
        preparation("owner_requested_change", owner_request=owner_request()),
        profile(BASE_VALUES),
        initialized=True,
        now=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert not result.ask_user and result.questions == []
    assert result.status == "blocked_by_conflict"


def test_exact_change_question_displays_round_scope_without_changing_legacy_serialization():
    from jobagent.rules.service import make_proposal
    from tests.rules.test_dynamic_registry import request

    snapshot = profile(BASE_VALUES)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = snapshot.version
    change.provenance.decided_at = datetime(2026, 10, 2, tzinfo=UTC)
    change.owner_request = owner_request(scope="round", run_id="SYNTHETIC_ROUND")
    proposal = make_proposal(change, snapshot, now=change.provenance.decided_at)
    assert "round SYNTHETIC_ROUND only" in proposal.question
    assert "reusable settings unchanged" in proposal.question
    legacy = request()
    assert "owner_request" not in legacy.model_dump(mode="json")
    assert "Scope:" not in make_proposal(legacy, None, now=legacy.provenance.decided_at).question


def test_owner_request_older_than_current_field_decision_never_reopens_questions():
    from jobagent.rules.preparation import prepare_configuration
    from jobagent.rules.service import activate_proposal, make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from tests.rules.test_dynamic_registry import request

    base = profile(BASE_VALUES)
    at = datetime(2026, 10, 2, tzinfo=UTC)
    original = owner_request(requested_at=at)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = base.version
    change.provenance.decided_at = at
    change.owner_request = original
    proposal = make_proposal(change, base, now=at)
    current = activate_proposal(
        proposal,
        RuleConfirmation(
            proposal_id=proposal.proposal_id,
            question_digest=proposal.question_digest,
            answer="Synthetic original approval",
            actor_id="synthetic owner",
            confirmed_at=at,
        ),
        base,
    )
    result = prepare_configuration(
        preparation("owner_requested_change", owner_request=original),
        current,
        initialized=True,
        now=at,
    )
    assert not result.ask_user and result.questions == [] and result.status == "blocked_by_conflict"


def test_sourcing_asks_platforms_first_then_the_method_for_each():
    from jobagent.rules.preparation import prepare_configuration

    first = prepare_configuration(preparation("initial_setup"), None, initialized=False)
    assert {"SOURCING_PLATFORMS", "SOURCING_METHODS"} <= {field.name for field in first.fields}
    # Initialized before these existed: ask platforms only, reopen nothing else.
    later = prepare_configuration(preparation(), profile(BASE_VALUES), initialized=True)
    assert later.status == "needs_user_decision" and not later.ready
    assert len(later.questions) == 1 and "SOURCING_PLATFORMS" in later.questions[0]
    chosen = prepare_configuration(
        preparation(), profile(BASE_VALUES | {"SOURCING_PLATFORMS": PLATFORMS}), initialized=True
    )
    assert len(chosen.questions) == 1 and "SOURCING_METHODS" in chosen.questions[0]
    ready = prepare_configuration(preparation(), profile(SOURCING_VALUES), initialized=True)
    assert ready.ready and not ready.ask_user


def test_every_chosen_platform_needs_a_method_and_methods_stay_on_chosen_platforms():
    from jobagent.rules.preparation import prepare_configuration

    uncovered = BASE_VALUES | {
        "SOURCING_PLATFORMS": ["liepin", "boss", "ats_boards"],
        "SOURCING_METHODS": METHODS,
    }
    result = prepare_configuration(preparation(), profile(uncovered), initialized=True)
    assert result.status == "blocked_by_conflict" and not result.ready
    assert result.reasons == ["sourcing_methods_do_not_cover:boss"]
    stray = BASE_VALUES | {"SOURCING_PLATFORMS": ["liepin"], "SOURCING_METHODS": METHODS}
    result = prepare_configuration(preparation(), profile(stray), initialized=True)
    assert result.reasons == ["sourcing_method_off_platform:ats_boards"]


def test_other_tasks_do_not_need_a_search_method():
    from jobagent.rules.preparation import prepare_configuration

    request = preparation().model_copy(update={"task_type": "research"})
    result = prepare_configuration(request, profile(BASE_VALUES), initialized=True)
    names = {field.name for field in result.fields}
    assert result.ready and not names & {"SOURCING_PLATFORMS", "SOURCING_METHODS"}


def test_platforms_are_known_ids_or_a_named_other():
    import pytest

    from jobagent.errors import ContractValidationError
    from jobagent.rules.registry import validate_value

    validate_value("SOURCING_PLATFORMS", ["boss", "liepin", "linkedin", "zhaopin", "ats_boards"])
    validate_value("SOURCING_PLATFORMS", ["other:某行业垂直招聘站"])
    for bad in ([], ["monster"], ["other:"], ["boss", "boss"]):
        with pytest.raises(ContractValidationError):
            validate_value("SOURCING_PLATFORMS", bad)


def test_a_search_method_must_name_a_known_kind_sites_and_a_concrete_how():
    import pytest

    from jobagent.errors import ContractValidationError
    from jobagent.rules.registry import validate_value

    validate_value("SOURCING_METHODS", METHODS)
    for bad in (
        [],
        [{"kind": "scrape_everything", "sites": ["x"], "how": "y"}],
        [{"kind": "mcp", "sites": [], "how": "Liepin MCP"}],
        [{"kind": "user_specified", "sites": ["boss"], "how": " "}],
        [{"kind": "mcp", "sites": ["liepin"]}],
        [{"kind": "mcp", "sites": ["company sites"], "how": "Not a platform id"}],
    ):
        with pytest.raises(ContractValidationError):
            validate_value("SOURCING_METHODS", bad)


def test_enumerable_fields_carry_their_choices_and_numbers_get_none():
    from jobagent.rules.preparation import prepare_configuration
    from jobagent.rules.registry import SOURCING_METHOD_KINDS, SOURCING_PLATFORM_IDS

    request = preparation("initial_setup", required_names=["SALARY_COMPARE_MODE"])
    by_name = {f.name: f for f in prepare_configuration(request, None, initialized=False).fields}
    platforms = by_name["SOURCING_PLATFORMS"]
    assert platforms.multiple and {c.value for c in platforms.choices} == SOURCING_PLATFORM_IDS
    assert all(c.label for c in platforms.choices)
    assert {c.value for c in by_name["SOURCING_METHODS"].choices} == SOURCING_METHOD_KINDS
    assert {c.value for c in by_name["SALARY_COMPARE_MODE"].choices} == {
        "upper_bound",
        "lower_bound",
    }
    assert not by_name["SALARY_COMPARE_MODE"].multiple
    # Numbers are the person's to decide: no option list that could pass as a default.
    assert by_name["TOP_PER_QUERY"].choices == []


def test_display_task_asks_the_person_which_front_ends_to_show():
    from jobagent.rules.preparation import prepare_configuration
    from jobagent.rules.registry import DISPLAY_FRONTEND_IDS

    request = preparation("initial_setup").model_copy(update={"task_type": "display"})
    first = prepare_configuration(request, None, initialized=False)
    [field] = [f for f in first.fields if f.name == "DISPLAY_FRONTENDS"]
    assert field.multiple and {c.value for c in field.choices} == DISPLAY_FRONTEND_IDS
    assert {"react", "feishu_bitable"} <= DISPLAY_FRONTEND_IDS
    assert any("DISPLAY_FRONTENDS" in q for q in first.questions)
    # Initialized before the variable existed: asked once, nothing else reopens.
    later = prepare_configuration(
        preparation().model_copy(update={"task_type": "display"}),
        profile(BASE_VALUES), initialized=True,
    )
    assert later.status == "needs_user_decision"
    assert len(later.questions) == 1 and "DISPLAY_FRONTENDS" in later.questions[0]
    chosen = prepare_configuration(
        preparation().model_copy(update={"task_type": "display"}),
        profile(BASE_VALUES | {"DISPLAY_FRONTENDS": ["feishu_bitable"]}), initialized=True,
    )
    assert chosen.ready and not chosen.ask_user


def test_front_ends_are_known_ids_or_any_named_other():
    import pytest

    from jobagent.errors import ContractValidationError
    from jobagent.rules.registry import validate_value

    validate_value("DISPLAY_FRONTENDS", ["react", "muse", "feishu_bitable"])
    validate_value("DISPLAY_FRONTENDS", ["other:Notion 数据库", "feishu_bitable"])
    for bad in ([], ["slack"], ["other:"], ["react", "react"], ["other:a\nb"]):
        with pytest.raises(ContractValidationError):
            validate_value("DISPLAY_FRONTENDS", bad)
