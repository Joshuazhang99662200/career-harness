"""Behavior of the two decisions shared by every Initial Setup host."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.setup.bootstrap import BootstrapSnapshot, plan_bootstrap, read_contract
from jobagent.setup.platforms import PlatformSettings, Probe, route_platforms

CONTRACT = Path(__file__).parents[1] / "skills/job-hunting/references/feishu-schema-bootstrap.md"


def plan(**changes):
    return plan_bootstrap(read_contract(CONTRACT), BootstrapSnapshot.model_validate(changes))


def workspace():
    return {"base_token": "synthetic-base", "name": "CareerHarness", "owned": True,
            "recognized": True}


def live_tables():
    return [
        {"id": f"table-{i}", "name": table, "fields": [
            {"id": f"field-{i}-{j}", **field} for j, field in enumerate(fields)
        ]}
        for i, (table, fields) in enumerate(read_contract(CONTRACT).tables.items())
    ]


def test_one_contract_has_80_fields_and_four_workflows():
    contract = read_contract(CONTRACT)
    assert [len(fields) for fields in contract.tables.values()] == [20, 5, 19, 19, 17]
    assert [w.signal_type for w in contract.signals] == [
        "approval_decision", "workflow_outcome", "greeting_revision", "matching_correction",
    ]
    assert contract.tables["岗位"][3]["options"][-1] == {"name": "LinkedIn"}


def test_creation_requires_verified_auth_complete_discovery_and_authority():
    assert plan().status == "auth_required"
    assert plan(auth_verified=True).status == "discover"
    assert plan(auth_verified=True, discovery_complete=True).status == "creation_required"
    result = plan(auth_verified=True, discovery_complete=True, configure=True, create=True)
    assert result.next_actions[0].command == "+base-create"
    assert len(result.next_actions[0].payload) == 20


def test_two_candidates_block_both_unbound_hosts_before_mutation():
    candidates = [workspace(), {**workspace(), "base_token": "another-base"}]
    result = plan(auth_verified=True, discovery_complete=True, candidates=candidates,
                  configure=True, create=True)
    assert result.status == "ambiguous"
    assert result.next_actions == []


def test_new_binding_waits_for_rediscovery_even_if_base_create_returned_an_id():
    result = plan(auth_verified=True, created_base="synthetic-base", configure=True, create=True)
    assert result.status == "discover"
    result = plan(auth_verified=True, discovery_complete=True, created_base="synthetic-base",
                  configure=True, create=True)
    assert result.status == "creation_unconfirmed"
    assert result.next_actions == []


def test_unknown_create_response_does_not_repeat_creation():
    result = plan(auth_verified=True, discovery_complete=True, configure=True, create=True,
                  creation_pending=True)
    assert result.status == "creation_unconfirmed"
    assert result.next_actions == []


def test_resume_fills_only_missing_objects_and_never_overwrites_type_conflicts():
    tables = live_tables()
    tables[0]["fields"].pop()
    common = dict(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, bot_can_write=True)
    result = plan(**common, tables=tables[:-1])
    assert {action.command for action in result.next_actions} == {"+field-create", "+table-create"}
    assert result.next_actions[0].payload[0]["name"] == "GPT处理"
    tables[1]["fields"][2]["type"] = "text"
    conflict = plan(**common, tables=tables)
    assert conflict.status == "schema_conflict"
    assert conflict.next_actions == []


def test_appending_select_options_preserves_existing_ids_and_metadata():
    tables = live_tables()
    options = tables[0]["fields"][3]["options"]
    options.pop()
    options.insert(0, {"id": "legacy-option", "name": "Legacy", "color": "blue"})
    result = plan(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, tables=tables)
    update = result.next_actions[0]
    assert update.command == "+field-update"
    assert update.payload["options"] == [*options, {"name": "LinkedIn"}]


def test_read_only_audit_identifies_exact_field_without_emitting_writes():
    tables = live_tables()
    tables[0]["fields"][3]["options"].pop()
    result = plan(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", tables=tables)
    assert result.status == "configure_required"
    assert result.issues == ["岗位.招聘平台"]
    assert result.next_actions == []


def test_existing_workflow_enable_trigger_verification_and_binding_are_separate():
    common = dict(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, tables=live_tables(),
                  workflows_complete=True)
    assert plan(**common).status == "bot_write_unverified"
    common["bot_can_write"] = True
    fresh = plan(**common)
    assert [action.command for action in fresh.next_actions] == ["+workflow-create"] * 4
    workflows = [dict(action.payload, workflow_id=f"flow-{i}", status="disabled")
                 for i, action in enumerate(fresh.next_actions)]
    result = plan(**common, workflows=workflows)
    assert [action.command for action in result.next_actions] == ["+workflow-enable"] * 4
    for workflow in workflows:
        workflow["status"] = "enabled"
    verify = plan(**common, workflows=workflows)
    assert verify.status == "verify_triggers"
    assert verify.next_actions == []
    ready = plan(**common, workflows=workflows, verified_workflows=[f"flow-{i}" for i in range(4)])
    assert ready.status == "ready"
    assert len(ready.binding.tables) == 5
    assert len(ready.binding.workflows) == 4
    assert not ready.dream_verified


def test_wrong_workflow_reference_and_duplicate_listener_are_conflicts():
    common = dict(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, tables=live_tables(),
                  workflows_complete=True, bot_can_write=True)
    action = plan(**common).next_actions[0]
    workflow = dict(action.payload, workflow_id="flow-1", status="enabled")
    extra = {**workflow, "title": "Duplicate", "workflow_id": "flow-2"}
    assert plan(**common, workflows=[workflow, extra]).status == "workflow_conflict"
    workflow["steps"][1]["data"]["table_name"] = "Other"
    assert plan(**common, workflows=[workflow]).status == "workflow_conflict"


def test_unrelated_workflows_are_preserved_even_if_they_watch_a_setup_field():
    common = dict(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, tables=live_tables(),
                  workflows_complete=True, bot_can_write=True)
    actions = plan(**common).next_actions
    extra = dict(actions[0].payload, title="Unrelated", workflow_id="unrelated", status="enabled")
    extra["steps"][1]["data"]["table_name"] = "Other"
    result = plan(**common, workflows=[extra])
    assert result.status == "reconcile_workflows"
    assert len(result.next_actions) == 4


def test_same_signal_label_with_wrong_watcher_is_never_created_in_parallel():
    common = dict(auth_verified=True, discovery_complete=True, candidates=[workspace()],
                  observed_base="synthetic-base", configure=True, tables=live_tables(),
                  workflows_complete=True, bot_can_write=True)
    actions = plan(**common).next_actions
    extra = dict(actions[0].payload, title="Other title", workflow_id="conflict", status="enabled")
    extra["steps"][0]["data"]["field_watch_info"] = [{"field_name": "公司"}]
    result = plan(**common, workflows=[extra])
    assert result.status == "workflow_conflict"
    assert result.next_actions == []


def probe(platform="boss", kind="browser_gui", **changes):
    data = dict(platform=platform, kind=kind, endpoint=f"{platform}:{kind}",
                host="host-a", session="session-a", available=True, login="ready",
                search_authorized=True, list_verified=True, jd_verified=True, page_verified=True)
    return Probe.model_validate(data | changes)


@pytest.mark.parametrize(("mode", "kind", "strategy"), [
    ("interactive", "browser_gui", "rank_candidates"),
    ("scheduled", "mcp", "query_then_rank"),
])
def test_router_distinguishes_gui_background_and_a_blocked_platform(mode, kind, strategy):
    settings = PlatformSettings(selected=["boss", "ats"], schedule="confirmed schedule",
                                per_platform_quota={"boss": 3}, hard_filters={})
    routes = route_platforms(settings, [probe(), probe(kind="mcp", background_verified=True,
                                                       scheduled_authorized=True)],
                             host="host-a", session="session-a", mode=mode)
    assert routes["boss"].kind == kind
    assert routes["boss"].search_strategy == strategy
    assert not routes["boss"].execution_verified
    assert routes["ats"].status == "unsupported"


def test_router_denies_stale_missing_login_and_unverified_pagination():
    settings = PlatformSettings(selected=["boss"])
    for candidate, status in (
        (probe(session="previous"), "needs_probe"),
        (probe(login="required"), "needs_login"),
        (probe(page_verified=False), "unverified"),
        (probe(search_authorized=False), "needs_authorization"),
    ):
        routes = route_platforms(settings, [candidate], host="host-a", session="session-a",
                                 mode="interactive")
        assert routes["boss"].status == status


def test_manual_override_roundtrips_and_forbidden_route_never_falls_back():
    settings = PlatformSettings(selected=["boss"], routing_mode="override",
                                overrides={"boss": "browser_gui"},
                                prohibited={"boss": ["browser_gui"]})
    restored = PlatformSettings.model_validate_json(settings.model_dump_json())
    assert restored == settings
    routes = route_platforms(restored, [probe(), probe(kind="mcp")],
                             host="host-a", session="session-a", mode="interactive")
    assert routes["boss"].status == "forbidden"
    assert routes["boss"].endpoint is None
    assert restored.schedule is None and restored.hard_filters is None


def test_router_needs_real_pagination_and_scheduled_operation_authorization():
    settings = PlatformSettings(selected=["boss"], schedule="confirmed schedule",
                                per_platform_quota={"boss": 3}, hard_filters={})
    routes = route_platforms(settings, [probe(kind="mcp", background_verified=True)],
                             host="host-a", session="session-a", mode="scheduled")
    assert routes["boss"].status == "no_background_route"


def test_login_required_on_one_route_allows_an_independently_verified_route():
    settings = PlatformSettings(selected=["boss"])
    routes = route_platforms(settings, [probe(login="required"), probe(kind="mcp")],
                             host="host-a", session="session-a", mode="interactive")
    assert routes["boss"].kind == "mcp"


def test_both_roles_can_share_choices_without_reusing_other_hosts_probes(tmp_path):
    request = tmp_path / "synthetic-settings.json"
    settings = PlatformSettings(selected=["boss", "ats"])
    gm = dict(settings=settings.model_dump(), mode="interactive", host="host-a",
              session="session-a", probes=[probe().model_dump()])
    em = dict(gm, host="host-b", session="session-b", probes=[
        *gm["probes"], probe(kind="mcp", host="host-b", session="session-b").model_dump(),
    ])
    routes = []
    for host_request in (gm, em):
        request.write_text(json.dumps(host_request), encoding="utf-8")
        result = CliRunner().invoke(app, ["setup", "platform-routes", "--request", str(request)])
        assert result.exit_code == 0, result.output
        routes.append(json.loads(result.output))
    assert routes[0].keys() == routes[1].keys() == {"boss", "ats"}
    assert [route["boss"]["kind"] for route in routes] == ["browser_gui", "mcp"]
    assert {route["ats"]["status"] for route in routes} == {"unsupported"}
    assert all(route["boss"]["execution_verified"] is False for route in routes)


def test_setup_cli_is_a_read_only_planner(tmp_path):
    request = tmp_path / "synthetic-bootstrap.json"
    request.write_text('{"auth_verified": true, "discovery_complete": true}', encoding="utf-8")
    result = CliRunner().invoke(app, [
        "setup", "feishu-plan", "--contract", str(CONTRACT), "--request", str(request),
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "creation_required"


def test_url_is_an_official_text_style_in_create_requests():
    link = next(field for field in read_contract(CONTRACT).tables["岗位"]
                if field["name"] == "原岗位链接")
    assert link == {"name": "原岗位链接", "type": "text", "style": {"type": "url"}}
