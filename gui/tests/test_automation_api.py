"""Authenticated API and lifecycle integration, with a synthetic run engine."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as panel
import server_mode


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "settings"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(panel, "discover_apps", lambda: {"Synthetic Bank": {
        "accounts": ["primary", "second"], "runnable": True, "dir": str(tmp_path / "data")}})
    monkeypatch.setattr(panel, "_RUNS", {})
    monkeypatch.setattr(server_mode, "INTERACTIVE_SCREENS", 0)
    server_mode.set_password("synthetic test passphrase")
    token = server_mode.new_session()
    with TestClient(panel.app, base_url="http://nas.local") as c:
        c.cookies.set(server_mode.SESSION_COOKIE, token)
        yield c
    server_mode._SESSIONS.clear()


def schedule(client, **extra):
    return client.post("/api/automation/schedule", json={
        "app": "Synthetic Bank", "account": "primary", "enabled": True, **extra})


def test_authentication_origin_and_host_protect_schedule(client):
    assert schedule(client).status_code == 200
    before = client.get("/api/automation").json()
    assert client.post("/api/automation/settings", json={"enabled": True},
                       headers={"Origin": "http://phishing.example"}).status_code == 403
    assert client.post("/api/automation/settings", json={"enabled": True},
                       headers={"Host": "untrusted.example"}).status_code == 400
    client.cookies.clear()
    assert client.post("/api/automation/settings", json={"enabled": True}).status_code == 401
    assert not before["settings"]["enabled"]


def test_backfill_range_is_durable_bounded_and_clears_after_success(client):
    schedule(client)
    assert client.post("/api/automation/backfill", json={"app": "Synthetic Bank", "start": "2026-02-30", "end": "2026-10-01"}).status_code == 400
    assert client.post("/api/automation/backfill", json={"app": "Synthetic Bank", "start": "2026-01-01", "end": "2026-10-01"}).status_code == 200
    store = panel.app.state.automation
    assert store.rows()[0]["range_start"] == "2026-01-01"
    store.finish("Synthetic Bank", "primary", "FAILED")
    assert store.rows()[0]["range_end"] == "2026-10-01"
    store.finish("Synthetic Bank", "primary", "COMPLETED")
    assert store.rows()[0]["range_start"] == ""


def test_expectations_and_notification_suppression(client):
    rule = {"start": "2026-01-01", "cycle": "quarterly"}
    assert client.post("/api/automation/expectations", json={"app": "Synthetic Bank", "rules": [rule]}).status_code == 200
    assert client.post("/api/automation/notifications", json={"app": "Synthetic Bank", "disabled": True}).status_code == 200
    value = client.get("/api/automation").json()["integrations"]
    assert value["suppression"] == {"Synthetic Bank": True}
    assert value["expectations"][0]["rules"] == [rule]


@pytest.mark.parametrize("operation,data", [
    ("schedule", {"app": "Unknown"}),
    ("schedule", {"app": "Synthetic Bank", "cron": "invalid"}),
    ("schedule", {"app": "Synthetic Bank", "zone": "No/SuchZone"}),
    ("schedule", {"app": "Synthetic Bank", "account": "../../elsewhere"}),
    ("schedule", {"app": "Synthetic Bank", "script": "arbitrary"}),
    ("settings", {"concurrency": 100}),
    ("settings", {"enabled": "yes"}),
    ("run", {"app": "Synthetic Bank"}),
])
def test_invalid_requests_make_no_jobs(client, operation, data):
    assert client.post("/api/automation/" + operation, json=data).status_code == 400
    assert client.get("/api/automation").json()["schedules"] == []


def test_human_states_require_resume_and_edit_does_not_clear_them(client):
    schedule(client)
    store = panel.app.state.automation
    store.finish("Synthetic Bank", "primary", "CHALLENGE_REQUIRED")
    assert schedule(client, cron="0 10 12 * *").status_code == 200
    assert store.rows()[0]["state"] == "CHALLENGE_REQUIRED"
    assert client.post("/api/automation/run", json={"app": "Synthetic Bank"}).status_code == 400
    assert client.post("/api/automation/reauthenticated", json={"app": "Synthetic Bank"}).status_code == 200
    assert store.rows()[0]["state"] == "READY"


@pytest.mark.parametrize("signal,expected,count", [
    (None, "COMPLETED", 2), (None, "NO_NEW_DOCUMENTS", 0),
    ("CHALLENGE_REQUIRED", "CHALLENGE_REQUIRED", 0),
    ("AUTH_REQUIRED", "AUTH_REQUIRED", 0), ("RATE_LIMITED", "RATE_LIMITED", 0),
])
def test_background_runs_use_existing_engine_and_survive_page_close(client, monkeypatch, signal, expected, count):
    calls = []
    def start(provider, account, action, scope, **kwargs):
        calls.append((provider, account, action, scope, kwargs))
        async def stream():
            if signal:
                yield "event: automation-state\ndata: " + signal + "\n\n"
            result = {"new_files": count, "attention": False, "stopped": int(bool(signal))}
            yield "event: result\ndata: " + json.dumps(result) + "\n\n"
            yield "event: done\ndata: 0\n\n"
        return StreamingResponse(stream())
    monkeypatch.setattr(panel, "_start_run", start)
    schedule(client)
    assert client.post("/api/automation/run", json={"app": "Synthetic Bank"}).status_code == 200
    # No run stream is held open by the client. The lifespan dispatches it.
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        rows = client.get("/api/automation").json()["schedules"]
        if rows[0]["state"] == expected:
            break
        time.sleep(0.05)
    assert rows[0]["state"] == expected
    assert calls == [("Synthetic Bank", "primary", "all", (), {"scheduled": True})]
    assert rows[0]["new_files"] == count


def test_interactive_screen_cancels_running_jobs_before_control(client, monkeypatch):
    cancelled = []
    def start(*args, **kwargs):
        async def stream():
            try:
                await asyncio.sleep(60)
                yield ""
            finally:
                cancelled.append(True)
        return StreamingResponse(stream())
    monkeypatch.setattr(panel, "_start_run", start)
    schedule(client)
    client.post("/api/automation/run", json={"app": "Synthetic Bank"})
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if panel.app.state.automation.rows()[0]["state"] == "RUNNING":
            break
        time.sleep(0.05)
    # The browser-screen connection invokes this callback before bridging input.
    client.portal.call(panel.app.state.pause_automation)
    assert cancelled
    assert panel.app.state.automation.rows()[0]["state"] == "PAUSED"


def test_delivery_retry_is_local_only(client, monkeypatch):
    monkeypatch.setattr(panel, "_start_run", lambda *a, **k: pytest.fail("must not access provider"))
    assert client.post("/api/automation/delivery", json={}).status_code == 200
    assert client.get("/automation").status_code == 200
    assert "Statement Harbor" in client.get("/automation").text


def test_health_reveals_no_private_state_and_fails_when_dispatch_is_unhealthy(client):
    client.cookies.clear()
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").text == "ok"
    panel.app.state.dispatcher.healthy = False
    assert client.get("/healthz").status_code == 503
    assert client.get("/healthz").text == "unavailable"
