import json

from typer.testing import CliRunner

from jobagent.cli.app import app
from tests.bridge.test_feishu_gateway import Transport, settings


def test_both_hosts_can_query_without_a_business_database(tmp_path, monkeypatch):
    from jobagent.cli import feishu

    transport = Transport()
    monkeypatch.setattr(feishu, "LarkCliTransport", lambda config: transport)
    config = tmp_path / "config.json"
    config.write_text(settings().model_dump_json(), encoding="utf-8")
    request = tmp_path / "query.json"
    request.write_text(json.dumps({
        "table": "jobs", "fields": ["assessment", "approval", "progress"],
        "conditions": [["assessment", "empty"]], "limit": 2, "offset": 0,
    }), encoding="utf-8")
    reply = CliRunner().invoke(app, ["feishu", "query", "--config", str(config),
                                   "--request", str(request)])
    assert reply.exit_code == 0, reply.output
    assert json.loads(reply.output)["records"][0]["record_id"] == "recSynthetic"
    assert not list(tmp_path.glob("*.sqlite*"))


def test_cli_rejects_missing_config_without_dispatch(tmp_path):
    result = CliRunner().invoke(app, ["feishu", "schema", "--config", str(tmp_path / "gone"),
                                    "--table", "jobs"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
