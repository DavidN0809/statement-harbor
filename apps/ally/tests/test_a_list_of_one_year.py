"""Ally's list of statements is heard however many years its picker holds.

The collector listens for the answers to the page's own statements API and
walks the year picker, since the page asks for one year's list at a time.
It began listening after Discover had opened the page, so the answer the
page asked for as it opened was never heard, and only a pick that moved
the picker made the page ask again. With one year in the picker, as for a
new account or one whose statements all fall in one year, no pick moved it
and nothing was heard. With the page left on its oldest year, the first
pick did not move it and that year was never heard. A list heard empty fell
back to reading the rows, which takes Ally's statements of one date that
read alike as one, keeps no document id, and calls the list whole.

Every year the picker holds is now picked from another year, and the walk
waits for the last pick's answer. With one year or none to pick, the list
is drawn again while the collector listens, through the Tax Forms tab and
back by the page's own navigation, and only when that brings no list is
the statements address loaded. A list that never arrives, or a picker that
could not be read, stops the run rather than pass for an empty list. The
Tax Forms tab is opened while its own collector listens, so its answer was
always heard, and a test here keeps it so.

In a real browser attached over CDP, as at home. Ally is a made-up host
name the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches Ally. Every name, id and year is
invented. What the made-up page assumes of Ally's, beyond what the live
probe saw, is that it asks for the year it shows as it opens and when that
year changes and at no other time, as the collector's own comment says,
that a year with no statement is answered with an empty list of them, and
that coming back from the Tax Forms tab draws the list anew. On Ally the
tabs are inside one page, and here each is a page of its own.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ally_docs as app_mod
import ally_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit
from paperpull_core.testkit import stall_reads

ALLY_HOST = "secure.ally.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % ALLY_HOST)

STATEMENTS_PATH = "/bank/statements-and-forms"
TAX_PATH = STATEMENTS_PATH + "/tax"
API = "/acs/v1/bank-statements"


def statement(doc_id, day, trust=""):
    record = {"documentId": doc_id, "documentName": "Statement",
              "uploadDate": day + "T00:00:00Z", "iraType": False}
    if trust:
        record["trustName"] = trust
    return record


# Every statement the made-up account could hold, by year. Two of a date
# read alike, as Ally's do, and the third belongs to a trust.
STATEMENTS = {
    "2031": [statement("e0000000-0000-4000-8000-000000000001", "2031-03-31"),
             statement("e0000000-0000-4000-8000-000000000002", "2031-03-31"),
             statement("e0000000-0000-4000-8000-000000000003", "2031-03-31",
                       trust="Example Family")],
    "2030": [statement("e0000000-0000-4000-8000-000000000004", "2030-12-31"),
             statement("e0000000-0000-4000-8000-000000000005", "2030-12-31",
                       trust="Example Family")],
    "2029": [statement("e0000000-0000-4000-8000-000000000006", "2029-12-31")],
}

TAX_FORMS = [{"documentId": "f0000000-0000-4000-8000-000000000001",
              "documentName": "Form 1099-INT", "taxYear": 2030,
              "uploadDate": "2031-01-10T00:00:00Z", "corrected": False, "iraType": False}]

# The tabs above both lists.
TABS = """<nav><a href="%(statements)s?tab=statements">Statements</a>
<a href="%(tax)s">Tax Forms</a></nav>""" % {"statements": STATEMENTS_PATH, "tax": TAX_PATH}

# The statements page. It asks for the list of the year its picker shows as
# it opens, unless it keeps the list it drew, and again whenever the year
# shown changes, then draws a row per statement as Ally's does, its date
# beside a button named for it.
STATEMENTS_PAGE = """<!doctype html><html><head><title>Statements and Tax Forms</title>
<style>.hidden { position: absolute; clip: rect(0 0 0 0); }</style></head><body>
%(tabs)s<main>
<h1>Statements and Tax Forms</h1>
<label for="statementYear">Year</label>
<select id="statementYear" data-guid="statementYear">%(options)s</select>
<table id="statements"><thead><tr><th>Date Posted</th><th>Statement Title</th></tr></thead>
<tbody></tbody></table>
<script>
const KEPT = %(kept)s;
const sel = document.getElementById('statementYear');
const body = document.querySelector('#statements tbody');
let asked = '';
function draw(list) {
  body.innerHTML = list.length ? '' : '<tr><td>There are no statements for this year.</td></tr>';
  for (const s of list) {
    const d = s.uploadDate.slice(0, 10).split('-');
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + d[1] + '/' + d[2] + '/' + d[0] + '</td><td>' +
      '<span class="hidden">Download statement for: </span><button type="button">' +
      (s.trustName ? s.trustName + ' Trust Statement' : 'Statement') + '</button></td>';
    body.appendChild(tr);
  }
}
function ask(year) {
  if (year === asked) return;
  asked = year;
  fetch('%(api)s?docType=STATEMENTS&year=' + year)
    .then(r => r.ok ? r.json() : {statements: []})
    .then(j => draw(j.statements || []), () => draw([]));
}
sel.addEventListener('change', () => ask(sel.value));
if (KEPT) { asked = sel.value; draw(KEPT); } else { ask(sel.value); }
</script></main></body></html>"""

# The Tax Forms tab, which asks for every form as it opens.
TAX_PAGE = """<!doctype html><html><head><title>Tax Forms</title></head><body>
%(tabs)s<main>
<h1>Tax Forms</h1>
<label for="taxYear">Tax year</label>
<select id="taxYear"><option>2030</option></select>
<table><tbody id="forms"></tbody></table>
<script>
fetch('%(api)s?docType=TAXFORMS').then(r => r.json()).then(j => {
  for (const f of j.taxForms || []) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>1099-INT</td><td><button type="button">Download 1099-INT</button></td>';
    document.getElementById('forms').appendChild(tr);
  }
});
</script></main></body></html>"""

# Ally's dashboard, with the Documents control in its navigation.
DASHBOARD_PAGE = """<!doctype html><html><head><title>Snapshot</title></head><body>
<nav><a href="%(statements)s?from=nav">Documents</a></nav><main><h1>Snapshot</h1></main>
</body></html>"""

# Ally's sign-in page, drawn at the address asked for once the session ends.
SIGN_IN_PAGE = """<!doctype html><html><head><title>Log In</title></head><body><main>
<h1>Log In</h1><input type="text" aria-label="Username">
<input type="password" aria-label="Password"></main></body></html>"""


class FakeAlly:
    def __init__(self):
        self.reset()

    def reset(self):
        # The years the account's picker holds, newest first, and the one
        # it shows as the page opens.
        self.years = ["2031"]
        self.shown = None
        # Whether the API answers, the statements of each year it has, and
        # how long it takes to answer for a year.
        self.api_answers = True
        self.statements = {year: list(s) for year, s in STATEMENTS.items()}
        self.slow = {}
        # Whether the statements page, come back to by its tab, draws the
        # list it kept rather than ask for it.
        self.kept_on_return = False
        # Whether the Tax Forms tab's answer carries a list of statements
        # beside its forms, empty.
        self.tax_lists_statements = False
        # What a load of the statements page draws after its first, by the
        # number of the load. None draws the statements page every time.
        self.later_loads = None
        # The query of every load of the statements address, and the year
        # or kind of every call to the API.
        self.opened = []
        self.asked = []


SITE = FakeAlly()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _statements_page(self, query):
        shown = SITE.shown or SITE.years[0]
        options = "".join('<option data-guid="statementYear-%s"%s>%s</option>'
                          % (y, " selected" if y == shown else "", y) for y in SITE.years)
        kept = "false"
        if SITE.kept_on_return and query == "tab=statements":
            kept = json.dumps(SITE.statements.get(shown, []))
        return STATEMENTS_PAGE % {"options": options, "api": API, "tabs": TABS, "kept": kept}

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        parts = urlsplit(self.path)
        path = parts.path.rstrip("/")
        query = parse_qs(parts.query)
        if host != ALLY_HOST:
            self.send_error(404)
        elif path == STATEMENTS_PATH:
            SITE.opened.append(parts.query)
            later = (SITE.later_loads or {}).get(len(SITE.opened))
            if later == "sign-in":
                page = SIGN_IN_PAGE
            elif later == "dashboard":
                page = DASHBOARD_PAGE % {"statements": STATEMENTS_PATH}
            else:
                page = self._statements_page(parts.query)
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == TAX_PATH:
            page = TAX_PAGE % {"api": API, "tabs": TABS}
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == API:
            kind = (query.get("docType") or [""])[0]
            year = (query.get("year") or [""])[0]
            SITE.asked.append(year or kind)
            time.sleep(SITE.slow.get(year, 0))
            if not SITE.api_answers:
                self._send(b"Service Unavailable", "text/plain", status=503)
            elif kind == "TAXFORMS":
                answer = {"taxForms": TAX_FORMS}
                if SITE.tax_lists_statements:
                    answer["statements"] = []
                self._send(json.dumps(answer).encode("utf-8"), "application/json")
            else:
                held = SITE.statements.get(year, []) if year in SITE.years else []
                self._send(json.dumps({"statements": held}).encode("utf-8"),
                           "application/json")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def address(server, path):
    return "http://%s:%d%s" % (ALLY_HOST, server, path)


@pytest.fixture(autouse=True)
def made_up_ally(server, monkeypatch):
    """Ally is the made-up site, as it starts, and the app's waits are
    short."""
    SITE.reset()
    base = "http://%s:%d" % (ALLY_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name, path in (("home", "/"), ("login", "/"), ("documents", STATEMENTS_PATH),
                       ("documents_alt", "/statements"),
                       ("documents_alt2", "/dashboard/#/statements"),
                       ("statements", "/bank/statements")):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES", [
        site.URLS[name] for name in ("documents", "documents_alt", "documents_alt2", "statements")])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == ALLY_HOST)
    # raising=False, so the app as it was before these waits runs too.
    monkeypatch.setattr(site, "ANSWER_WAIT_S", 4, raising=False)
    monkeypatch.setattr(site, "DRAW_WAIT_S", 4, raising=False)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))


@pytest.fixture
def tab(attached):
    """A tab in the browser the app attaches to, for a look at a page."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(attached)
    page = browser.contexts[0].new_page()
    yield page
    page.close()
    pw.stop()


