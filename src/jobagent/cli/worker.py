"""Explicit one-shot worker handoffs; no browser driver, approvals or scheduler."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from pydantic import ValidationError

from jobagent.bridge.feishu_gateway import FeishuGateway, LarkCliTransport
from jobagent.bridge.worker import SharedJobReader, WorkerGateway
from jobagent.cli.private_io import read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.feishu import FeishuConfig, FeishuRecord, SharedSendPolicy
from jobagent.schemas.worker import WorkerFetchRequest, WorkerReadback
from jobagent.sources import SourceRegistry
from jobagent.storage.database import Database

worker_app = typer.Typer(
    help="Typed local worker handoffs and single approved greetings.", no_args_is_help=True
)
DatabaseOption = Annotated[Path, typer.Option("--database", help="Explicit local database path.")]
SessionOption = Annotated[str, typer.Option("--session", help="Owner of the platform lease.")]
RecordOption = Annotated[str | None, typer.Option("--record-id")]
FixtureOption = Annotated[
    Path | None,
    typer.Option("--shared-fixture", help="Local current-record fixture, reread each call."),
]
FeishuConfigOption = Annotated[Path | None, typer.Option("--feishu-config")]
TableOption = Annotated[str | None, typer.Option("--table")]
ApprovedOption = Annotated[list[str] | None, typer.Option("--approved")]
ReadyOption = Annotated[list[str] | None, typer.Option("--ready-progress")]
ModelT = TypeVar("ModelT", bound=ContractModel)


def _load(path: Path, contract: type[ModelT]) -> ModelT:
    try:
        return contract.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Worker input does not satisfy the required contract.",
            details={"contract": contract.__name__, "file_name": path.name},
        ) from error


class _FixtureSharedReader:
    """Read the fixture file on every call. This is not a live Bitable query."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def current(self, record_id: str) -> FeishuRecord:
        record = read_model(self.path, FeishuRecord)
        if record.record_id != record_id:
            raise ContractValidationError("Shared fixture is for a different record.")
        return record


class _GatewaySharedReader:
    def __init__(self, gateway: FeishuGateway, table: str) -> None:
        self.gateway = gateway
        self.table = table

    def current(self, record_id: str) -> FeishuRecord:
        return self.gateway.get(self.table, record_id)


def _gateway(
    path: Path,
    sources_dir: Path | None = None,
    *,
    shared_fixture: Path | None = None,
    feishu_config: Path | None = None,
    table: str | None = None,
    record_id: str | None = None,
    approved: list[str] | None = None,
    ready_progress: list[str] | None = None,
) -> WorkerGateway:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    if shared_fixture is not None and feishu_config is not None:
        raise ContractValidationError("Pass either a shared fixture or a Feishu config.")
    shared: SharedJobReader | None = None
    policy = None
    if record_id and approved and ready_progress and (shared_fixture or feishu_config):
        policy = SharedSendPolicy(approved_values=approved, ready_progress=ready_progress)
        if shared_fixture is not None:
            shared = _FixtureSharedReader(shared_fixture)
        elif feishu_config is not None and table is not None:
            config = read_model(feishu_config, FeishuConfig)
            shared = _GatewaySharedReader(FeishuGateway(config, LarkCliTransport(config)), table)
        else:
            shared = None
            policy = None
    return WorkerGateway(
        database,
        manifests=SourceRegistry.default(sources_dir).all(),
        shared=shared,
        shared_record_id=record_id,
        send_policy=policy,
    )


def _run(action: Callable[[], ContractModel | list[ContractModel]]) -> None:
    try:
        result = action()
        if isinstance(result, ContractModel):
            typer.echo(result.model_dump_json(indent=2))
        else:
            typer.echo(
                json.dumps(
                    [i.model_dump(mode="json") for i in result], ensure_ascii=False, indent=2
                )
            )
    except JobAgentError as error:
        typer.echo(
            json.dumps(
                {"error": {"code": error.code, "message": error.message, "details": error.details}},
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=1) from error


@worker_app.command("ingest")
def ingest(
    request_path: Path,
    database: DatabaseOption,
    sources_dir: Annotated[Path | None, typer.Option("--sources-dir")] = None,
) -> None:
    """Validate observations and commit jobs plus their completion event atomically."""

    def action() -> ContractModel:
        request = _load(request_path, WorkerFetchRequest)
        return _gateway(database, sources_dir).ingest(request)

    _run(action)


@worker_app.command("claim-greeting")
def claim_greeting(
    batch_id: str,
    platform: Annotated[str, typer.Option("--platform")],
    session: SessionOption,
    database: DatabaseOption,
    record_id: RecordOption = None,
    shared_fixture: FixtureOption = None,
    feishu_config: FeishuConfigOption = None,
    table: TableOption = None,
    approved: ApprovedOption = None,
    ready_progress: ReadyOption = None,
) -> None:
    """Reserve one item only after a fresh shared approval and progress read."""
    _run(lambda: _gateway(
        database, shared_fixture=shared_fixture, feishu_config=feishu_config, table=table,
        record_id=record_id, approved=approved, ready_progress=ready_progress,
    ).claim_greeting(batch_id, platform, session))


@worker_app.command("authorize-greeting")
def authorize_greeting(
    task_id: str,
    session: SessionOption,
    database: DatabaseOption,
    record_id: RecordOption = None,
    shared_fixture: FixtureOption = None,
    feishu_config: FeishuConfigOption = None,
    table: TableOption = None,
    approved: ApprovedOption = None,
    ready_progress: ReadyOption = None,
) -> None:
    """Reread the shared record, then issue one single-use dispatch authorization."""
    _run(lambda: _gateway(
        database, shared_fixture=shared_fixture, feishu_config=feishu_config, table=table,
        record_id=record_id, approved=approved, ready_progress=ready_progress,
    ).authorize_greeting(task_id, session))


@worker_app.command("record-greeting")
def record_greeting(
    readback_path: Path,
    database: DatabaseOption,
    record_id: RecordOption = None,
    shared_fixture: FixtureOption = None,
    feishu_config: FeishuConfigOption = None,
    table: TableOption = None,
    approved: ApprovedOption = None,
    ready_progress: ReadyOption = None,
) -> None:
    """Reread shared state, then commit one observed result. This command does not send."""

    def action() -> ContractModel:
        readback = _load(readback_path, WorkerReadback)
        return _gateway(
            database, shared_fixture=shared_fixture, feishu_config=feishu_config, table=table,
            record_id=record_id, approved=approved, ready_progress=ready_progress,
        ).record_greeting(readback)

    _run(action)


@worker_app.command("show")
def show(task_id: str, database: DatabaseOption) -> None:
    """Read one durable task result; never assume a parent agent status is proof."""

    def action() -> ContractModel:
        state = _gateway(database).show(task_id)
        if state is None:
            raise ContractValidationError("Worker task was not found.")
        return state

    _run(action)


@worker_app.command("events")
def events(database: DatabaseOption) -> None:
    """Read pending completion events once; this starts no listener or polling."""
    _run(lambda: list(_gateway(database).events()))


@worker_app.command("ack")
def acknowledge(event_id: str, database: DatabaseOption) -> None:
    """Acknowledge an existing completion event idempotently."""
    _run(lambda: _gateway(database).acknowledge(event_id))
