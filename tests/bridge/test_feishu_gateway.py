"""Synthetic transport fixtures; no real account, business database or sending."""

import json
import subprocess

import pytest

from jobagent.bridge.feishu_gateway import FeishuGateway, LarkCliTransport
from jobagent.errors import ContractValidationError
from jobagent.schemas.feishu import FeishuConfig, FeishuPatch


def settings():
    return FeishuConfig.model_validate({
        "base_token": "BASE_SYNTHETIC", "identity": "user",
        "executable": "synthetic-lark.exe", "timeout_seconds": 8,
        "tables": {"jobs": {
            "table_id": "tblSynthetic",
            "fields": {"assessment": "fldA", "progress": "fldP", "approval": "fldH"},
            "writable": {"generation": ["assessment"], "execution": ["progress"]},
        }},
    })


SCHEMA = {"fields": [
    {"id": "fldA", "name": "Assessment", "type": "text"},
    {"id": "fldP", "name": "Progress", "type": "select",
     "multiple": False, "options": [{"name": "DRAFT"}, {"name": "SENT"}]},
    {"id": "fldH", "name": "Approval", "type": "select",
     "multiple": False, "options": [{"name": "YES"}, {"name": "WAIT"}]},
], "total": 3}


def matrix(value="", *, ids=None, more=False, revision=7):
    return {"fields": ["Approval", "Assessment", "Progress"],
            "field_id_list": ["fldH", "fldA", "fldP"],
            "field_type_list": ["select", "text", "select"],
            "data": [[["WAIT"], value, ["DRAFT"]]],
            "record_id_list": ["recSynthetic"] if ids is None else ids,
            "has_more": more, "rev": revision}


class Transport:
    def __init__(self):
        self.calls = []
        self.current = matrix()
        self.ignore_write = False
        self.fail_write = False

    def call(self, argv):
        self.calls.append(argv)
        if "+field-list" in argv:
            return SCHEMA
        if "+record-list" in argv or "+record-get" in argv:
            return self.current
        assert "+record-batch-update" in argv
        if self.fail_write:
            raise ContractValidationError("Synthetic timeout")
        body = json.loads(argv[argv.index("--json") + 1])
        if not self.ignore_write:
            self.current = matrix(body["update_records"]["recSynthetic"]["fldA"])
        return {}


def query(gateway, **kwargs):
    return gateway.query("jobs", fields=["assessment", "progress", "approval"],
                         conditions=[["assessment", "empty"]], limit=2, offset=0, **kwargs)


def patch(digest, **changes):
    return FeishuPatch.model_validate({
        "table": "jobs", "record_id": "recSynthetic", "role": "generation",
        "expected_digest": digest, "fields": {"assessment": "Grounded synthetic result"},
        "evidence_reference": "SYNTHETIC_REVIEW_1", **changes,
    })


def test_query_maps_live_field_ids_and_preserves_incomplete_page():
    transport = Transport()
    transport.current["has_more"] = True
    result = query(FeishuGateway(settings(), transport))
    assert result.has_more and result.next_offset == 1
    assert result.records[0].fields == {
        "assessment": "", "progress": ["DRAFT"], "approval": ["WAIT"],
    }
    argv = transport.calls[-1]
    assert json.loads(argv[argv.index("--filter-json") + 1])["conditions"] == [["fldA", "empty"]]
    assert "--output" not in argv


def test_execution_query_uses_the_same_live_schema_and_both_state_fields():
    transport = Transport()
    gateway = FeishuGateway(settings(), transport)
    gateway.query("jobs", fields=["approval", "progress"],
                  conditions=[["approval", "intersects", ["YES"]],
                              ["progress", "intersects", ["DRAFT"]]], limit=2, offset=0)
    predicate = json.loads(transport.calls[-1][-1])
    assert predicate["conditions"] == [["fldH", "intersects", ["YES"]],
                                       ["fldP", "intersects", ["DRAFT"]]]


@pytest.mark.parametrize("change", [
    {"record_id_list": []}, {"field_id_list": ["fldH", "fldA"]},
    {"has_more": None}, {"data": [[["WAIT"], "missing column"]]},
])
def test_invalid_or_missing_reads_are_errors_not_successful_zero(change):
    transport = Transport()
    transport.current.update(change)
    with pytest.raises(ContractValidationError):
        query(FeishuGateway(settings(), transport))


def test_patch_reads_current_content_then_verifies_exact_writeback():
    transport = Transport()
    gateway = FeishuGateway(settings(), transport)
    current = gateway.get("jobs", "recSynthetic")
    result = gateway.patch(patch(current.content_digest))
    assert result.status == "verified" and result.verified
    assert result.record.fields["assessment"] == "Grounded synthetic result"
    assert result.concurrency_guarantee == "pre_read_only"
    assert sum("+record-batch-update" in call for call in transport.calls) == 1


