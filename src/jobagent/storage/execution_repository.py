"""Append-only storage for panel execution lists and their one confirmation each."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from jobagent.errors import StorageError
from jobagent.schemas.console_host import HostBatch
from jobagent.storage.database import Database


@dataclass(frozen=True)
class ItemRef:
    """Where an execution item's approval and send record live."""

    batch_id: str
    number: int
    approval_id: str


@dataclass(frozen=True)
class StoredBatch:
    candidate_id: str
    batch: HostBatch
    refs: dict[str, ItemRef]


@dataclass(frozen=True)
class Confirmation:
    event_id: str
    candidate_id: str
    operation_key: str
    batch_id: str
    request_digest: str
    item_ids: tuple[str, ...]


class SqliteExecutionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_batch(
        self, candidate_id: str, batch: HostBatch, refs: dict[str, ItemRef], now: datetime
    ) -> None:
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO execution_batches VALUES (?, ?, ?, ?, ?)",
                    (batch.batch_id, candidate_id, batch.model_dump_json(),
                     json.dumps({k: [r.batch_id, r.number, r.approval_id]
                                 for k, r in refs.items()}),
                     now.isoformat()),
                )
        except sqlite3.Error as error:
            raise StorageError("Could not save the execution list.") from error

    @staticmethod
    def _stored(row: sqlite3.Row) -> StoredBatch:
        refs = {k: ItemRef(v[0], int(v[1]), v[2]) for k, v in json.loads(row["refs_json"]).items()}
        return StoredBatch(
            candidate_id=row["candidate_id"],
            batch=HostBatch.model_validate_json(row["batch_json"]),
            refs=refs,
        )

    def _ready(self) -> bool:
        """False for a database that predates execution lists: it has none to read."""
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'execution_batches'"
            ).fetchone() is not None

    def get_batch(self, candidate_id: str, batch_id: str) -> StoredBatch | None:
        if not self._ready():
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_batches WHERE batch_id = ? AND candidate_id = ?",
                (batch_id, candidate_id),
            ).fetchone()
        return None if row is None else self._stored(row)

    def list_batches(self, candidate_id: str) -> list[StoredBatch]:
        if not self._ready():
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_batches WHERE candidate_id = ? "
                "ORDER BY created_at, batch_id",
                (candidate_id,),
            ).fetchall()
        return [self._stored(row) for row in rows]

    @staticmethod
    def _confirmation(row: sqlite3.Row) -> Confirmation:
        return Confirmation(
            event_id=row["event_id"], candidate_id=row["candidate_id"],
            operation_key=row["operation_key"], batch_id=row["batch_id"],
            request_digest=row["request_digest"],
            item_ids=tuple(json.loads(row["item_ids_json"])),
        )

    def confirmation_for_key(self, candidate_id: str, operation_key: str) -> Confirmation | None:
        if not self._ready():
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_confirmations WHERE candidate_id = ? "
                "AND operation_key = ?",
                (candidate_id, operation_key),
            ).fetchone()
        return None if row is None else self._confirmation(row)

    def confirmation_for_batch(self, batch_id: str) -> Confirmation | None:
        if not self._ready():
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_confirmations WHERE batch_id = ?", (batch_id,),
            ).fetchone()
        return None if row is None else self._confirmation(row)

    def save_confirmation(
        self, confirmation: Confirmation, *, actor_id: str, now: datetime
    ) -> str:
        """Store the one confirmation of a list; "duplicate" if the list already has one."""
        try:
            with self.database.transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM execution_confirmations WHERE batch_id = ? "
                    "OR (candidate_id = ? AND operation_key = ?)",
                    (confirmation.batch_id, confirmation.candidate_id,
                     confirmation.operation_key),
                ).fetchone():
                    return "duplicate"
                connection.execute(
                    "INSERT INTO execution_confirmations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (confirmation.event_id, confirmation.candidate_id,
                     confirmation.operation_key, confirmation.batch_id,
                     confirmation.request_digest, json.dumps(list(confirmation.item_ids)),
                     actor_id, now.isoformat()),
                )
            return "stored"
        except sqlite3.Error as error:
            raise StorageError("Could not save the execution confirmation.") from error
