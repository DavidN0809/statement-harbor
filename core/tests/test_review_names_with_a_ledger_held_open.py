"""Review Names never ends with a receipt renamed and a ledger naming it by
the name it had.

Review Names renamed a receipt and then wrote its new name into the index,
the order history and progress.json, the way Rename used to. With the index
or the order history open in Excel, the rename was done, the write waited
its minute and gave up, and the index kept the name the file no longer had,
the order history written all the same. Verify then reported the file
missing, and the next run was confused about it. Rename was mended so
(test_rename_with_a_ledger_held_open.py), and Review Names had the same gap.

Now each ledger is shown to be writable before the first question, waiting
the minute a write waits while another program holds it, and nothing is
asked or renamed while one stays held. When a write still fails after a
receipt was renamed, what was written for it is written back, its record
goes back as it was in memory (every app saves progress.json on its way
out), the file goes back under the name it had, never over another file,
and the review says so and stops with exit code 1.

These run each receipt app's own review_names over an output folder on
disk, with the typing stood in for and each receipt written down by the
app's own code. A write is refused where the real one gives up, or on
Windows the file is held open the way Excel holds a workbook it has open.
Every name, number and answer is invented.
"""
import json
import os
import sys
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.models import ONLINE

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_reviews_a_name_once as census  # noqa: E402
from test_rename_with_a_ledger_held_open import held_like_excel  # noqa: E402

APPS = census.APPS
IDS = [a.name for a in APPS]
FIRST = "2026-05-14 Unsure Receipt.pdf"
SECOND = "2026-05-14 Other Receipt.pdf"

on_windows = pytest.mark.skipif(os.name != "nt", reason="Windows is where an open file "
                                "cannot be replaced")


@pytest.fixture(autouse=True)
def default_names():
    """Files named the default way, whatever a test before this one chose."""
    core_storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def body_of(number: str) -> bytes:
    return b"%PDF-1.4\n% the invented receipt of order " + number.encode() + b"\n%%EOF\n"


def two_unsure(app, tmp_path):
    """The app, and two receipts it saved and marked for review for their
    names, each written down by its own code, and the folder they are in."""
    mod = census.load(app)
    inst = census.runnable(mod, tmp_path / "out")
    filed = inst.paths.folder_for(ONLINE)
    filed.mkdir(parents=True, exist_ok=True)
    for number, name in (("ORDER-0001", FIRST), ("ORDER-0002", SECOND)):
        path = filed / name
        path.write_bytes(body_of(number))
        census.as_a_run_left_it(inst, number, path, saved=True, confidence="Low")
    return mod, inst, filed


def ledgers_of(inst, filed) -> dict:
    """Every file in the receipts' folder with its bytes, both CSVs, and
    progress.json as it is on disk, empty when there is none yet."""
    progress = inst.paths.progress_json
    return {"files": {p.name: p.read_bytes() for p in filed.iterdir()},
            "index": inst.index_csv.read_all(),
            "orders": inst.order_csv.read_all(),
            "progress": (json.loads(progress.read_text(encoding="utf-8"))
                         if progress.exists() else {})}


def as_it_was(inst, filed, before: dict) -> None:
    """Each receipt is under the name it had with its own bytes, nothing
    else is in its folder, and both CSVs and progress.json are as they were,
    progress.json on disk and as the app saves it on its way out too."""
    assert ledgers_of(inst, filed) == before
    inst.progress.save()
    assert ledgers_of(inst, filed) == before, "the record in memory still names the new name"


def reviewed(mod, inst, monkeypatch, capsys, answers=("Garden Hose", "Lamp")):
    """The app's own Review Names, the person typing `answers` in turn. What
    it asked, what stopped it (None when it finished), and what it said."""
    capsys.readouterr()
    asked = []

    def answer(prompt):
        asked.append(prompt)
        return answers[len(asked) - 1]

    monkeypatch.setattr(mod, "ask", answer)
    stop = None
    try:
        inst.cmd_review_names()
    except (SystemExit, KeyboardInterrupt) as e:
        stop = e
    return asked, stop, " ".join(capsys.readouterr().out.split())


