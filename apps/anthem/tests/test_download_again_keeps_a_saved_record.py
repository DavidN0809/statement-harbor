"""Anthem's member documents, ID cards and letters keep a saved record
through a Download again that saves nothing.

Anthem saves these in a loop of their own (App._save_collected), apart from
its EOBs, and writes their records there rather than through _record, so
saved_copy.holds never stood in front of them. Download again takes each
again, and a fetch that brought nothing, or a copy that failed its check,
merged Needs Manual Review and the copy put aside into the saved record
while it still said downloaded. Its state then said Manual Review and its
file was the copy put aside, and Rename and the Pilot report read it so.

Here the app is built by its own parser and __init__ with a made-up config,
and only what Anthem hands over for a row is stood in.
"""
import io
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import saved_copy  # noqa: E402
from paperpull_core.models import State  # noqa: E402

ROW = {"label": "Summary of Benefits and Coverage", "key": "member:900000000000001",
       "doc_id": "900000000000001", "date": "2026-06-15", "folder_attr": "other_documents"}


def opening_pdf() -> bytes:
    """A one page PDF of invented words that opens."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 300})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


FAILING = b"%PDF-1.4\n% an invented blank print\n%%EOF\n"


@pytest.fixture
def build(tmp_path, monkeypatch):
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    def made(redownload: bool = False):
        flags = ["--config", str(cfg)] + (["--redownload"] if redownload else [])
        app = app_mod.App(app_mod.build_parser().parse_args(flags))
        app._on_its_site = lambda: None
        return app
    return made


def save(app, handed: bytes) -> dict:
    app._save_collected("member documents", [dict(ROW)], lambda page, row: handed)
    app.progress.save()
    return dict(app.progress.get(ROW["key"]) or {})


def a_plain_run_takes_it_again(build) -> bool:
    fetched = []
    app = build()
    app._save_collected("member documents", [dict(ROW)],
                        lambda page, row: fetched.append(row) or b"")
    return bool(fetched)


def saved_before(build) -> dict:
    rec = save(build(), opening_pdf())
    assert rec["downloaded_ok"] is True and Path(rec["pdf_path"]).is_file()
    return rec


def stands(before: dict, after: dict):
    changed = {f: (before.get(f), after.get(f)) for f in sorted(set(before) | set(after))
               if f not in ("notes", "updated_at") and before.get(f) != after.get(f)}
    assert not changed, "a Download again that saved nothing changed the record %r" % changed
    assert saved_copy.NOTE in after.get("notes", "")


def test_a_download_again_that_fetches_nothing_keeps_the_saved_record(build):
    before = saved_before(build)
    stands(before, save(build(redownload=True), b""))
    assert not a_plain_run_takes_it_again(build)


def test_a_download_again_put_aside_keeps_the_saved_record(build):
    before = saved_before(build)
    after = save(build(redownload=True), FAILING)
    stands(before, after)
    assert Path(after["pdf_path"]).read_bytes() == Path(before["pdf_path"]).read_bytes()
    assert not a_plain_run_takes_it_again(build)


@pytest.mark.parametrize("sized", [True, False],
                         ids=["record with its size", "record saved before sizes were kept"])
def test_a_copy_left_where_the_saved_one_was_is_never_vouched_for(build, monkeypatch, sized):
    """The person deleted the saved file, so the attempt saves under its
    name, and its copy fails its check and cannot be moved to Manual
    Review, a file another program holds open. A record saved before this
    loop kept a file's size is told by the name alone."""
    before = saved_before(build)
    if not sized:
        app = build()
        app.progress.update(ROW["key"], {"pdf_size": ""})
        app.progress.save()
    Path(before["pdf_path"]).unlink()
    moving = Path.replace

    def refused(self, target):
        if "Manual Review" in str(target):
            raise OSError("another program holds the file open")
        return moving(self, target)

    monkeypatch.setattr(Path, "replace", refused)
    after = save(build(redownload=True), FAILING)
    assert Path(after["pdf_path"]).read_bytes() == FAILING, "the attempt left no copy, so this shows nothing"
    assert not after.get("downloaded_ok"), "the record says the attempt's copy is the one saved"
    monkeypatch.setattr(Path, "replace", moving)
    assert a_plain_run_takes_it_again(build)


def test_a_first_fetch_put_aside_is_recorded_as_before(build):
    after = save(build(), FAILING)
    assert after["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert "Manual Review" in after["pdf_path"]
    assert not after.get("downloaded_ok")
