"""An Apple purchase whose receipt Apple refused goes on counting after a
move with --minimal.

Apple counts the separate runs on which it refused a purchase's receipt,
and those on which it did not ask, and saves a record of the purchase in
its place on the third (_apple_refused, _would_make_a_record), saying how
many of them it was not asked on. That is no skip decision, since the
purchase is not done, and tools/migrate.py --minimal carried neither list.
On the new computer Apple counted its refusals from none, and the purchase
took three more refused runs before its record was saved.

These keep such a purchase with the app's own downloader over an output
folder on disk, move the history with the tool and ask the app's own code
on the new computer. Every name and number is invented.
"""
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from paperpull_core.models import State

# The move test beside this file, for its helpers and the census it loads.
_MOVE = Path(__file__).with_name("test_a_receipt_set_aside_stays_set_aside_after_a_move.py")
_spec = importlib.util.spec_from_file_location("set_aside_move", _MOVE)
move = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(move)
census, migrate = move.census, move.migrate

APPLE = census.REPO / "apps" / "apple"
FIRST_RUNS = ["2031-01-02T12:00:00", "2031-01-03T12:00:00"]
REFUSED = {"state": State.FAILED.value, "notes": "Apple refused its receipt",
           "refused_runs": list(FIRST_RUNS), "not_asked_runs": FIRST_RUNS[1:]}


def keep(root: Path, rec: dict):
    """Apple's own downloader writes the purchase's record into an install
    under root. (the module, the purchase)"""
    mod = census.load(APPLE)
    out = move.install(root, APPLE)
    p = census.purchase()
    census.app_in(mod, out).progress.update(p.key, dict(p.to_dict(), **rec))
    return mod, p


def moved(tmp_path: Path, rec: dict, minimal=True, here: dict = None):
    """The record kept on the old computer, moved to a new one, where the
    same purchase has `here` already when given. (the module, the purchase,
    the new install)"""
    mod, p = keep(tmp_path / "old", rec)
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=minimal) == 0
    new = move.install(tmp_path / "new", APPLE, {} if here is None else
                       {p.key: dict(p.to_dict(), **here)})
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    return mod, p, new


def carried(tmp_path: Path, rec: dict) -> dict:
    """The record as a --minimal export writes it."""
    _, p = keep(tmp_path / "old", rec)
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=True) == 0
    with zipfile.ZipFile(archive) as z:
        name = next(n for n in z.namelist() if n.endswith("/progress.json"))
        return json.loads(z.read(name).decode("utf-8"))[p.key]


@pytest.mark.parametrize("minimal", [True, False], ids=["minimal", "whole"])
def test_apple_counts_the_runs_it_was_refused_on_the_old_computer(minimal, tmp_path, capsys):
    mod, p, new = moved(tmp_path, REFUSED, minimal)
    capsys.readouterr()
    app = census.app_in(mod, new)
    assert app._would_make_a_record(p), (
        "Apple refused it on %d runs before the move, and the third would make its "
        "record, %r" % (len(FIRST_RUNS), app.progress.get(p.key)))
    rec = app.progress.get(p.key)
    assert rec["not_asked_runs"] == FIRST_RUNS[1:], "the record says which runs did not ask"


def test_an_apple_purchase_refused_once_still_needs_its_runs(tmp_path, capsys):
    """Not a census of nothing. One refused run and this one make two."""
    mod, p, new = moved(tmp_path, dict(REFUSED, refused_runs=FIRST_RUNS[:1]))
    capsys.readouterr()
    assert not census.app_in(mod, new)._would_make_a_record(p)


def test_an_import_fills_in_the_runs_of_a_purchase_this_install_has_without_them(tmp_path,
                                                                                capsys):
    """This install has the purchase from an older --minimal move, without
    its runs. A newer file fills them in."""
    mod, p, new = moved(tmp_path, REFUSED, here={"state": State.FAILED.value})
    capsys.readouterr()
    rec = census.app_in(mod, new).progress.get(p.key)
    assert (rec["refused_runs"], rec["not_asked_runs"]) == (FIRST_RUNS, FIRST_RUNS[1:]), rec


def test_runs_this_install_counted_stay_its_own_both_lists_together(tmp_path, capsys):
    """A run here was refused, by a version that kept no list of runs it
    did not ask on. The old computer's list of those would count runs
    that are not among this install's refused ones, so neither comes."""
    here = {"state": State.FAILED.value, "refused_runs": ["2031-02-01T09:00:00"]}
    mod, p, new = moved(tmp_path, REFUSED, here=here)
    capsys.readouterr()
    rec = census.app_in(mod, new).progress.get(p.key)
    assert rec["refused_runs"] == ["2031-02-01T09:00:00"], rec
    assert "not_asked_runs" not in rec, rec


def test_a_purchase_saved_here_takes_no_runs_from_the_old_computer(tmp_path, capsys):
    here = {"state": State.PDF_VERIFIED.value, "downloaded_ok": True}
    mod, p, new = moved(tmp_path, REFUSED, here=here)
    capsys.readouterr()
    rec = census.app_in(mod, new).progress.get(p.key)
    assert not {"refused_runs", "not_asked_runs"} & set(rec), rec


def test_a_saved_apple_record_keeps_its_runs_out_of_a_minimal_file(tmp_path):
    saved = dict(REFUSED, state=State.PDF_VERIFIED.value, downloaded_ok=True)
    rec = carried(tmp_path, saved)
    assert not {"refused_runs", "not_asked_runs"} & set(rec), rec
    assert {"refused_runs", "not_asked_runs"} <= set(carried(tmp_path / "again", REFUSED))


def test_only_its_own_provider_carries_them():
    """Another app's record of the same shape carries none of them."""
    for provider in ("", "Kroger", "Robinhood", "Target"):
        cut = migrate._skip_fields(dict(REFUSED), provider)
        assert not {"refused_runs", "not_asked_runs"} & set(cut), (provider, cut)