def exit_code(stop):
    return stop.code if isinstance(stop, SystemExit) else stop


def path_of(inst, which: str) -> Path:
    """The file behind a ledger the review writes."""
    return Path({"index": inst.index_csv.path, "order history": inst.order_csv.path,
                 "progress.json": inst.paths.progress_json}[which])


def file_of(inst, which: str) -> str:
    return path_of(inst, which).name


class Refusals:
    """Writes to refuse, by file name and how many times, after letting
    `skip` of them through, each refused as a write gives up when the file
    stayed held through its minute, unless `error` says otherwise. `first`
    is run just before a write is refused."""

    def __init__(self):
        self.left = {}
        self.skip = {}
        self.error = PermissionError
        self.first = None


@pytest.fixture
def refuse(monkeypatch):
    real = core_storage.atomic_write_text
    refusals = Refusals()

    def write(path, text, encoding="utf-8"):
        name = Path(path).name
        if refusals.skip.get(name):
            refusals.skip[name] -= 1
        elif refusals.left.get(name):
            refusals.left[name] -= 1
            if refusals.first:
                refusals.first()
            raise refusals.error("%s stayed locked. Close the program using it and re-run."
                                 % path)
        return real(path, text, encoding)

    monkeypatch.setattr(core_storage, "atomic_write_text", write)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return refusals


@pytest.fixture
def waits(monkeypatch):
    """Each pause a wait for a held file takes, without the pause."""
    paused = []
    monkeypatch.setattr("time.sleep", lambda s: paused.append(s))
    return paused


def test_there_are_apps_to_check():
    assert len(APPS) >= 14, IDS


# -- a write that fails after the receipt was renamed --------------------------

