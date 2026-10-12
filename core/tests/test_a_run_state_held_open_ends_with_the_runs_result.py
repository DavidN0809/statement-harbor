"""A run whose progress.json another program holds ends with its result,
never a traceback.

Every app saves its run state on its way out, in the finally of its main,
and writes the result the panel reads after that. With progress.json held
open, that save waited its minute and raised PermissionError out of the
finally, so the person saw a traceback in place of how the run ended and
the panel got no result. Rename showed it plainest. Its check found
progress.json held, waited its minute, said nothing was renamed and
stopped, and then the save on the way out waited a second minute and
raised over that clean stop.

Now the save on the way out says in one line that the file could not be
written and where, the run ends as it would have, and a file the run has
already waited for is tried once more and not waited for again (core
storage JsonStore.save, and test_run_reporting.py for every app's main).

A document app and a receipt app here are built as they are at home and
given two documents or two purchases by their own code, the way
test_every_app_renames_only_what_its_ledgers_can_follow.py builds them.
Then each one's own Rename runs with --apply through its own main, as the
panel presses it, once with progress.json refused where Windows refuses to
replace a file another program holds, and on Windows once more with it held
open the way Excel holds a workbook it has open.
"""
import json
import os
import sys
from pathlib import Path

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import PREFIX

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402
import test_every_app_renames_only_what_its_ledgers_can_follow as ledgers  # noqa: E402
from test_rename_with_a_ledger_held_open import held_like_excel  # noqa: E402

# One app of each kind, Citi's statements and Target's receipts.
KINDS = [d for d in census.APPS if d.name in ("citi", "target")]
IDS = [d.name for d in KINDS]


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return census.Home(request.param, tmp_path, monkeypatch, capsys)


def test_there_is_an_app_of_each_kind():
    assert IDS == ["citi", "target"]


def renamed(home):
    """The app's own Rename with --apply, through its own main, its exit
    code and everything it printed. PermissionError out of main is the
    traceback the person saw."""
    home.capsys.readouterr()
    try:
        code = home.mod.main(["--config", str(home.cfg), "--rename", "--apply"])
    except SystemExit as stop:
        code = stop.code
    except PermissionError as e:
        pytest.fail("%s ended with a traceback, %r" % (home.app.name, e))
    return code, home.capsys.readouterr().out


def ended_with_its_result(home, names: dict, code, out: str, progress: Path) -> None:
    """Rename stopped and said why, before it changed a record, so the save
    on the way out had nothing to write and neither waited nor said a word
    more, the result was written and says the run stopped, and every file
    keeps the name its ledgers give it."""
    said = " ".join(out.split())
    assert code == 1, said[-1500:]
    assert "Nothing was renamed, since progress.json could not be written" in said, (
        said[-1500:])
    assert ("  ! %s could not be written, so it keeps what was last saved in it. Close any "
            "program that has it open before the next run." % progress) not in out.splitlines(), (
        said[-1500:])
    results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
               if line.startswith(PREFIX)]
    assert len(results) == 1 and results[0]["stopped"] == 1, said[-1500:]
    assert "This run stopped before it finished." in said, said[-1500:]
    assert "Resume" not in said, "a rename has nothing for Resume to carry on with"
    ledgers.where_its_ledgers_say(home, names, said)


@pytest.mark.parametrize("home", KINDS, ids=IDS, indirect=True)
def test_a_run_state_that_will_not_write_ends_with_the_result(home):
    names = ledgers.two_saved(home)
    progress = Path(home.build().progress.path)
    real = os.replace
    tries = []

    def replace(src, dst, *args, **kwargs):
        if Path(dst) == progress:
            tries.append(dst)
            raise PermissionError(13, "The process cannot access the file because it is "
                                  "being used by another process", str(dst))
        return real(src, dst, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "replace", replace)
        code, out = renamed(home)
    ended_with_its_result(home, names, code, out, progress)
    assert len(tries) == core_storage._LOCKED_TRIES + 1, (
        "%s waited for progress.json again on its way out, %d tries"
        % (home.app.name, len(tries)))


@pytest.mark.skipif(os.name != "nt", reason="Windows is where an open file cannot be replaced")
@pytest.mark.parametrize("home", KINDS, ids=IDS, indirect=True)
def test_a_run_state_open_in_excel_ends_with_the_result(home, monkeypatch):
    names = ledgers.two_saved(home)
    progress = Path(home.build().progress.path)
    pauses = []
    monkeypatch.setattr("time.sleep", lambda seconds: pauses.append(seconds))
    with held_like_excel(progress):
        code, out = renamed(home)
    ended_with_its_result(home, names, code, out, progress)
    waits = [s for s in pauses if s == core_storage._LOCKED_PAUSE_S]
    assert len(waits) == core_storage._LOCKED_TRIES, (
        "%s waited for progress.json again on its way out, %d pauses"
        % (home.app.name, len(waits)))
