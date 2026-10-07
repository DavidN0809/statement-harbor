"""The double-click files do what they say, run for real (#47).

review_names.bat and review_names.command find the Python a folder should
run on, a checkout's own venv, or the packaged app's Python when the folder
has no setup file, which is how a folder the packaged app made looks. They
hand the app the account named after them, and pass its exit code back.

paperpull.bat opens the control panel when it is double-clicked in the
packaged app with nothing after it, because older shortcuts to the panel's
old launcher land on it, and otherwise runs the terminal command. Its exit
code is the command's, where every run used to report success.

setup-all builds one environment for a whole checkout, gui/.venv, which
is the control panel's own, and makes no venv for any app (#65). It says
all is set when that worked, and names the step that did not, where every
run since 0.19.0 reported a problem. In a checkout, login and review_names
run an app on its own .venv when it has one, and otherwise on gui/.venv
once that can import what an app needs, and they ask for setup-all until
it can.

The batch files run under cmd, on Windows only. The .command runs under
bash, Git's own on Windows, so the Windows test runner covers both. No
test here links to a real Python folder. A stand-in Python is a copy of
the interpreter's own files, pointed at its library by PYTHONHOME, so
nothing that cleans up a test folder can reach a real install. Where a
test needs a Python that sees none of the packages of the one running the
tests, it makes a venv with no pip, which on Windows holds copies.

Every shell script the repository ships is also read by bash -n, which
runs none of it, since setup-all.command did not parse for a month and
nothing asked. A Mac runs a .command with /bin/bash, which is 3.2, so on
a Mac that bash reads them as well, and CI does this on macOS and Linux.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == "win32"
APP = "lowes"                       # the one with an apostrophe in its name
SCRIPT = "lowes_receipts.py"

# The app's own script, replaced by one that says what it was given.
FAKE_APP = "import sys\nprint('APP GOT', sys.argv[1:])\nsys.exit(4)\n"

windows_only = pytest.mark.skipif(not WINDOWS, reason="batch files run on Windows")


def _bash():
    """Git's bash on Windows, never the WSL one on PATH, whose paths differ."""
    if WINDOWS:
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


def _stand_in_python(folder: Path) -> dict:
    """A python.exe in `folder` that runs, and the environment it needs."""
    folder.mkdir(parents=True, exist_ok=True)
    base = Path(sys.base_prefix)
    for f in [base / "python.exe", *base.glob("*.dll")]:
        shutil.copy2(f, folder / f.name)
    return dict(os.environ, PYTHONHOME=str(base))


def _cmd(bat: Path, *args, env=None):
    """Run a batch file the way a double-click does, with no one to press a
    key at its pause."""
    line = subprocess.list2cmdline([str(bat), *args])
    return subprocess.run("cmd /c " + line + " < NUL", shell=True, capture_output=True,
                          text=True, env=env, cwd=str(bat.parent))


# -- review_names.bat ----------------------------------------------------------

@windows_only
def test_review_names_bat_runs_on_the_installed_apps_python(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.bat", install)
    (install / SCRIPT).write_text(FAKE_APP, encoding="utf-8")
    env = _stand_in_python(tmp_path / "Local" / "PaperPull" / "python")
    env["LOCALAPPDATA"] = str(tmp_path / "Local")

    r = _cmd(install / "review_names.bat", env=env)
    assert "APP GOT ['--review-names']" in r.stdout, r.stdout + r.stderr
    assert "Lowe's Receipts - review names" in r.stdout
    assert r.returncode == 4, "the app's own exit code must come back"

    r = _cmd(install / "review_names.bat", "spouse", env=env)
    assert "APP GOT ['--review-names', '--config', 'config.spouse.json']" in r.stdout, r.stdout


@windows_only
def test_review_names_bat_asks_for_setup_in_a_checkout_that_has_none(tmp_path):
    """A folder with setup.bat is set up by it, and never borrows the
    installed app's Python, whose shared code may be another version."""
    folder = tmp_path / "lowes"
    folder.mkdir()
    for name in ("review_names.bat", "setup.bat"):
        shutil.copy2(REPO / "apps" / APP / name, folder)
    (folder / SCRIPT).write_text(FAKE_APP, encoding="utf-8")
    env = _stand_in_python(tmp_path / "Local" / "PaperPull" / "python")
    env["LOCALAPPDATA"] = str(tmp_path / "Local")

    r = _cmd(folder / "review_names.bat", env=env)
    assert "run setup.bat first" in r.stdout, r.stdout
    assert "APP GOT" not in r.stdout
    assert r.returncode == 1


@windows_only
def test_review_names_bat_says_what_to_do_when_the_app_is_not_installed(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.bat", install)
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "nowhere"))
    r = _cmd(install / "review_names.bat", env=env)
    assert "was not found" in r.stdout and "paperpull.bat lowes review-names" in r.stdout, r.stdout
    assert r.returncode == 1


