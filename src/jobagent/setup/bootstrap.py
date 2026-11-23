"""Plan Feishu mutations from fresh, privately observed official CLI responses."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jobagent.errors import ContractValidationError

WORKSPACE_NAME = "CareerHarness"
FIELD_TYPES = {"文本": "text", "附件": "attachment", "日期时间": "datetime", "数字": "number"}


@dataclass(frozen=True)
class Signal:
    field: str
    signal_type: str
    domain: str

    @property
    def title(self) -> str:
        return "CH Signal - " + self.signal_type.replace("_", " ").title()


@dataclass(frozen=True)
class Contract:
    tables: dict[str, list[dict[str, Any]]]
    signals: list[Signal]


def read_contract(path: Path) -> Contract:
    """Read the published field and Workflow tables, the only schema source."""
    tables: dict[str, list[dict[str, Any]]] = {}
    signals: list[Signal] = []
    table = ""
    count = 0
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractValidationError("Could not read the Feishu schema contract.") from error
    for line in content.splitlines():
        match = re.fullmatch(r"### (.+)\uFF08(\d+) 列\uFF09", line)
        if line.startswith("##"):
            if table and len(tables[table]) != count:
                raise ContractValidationError("A Feishu contract field count does not match.")
            table = ""
        if match:
            table, count_text = match.groups()
            count = int(count_text)
            tables[table] = []
        if table and line.startswith("| `"):
            name, description = (part.strip() for part in line.split("|")[1:3])
            tables[table].append(_field(name.strip("`"), description))
        if not table and re.fullmatch(r"\| `[^|]+` \| `[^|]+` \| `[^|]+` \|", line):
            parts = [item.strip().strip("`") for item in line.split("|")[1:-1]]
            signals.append(Signal(*parts))
    if len(tables) != 5 or len(signals) != 4:
        raise ContractValidationError("Expected five Feishu tables and four workflows.")
    if any(signal.field not in {field["name"] for field in tables["岗位"]} for signal in signals):
        raise ContractValidationError("A workflow watches a field missing from the Feishu schema.")
    return Contract(tables, signals)


def _field(name: str, description: str) -> dict[str, Any]:
    kind = description.split("\uFF08", 1)[0]
    if description.startswith("单选\uFF1A"):
        options = description.split("\uFF1A", 1)[1].split("/")
        return {
            "name": name, "type": "select", "multiple": False,
            "options": [{"name": option} for option in options],
        }
    if kind == "网址或文本":
        return {"name": name, "type": "text", "style": {"type": "url"}}
    if kind not in FIELD_TYPES:
        raise ContractValidationError("The Feishu contract contains an unsupported field type.")
    return {"name": name, "type": FIELD_TYPES[kind]}


class PrivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidate(PrivateInput):
    base_token: str = Field(min_length=1)
    name: str
    owned: bool
    recognized: bool


class LiveTable(PrivateInput):
    id: str = Field(min_length=1)
    name: str
    fields: list[dict[str, Any]]


class BootstrapSnapshot(PrivateInput):
    auth_verified: bool = False
    configure: bool = False
    create: bool = False
    discovery_complete: bool = False
    candidates: list[Candidate] = Field(default_factory=list)
    bound_base: str | None = None
    created_base: str | None = None
    creation_pending: bool = False
    observed_base: str | None = None
    tables: list[LiveTable] | None = None
    bot_can_write: bool = False
    workflows_complete: bool = False
    workflows: list[dict[str, Any]] = Field(default_factory=list)
    verified_workflows: set[str] = Field(default_factory=set)
    disable_legacy_trace: bool = False
    native_trace_verified: bool = False
    dream_verified: bool = False


class Action(BaseModel):
    command: Literal[
        "+base-create", "+table-create", "+field-create", "+field-update",
        "+workflow-disable",
    ]
    table: str | None = None
    target: str | None = None
    payload: Any = None


class Binding(BaseModel):
    base_token: str
    tables: dict[str, str]
    fields: dict[str, dict[str, str]]
    workflows: dict[str, str]


class BootstrapPlan(BaseModel):
    status: str
    next_actions: list[Action] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    candidate: str | None = None
    binding: Binding | None = None
    trace_status: Literal[
        "not_checked", "inspect_workflows", "workflow_conflict",
        "legacy_workflows_active", "await_native_trace", "ready",
    ] = "not_checked"
    legacy_workflow_ids: list[str] = Field(default_factory=list)
    dream_verified: bool = False


def plan_bootstrap(contract: Contract, snapshot: BootstrapSnapshot) -> BootstrapPlan:
    """Advance one readback gate at a time; never emit speculative writes."""
    if not snapshot.auth_verified:
        return BootstrapPlan(status="auth_required")
    if not snapshot.discovery_complete and not snapshot.bound_base:
        return BootstrapPlan(status="discover")
    candidates = {
        item.base_token: item for item in snapshot.candidates
        if (item.owned and item.recognized) or item.base_token == snapshot.bound_base
    }
    if not snapshot.bound_base and len(candidates) > 1:
        return BootstrapPlan(status="ambiguous", issues=list(candidates))
    if snapshot.created_base and snapshot.created_base not in candidates:
        return BootstrapPlan(status="creation_unconfirmed")
    selected = snapshot.bound_base or next(iter(candidates), None)
    if selected is None:
        if snapshot.creation_pending:
            return BootstrapPlan(status="creation_unconfirmed")
        if any(item.name == WORKSPACE_NAME for item in snapshot.candidates):
            return BootstrapPlan(status="workspace_conflict")
        if not (snapshot.configure and snapshot.create):
            return BootstrapPlan(status="creation_required")
        return BootstrapPlan(status="provision", next_actions=[
            Action(command="+base-create", target=WORKSPACE_NAME, table="岗位",
                   payload=contract.tables["岗位"]),
        ])
    if selected not in candidates or snapshot.observed_base != selected or snapshot.tables is None:
        return BootstrapPlan(status="inspect_base", candidate=selected)
    tables, fields, actions, conflicts = _schema_plan(contract, snapshot.tables)
    if conflicts:
        return BootstrapPlan(status="schema_conflict", candidate=selected, issues=conflicts)
    if actions:
        return _reconcile(snapshot.configure, "reconcile_schema", selected, actions)
    if not snapshot.bot_can_write:
        return BootstrapPlan(status="bot_write_unverified", candidate=selected)
    result = BootstrapPlan(
        status="ready", candidate=selected,
        binding=Binding(base_token=selected, tables=tables, fields=fields, workflows={}),
    )
    if not snapshot.workflows_complete:
        result.trace_status = "inspect_workflows"
        return result
    active, conflicts = _legacy_workflow_plan(contract, snapshot, tables, fields)
    result.legacy_workflow_ids = list(active)
    if conflicts:
        result.trace_status = "workflow_conflict"
        result.issues = conflicts
    elif active:
        result.trace_status = "legacy_workflows_active"
        if snapshot.configure and snapshot.disable_legacy_trace:
            result.next_actions = [
                Action(command="+workflow-disable", table=field, target=workflow_id)
                for workflow_id, field in active.items()
            ]
    else:
        result.trace_status = "ready" if snapshot.native_trace_verified else "await_native_trace"
        result.dream_verified = snapshot.native_trace_verified and snapshot.dream_verified
    return result


def _reconcile(
    configure: bool, status: str, base_token: str, actions: list[Action],
) -> BootstrapPlan:
    issues: list[str] = []
    for action in actions:
        if action.command == "+field-create":
            issues.extend(f"{action.table}.{field['name']}" for field in action.payload)
        elif action.command == "+field-update":
            issues.append(f"{action.table}.{action.payload['name']}")
        elif action.table:
            issues.append(action.table)
    return BootstrapPlan(
        status=status if configure else "configure_required", candidate=base_token,
        next_actions=actions if configure else [], issues=issues,
    )


def _schema_plan(
    contract: Contract, live: list[LiveTable],
) -> tuple[dict[str, str], dict[str, dict[str, str]], list[Action], list[str]]:
    tables: dict[str, str] = {}
    fields: dict[str, dict[str, str]] = {}
    actions: list[Action] = []
    conflicts: list[str] = []
    for name, definitions in contract.tables.items():
        matches = [table for table in live if table.name == name]
        if not matches:
            actions.append(Action(command="+table-create", table=name, payload=definitions))
            continue
        if len(matches) != 1:
            conflicts.append(name)
            continue
        table = matches[0]
        tables[name], fields[name] = table.id, {}
        new_fields = []
        for definition in definitions:
            field = definition["name"]
            found = [item for item in table.fields if item.get("name") == field]
            if not found:
                new_fields.append(definition)
                continue
            if len(found) != 1 or not _compatible(definition, found[0]):
                conflicts.append(f"{name}.{field}")
                continue
            current = found[0]
            field_id = current.get("id")
            if not isinstance(field_id, str) or not field_id:
                conflicts.append(f"{name}.{field}")
                continue
            fields[name][field] = field_id
            if definition["type"] == "select":
                update = _append_options(definition, current)
                if update is None:
                    conflicts.append(f"{name}.{field}")
                elif update:
                    actions.append(Action(command="+field-update", table=name,
                                          target=field_id, payload=update))
        if new_fields:
            actions.append(Action(command="+field-create", table=name,
                                  target=table.id, payload=new_fields))
    return tables, fields, actions, conflicts


def _compatible(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected["name"] == "原岗位链接":
        return actual.get("type") in {"text", "url"}
    if expected["name"] == "更新时间":
        return actual.get("type") in {"datetime", "updated_at"}
    return bool(actual.get("type") == expected["type"])


def _append_options(definition: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    options = current.get("options")
    if (current.get("multiple", False) or current.get("dynamic_options_source") is not None
            or not isinstance(options, list)
            or any(not isinstance(option, dict) or not isinstance(option.get("name"), str)
                   for option in options)):
        return None
    names = {option["name"] for option in options}
    missing = [option for option in definition["options"] if option["name"] not in names]
    if not missing:
        return {}
    return {**definition, **{key: current[key] for key in ("default_value", "description")
                              if key in current}, "options": [*options, *missing]}


def _legacy_workflow_plan(
    contract: Contract, snapshot: BootstrapSnapshot,
    tables: dict[str, str], fields: dict[str, dict[str, str]],
) -> tuple[dict[str, str], list[str]]:
    active: dict[str, str] = {}
    seen: set[str] = set()
    conflicts: list[str] = []
    for signal in contract.signals:
        matches = [existing for existing in snapshot.workflows
                   if _related_workflow(existing, signal, tables, fields)]
        if not matches:
            continue
        if len(matches) != 1 or not _legacy_workflow_matches(matches[0], signal, tables, fields):
            conflicts.append(signal.field)
            continue
        live = matches[0]
        workflow_id = live.get("workflow_id")
        if (not isinstance(workflow_id, str) or not workflow_id or workflow_id in seen
                or live.get("status") not in {"enabled", "disabled"}):
            conflicts.append(signal.field)
            continue
        seen.add(workflow_id)
        if live.get("status") == "enabled":
            active[workflow_id] = signal.field
    return active, conflicts


def _related_workflow(
    existing: dict[str, Any], signal: Signal, tables: dict[str, str],
    fields: dict[str, dict[str, str]],
) -> bool:
    if existing.get("title") == signal.title:
        return True
    steps = existing.get("steps") or []
    writers = [step.get("data") or {} for step in steps if step.get("type") == "AddRecordAction"]
    signal_writers = [writer for writer in writers
                      if writer.get("table_name") in {"Human Signals", tables["Human Signals"]}]
    if not signal_writers:
        return False
    tags = {"signal_type", fields["Human Signals"]["signal_type"]}
    if any(value.get("value") == signal.signal_type
           for writer in signal_writers for field in writer.get("field_values") or []
           if field.get("field_name") in tags for value in field.get("value") or []):
        return True
    watched = {signal.field, fields["岗位"][signal.field]}
    return any(
        item.get("field_name") in watched
        for step in steps if (step.get("data") or {}).get("table_name") in {"岗位", tables["岗位"]}
        for item in (step.get("data") or {}).get("field_watch_info") or []
    )


def _legacy_trace_values(
    signal: Signal, trigger_id: str, fields: dict[str, dict[str, str]],
) -> dict[str, tuple[str, str]]:
    return {
        "source_table": ("text", "岗位"), "source_record_id": ("ref", f"$.{trigger_id}.recordId"),
        "job_title": ("ref", f"$.{trigger_id}.{fields['岗位']['岗位名']}"),
        "field_name": ("text", signal.field), "field_id": ("text", fields["岗位"][signal.field]),
        "signal_type": ("text", signal.signal_type), "memory_domain": ("text", signal.domain),
        "learning_status": ("text", "pending_history_enrichment"),
    }


def _legacy_workflow_matches(
    live: dict[str, Any], signal: Signal, tables: dict[str, str],
    fields: dict[str, dict[str, str]],
) -> bool:
    steps = live.get("steps") or []
    if len(steps) != 2:
        return False
    trigger, action = steps
    if (trigger.get("type") != "SetRecordTrigger" or action.get("type") != "AddRecordAction"
            or not trigger.get("id") or trigger.get("next") != action.get("id")
            or action.get("next") or trigger.get("condition_list")):
        return False
    source, destination = trigger.get("data") or {}, action.get("data") or {}
    field = signal.field
    watch = source.get("field_watch_info")
    if (source.get("table_name") not in {"岗位", tables["岗位"]}
            or destination.get("table_name") not in {"Human Signals", tables["Human Signals"]}
            or not isinstance(watch, list) or len(watch) != 1
            or watch[0].get("field_name") not in {field, fields["岗位"][field]}
            or watch[0].get("operator") or watch[0].get("value")
            or source.get("condition_list") or source.get("record_watch_info")):
        return False
    live_values = {value["field_name"]: value["value"]
                   for value in destination.get("field_values") or []
                   if "field_name" in value and "value" in value}
    for name, (kind, value) in _legacy_trace_values(signal, trigger["id"], fields).items():
        if live_values.get(name, live_values.get(fields["Human Signals"][name])) != [
            {"value_type": kind, "value": value}
        ]:
            return False
    return True
