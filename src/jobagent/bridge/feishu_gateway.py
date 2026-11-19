"""Thin official-CLI adapter shared by generation/execution hosts; no database or sends."""

import json
import subprocess
from pathlib import Path
from typing import Any, Never, Protocol

from pydantic import JsonValue

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.feishu import (
    FeishuConfig,
    FeishuPage,
    FeishuPatch,
    FeishuRecord,
    FeishuTable,
    FeishuWriteReceipt,
)


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

    def schema(self, key: str) -> dict[str, dict[str, Any]]:
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
            if name == "approval" or field.get("name") in {"批准状态", "你的决定"}:
                reject("Human decision fields cannot be changed by an agent.")
            if (field.get("name") in {"招呼语", "邮件正文", "准确全文"}
                    and name not in table.material_fields):
                reject("Material writes require an explicit current-approval guard configuration.")
            kind = field.get("type")
            if kind == "text":
                if value is not None and not isinstance(value, str):
                    reject("Text fields require an exact string or null.")
            elif kind == "select":
                options = {o.get("name") for o in field.get("options", [])}
                if (not isinstance(value, list) or not all(isinstance(v, str) for v in value)
                        or not set(value) <= options
                        or (field.get("multiple") is False and len(value) > 1)):
                    reject("Select values must match the current live schema.")
            else:
                reject("This minimal adapter only writes text/select; other types need adapters.")
        current = self.get(request.table, request.record_id)
        if current.content_digest != request.expected_digest:
            reject("Record content changed; reread the shared source before writing.")
        approval = current.fields.get("approval")
        if (set(request.fields) & set(table.material_fields) and isinstance(approval, list)
                and any(value in table.approved_values for value in approval)):
            reject("Approved material cannot be edited in place; resolve its approval first.")
        receipt = FeishuWriteReceipt(record_id=request.record_id, status="unverified",
                                     verified=False, dispatched=False,
                                     evidence_reference=request.evidence_reference)
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
