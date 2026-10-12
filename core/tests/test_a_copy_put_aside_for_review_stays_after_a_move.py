"""A copy put aside for review here stays put aside after a move.

A receipt page that showed another purchase is saved as a copy in Manual
Review, and the record says Needs Manual Review. Every app holds that done
while the copy is still on disk, and deleting the copy is how a person asks
for the receipt again (#42). tools/migrate.py let an incoming record's final
state replace any state it does not call final, this one too. So when the
old computer had set the same purchase aside (its page showed nothing on
three days), the import turned the record into No Receipt Available, the
skip line said the receipt "did not show on 3 separate days" for a purchase
with a copy on disk, and deleting the copy no longer asked for it again.

These put the copy aside with each receipt app's own _finish_pdf, set the
purchase aside on the old computer with the core's tried_again, move the
history with the tool and ask the app's own _already_done and the core's
skip line on the new computer. Every name and number is invented.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from paperpull_core import not_shown, testkit
from paperpull_core.models import State

# The move test beside this file, for its helpers and the census it loads.
_MOVE = Path(__file__).with_name("test_a_receipt_set_aside_stays_set_aside_after_a_move.py")
_spec = importlib.util.spec_from_file_location("set_aside_move", _MOVE)
move = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(move)
census, migrate = move.census, move.migrate


def put_aside_for_review(mod, out: Path):
    """A run here whose receipt page showed another purchase, so the copy
    went to Manual Review. The app holds the purchase done."""
    p = census.purchase()
    filed = testkit.file_a_receipt(census.app_in(mod, out), p, census.ANOTHER_PAGE)
    assert not filed.kept and filed.path.exists(), filed
    assert filed.record["state"] == State.NEEDS_MANUAL_REVIEW.value, filed.record
    assert census.app_in(mod, out)._already_done(p), "a copy in review is done before the move"
    return filed.path


def moved_here(app, minimal, tmp_path):
    """The old computer set the purchase aside, this one put a copy aside
    for review, and the history comes across."""
    mod = census.load(app)
    p = move.set_aside(mod, move.install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=minimal) == 0
    new = move.install(tmp_path / "new", app)
    copy = put_aside_for_review(mod, new)
    return mod, new, p, archive, copy


@pytest.mark.parametrize("minimal", [True, False], ids=["minimal", "whole"])
@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_a_copy_in_review_keeps_its_record_when_the_old_computer_set_it_aside(
        app, minimal, tmp_path, capsys):
    mod, new, p, archive, copy = moved_here(app, minimal, tmp_path)
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    capsys.readouterr()

    done, said, rec = move.asked_after_the_move(mod, new, p)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value, (
        "%s's copy in review became %r" % (app.name, rec["state"]))
    assert Path(rec["pdf_path"]) == copy, rec
    assert not rec.get(not_shown.DAYS_KEY), "the old computer's days came without its state"
    assert done, rec
    assert move.SAID not in said, (app.name, said)

    copy.unlink()
    assert not census.app_in(mod, new)._already_done(p), (
        "%s no longer asks again for a receipt whose copy in review was deleted" % app.name)


# Where each person's app writes, as their config names it. The first
# person writes into the install, as config.example.json says, a second
# person added by tools/add_account.py beside it, and one a person chose
# inside it, whose folder is not the one their paths are relative to.
FOLDERS = {"primary": ".", "beside": "../{app} - sam", "inside": "Receipts of sam"}


def set_up(root: Path, app: Path, where: str) -> tuple:
    """An install as the control panel makes one, and the person's folder.
    The app runs in the install, so the paths it records are relative to it.
    (the install, the folder the person's app writes into, as it names it)"""
    home = move.install(root, app)
    (home / census.entry_of(app).name).write_text("", encoding="utf-8")
    (home / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    folder = Path(FOLDERS[where].format(app=app.name))
    if where != "primary":
        (home / "config.sam.json").write_text(json.dumps({"output_dir": str(folder)}),
                                              encoding="utf-8")
    return home, folder


@pytest.mark.parametrize("where", sorted(FOLDERS))
@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_a_copy_in_review_under_a_relative_folder_keeps_its_record(app, where, tmp_path,
                                                                    monkeypatch, capsys):
    """The tool runs from wherever the control panel or a shell started it,
    and reads a relative path against the install, as the app does."""
    mod = census.load(app)
    old, folder = set_up(tmp_path / "old", app, where)
    monkeypatch.chdir(old)
    p = move.set_aside(mod, folder)
    new, _ = set_up(tmp_path / "new", app, where)
    monkeypatch.chdir(new)
    copy = put_aside_for_review(mod, folder)
    assert not copy.is_absolute(), copy

    monkeypatch.chdir(tmp_path)
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=True) == 0
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    capsys.readouterr()

    monkeypatch.chdir(new)
    done, said, rec = move.asked_after_the_move(mod, folder, p)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value, (
        "%s's copy in review became %r" % (app.name, rec["state"]))
    assert done and move.SAID not in said, (app.name, said, rec)
    copy.unlink()
    assert not census.app_in(mod, folder)._already_done(p), app.name


@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_a_review_record_whose_copy_is_gone_takes_what_the_old_computer_settled(
        app, tmp_path, capsys):
    """Deleting the copy asked for the receipt again, so this install had
    not finished it, and the old computer had. The import finishes it."""
    mod, new, p, archive, copy = moved_here(app, True, tmp_path)
    copy.unlink()
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    capsys.readouterr()

    done, said, rec = move.asked_after_the_move(mod, new, p)
    assert rec["state"] == State.NO_RECEIPT_AVAILABLE.value, rec
    assert done, rec
    assert move.SAID in said, (app.name, said)


def test_the_plan_does_not_count_a_copy_in_review_as_marked_done(tmp_path, capsys):
    app = next(a for a in census.APPS if a.name == "kroger")
    _, _, _, archive, _ = moved_here(app, True, tmp_path)
    assert migrate.do_import(archive, tmp_path / "new", dry_run=True) == 0
    plan = capsys.readouterr().out
    assert "0 marked done" in plan, plan


@pytest.mark.parametrize("incoming", [
    {"state": State.COMPLETED.value},
    {"state": State.PDF_VERIFIED.value},
    {"state": State.CANCELED.value},
    {"state": State.NO_RECEIPT_AVAILABLE.value,
     not_shown.DAYS_KEY: ["2031-01-01", "2031-01-02", "2031-01-03"]},
], ids=["completed", "verified", "canceled", "set aside"])
def test_any_final_state_leaves_a_document_in_review_alone(incoming, tmp_path):
    """The same for a document app's record, which holds a copy in review
    done the same way. A document saved on the old computer still comes
    across as saved."""
    copy = tmp_path / "Manual Review" / "statement.pdf"
    copy.parent.mkdir()
    copy.write_bytes(b"%PDF-1.4 an invented statement")
    review = {"state": State.NEEDS_MANUAL_REVIEW.value, "pdf_path": str(copy)}
    for saved in (False, True):
        target = {"k": dict(review)}
        migrate._merge(target, {"k": dict(incoming, downloaded_ok=saved)}, [], tmp_path)
        assert target["k"]["state"] == State.NEEDS_MANUAL_REVIEW.value, target
        assert target["k"]["pdf_path"] == str(copy), target
        assert not target["k"].get(not_shown.DAYS_KEY), target
        assert bool(target["k"].get("downloaded_ok")) is saved, target


@pytest.mark.parametrize("state", [State.PDF_SAVED.value, State.FAILED.value])
def test_only_a_copy_in_review_keeps_its_record(state, tmp_path):
    """A record in another unfinished state with a file where it says, as
    Target's leaves when a run walked only some of an order's invoices, is
    not done here, and still takes what the old computer finished."""
    pdf = tmp_path / "Receipts" / "receipt.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 an invented receipt")
    target = {"k": {"state": state, "pdf_path": str(pdf)}}
    migrate._merge(target, {"k": {"state": State.COMPLETED.value}}, [], tmp_path)
    assert target["k"]["state"] == State.COMPLETED.value, target
