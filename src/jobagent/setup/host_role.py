"""Resolve the current host's CareerHarness role from trusted metadata and user choice."""

from typing import Literal

from pydantic import BaseModel, Field

from jobagent.setup.bootstrap import PrivateInput

Choice = Literal["A", "B", "C"]
Role = Literal["gm", "em", "both"]
RoleUnit = Literal["gm", "em"]
HOST_NAMES = {
    "codex": "Codex", "chatgpt": "GPT", "gpt": "GPT", "gemini": "Gemini",
    "muse": "Muse", "grok": "Grok", "grok bot": "Grok", "workbuddy": "WorkBuddy",
    "claude": "Claude", "claude code": "Claude",
}
CHOICES: dict[Choice, Role] = {"A": "gm", "B": "em", "C": "both"}
ROLE_UNITS: dict[Role, tuple[RoleUnit, ...]] = {
    "gm": ("gm",), "em": ("em",), "both": ("gm", "em"),
}


class HostBinding(PrivateInput):
    host_key: str = Field(min_length=1)
    role: Role


class HostRoleRequest(PrivateInput):
    runtime_client: str | None = None
    host_name: str | None = Field(default=None, max_length=64)
    host_key: str | None = Field(default=None, min_length=1)
    binding: HostBinding | None = None
    binding_invalid: bool = False
    change_requested: bool = False
    user_choice: Choice | None = None


class HostRolePlan(BaseModel):
    status: Literal["choose_role", "resume", "confirmed"]
    host_name: str
    prompt: str | None = None
    binding: HostBinding | None = None
    roles: list[RoleUnit] = Field(default_factory=list)
    first_task: Literal["personal_facts", "platform_capabilities"] | None = None
    grants_send: Literal[False] = False


def resolve_host_role(request: HostRoleRequest) -> HostRolePlan:
    client = (request.runtime_client or "").strip().casefold()
    explicit_name = " ".join((request.host_name or "").split())
    name = HOST_NAMES.get(client) or explicit_name or "当前 AI 助手"
    saved = request.binding
    if request.user_choice is not None:
        role = CHOICES[request.user_choice]
        binding = HostBinding(host_key=request.host_key, role=role) if request.host_key else None
        status: Literal["resume", "confirmed"] = "confirmed"
    elif (saved and request.host_key == saved.host_key
          and not (request.change_requested or request.binding_invalid)):
        role, binding, status = saved.role, saved, "resume"
    else:
        return HostRolePlan(status="choose_role", host_name=name, prompt=_role_prompt(name))
    return HostRolePlan(
        status=status, host_name=name, binding=binding, roles=list(ROLE_UNITS[role]),
        first_task="platform_capabilities" if role == "em" else "personal_facts",
    )


def _role_prompt(name: str) -> str:
    return (
        "您好！CareerHarness 将协助您寻找合适的工作机会，"  # noqa: RUF001
        "包括岗位搜索、招聘沟通、简历优化与持续跟进。\n\n"
        f"您打算让 {name} 承担什么角色？\n\n"  # noqa: RUF001
        "A. 帮您生成交流话术、修订简历\n\n"
        "B. 帮您搜索岗位，与 HR 主动开展交流\n\n"  # noqa: RUF001
        "C. 两者兼备\n\n"
        "只有您在飞书批准当前岗位及其材料后，才会对外发送。"  # noqa: RUF001
    )