# -- paperpull.bat -------------------------------------------------------------

def _packaged_folder(tmp_path: Path, with_exe: bool) -> tuple:
    folder = tmp_path / ("installed" if with_exe else "checkout")
    env = _stand_in_python(folder / "python")
    shutil.copy2(REPO / "paperpull.bat", folder)
    (folder / "paperpull.py").write_text(
        "import sys\nprint('TERMINAL GOT', sys.argv[1:])\nsys.exit(3)\n", encoding="utf-8")
    if with_exe:
        # Stands in for the panel's PaperPull.exe. It prints this computer's
        # name, which nothing else here does.
        shutil.copy2(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "hostname.exe",
                     folder / "PaperPull.exe")
    return folder, env


@windows_only
def test_paperpull_bat_double_clicked_in_the_package_opens_the_panel(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=True)
    r = _cmd(folder / "paperpull.bat", env=env)
    assert os.environ.get("COMPUTERNAME", "").lower() in r.stdout.lower(), r.stdout + r.stderr
    assert "TERMINAL GOT" not in r.stdout


@windows_only
def test_paperpull_bat_with_a_command_runs_it_and_passes_its_exit_code_back(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=True)
    r = _cmd(folder / "paperpull.bat", "costco", "review-names", env=env)
    assert "TERMINAL GOT ['costco', 'review-names']" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3


@windows_only
def test_paperpull_bat_in_a_checkout_is_only_the_terminal_command(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=False)
    r = _cmd(folder / "paperpull.bat", env=env)
    assert "TERMINAL GOT []" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3


# -- setup-all -----------------------------------------------------------------

# pip in the stand-in venv. It writes down what it was asked, fails when the
# word in FAKE_PIP_FAILS is among its arguments, and installs nothing.
FAKE_PIP = ("import os, sys\n"
            "with open(os.environ['FAKE_PIP_LOG'], 'a', encoding='utf-8') as log:\n"
            "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.exit(1 if os.environ.get('FAKE_PIP_FAILS') in sys.argv else 0)\n")

# Every requirements file of the checkout setup-all is tried on, the panel's
# first and then the apps' in the order a folder listing gives them.
SETUP_ALL_REQUIREMENTS = ["gui/requirements.txt", "apps/demo/requirements.txt",
                          "apps/kept/requirements.txt"]


def _setup_all_checkout(tmp_path: Path, script: str) -> Path:
    """setup-all beside the GUI and two apps, kept, which has a venv of its
    own, and demo, which has none."""
    checkout = tmp_path / "checkout"
    for folder in ("apps/demo", "apps/kept", "gui"):
        (checkout / folder).mkdir(parents=True)
        (checkout / folder / "requirements.txt").write_text("pypdf\n", encoding="utf-8")
    kept = checkout / "apps" / "kept" / ".venv" / ("Scripts/python.exe" if script.endswith(".bat")
                                                   else "bin/python")
    kept.parent.mkdir(parents=True)
    kept.write_text("#!/bin/sh\necho KEPT VENV RAN\n", encoding="utf-8", newline="\n")
    kept.chmod(0o755)
    (checkout / "core").mkdir()
    (checkout / "core" / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copy2(REPO / script, checkout)
    return checkout


def _pip_calls(log: Path) -> list:
    """Each call written down, its words joined by spaces, with / for \\."""
    if not log.is_file():
        return []
    return [line.replace("\\", "/").replace('"', "")
            for line in log.read_text(encoding="utf-8").splitlines()]


def _says_one_environment(r, checkout: Path, calls: list, venv_folder: str) -> None:
    """What both setup-alls are held to. One pip call reads every
    requirements file, the core goes in from the checkout, no app gets a
    venv, and the app that has one of its own is named and left alone."""
    said = r.stdout + r.stderr
    assert "All set. The control panel and 2 apps share one environment, %s." % venv_folder \
        in r.stdout, said
    asked = [c.split() for c in calls if "-r" in c.split()]
    assert len(asked) == 1, calls
    words = asked[0]
    assert [words[i + 1] for i, w in enumerate(words[:-1]) if w == "-r"] \
        == SETUP_ALL_REQUIREMENTS, calls
    assert any(c.endswith("-e ./core") for c in calls), calls
    assert not (checkout / "apps" / "demo" / ".venv").exists(), "setup-all made a venv for an app"
    assert "keep the .venv of their own" in r.stdout and " kept" in r.stdout, said
    assert "KEPT VENV RAN" not in said


@windows_only
def test_setup_all_bat_builds_one_environment_and_names_a_step_that_failed(tmp_path):
    """It used to make a venv in every app folder, about 400 MB each,
    though every app asks for the same few packages (#65). From 0.19.0
    every run also listed playwright-chromium among the setups that had
    problems, since the script checked for a browser download it no longer
    made."""
    checkout = _setup_all_checkout(tmp_path, "setup-all.bat")
    env = _stand_in_python(checkout / "gui" / ".venv" / "Scripts")
    pip = tmp_path / "fake" / "pip"
    pip.mkdir(parents=True)
    (pip / "__init__.py").write_text("", encoding="utf-8")
    (pip / "__main__.py").write_text(FAKE_PIP, encoding="utf-8")
    log = tmp_path / "pip.log"
    env.update(PYTHONPATH=str(tmp_path / "fake"), PYTHONNOUSERSITE="1", PIP_NO_INDEX="1",
               FAKE_PIP_LOG=str(log))
    # The script stops when it finds no Python on PATH, so one is there.
    env["PATH"] = str(checkout / "gui" / ".venv" / "Scripts") + os.pathsep + env.get("PATH", "")

    r = _cmd(checkout / "setup-all.bat", env=env)
    _says_one_environment(r, checkout, _pip_calls(log), "gui\\.venv")
    assert "failed" not in r.stdout

    log.unlink()
    env["FAKE_PIP_FAILS"] = "-r"
    r = _cmd(checkout / "setup-all.bat", env=env)
    assert "Installing the requirements failed" in r.stdout, r.stdout + r.stderr
    assert "Setup did not finish" in r.stdout and "All set" not in r.stdout


# python3 for setup-all.command. Its venv is a folder whose python writes
# down what it was asked and fails as FAKE_PIP does.
FAKE_PYTHON3 = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    echo "venv $3" >> "$FAKE_PIP_LOG"
    mkdir -p "$3/bin"
    cp "$FAKE_VENV_PYTHON" "$3/bin/python"
    chmod +x "$3/bin/python"
    exit 0
fi
exit 1
"""
FAKE_VENV_PYTHON = """#!/bin/sh
echo "$*" >> "$FAKE_PIP_LOG"
for word in "$@"; do
    if [ "$word" = "${FAKE_PIP_FAILS:-}" ]; then exit 1; fi
done
exit 0
"""


def test_setup_all_command_builds_one_environment_and_names_a_step_that_failed(tmp_path):
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run a .command with")
    checkout = _setup_all_checkout(tmp_path, "setup-all.command")
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, text in (("python3", FAKE_PYTHON3), ("venv-python", FAKE_VENV_PYTHON)):
        (tools / name).write_text(text, encoding="utf-8", newline="\n")
        (tools / name).chmod(0o755)
    log = tmp_path / "pip.log"
    env = dict(os.environ, FAKE_PIP_LOG=log.as_posix(),
               FAKE_VENV_PYTHON=(tools / "venv-python").as_posix(),
               PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""))

    def run():
        return subprocess.run([bash, (checkout / "setup-all.command").as_posix()],
                              capture_output=True, text=True, env=env, cwd=str(checkout))

    r = run()
    calls = _pip_calls(log)
    _says_one_environment(r, checkout, calls, "gui/.venv")
    assert [c for c in calls if c.startswith("venv ")] == ["venv gui/.venv"], calls
    assert r.returncode == 0, r.stdout + r.stderr

    log.unlink()
    env["FAKE_PIP_FAILS"] = "-r"
    r = run()
    assert "Installing the requirements failed" in r.stdout, r.stdout + r.stderr
    assert "Setup did not finish" in r.stdout and "All set" not in r.stdout
    assert r.returncode == 1
    assert [c for c in _pip_calls(log) if c.startswith("venv ")] == [], \
        "the environment already there is used again"


# -- review_names.command ------------------------------------------------------

def _run_command(script: Path, home: Path, *args):
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run a .command with")
    env = dict(os.environ, HOME=home.as_posix())
    return subprocess.run([bash, script.as_posix(), *args], capture_output=True, text=True,
                          env=env, cwd=str(script.parent))


def _fake_mac_app(home: Path) -> None:
    """PaperPull.app in ~/Applications, with a python3 that says what it
    was given and whether it was started the way the app starts it."""
    py = home / "Applications" / "PaperPull.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\necho "BUNDLED PY: $* NOUSERSITE=$PYTHONNOUSERSITE"\n',
                  encoding="utf-8", newline="\n")
    py.chmod(0o755)


def test_review_names_command_runs_on_the_apps_own_python(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.command", install)
    _fake_mac_app(tmp_path / "home")

    r = _run_command(install / "review_names.command", tmp_path / "home")
    assert "BUNDLED PY: %s --review-names NOUSERSITE=1" % SCRIPT in r.stdout, r.stdout + r.stderr
    assert "Lowe's Receipts - review names" in r.stdout
    assert r.returncode == 0

    r = _run_command(install / "review_names.command", tmp_path / "home", "spouse")
    assert "--review-names --config config.spouse.json" in r.stdout, r.stdout + r.stderr


def test_review_names_command_asks_for_setup_in_a_checkout_that_has_none(tmp_path):
    folder = tmp_path / "lowes"
    folder.mkdir()
    for name in ("review_names.command", "setup.command"):
        shutil.copy2(REPO / "apps" / APP / name, folder)
    _fake_mac_app(tmp_path / "home")
    r = _run_command(folder / "review_names.command", tmp_path / "home")
    assert "run ./setup.command first" in r.stdout, r.stdout + r.stderr
    assert "BUNDLED PY" not in r.stdout
    assert r.returncode == 1


def test_review_names_command_says_what_to_do_when_the_app_is_not_found(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.command", install)
    (tmp_path / "home").mkdir()
    r = _run_command(install / "review_names.command", tmp_path / "home")
    assert "was not found in Applications" in r.stdout, r.stdout + r.stderr
    assert "paperpull lowes review-names" in r.stdout
    assert r.returncode == 1


# -- a checkout's shared environment, from each launcher (#65) -----------------

# What a launcher checks the shared environment can import before it runs an
# app on it.
NEEDS = ("paperpull_core", "playwright", "pypdf")

# The app's own script, replaced by one that also says which Python ran it.
FAKE_APP_SAYS_WHERE = ("import sys\nprint('APP GOT', sys.argv[1:])\n"
                       "print('RAN ON', sys.executable)\nsys.exit(4)\n")

# Every kind of launcher that runs an app, as (app, launcher, its script, its
# flag). PG&E's login.bat chooses its Python before its banner, the rest
# after it.
LAUNCHED = [pytest.param(app, launcher, script, flag,
                         marks=[windows_only] if launcher.endswith(".bat") else [],
                         id="%s/%s" % (app, launcher))
            for app, launcher, script, flag in (
                (APP, "login.bat", SCRIPT, "--open-browser"),
                (APP, "review_names.bat", SCRIPT, "--review-names"),
                ("pge", "login.bat", "pge_docs.py", "--open-browser"),
                (APP, "login.command", SCRIPT, "--open-browser"),
                (APP, "review_names.command", SCRIPT, "--review-names"),
                ("pge", "login.command", "pge_docs.py", "--open-browser"))]


def _venv(folder: Path) -> None:
    """A real venv with no pip in it, whose Python sees none of the
    packages of the Python that made it, as gui/.venv did before setup-all
    filled it. On Windows it also gets the bin/python a .command looks for,
    which hands over to the venv's own."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder)],
                   check=True, capture_output=True)
    if WINDOWS:
        (folder / "bin").mkdir()
        (folder / "bin" / "python").write_text(
            '#!/bin/sh\nexec "%s" "$@"\n' % (folder / "Scripts" / "python.exe").as_posix(),
            encoding="utf-8", newline="\n")


