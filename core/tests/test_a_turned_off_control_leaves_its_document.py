"""A document whose own control the site has turned off is left for review
and the next run, and the run goes on, in every app that presses one.

The release review of 0.45.0 found it. pressing.press_once stopped the run
when Playwright's press did not go through because the control was not
enabled, and pressing.click did the same. The apps that find a document's
control by its role and its name find a turned off one too, since
Playwright's get_by_role does, so a greyed out Download for one document
had Playwright wait eight seconds and then stopped the run there. Every
later run stopped at that same document, and nothing after it was ever
downloaded.

Now such a control is not pressed, and nothing is. The press raises
pressing.TurnedOff only once Playwright has said nothing but that it waited
and the control was not enabled, nothing came, and a fresh read finds the
control on the page, showing, turned off and with nothing over it. Where an
app presses a document's own control it catches that and leaves the
document, which its run marks for review and takes again on the next run.
Anywhere else TurnedOff stops the run as NotPressed did, and a turned off
control that something covers or that cannot be read stops it as before.

The census finds the presses by what the code does. From every method of
an app that marks a document downloaded it follows every function, method
and module function it can reach, through self, the app's own modules and
every name it hands on, and in them every press through
paperpull_core.pressing. Each one catches pressing.TurnedOff around the
press or is named in STOPS with why a turned off control there should stop
the run. Every press that catches it is then driven in a real browser, the
app's own function on a page whose control is turned off. Every word and
number here is made up.
"""
import ast
import importlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from paperpull_core import pressing

REPO = Path(__file__).resolve().parents[2]
HELPERS = {"press_once", "click", "check"}

# Presses a document's download reaches that stop the run when their control
# is turned off, as every press did before. None of them is a document's own
# control, or something was pressed for the document already.
STOPS = {
    ("amex", "goto_documents", "open the statements page"):
        "reaches the statements page every document is taken from, so a turned off "
        "link there would leave every document",
    ("amex", "expand_sections", "open a section"):
        "opens a section of the statements page for every document in it",
    ("amex", "close_file_type_dialog", "close the file type dialog"):
        "closes the dialog the document before left open, and a dialog that will not "
        "close covers every press after it",
    ("amex", "_choose_pdf", "choose the pdf"):
        "the PDF choice in the dialog the document's own Download opened, so a press "
        "was made for the document already",
    ("amex", "download_document", "press the dialog download"):
        "the dialog's own Download, once the row's Download opened the dialog, so a "
        "press was made for the document already",
    ("pge", "goto_page_number", ""):
        "the history's page picker, a step to the page a bill is on and every bill "
        "after it",
    ("vanguard", "dismiss_timeout", "continue the session"):
        "keeps the session open for every document",
    ("vanguard", "show_more", "show more of the list"):
        "a control of the whole list, read as turned on before it is pressed, and a "
        "list shown in full leaves only the statement not shown",
}

# The presses that catch TurnedOff and leave their document, by app, before
# this census. It finds them by what they do, this only keeps it from
# passing on finding none.
LEAVES = {
    ("adp", "open_tax_statement_check"), ("amex", "download_document"),
    ("amfam", "_catch_pdf"), ("applecard", "_catch_pdf"), ("att", "_catch_pdf"),
    ("etrade", "_catch_pdf"), ("golden1", "_catch_pdf"), ("nelnet", "_catch_pdf"),
    ("newrez", "_catch_pdf"), ("pge", "_press_once"), ("sba", "_catch_pdf"),
    ("smud", "_catch_pdf"), ("statefarm", "_catch_pdf"), ("vanguard", "download_document"),
    ("verizonmobile", "_catch_pdf"), ("wellsfargo", "_catch_pdf")}


# ---------------------------------------------------------------------------
# The census, by what the code does
# ---------------------------------------------------------------------------

def _modules(app: Path) -> dict:
    out = {}
    for path in sorted(app.glob("*.py")):
        try:
            out[path.stem] = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            pass
    return out


