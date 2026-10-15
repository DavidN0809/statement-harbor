import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation import Store
from interventions import Notices
from mail_triggers import MailTriggers, match
from reconciliation import missing, periods


def message(sender="billing@bank.example", result="pass", extra=""):
    return (f"From: {sender}\r\nSubject: Your statement is available 2026-10\r\n"
            f"Authentication-Results: trusted; dmarc={result} header.from=bank.example\r\n"
            f"{extra}\r\n").encode()


def test_mail_authentication_requires_first_trusted_result():
    mapping = [{"app": "Bank", "senders": ["billing@bank.example"]}]
    assert match(message(), mapping, "trusted") == [("Bank", "primary", "2026-10")]
    assert not match(message(result="fail", extra="Authentication-Results: trusted; dmarc=pass header.from=bank.example\r\n"), mapping, "trusted")
    assert not match(message(), mapping, "other")
    assert not match(message(sender="phish@evil.example"), mapping, "trusted")
    assert not match(message(extra="From: other@bank.example\r\n"), mapping, "trusted")


def test_mail_uid_restart_dedup_and_read_only(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    store.put("Bank", "primary", enabled=True)
    store.settings({"enabled": True})
    for name in ("user", "password"):
        (tmp_path / name).write_text("synthetic")
    class IMAP:
        uids = b"1"
        fetched = []
        def login(self, *args): pass
        def select(self, folder, readonly):
            assert readonly
            return "OK", []
        def response(self, name): return name, [b"42"]
        def uid(self, command, *args):
            if command == "search": return "OK", [self.uids]
            assert "BODY.PEEK" in args[1]
            self.fetched.append(args[0])
            return "OK", [(b"header", message())]
        def logout(self): pass
    cfg = {"enabled": True, "host": "localhost", "folder": "Billing", "authserv_id": "trusted",
           "username_file": str(tmp_path / "user"), "password_file": str(tmp_path / "password"),
           "mappings": [{"app": "Bank", "senders": ["billing@bank.example"]}]}
    MailTriggers(store, cfg, IMAP).poll()
    assert not IMAP.fetched
    IMAP.uids = b"1 2"
    MailTriggers(store, cfg, IMAP).poll()
    assert IMAP.fetched == ["2"]
    assert store.rows()[0]["requested"] == 2
    MailTriggers(store, cfg, IMAP).poll()
    assert IMAP.fetched == ["2"]
    store.finish("Bank", "primary", "AUTH_REQUIRED")
    store.trigger("Bank", "primary")
    assert store.rows()[0]["state"] == "AUTH_REQUIRED"


def test_notice_dedup_restart_suppression_and_privacy(tmp_path, monkeypatch):
    store = Store(tmp_path / "store.sqlite3")
    posted = []
    class HTTP:
        def __init__(self, *args): pass
        def json(self, path, value): posted.append(value)
    monkeypatch.setattr("interventions.Service", HTTP)
    issues = [("Bank", "CHALLENGE_REQUIRED", "private-account-123456789")]
    notices = Notices(store)
    notices.sync(issues, {"enabled": True})
    Notices(store).sync(issues, {"enabled": True})
    assert len(posted) == 1
    assert "123456789" not in json.dumps(posted)
    notices.sync([], {"enabled": True})
    notices.suppress("Bank", True)
    notices.sync(issues, {"enabled": True})
    assert len(posted) == 1
    notices.suppress("Bank", False)
    notices.sync(issues, {"enabled": True})
    assert len(posted) == 2


def test_transient_delivery_error_has_grace_period(tmp_path, monkeypatch):
    store = Store(tmp_path / "store.sqlite3")
    notices = Notices(store)
    class HTTP:
        def __init__(self, *args): pass
        def json(self, *args): pytest.fail("transient error must not notify")
    monkeypatch.setattr("interventions.Service", HTTP)
    notices.sync([("Bank", "DELIVERY", "id")], {"enabled": True})
    notices.sync([], {"enabled": True})


def test_quarterly_month_boundaries_and_leap_year():
    quarterly = {"start": "2026-03-01", "cycle": "quarterly"}
    assert list(periods(quarterly, date(2026, 10, 18))) == ["2026-03", "2026-06", "2026-09"]
    monthly = {"start": "2024-01-01", "available_day": 31, "grace_days": 0}
    assert list(periods(monthly, date(2024, 2, 28))) == []
    assert list(periods(monthly, date(2024, 2, 29))) == ["2024-01"]


def test_separate_subaccounts_not_satisfied_by_one_statement(tmp_path):
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"synthetic")
    record = {"downloaded_ok": True, "pdf_path": str(pdf), "period": "2026-01", "category": "statement", "account": "internal-one"}
    (tmp_path / "progress.json").write_text(json.dumps({"id": record}))
    rule = {"start": "2026-01-01", "account_key": hashlib.sha256(b"internal-two").hexdigest()}
    assert missing(rule, tmp_path, date(2026, 2, 18)) == ["2026-01"]
    rule["account_key"] = hashlib.sha256(b"internal-one").hexdigest()
    assert not missing(rule, tmp_path, date(2026, 2, 18))


def test_publication_retry_is_durable_bounded_and_auth_safe(tmp_path):
    import time
    from integration_worker import Integrations
    from paperpull_core.outbox import Outbox
    store = Store(tmp_path / "store.sqlite3")
    store.put("Bank", "primary", enabled=True)
    store.settings({"enabled": True})
    store.finish("Bank", "primary", "NO_NEW_DOCUMENTS")
    worker = Integrations(store, Outbox(tmp_path / "delivery.sqlite3"), None)
    today = date.today()
    # Same-month publication makes this fixture independent of calendar date.
    rule = {"start": today.replace(day=1).isoformat(), "available_day": today.day,
            "publication_lag_months": 0, "retry_missing": True}
    for attempt in range(3):
        with store.db() as db:
            db.execute("UPDATE schedules SET attempted=?,requested=0,state='NO_NEW_DOCUMENTS'", (time.time() - 90000,))
            db.execute("UPDATE publication_retries SET last=?", (time.time() - 90000,))
        worker.retry_publication("Bank", "primary", rule, tmp_path)
        assert store.rows()[0]["requested"] == (2 if attempt < 2 else 0)
    with store.db() as db:
        db.execute("DELETE FROM publication_retries")
    store.finish("Bank", "primary", "AUTH_REQUIRED")
    worker.retry_publication("Bank", "primary", rule, tmp_path)
    assert store.rows()[0]["state"] == "AUTH_REQUIRED"