def ids(*years):
    return sorted(s["documentId"] for y in years for s in STATEMENTS[y])


def opened(tab, server):
    """The statements page open in `tab`, its list drawn, and nothing it
    asked for so far counted."""
    tab.goto(address(server, STATEMENTS_PATH))
    tab.wait_for_function("() => document.querySelector('#statements tbody').children.length > 0")
    del SITE.asked[:]


def listed(got):
    assert got is not None, "no list"
    return sorted(r["documentId"] for r in got)


def test_a_year_alone_in_the_picker_is_heard_inside_the_page(tab, server):
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031")
    # Drawn again by coming back through the page's own tab, and the
    # statements address was never loaded again.
    assert SITE.opened == ["", "tab=statements"], SITE.opened


def test_the_oldest_year_shown_is_heard(tab, server):
    SITE.years, SITE.shown = ["2031", "2030"], "2030"
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031", "2030")


def test_the_last_pick_is_waited_for(tab, server):
    # The year the page was left on is asked for only by the last pick,
    # and its answer is still on its way when the walk ends.
    SITE.years, SITE.shown, SITE.slow = ["2031", "2030"], "2030", {"2030": 1.5}
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031", "2030")


def test_a_year_with_no_statement_yet_is_an_empty_list(tab, server):
    SITE.statements["2031"] = []
    opened(tab, server)
    assert site.ally_collect_via_api(tab) == []
    assert "2031" in SITE.asked, SITE.asked


def test_a_list_that_never_arrives_is_not_an_empty_one(tab, server):
    SITE.api_answers = False
    opened(tab, server)
    assert site.ally_collect_via_api(tab) is None


def test_a_list_of_several_years_that_never_arrives_is_not_an_empty_one(tab, server):
    SITE.years, SITE.api_answers = ["2031", "2030", "2029"], False
    opened(tab, server)
    assert site.ally_collect_via_api(tab) is None


def test_a_list_the_page_keeps_is_asked_for_at_its_address(tab, server):
    SITE.kept_on_return = True
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031")
    assert SITE.opened == ["", "tab=statements", ""], SITE.opened


def test_the_tax_forms_tabs_answer_is_not_the_list(tab, server):
    # The tab's answer comes while the collector listens, and the list of
    # statements is still asked for.
    SITE.kept_on_return, SITE.tax_lists_statements = True, True
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031")
    assert "TAXFORMS" in SITE.asked, SITE.asked


def test_a_load_that_lands_elsewhere_finds_the_page_by_its_navigation(tab, server):
    # The statements address lands on the dashboard, as an address of the
    # app's own can, and its Documents control opens the statements page.
    SITE.kept_on_return, SITE.later_loads = True, {3: "dashboard"}
    opened(tab, server)
    assert listed(site.ally_collect_via_api(tab)) == ids("2031")
    assert SITE.opened == ["", "tab=statements", "", "from=nav"], SITE.opened


