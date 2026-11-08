"""Portable read-only console queries and explicit host activity ingestion."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from jobagent.bridge.panel_decisions import (
    panel_materials,
    record_panel_decision,
)
from jobagent.console.activities import record_activity
from jobagent.console.execution import (
    confirm_execution,
    create_execution_batch,
    operation_receipt,
    read_execution_batch,
)
from jobagent.console.host_state import host_state
from jobagent.console.projection import definitions as field_definitions
from jobagent.console.projection import snapshot
from jobagent.console.selection import read_selection, save_selection
from jobagent.console.server import make_server
from jobagent.errors import JobAgentError
from jobagent.schemas.console import ConsoleActivityInput
from jobagent.schemas.console_host import (
    HostDecisionRequest,
    HostExecutionRequest,
    HostReceipt,
    HostSelectionRequest,
)

console_app = typer.Typer(help="Read-only console and explicit host observations.")
DatabaseOption = Annotated[Path, typer.Option("--database")]
WorkspaceOption = Annotated[Path, typer.Option("--workspace")]


def _output(action: Callable[[], object]) -> None:
    try:
        typer.echo(json.dumps(action(), ensure_ascii=False, indent=2))
    except (JobAgentError, OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "CONSOLE_INPUT_UNAVAILABLE",
                        "message": "Console input unavailable or invalid.",
                    }
                }
            )
        )
        raise typer.Exit(1) from None


@console_app.command("definitions")
def definitions() -> None:
    _output(field_definitions)


@console_app.command("list")
def list_records(
    candidate_id: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    workspace: WorkspaceOption = Path("."),
) -> None:
    _output(lambda: snapshot(database, workspace, candidate_id).model_dump(mode="json"))


@console_app.command("event")
def event(path: Path, workspace: WorkspaceOption = Path(".")) -> None:
    _output(
        lambda: record_activity(
            workspace,
            ConsoleActivityInput.model_validate_json(path.read_bytes()),
        ).model_dump(mode="json")
    )


@console_app.command("materials")
def materials(
    candidate: Annotated[str, typer.Option("--candidate")],
    contact: Annotated[str, typer.Option("--contact", help="The panel contact (PIPE_*).")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Exact greetings awaiting the person's decision for one panel contact (getMaterials)."""
    _output(lambda: [
        material.model_dump(mode="json")
        for material in panel_materials(database, candidate, contact)
    ])


def _receipt(receipt: HostReceipt) -> None:
    typer.echo(receipt.model_dump_json(indent=2))
    if receipt.status != "saved":
        raise typer.Exit(1)


@console_app.command("host-state")
def host_state_command(
    candidate: Annotated[str, typer.Option("--candidate")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Read-only HostState (getHostState): greeting materials and saved panel decisions."""
    _output(lambda: host_state(database, candidate).model_dump(mode="json"))


@console_app.command("decide")
def decide(
    path: Annotated[Path, typer.Argument(help="HostDecisionRequest JSON from the panel.")],
    actor: Annotated[str, typer.Option("--actor", help="Who acted in the panel.")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Record a panel decision (recordDecision). Approval goes through the outreach gate on
    the exact asked words; edits become revision feedback; nothing is sent."""
    try:
        request = HostDecisionRequest.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        typer.echo(json.dumps({"error": {"code": "CONSOLE_INPUT_UNAVAILABLE",
                                         "message": "Decision request unavailable or invalid."}}))
        raise typer.Exit(1) from None
    _receipt(record_panel_decision(database, request, actor_id=actor, now=datetime.now(UTC)))


@console_app.command("operation")
def operation(
    operation_key: str,
    candidate: Annotated[str, typer.Option("--candidate")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Read back one panel operation by its key (getOperation); never repeats it."""
    _receipt(operation_receipt(database, candidate, operation_key))


@console_app.command("selection")
def selection_show(
    candidate: Annotated[str, typer.Option("--candidate")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """The panel's selection queue (getSelectionQueue). Selecting grants nothing; a contact
    leaves only after a later send was verified by exact readback."""
    _output(lambda: read_selection(database, candidate).model_dump(mode="json"))


@console_app.command("select")
def selection_change(
    path: Annotated[Path, typer.Argument(help="HostSelectionRequest JSON from the panel.")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Change the selection against the version last read (toggle/applySelectionOperation);
    a change against an older version is refused."""
    try:
        request = HostSelectionRequest.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        typer.echo(json.dumps({"error": {"code": "CONSOLE_INPUT_UNAVAILABLE",
                                         "message": "Selection request unavailable or invalid."}}))
        raise typer.Exit(1) from None
    receipt = save_selection(database, request, now=datetime.now(UTC))
    typer.echo(receipt.model_dump_json(indent=2))
    if receipt.status != "saved":
        raise typer.Exit(1)


@console_app.command("batch-create")
def batch_create(
    candidate: Annotated[str, typer.Option("--candidate")],
    contact: Annotated[list[str], typer.Option("--contact", help="A selected contact (PIPE_*).")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """List the selected contacts' approved first greetings (createExecutionBatch).
    Anything without a current approval is listed with its reason; nothing is sent."""
    _output(lambda: create_execution_batch(
        database, candidate, contact, now=datetime.now(UTC)
    ).model_dump(mode="json"))


@console_app.command("batch")
def batch_show(
    batch_id: str,
    candidate: Annotated[str, typer.Option("--candidate")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """One execution list with each item's status read from send audits and readbacks
    (getBatch); prints null for an unknown list."""
    _output(lambda: (lambda b: None if b is None else b.model_dump(mode="json"))(
        read_execution_batch(database, candidate, batch_id)
    ))


@console_app.command("batch-confirm")
def batch_confirm(
    path: Annotated[Path, typer.Argument(help="HostExecutionRequest JSON from the panel.")],
    actor: Annotated[str, typer.Option("--actor", help="Who confirmed in the panel.")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Confirm which listed items to run (confirmExecution). Only the selected items are
    handed to the host's outreach lease/next/record cadence; the repository sends nothing."""
    try:
        request = HostExecutionRequest.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        typer.echo(json.dumps({"error": {"code": "CONSOLE_INPUT_UNAVAILABLE",
                                         "message": "Execution request unavailable or invalid."}}))
        raise typer.Exit(1) from None
    _receipt(confirm_execution(database, request, actor_id=actor, now=datetime.now(UTC)))


@console_app.command("serve")
def serve(
    candidate_id: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    workspace: WorkspaceOption = Path("."),
    assets: Annotated[Path, typer.Option("--assets")] = Path("frontend/dist"),
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
) -> None:
    try:
        server = make_server(database, workspace, candidate_id, assets, port=port)
    except (OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "CONSOLE_SERVER_UNAVAILABLE",
                        "message": "Local console server unavailable.",
                    }
                }
            )
        )
        raise typer.Exit(1) from None
    typer.echo(json.dumps({"url": f"http://127.0.0.1:{port}", "read_only": True}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
