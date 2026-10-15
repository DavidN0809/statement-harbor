"""Statement Harbor durable dispatcher. SQLite holds data, never pickled jobs.

APScheduler supplies timezone-aware cron calculations. A single ASGI lifespan
owns dispatch and the existing panel run engine owns all provider work.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from paperpull_core.process_lock import ProcessLock as ProcessLock

STATES = frozenset({"READY", "RUNNING", "AUTH_REQUIRED", "CHALLENGE_REQUIRED",
                    "RATE_LIMITED", "COMPLETED", "NO_NEW_DOCUMENTS", "FAILED", "PAUSED"})
HUMAN = {"AUTH_REQUIRED", "CHALLENGE_REQUIRED", "PAUSED"}
DEFAULTS = {"enabled": False, "concurrency": 2, "retry_seconds": 21600,
            "max_retries": 2, "min_interval": 21600, "timeout_seconds": 3600}


def next_time(cron, zone, after):
    trigger = CronTrigger.from_crontab(cron, timezone=ZoneInfo(zone))
    # Strictly later, and persisted as UTC epoch so the repeated DST hour
    # cannot cause the same instant to be dispatched twice.
    from datetime import timedelta
    value = trigger.get_next_fire_time(None, datetime.fromtimestamp(after, timezone.utc)
                                       + timedelta(seconds=1))
    if value is None:
        raise ValueError("schedule has no future occurrence")
    return value.timestamp()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS providers (app TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS schedules (
                  app TEXT NOT NULL, account TEXT NOT NULL, enabled INTEGER NOT NULL,
                  cron TEXT NOT NULL, zone TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'READY',
                  next REAL NOT NULL, attempted REAL, successful REAL,
                  failures INTEGER NOT NULL DEFAULT 0, new_files INTEGER NOT NULL DEFAULT 0,
                  requested INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(app, account));
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, at REAL NOT NULL, app TEXT NOT NULL,
                  state TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (json.dumps(DEFAULTS),))
            columns = {r[1] for r in db.execute("PRAGMA table_info(schedules)")}
            for column in ("range_start", "range_end"):
                if column not in columns:
                    db.execute(f"ALTER TABLE schedules ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self, changes=None):
        with self.db() as db:
            value = DEFAULTS | json.loads(db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])
            if changes is not None:
                if not isinstance(changes, dict) or changes.keys() - DEFAULTS.keys():
                    raise ValueError("unknown settings")
                if "enabled" in changes and type(changes["enabled"]) is not bool:
                    raise ValueError("enabled must be a boolean")
                for key, low, high in (("concurrency", 1, 8), ("retry_seconds", 3600, 604800),
                                       ("min_interval", 3600, 604800), ("max_retries", 0, 5),
                                       ("timeout_seconds", 60, 14400)):
                    if key in changes and (type(changes[key]) is not int or not low <= changes[key] <= high):
                        raise ValueError("invalid " + key)
                value.update(changes)
                db.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(value),))
            return value

    def put(self, app, account, cron="0 9 10 * *", zone="America/New_York", enabled=False):
        if type(enabled) is not bool or not isinstance(cron, str) or not isinstance(zone, str):
            raise ValueError("invalid schedule")
        due = next_time(cron, zone, time.time())
        with self.db() as db:
            db.execute("""INSERT INTO schedules(app,account,enabled,cron,zone,next) VALUES (?,?,?,?,?,?)
              ON CONFLICT(app,account) DO UPDATE SET enabled=excluded.enabled, cron=excluded.cron,
              zone=excluded.zone, next=excluded.next""", (app, account, enabled, cron, zone, due))
            db.execute("INSERT OR IGNORE INTO providers VALUES (?,1)", (app,))

    def provider(self, app, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO providers VALUES (?,?)", (app, enabled))

    def rows(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT s.*, p.enabled AS provider_enabled FROM schedules s JOIN providers p USING(app) ORDER BY app,account")]

    def events(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT at,app,state FROM events ORDER BY id DESC LIMIT 100")]

    def request(self, app, account, reauthenticated=False, start="", end=""):
        if start or end:
            from datetime import date
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if first > last or (last - first).days > 3660:
                raise ValueError("invalid historical range")
            start, end = first.isoformat(), last.isoformat()
        with self.db() as db:
            row = db.execute("SELECT state,next FROM schedules WHERE app=? AND account=?", (app, account)).fetchone()
            if row is None:
                raise ValueError("save a schedule first")
            if row[0] == "RUNNING":
                raise ValueError("account is running")
            if row[0] in HUMAN and not reauthenticated:
                raise ValueError("resolve the sign-in or challenge, then explicitly resume")
            if row[0] == "RATE_LIMITED" and row[1] > time.time():
                raise ValueError("provider backoff is still active")
            if reauthenticated and not start and not end:
                pending = db.execute("SELECT range_start,range_end FROM schedules WHERE app=? AND account=?", (app, account)).fetchone()
                start, end = pending
            db.execute("UPDATE schedules SET requested=1, state='READY', failures=0,range_start=?,range_end=? WHERE app=? AND account=?", (start, end, app, account))

    def recover(self):
        # Called only after the exclusive process lock is acquired. Missed jobs
        # coalesce to one run. A full discovery reuses the engine's sticky ledger.
        with self.db() as db:
            db.execute("UPDATE schedules SET state='READY',requested=2 WHERE state='RUNNING'")

    def trigger(self, app, account):
        """Untrusted external hints never override enablement, backoff or auth."""
        with self.db() as db:
            row = db.execute("SELECT * FROM schedules WHERE app=? AND account=?", (app, account)).fetchone()
            if row and row["state"] not in HUMAN | {"RUNNING", "FAILED", "RATE_LIMITED"}:
                db.execute("UPDATE schedules SET requested=2 WHERE app=? AND account=?", (app, account))

    def claim(self, app, account, now):
        cfg = self.settings()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT s.*,p.enabled AS provider_enabled FROM schedules s JOIN providers p USING(app) WHERE app=? AND account=?", (app, account)).fetchone()
            if (not row or (row["requested"] != 1 and
                           (not cfg["enabled"] or not row["enabled"] or not row["provider_enabled"]))
                    or row["state"] in HUMAN | {"RUNNING"}
                    or (row["state"] in {"FAILED", "RATE_LIMITED"} and row["failures"] > cfg["max_retries"])
                    or (not row["requested"] and row["next"] > now)
                    or (row["requested"] != 1 and row["attempted"] is not None
                        and now - row["attempted"] < cfg["min_interval"])):
                return False
            if db.execute("SELECT count(*) FROM schedules WHERE state='RUNNING'").fetchone()[0] >= cfg["concurrency"]:
                return False
            db.execute("UPDATE schedules SET state='RUNNING',attempted=?,requested=0 WHERE app=? AND account=?", (now, app, account))
            return True

    def finish(self, app, account, state, count=0, now=None):
        if state not in STATES - {"RUNNING"}:
            raise ValueError("invalid outcome")
        now = time.time() if now is None else now
        cfg = self.settings()
        with self.db() as db:
            row = db.execute("SELECT * FROM schedules WHERE app=? AND account=?", (app, account)).fetchone()
            failures = row["failures"] + 1 if state in {"FAILED", "RATE_LIMITED"} else 0
            due = next_time(row["cron"], row["zone"], now)
            if failures and failures <= cfg["max_retries"]:
                due = now + max(cfg["min_interval"], cfg["retry_seconds"] * 2 ** (failures - 1))
            success = now if state in {"COMPLETED", "NO_NEW_DOCUMENTS"} else row["successful"]
            db.execute("UPDATE schedules SET state=?, next=?,failures=?,successful=?,new_files=? WHERE app=? AND account=?", (state, due, failures, success, count, app, account))
            if state in {"COMPLETED", "NO_NEW_DOCUMENTS"}:
                db.execute("UPDATE schedules SET range_start='',range_end='' WHERE app=? AND account=?", (app, account))
            # Fixed enum and provider install name only, no child output or account.
            db.execute("INSERT INTO events(at,app,state) VALUES (?,?,?)", (now, app, state))
            db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 500)")


class Dispatcher:
    def __init__(self, store, execute, busy):
        self.store, self.execute, self.busy = store, execute, busy
        self.tasks = set()
        self.healthy = True

    async def tick(self):
        if not self.healthy:
            return
        for row in self.store.rows():
            if self.busy(row["app"], row["account"]):
                continue
            if self.store.claim(row["app"], row["account"], time.time()):
                task = asyncio.create_task(self.run(row))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

    async def run(self, row):
        state, count = "FAILED", 0
        try:
            state, count = await asyncio.wait_for(self.execute(row), self.store.settings()["timeout_seconds"])
        except asyncio.CancelledError:
            # Keep RUNNING durably, for startup recovery.
            raise
        except Exception:
            # Never persist exception text, URLs or child-process output.
            pass
        try:
            self.store.finish(row["app"], row["account"], state, count)
        except Exception:
            # Lost durable state must stop dispatch. The health probe will
            # fail and an operator can repair storage before recovery.
            self.healthy = False

    async def loop(self):
        try:
            while True:
                await self.tick()
                await asyncio.sleep(5)
        except Exception:
            self.healthy = False
        finally:
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
