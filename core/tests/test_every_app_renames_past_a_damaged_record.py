"""A record whose path is not text reads as no path, in Rename and Review
Names, in every app.

progress.json is a file a person can open and edit, and a file a crash can
leave damaged. A record whose pdf_path or pdf_filename was a number, a list
or a mapping stopped Rename --apply with an AttributeError in
update_progress, after the files had moved and both CSVs had been written.
progress.json was not saved, so every record went on naming a file that was
gone, and the next run and the next Rename read them so. Review Names
stopped the same way on a purchase whose own record held such a path, with
its receipt already renamed.

Such a value names no file, so it is read as no path at all, as an empty
one is, and the rename finishes with progress.json following it. The value
itself is left as it was, since this program did not write it and cannot
tell what was meant.

Each app runs its own Rename through its own main, and each receipt app its
own Review Names. Every name, number and file is invented.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.models import State


def _harness(file: str, name: str):
    """A sibling test file, for the harness that builds an app as it is at
    home and runs its own Rename or Review Names."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renames = _harness("test_every_app_renames_only_a_file_it_holds.py", "held_rename_harness")
reviews = _harness("test_every_app_reviews_a_name_once.py", "review_names_harness")

# What a hand edit or a damaged file can leave where a path belongs.
DAMAGED = {"a number": 5, "a list": None, "a mapping": None, "true": True,
           "a fraction": 0.5}


def damaged(held: Path) -> dict:
    """Each damaged value, a list and a mapping holding the held file's own
    path, so one read as text would still not name it by chance."""
    values = dict(DAMAGED)
    values["a list"] = [str(held)]
    values["a mapping"] = {"path": str(held)}
    return values


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return renames.Home(request.param, tmp_path, monkeypatch, capsys)


@pytest.mark.parametrize("home", renames.APPS, ids=renames.IDS, indirect=True)
def test_rename_finishes_past_a_record_whose_path_is_not_text(home):
    """--apply renames the file, points the index at it, and saves
    progress.json with the file's own record following it. A record whose
    pdf_path is not text and whose pdf_filename is the file's follows it by
    name, as one with an empty path does, and every value that is not text
    is left as it was. A summary that is not text reads as
    none, and the row's names the file, where it used to leave the file
    with the name it had."""
    app = home.build()
    filed = app.paths.folder_for(next(iter(core_storage.spec().routes), "Statement"))
    held = renames.pdf(filed / "old name.pdf", "held")
    app.index_csv.append_rows([renames.a_row(app.index_csv.columns, 1, held)])
    # The file's own record, whose summary is not text either, so the name
    # is built from the row's.
    records = {"Invented:ORDER-0001": {"order_number": "ORDER-0001", "summary": 5,
                                       "pdf_path": str(held), "pdf_filename": held.name}}
    for i, (what, value) in enumerate(damaged(held).items()):
        records["Invented:path %d" % i] = {"title": what, "pdf_path": value,
                                           "pdf_filename": held.name}
        records["Invented:name %d" % i] = {"title": what, "pdf_path": "",
                                           "pdf_filename": value}
        records["Invented:both %d" % i] = {"title": what, "pdf_path": value,
                                           "pdf_filename": value,
                                           "invoices": [{"file": value}, value]}
    progress = app.paths.progress_json
    written = dict(json.loads(progress.read_text(encoding="utf-8"))
                   if progress.exists() else {}, **records)
    progress.write_text(json.dumps(written), encoding="utf-8")

    said, error = home.rename("--apply")

    assert error is None, "%s's Rename ended with %r\n%s" % (home.app.name, error, said[-1500:])
    now = [p for p in filed.glob("*.pdf")]
    assert len(now) == 1 and "Invented Thing 1" in now[0].name and not held.exists(), (
        "%s did not rename the file\n%s" % (home.app.name, said[-1500:]))
    assert [Path(r["PDF Full Path"]) for r in home.build().index_csv.read_all()] == now
    after = json.loads(progress.read_text(encoding="utf-8"))
    own = after["Invented:ORDER-0001"]
    assert (Path(own["pdf_path"]), own["pdf_filename"]) == (now[0], now[0].name), (
        "%s's progress.json still names the old file\n%s" % (home.app.name, said[-1500:]))
    for key, rec in records.items():
        if key == "Invented:ORDER-0001":
            continue
        # A record whose path is not text follows the file by its name, as
        # one with an empty path does, and keeps the value it had.
        if key.startswith("Invented:path"):
            rec = dict(rec, pdf_filename=now[0].name)
        kept = {k: v for k, v in after[key].items() if k != "updated_at"}
        assert kept == rec, "%s changed a damaged record %s" % (home.app.name, key)


@pytest.mark.parametrize("app", reviews.APPS, ids=[a.name for a in reviews.APPS])
@pytest.mark.parametrize("what", list(DAMAGED))
def test_review_names_finishes_past_its_own_record_whose_path_is_not_text(
        app, what, tmp_path, monkeypatch):
    """A receipt marked for review whose own record's pdf_path and items
    hold something other than text. The new name is given to the file and
    its rows, and its record, which names no file, is left as it was and
    marks nothing Completed, as a record with an empty path is."""
    # Files named the default way, put back after as Home puts them back.
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    core_storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    mod = reviews.load(app)
    inst = reviews.runnable(mod, tmp_path / "out")
    filed = inst.paths.folder_for("Online")
    old = reviews.opening_pdf(filed, "2026-05-14 Older Words.pdf")
    purchase = reviews.as_a_run_left_it(inst, "ORDER-0001", old, saved=True,
                                        confidence="Low")
    value = damaged(old)[what]
    # The items shown beside it, damaged as well, the list holding entries
    # that are not mappings and names that are not text.
    items = value if what != "a list" else ["Invented Item", {"name": 5}, None]
    inst.progress.update(purchase.key, {"pdf_path": value, "items": items})
    monkeypatch.setattr(mod, "ask", lambda prompt: "Garden Hose")

    inst.cmd_review_names()

    now = [p for p in filed.glob("*.pdf")]
    assert len(now) == 1 and "Garden Hose" in now[0].name, app.name
    rows = inst.index_csv.read_all()
    assert [Path(r["PDF Full Path"]) for r in rows] == now
    assert [r["Processing Status"] for r in rows] != ["Completed"], app.name
    record = inst.progress.get(purchase.key)
    assert (record["pdf_path"], record["items"]) == (value, items)
    assert record["state"] != State.COMPLETED.value, app.name
