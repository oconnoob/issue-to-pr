from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import asyncio
from dataclasses import replace
import hashlib
import hmac
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from relay.app import MAX_BODY, create_app
from relay.config import Settings
from relay.delivery import Inbox, signature

EXECUTION = "7c1f9e2a-3b4c-5d6e-7f80-91a2b3c4d5e6"


@pytest.fixture
def event():
    return {
        "action": "labeled", "label": {"name": "agent"},
        "repository": {"full_name": "demo/project", "default_branch": "main",
                       "clone_url": "https://github.com/demo/project.git"},
        "issue": {"number": 7, "title": "Fix café", "body": "A small bug",
                  "html_url": "https://github.com/demo/project/issues/7",
                  "state": "open", "author_association": "MEMBER"},
        "sender": {"login": "labeler"},
    }


@pytest.fixture(params=["sqlite", "postgres"])
def settings(tmp_path, request):
    return Settings("demo/project", "github-test-secret", "lookup-test-token",
                    "https://api.digitalocean.com/test-trigger", "do-test-secret",
                    database=(request.getfixturevalue("postgres_url") if request.param == "postgres"
                              else str(tmp_path / "relay.sqlite3")))


@pytest.fixture
def make_client(settings):
    with ExitStack() as stack:
        def make(handler=None, config=None):
            calls = []

            def dispatch(request):
                calls.append(request)
                if handler:
                    return handler(request)
                return httpx.Response(202, json={"execution_id": EXECUTION})

            outbound = httpx.AsyncClient(transport=httpx.MockTransport(dispatch))
            app = create_app(config or settings, outbound, run_worker=False)
            client = stack.enter_context(TestClient(app))
            return client, app, calls

        yield make


def headers(body, delivery=None, event_name="issues"):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(
        b"github-test-secret", body, hashlib.sha256).hexdigest(),
        "X-GitHub-Delivery": delivery or str(uuid4()),
        "X-GitHub-Event": event_name, "Content-Type": "application/json"}


def send(client, event, delivery=None):
    body = json.dumps(event).encode()
    return client.post("/webhooks/github", content=body, headers=headers(body, delivery))


def run_one(client, app):
    return client.portal.call(app.state.worker.process_one)


def status(app):
    return dict(app.state.inbox.db.execute("SELECT * FROM deliveries").fetchone())


@pytest.mark.parametrize("received", ["", "sha1=abc", "sha256=wrong", "sha256=" + "0" * 64])
def test_reject_bad_signature(make_client, event, received):
    client, app, calls = make_client()
    body = json.dumps(event).encode()
    request_headers = headers(body)
    request_headers["X-Hub-Signature-256"] = received
    assert client.post("/webhooks/github", content=body, headers=request_headers).status_code == 401
    assert app.state.inbox.next() is None
    assert not calls


def test_signature_is_over_exact_received_bytes(make_client, event):
    client, _, _ = make_client()
    body = json.dumps(event).encode()
    assert client.post("/webhooks/github", content=body + b" ", headers=headers(body)).status_code == 401


@pytest.mark.parametrize("change,reason", [
    (lambda e: e.update(action="opened"), "not_labeled"),
    (lambda e: e["label"].update(name="other"), "different_label"),
    (lambda e: e["repository"].update(full_name="someone/else"), "different_repository"),
    (lambda e: e["issue"].update(pull_request={}), "pull_request"),
    (lambda e: e["issue"].update(state="closed"), "issue_not_open"),
])
def test_filters(make_client, event, change, reason):
    client, app, calls = make_client()
    change(event)
    response = send(client, event)
    assert response.status_code == 202
    assert response.json() == {"status": "skipped", "reason": reason}
    assert not run_one(client, app)
    assert not calls


def test_ping_and_unknown_source(make_client):
    client, _, calls = make_client()
    body = b"{}"
    assert client.post("/webhooks/github", content=body,
                       headers=headers(body, event_name="ping")).json()["reason"] == "not_issues"
    assert client.post("/webhooks/unknown").status_code == 404
    assert client.get("/healthz").status_code == 200
    assert not calls


