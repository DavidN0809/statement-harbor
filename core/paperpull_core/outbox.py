"""Durable consume-folder handoff, independent from provider downloads.

The consume protocol has no acknowledgement. HANDED_OFF means an atomic file
publication, never confirmed Paperless ingestion. An ambiguous crash is held
for operator reconciliation instead of risking a second ingestion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError

_PDF_LOG_LOCK = threading.RLock()


class Outbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT NOT NULL,
              sha256 TEXT NOT NULL, state TEXT NOT NULL, error TEXT)""")
            columns = {r[1] for r in db.execute("PRAGMA table_info(documents)")}
            for name, definition in {"transport": "TEXT NOT NULL DEFAULT 'consume'", "task": "TEXT",
                                     "provider": "TEXT NOT NULL DEFAULT 'Institution'",
                                     "account": "TEXT NOT NULL DEFAULT 'primary'",
                                     "metadata": "TEXT NOT NULL DEFAULT '{}'"}.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, source, consume, provider, account="primary", identity=None, metadata=None):
        source = Path(source).resolve()
        if source.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("PDF exceeds delivery size limit")
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # The engine owns the provider/account/type/period/document identity.
        # Hash that opaque engine key here, retaining distinct same-date PDFs.
        logical = identity or str(source)
        key = hashlib.sha256((provider + "\0" + account + "\0" + logical + "\0" + digest).encode()).hexdigest()
        name = re.sub(r"[^A-Za-z -]", "", provider)[:60].strip() or "Institution"
        from .services import configuration
        config = configuration().get("paperless", {})
        mode = config.get("mode", "consume")
        if mode not in {"consume", "api"}:
            raise ValueError("invalid delivery mode")
        metadata = dict(metadata or {})
        metadata["account_category"] = config.get("account_categories", {}).get(provider + "/" + account, metadata.get("account_category", "Financial"))
        metadata = safe_metadata(metadata)
        # Never carry account numbers from provider-supplied filenames.
        title = " ".join(filter(None, [metadata["period"], name, metadata["category"], metadata["kind"]]))
        target = Path(consume).resolve() / (title + " " + key + ".pdf")
        with self.db() as db:
            db.execute("""INSERT INTO documents(id,source,destination,sha256,state,error,transport,provider,account,metadata)
                          VALUES (?,?,?,?, 'PENDING',NULL,?,?,?,?)
                          ON CONFLICT(id) DO UPDATE SET source=excluded.source""",
                       (key, str(source), str(target), digest, mode, name, account, json.dumps(metadata)))
        return key

    def counts(self):
        with self.db() as db:
            return {r[0]: r[1] for r in db.execute("SELECT state,count(*) FROM documents GROUP BY state")}

    def reconcile(self, root, provider, account, since):
        """Only the existing engine's successful progress records, under root."""
        import json
        root = Path(root).resolve()
        try:
            data = json.loads((root / "progress.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        records = data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else []
        for identity, record in records:
            if not isinstance(record, dict) or not record.get("downloaded_ok"):
                continue
            raw = record.get("pdf_path")
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw)
            path = (path if path.is_absolute() else root / path).resolve()
            try:
                if (root in path.parents and path.suffix.lower() == ".pdf"
                        and path.stat().st_mtime >= since):
                    consume = Path(os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless")
                    if os.environ.get("PAPERLESS_SUBFOLDERS") == "1":
                        consume /= re.sub(r"[^A-Za-z0-9 &'._-]", "", provider).strip(" .") or "PaperPull"
                    self.enqueue(path, consume, provider, account,
                                 identity=str(identity) if isinstance(data, dict) else None, metadata=record)
            except OSError:
                continue

    @staticmethod
    def identities(root):
        """Engine keys are hashed by enqueue, never printed or used as names."""
        import json
        root = Path(root).resolve()
        try:
            data = json.loads((root / "progress.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for key, record in data.items():
            if isinstance(record, dict) and record.get("downloaded_ok") and record.get("pdf_path"):
                path = Path(record["pdf_path"])
                path = (path if path.is_absolute() else root / path).resolve()
                if root in path.parents:
                    out[str(path)] = str(key)
        return out

    def flush(self):
        # Transaction serializes writers, including manual retries and plug-ins.
        # The pre-publication PUBLISHING commit makes a crash detectable.
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM documents WHERE state IN ('PENDING','PUBLISHING','SUBMITTING','PROCESSING')")]
        for row in rows:
            if row["transport"] == "api":
                self._api_deliver(row["id"])
            else:
                self._deliver(row["id"])
        return self.counts()

    def retry(self, key):
        # Only definitively failed API tasks may be retried. Ambiguous submissions
        # are reconciled with Paperless and never blindly resubmitted.
        with self.db() as db:
            db.execute("UPDATE documents SET state='PENDING',task=NULL,error=NULL WHERE id=? AND state='API_FAILED'", (key,))

    def overview(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT id,provider,account,state,error,transport FROM documents ORDER BY rowid DESC LIMIT 200")]

    def _api_deliver(self, key):
        from .paperless_api import Paperless
        from .services import configuration
        from .process_lock import ProcessLock
        try:
            lock = ProcessLock(self.path.with_name(self.path.name + ".api.lock"))
        except RuntimeError:
            return
        try:
            with lock:
                self._api_work(key, Paperless, configuration)
        except HTTPError as error:
            with self.db() as db:
                # An explicit client rejection is safe to retry manually after
                # repair; timeouts and server errors remain ambiguous.
                rejected = error.code in {400, 401, 403, 404, 413, 415, 422, 429}
                db.execute("UPDATE documents SET state=CASE WHEN state='SUBMITTING' AND ? THEN 'API_FAILED' ELSE state END,error='SERVICE_REJECTED' WHERE id=?", (rejected, key))
        except Exception:
            # Never retain remote response text, URLs or credentials.
            with self.db() as db:
                db.execute("UPDATE documents SET error='SERVICE_UNAVAILABLE' WHERE id=? AND state NOT IN ('DELIVERED','CORRUPT')", (key,))

    def _api_work(self, key, factory, configuration):
        # The OS lock serializes HTTP work across processes; SQLite transactions
        # remain short, so slow services cannot block the provider scheduler.
        with self.db() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (key,)).fetchone()
        if row["state"] not in {"PENDING", "SUBMITTING", "PROCESSING"}:
            return
        config = configuration().get("paperless", {})
        if config.get("mode") != "api":
            return
        api = factory(config)
        data = Path(row["source"]).read_bytes()
        if not valid_pdf(Path(row["source"])) or hashlib.sha256(data).hexdigest() != row["sha256"]:
            self._api_state(key, "CORRUPT", "INVALID_PDF")
            return
        found = api.existing(data, row["sha256"])
        if found:
            self._api_state(key, "DELIVERED")
            return
        if row["state"] == "PROCESSING":
            status = api.task(row["task"])
            if status in {"FAILURE", "REVOKED"}:
                self._api_state(key, "API_FAILED", "PROCESSING_FAILED")
            elif status in {"SUCCESS", "UNKNOWN"}:
                self._api_state(key, "PROCESSING", "VERIFY_ORIGINAL" if status == "SUCCESS" else "TASK_UNKNOWN")
            return
        if row["state"] == "SUBMITTING":
            self._api_state(key, "SUBMITTING", "RECONCILE")
            return
        meta = json.loads(row["metadata"])
        fields = api.metadata(row["provider"], meta["category"], meta["kind"])
        fields["title"] = " ".join(filter(None, [meta.get("period"), row["provider"], meta["category"], meta["kind"]]))
        if meta.get("date"):
            fields["created"] = meta["date"]
        # This commit must precede POST. Ambiguous submission never resends.
        self._api_state(key, "SUBMITTING")
        task = api.submit(data, key + ".pdf", fields)
        with self.db() as db:
            db.execute("UPDATE documents SET state='PROCESSING',task=?,error=NULL WHERE id=?", (task, key))

    def _api_state(self, key, state, error=None):
        with self.db() as db:
            db.execute("UPDATE documents SET state=?,error=? WHERE id=?", (state, error, key))

    def _deliver(self, key):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM documents WHERE id=?", (key,)).fetchone()
            if row["state"] not in {"PENDING", "PUBLISHING"}:
                return
            target, source = Path(row["destination"]), Path(row["source"])
            part = target.with_name("." + key + ".part")
            if row["state"] == "PUBLISHING":
                # A ready part proves publication never happened. Its absence
                # cannot distinguish a consumed file from a failed rename.
                if not part.exists():
                    db.execute("UPDATE documents SET state='UNCERTAIN',error='RECONCILE' WHERE id=?", (key,))
                    return
            try:
                # Reuse upstream validation and never retain its free-text reason.
                valid = valid_pdf(source)
                if not valid:
                    db.execute("UPDATE documents SET state='CORRUPT',error='INVALID_PDF' WHERE id=?", (key,))
                    return
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    db.execute("UPDATE documents SET state='CORRUPT',error='HASH_CHANGED' WHERE id=?", (key,))
                    return
                if not target.parent.is_dir():
                    consume = Path(os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless").resolve()
                    if target.parent.parent == consume and consume.is_dir():
                        target.parent.mkdir(exist_ok=True)
                    else:
                        raise OSError("consume folder unavailable")
                if target.exists():
                    # Could be ours after a crash, or an operator's file. Never overwrite.
                    same = hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"]
                    db.execute("UPDATE documents SET state=?,error=? WHERE id=?",
                               ("HANDED_OFF" if same else "UNCERTAIN", None if same else "COLLISION", key))
                    return
                with open(part, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                db.execute("UPDATE documents SET state='PUBLISHING',error=NULL WHERE id=?", (key,))
            except OSError:
                db.execute("UPDATE documents SET state='PENDING',error='IO_ERROR' WHERE id=?", (key,))
                return

        # Keep the second transaction locked across rename and acknowledgement.
        # On process death the committed PUBLISHING row remains.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state FROM documents WHERE id=?", (key,)).fetchone()[0]
            if current != "PUBLISHING":
                return
            try:
                if not target.exists():
                    os.replace(part, target)
                else:
                    db.execute("UPDATE documents SET state='UNCERTAIN',error='COLLISION' WHERE id=?", (key,))
                    return
                if os.name != "nt":
                    fd = os.open(target.parent, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                db.execute("UPDATE documents SET state='HANDED_OFF',error=NULL WHERE id=?", (key,))
            except OSError:
                # Leave PUBLISHING. Recovery decides using the part file.
                return


def valid_pdf(source):
    from .receipt_pdf import validate_pdf
    import logging
    with _PDF_LOG_LOCK:
        before = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            return source.stat().st_size <= 64 * 1024 * 1024 and validate_pdf(source, min_bytes=1).ok
        finally:
            logging.disable(before)


def safe_metadata(record):
    """Never copy provider titles, account numbers, names or notices into metadata."""
    from datetime import date
    category = str(record.get("account_category", "Financial"))
    category = category if category in {"Checking", "Savings", "Credit Card", "Loan", "Mortgage", "Utility", "Investment"} else "Financial"
    kind = str(record.get("category", "Document")).casefold()
    kind = {"statement": "Statement", "tax": "Tax Form", "tax document": "Tax Form", "notice": "Notice", "bill": "Bill", "receipt": "Receipt"}.get(kind, "Document")
    raw = str(record.get("date", ""))
    try:
        raw = date.fromisoformat(raw).isoformat()
    except ValueError:
        raw = ""
    return {"category": category, "kind": kind, "date": raw, "period": raw[:7]}
