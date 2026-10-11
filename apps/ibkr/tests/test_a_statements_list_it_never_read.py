"""Discover never calls a statements list it did not read whole, and a
statement is filed under the account its own file names, in a real browser.

From the review of #77. The months come from the Activity Statement
dialog's Date select. When the dialog never opened (its row not drawn in
time, Monthly not chosen, no Date select of months) the list came back
empty, and Discover noted it read whole, so Pilot and Run All finished
clean with nothing done. It stops now, as every other app does since
0.45.0.

The account number was read from the first 1,200 characters of the page,
so a notice above the heading left it unread, and the same months came
back as new records filed under "Account", each to be downloaded again
under a second name. The whole page is read now, a page with no account
number on it stops Discover, and a file whose own name says it belongs to
another account is not taken.

In a real browser attached over CDP, as at home. Interactive Brokers is a
made-up host name the browser is told to find on this machine, and every
other name fails to resolve, so nothing reaches Interactive Brokers. Every
account number and month is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ibkr_docs as app_mod
import ibkr_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

IBKR_HOST = "www.interactivebrokers.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % IBKR_HOST)
ACCOUNT = "U1234567"
MONTHS = [("September, 2031", "203109"), ("August, 2031", "203108"),
          ("July, 2031", "203107")]

# The Statements page. Its Default Statements list draws a moment after the
# page, with the Activity Statement row and its Run arrow. Run opens the
# statement dialog, with a Period select and, once Monthly is chosen, the
# Date select of months. Download PDF asks for the month chosen, and the
# file comes back named <account>_<YYYYMM>_<YYYYMM>.pdf, as the live page
# names it.
STATEMENTS_PAGE = """<!doctype html><html><head><title>Statements</title></head><body>
%(notice)s
<h1>Statements <span>%(account)s</span></h1>
<h3>Default Statements</h3>
<div id="list"></div>
<div id="dlg"></div>
<script>
const ROWS = %(rows)s;
const MONTHS = %(months)s;
function dialog() {
  document.getElementById('dlg').innerHTML =
    '<div role="dialog" aria-label="Activity Statement">' +
    '<div class="modal-title">Activity Statement</div><form name="statementForm">' +
    '<select id="period"><option>Daily</option><option>Custom Date Range</option>' +
    '<option>Monthly</option><option>Annual</option></select>' +
    '<select id="date" hidden>' + MONTHS.map(m => '<option value="string:' + m[1] + '">' +
    m[0] + '</option>').join('') + '</select>' +
    '<button type="button" id="pdf">Download PDF</button></form></div>';
  const p = document.getElementById('period'), d = document.getElementById('date');
  p.addEventListener('change', () => { d.hidden = p.value !== 'Monthly'; });
  document.getElementById('pdf').addEventListener('click', () => {
    location.href = '/statement?m=' + d.value.replace('string:', '');
  });
}
if (ROWS) setTimeout(() => {
  document.getElementById('list').innerHTML = '<div class="row"><strong>Activity Statement' +
    '</strong> <a href="#" aria-label="Info">i</a> <a href="#" aria-label="Run">&rarr;</a></div>';
  document.querySelector("a[aria-label='Run']").addEventListener('click', (e) => {
    e.preventDefault();
    dialog();
  });
}, 300);
</script></body></html>"""

PORTAL_PAGE = """<!doctype html><html><head><title>Portal</title></head><body>
<h1>Portfolio</h1></body></html>"""


class FakeIbkr:
    def __init__(self):
        self.reset()

    def reset(self):
        # Whether the Activity Statement row draws, the account number the
        # page shows (none at all when empty), a notice drawn above the
        # heading, and the account the downloaded file is named for.
        self.rows = True
        self.account = ACCOUNT
        self.notice = ""
        self.file_account = ACCOUNT


SITE = FakeIbkr()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, headers=()):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        parts = urlsplit(self.path)
        if host != IBKR_HOST:
            self.send_error(404)
        elif parts.path.startswith("/AccountManagement/"):
            page = STATEMENTS_PAGE % {"rows": "true" if SITE.rows else "false",
                                      "account": SITE.account, "notice": SITE.notice,
                                      "months": json.dumps(MONTHS)}
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        elif parts.path == "/statement":
            month = parse_qs(parts.query).get("m", [""])[0]
            name = "%s_%s_%s.pdf" % (SITE.file_account, month, month)
            self._send(testkit.text_pdf(["Activity Statement", SITE.file_account, month]),
                       "application/pdf",
                       [("Content-Disposition", 'attachment; filename="%s"' % name)])
        elif parts.path == "/portal/":
            self._send(PORTAL_PAGE.encode("utf-8"), "text/html; charset=utf-8")
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
    return "http://%s:%d%s" % (IBKR_HOST, server, path)


@pytest.fixture(autouse=True)
def made_up_ibkr(server, monkeypatch):
    """Interactive Brokers is the made-up site, and the app's waits are short."""
    SITE.reset()
    base = "http://%s:%d" % (IBKR_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name, path in (("home", "/"), ("login", "/sso/Login"), ("portal", "/portal/"),
                       ("documents", site.STATEMENTS_PATH)):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == IBKR_HOST)
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 3000)
    from playwright.sync_api import Page
    real_wait = Page.wait_for_timeout
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    return SITE


