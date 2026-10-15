"""Persistent, sanitized, deduplicated Home Assistant intervention notices."""
from __future__ import annotations

import hashlib
import re
import time

from paperpull_core.services import Service

MESSAGES = {
    "AUTH_REQUIRED": "Sign in again, close the browser screen, then resume automation.",
    "CHALLENGE_REQUIRED": "Complete the security challenge yourself, then resume automation.",
    "PAUSED": "Inspect the provider document page and resume after resolving the stop.",
    "FAILED": "Repeated download failure. Inspect the provider document page for website changes.",
    "RATE_LIMITED": "Repeated provider rate limiting. Review the check frequency.",
    "MISSING": "An expected statement is missing. Review archive expectations and the provider portal.",
    "CORRUPT": "A PDF failed validation. Inspect the private archive and retry the document download.",
    "DELIVERY": "Paperless delivery needs attention. Check service access and the delivery queue.",
}


class Notices:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS notices (
                key TEXT PRIMARY KEY, app TEXT NOT NULL, kind TEXT NOT NULL, sent REAL, active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS suppression (app TEXT PRIMARY KEY, disabled INTEGER NOT NULL);""")
            columns = {r[1] for r in db.execute("PRAGMA table_info(notices)")}
            if "created" not in columns:
                db.execute("ALTER TABLE notices ADD COLUMN created REAL NOT NULL DEFAULT 0")
        self.status = "DISABLED"

    def suppress(self, app, disabled):
        if type(disabled) is not bool:
            raise ValueError("boolean required")
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO suppression VALUES (?,?)", (app, disabled))

    def suppression(self):
        with self.store.db() as db:
            return {r[0]: bool(r[1]) for r in db.execute("SELECT app,disabled FROM suppression")}

    def sync(self, issues, config):
        # Stable hashes identify incidents without transmitting any account IDs.
        current = set()
        with self.store.db() as db:
            for app, kind, incident in issues:
                if kind not in MESSAGES:
                    continue
                key = hashlib.sha256((app + "\0" + kind + "\0" + incident).encode()).hexdigest()
                current.add(key)
                db.execute("""INSERT INTO notices(key,app,kind,sent,active,created) VALUES (?,?,?,NULL,1,?) ON CONFLICT(key) DO UPDATE
                              SET sent=CASE WHEN active=0 THEN NULL ELSE sent END,
                              created=CASE WHEN active=0 THEN excluded.created ELSE created END,active=1""", (key, app, kind, time.time()))
            for row in db.execute("SELECT key FROM notices WHERE active=1").fetchall():
                if row[0] not in current:
                    db.execute("UPDATE notices SET active=0 WHERE key=?", (row[0],))
            db.execute("DELETE FROM notices WHERE active=0 AND (sent IS NULL OR sent<?)", (time.time() - 90 * 86400,))
        if not config.get("enabled"):
            self.status = "DISABLED"
            return
        try:
            http = Service(config, "Bearer")
            with self.store.db() as db:
                rows = db.execute("""SELECT n.* FROM notices n LEFT JOIN suppression s USING(app)
                    WHERE active=1 AND sent IS NULL AND COALESCE(s.disabled,0)=0""").fetchall()
            for row in rows:
                if row["kind"] == "DELIVERY" and time.time() - row["created"] < 3600:
                    continue
                provider = re.sub(r"[^A-Za-z -]", "", row["app"])[:60] or "Institution"
                http.json("/api/services/persistent_notification/create", {
                    "title": "Statement Harbor: " + provider,
                    "message": MESSAGES[row["kind"]], "notification_id": "harbor-" + row["key"]})
                with self.store.db() as db:
                    db.execute("UPDATE notices SET sent=? WHERE key=?", (time.time(), row["key"]))
            self.status = "READY"
        except Exception:
            self.status = "UNAVAILABLE"