def _checkout_with(tmp_path: Path, app: str, launcher: str, script: str,
                   shared: bool = True, own: bool = False) -> Path:
    """An app in a checkout's layout, with its launcher, its setup file and
    FAKE_APP_SAYS_WHERE for its script, setup-all two folders up, and
    gui/.venv and a venv of the app's own when asked for. Returns the
    app's folder."""
    checkout = tmp_path / "checkout"
    folder = checkout / "apps" / app
    folder.mkdir(parents=True)
    suffix = Path(launcher).suffix
    for name in (launcher, "setup" + suffix):
        shutil.copy2(REPO / "apps" / app / name, folder)
    (folder / script).write_text(FAKE_APP_SAYS_WHERE, encoding="utf-8")
    shutil.copy2(REPO / ("setup-all" + suffix), checkout)
    if shared:
        _venv(checkout / "gui" / ".venv")
    if own:
        _venv(folder / ".venv")
    return folder


def _stubs(tmp_path: Path, names=NEEDS) -> Path:
    """A folder holding an empty package for each of names."""
    stubs = tmp_path / "stubs"
    for name in names:
        (stubs / name).mkdir(parents=True)
        (stubs / name / "__init__.py").write_text("", encoding="utf-8")
    return stubs


def _launch(tmp_path: Path, launcher: Path, stubs, *args):
    """Run a launcher as a double-click does, where a venv can import
    nothing but what is in stubs."""
    env = dict(os.environ, HOME=(tmp_path / "home").as_posix())
    for name in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    if stubs is not None:
        env["PYTHONPATH"] = str(stubs)
    if launcher.suffix == ".bat":
        return _cmd(launcher, *args, env=env)
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run a .command with")
    return subprocess.run([bash, launcher.as_posix(), *args], capture_output=True, text=True,
                          env=env, cwd=str(launcher.parent))


