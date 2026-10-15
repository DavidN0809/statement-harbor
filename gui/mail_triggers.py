"""Optional Proton Bridge IMAP trigger. No mail URL is ever opened."""
from __future__ import annotations

import email
import hashlib
import imaplib
import re
import ssl
from email import policy
from email.utils import getaddresses

from paperpull_core.services import secret


def match(headers, mappings, authserv_id):
    message = email.message_from_bytes(headers, policy=policy.default)
    if message.defects or len(message.get_all("From", [])) != 1:
        return []
    senders = getaddresses(message.get_all("From", []))
    if len(senders) != 1:
        return []
    sender = senders[0][1].lower()
    # Only the first Authentication-Results field is trusted, and only when
    # the operator has verified Bridge/Proton prepends this authserv identity.
    # A later attacker-injected header must not override a failing first one.
    results = message.get_all("Authentication-Results", [])
    if not results or results[0].split(";", 1)[0].strip() != authserv_id:
        return []
    auth = results[0]
    domain = sender.rpartition("@")[2]
    if not re.search(r";\s*dmarc=pass\b[^;]*\bheader\.from=" + re.escape(domain) + r"(?=[;\s]|$)", auth, re.I):
        return []
    subject = str(message.get("Subject", ""))[:500]
    # Period is an optional hint only. It cannot change download URLs or scope.
    period = re.search(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", subject)
    return [(row["app"], row.get("account", "primary"), period[0] if period else None)
            for row in mappings if sender in {x.lower() for x in row["senders"]}
            and re.search(r"\b(statement|bill|tax document|1098|1099)\b", subject, re.I)]


class MailTriggers:
    def __init__(self, store, config, factory=None):
        self.store, self.config, self.factory = store, config, factory
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS mail_cursor (mailbox TEXT PRIMARY KEY, validity TEXT, uid INTEGER)")
        self.status = "DISABLED"
        self.auth_failed = False

    def poll(self):
        cfg = self.config
        if not cfg.get("enabled"):
            self.status = "DISABLED"
            return
        if self.auth_failed:
            return
        client = None
        try:
            if any(c in cfg["folder"] for c in "\r\n\0") or len(cfg["folder"]) > 256:
                raise ValueError("invalid billing folder")
            # No implicit plaintext even on loopback; trust Bridge's exported
            # certificate through cafile. Dedicated Bridge credentials only.
            context = ssl.create_default_context(cafile=cfg.get("ca_file"))
            if self.factory:
                client = self.factory()
            else:
                client = imaplib.IMAP4(cfg["host"], int(cfg.get("port", 1143)), timeout=20)
                client.starttls(ssl_context=context)
            try:
                client.login(secret(cfg["username_file"]), secret(cfg["password_file"]))
            except imaplib.IMAP4.error:
                self.auth_failed = True
                self.status = "AUTH_REQUIRED"
                return
            if client.select('"' + cfg["folder"].replace('"', '').replace('\\', '') + '"', readonly=True)[0] != "OK":
                raise ValueError("folder unavailable")
            validity = client.response("UIDVALIDITY")[1][0].decode("ascii")
            mailbox = hashlib.sha256((cfg["host"] + "\0" + cfg["folder"]).encode()).hexdigest()
            result, data = client.uid("search", None, "ALL")
            if result != "OK":
                raise ValueError("search unavailable")
            uids = [int(x) for x in data[0].split()]
            with self.store.db() as db:
                row = db.execute("SELECT validity,uid FROM mail_cursor WHERE mailbox=?", (mailbox,)).fetchone()
                # Initial connection and UIDVALIDITY changes establish a baseline.
                # Historical messages must not trigger a burst of bank visits.
                if row is None or row[0] != validity:
                    db.execute("INSERT OR REPLACE INTO mail_cursor VALUES (?,?,?)", (mailbox, validity, max(uids, default=0)))
                    self.status = "READY"
                    return
                cursor = row[1]
            for uid in [x for x in sorted(uids) if x > cursor][:10]:
                result, data = client.uid("fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT AUTHENTICATION-RESULTS)])")
                if result != "OK":
                    raise ValueError("fetch unavailable")
                header = next((part[1] for part in data if isinstance(part, tuple)), b"")
                if len(header) <= 32768:
                    for app, account, _period in match(header, cfg.get("mappings", []), cfg["authserv_id"]):
                        self.store.trigger(app, account)
                with self.store.db() as db:
                    db.execute("UPDATE mail_cursor SET uid=? WHERE mailbox=?", (uid, mailbox))
            self.status = "READY"
        except Exception:
            self.status = "UNAVAILABLE"
        finally:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass
