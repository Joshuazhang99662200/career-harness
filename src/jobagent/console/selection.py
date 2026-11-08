# ruff: noqa: RUF001  -- user-facing receipts are written in Chinese.
"""The panel's selection queue, kept by the repository so it survives reloads.

Selecting is only a choice of what to look at or run next: it never approves or
sends. A contact leaves the selection only when a send chosen after it was
selected has been verified by exact readback; queued, failed and unknown ones
stay, so nothing silently drops out. Every change is an append-only version,
and a change made against an older version is refused instead of overwriting.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from jobagent.console.execution import execution_batches
from jobagent.errors import JobAgentError, StorageError
from jobagent.schemas.console_host import (
    HostSelection,
    HostSelectionReceipt,
    HostSelectionRequest,
)
from jobagent.storage.database import Database
from jobagent.storage.pipeline_repository import PipelineRepository


def _latest(db: Database, candidate_id: str) -> tuple[int, dict[str, str | None]]:
    with db.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'panel_selection_versions'"
        ).fetchone() is None:
            return 0, {}
        row = connection.execute(
            "SELECT version, contacts_json FROM panel_selection_versions "
            "WHERE candidate_id = ? ORDER BY version DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
    if row is None:
        return 0, {}
    return int(row["version"]), dict(json.loads(row["contacts_json"]))


def _verified(db: Database, candidate_id: str) -> dict[str, str]:
    """Per contact, the latest confirmed execution item verified by exact readback."""
    verified: dict[str, str] = {}
    for batch in execution_batches(db, candidate_id):
        for item in batch.items:
            if item.selected and item.status == "verified":
                verified[item.contact_id] = item.item_id
    return verified


def _current(db: Database, candidate_id: str) -> tuple[int, dict[str, str | None]]:
    version, contacts = _latest(db, candidate_id)
    verified = _verified(db, candidate_id)
    return version, {
        contact: baseline for contact, baseline in contacts.items()
        if verified.get(contact) in (None, baseline)
    }


def read_selection(database: Path, candidate_id: str) -> HostSelection:
    db = Database(database)
    version, contacts = _current(db, candidate_id)
    return HostSelection(candidate_id=candidate_id, version=version, contact_ids=list(contacts))


def save_selection(
    database: Path, request: HostSelectionRequest, *, now: datetime
) -> HostSelectionReceipt:
    """Apply one selection change made against the version the panel last read."""
    db = Database(database)
    db.migrate()
    version, contacts = _current(db, request.candidate_id)

    def receipt(
        status: Literal["saved", "rejected"], message: str, version: int,
        contacts: dict[str, str | None],
    ) -> HostSelectionReceipt:
        return HostSelectionReceipt(
            status=status,
            message=message,
            selection=HostSelection(
                candidate_id=request.candidate_id, version=version, contact_ids=list(contacts)
            ),
        )

    if request.expected_version != version:
        return receipt("rejected", "选择刚被更新过，请刷新后再操作；这次没有保存。",
                       version, contacts)
    owned = {job.pipeline_id for job, _ in
             PipelineRepository(db).list_records(request.candidate_id)}
    if any(contact not in owned for contact in request.contact_ids):
        return receipt("rejected", "选择包含不属于当前候选人的岗位，已停止保存。",
                       version, contacts)
    verified = _verified(db, request.candidate_id)
    chosen = dict(contacts)
    targets = list(dict.fromkeys(request.contact_ids))
    operation = request.operation
    for contact in targets:
        add = operation in {"select", "select_visible"} or (
            operation == "invert_visible" and contact not in chosen
        )
        if add:
            chosen.setdefault(contact, verified.get(contact))
        elif operation in {"deselect", "clear_visible", "invert_visible"}:
            chosen.pop(contact, None)
    if operation == "clear_all":
        chosen = {}
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO panel_selection_versions VALUES (?, ?, ?, ?)",
                (request.candidate_id, version + 1, json.dumps(chosen), now.isoformat()),
            )
    except sqlite3.IntegrityError:
        latest_version, latest = _current(db, request.candidate_id)
        return receipt("rejected", "选择刚被更新过，请刷新后再操作；这次没有保存。",
                       latest_version, latest)
    except (sqlite3.Error, JobAgentError) as error:
        raise StorageError("Could not save the panel selection.") from error
    return receipt("saved", f"已保存选择，共 {len(chosen)} 个岗位；选择不代表批准。",
                   version + 1, chosen)