def _is_true(n) -> bool:
    return isinstance(n, ast.Constant) and n.value is True


def _marks_downloaded(fn) -> bool:
    """Whether a function marks a document or a receipt downloaded, which
    is what the method that takes one does, as an attribute, a key of a
    record or a keyword."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and _is_true(n.value) and any(
                (isinstance(t, ast.Attribute) and t.attr == "downloaded_ok")
                or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "downloaded_ok") for t in n.targets):
            return True
        if isinstance(n, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "downloaded_ok" and _is_true(v)
                for k, v in zip(n.keys, n.values)):
            return True
        if isinstance(n, ast.keyword) and n.arg == "downloaded_ok" and _is_true(n.value):
            return True
    return False


class _App:
    """An app's modules, what each one's names point to, and every press
    through paperpull_core.pressing that a document's download reaches."""

    def __init__(self, app: Path):
        self.name = app.name
        self.mods = _modules(app)
        self.funcs, self.methods, self.mod_alias, self.name_alias = {}, {}, {}, {}
        self.press_alias, self.pressing = {}, {}
        for m, tree in self.mods.items():
            self.funcs[m] = {n.name: n for n in tree.body
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            self.methods[m] = {}
            for c in tree.body:
                if isinstance(c, ast.ClassDef):
                    for n in c.body:
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.methods[m].setdefault(n.name, []).append(("%s.%s" % (c.name, n.name), n))
            self.mod_alias[m], self.name_alias[m] = {}, {}
            self.press_alias[m], self.pressing[m] = {}, set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name in self.mods:
                            self.mod_alias[m][a.asname or a.name] = a.name
                        if a.name.split(".")[-1] == "pressing":
                            self.pressing[m].add(a.asname or a.name)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    if n.module in self.mods:
                        for a in n.names:
                            self.name_alias[m][a.asname or a.name] = (n.module, a.name)
                    if n.module.split(".")[-1] == "pressing":
                        for a in n.names:
                            if a.name in HELPERS:
                                self.press_alias[m][a.asname or a.name] = a.name
                    for a in n.names:
                        if a.name == "pressing":
                            self.pressing[m].add(a.asname or "pressing")
        self.starts = [(m, qual, fn) for m in self.mods for defs in self.methods[m].values()
                       for qual, fn in defs if _marks_downloaded(fn)]
        self.presses = self._reach()

    def _helper(self, m: str, call: ast.Call) -> str:
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in HELPERS and isinstance(f.value, ast.Name) \
                and f.value.id in self.pressing[m]:
            return f.attr
        if isinstance(f, ast.Name) and f.id in self.press_alias[m]:
            return self.press_alias[m][f.id]
        return ""

    def _points_to(self, m: str, n) -> list:
        out = []
        if isinstance(n, ast.Name):
            if n.id in self.funcs[m]:
                out.append((m, n.id, self.funcs[m][n.id]))
            if n.id in self.name_alias[m]:
                mm, name = self.name_alias[m][n.id]
                if name in self.funcs.get(mm, {}):
                    out.append((mm, name, self.funcs[mm][name]))
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id in ("self", "cls"):
                out.extend((m, qual, d) for qual, d in self.methods[m].get(n.attr, []))
            elif n.value.id in self.mod_alias[m]:
                mm = self.mod_alias[m][n.value.id]
                if n.attr in self.funcs.get(mm, {}):
                    out.append((mm, n.attr, self.funcs[mm][n.attr]))
        return out

    def _reach(self) -> list:
        seen, queue, presses = set(), list(self.starts), []
        while queue:
            m, qual, fn = queue.pop()
            if (m, qual) in seen:
                continue
            seen.add((m, qual))
            parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and self._helper(m, n):
                    step = next((k.value.value for k in n.keywords
                                 if k.arg == "step" and isinstance(k.value, ast.Constant)), "")
                    presses.append({"app": self.name, "module": m, "function": qual,
                                    "helper": self._helper(m, n), "step": step,
                                    "line": n.lineno, "leaves": self._caught(m, n, parents, fn)})
                for target in self._points_to(m, n):
                    if (target[0], target[1]) not in seen:
                        queue.append(target)
        return sorted(presses, key=lambda p: (p["module"], p["line"]))

    def _caught(self, m: str, call, parents: dict, fn) -> bool:
        """Whether the press sits in the body of a try, in its own function,
        with a handler for pressing.TurnedOff."""
        child, node = call, parents.get(call)
        while node is not None and node is not fn:
            if isinstance(node, ast.Try) and any(child is s for s in node.body):
                for h in node.handlers:
                    kinds = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
                    if any(isinstance(k, ast.Attribute) and k.attr == "TurnedOff"
                           and isinstance(k.value, ast.Name) and k.value.id in self.pressing[m]
                           for k in kinds):
                        return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return False
            child, node = node, parents.get(node)
        return False


APPS = [_App(d) for d in sorted((REPO / "apps").iterdir())
        if d.is_dir() and not d.name.startswith(("_", "."))]
PRESSES = [p for a in APPS for p in a.presses]
LEAVING = sorted({(p["app"], p["function"]) for p in PRESSES if p["leaves"]})
# Driven in a browser, every press that leaves its document and every one
# known to, so a press that stopped leaving still fails there.
DRIVEN = sorted(set(LEAVING) | LEAVES)


def test_every_app_that_takes_documents_is_read():
    """Not vacuous. The method that takes one document or one receipt is
    found in every app, by what it does."""
    entry = {a.name for a in APPS if any(m.endswith(("_docs", "_receipts")) for m in a.mods)}
    missing = sorted(a.name for a in APPS if a.name in entry and not a.starts)
    assert len(entry) >= 55 and not missing, missing


def test_every_press_a_document_reaches_leaves_it_or_says_why_it_stops():
    unnamed = ["%(app)s %(module)s.%(function)s line %(line)d, %(helper)s step %(step)r" % p
               for p in PRESSES
               if not p["leaves"] and (p["app"], p["function"], p["step"]) not in STOPS]
    assert not unnamed, (
        "these presses are reached from a document's download and neither catch "
        "pressing.TurnedOff nor are named in STOPS: %s" % unnamed)


def test_the_presses_named_to_stop_are_still_there():
    there = {(p["app"], p["function"], p["step"]) for p in PRESSES if not p["leaves"]}
    assert set(STOPS) <= there, sorted(set(STOPS) - there)


def test_every_document_control_known_to_be_pressed_leaves_its_document():
    assert set(LEAVING) >= LEAVES, sorted(LEAVES - set(LEAVING))


# ---------------------------------------------------------------------------
# Each press that leaves its document, driven in a real browser
# ---------------------------------------------------------------------------

sync_api = pytest.importorskip("playwright.sync_api")

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40

# Another document's control, drawn the moment the press is over, the way a
# list goes on drawing. A capture that went on looking for a second step
# would press it.
LATER = ("() => { const b = document.createElement('button'); b.type = 'button'; "
         "b.textContent = 'Download PDF'; b.onclick = () => { window.laterPresses++; }; "
         "document.body.appendChild(b); }")

COVER = ('<div style="position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; '
         'z-index: 10; background: rgba(0, 0, 0, .25)" onclick="window.coverPresses++">'
         'Chat with us</div>')

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
td { height: 64px; position: relative; }
.ctl { display: inline-block; width: 220px; height: 40px; }</style>
<script>window.presses = 0; window.laterPresses = 0; window.coverPresses = 0;</script></head>
<body><main><h1>Statements</h1>
<table><tr><td>%(row)s</td><td>%(control)s</td></tr></table></main>%(extra)s</body></html>"""

# Vanguard's statement, as its own browser test makes it up.
VG_ACCOUNT = "Example Holder, Cash Plus Account, 1234567"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        extra = []
        if path.startswith(("/statement.pdf", "/doc")):
            self.server.asked.append(path)
            body, kind = _PDF, "application/pdf"
            extra = [("Content-Disposition", 'attachment; filename="statement.pdf"')]
        else:
            body, kind = self.server.page.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _loaded(app: str, module: str):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_site", "_docs")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        importlib.import_module("storage")
        return importlib.import_module(module)
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


class _Ran:
    """What one drive of an app's own press path came to."""

    def __init__(self, page, server):
        self.page = page
        self.server = server
        self.result = None
        self.stop = None
        self.seconds = 0.0
        self.trace: list = []

    def count(self, name: str) -> int:
        return int(self.page.evaluate("window.%s" % name))


@pytest.fixture()
def drive(browser, tmp_path, monkeypatch):
    """Run `call(site, page, out, staging, trace)` on a page of the test's
    own site, with the press given half a second, the control drawn by
    `control`. `before` runs just before every press_once, and LATER is
    drawn as each one ends."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.asked = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 600}, accept_downloads=True)
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    real = pressing.press_once

    def run(app, module, call, *, row="June 30, 2026", control, extra="", before=None,
            press_ms=None):
        site = _loaded(app, module)
        monkeypatch.setattr(site, "is_safe_url", lambda url: (
            urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == port))
        if press_ms:
            monkeypatch.setattr(pressing, "PRESS_MS", press_ms)
        httpd.page = PAGE % {"row": row, "control": control, "extra": extra}
        page = context.new_page()
        page.goto("http://127.0.0.1:%d/statements" % port)
        ran = _Ran(page, httpd)

        def with_later(*args, **kwargs):
            if before is not None:
                page.evaluate(before)
            try:
                return real(*args, **kwargs)
            finally:
                page.evaluate(LATER)
        monkeypatch.setattr(pressing, "press_once", with_later)
        out = tmp_path / app / "2026-06-30 Statement.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = tmp_path / app / "downloads"
        staging.mkdir(exist_ok=True)
        started = time.monotonic()
        try:
            ran.result = call(site, page, out, staging, ran.trace)
        except pressing.Stop as stop:
            ran.stop = stop
        ran.seconds = time.monotonic() - started
        ran.out = out
        monkeypatch.setattr(pressing, "press_once", real)
        return ran

    yield run
    context.close()
    httpd.shutdown()
    httpd.server_close()


def _button(off: bool, words: str = "Download statement", **attrs) -> str:
    more = "".join(' %s="%s"' % (k.replace("_", "-"), v) for k, v in attrs.items())
    return ('<button id="get" type="button" class="ctl"%s%s '
            'onclick="window.presses++; fetch(\'/statement.pdf\');">%s</button>'
            % (" disabled" if off else "", more, words))


def _catch_pdf(site, page, out, staging, trace):
    return site._catch_pdf(page, page.query_selector("#get"), "Download statement", out, trace,
                           staging)


def _adp(monkeypatch):
    def call(site, page, out, staging, trace):
        monkeypatch.setattr(site, "goto_documents", lambda page: True)
        return site.open_tax_statement_check(page)
    return call


def _amex(site, page, out, staging, trace):
    return site.download_document(page, "Statement", "2026-06-30", out)


def _vanguard(monkeypatch):
    def call(site, page, out, staging, trace):
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "EVENT_WAIT_MS", 3000)
        return site.download_document(
            page, account_id="123400000000001", charitable=False, doc_type="Statement",
            title="Account Statement - " + VG_ACCOUNT, date="2026-08-31", out_path=out,
            dl_dir=staging)
    return call


def _pge(site, page, out, staging, trace):
    said: dict = {}
    got = site._press_once(page, page.query_selector("#get"), lambda: False, said=said)
    trace.append(said)
    return got


def _vanguard_icon(off: bool) -> str:
    return ('<a id="get" class="ctl" title="Pdf download icon" href="/doc"%s '
            'onclick="window.presses++" aria-label="Download a pdf statement generated on '
            'August 31, 2026 with description %s">pdf</a>'
            % (' aria-disabled="true"' if off else "", VG_ACCOUNT))


def _amex_button(off: bool) -> str:
    return ('<button id="get" type="button" class="ctl" '
            'data-testid="card/2026-06-30/download-button"%s '
            'onclick="window.presses++">Download</button>' % (" disabled" if off else ""))


def _pge_link(off: bool) -> str:
    return ('<a id="get" class="ctl" href="#"%s onclick="window.presses++; return false;">'
            'View Bill PDF</a>' % (' aria-disabled="true"' if off else ""))


def _how(app: str, function: str, monkeypatch):
    """The app's own press path, the page that shows its control, and the
    row it sits in, for each press that leaves its document."""
    if function == "_catch_pdf":
        return "%s_site" % app, _catch_pdf, _button, "June 30, 2026"
    if (app, function) == ("adp", "open_tax_statement_check"):
        return ("adp_site", _adp(monkeypatch),
                lambda off: _button(off, "View statement"), "2030 W-2")
    if (app, function) == ("amex", "download_document"):
        return "amex_site", _amex, _amex_button, "June 30, 2026"
    if (app, function) == ("vanguard", "download_document"):
        return "vanguard_site", _vanguard(monkeypatch), _vanguard_icon, \
            "%s</td><td>08/31/2026" % VG_ACCOUNT
    if (app, function) == ("pge", "_press_once"):
        return "pge_site", _pge, _pge_link, "June 30, 2026"
    return None


def test_every_press_that_leaves_its_document_is_driven_here(monkeypatch):
    undriven = [x for x in DRIVEN if _how(x[0], x[1], monkeypatch) is None]
    assert not undriven, "no browser drive for %s, add one to _how" % undriven


@pytest.mark.parametrize("app,function", DRIVEN, ids=lambda x: x)
def test_a_turned_off_control_is_not_pressed_and_the_run_goes_on(drive, app, function,
                                                                 monkeypatch):
    module, call, control, row = _how(app, function, monkeypatch)
    ran = drive(app, module, call, row=row, control=control(True))
    assert ran.stop is None, "the run stopped at a turned off control: %r" % (ran.stop,)
    assert not ran.result, "the press path took the document: %r" % (ran.result,)
    assert ran.count("presses") == 0, "the turned off control was pressed"
    assert ran.count("laterPresses") == 0, "a control drawn after the press was pressed"
    assert ran.server.asked == [], "something was asked for the document"
    assert not ran.out.exists()
    # Left once the press's own time is over, not after a capture's waits
    # for a document, which take ten seconds and more.
    assert ran.seconds < 9, ran.seconds


@pytest.mark.parametrize("app,function", DRIVEN, ids=lambda x: x)
def test_a_turned_off_control_under_a_cover_stops_the_run(drive, app, function, monkeypatch):
    module, call, control, row = _how(app, function, monkeypatch)
    ran = drive(app, module, call, row=row, control=control(True), extra=COVER)
    assert isinstance(ran.stop, pressing.Covered), ran.stop
    assert ran.count("presses") == 0
    assert ran.count("coverPresses") == 0


@pytest.mark.parametrize("app", sorted({a for a, f in DRIVEN if f == "_catch_pdf"}))
def test_a_control_turned_on_while_the_press_waits_is_pressed_once(drive, app):
    """The press still waits for a control the page turns on a moment
    later, as Playwright always did, and the statement it brings is saved."""
    ran = drive(app, "%s_site" % app, _catch_pdf, control=_button(True), press_ms=4000,
                before="() => setTimeout(() => { document.getElementById('get').disabled = "
                       "false; }, 300)")
    assert ran.stop is None, ran.stop
    assert ran.result is True
    assert ran.out.read_bytes() == _PDF
    assert ran.count("presses") == 1