def _ran_in(out: str):
    """The venv whose Python ran FAKE_APP_SAYS_WHERE, or None."""
    m = re.search(r"^RAN ON (.+)$", out, re.M)
    return str(Path(m.group(1).strip()).parents[1]) if m else None


@pytest.mark.parametrize("app,launcher,script,flag", LAUNCHED)
def test_a_launcher_in_a_checkout_runs_on_the_shared_environment(app, launcher, script, flag,
                                                                 tmp_path):
    """An app with no venv of its own runs on gui/.venv, which setup-all
    builds once for all of them, where each used to need one of its own of
    about 400 MB (#65). The account named after it still reaches the app."""
    folder = _checkout_with(tmp_path, app, launcher, script)
    stubs = _stubs(tmp_path)
    r = _launch(tmp_path, folder / launcher, stubs)
    said = r.stdout + r.stderr
    assert "APP GOT ['%s']" % flag in r.stdout, said
    assert os.path.samefile(_ran_in(r.stdout), folder.parents[1] / "gui" / ".venv"), said

    r = _launch(tmp_path, folder / launcher, stubs, "spouse")
    assert "APP GOT ['%s', '--config', 'config.spouse.json']" % flag in r.stdout, \
        r.stdout + r.stderr


@pytest.mark.parametrize("app,launcher,script,flag", LAUNCHED)
def test_a_launcher_keeps_an_apps_own_environment(app, launcher, script, flag, tmp_path):
    """An app set up on its own, before setup-all built one environment or
    since by its own setup file, keeps running on its own venv."""
    folder = _checkout_with(tmp_path, app, launcher, script, own=True)
    r = _launch(tmp_path, folder / launcher, _stubs(tmp_path))
    said = r.stdout + r.stderr
    assert "APP GOT ['%s']" % flag in r.stdout, said
    assert os.path.samefile(_ran_in(r.stdout), folder / ".venv"), said


