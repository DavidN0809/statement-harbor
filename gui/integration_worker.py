"""Independent optional integrations; an outage never stops provider dispatch."""
from __future__ import annotations

import json
import re
import time

from paperpull_core.services import configuration
from interventions import Notices
from mail_triggers import MailTriggers
from reconciliation import missing, periods


class Integrations:
    def __init__(self, store, outbox, panel):
        self.store, self.outbox, self.panel = store, outbox, panel
        self.notices = Notices(store)
        self.mail = None
        self.mail_config = None
        self.next_mail = 0
        self.missing = []
        self.status = "READY"
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS expectations (app TEXT,account TEXT,value TEXT,PRIMARY KEY(app,account))")
            db.execute("CREATE TABLE IF NOT EXISTS publication_retries (app TEXT,account TEXT,period TEXT,attempts INTEGER,last REAL,PRIMARY KEY(app,account,period))")

    def expectations(self):
        with self.store.db() as db:
            return [{"app": r[0], "account": r[1], "rules": json.loads(r[2])}
                    for r in db.execute("SELECT * FROM expectations")]

    def put(self, app, account, rules):
        from datetime import date
        from zoneinfo import ZoneInfo
        if not isinstance(rules, list) or len(rules) > 30:
            raise ValueError("invalid expectations")
        for rule in rules:
            if not isinstance(rule, dict) or rule.keys() - {"start", "cycle", "available_day", "grace_days", "publication_lag_months", "document_type", "account_key", "account_field", "zone", "retry_missing"}:
                raise ValueError("invalid expectation")
            if type(rule.get("retry_missing", False)) is not bool:
                raise ValueError("boolean required")
            if rule.get("account_key") and not re.fullmatch(r"[a-f0-9]{64}", rule["account_key"]):
                raise ValueError("account key must be SHA-256")
            if "account_field" in rule and not re.fullmatch(r"[a-z_]{1,40}", rule["account_field"]):
                raise ValueError("invalid account field")
            list(periods(rule, date.today()))
            ZoneInfo(rule.get("zone", "America/New_York"))
            if rule.get("document_type", "statement") not in {"statement", "tax", "bill", "notice"}:
                raise ValueError("invalid document type")
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO expectations VALUES (?,?,?)", (app, account, json.dumps(rules)))

    def overview(self):
        return {"status": self.status, "mail": self.mail.status if self.mail else "DISABLED",
                "notifications": self.notices.status, "suppression": self.notices.suppression(),
                "missing": self.missing, "expectations": self.expectations()}

    def retry_publication(self, app, account, rule, root):
        import calendar
        from datetime import date, datetime
        from zoneinfo import ZoneInfo
        if not rule.get("retry_missing") or not self.store.settings()["enabled"]:
            return
        today = datetime.now(ZoneInfo(rule.get("zone", "America/New_York"))).date()
        candidates = missing(rule | {"grace_days": 0}, root, today)
        if not candidates:
            return
        period = candidates[-1]
        # Retry only this publication window, never a historical archive gap.
        year, month = map(int, period.split("-"))
        y, m = divmod(year * 12 + month - 1 + int(rule.get("publication_lag_months", 1)), 12)
        due = date(y, m + 1, min(int(rule.get("available_day", 10)), calendar.monthrange(y, m + 1)[1]))
        if not 0 <= (today - due).days <= max(7, int(rule.get("grace_days", 7))):
            return
        now = time.time()
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT s.*,p.enabled AS provider_enabled FROM schedules s JOIN providers p USING(app) WHERE app=? AND account=?", (app, account)).fetchone()
            if (not row or not row["enabled"] or not row["provider_enabled"] or row["requested"]
                    or row["state"] not in {"COMPLETED", "NO_NEW_DOCUMENTS"}
                    or row["attempted"] is None or now - row["attempted"] < 86400):
                return
            last = db.execute("SELECT attempts,last FROM publication_retries WHERE app=? AND account=? AND period=?", (app, account, period)).fetchone()
            if last and (last[0] >= 2 or now - last[1] < 86400):
                return
            db.execute("INSERT INTO publication_retries VALUES (?,?,?,1,?) ON CONFLICT(app,account,period) DO UPDATE SET attempts=attempts+1,last=excluded.last", (app, account, period, now))
            db.execute("UPDATE schedules SET requested=2 WHERE app=? AND account=?", (app, account))

    def tick(self):
        try:
            config = configuration()
        except Exception:
            self.status = "CONFIGURATION_ERROR"
            return
        self.status = "READY"
        mail_config = config.get("mail", {})
        if self.mail_config != mail_config:
            self.mail_config = mail_config
            self.mail = MailTriggers(self.store, mail_config)
            self.next_mail = 0
        if time.time() >= self.next_mail:
            self.mail.poll()
            self.next_mail = time.time() + 900
        issues = []
        for row in self.store.rows():
            if row["state"] in {"AUTH_REQUIRED", "CHALLENGE_REQUIRED", "PAUSED"} or (row["state"] in {"FAILED", "RATE_LIMITED"} and row["failures"] >= 2):
                issues.append((row["app"], row["state"], row["account"]))
        self.missing = []
        for group in self.expectations():
            try:
                meta = self.panel.discover_apps()[group["app"]]
                root = self.panel._account_root(meta, group["account"])
                for index, rule in enumerate(group["rules"]):
                    values = missing(rule, root)
                    self.retry_publication(group["app"], group["account"], rule, root)
                    if values:
                        self.missing.append({"app": group["app"], "account": group["account"], "rule": index, "periods": values})
                        issues.append((group["app"], "MISSING", group["account"] + ":" + str(index)))
            except (KeyError, ValueError, OSError):
                self.status = "EXPECTATION_ERROR"
        for row in self.outbox.overview():
            if row["state"] == "CORRUPT":
                issues.append((row["provider"], "CORRUPT", row["id"]))
            elif row["state"] in {"API_FAILED", "UNCERTAIN", "SUBMITTING"} or row["error"]:
                issues.append((row["provider"], "DELIVERY", row["id"]))
        self.notices.sync(issues, config.get("home_assistant", {}))