def test_a_picker_that_could_not_be_read_is_not_a_list(tab, server, monkeypatch, caplog):
    opened(tab, server)
    stall_reads(monkeypatch, {"statementYear-2031"}, locator=("all_inner_texts",))
    assert site.ally_collect_via_api(tab) is None
    assert "could not be read" in caplog.text


def run_discover(tmp_path, attached, server, capsys, types=("Statement",)):
    """Discover from the person's Ally tab on the statements address, the
    only tab open."""
    theirs = testkit.open_tab(attached, address(server, STATEMENTS_PATH),
                              "Statements and Tax Forms")
    testkit.keep_only(attached, {theirs})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": attached,
        "document_types": list(types), "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    capsys.readouterr()
    try:
        ended = ("returned", app_mod.main(["--config", str(cfg), "--discover"]))
    except SystemExit as e:
        ended = ("exit", e.code)
    said = " ".join(capsys.readouterr().out.split())
    out = tmp_path / "out"
    whole = json.loads((out / "last-listing.json").read_text(encoding="utf-8"))["complete"]
    found = out / "discovery.json"
    records = json.loads(found.read_text(encoding="utf-8")) if found.exists() else {}
    return ended, said, whole, records


def test_discover_lists_every_statement_of_a_single_year(server, attached, tmp_path, capsys):
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert sorted(records) == ["id:" + i for i in ids("2031")], (sorted(records), said[-1500:])


def test_discover_lists_the_oldest_year_the_page_was_left_on(server, attached, tmp_path,
                                                             capsys):
    SITE.years, SITE.shown = ["2031", "2030"], "2030"
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert sorted(records) == ["id:" + i for i in ids("2031", "2030")], sorted(records)


def test_discover_lists_every_year_from_the_newest(server, attached, tmp_path, capsys):
    SITE.years = ["2031", "2030", "2029"]
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert sorted(records) == ["id:" + i for i in ids("2031", "2030", "2029")], sorted(records)


def test_discover_of_a_new_account_lists_nothing_and_goes_on(server, attached, tmp_path,
                                                             capsys):
    SITE.statements["2031"] = []
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert records == {} and "did not arrive" not in said, said[-1500:]


def test_discover_stops_when_the_list_never_arrives(server, attached, tmp_path, capsys):
    SITE.api_answers = False
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "did not arrive whole" in said and records == {}, said[-1500:]


def test_discover_stops_when_the_session_ends_as_the_list_is_drawn_again(server, attached,
                                                                        tmp_path, capsys):
    SITE.later_loads = {n: "sign-in" for n in range(2, 12)}
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "signed you out" in said and records == {}, said[-1500:]


def test_discover_says_so_when_the_session_ends_again_after_a_sign_in(server, attached,
                                                                     tmp_path, capsys,
                                                                     monkeypatch):
    # Enter is pressed at the console, and the page is still a sign-in.
    SITE.later_loads = {n: "sign-in" for n in range(2, 30)}
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "asked for a sign-in or a check again" in said, said[-1500:]
    assert "did not arrive" not in said and records == {}, said[-1500:]


def test_discover_hears_the_tax_forms_tab_as_it_opens(server, attached, tmp_path, capsys):
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys,
                                               types=("Statement", "Tax Document"))
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert "id:" + TAX_FORMS[0]["documentId"] in records, sorted(records)
    assert "TAXFORMS" in SITE.asked