@pytest.mark.parametrize("app,launcher,script,flag", LAUNCHED)
def test_a_launcher_asks_for_setup_all_until_the_shared_environment_can_run_an_app(
        app, launcher, script, flag, tmp_path):
    """gui/.venv as every setup-all made it before this one, with the
    panel's packages and none of an app's, would start an app only for it
    to fail on an import. Missing one package is enough to ask, and so is
    having no gui/.venv at all."""
    folder = _checkout_with(tmp_path, app, launcher, script)
    asked = "Run setup-all%s in the PaperPull folder first." % Path(launcher).suffix
    for stubs in (_stubs(tmp_path, NEEDS[:-1]), None, "no gui/.venv"):
        if stubs == "no gui/.venv":
            shutil.rmtree(folder.parents[1] / "gui")
            stubs = _stubs(tmp_path / "all", NEEDS)
        r = _launch(tmp_path, folder / launcher, stubs)
        assert asked in r.stdout, r.stdout + r.stderr
        assert "APP GOT" not in r.stdout
        assert r.returncode == 1


@pytest.mark.parametrize("launcher", [pytest.param("login.bat", marks=windows_only),
                                      "login.command"])
def test_login_outside_a_checkout_asks_for_its_own_setup(launcher, tmp_path):
    """A folder the panel made from a checkout, somewhere else, has its own
    setup file and nothing two folders up, so that is the one it names."""
    folder = tmp_path / "Lowe's Receipts"
    folder.mkdir()
    for name in (launcher, "setup" + Path(launcher).suffix):
        shutil.copy2(REPO / "apps" / APP / name, folder)
    (folder / SCRIPT).write_text(FAKE_APP_SAYS_WHERE, encoding="utf-8")
    r = _launch(tmp_path, folder / launcher, _stubs(tmp_path))
    own = "setup.bat" if launcher.endswith(".bat") else "./setup.command"
    assert "This app is not set up yet - run %s first." % own in r.stdout, r.stdout + r.stderr
    assert "APP GOT" not in r.stdout
    assert r.returncode == 1


def _block(lines: list, first: str, last: str) -> list:
    start = lines.index(first)
    return lines[start:lines.index(last, start) + 1]


def test_every_batch_launcher_chooses_its_python_as_the_tested_ones_do():
    """Every login.bat and review_names.bat, in every app, tries the app's
    own venv first, then the shared one with the check the tests above
    run, says what to set up when neither will do, and runs the app only
    on the Python it chose. The files were changed by a script, and this
    is what holds each of them to the ones that run."""
    tested = (REPO / "apps" / APP / "login.bat").read_text(encoding="utf-8").splitlines()
    shared = _block(tested, 'set "PY=..\\..\\gui\\.venv\\Scripts\\python.exe"',
                    "if not errorlevel 1 goto run")
    refusal = _block(tested, ":notsetup", "exit /b 1")
    assert len(shared) == 4 and len(refusal) == 9, (shared, refusal)
    launchers = sorted((REPO / "apps").glob("*/login.bat")) + \
        sorted((REPO / "apps").glob("*/review_names.bat"))
    assert len(launchers) > 70, len(launchers)
    wrong = []
    for f in launchers:
        lines = f.read_text(encoding="utf-8").splitlines()
        name = "%s/%s" % (f.parent.name, f.name)
        try:
            own = lines.index('set "PY=.venv\\Scripts\\python.exe"')
            at = lines.index(shared[0])
            stop = lines.index(refusal[0])
            run = lines.index(":run")
        except ValueError as e:
            wrong.append("%s lacks %s" % (name, e))
            continue
        runs = [i for i, line in enumerate(lines) if re.search(r"\S+\.py\b", line)
                and not line.lower().startswith(("rem", "echo"))]
        if (lines[own + 1] != 'if exist "%PY%" goto run' or not own < at < stop < run
                or lines[at:at + len(shared)] != shared
                or lines[stop:stop + len(refusal)] != refusal
                or len(runs) != 1 or runs[0] <= run or not lines[runs[0]].startswith('"%PY%" ')):
            wrong.append(name)
    assert not wrong, "these choose their Python another way, " + ", ".join(wrong)


