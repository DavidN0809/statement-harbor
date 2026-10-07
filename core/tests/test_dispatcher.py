"""paperpull.py, one command for every app.

Each app is one script and one flag. The dispatcher's whole job is to find
the right folder, the right interpreter and the right flag, and get out of
the way. These pin each of those, and that the panel and the terminal offer
the same commands, since the point of #23 was to stop having two answers.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import paperpull  # noqa: E402


def _app(root: Path, slug: str, provider: str, folder: str | None = None,
         login_flag: str = "--open-browser", venv: bool = False) -> Path:
    d = root / (folder or slug)
    d.mkdir(parents=True)
    (d / ("%s_docs.py" % slug)).write_text(
        'ap.add_argument("%s")\n' % login_flag, encoding="utf-8")
    (d / "storage.py").write_text('SPEC = AppSpec(\n    provider="%s",\n)\n' % provider,
                                  encoding="utf-8")
    if venv:
        py = d / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"")
        (d / ".venv" / "bin").mkdir()
        (d / ".venv" / "bin" / "python").write_bytes(b"")
    return d


@pytest.fixture
def root(tmp_path, monkeypatch):
    # Where the checkout's shared environment would be, made only by a test
    # that wants one, so the gui/.venv of the checkout running these tests,
    # or its absence on CI, never decides what they see.
    monkeypatch.setattr(paperpull, "SHARED_VENV", tmp_path / "gui" / ".venv")
    _app(tmp_path, "pge", "PG&E", folder="PG&E Statements", venv=True)
    _app(tmp_path, "chase", "Chase")
    _app(tmp_path, "target", "Target", login_flag="--login")
    (tmp_path / "Removed").mkdir()
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    return tmp_path


# -- which app -----------------------------------------------------------------

def test_only_folders_with_an_entry_script_count(root):
    assert [d.name for d in paperpull.list_apps(root)] == \
        ["chase", "PG&E Statements", "target"]


def test_an_app_is_found_by_folder_slug_or_provider_in_any_case(root):
    for wanted in ("PG&E Statements", "pg&e statements", "pge", "PGE", "PG&E"):
        assert paperpull.find_app(root, wanted).name == "PG&E Statements", wanted
    assert paperpull.find_app(root, "Chase").name == "chase"


def test_an_unknown_app_says_so_and_points_at_list(root):
    with pytest.raises(SystemExit, match="No app called 'wells'.*list"):
        paperpull.find_app(root, "wells")


def test_an_ambiguous_name_lists_the_candidates_rather_than_guessing(root):
    _app(root, "chasebank", "Chase Bank")
    with pytest.raises(SystemExit, match="more than one app: chase, chasebank"):
        paperpull.find_app(root, "chas")


def test_an_empty_root_is_reported_not_searched(tmp_path):
    with pytest.raises(SystemExit, match="No apps under"):
        paperpull.find_app(tmp_path, "pge")


# -- how it runs ---------------------------------------------------------------

def test_the_apps_own_venv_is_preferred_and_this_python_is_the_fallback(root):
    assert paperpull.interpreter(root / "PG&E Statements").name == "python.exe"
    assert paperpull.interpreter(root / "chase") == Path(sys.executable)


def test_each_command_becomes_its_flag_and_extras_pass_through(root):
    argv = paperpull.build_argv(root / "chase", "all", None, ["--year", "2025", "--yes"])
    assert argv[1:] == ["chase_docs.py", "--all", "--year", "2025", "--yes"]
    assert paperpull.build_argv(root / "chase", "dry-run", None, [])[2:] == ["--dry-run"]


def test_login_opens_a_browser_for_cdp_apps_and_checks_for_the_other(root):
    assert paperpull.build_argv(root / "chase", "login", None, [])[2:] == ["--open-browser"]
    assert paperpull.build_argv(root / "target", "login", None, [])[2:] == ["--login"]


def test_a_second_account_maps_to_its_config_file(root):
    (root / "chase" / "config.spouse.json").write_text("{}", encoding="utf-8")
    argv = paperpull.build_argv(root / "chase", "pilot", "spouse", [])
    assert argv[2:] == ["--pilot", "--config", "config.spouse.json"]
    assert paperpull.build_argv(root / "chase", "pilot", "primary", [])[2:] == ["--pilot"]


def test_a_missing_account_is_refused_before_anything_runs(root):
    with pytest.raises(SystemExit, match="No config.spouse.json in chase"):
        paperpull.build_argv(root / "chase", "pilot", "spouse", [])


def test_main_runs_in_the_apps_folder_and_returns_its_exit_code(root, monkeypatch):
    seen = {}

    def fake_run(app_dir, argv):
        seen["cwd"], seen["argv"] = app_dir, argv
        return 7

    monkeypatch.setattr(paperpull, "run", fake_run)
    monkeypatch.setattr(paperpull, "runs_apps", lambda python: True)
    rc = paperpull.main(["--root", str(root), "chase", "resume", "--max-docs", "3"])
    assert rc == 7
    assert seen["cwd"] == root / "chase"
    assert seen["argv"][1:] == ["chase_docs.py", "--resume", "--max-docs", "3"]


def test_an_app_writes_utf8_wherever_its_output_goes(root, tmp_path, monkeypatch):
    """Output headed for a file was written in the Windows code page, and
    printing a receipt named in Chinese failed that purchase (Apple,
    2026-09-27, Cut the Rope). The panel always set UTF-8, the terminal
    did not."""
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call", lambda argv, **kw: calls.append(kw) or 0)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    assert paperpull.run(root / "chase", ["python", "chase_docs.py"]) == 0
    assert calls[0]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert calls[0]["cwd"] == str(root / "chase")

    monkeypatch.setenv("PYTHONIOENCODING", "utf-16")
    assert paperpull.app_env()["PYTHONIOENCODING"] == "utf-16", "a setting of the person's own is kept"

    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    out = tmp_path / "run.log"
    with open(out, "wb") as sink:
        rc = subprocess.run([sys.executable, "-c", "print('\\u5272\\u7ef3\\u5b50')"],
                            stdout=sink, env=paperpull.app_env()).returncode
    assert rc == 0
    assert out.read_bytes().decode("utf-8").strip() == "割绳子"


def test_no_venv_and_nothing_that_can_run_it_stops_naming_setup_all(root, monkeypatch):
    """Since #65 a checkout is set up all at once, by setup-all, into one
    environment every app shares. Setting up one app alone still works.
    An app with a venv of its own is never stopped."""
    monkeypatch.setattr(paperpull, "runs_apps", lambda python: False)
    script = "setup-all.bat" if os.name == "nt" else "setup-all.command"
    with pytest.raises(SystemExit, match=r"chase is not set up yet\. Run %s in .*, or "
                       r"python paperpull\.py chase setup" % re.escape(script)):
        paperpull.main(["--root", str(root), "chase", "verify"])
    monkeypatch.setattr(paperpull, "run", lambda app_dir, argv: 0)
    assert paperpull.main(["--root", str(root), "pge", "verify"]) == 0


def _shared(root: Path) -> Path:
    """The checkout's shared environment, where paperpull.SHARED_VENV is."""
    py = root / "gui" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    return py