@pytest.mark.parametrize("app", APPS, ids=IDS)
@pytest.mark.parametrize("which", ["index", "order history", "progress.json"])
def test_a_ledger_that_will_not_write_puts_the_receipt_back(app, which, tmp_path, refuse,
                                                            monkeypatch, capsys):
    """The index, the order history or progress.json is refused after the
    first receipt was renamed. Its file goes back under the name it had, each
    ledger written for it is written back, its record in memory is put back,
    and the review stops with exit code 1 before the second question."""
    mod, inst, filed = two_unsure(app, tmp_path)
    before = ledgers_of(inst, filed)
    held = file_of(inst, which)
    refuse.left[held] = 1
    asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1, said[-1500:]
    as_it_was(inst, filed, before)
    assert len(asked) == 1, "the review went on after a write failed"
    assert ("%s could not be written (PermissionError), so the receipt was put back under "
            "the name it had." % held) in said, said[-1500:]
    assert "Close any program that has %s open and run Review Names again." % held in said
    assert "renamed before it" not in said
    assert "CSV files and progress.json updated." not in said


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_record_made_for_the_receipt_is_taken_away_again(app, tmp_path, refuse,
                                                           monkeypatch, capsys):
    """A receipt with rows and no record yet, as when progress.json was lost.
    The review makes it a record, progress.json is refused, and the record
    has to go again, since the app saves progress.json on its way out and it
    would name a file put back under another name."""
    mod = census.load(app)
    inst = census.app_in(mod, tmp_path / "out")
    filed = inst.paths.folder_for(ONLINE)
    filed.mkdir(parents=True, exist_ok=True)
    (filed / FIRST).write_bytes(body_of("ORDER-0001"))
    inst.index_csv.append_rows([census.index_row("ORDER-0001", filed / FIRST)])
    inst.order_csv.append_rows([census.order_row("ORDER-0001", FIRST)])
    before = ledgers_of(inst, filed)
    assert before["progress"] == {}
    refuse.left["progress.json"] = 1
    asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1, said[-1500:]
    assert inst.progress.data == {}, inst.progress.data
    as_it_was(inst, filed, before)


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_ctrl_c_while_the_index_is_written_puts_the_receipt_back(app, tmp_path, refuse,
                                                                monkeypatch, capsys):
    mod, inst, filed = two_unsure(app, tmp_path)
    before = ledgers_of(inst, filed)
    refuse.left[file_of(inst, "index")], refuse.error = 1, KeyboardInterrupt
    asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert isinstance(stop, KeyboardInterrupt), said[-1500:]
    as_it_was(inst, filed, before)
    assert "Review Names was stopped while it wrote %s" % file_of(inst, "index") in said


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_receipt_renamed_before_keeps_its_new_name(app, tmp_path, refuse, monkeypatch,
                                                      capsys):
    """The first receipt is renamed and written down. The index is refused
    for the second. The first keeps its new name, named so in both CSVs and
    progress.json, and only the second goes back."""
    mod, inst, filed = two_unsure(app, tmp_path)
    index = file_of(inst, "index")
    refuse.skip[index], refuse.left[index] = 1, 1
    asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1, said[-1500:]
    assert len(asked) == 2
    garden = [p for p in filed.iterdir() if "Garden Hose" in p.name]
    assert len(garden) == 1, sorted(p.name for p in filed.iterdir())
    assert sorted(p.name for p in filed.iterdir()) == sorted([garden[0].name, SECOND])
    assert garden[0].read_bytes() == body_of("ORDER-0001")
    assert (filed / SECOND).read_bytes() == body_of("ORDER-0002")
    inst.progress.save()
    records = json.loads(inst.paths.progress_json.read_text(encoding="utf-8"))
    assert {k: Path(v["pdf_path"]).name for k, v in records.items()} == {
        "Online:ORDER-0001": garden[0].name, "Online:ORDER-0002": SECOND}
    for csv in (inst.index_csv, inst.order_csv):
        assert {r["Order or Receipt Number"]: r["PDF Filename"] for r in csv.read_all()} == {
            "ORDER-0001": garden[0].name, "ORDER-0002": SECOND}, csv.path.name
    assert "so the receipt was put back under the name it had" in said, said[-1500:]
    assert "Each receipt renamed before it keeps its new name" in said


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_receipt_whose_name_was_taken_is_never_put_over_another_file(app, tmp_path, refuse,
                                                                      monkeypatch, capsys):
    """Something took the first receipt's old name while the index was waited
    for. The receipt stays under its new name, said with the name it goes
    back to by hand, and the file that took the name is left as it is."""
    mod, inst, filed = two_unsure(app, tmp_path)
    refuse.left[file_of(inst, "index")] = 1
    refuse.first = lambda: (filed / FIRST).write_bytes(b"%PDF- somebody else's")
    asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1, said[-1500:]
    garden = [p for p in filed.iterdir() if "Garden Hose" in p.name]
    assert len(garden) == 1, sorted(p.name for p in filed.iterdir())
    assert sorted(p.name for p in filed.iterdir()) == sorted([FIRST, SECOND, garden[0].name])
    assert (filed / FIRST).read_bytes() == b"%PDF- somebody else's"
    assert garden[0].read_bytes() == body_of("ORDER-0001")
    assert ("and the receipt could not be put back under the name it had, so rename it back "
            "to that by hand. %s back to %s" % (garden[0].name, FIRST)) in said, said[-1500:]


# -- a ledger held open before anything moves ----------------------------------

