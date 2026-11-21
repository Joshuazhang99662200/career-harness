"""Thin official-CLI adapter shared by generation/execution hosts; no database or sends."""

import json
import subprocess
from pathlib import Path
from typing import Any, Never, Protocol

from pydantic import JsonValue

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.memory.history_match import ParsedPage, match_history, parse_history_page
from jobagent.schemas.feishu import (
    FeishuConfig,
    FeishuCreateReceipt,
    FeishuPage,
    FeishuPatch,
    FeishuRecord,
    FeishuTable,
    FeishuWriteReceipt,
)
from jobagent.schemas.memory_signal import OperatorDirectory
from jobagent.schemas.shared_memory import SHARED_MEMORY_TABLE_KEYS, RecordHistoryDiff


def reject(message: str) -> Never:
    raise ContractValidationError(message)


class FeishuTransport(Protocol):
    def call(self, argv: list[str]) -> dict[str, Any]: ...


class LarkCliTransport:
    def __init__(self, config: FeishuConfig) -> None:
        self.config = config
        if Path(config.executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            reject("Configure the native CLI executable; shell shims cannot preserve JSON argv.")

    def call(self, argv: list[str]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [self.config.executable, *argv, "--as", self.config.identity, "--format", "json"],
                shell=False, capture_output=True, text=True, encoding="utf-8",
                timeout=self.config.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ContractValidationError(
                "Feishu CLI dispatch failed; do not retry unknown writes."
            ) from error
        try:
            envelope = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        except (ValueError, TypeError) as error:
            raise ContractValidationError("Feishu CLI returned an invalid response.") from error
        if (result.returncode != 0 or not isinstance(envelope, dict)
                or envelope.get("ok") is not True or not isinstance(envelope.get("data"), dict)):
            # Do not echo stderr, credentials, payloads or arbitrary server error text.
            reject("Feishu CLI request was not accepted; inspect authorization or source health.")
        return dict(envelope["data"])


class FeishuGateway:
    def __init__(self, config: FeishuConfig, transport: FeishuTransport) -> None:
        self.config = FeishuConfig.model_validate(config.model_dump())
        self.transport = transport

    def _table(self, key: str) -> FeishuTable:
        table = self.config.tables.get(key)
        if table is None:
            reject("Table is not in this host's explicit Feishu configuration.")
        assert table is not None
        return table

    def _args(self, key: str, command: str) -> list[str]:
        return ["base", command, "--base-token", self.config.base_token,
                "--table-id", self._table(key).table_id]

    def _live_fields(self, key: str) -> dict[str, dict[str, Any]]:
        fields: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            page = self.transport.call([
                *self._args(key, "+field-list"), "--limit", "200", "--offset", str(offset),
            ])
            rows, total = page.get("fields"), page.get("total")
            if not isinstance(rows, list) or type(total) is not int or total < 0:
                reject("Feishu field schema is incomplete or invalid.")
            for field in rows:
                if not isinstance(field, dict) or not isinstance(field.get("id"), str):
                    reject("Feishu field schema contains an invalid field.")
                if field["id"] in fields:
                    reject("Feishu schema pagination repeated a field.")
                fields[field["id"]] = field
            offset += len(rows)
            if offset == total:
                break
            if not rows or offset > total:
                reject("Feishu field schema pagination is incomplete.")
        return fields

    def catalog(self, key: str) -> list[dict[str, Any]]:
        return [dict(field) for field in self._live_fields(key).values()]

    def schema(self, key: str) -> dict[str, dict[str, Any]]:
        fields = self._live_fields(key)
        mapping = self._table(key).fields
        if not set(mapping.values()) <= set(fields):
            reject("Configured field IDs are missing from the current live schema.")
        return {name: fields[field_id] for name, field_id in mapping.items()}

    def _page(self, key: str, data: dict[str, Any], offset: int) -> FeishuPage:
        table = self._table(key)
        ids, columns, rows = data.get("record_id_list"), data.get("field_id_list"), data.get("data")
        if (not isinstance(ids, list) or not isinstance(columns, list) or not isinstance(rows, list)
                or type(data.get("has_more")) is not bool or len(ids) != len(rows)
                or not all(isinstance(c, str) for c in columns)
                or not all(isinstance(r, str) for r in ids)
                or len(set(columns)) != len(columns) or len(set(ids)) != len(ids)):
            reject("Feishu records response is incomplete or invalid.")
        reverse = {field_id: name for name, field_id in table.fields.items()}
        if any(not isinstance(c, str) or c not in reverse for c in columns):
            reject("Feishu returned fields outside the requested mapping.")
        records = []
        for record_id, row in zip(ids, rows, strict=True):
            if (not isinstance(record_id, str) or not isinstance(row, list)
                    or len(row) != len(columns)):
                reject("Feishu record row is malformed.")
            values = {reverse[c]: value for c, value in zip(columns, row, strict=True)}
            records.append(FeishuRecord(
                table_id=table.table_id, record_id=record_id, fields=values,
                content_digest=canonical_digest({
                    "base": self.config.base_token, "table": table.table_id,
                    "record": record_id, "mapping": table.fields, "fields": values,
                }),
            ))
        if data["has_more"] and not records:
            reject("Feishu returned an empty incomplete page; no safe pagination progress.")
        return FeishuPage(table_id=table.table_id, records=records, has_more=data["has_more"],
                          next_offset=offset + len(records) if data["has_more"] else None,
                          table_revision=data.get("rev"))

    def query(
        self, key: str, *, fields: list[str], conditions: list[list[JsonValue]],
        limit: int, offset: int, expected_table_revision: int | str | None = None,
    ) -> FeishuPage:
        if not 1 <= limit <= 200 or offset < 0 or not fields or len(set(fields)) != len(fields):
            reject("Explicit page size, offset and unique projected fields are required.")
        if offset and expected_table_revision is None:
            reject("Continuation requires the table revision from the previous page.")
        live = self.schema(key)
        table = self._table(key)
        if not set(fields) <= set(live):
            reject("Query projects an unmapped field.")
        native = []
        for condition in conditions:
            if (len(condition) not in {2, 3} or not isinstance(condition[0], str)
                    or condition[0] not in live):
                reject("Query condition must name a mapped semantic field.")
            native.append([table.fields[condition[0]], *condition[1:]])
        argv = [*self._args(key, "+record-list"), "--limit", str(limit), "--offset", str(offset)]
        for name in fields:
            argv.extend(["--field-id", table.fields[name]])
        argv.extend(["--filter-json", json.dumps({"logic": "and", "conditions": native})])
        result = self._page(key, self.transport.call(argv), offset)
        if (expected_table_revision is not None
                and result.table_revision != expected_table_revision):
            reject("Shared table revision changed during pagination; restart current-state query.")
        if any(not set(fields) <= set(record.fields) for record in result.records):
            reject("Feishu omitted a requested projection field.")
        return result

    def get(self, key: str, record_id: str) -> FeishuRecord:
        argv = [*self._args(key, "+record-get"), "--record-id", record_id]
        for field_id in self._table(key).fields.values():
            argv.extend(["--field-id", field_id])
        page = self._page(key, self.transport.call(argv), 0)
        if (page.has_more or len(page.records) != 1 or page.records[0].record_id != record_id
                or set(page.records[0].fields) != set(self._table(key).fields)):
            reject("Feishu record is missing, mismatched or incompletely projected.")
        return page.records[0]

    def patch(self, request: FeishuPatch) -> FeishuWriteReceipt:
        table = self._table(request.table)
        live = self.schema(request.table)
        allowed = set(table.writable.get(request.role, []))
        if not set(request.fields) <= allowed:
            reject("Patch crosses this role's explicit writable field boundary.")
        for name, value in request.fields.items():
            field = live[name]
            if (field.get("name") in {"招呼语", "邮件正文", "准确全文"}
                    and name not in table.material_fields):
                reject("Material writes require an explicit current-approval guard configuration.")
            if name == "approval":
                if value != [table.pending_approval_value]:
                    reject("Agents may only mark a job as awaiting the human's decision.")
                _reject_cell(field, name, value, pending=True)
                continue
            _reject_cell(field, name, value)
        current = self.get(request.table, request.record_id)
        if current.content_digest != request.expected_digest:
            reject("Record content changed; reread the shared source before writing.")
        approval = current.fields.get("approval")
        if (set(request.fields) & set(table.material_fields) and isinstance(approval, list)
                and any(value in table.approved_values for value in approval)):
            reject("Approved material cannot be edited in place; resolve its approval first.")
        receipt = FeishuWriteReceipt(record_id=request.record_id, status="unverified",
                                     verified=False, dispatched=False,
                                     source_reference=request.source_reference)
        if all(current.fields[name] == value for name, value in request.fields.items()):
            return receipt.model_copy(update={"status": "verified", "verified": True,
                                               "record": current})
        payload = {"update_records": {request.record_id: {
            table.fields[name]: value for name, value in request.fields.items()
        }}}
        receipt.dispatched = True
        try:
            response = self.transport.call([
                *self._args(request.table, "+record-batch-update"),
                "--json", json.dumps(payload, ensure_ascii=False),
            ])
            if response.get("ignored_fields"):
                receipt.diagnostic = "ignored_fields_requires_reconciliation"
                return receipt
        except ContractValidationError:
            receipt.status = "unknown"
            receipt.diagnostic = "dispatch_outcome_unknown_do_not_repeat"
            return receipt
        try:
            record = self.get(request.table, request.record_id)
        except ContractValidationError:
            receipt.status = "unknown"
            receipt.diagnostic = "readback_unavailable_do_not_repeat"
            return receipt
        receipt.record = record
        receipt.verified = all(
            record.fields[name] == value for name, value in request.fields.items()
        )
        receipt.status = "verified" if receipt.verified else "unverified"
        if not receipt.verified:
            receipt.diagnostic = "readback_mismatch_do_not_repeat"
        return receipt

    def _require_configured_table(self, key: str) -> FeishuTable:
        if key not in SHARED_MEMORY_TABLE_KEYS or key not in self.config.tables:
            reject(
                "This operation uses the private Jobs, Materials, Human Signals "
                "or memory table mapping."
            )
        return self._table(key)

    def record_history(
        self,
        key: str,
        record_id: str,
        field_id: str,
        *,
        operators: OperatorDirectory,
        page_size: int = 50,
        max_pages: int = 20,
    ) -> RecordHistoryDiff:
        """Read one job record's history. A partial page sequence is not a diff."""
        if key != "jobs":
            reject("Record history for preference learning reads the production jobs table.")
        self._require_configured_table(key)
        if not record_id or not field_id or not 1 <= page_size <= 50 or not 1 <= max_pages <= 50:
            reject("Record history needs one record, one field, and an explicit page budget.")
        directory = OperatorDirectory.model_validate(operators.model_dump())
        pages: list[ParsedPage] = []
        cursor: int | None = None
        while len(pages) < max_pages:
            argv = [
                *self._args(key, "+record-history-list"),
                "--record-id", record_id,
                "--page-size", str(page_size),
            ]
            if cursor is not None:
                argv.extend(["--max-version", str(cursor)])
            page = parse_history_page(self.transport.call(argv))
            pages.append(page)
            if not page.has_more:
                break
            if page.next_max_version is None:
                reject("Record history page did not continue.")
            cursor = page.next_max_version
        else:
            reject("Record history did not finish; the diff is not uniquely matched.")
        return match_history(
            pages, record_id=record_id, field_id=field_id, operators=directory
        )

    def append_memory_row(self, key: str, fields: dict[str, JsonValue]) -> FeishuCreateReceipt:
        """Create the first memory row for a candidate and domain, then read it back."""
        if key not in {"search_memory", "greeting_memory"}:
            reject("Record creation is limited to the two production memory tables.")
        table = self._require_configured_table(key)
        if not fields:
            reject("Memory append requires the semantic columns.")
        allowed = set(table.writable.get("memory", []))
        if set(fields) != allowed or not set(fields) <= set(table.fields):
            reject("Memory append must write exactly the memory role's columns.")
        live = self.schema(key)
        for name, value in fields.items():
            _reject_cell(live[name], name, value)
        receipt = FeishuCreateReceipt(
            status="unverified", verified=False, dispatched=False
        )
        payload = {"create_records": [{
            table.fields[name]: value for name, value in fields.items()
        }]}
        receipt.dispatched = True
        try:
            response = self.transport.call([
                *self._args(key, "+record-batch-create"),
                "--json", json.dumps(payload, ensure_ascii=False),
            ])
        except ContractValidationError:
            receipt.status = "unknown"
            receipt.diagnostic = "dispatch_outcome_unknown_do_not_repeat"
            return receipt
        if response.get("ignored_fields"):
            receipt.diagnostic = "ignored_fields_requires_reconciliation"
            return receipt
        created = response.get("record_id_list")
        if (not isinstance(created, list) or len(created) != 1
                or not isinstance(created[0], str) or not created[0]):
            receipt.status = "unknown"
            receipt.diagnostic = "create_identity_unknown_do_not_repeat"
            return receipt
        try:
            record = self.get(key, created[0])
        except ContractValidationError:
            receipt.status = "unknown"
            receipt.record_id = created[0]
            receipt.diagnostic = "readback_unavailable_do_not_repeat"
            return receipt
        receipt.record_id = record.record_id
        receipt.record = record
        receipt.verified = all(record.fields.get(name) == value for name, value in fields.items())
        receipt.status = "verified" if receipt.verified else "unverified"
        if not receipt.verified:
            receipt.diagnostic = "readback_mismatch_do_not_repeat"
        return receipt


def _reject_cell(
    field: dict[str, Any], name: str, value: JsonValue, *, pending: bool = False
) -> None:
    human_only = {"你的决定"} if pending else {"批准状态", "你的决定"}
    if (name == "approval" and not pending) or field.get("name") in human_only:
        reject("Human decision fields cannot be changed by an agent.")
    kind = field.get("type")
    if kind == "text":
        if value is not None and not isinstance(value, str):
            reject("Text fields require an exact string or null.")
    elif kind == "select":
        options = {option.get("name") for option in field.get("options", [])}
        if (not isinstance(value, list) or not all(isinstance(item, str) for item in value)
                or not set(value) <= options
                or (field.get("multiple") is False and len(value) > 1)):
            reject("Select values must match the current live schema.")
    elif kind == "datetime":
        if value is not None and (not isinstance(value, str) or not value):
            reject("Datetime fields require an exact string or null.")
    else:
        reject("This minimal adapter only writes text, select or datetime.")
