import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from paperpull_core.outbox import Outbox


def pdf(path, width=100):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    writer.write(path)
    return path


@pytest.fixture
def setup(tmp_path):
    consume = tmp_path / "consume"
    consume.mkdir()
    return Outbox(tmp_path / "outbox.sqlite3"), consume, pdf(tmp_path / "synthetic-123456789.pdf")


def test_consumed_document_is_never_published_again(setup):
    box, consume, source = setup
    key = box.enqueue(source, consume, "Bank")
    assert box.flush() == {"HANDED_OFF": 1}
    target = next(consume.iterdir())
    assert "123456789" not in target.name
    target.unlink()  # Paperless consumed it.
    assert Outbox(box.path).enqueue(source, consume, "Bank") == key
    assert Outbox(box.path).flush() == {"HANDED_OFF": 1}
    assert not list(consume.iterdir())
    assert source.exists()


def test_two_statements_same_date_preserved(setup):
    box, consume, source = setup
    two = pdf(source.with_name("another.pdf"), width=120)
    assert box.enqueue(source, consume, "Bank") != box.enqueue(two, consume, "Bank")
    assert box.flush() == {"HANDED_OFF": 2}
    assert len(list(consume.glob("*.pdf"))) == 2
    assert not list(consume.glob(".*"))


def test_io_failure_retries_without_provider_or_redownload(setup):
    box, consume, source = setup
    consume.rmdir()
    box.enqueue(source, consume, "Bank")
    assert box.flush() == {"PENDING": 1}
    consume.mkdir()
    assert Outbox(box.path).flush() == {"HANDED_OFF": 1}


@pytest.mark.parametrize("data", [b"<html>login password private</html>", b"%PDF-1.7 incomplete", b""])
def test_corrupt_files_never_reach_consume(setup, data):
    box, consume, source = setup
    source.write_bytes(data)
    box.enqueue(source, consume, "Bank")
    assert box.flush() == {"CORRUPT": 1}
    assert not list(consume.iterdir())
    assert b"password" not in box.path.read_bytes()


def test_changed_pdf_is_rejected(setup):
    box, consume, source = setup
    box.enqueue(source, consume, "Bank")
    pdf(source, width=200)
    assert box.flush() == {"CORRUPT": 1}


def test_ambiguous_crash_never_republishes(setup):
    box, consume, source = setup
    key = box.enqueue(source, consume, "Bank")
    with box.db() as db:
        db.execute("UPDATE documents SET state='PUBLISHING' WHERE id=?", (key,))
    assert Outbox(box.path).flush() == {"UNCERTAIN": 1}
    assert not list(consume.iterdir())


def test_crash_before_publication_resumes_from_hidden_part(setup):
    box, consume, source = setup
    key = box.enqueue(source, consume, "Bank")
    (consume / ("." + key + ".part")).write_bytes(source.read_bytes())
    with box.db() as db:
        db.execute("UPDATE documents SET state='PUBLISHING' WHERE id=?", (key,))
    assert Outbox(box.path).flush() == {"HANDED_OFF": 1}
    assert len(list(consume.iterdir())) == 1


def test_recovery_uses_completed_engine_records_and_root_boundary(setup, tmp_path, monkeypatch):
    box, consume, source = setup
    root = tmp_path / "archive"
    root.mkdir()
    saved = pdf(root / "saved.pdf")
    (root / "progress.json").write_text(json.dumps({
        "one": {"downloaded_ok": True, "pdf_path": str(saved)},
        "two": {"downloaded_ok": True, "pdf_path": str(source)},
        "three": {"downloaded_ok": False, "pdf_path": str(source)}
    }))
    monkeypatch.setenv("PAPERLESS_CONSUME_DIR", str(consume))
    box.reconcile(root, "Bank", "primary", 0)
    assert box.flush() == {"HANDED_OFF": 1}


def test_parallel_flush_does_not_duplicate(setup):
    from concurrent.futures import ThreadPoolExecutor
    box, consume, source = setup
    box.enqueue(source, consume, "Bank")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: Outbox(box.path).flush(), range(4)))
    assert box.counts() == {"HANDED_OFF": 1}
    assert len(list(consume.iterdir())) == 1


def test_engine_key_survives_rename_and_identical_different_documents(setup):
    box, consume, source = setup
    first = box.enqueue(source, consume, "Bank", identity="statement:checking:2026-10:id-1")
    box.flush()
    next(consume.iterdir()).unlink()
    renamed = source.with_name("renamed.pdf")
    source.rename(renamed)
    assert box.enqueue(renamed, consume, "Bank", identity="statement:checking:2026-10:id-1") == first
    box.flush()
    assert not list(consume.iterdir())
    assert box.enqueue(renamed, consume, "Bank", identity="statement:savings:2026-10:id-2") != first
    assert box.flush() == {"HANDED_OFF": 2}
    assert len(list(consume.iterdir())) == 1


@pytest.mark.parametrize("after_rename", [False, True])
def test_process_death_at_publication_boundary_never_duplicates(setup, monkeypatch, after_rename):
    import paperpull_core.outbox as module
    box, consume, source = setup
    box.enqueue(source, consume, "Bank")
    replace = module.os.replace
    def die(part, target):
        if after_rename:
            replace(part, target)
            Path(target).unlink()  # A fast consumer has already taken it.
        raise SystemExit("synthetic crash")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", die)
        with pytest.raises(SystemExit):
            box.flush()
    restarted = Outbox(box.path)
    assert restarted.flush() == ({"UNCERTAIN": 1} if after_rename else {"HANDED_OFF": 1})
    assert len(list(consume.glob("*.pdf"))) == (0 if after_rename else 1)