def test_an_app_with_no_venv_of_its_own_runs_on_the_checkouts_shared_one(root):
    shared = _shared(root)
    assert paperpull.interpreter(root / "chase") == shared
    assert paperpull.build_argv(root / "chase", "pilot", None, [])[0] == str(shared)
    assert paperpull.interpreter(root / "PG&E Statements") == \
        root / "PG&E Statements" / ".venv" / "Scripts" / "python.exe"


def test_the_shared_environment_is_asked_whether_it_can_run_an_app(tmp_path, monkeypatch):
    """The gui/.venv every setup-all made before this one holds the panel's
    packages and none of an app's, so an app started on it would fail on
    its first import. It is asked, by starting it, as a run would."""
    venv = tmp_path / "gui" / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                   check=True, capture_output=True)
    python = paperpull.venv_python(venv)
    stubs = tmp_path / "stubs"
    for name in paperpull.NEEDS:
        (stubs / name).mkdir(parents=True)
        (stubs / name / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(stubs))
    assert paperpull.runs_apps(python)
    shutil.rmtree(stubs / "pypdf")
    assert not paperpull.runs_apps(python)
    monkeypatch.delenv("PYTHONPATH")
    assert not paperpull.runs_apps(python)
    assert not paperpull.runs_apps(tmp_path / "nowhere" / "python.exe")


def test_list_marks_only_an_app_nothing_here_can_run(root, monkeypatch, capsys):
    """It used to mark every app with no venv, which in the packaged app,
    whose apps never have one, was all of them."""
    for answer in (False, True):
        monkeypatch.setattr(paperpull, "runs_apps", lambda python: answer)
        assert paperpull.main(["--root", str(root), "list"]) == 0
        marked = {line.split()[0] for line in capsys.readouterr().out.splitlines()
                  if "(not set up yet)" in line}
        assert marked == ({"chase", "target"} if not answer else set()), marked