def test_configurable_label(make_client, settings, event):
    client, app, _ = make_client(config=replace(settings, label="fix-it"))
    assert send(client, event).json()["reason"] == "different_label"
    event["label"]["name"] = "fix-it"
    assert send(client, event).json()["status"] == "queued"
    assert run_one(client, app)
    assert status(app)["status"] == "forwarded"


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_trusted_author_and_slim_signed_payload(make_client, event, association, monkeypatch):
    monkeypatch.setattr("relay.delivery.time.time", lambda: 1700000000)
    client, app, calls = make_client()
    event["issue"]["author_association"] = association
    assert send(client, event).json()["status"] == "queued"
    assert not calls  # HTTP acknowledgement precedes all external calls.
    assert run_one(client, app)
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    payload = json.loads(request.content)
    assert set(payload) == {"repository", "issue"}
    assert set(payload["issue"]) == {"number", "title", "body", "html_url"}
    assert "café" in request.content.decode()
    assert b"sender" not in request.content
    assert "authorization" not in request.headers  # Never forward the lookup token.
    expected = hmac.new(b"do-test-secret", b"1700000000." + request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-DigitalOcean-Signature"] == f"t=1700000000,v1={expected}"
    assert status(app)["execution_id"] == EXECUTION


def test_custom_signature_external_vector():
    # Independently generated with openssl dgst -sha256 -hmac do-test-secret.
    assert signature("do-test-secret", '{"issue":{"title":"Fix café"}}'.encode(), 1700000000) == (
        "t=1700000000,v1=cab06c7368590c6ac25950e88ec4c7cbb60caa1af01bd613b5bc4a317c95339f")


@pytest.mark.parametrize("lookup_status,expected", [(204, "forwarded"), (404, "skipped")])
def test_labeler_lookup(make_client, event, lookup_status, expected):
    def remote(request):
        if request.method == "GET":
            assert str(request.url) == "https://api.github.com/repos/demo/project/collaborators/labeler"
            assert request.headers["Authorization"] == "Bearer lookup-test-token"
            return httpx.Response(lookup_status)
        return httpx.Response(202, json={"execution_id": EXECUTION})

    client, app, calls = make_client(remote)
    event["issue"]["author_association"] = "NONE"
    send(client, event)
    run_one(client, app)
    assert status(app)["status"] == expected
    assert len(calls) == (2 if lookup_status == 204 else 1)


def test_repository_owner_labeler(make_client, event):
    client, app, calls = make_client()
    event["issue"]["author_association"] = "NONE"
    event["sender"]["login"] = "demo"
    send(client, event)
    run_one(client, app)
    assert status(app)["status"] == "forwarded"
    assert [request.method for request in calls] == ["POST"]


@pytest.mark.parametrize("code", [200, 301, 401, 403, 429, 500])
def test_authorization_errors_never_forward(make_client, event, code):
    client, app, calls = make_client(lambda request: httpx.Response(code))
    event["issue"]["author_association"] = "NONE"
    send(client, event)
    for attempt in range(5):
        app.state.inbox.db.execute("UPDATE deliveries SET next_at=0")
        app.state.inbox.db.commit()
        run_one(client, app)
    assert status(app)["status"] == "failed"
    assert status(app)["reason"] == "authorization_unavailable"
    assert all(request.method == "GET" for request in calls)


def test_dedup_under_concurrent_redelivery(make_client, event):
    client, app, calls = make_client()
    delivery = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client, event, delivery).json()["status"], range(10)))
    assert responses.count("queued") == 1
    assert responses.count("duplicate") == 9
    assert run_one(client, app)
    assert not run_one(client, app)
    assert len(calls) == 1


def test_queue_and_dedup_survive_restart(settings, event):
    delivery = str(uuid4())
    for iteration in range(2):
        outbound = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(202, json={"execution_id": EXECUTION})))
        app = create_app(settings, outbound, run_worker=False)
        with TestClient(app) as client:
            assert send(client, event, delivery).json()["status"] == ("queued" if iteration == 0 else "duplicate")
            if iteration:
                run_one(client, app)
                assert status(app)["status"] == "forwarded"


def test_crash_during_send_is_not_automatically_replayed(settings):
    inbox = Inbox(settings.database)
    inbox.enqueue("github", str(uuid4()), {"payload": {}})
    assert inbox.ensure_leader()
    inbox.update(inbox.next(), "sending")
    inbox.close()
    inbox = Inbox(settings.database)
    assert inbox.ensure_leader()
    assert inbox.next() is None
    assert inbox.db.execute("SELECT status FROM deliveries").fetchone()["status"] == "uncertain"
    inbox.close()


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(202), "no_execution_id_check_trigger_status"),
    (httpx.Response(202, json={"execution_id": "bad"}), "no_execution_id_check_trigger_status"),
    (httpx.Response(500), "trigger_http_500"),
    (httpx.Response(401), "trigger_http_401"),
    (httpx.Response(429), "trigger_http_429"),
    (httpx.Response(302), "trigger_http_302"),
])
def test_trigger_failures_are_not_success_or_silently_retried(make_client, event, response, expected):
    client, app, calls = make_client(lambda request: response)
    send(client, event)
    run_one(client, app)
    assert status(app)["status"] in {"uncertain", "failed"}
    assert status(app)["reason"] == expected
    assert not run_one(client, app)
    assert len(calls) == 1


def test_ambiguous_timeout(make_client, event):
    def timeout(request):
        raise httpx.ReadTimeout("Do not log this secret URL", request=request)

    client, app, calls = make_client(timeout)
    send(client, event)
    run_one(client, app)
    assert status(app)["status"] == "uncertain"
    assert not run_one(client, app)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"{bad", b"[]", b"null", b"\xff"])
