"""Every echo line in a batch file prints the whole line.

In cmd a bare & ends a command and runs what follows it as another one, a
bare | pipes into it, and a bare < or > redirects. So the banner line
"echo   2. Open your Statements & Documents page" printed half a line and
then said "'Documents' is not recognized as an internal or external
command", and AT&T's login and setup said the same of "T". The line has to
write ^& (PG&E and M&T always did), or hold the character inside double
quotes, where cmd leaves it alone.

The census reads every tracked .bat file, the apps' and the root's, and
names each echo line with such a character outside double quotes. A
redirect at the very end of the line, such as >nul or 2>&1, is meant and
is let through. A second test runs sample lines in cmd itself, so what the
census calls fine is what cmd prints whole. A third holds the Mac
launchers, which tools/make_unix_launchers.py writes from these lines, to
the text cmd prints, not the caret that keeps it whole.
"""
import importlib.util
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# An echo command, at the start of a line or after an if, a do, an else, an
# @ or an opening parenthesis. What follows it, to the end of the line, is
# what it prints.
ECHO = re.compile(r"(?:^|[\s(@])echo(?=[\s.,;:=(/+\[\]]|$)", re.I)

# One redirect a line may end on, of either stream, to nul, to the other
# stream, or to a file named by a variable or in quotes.
_TARGET = r'(?:nul|&[12]|"[^"]*"|%\w+%)'
REDIRECTS = re.compile(r"\s*(?:[12]?>>?\s*%s\s*)+" % _TARGET, re.I)


def bare_specials(line: str) -> list:
    """The places in an echo line where cmd would end, pipe or redirect it,
    each a & | < or > outside double quotes with no caret before it. A
    redirect the line ends on is meant and is left out. A line that echoes
    nothing, or a remark, has none."""
    stripped = line.lstrip().lower()
    if stripped.startswith("::") or re.match(r"@?rem(\s|$)", stripped):
        return []
    found = ECHO.search(line)
    if not found:
        return []
    start = found.end()
    places, quoted, i = [], False, start
    while i < len(line):
        c = line[i]
        if c == '"':
            quoted = not quoted
        elif not quoted and c == "^":
            i += 1
        elif not quoted and c in "&|<>":
            places.append(i)
        i += 1
    if places and line[places[0]] == ">":
        first = places[0] - 1 if line[places[0] - 1:places[0]] in ("1", "2") else places[0]
        if line[first - 1:first].isspace() and REDIRECTS.fullmatch(line, first - 1):
            return []
    return places


def _tracked_batch_files():
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-z", "--", "*.bat", "*.cmd"],
                            cwd=REPO, capture_output=True)
    if listed.returncode:
        pytest.skip("not a git checkout")
    return [rel for rel in listed.stdout.decode("utf-8").split("\0") if rel]


def test_every_echo_line_in_a_batch_file_prints_the_whole_line():
    """The census over every tracked batch file, the apps' and the root's."""
    files = _tracked_batch_files()
    assert len(files) > 140, len(files)
    assert {"setup-all.bat", "apps/pge/login.bat", "tools/status.bat"} <= set(files)
    wrong, echoes = [], 0
    for rel in files:
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if ECHO.search(line):
                echoes += 1
            if bare_specials(line):
                wrong.append("%s:%d  %s" % (rel, n, line.strip()))
    # Not passing because it read nothing.
    assert echoes > 1500, echoes
    assert not wrong, ("cmd ends, pipes or redirects these echo lines partway, write the "
                       "character as ^& ^| ^< ^> or put it in double quotes.\n"
                       + "\n".join(wrong))


# (the line, what its author meant it to print). The census must call a
# line fine exactly when cmd prints that.
SAMPLES = [
    ("echo   2. Open your Statements & Documents page.", "  2. Open your Statements & Documents page."),
    ("echo   2. Open your Statements ^& Documents page.", "  2. Open your Statements & Documents page."),
    ("echo  AT&T Documents - sign in", " AT&T Documents - sign in"),
    ("echo  AT^&T Documents - sign in", " AT&T Documents - sign in"),
    ('echo   Run "a & b" here', '  Run "a & b" here'),
    ('echo   "^&" stays as written in quotes', '  "^&" stays as written in quotes'),
    ("echo   Account -> Billing (bill history).", "  Account -> Billing (bill history)."),
    ("echo   Account -^> Billing (bill history).", "  Account -> Billing (bill history)."),
    ("echo   one | two", "  one | two"),
    ("echo   one ^| two", "  one | two"),
    ("echo   a <b> c", "  a <b> c"),
    ("echo   a ^<b^> c", "  a <b> c"),
    ("echo   said nothing >nul", ""),
    ("echo   said nothing 1>nul 2>&1", ""),
    ('if not "1"=="" echo Account: A^&B', "Account: A&B"),
    ('if not "1"=="" echo Account: A&B', "Account: A&B"),
    ("rem   Statements & Documents", ""),
]


def test_the_census_agrees_with_cmd():
    """Each sample line runs in cmd from a folder of its own, and the
    census calls it fine exactly when cmd printed what was meant, nothing
    else and no error."""
    if sys.platform != "win32":
        pytest.skip("batch files run on Windows")
    import tempfile

    def run(n):
        line, meant = SAMPLES[n]
        with tempfile.TemporaryDirectory() as folder:
            bat = Path(folder) / "line.bat"
            bat.write_bytes(("@echo off\r\n%s\r\n" % line).encode("ascii"))
            r = subprocess.run(["cmd", "/d", "/c", str(bat)], cwd=folder,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            printed = r.stdout.rstrip("\r\n")
            whole = printed == meant and not r.stderr.strip()
            return line, whole, printed, r.stderr.strip()

    with ThreadPoolExecutor(8) as pool:
        ran = list(pool.map(run, range(len(SAMPLES))))
    disagree = ["%r: census says %s, cmd printed %r, said %r"
                % (line, "fine" if not bare_specials(line) else "broken", printed, said)
                for line, whole, printed, said in ran if whole != (not bare_specials(line))]
    assert not disagree, "\n".join(disagree)
    # Both answers came up, so neither side passed by saying the same thing always.
    assert {whole for _, whole, _, _ in ran} == {True, False}


def test_a_mac_launcher_prints_what_cmd_prints_not_the_caret(tmp_path):
    """bash prints a caret as it is, so the generator reads each line as
    cmd prints it, in the login banner, the setup title and the review
    names title alike."""
    spec = importlib.util.spec_from_file_location(
        "make_unix_launchers", REPO / "tools" / "make_unix_launchers.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    app = tmp_path / "att"
    app.mkdir()
    for name in ("login.bat", "setup.bat"):
        shutil.copy2(REPO / "apps" / "att" / name, app)
    review = (REPO / "apps" / "lowes" / "review_names.bat").read_text(encoding="utf-8")
    assert "echo  Lowe's Receipts - review names" in review
    (app / "review_names.bat").write_text(
        review.replace("Lowe's Receipts - review names", "AT^&T Receipts - review names"),
        encoding="utf-8")
    written = {f.name: f.read_text(encoding="utf-8") for f in gen.build(app)}
    assert sorted(written) == ["login.command", "review_names.command", "setup.command"]
    assert "echo 'AT&T Documents - sign in'" in written["login.command"]
    assert "myAT&T, Billing" in written["login.command"]
    assert 'echo "=== AT&T Documents setup ==="' in written["setup.command"]
    assert "echo 'AT&T Receipts - review names'" in written["review_names.command"]
    carets = [name for name, text in written.items() if "^" in text]
    assert not carets, carets