def _calls_that_make_venvs(calls: list, fail_at=None):
    """subprocess.call, which writes each argv down and, asked to make a
    venv, puts a Python in it, failing the call numbered fail_at."""
    def call(argv, **kw):
        calls.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            py = Path(argv[3]) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_bytes(b"")
        return 1 if len(calls) == fail_at else 0
    return call


def test_setup_makes_a_venv_installs_requirements_then_the_core(root, monkeypatch):
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call", _calls_that_make_venvs(calls))
    monkeypatch.setattr(paperpull, "core_source", lambda: ["-e", "CORE"])
    (root / "chase" / "requirements.txt").write_text("playwright\n", encoding="utf-8")
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 0
    assert calls[0][1:] == ["-m", "venv", str(root / "chase" / ".venv")]
    assert calls[-1][-2:] == ["-e", "CORE"]
    assert any("requirements.txt" in " ".join(c) for c in calls)


def test_setup_gives_an_app_its_own_venv_even_beside_the_shared_one(root, monkeypatch):
    """setup is for one app on its own, and installs nothing into the
    environment every other app runs on."""
    shared = _shared(root)
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call", _calls_that_make_venvs(calls))
    monkeypatch.setattr(paperpull, "core_source", lambda: ["-e", "CORE"])
    (root / "chase" / "requirements.txt").write_text("playwright\n", encoding="utf-8")
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 0
    own = paperpull.venv_python(root / "chase" / ".venv")
    assert calls[0][1:3] == ["-m", "venv"]
    assert [c[0] for c in calls[1:]] == [str(own)] * 3, calls
    assert str(shared) not in str(calls)


def test_setup_stops_when_the_venv_it_made_holds_no_python(root, monkeypatch):
    """It used to go on and install everything into the Python running it."""
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call", lambda argv, **kw: calls.append(argv) or 0)
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 1
    assert len(calls) == 1


def test_setup_stops_at_the_first_failed_step(root, monkeypatch):
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call", _calls_that_make_venvs(calls, fail_at=2))
    monkeypatch.setattr(paperpull, "core_source", lambda: ["-e", "CORE"])
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 1
    assert len(calls) == 2


# -- where the apps are --------------------------------------------------------

def test_root_precedence_is_flag_then_environment_then_panel_then_checkout(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"apps_root": "%s"}' % (tmp_path / "panel").as_posix(),
                        encoding="utf-8")
    monkeypatch.setattr(paperpull, "settings_path", lambda: settings)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    assert paperpull.apps_root(None) == tmp_path / "panel"
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "env"))
    assert paperpull.apps_root(None) == tmp_path / "env"
    assert paperpull.apps_root(str(tmp_path / "flag")) == tmp_path / "flag"
    monkeypatch.delenv("APPS_ROOT")
    settings.unlink()
    assert paperpull.apps_root(None) == REPO / "apps"


# -- the panel and the terminal agree -------------------------------------------

def test_the_terminal_offers_every_command_the_panel_does():
    src = (REPO / "gui" / "app.py").read_text(encoding="utf-8")
    block = src[src.index("ACTIONS = {"):src.index("}", src.index("ACTIONS = {"))]
    panel = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    assert panel, "could not read the panel's ACTIONS"
    assert panel <= set(paperpull.COMMANDS), panel - set(paperpull.COMMANDS)


def test_every_real_app_resolves_and_builds_a_command():
    """Against the checkout itself, so a new provider that breaks the naming
    convention is caught here rather than by the first person to type it."""
    apps = paperpull.list_apps(REPO / "apps")
    assert len(apps) >= 26
    for d in apps:
        assert paperpull.find_app(REPO / "apps", d.name) == d
        argv = paperpull.build_argv(d, "pilot", None, [])
        assert argv[1].endswith((".py",)) and argv[2] == "--pilot"
        assert paperpull.build_argv(d, "login", None, [])[2] in ("--open-browser", "--login")


# -- the launchers that are gone stay gone -------------------------------------

