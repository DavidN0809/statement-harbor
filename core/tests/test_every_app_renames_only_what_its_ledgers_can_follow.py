"""Every app's Rename ends with each file where its ledgers say it is, even
when a ledger cannot be written.

Rename renamed the files and only then wrote the index and the run state.
With the index open in Excel the write gave up after its minute, the files
already renamed, so the index and progress.json named every file by a name
it no longer had. Verify reported each one missing, and the next Rename
said every file was already named the way the app names it. The core's
Rename now shows each ledger can be written before a file moves, and puts
every file back when one still cannot be written (core
test_rename_with_a_ledger_held_open.py).

Each app here is built as it is at home, from its own code, the way
test_every_app_renames_each_file_for_its_own_record.py builds it, with two
documents or two purchases written down by its own code. Then the naming
pattern changes and the app's own Rename runs with --apply through its own
main, as the panel presses it. Once the index is refused where the real
write gives up, after the files moved, and on Windows once it is held open
the way Excel holds it, before anything moves. Each time the app has to
stop with exit code 1, so the panel does not say the files were renamed,
and every file has to keep the name it had, with the index and the run
state, as the app saved it on its way out, naming it.
"""
import os
import sys
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402
from test_rename_with_a_ledger_held_open import held_like_excel  # noqa: E402

APPS, IDS = census.APPS, census.IDS


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return census.Home(request.param, tmp_path, monkeypatch, capsys)


def two_saved(home) -> dict:
    """Two documents or two purchases written down by the app's own code,
    each with a file of its own, and the name each file has, by its bytes."""
    app = home.build()
    if hasattr(home.mod, "Document"):
        for doc in census.two_documents(home, titles=(census.TITLE, census.OTHER_TITLE)):
            census.downloaded(app, doc)
    else:
        for number in ("ORD" + a for a in census.ACCOUNTS):
            census.purchased(home, app, number)
    census.saved(app)
    names = {body: path.name for body, path in home.files().items()}
    assert len(names) == 2, names
    home.set_pattern(census.PATTERN)
    return names


def renamed(home):
    """The app's own Rename with --apply, through its own main, its exit
    code and what it said."""
    home.capsys.readouterr()
    try:
        code = home.mod.main(["--config", str(home.cfg), "--rename", "--apply"])
    except SystemExit as stop:
        code = stop.code
    return code, " ".join(home.capsys.readouterr().out.split())


def where_its_ledgers_say(home, names: dict, said: str) -> None:
    files = home.files()
    assert {body: path.name for body, path in files.items()} == names, (
        "%s left a file renamed\n%s" % (home.app.name, said[-1500:]))
    app = home.build()
    rows = app.index_csv.read_all()
    records = [r for r in app.progress.data.values() if isinstance(r, dict)]
    for path in files.values():
        assert [r for r in rows if Path(r["PDF Full Path"]) == path], (
            "%s's index does not name %s\n%s" % (home.app.name, path.name, said[-1500:]))
        assert [r for r in records if r.get("pdf_path") and Path(r["pdf_path"]) == path], (
            "%s's run state does not name %s\n%s" % (home.app.name, path.name, said[-1500:]))
    assert home.browser.asked == 0, "Rename reached for a browser"


def test_there_are_apps_to_check():
    assert len(APPS) >= 61, IDS


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_an_index_that_will_not_write_puts_every_file_back(home, monkeypatch):
    names = two_saved(home)
    index = Path(home.build().index_csv.path)
    real = core_storage.atomic_write_text
    refused = []

    def write(path, text, encoding="utf-8"):
        if Path(path) == index and not refused:
            refused.append(path)
            raise PermissionError("%s stayed locked. Close the program using it and "
                                  "re-run." % path)
        return real(path, text, encoding)

    monkeypatch.setattr(core_storage, "atomic_write_text", write)
    code, said = renamed(home)
    assert refused, "%s never wrote its index, so nothing moved\n%s" % (
        home.app.name, said[-1500:])
    assert code == 1, said[-1500:]
    assert ("%s could not be written (PermissionError), so every file was put back under "
            "the name it had and nothing was renamed." % index.name) in said, said[-1500:]
    assert "Resume" not in said, "a rename has nothing for Resume to carry on with"
    where_its_ledgers_say(home, names, said)


@pytest.mark.skipif(os.name != "nt", reason="Windows is where an open file cannot be replaced")
@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_an_index_open_in_excel_renames_nothing(home):
    names = two_saved(home)
    index = Path(home.build().index_csv.path)
    with held_like_excel(index):
        code, said = renamed(home)
    assert code == 1, said[-1500:]
    assert "Nothing was renamed, since %s could not be written" % index.name in said, (
        said[-1500:])
    assert "Resume" not in said, "a rename has nothing for Resume to carry on with"
    where_its_ledgers_say(home, names, said)
