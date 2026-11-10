"""Loopback-only adapter; no arbitrary private file access.

GET is read-only. The only writes are the first-use onboarding actions, and only
when the server was started with them explicitly enabled. They call the
Candidate Core services and answer with the state read back from storage.
"""

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

from pydantic import TypeAdapter

from jobagent.console.onboarding import (
    MAX_RESUME_BYTES,
    OnboardingWriter,
    dumps,
    onboarding_state,
)
from jobagent.console.projection import definitions, snapshot
from jobagent.errors import JobAgentError
from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.onboarding import OnboardingState

# A custom header forces a CORS preflight, which this server never grants.
INTENT_HEADER = "X-CareerHarness-Intent"
_JSON_LIMIT = 64 * 1024


def _json_object(raw: bytes | None) -> dict[str, object] | None:
    try:
        loaded = json.loads(raw) if raw is not None else None
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def make_server(
    database: Path,
    workspace: Path,
    candidate_id: str,
    assets: Path,
    *,
    port: int = 8765,
    onboarding_writes: bool = False,
) -> ThreadingHTTPServer:
    candidate_id = TypeAdapter(CandidateId).validate_python(candidate_id)
    root = assets.resolve()
    writer = OnboardingWriter(database, candidate_id) if onboarding_writes else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def reply(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def error_json(self, status: int, code: str) -> None:
            self.reply(
                status,
                json.dumps({"error": {"code": code}}).encode(),
                "application/json; charset=utf-8",
            )

        def allowed(self) -> bool:
            port_number = cast(ThreadingHTTPServer, self.server).server_port
            hosts = {f"127.0.0.1:{port_number}", f"localhost:{port_number}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return (
                host in hosts
                and (origin is None or origin == f"http://{host}")
                and self.headers.get("Sec-Fetch-Site") != "cross-site"
            )

        def refuse(self) -> None:
            self.error_json(405, "read_only")

        do_PUT = refuse
        do_PATCH = refuse
        do_DELETE = refuse
        do_OPTIONS = refuse

        def same_origin_write(self) -> bool:
            host = self.headers.get("Host", "")
            return (
                self.allowed()
                and self.headers.get("Origin") == f"http://{host}"
                and self.headers.get("Sec-Fetch-Site") in (None, "same-origin")
                and self.headers.get(INTENT_HEADER) == "onboarding"
            )

        def body(self, limit: int) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return None
            if not 0 <= length <= limit:
                return None
            return self.rfile.read(length)

        def state_reply(self, status: int, state: OnboardingState, error: str = "") -> None:
            payload = state.model_dump(mode="json")
            body = {"state": payload} if not error else {"error": {"code": error}, "state": payload}
            self.reply(
                status,
                json.dumps(body, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_POST(self) -> None:
            path = unquote(urlsplit(self.path).path)
            if writer is None or not path.startswith("/api/onboarding/"):
                self.refuse()
                return
            if not self.same_origin_write():
                self.error_json(403, "local_origin_required")
                return
            action = path.removeprefix("/api/onboarding/")
            kind = self.headers.get("Content-Type", "").split(";")[0].strip()
            content: bytes | None = b""
            fields: dict[str, object] | None = {}
            if action == "resume":
                content = self.body(MAX_RESUME_BYTES) if kind == "application/pdf" else None
            else:
                raw = self.body(_JSON_LIMIT) if kind == "application/json" else None
                fields = _json_object(raw)
            if content is None or fields is None:
                self.error_json(400, "invalid_request")
                return

            def text(name: str) -> str:
                value = fields.get(name)
                return value if isinstance(value, str) else ""

            try:
                if action == "start":
                    state = writer.start()
                elif action == "resume":
                    state = writer.add_resume(content, unquote(self.headers.get("X-File-Name", "")))
                elif action == "import":
                    state = writer.import_extraction(text("request_id"))
                elif action == "question":
                    state = writer.ask()
                elif action == "answer":
                    skip = fields.get("skip") is True
                    state = writer.answer(
                        text("question_id"), None if skip else text("answer") or None, skip=skip
                    )
                elif action == "confirm":
                    state = writer.confirm(text("evidence_id"), text("statement_digest"))
                elif action == "edit":
                    state = writer.edit(
                        text("evidence_id"), text("statement_digest"), text("statement")
                    )
                else:
                    self.error_json(404, "not_found")
                    return
            except JobAgentError as error:
                self.state_reply(409, writer.state(), error.code)
                return
            except (OSError, ValueError):
                self.state_reply(503, writer.state(), "source_unavailable")
                return
            self.state_reply(200, state)

        def do_GET(self) -> None:
            if not self.allowed():
                self.error_json(403, "local_origin_required")
                return
            path = unquote(urlsplit(self.path).path)
            if path == "/api/onboarding":
                state = onboarding_state(database, candidate_id, writable=writer is not None)
                self.reply(200, dumps(state), "application/json; charset=utf-8")
                return
            if path in {"/api/snapshot", "/api/definitions"}:
                try:
                    data = (
                        snapshot(database, workspace, candidate_id).model_dump(mode="json")
                        if path == "/api/snapshot"
                        else definitions()
                    )
                    self.reply(
                        200,
                        json.dumps(data, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8",
                    )
                except (OSError, ValueError):
                    self.error_json(503, "source_unavailable")
                return
            if path == "/":
                target = root / "index.html"
            elif path.startswith("/assets/") and ".." not in path.split("/"):
                target = (root / path.lstrip("/")).resolve()
            else:
                self.error_json(404, "not_found")
                return
            if not target.is_relative_to(root) or target.is_symlink():
                self.error_json(404, "not_found")
                return
            try:
                content = target.read_bytes()
            except OSError:
                self.error_json(
                    503 if path == "/" else 404,
                    "frontend_build_required" if path == "/" else "not_found",
                )
                return
            self.reply(
                200, content, mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