def test_stale_content_never_dispatches_a_write():
    transport = Transport()
    gateway = FeishuGateway(settings(), transport)
    current = gateway.get("jobs", "recSynthetic")
    transport.current = matrix("Human edit")
    with pytest.raises(ContractValidationError):
        gateway.patch(patch(current.content_digest))
    assert not any("+record-batch-update" in call for call in transport.calls)


@pytest.mark.parametrize("changes", [
    {"fields": {"approval": ["YES"]}},
    {"fields": {"progress": ["SENT"]}},
    {"fields": {"unmapped_field": "x"}},
])
def test_role_boundary_and_human_approval_fields_cannot_be_written(changes):
    transport = Transport()
    gateway = FeishuGateway(settings(), transport)
    current = gateway.get("jobs", "recSynthetic")
    with pytest.raises(ContractValidationError):
        gateway.patch(patch(current.content_digest, **changes))
    assert not any("+record-batch-update" in call for call in transport.calls)


def test_config_cannot_grant_an_agent_approval_write_permission():
    config = settings().model_dump()
    config["tables"]["jobs"]["writable"]["execution"].append("approval")
    with pytest.raises(ValueError):
        FeishuConfig.model_validate(config)


def test_unknown_write_is_not_retried_and_readback_mismatch_is_not_success():
    for fail, ignore, status in [(True, False, "unknown"), (False, True, "unverified")]:
        transport = Transport()
        transport.fail_write, transport.ignore_write = fail, ignore
        gateway = FeishuGateway(settings(), transport)
        current = gateway.get("jobs", "recSynthetic")
        result = gateway.patch(patch(current.content_digest))
        assert not result.verified and result.status == status
        assert sum("+record-batch-update" in call for call in transport.calls) == 1


def test_select_value_must_exist_in_current_schema():
    transport = Transport()
    gateway = FeishuGateway(settings(), transport)
    current = gateway.get("jobs", "recSynthetic")
    with pytest.raises(ContractValidationError):
        gateway.patch(patch(current.content_digest, role="execution",
                            fields={"progress": ["UNREGISTERED"]}))


def test_material_edits_cannot_preserve_an_existing_approval():
    config = settings().model_dump()
    config["tables"]["jobs"].update(material_fields=["assessment"], approved_values=["YES"])
    transport = Transport()
    transport.current["data"][0][0] = ["YES"]
    gateway = FeishuGateway(FeishuConfig.model_validate(config), transport)
    current = gateway.get("jobs", "recSynthetic")
    with pytest.raises(ContractValidationError):
        gateway.patch(patch(current.content_digest))
    assert not any("+record-batch-update" in call for call in transport.calls)


def test_editable_material_requires_an_explicit_guard_even_if_omitted_from_config():
    class NativeMaterialTransport(Transport):
        def call(self, argv):
            if "+field-list" in argv:
                schema = json.loads(json.dumps(SCHEMA))
                schema["fields"][0]["name"] = "招呼语"
                return schema
            return super().call(argv)

    transport = NativeMaterialTransport()
    gateway = FeishuGateway(settings(), transport)
    current = gateway.get("jobs", "recSynthetic")
    with pytest.raises(ContractValidationError):
        gateway.patch(patch(current.content_digest))


def test_pagination_requires_a_matching_shared_table_revision():
    gateway = FeishuGateway(settings(), Transport())
    with pytest.raises(ContractValidationError):
        gateway.query("jobs", fields=["assessment"], conditions=[], limit=2, offset=1)
    with pytest.raises(ContractValidationError):
        gateway.query("jobs", fields=["assessment"], conditions=[], limit=2, offset=1,
                      expected_table_revision=6)


def test_transport_uses_argv_without_shell_and_checks_business_envelope(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "data": {}}), "")

    monkeypatch.setattr(subprocess, "run", run)
    transport = LarkCliTransport(settings())
    value = json.dumps({"text": 'literal & $(x) "quote"'}, ensure_ascii=False)
    assert transport.call(["base", "+record-batch-update", "--json", value]) == {}
    assert "--as" in calls[0][0] and calls[0][0][-2:] == ["--format", "json"]
    assert value in calls[0][0] and calls[0][1]["shell"] is False

    def denied(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, '{"ok":false,"error":{"subtype":"missing_scope"}}', ""
        )

    monkeypatch.setattr(subprocess, "run", denied)
    with pytest.raises(ContractValidationError):
        transport.call(["base", "+field-list"])
