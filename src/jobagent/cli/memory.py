"""P1 offline memory inventory, immutable metadata snapshots and context selection."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.bridge.memory_sources import PrivateSourceReader, private_path
from jobagent.bridge.shared_memory import SharedMemoryService
from jobagent.cli.feishu import gateway as feishu_gateway
from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.jobs.search_memory_apply import apply_search_memory
from jobagent.jobs.shared_send_gate import shared_send_decision
from jobagent.memory.effect import memory_effect_report, reply_outcomes, sent_from_ledger
from jobagent.memory.service import MemoryService
from jobagent.memory.signal import SignalInbox
from jobagent.memory.signal_compile import FileAttributor, SignalCompiler
from jobagent.memory.simulation import simulate as run_simulation
from jobagent.memory.usage import summarize_memory_usage
from jobagent.schemas.common import ContractModel
from jobagent.schemas.memory import MemoryConfig
from jobagent.schemas.memory_signal import (
    AttributionFile,
    CurrentSharedProjection,
    HumanSignalFile,
    JobContextFile,
    OperatorDirectory,
    PublishedMemoryFile,
    SearchParameters,
    SignalReceiptFile,
    WatchedJobFields,
)
from jobagent.schemas.shared_memory import (
    DreamBatchComplete,
    DreamBatchStart,
    FetchMemoryPin,
    MemoryPublishRequest,
    SearchRoundInput,
)
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.memory_repository import MemoryRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

memory_app = typer.Typer(help="Private source inventory and deterministic context; no model calls.")
ConfigOption = Annotated[Path, typer.Option("--config")]
StoreOption = Annotated[Path, typer.Option("--store")]


def _run(
    config: Path,
    store: Path,
    operation: str,
    *,
    snapshot: str = "",
    task: str = "",
    job: str | None = None,
) -> None:
    try:
        settings = read_model(private_path(config), MemoryConfig)
        service = MemoryService(
            settings, PrivateSourceReader(settings, store), MemoryRepository(store)
        )
        result: ContractModel
        if operation == "status":
            result = service.status()
        elif operation == "compile":
            result = service.compile()
        else:
            result = service.context(
                snapshot, task=task, job_id=job, candidate_id=settings.candidate_id
            )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
    except (OSError, sqlite3.Error, ValidationError, UnicodeError):
        fail(ContractValidationError("Private memory input or sidecar is unavailable or invalid."))


@memory_app.command("status")
def status(config: ConfigOption, store: StoreOption) -> None:
    _run(config, store, "status")


@memory_app.command("compile")
def compile_snapshot(config: ConfigOption, store: StoreOption) -> None:
    _run(config, store, "compile")


@memory_app.command("context")
def context(
    config: ConfigOption,
    store: StoreOption,
    snapshot: Annotated[str, typer.Option("--snapshot")],
    task: Annotated[str, typer.Option("--task")],
    job: Annotated[str | None, typer.Option("--job")] = None,
) -> None:
    _run(config, store, "context", snapshot=snapshot, task=task, job=job)


@memory_app.command("usage")
def usage(
    candidate: Annotated[str, typer.Option("--candidate")],
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Show which memory versions and preference rules reached drafted, approved and sent items.

    Read from the outreach ledger only; items without generation provenance are
    reported as unattributed. Grants no approval.
    """
    try:
        store = SqliteOutreachRepository(open_database(database))
        batches = store.list_batches()
        approvals = {
            batch.batch_id: approval
            for batch in batches
            if (approval := store.get_approval(batch.batch_id)) is not None
        }
        report = summarize_memory_usage(
            candidate, batches=batches, approvals=approvals, audits=store.list_audits(),
        )
        typer.echo(report.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


@memory_app.command("effect")
def effect(
    candidate: Annotated[str, typer.Option("--candidate")],
    window_days: Annotated[
        int, typer.Option("--window-days", min=1, help="Reply observation window; required.")
    ],
    min_sample: Annotated[
        int, typer.Option("--min-sample", min=1, help="Closed sends needed per arm; required.")
    ],
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Compare reply rates of memory-shaped greetings with greetings made without memory.

    Only closed windows count; small samples report insufficient_sample. The result
    is observational and grants nothing.
    """
    try:
        db = open_database(database)
        store = SqliteOutreachRepository(db)
        owned = {
            e.id for e in SqliteCandidateRepository(db).list_evidence(candidate)
            if e.user_confirmed and e.confidence.value != "weak"
        }
        conversations = SqliteConversationRepository(db)
        threads = [
            (conversation, conversations.list_events(conversation.conversation_id))
            for conversation in conversations.list_conversations()
        ]
        now = datetime.now(UTC)
        window = timedelta(days=window_days)
        items = sent_from_ledger(
            candidate, batches=store.list_batches(), audits=store.list_audits(),
            owned_evidence_ids=owned,
        )
        report = memory_effect_report(
            candidate, reply_outcomes(items, threads, now=now, window=window),
            window=window, min_sample=min_sample, observed_at=now,
        )
        typer.echo(report.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


@memory_app.command("simulate")
def simulate(
    trials: Annotated[int, typer.Option("--trials", min=1)],
    sample_size: Annotated[int, typer.Option("--sample-size", min=1, help="Sends per arm.")],
    base_rate: Annotated[float, typer.Option("--base-rate", min=0, max=1)],
    lift: Annotated[float, typer.Option("--lift", min=-1, max=1)],
    min_sample: Annotated[int, typer.Option("--min-sample", min=1)],
    seed: Annotated[int, typer.Option("--seed")] = 0,
) -> None:
    """Synthetic check: how often `memory effect` would claim or detect a difference."""
    try:
        typer.echo(run_simulation(
            trials=trials, sample_size=sample_size, base_rate=base_rate, lift=lift,
            min_sample=min_sample, seed=seed,
        ).model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


def _load_receipt(path: Path) -> SignalReceiptFile:
    if not path.exists():
        return SignalReceiptFile()
    return read_model(path, SignalReceiptFile)


@memory_app.command("signal-receive")
def signal_receive(
    event: Annotated[Path, typer.Option("--event", help="Local event JSON fixture.")],
    fields: Annotated[Path, typer.Option("--fields")],
    operators: Annotated[Path, typer.Option("--operators")],
    receipt: Annotated[
        Path | None, typer.Option("--receipt", help="Optional event-id digest file.")
    ] = None,
) -> None:
    """Filter one local record-changed fixture. No subscription, network or send."""
    try:
        payload = json.loads(event.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ContractValidationError("Bitable event payload must be an object.")
        prior = _load_receipt(receipt) if receipt is not None else SignalReceiptFile()
        inbox = SignalInbox(
            read_model(fields, WatchedJobFields),
            read_model(operators, OperatorDirectory),
            prior_digests=prior.digests,
        )
        result = inbox.receive(payload)
        if receipt is not None:
            receipt.write_text(
                SignalReceiptFile(digests=inbox.digests).model_dump_json(indent=2),
                encoding="utf-8",
            )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
    except (OSError, json.JSONDecodeError, ValidationError, UnicodeError):
        fail(ContractValidationError("Signal event fixture is unavailable or invalid."))


@memory_app.command("signal-compile")
def signal_compile(
    signals: Annotated[Path, typer.Option("--signals")],
    contexts: Annotated[Path, typer.Option("--contexts")],
    attributions: Annotated[Path, typer.Option("--attributions")],
    learned: Annotated[
        Path | None, typer.Option("--learned", help="Optional published-memory file.")
    ] = None,
) -> None:
    """Check host attributions and publish memory. Does not call a model or Feishu."""
    try:
        signal_file = read_model(signals, HumanSignalFile)
        context_file = read_model(contexts, JobContextFile)
        attribution_file = read_model(attributions, AttributionFile)
        existing = (
            read_model(learned, PublishedMemoryFile) if learned and learned.exists() else None
        )
        contexts_by_record = {item.record_id: item for item in context_file.contexts}
        if len(contexts_by_record) != len(context_file.contexts):
            raise ContractValidationError("Job context record ids must be unique.")
        compiler = SignalCompiler(contexts_by_record, FileAttributor(attribution_file.attributions))
        if existing is not None:
            compiler.remember(existing.memories)
        result = compiler.compile(signal_file.signals)
        if learned is not None:
            learned.write_text(
                PublishedMemoryFile(memories=compiler.export()).model_dump_json(indent=2),
                encoding="utf-8",
            )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
    except (OSError, ValidationError, UnicodeError):
        fail(ContractValidationError("Signal compile input is unavailable or invalid."))


@memory_app.command("apply-search")
def apply_search(
    candidate: Annotated[str, typer.Option("--candidate")],
    base: Annotated[Path, typer.Option("--base")],
    memories: Annotated[Path, typer.Option("--memories")],
) -> None:
    """Apply search memory to keywords, role direction and exclusions. Does not search."""
    try:
        applied = apply_search_memory(
            read_model(base, SearchParameters),
            read_model(memories, PublishedMemoryFile).memories,
            candidate_id=candidate,
        )
        typer.echo(applied.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


def _shared_memory(config: Path, operators: OperatorDirectory | None = None) -> SharedMemoryService:
    return SharedMemoryService(feishu_gateway(config), operators or OperatorDirectory())


@memory_app.command("workflow-page")
def workflow_page(
    config: ConfigOption,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)],
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    revision: Annotated[int | None, typer.Option("--revision")] = None,
) -> None:
    """Read one page of pending Workflow Human Signals. Does not subscribe or write."""
    try:
        if offset and revision is None:
            raise ContractValidationError("Continuation requires the table revision.")
        page = _shared_memory(config).page_workflow_signals(
            limit=limit, offset=offset, expected_table_revision=revision,
        )
        typer.echo(page.model_dump_json())
    except JobAgentError as error:
        fail(error)


@memory_app.command("enrich-signal")
def enrich_signal(
    config: ConfigOption,
    record_id: Annotated[str, typer.Option("--record-id")],
    operators: Annotated[Path, typer.Option("--operators")],
) -> None:
    """Attach record history to one Human Signal. Failure leaves learning_status unchanged."""
    try:
        directory = read_model(operators, OperatorDirectory)
        result = _shared_memory(config, directory).enrich_signal(record_id)
        typer.echo(result.model_dump_json())
    except JobAgentError as error:
        fail(error)


@memory_app.command("publish-version")
def publish_version(
    config: ConfigOption, request: Annotated[Path, typer.Option("--request")]
) -> None:
    """Validate a supplied memory draft and publish the next version. Does not call a model."""
    try:
        result = _shared_memory(config).publish_memory(read_model(request, MemoryPublishRequest))
        typer.echo(result.model_dump_json())
        if not result.verified:
            raise typer.Exit(1)
    except JobAgentError as error:
        fail(error)


@memory_app.command("search-round")
def search_round(config: ConfigOption, request: Annotated[Path, typer.Option("--request")]) -> None:
    """Read the latest published search memory. No memory keeps the supplied search config."""
    try:
        plan = _shared_memory(config).read_search_round(read_model(request, SearchRoundInput))
        typer.echo(plan.model_dump_json())
    except JobAgentError as error:
        fail(error)


@memory_app.command("dream-batch-start")
def dream_batch_start(
    config: ConfigOption, request: Annotated[Path, typer.Option("--request")]
) -> None:
    """Freeze pending human signals for one Dream run. Does not call a model."""
    try:
        page = _shared_memory(config).start_dream_batch(read_model(request, DreamBatchStart))
        typer.echo(page.model_dump_json())
    except JobAgentError as error:
        fail(error)


@memory_app.command("dream-batch-complete")
def dream_batch_complete(
    config: ConfigOption, request: Annotated[Path, typer.Option("--request")]
) -> None:
    """Publish one complete snapshot for a frozen batch. Does not call a model."""
    try:
        result = _shared_memory(config).complete_dream_batch(
            read_model(request, DreamBatchComplete)
        )
        typer.echo(result.model_dump_json())
        if not result.verified:
            raise typer.Exit(1)
    except JobAgentError as error:
        fail(error)


@memory_app.command("fetch-pin")
def fetch_pin(config: ConfigOption, request: Annotated[Path, typer.Option("--request")]) -> None:
    """Pin the latest valid search snapshot for one Fetch round. Does not fetch."""
    try:
        pin = _shared_memory(config).pin_fetch_memory(read_model(request, SearchRoundInput))
        typer.echo(pin.model_dump_json())
    except JobAgentError as error:
        fail(error)


@memory_app.command("fetch-continue")
def fetch_continue(
    config: ConfigOption, request: Annotated[Path, typer.Option("--request")]
) -> None:
    """Re-read the pinned snapshot. A newer publish does not replace it."""
    try:
        body = json.loads(request.read_text(encoding="utf-8"))
        pin = FetchMemoryPin.model_validate(body["pin"])
        current = SearchRoundInput.model_validate(body["round"])
        held = _shared_memory(config).continue_fetch(pin, current)
        typer.echo(held.model_dump_json())
    except JobAgentError as error:
        fail(error)
    except (OSError, json.JSONDecodeError, ValidationError, UnicodeError):
        fail(ContractValidationError("Fetch pin input is unavailable or invalid."))


@memory_app.command("send-gate")
def send_gate(
    projection: Annotated[Path, typer.Option("--projection")],
    approved: Annotated[list[str], typer.Option("--approved")],
) -> None:
    """Read a current approval projection and refuse to send."""
    try:
        decision = shared_send_decision(
            read_model(projection, CurrentSharedProjection), approved_values=approved
        )
        typer.echo(decision.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