def test_an_app_ships_only_setup_login_and_review_names_as_double_click_files():
    """Two hundred and forty-four files that each called one script with one
    flag were deleted for #23. The dispatcher does that job. A new provider
    cloned from an old checkout would bring them back.

    review_names came back on its own terms, in every receipt app that has
    the mode and nowhere else, because it asks for one name at a time and
    so cannot run in the panel, and a tester told to type its terminal
    command on a Mac got "command not found" (#47)."""
    everywhere = {"setup.bat", "setup.command", "login.bat", "login.command"}
    review = {"review_names.bat", "review_names.command"}
    stray, missing, with_mode = [], [], 0
    for app in sorted(d for d in (REPO / "apps").iterdir() if d.is_dir()):
        entry = paperpull.entry_script(app)
        has_mode = bool(entry) and "--review-names" in entry.read_text(encoding="utf-8", errors="ignore")
        with_mode += has_mode
        allowed = everywhere | (review if has_mode else set())
        for f in app.iterdir():
            if f.suffix in (".bat", ".command") and f.name not in allowed:
                stray.append(str(f.relative_to(REPO)))
        if has_mode:
            missing += [str((app / n).relative_to(REPO)) for n in sorted(review)
                        if not (app / n).is_file()]
    assert with_mode >= 12, with_mode
    assert not stray, "launchers that paperpull.py replaced: " + ", ".join(stray)
    assert not missing, "a receipt app without its review_names file: " + ", ".join(missing)


def test_every_command_file_opens_on_a_mac_double_click():
    """A .command opens on a double-click only when it is executable and
    has Unix line endings. git on Windows cannot record the first, and the
    setup and login files of the 36 apps generated on a Windows machine
    reached every Mac without it, 72 files that would not open."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-s", "--", "*.command"], cwd=REPO,
                            capture_output=True, text=True)
    if listed.returncode:
        pytest.skip("not a git checkout")
    rows = [line.split(None, 3) for line in listed.stdout.splitlines() if line.strip()]
    assert len(rows) > 100, len(rows)
    not_executable = [row[3] for row in rows if row[0] != "100755"]
    assert not not_executable, ("run git update-index --chmod=+x on " + ", ".join(not_executable))
    eol = subprocess.run([git, "ls-files", "--eol", "--", "*.command"], cwd=REPO,
                         capture_output=True, text=True)
    crlf = [line.split()[-1] for line in eol.stdout.splitlines()
            if line.strip() and not line.startswith("i/lf")]
    assert not crlf, "a .command stored without Unix line endings: " + ", ".join(crlf)


def test_no_app_doc_still_points_at_a_deleted_launcher():
    gone = re.compile(r"\b(run_pilot|run_all|resume|verify_documents|diagnose)\.(bat|command)\b")
    stale = []
    for f in (REPO / "apps").glob("*/*.md"):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if gone.search(line):
                stale.append("%s:%d" % (f.relative_to(REPO), i))
    for f in (REPO / "apps").glob("*/COMMANDS.txt"):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if gone.search(line):
                stale.append("%s:%d" % (f.relative_to(REPO), i))
    assert not stale, "docs still name a deleted launcher: " + ", ".join(stale)


def test_the_packaged_app_defaults_to_documents_not_its_templates(tmp_path, monkeypatch):
    here = tmp_path / "PaperPull.app" / "Contents" / "Resources"
    (here / "templates" / "apps").mkdir(parents=True)
    monkeypatch.setattr(paperpull, "HERE", here)
    monkeypatch.setattr(paperpull, "settings_path", lambda: tmp_path / "none.json")
    monkeypatch.delenv("APPS_ROOT", raising=False)
    assert paperpull.apps_root(None) == Path.home() / "Documents" / "PaperPull"


def test_on_windows_the_terminal_reads_the_panels_settings_from_roaming_first(tmp_path, monkeypatch):
    monkeypatch.setattr(paperpull.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    new = tmp_path / "Roaming" / "PaperPull" / "settings.json"
    old = tmp_path / "Local" / "PaperPull" / "settings.json"
    # nothing anywhere: the new location, so a later write lands there
    assert paperpull.settings_path() == new
    # only the old file, the panel has not run yet to move it: read it
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")
    assert paperpull.settings_path() == old
    # both: the new one wins
    new.parent.mkdir(parents=True)
    new.write_text("{}", encoding="utf-8")
    assert paperpull.settings_path() == new


def test_a_relative_root_is_made_absolute_before_the_app_runs_in_its_own_folder(tmp_path, monkeypatch):
    """`paperpull --root apps schwab setup` handed pip "apps/schwab/requirements.txt"
    while running inside apps/schwab, and pip could not find it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "apps").mkdir()
    root = paperpull.apps_root("apps")
    assert root.is_absolute() and root == tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", "apps")
    assert paperpull.apps_root(None).is_absolute()
