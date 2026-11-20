"""Shared-source reads and explicitly scoped writes; never creates a business ledger."""

import json
from pathlib import Path
from typing import Annotated

import typer

from jobagent.bridge.feishu_gateway import FeishuGateway, LarkCliTransport
from jobagent.cli.private_io import fail, read_model
from jobagent.errors import JobAgentError
from jobagent.schemas.feishu import FeishuConfig, FeishuPatch, FeishuQuery
from jobagent.schemas.shared_memory import RecordHistoryRequest

feishu_app = typer.Typer(help="Shared Feishu source via the installed official CLI.")
ConfigOption = Annotated[Path, typer.Option("--config")]
RequestOption = Annotated[Path, typer.Option("--request")]
TableOption = Annotated[str, typer.Option("--table")]


def gateway(config: Path) -> FeishuGateway:
    settings = read_model(config, FeishuConfig)
    return FeishuGateway(settings, LarkCliTransport(settings))


@feishu_app.command("schema")
def schema(config: ConfigOption, table: TableOption) -> None:
    """Resolve private semantic mappings against the live field schema."""
    try:
        typer.echo(json.dumps(gateway(config).schema(table), ensure_ascii=False))
    except JobAgentError as error:
        fail(error)


@feishu_app.command("query")
def query(config: ConfigOption, request: RequestOption) -> None:
    """Read a bounded current-state worklist; pagination is not a workflow cursor."""
    try:
        value = read_model(request, FeishuQuery)
        page = gateway(config).query(value.table, fields=value.fields, conditions=value.conditions,
                                     limit=value.limit, offset=value.offset,
                                     expected_table_revision=value.expected_table_revision)
        typer.echo(page.model_dump_json())
    except JobAgentError as error:
        fail(error)


@feishu_app.command("get")
def get_record(
    config: ConfigOption, table: TableOption,
    record_id: Annotated[str, typer.Option("--record-id")],
) -> None:
    """Read one mapped record and its content digest, without creating local state."""
    try:
        result = gateway(config).get(table, record_id)
        typer.echo(result.model_dump_json())
    except JobAgentError as error:
        fail(error)


@feishu_app.command("record-history")
def record_history(config: ConfigOption, request: RequestOption) -> None:
    """Read one job record's history for one field. Does not write or learn."""
    try:
        value = read_model(request, RecordHistoryRequest)
        diff = gateway(config).record_history(
            value.table,
            value.record_id,
            value.field_id,
            operators=value.operators,
            page_size=value.page_size,
            max_pages=value.max_pages,
        )
        typer.echo(diff.model_dump_json())
    except JobAgentError as error:
        fail(error)


@feishu_app.command("patch")
def patch(config: ConfigOption, request: RequestOption) -> None:
    """Write explicit role-allowed fields and verify the exact readback; never send."""
    try:
        result = gateway(config).patch(read_model(request, FeishuPatch))
        typer.echo(result.model_dump_json())
        if not result.verified:
            raise typer.Exit(1)
    except JobAgentError as error:
        fail(error)
