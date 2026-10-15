"""Synthetic-only durable automation contracts. No financial sites contacted."""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation import Dispatcher, ProcessLock, Store, next_time
from paperpull_core.automation_runner import guard_site


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "automation.sqlite3")
    s.settings({"enabled": True, "min_interval": 3600, "retry_seconds": 3600})
    s.put("Synthetic Bank", "primary", enabled=True)
    s.request("Synthetic Bank", "primary")
    return s


def test_schedule_and_global_setting_survive_restart(store):
    again = Store(store.path)
    assert again.settings()["enabled"]
    assert again.rows()[0]["cron"] == "0 9 10 * *"
    assert again.rows()[0]["requested"] == 1


def test_claim_is_atomic_across_connections(store):
    from concurrent.futures import ThreadPoolExecutor
    def claim(_):
        return Store(store.path).claim("Synthetic Bank", "primary", time.time())
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1


def test_global_provider_and_account_disable(store):
    with store.db() as db:
        db.execute("UPDATE schedules SET requested=0,next=0")
    store.settings({"enabled": False})
    assert not store.claim("Synthetic Bank", "primary", time.time())
    store.settings({"enabled": True})
    store.provider("Synthetic Bank", False)
    assert not store.claim("Synthetic Bank", "primary", time.time())
    store.provider("Synthetic Bank", True)
    store.put("Synthetic Bank", "primary", enabled=False)
    assert not store.claim("Synthetic Bank", "primary", time.time())


def test_global_limit_and_different_accounts(store):
    store.settings({"concurrency": 1})
    store.put("Other", "second", enabled=True)
    store.request("Other", "second")
    assert store.claim("Synthetic Bank", "primary", time.time())
    assert not store.claim("Other", "second", time.time())
    store.settings({"concurrency": 2})
    assert store.claim("Other", "second", time.time())


def test_restart_recovers_only_interrupted_jobs(store):
    now = time.time()
    assert store.claim("Synthetic Bank", "primary", now)
    again = Store(store.path)
    again.recover()
    assert again.rows()[0]["state"] == "READY"
    assert not again.claim("Synthetic Bank", "primary", now + 1)
    assert again.claim("Synthetic Bank", "primary", now + 3601)


@pytest.mark.parametrize("state", ["AUTH_REQUIRED", "CHALLENGE_REQUIRED", "PAUSED"])
def test_human_states_never_retry_until_explicit_resume(store, state):
    now = time.time()
    store.finish("Synthetic Bank", "primary", state, now=now)
    store.recover()
    assert not store.claim("Synthetic Bank", "primary", now + 1e7)
    with pytest.raises(ValueError):
        store.request("Synthetic Bank", "primary")
    store.request("Synthetic Bank", "primary", reauthenticated=True)
    assert store.claim("Synthetic Bank", "primary", now + 1e7)


@pytest.mark.parametrize("state", ["FAILED", "RATE_LIMITED"])
def test_bounded_exponential_retries(store, state):
    now = time.time()
    for failure in range(1, 4):
        store.finish("Synthetic Bank", "primary", state, now=now)
        row = store.rows()[0]
        assert row["failures"] == failure
        if failure <= 2:
            assert row["next"] == now + 3600 * 2 ** (failure - 1)
        now = row["next"] + 1
    assert not store.claim("Synthetic Bank", "primary", now + 1e7)


def test_success_and_no_new_counts(store):
    store.finish("Synthetic Bank", "primary", "COMPLETED", 2, now=1000)
    row = store.rows()[0]
    assert row["successful"] == 1000 and row["new_files"] == 2
    store.finish("Synthetic Bank", "primary", "NO_NEW_DOCUMENTS", now=2000)
    assert store.rows()[0]["successful"] == 2000


@pytest.mark.parametrize("changes", [{"enabled": "true"}, {"concurrency": True},
    {"concurrency": 0}, {"min_interval": 1}, {"timeout_seconds": 999999}, {"shell": "anything"}])
def test_untrusted_settings_rejected(store, changes):
    with pytest.raises(ValueError):
        store.settings(changes)


def test_bad_schedule_is_not_saved(store):
    for cron, zone in [("broken", "America/New_York"), ("0 9 * * *", "No/SuchZone")]:
        with pytest.raises((ValueError, KeyError)):
            store.put("Other", "primary", cron, zone)
    assert len(store.rows()) == 1


