import http.client
import json
from threading import Thread


def test_http_is_read_only_scoped_and_never_serves_private_paths(tmp_path):
    from jobagent.console.server import make_server

    assets = tmp_path / "dist"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>Console</h1>", encoding="utf-8")
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")
    server = make_server(tmp_path / "absent.sqlite3", tmp_path, "CAND_DEMO", assets, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request("GET", "/api/snapshot")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["candidate_id"] == "CAND_DEMO"
        for method, path, headers, expected in [
            ("POST", "/api/snapshot", {}, 405),
            ("GET", "/api/snapshot", {"Host": "evil.test"}, 403),
            ("GET", "/api/snapshot", {"Origin": "https://evil.test"}, 403),
            ("GET", "/api/snapshot", {"Sec-Fetch-Site": "cross-site"}, 403),
            ("GET", "/../private.txt", {}, 404),
            ("GET", "/assets/%2e%2e/%2e%2e/private.txt", {}, 404),
        ]:
            client.request(method, path, headers=headers)
            response = client.getresponse()
            assert response.status == expected, (method, path, headers, response.status)
            assert b"secret" not in response.read()
        client.request("GET", "/api/definitions")
        response = client.getresponse()
        assert response.status == 200 and b"jd_text" in response.read()
        client.request("GET", "/")
        response = client.getresponse()
        assert response.status == 200 and b"Console" in response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_missing_assets_reports_build_required(tmp_path):
    from jobagent.console.server import make_server

    server = make_server(
        tmp_path / "missing.sqlite3", tmp_path, "CAND_DEMO", tmp_path / "missing-dist", port=0
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request("GET", "/")
        response = client.getresponse()
        assert response.status == 503
        assert b"build" in response.read()
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _serve(tmp_path, **options):
    from jobagent.console.server import make_server

    assets = tmp_path / "dist"
    assets.mkdir(exist_ok=True)
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    server = make_server(database, tmp_path, "CAND_SYNTHETIC", assets, port=0, **options)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, database


def _post(server, path, body=b"{}", kind="application/json", **extra):
    host = f"127.0.0.1:{server.server_port}"
    headers = {
        "Host": host,
        "Origin": f"http://{host}",
        "Content-Type": kind,
        "X-CareerHarness-Intent": "onboarding",
        **extra,
    }
    client = http.client.HTTPConnection("127.0.0.1", server.server_port)
    client.request("POST", path, body=body, headers=headers)
    response = client.getresponse()
    data = response.read()
    client.close()
    return response.status, json.loads(data)


def test_onboarding_is_readable_but_not_writable_by_default(tmp_path):
    server, thread, database = _serve(tmp_path)
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        client.request("GET", "/api/onboarding")
        response = client.getresponse()
        state = json.loads(response.read())
        assert response.status == 200
        assert (state["stage"], state["source"], state["writable"]) == (
            "not_started",
            "missing",
            False,
        )
        client.close()
        status, _ = _post(server, "/api/onboarding/start")
        assert status == 405 and not database.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_onboarding_writes_need_same_origin_and_the_intent_header(tmp_path):
    server, thread, database = _serve(tmp_path, onboarding_writes=True)
    try:
        for extra in (
            {"Origin": "https://evil.test"},
            {"X-CareerHarness-Intent": "other"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Host": "evil.test"},
        ):
            status, _ = _post(server, "/api/onboarding/start", **extra)
            assert status == 403, extra
        status, _ = _post(server, "/api/onboarding/start", kind="text/plain")
        assert status == 400
        assert not database.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_onboarding_flow_over_http_reads_back_saved_state(tmp_path):
    server, thread, database = _serve(tmp_path, onboarding_writes=True)
    try:
        status, body = _post(server, "/api/onboarding/start")
        assert status == 200 and body["state"]["stage"] == "collecting"
        status, body = _post(server, "/api/onboarding/question")
        question = body["state"]["open_question"]
        assert question["gap_id"] == "GAP_EXPERIENCE"
        status, body = _post(
            server,
            "/api/onboarding/answer",
            json.dumps(
                {"question_id": question["question_id"], "answer": "Ran a synthetic pilot."}
            ).encode(),
        )
        [fact] = body["state"]["facts"]
        assert status == 200 and fact["confirmed"] is False
        status, body = _post(
            server,
            "/api/onboarding/confirm",
            json.dumps(
                {"evidence_id": fact["evidence_id"], "statement_digest": "sha256:x"}
            ).encode(),
        )
        assert status == 409 and body["error"]["code"] == "STALE_APPROVAL"
        assert body["state"]["facts"][0]["confirmed"] is False
        status, body = _post(
            server,
            "/api/onboarding/confirm",
            json.dumps(
                {"evidence_id": fact["evidence_id"], "statement_digest": fact["statement_digest"]}
            ).encode(),
        )
        assert status == 200 and body["state"]["stage"] == "ready"
        status, body = _post(server, "/api/onboarding/resume", b"not a pdf", kind="application/pdf")
        assert status == 409 and body["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
        assert database.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