def test_every_mac_launcher_is_what_the_generator_writes(tmp_path):
    """The .command files are written from the .bat files by
    tools/make_unix_launchers.py. One edited by hand, or a change to the
    generator never run, leaves a Mac launcher doing what its .bat does
    not, and only the few tested above run on Windows."""
    spec = importlib.util.spec_from_file_location(
        "make_unix_launchers", REPO / "tools" / "make_unix_launchers.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    differ, made = [], 0
    for app in sorted(p for p in (REPO / "apps").iterdir() if p.is_dir()):
        copy = tmp_path / app.name
        copy.mkdir()
        for bat in app.glob("*.bat"):
            shutil.copy2(bat, copy)
        written = {f.name: f for f in gen.build(copy)}
        made += len(written)
        shipped = {f.name for f in app.glob("*.command")}
        for name in sorted(shipped | set(written)):
            if name not in written or name not in shipped \
                    or (app / name).read_bytes() != written[name].read_bytes():
                differ.append("%s/%s" % (app.name, name))
    assert made > 130, made
    assert not differ, ("these differ from what tools/make_unix_launchers.py writes, "
                        + ", ".join(differ))


# -- every shell script parses -------------------------------------------------

# A first line that hands the file to sh or bash.
SHELL_FIRST_LINE = re.compile(r"#!\s*(/usr)?/bin/(env\s+)?(ba)?sh\b")

# What removing the browser download left in setup-all.command in 0.19.0, an
# if with nothing but comments in it, which bash refuses to read.
EMPTIED_IF = """#!/usr/bin/env bash
for app in apps/*/; do
    if [ $first -eq 1 ]; then
# The browser download is no longer part of setup.
    fi
    echo "ok"
done
"""


def _bashes():
    """Each bash here that a script could meet. A Mac runs a .command with
    /bin/bash, which is 3.2, while PATH can find a newer one first."""
    found = {}
    for bash in (_bash(), None if WINDOWS else "/bin/bash"):
        if bash and Path(bash).is_file():
            found.setdefault(os.path.realpath(bash), bash)
    return list(found.values())


def _shell_scripts():
    """(path, text) for every tracked file a shell runs, found by its suffix
    or its first line, so paperpull, which has no suffix, is one of them."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-z"], cwd=REPO, capture_output=True)
    if listed.returncode:
        pytest.skip("not a git checkout")
    scripts = []
    for rel in listed.stdout.decode("utf-8").split("\0"):
        f = REPO / rel
        if not rel or not f.is_file():
            continue
        with f.open("rb") as fh:
            first = fh.readline(200).decode("utf-8", "replace")
        if f.suffix in (".command", ".sh") or SHELL_FIRST_LINE.match(first):
            # Read as text, so the CRLF a Windows checkout can give a file
            # that git stores with LF does not count against it.
            scripts.append((rel, f.read_text(encoding="utf-8")))
    return scripts


def _parse_errors(bash, scripts, folder: Path) -> list:
    """What bash -n says about each script that does not parse, or whose
    here-document runs to the end of the file, which bash -n only warns of.

    Each script gets a bash of its own, except on Windows, where Git's bash
    takes one to nine seconds to start on a busy machine. There one bash
    reads them all, each the body of a function of its own after a no-op,
    so that a script of comments alone still parses, and prints them back
    with --pretty-print, which runs nothing. Every function has to come
    back, in order, since a quote left open in one script can run into the
    next and close on a later apostrophe, and the whole would still parse.
    When they do not, halving the scripts finds the first one that breaks
    them, and bash reads that one alone, so the message is its own."""
    def alone(n):
        name, text = scripts[n]
        f = folder / ("alone-%d.sh" % n)
        f.write_bytes(text.encode("utf-8"))
        r = subprocess.run([bash, "-n", f.as_posix()], capture_output=True, text=True)
        said = r.stderr.replace(f.as_posix(), name).strip()
        if r.returncode or "delimited by end-of-file" in said:
            return said or "bash -n ended %d on %s" % (r.returncode, name)
        return ""

    def first_ones_come_back(n):
        """Whether the first n scripts come back as n functions, or None
        from a bash before 5.2, which has no --pretty-print."""
        f = folder / ("first-%d.sh" % n)
        f.write_bytes("".join("function _script_%d {\n:\n%s\n\n}\n" % (i, text)
                              for i, (_, text) in enumerate(scripts[:n])).encode("utf-8"))
        r = subprocess.run([bash, "--pretty-print", f.as_posix()], capture_output=True, text=True)
        if r.returncode and "--pretty-print" in r.stderr:
            return None
        back = re.findall(r"^(?:function )?_script_(\d+) \(\)", r.stdout, re.M)
        return r.returncode == 0 and back == [str(i) for i in range(n)]

    every = first_ones_come_back(len(scripts)) if WINDOWS else None
    if every is None:
        return [e for e in map(alone, range(len(scripts))) if e]
    if every:
        return []
    # The first `good` scripts come back and the first `bad` do not.
    good, bad = 0, len(scripts)
    while bad - good > 1:
        mid = (good + bad) // 2
        if first_ones_come_back(mid):
            good = mid
        else:
            bad = mid
    return [alone(bad - 1) or "%s parses alone but not as the body of a function"
            % scripts[bad - 1][0]]


@pytest.mark.parametrize("bash", _bashes())
def test_the_parse_check_names_an_if_with_nothing_left_in_it(bash, tmp_path):
    """Among scripts that parse, the check names the one that does not, in
    bash's own words, a quote left open is named although a later
    apostrophe closes it, and a script of a comment alone parses, as it
    does for bash -n on its own."""
    before = ("before.sh", "#!/bin/sh\necho before\n")
    notes = ("notes.sh", "#!/bin/sh\n# a comment and nothing else\n")
    open_quote = ("open-quote.command", "#!/usr/bin/env bash\necho 'Run this app's setup first'\n")
    later = ("later.sh", "#!/bin/sh\n# this app's own check\necho done\n")
    checks = {"emptied": [before, ("emptied.command", EMPTIED_IF), notes],
              "open-quote": [open_quote, later, notes],
              "clean": [notes, before]}
    # The three are read side by side, each in a folder of its own. They
    # start eight bashes between them, one after another within each, and
    # one after another all eight took a minute on a Windows machine whose
    # Git bash took several seconds to start.
    for name in checks:
        (tmp_path / name).mkdir()
    with ThreadPoolExecutor(len(checks)) as pool:
        said = dict(zip(checks, pool.map(
            lambda name: _parse_errors(bash, checks[name], tmp_path / name), checks)))

    errors = said["emptied"]
    assert len(errors) == 1, errors
    assert errors[0].startswith("emptied.command: line 5: syntax error"), errors

    errors = said["open-quote"]
    assert len(errors) == 1, errors
    assert errors[0].startswith("open-quote.command: line "), errors
    assert "unexpected EOF while looking for matching" in errors[0], errors

    assert said["clean"] == []


@pytest.mark.parametrize("bash", _bashes())
def test_every_shell_script_parses(bash, tmp_path):
    """From 0.19.0, setup-all.command held an if with nothing but comments
    in it. bash reads a whole loop before it runs any of it, so the script
    printed its header and the Python it found, ended on a syntax error,
    and set nothing up."""
    scripts = _shell_scripts()
    names = {name for name, _ in scripts}
    assert len(scripts) > 100, len(scripts)
    assert {"setup-all.command", "paperpull", "server/start.sh"} <= names, sorted(names)
    errors = _parse_errors(bash, scripts, tmp_path)
    assert not errors, "bash cannot read these.\n" + "\n".join(errors)


def test_every_shell_script_checks_out_with_unix_line_endings():
    """A Windows clone gives a text file CRLF unless .gitattributes pins
    it, and a script with CRLF does not start on macOS or Linux, or in WSL
    on that clone. paperpull has no suffix, so the *.command and *.sh lines
    missed it, and in WSL it said env could not find bash with a carriage
    return on the end."""
    names = [name for name, _ in _shell_scripts()]
    assert "paperpull" in names, names
    r = subprocess.run([shutil.which("git"), "check-attr", "-z", "eol", "--", *names],
                       cwd=REPO, capture_output=True, text=True)
    fields = r.stdout.split("\0")
    eol = dict(zip(fields[0::3], fields[2::3]))
    unpinned = [name for name in names if eol.get(name) != "lf"]
    assert not unpinned, "pin these to LF in .gitattributes, " + ", ".join(unpinned)