def test_month_boundaries_and_dst():
    def epoch(text):
        return datetime.fromisoformat(text).timestamp()
    assert next_time("0 9 10 * *", "America/New_York", epoch("2026-02-28T23:00:00+00:00")) == epoch("2026-03-10T13:00:00+00:00")
    assert next_time("0 9 10 * *", "America/New_York", epoch("2026-10-31T23:00:00+00:00")) == epoch("2026-11-10T14:00:00+00:00")
    assert next_time("0 9 31 * *", "America/New_York", epoch("2026-01-31T15:00:00+00:00")) == epoch("2026-03-31T13:00:00+00:00")
    assert next_time("0 9 * * *", "America/New_York", epoch("2026-03-08T05:00:00+00:00")) == epoch("2026-03-08T13:00:00+00:00")
    assert next_time("0 9 * * *", "America/New_York", epoch("2026-11-01T04:00:00+00:00")) == epoch("2026-11-01T14:00:00+00:00")


def test_durable_write_failure_stops_dispatch(store, monkeypatch):
    async def scenario():
        async def execute(row):
            return "COMPLETED", 1
        d = Dispatcher(store, execute, lambda *args: False)
        def broken(*args):
            raise OSError("synthetic storage unavailable")
        monkeypatch.setattr(store, "finish", broken)
        await d.run(store.rows()[0])
        assert not d.healthy
        await d.tick()
        assert not d.tasks
    asyncio.run(scenario())


def test_duplicate_worker_fails_closed(tmp_path):
    path = tmp_path / "process.lock"
    first = ProcessLock(path)
    try:
        with pytest.raises(RuntimeError):
            ProcessLock(path)
    finally:
        first.close()
    ProcessLock(path).close()


def test_dispatcher_parallelism_busy_pause_and_completion(store):
    async def scenario():
        gate = asyncio.Event()
        calls = []
        async def execute(row):
            calls.append(row["app"])
            await gate.wait()
            return "COMPLETED", 2
        store.put("Other", "primary", enabled=True)
        store.request("Other", "primary")
        d = Dispatcher(store, execute, lambda *args: True)
        await d.tick()
        assert not d.tasks
        d.busy = lambda *args: False
        await d.tick()
        await asyncio.sleep(0)
        await d.tick()
        assert len(d.tasks) == 2
        assert sorted(calls) == ["Other", "Synthetic Bank"]
        gate.set()
        await asyncio.gather(*d.tasks)
        assert all(r["state"] == "COMPLETED" for r in store.rows())
    asyncio.run(scenario())


def test_errors_never_persist_exception_text(store):
    async def scenario():
        async def execute(row):
            raise RuntimeError("password=secret account=123456789 token=private")
        d = Dispatcher(store, execute, lambda *args: False)
        await d.run(store.rows()[0])
    asyncio.run(scenario())
    assert b"123456789" not in store.path.read_bytes()
    assert b"password=" not in store.path.read_bytes()


@pytest.mark.parametrize("signed_out,challenge,expected", [(True,False,"AUTH_REQUIRED"),
    (False,True,"CHALLENGE_REQUIRED"), (True,True,"CHALLENGE_REQUIRED")])
def test_provider_detectors_stop_before_any_authentication_action(signed_out, challenge, expected, capsys):
    site = SimpleNamespace(looks_signed_out=lambda p: signed_out,
                           detect_security_challenge=lambda p: "private text" if challenge else None,
                           is_safe_url=lambda url: True)
    guard_site(site)
    with pytest.raises(SystemExit):
        site.looks_signed_out(object())
    assert capsys.readouterr().out == "HARBOR_STATE " + expected + "\n"


def test_missing_provider_contract_fails_closed(capsys):
    with pytest.raises(SystemExit):
        guard_site(SimpleNamespace())
    assert capsys.readouterr().out == "HARBOR_STATE PAUSED\n"


def test_rate_limit_stops_next_provider_operation_without_logging_response(capsys):
    site = SimpleNamespace(looks_signed_out=lambda page: False,
                           detect_security_challenge=lambda page: None,
                           is_safe_url=lambda url: url.startswith("https://bank.example/"))
    watch = guard_site(site)
    watch.observe(SimpleNamespace(status=429, url="https://third-party.example/private"))
    assert site.is_safe_url("https://bank.example/documents")
    watch.observe(SimpleNamespace(status=429, url="https://bank.example/document?token=private"))
    with pytest.raises(SystemExit):
        site.is_safe_url("https://bank.example/another-document")
    assert capsys.readouterr().out == "HARBOR_STATE RATE_LIMITED\n"