@pytest.fixture
def tab(attached, server):
    """A tab in the browser the app attaches to, on the Statements page."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(attached)
    page = browser.contexts[0].new_page()
    page.goto(address(server, site.STATEMENTS_PATH))
    yield page
    page.close()
    pw.stop()


# -- Discover, driven through main ----------------------------------------

def run_discover(tmp_path, attached, server, capsys):
    """The person's tab on the portal, the only tab open, then a Discover.
    How it ended, what it said, whether the list was noted whole, and the
    records it holds."""
    theirs = testkit.open_tab(attached, address(server, "/portal/"), "Portal")
    testkit.keep_only(attached, {theirs})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": attached,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    capsys.readouterr()
    try:
        ended = ("returned", app_mod.main(["--config", str(cfg), "--discover"]))
    except SystemExit as e:
        ended = ("exit", e.code)
    said = " ".join(capsys.readouterr().out.split())
    whole = json.loads((tmp_path / "out" / "last-listing.json").read_text(
        encoding="utf-8"))["complete"]
    found = tmp_path / "out" / "discovery.json"
    records = json.loads(found.read_text(encoding="utf-8")) if found.exists() else {}
    return ended, said, whole, records


def test_discover_lists_every_month_the_dialog_offers(tmp_path, attached, server, capsys):
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert sorted(r["document_id"] for r in records.values()) == sorted(c for _, c in MONTHS)
    assert {r["account_id"] for r in records.values()} == {ACCOUNT}


def test_discover_stops_when_the_statement_dialog_never_opens(tmp_path, attached, server,
                                                              capsys):
    """The Activity Statement row never draws, so no month was read."""
    SITE.rows = False
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "Discovery complete" not in said, said[-1500:]
    assert records == {}


def test_discover_stops_when_no_account_number_reads(tmp_path, attached, server, capsys):
    SITE.account = ""
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert records == {}


def test_a_notice_above_the_heading_lists_no_month_twice(tmp_path, attached, server, capsys):
    run_discover(tmp_path, attached, server, capsys)
    SITE.notice = "<p>%s</p>" % ("An invented notice about the account. " * 40)
    ended, said, whole, records = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert len(records) == len(MONTHS), sorted(records)


# -- a download --------------------------------------------------------------

def download(tab, tmp_path):
    out = tmp_path / "Statements" / "statement.pdf"
    got = site.download_document(tab, account_id=ACCOUNT, doc_type="Activity Statement",
                                 title="Activity Statement - Account %s" % ACCOUNT,
                                 date="2031-09-30", out_path=out,
                                 document_id_hint="203109", dl_dir=tmp_path / "staging")
    return got, out


def test_a_statement_of_its_own_account_is_saved(tab, tmp_path):
    got, out = download(tab, tmp_path)
    assert got and out.read_bytes()[:5] == b"%PDF-"


def test_a_statement_named_for_another_account_is_not_taken(tab, tmp_path):
    SITE.file_account = "U7654321"
    got, out = download(tab, tmp_path)
    assert got is False
    assert not out.exists()
    assert not [p for p in out.parent.glob("*") if p.is_file()]


# -- the regional host message ----------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.interactivebrokers.de/portal/",
    "https://www.interactivebrokers.com.au/portal/",
    "https://www.interactivebrokers.co.jp/portal/",
])
def test_another_regional_domain_is_named(url):
    assert site.regional_host_problem(url)


@pytest.mark.parametrize("url", [
    "https://www.interactivebrokers.com.example.test/portal/",
    "https://interactivebrokers.co.example/portal/",
    "https://www.interactivebrokers.com.au.example.test/portal/",
])
def test_a_lookalike_domain_is_never_suggested(url):
    assert site.regional_host_problem(url) is None
