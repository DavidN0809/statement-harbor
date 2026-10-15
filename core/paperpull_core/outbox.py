"""Durable consume-folder handoff, independent from provider downloads.

The consume protocol has no acknowledgement. HANDED_OFF means an atomic file
publication, never confirmed Paperless ingestion. An ambiguous crash is held
for operator reconciliation instead of risking a second ingestion.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Outbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT NOT NULL,
              sha256 TEXT NOT NULL, state TEXT NOT NULL, error TEXT)""")
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

    def enqueue(self, source, consume, provider, account="primary", identity=None):
        source = Path(source).resolve()
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # The engine owns the provider/account/type/period/document identity.
        # Hash that opaque engine key here, retaining distinct same-date PDFs.
        logical = identity or str(source)
        key = hashlib.sha256((provider + "\0" + account + "\0" + logical + "\0" + digest).encode()).hexdigest()
        import re
        name = re.sub(r"[^A-Za-z -]", "", provider)[:60].strip() or "Institution"
        # Never carry account numbers from provider-supplied filenames.
        target = Path(consume).resolve() / (name + " Document " + key + ".pdf")
        with self.db() as db:
            db.execute("""INSERT INTO documents VALUES (?,?,?,?, 'PENDING',NULL)
                          ON CONFLICT(id) DO UPDATE SET source=excluded.source""",
                       (key, str(source), str(target), digest))
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
                    self.enqueue(path, os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless", provider, account,
                                 identity=str(identity) if isinstance(data, dict) else None)
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
            rows = [dict(r) for r in db.execute("SELECT * FROM documents WHERE state IN ('PENDING','PUBLISHING')")]
        for row in rows:
            self._deliver(row["id"])
        return self.counts()

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
                from .receipt_pdf import validate_pdf
                import logging
                # pypdf diagnostics may contain file bytes. Do not emit them.
                before = logging.root.manager.disable
                logging.disable(logging.CRITICAL)
                try:
                    valid = validate_pdf(source, min_bytes=1).ok
                finally:
                    logging.disable(before)
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
