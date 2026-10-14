"""Which of the core suite's two runs a test file of core/tests belongs to.

The core's tests run as two suites, core and core-browsers. Whole, core was
the longest suite on CI by far. Since CI went to six parts it ran alone in
part 1, 36 to 45 minutes against the job's limit of 45 while the other five
parts took 25 to 28, and two runs of 12 were stopped at the limit with
nothing failed. Here, a whole run of every suite took about as long as core
alone. As two suites, each part and each run here can fill up around them.

A file goes to core-browsers when its own code calls Playwright or one of
the core testkit's real-browser helpers, read with ast so a word in a
docstring or a comment does not count. Every other file, a new one
included, stays in core, and so does the privacy canary, so the suite the
runner holds to the canary is still core. The two are complements of one
rule, so every file runs in exactly one of them, and a file this rule
misplaces costs only balance, never a test.

The runner names the part in PAPERPULL_CORE_PART and loads this plugin with
-p core_part. Without that variable it ignores nothing, so pytest run by
hand in core/ still runs every test.
"""
import ast
import fnmatch
import os
from pathlib import Path

PART = "PAPERPULL_CORE_PART"
CORE = "core"
BROWSERS = "core-browsers"

# Calls that start or drive a real browser, Playwright's own and the core
# testkit's helpers that open one. The tab and fresh-browser censuses use
# stand-ins, so they stay in core.
DRIVES = frozenset({
    "sync_playwright", "async_playwright", "launch", "launch_persistent_context",
    "connect_over_cdp", "new_page", "new_context",
    "drawn_browser", "open_tab", "tabs_of", "keep_only", "_start_fresh_browser", "close_tab",
})

# Always in core, whatever they call. The canary holds the promise that a
# failure file carries no page content, and the runner refuses a run that
# holds core unless every test of it ran there.
KEPT_IN_CORE = frozenset({"test_failure_canary.py"})


# pytest's own default for the files it collects tests from. The hook reads
# the run's python_files, so a pattern set in pytest.ini counts too. A file
# pytest collects that this did not count as a test file would be left out
# of neither suite and so run in both.
PYTHON_FILES = ("test_*.py", "*_test.py")


def is_test_file(path, patterns=PYTHON_FILES) -> bool:
    name = Path(path).name
    return name.endswith(".py") and any(fnmatch.fnmatch(name, p) for p in patterns)


def drives_a_browser(path) -> bool:
    """Whether the file's code calls one of DRIVES. A file that cannot be
    read or parsed does not, so it stays in core, where its error shows."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
            if name in DRIVES:
                return True
    return False


def part_of(path) -> str:
    """core or core-browsers, for a test file of core/tests."""
    if Path(path).name in KEPT_IN_CORE:
        return CORE
    return BROWSERS if drives_a_browser(path) else CORE


def pytest_ignore_collect(collection_path, config):
    want = os.environ.get(PART, "")
    patterns = config.getini("python_files") if config is not None else PYTHON_FILES
    if want not in (CORE, BROWSERS) or not is_test_file(collection_path, patterns or PYTHON_FILES):
        return None
    return True if part_of(collection_path) != want else None
