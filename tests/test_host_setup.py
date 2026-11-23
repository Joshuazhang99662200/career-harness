import json

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.setup.host_role import HostBinding, HostRoleRequest, resolve_host_role


@pytest.mark.parametrize(("client", "display"), [
    ("codex", "Codex"), ("ChatGPT", "GPT"), ("gpt", "GPT"), ("gemini", "Gemini"),
    ("muse", "Muse"), ("grok", "Grok"), ("workbuddy", "WorkBuddy"),
    ("Gemini via copied chat text", "当前 AI 助手"), (None, "当前 AI 助手"),
])
def test_first_launch_names_the_actual_host_without_assigning_a_role(client, display):
    result = resolve_host_role(HostRoleRequest(runtime_client=client))
    assert result.host_name == display
    assert result.status == "choose_role"
    assert f"您打算让 {display} 承担什么角色" in result.prompt
    assert "只有您在飞书批准" in result.prompt
    assert result.roles == []
    assert not result.grants_send


@pytest.mark.parametrize(("choice", "roles", "first"), [
    ("A", ["gm"], "personal_facts"),
    ("B", ["em"], "platform_capabilities"),
    ("C", ["gm", "em"], "personal_facts"),
])
def test_only_explicit_choice_routes_initialization(choice, roles, first):
    result = resolve_host_role(HostRoleRequest(host_key="host-a", user_choice=choice))
    assert result.roles == roles
    assert result.first_task == first
    assert result.binding.host_key == "host-a"
    assert not result.grants_send


def test_host_name_override_is_display_only_and_never_copies_another_hosts_role():
    saved = HostBinding(host_key="host-a", role="em")
    result = resolve_host_role(HostRoleRequest(
        host_key="host-b", host_name="WorkBuddy", binding=saved,
    ))
    assert result.host_name == "WorkBuddy"
    assert result.status == "choose_role"
    assert result.roles == []
    assert resolve_host_role(HostRoleRequest(
        runtime_client="Codex", host_name="Muse",
    )).host_name == "Codex"


def test_existing_role_resumes_until_request_or_binding_invalid():
    binding = HostBinding(host_key="host-a", role="gm")
    common = dict(host_key="host-a", binding=binding)
    restored = resolve_host_role(HostRoleRequest(**common))
    assert restored.status == "resume"
    assert restored.prompt is None
    assert restored.roles == ["gm"]
    for change in ({"change_requested": True}, {"binding_invalid": True}):
        assert resolve_host_role(HostRoleRequest(**common, **change)).status == "choose_role"


def test_unknown_host_can_choose_a_session_role_without_storing_a_guessed_binding():
    result = resolve_host_role(HostRoleRequest(user_choice="B"))
    assert result.host_name == "当前 AI 助手"
    assert result.roles == ["em"]
    assert result.binding is None


def test_host_role_cli_resumes_and_does_not_change_the_private_request(tmp_path):
    request = tmp_path / "setup.json"
    content = json.dumps({"host_key": "host-a", "binding": {"host_key": "host-a", "role": "both"}})
    request.write_text(content, encoding="utf-8")
    result = CliRunner().invoke(app, ["setup", "host-role", "--request", str(request)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["roles"] == ["gm", "em"]
    assert request.read_text(encoding="utf-8") == content