def test_malformed_json(make_client, body):
    client, _, _ = make_client()
    assert client.post("/webhooks/github", content=body, headers=headers(body)).status_code == 400


@pytest.mark.parametrize("change", [
    lambda e: e["issue"].update(number=True),
    lambda e: e["issue"].update(number=-1),
    lambda e: e["issue"].update(body={"not": "text"}),
    lambda e: e["repository"].update(clone_url="https://evil.example/repo.git"),
    lambda e: e["issue"].update(html_url="https://evil.example/issue"),
    lambda e: e["sender"].update(login="../../evil"),
])
def test_malformed_fields(make_client, event, change):
    client, _, calls = make_client()
    change(event)
    assert send(client, event).status_code == 400
    assert not calls


def test_body_limit_and_delivery_id(make_client, event):
    client, _, _ = make_client()
    assert send(client, event, "not-a-uuid").status_code == 400
    body = b"a" * (MAX_BODY + 1)
    assert client.post("/webhooks/github", content=body, headers=headers(body)).status_code == 413


def test_logs_only_decisions(make_client, event, caplog):
    client, app, _ = make_client()
    event["issue"]["body"] = "PRIVATE-ISSUE-TEXT"
    with caplog.at_level("INFO", logger="relay"):
        send(client, event)
        run_one(client, app)
    assert "decision=queued" in caplog.text
    assert "decision=forwarded" in caplog.text
    for secret in ["PRIVATE-ISSUE-TEXT", "github-test-secret", "lookup-test-token", "do-test-secret"]:
        assert secret not in caplog.text


def test_background_worker_forwards_without_manual_step(settings, event):
    outbound = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(202, json={"execution_id": EXECUTION})))
    app = create_app(settings, outbound)
    with TestClient(app) as client:
        assert send(client, event).json()["status"] == "queued"

        async def wait_for_worker():
            async with asyncio.timeout(3):
                while status(app)["status"] != "forwarded":
                    await asyncio.sleep(0.01)

        client.portal.call(wait_for_worker)
        assert client.get("/healthz").status_code == 200


def test_worker_failure_is_unhealthy_without_leaking_exception(settings, event, caplog):
    def fail(request):
        raise RuntimeError("PRIVATE-URL-AND-TOKEN")

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    app = create_app(settings, outbound)
    with caplog.at_level("INFO", logger="relay"), TestClient(app) as client:
        send(client, event)

        async def wait_for_stop():
            async with asyncio.timeout(3):
                while not app.state.task.done():
                    await asyncio.sleep(0.01)

        client.portal.call(wait_for_stop)
        assert client.get("/healthz").status_code == 503
    assert "worker_stopped" in caplog.text
    assert "PRIVATE-URL-AND-TOKEN" not in caplog.text


@pytest.mark.parametrize("change", [
    {"HARNESS_TRIGGER_URL": "http://example.com/webhook"},
    {"HARNESS_TRIGGER_URL": "https://user:password@example.com/webhook"},
    {"HARNESS_TRIGGER_SECRET": "same-secret"},
    {"GITHUB_REPOSITORY": "invalid"},
    {"AGENT_LABEL": " "},
])
def test_invalid_configuration_fails_at_startup(monkeypatch, change):
    env = {"GITHUB_REPOSITORY": "demo/project", "GITHUB_WEBHOOK_SECRET": "same-secret",
           "RELAY_GITHUB_TOKEN": "lookup-token", "HARNESS_TRIGGER_URL": "https://example.com/webhook",
           "HARNESS_TRIGGER_SECRET": "different-secret", "AGENT_LABEL": "agent"}
    for key, value in (env | change).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_persistence_failure_is_not_acknowledged(make_client, event, monkeypatch):
    client, app, calls = make_client()

    def fail(*args):
        raise RuntimeError("PRIVATE-DATABASE-URL")

    monkeypatch.setattr(app.state.inbox, "enqueue", fail)
    response = send(client, event)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    assert not calls


def test_database_failure_is_unhealthy(make_client, monkeypatch):
    client, app, _ = make_client()

    def fail():
        raise RuntimeError("PRIVATE-DATABASE-URL")

    monkeypatch.setattr(app.state.inbox, "health", fail)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert "PRIVATE" not in response.text


def test_database_environment_selection(monkeypatch):
    monkeypatch.delenv("APP_PLATFORM", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_PATH", "/tmp/local.sqlite3")
    assert Settings.database_from_env() == "/tmp/local.sqlite3"
    monkeypatch.setenv("APP_PLATFORM", "true")
    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        Settings.database_from_env()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///ephemeral.db")
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        Settings.database_from_env()
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/relay")
    assert Settings.database_from_env() == "postgresql://localhost/relay"