@on_windows
@pytest.mark.parametrize("app", APPS, ids=IDS)
@pytest.mark.parametrize("which", ["index", "order history", "progress.json"])
def test_a_ledger_open_in_excel_asks_nothing_and_renames_nothing(app, which, tmp_path, waits,
                                                                 monkeypatch, capsys):
    mod, inst, filed = two_unsure(app, tmp_path)
    before = ledgers_of(inst, filed)
    held = file_of(inst, which)
    with held_like_excel(path_of(inst, which)):
        asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1, said[-1500:]
    assert asked == [], "a question was asked while a ledger could not be written"
    as_it_was(inst, filed, before)
    assert len(waits) == 30 and sum(waits) == 60, "it waits the minute a write waits"
    assert said.count("is open in another program") == 1
    assert ("Nothing was renamed, since %s could not be written, and Review Names writes each "
            "new name into it as it renames. Close any program that has it open and run "
            "Review Names again." % held) in said, said[-1500:]


@on_windows
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_two_ledgers_open_in_excel_are_both_named(app, tmp_path, waits, monkeypatch, capsys):
    mod, inst, filed = two_unsure(app, tmp_path)
    before = ledgers_of(inst, filed)
    with held_like_excel(path_of(inst, "index")), held_like_excel(path_of(inst, "order history")):
        asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert exit_code(stop) == 1 and asked == [], said[-1500:]
    as_it_was(inst, filed, before)
    assert ("Nothing was renamed, since %s and %s could not be written, and Review Names "
            "writes each new name into them as it renames. Close any program that has them "
            "open and run Review Names again." % (file_of(inst, "index"),
                                                  file_of(inst, "order history"))) in said


@on_windows
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_an_index_closed_while_the_review_waits_is_reviewed(app, tmp_path, monkeypatch,
                                                            capsys):
    mod, inst, filed = two_unsure(app, tmp_path)
    with held_like_excel(path_of(inst, "index")) as release:
        paused = []

        def pause(seconds):
            paused.append(seconds)
            if len(paused) == 3:
                release()                       # Excel closed in the third pause

        monkeypatch.setattr("time.sleep", pause)
        asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert stop is None and len(asked) == 2, said[-1500:]
    assert said.index("is open in another program") < said.index("need review"), \
        "it waited before the first question"
    names = sorted(p.name for p in filed.iterdir())
    assert len(names) == 2 and all("Garden Hose" in n or "Lamp" in n for n in names), names
    assert sorted(r["PDF Filename"] for r in inst.index_csv.read_all()) == names
    assert "CSV files and progress.json updated." in said


@on_windows
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_nothing_to_review_never_waits_for_a_held_index(app, tmp_path, waits, monkeypatch,
                                                        capsys):
    mod, inst, filed = two_unsure(app, tmp_path)
    finished = [dict(r, **{"Classification Confidence": "High", "Processing Status":
                           "Completed"}) for r in inst.index_csv.read_all()]
    inst.index_csv.rewrite(finished)
    with held_like_excel(path_of(inst, "index")):
        asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    assert stop is None and asked == [] and not waits, said[-1500:]
    assert "No receipts need name review." in said


@on_windows
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_an_index_opened_after_the_check_puts_the_receipt_back(app, tmp_path, waits,
                                                               monkeypatch, capsys):
    """Excel opened the index after the check, while the first receipt was
    renamed. The real write waits its minute for it, gives up, and the
    receipt goes back under the name it had."""
    mod, inst, filed = two_unsure(app, tmp_path)
    before = ledgers_of(inst, filed)
    real_rename = Path.rename
    holding = []

    def rename(self, target):
        moved = real_rename(self, target)
        if self.name == FIRST and not holding:
            holding.append(held_like_excel(path_of(inst, "index")))
            holding[0].__enter__()
        return moved

    monkeypatch.setattr(Path, "rename", rename)
    try:
        asked, stop, said = reviewed(mod, inst, monkeypatch, capsys)
    finally:
        if holding:
            holding[0].__exit__(None, None, None)
    assert holding, "the first receipt was never renamed"
    assert exit_code(stop) == 1, said[-1500:]
    assert len(waits) == 30, "the write waited its minute before it gave up"
    as_it_was(inst, filed, before)
    assert ("%s could not be written (PermissionError), so the receipt was put back under the "
            "name it had." % file_of(inst, "index")) in said, said[-1500:]
