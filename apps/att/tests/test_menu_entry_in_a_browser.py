"""AT&T's Download PDF menu is pressed only while Download PDF is on the page.

The tester's screenshot (#26, round seven) showed what "Download PDF" does.
A small menu pops down holding "Regular PDF" and "Accessibility PDF",
made of plain elements, and "Regular PDF" saves the bill. Where in the page
the menu is drawn was never recorded, beside the button or at the end of
the page, so where the entry sits is written to the trace and not yet
required. What is required is that the Download PDF pressed is still on
the page, since a bill drawn anew after the press may show another bill's
menu.

AT&T's own _catch_pdf in a real browser, on a page of the test's own.
Every word here is made up.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_site as site
from paperpull_core import pressing

sync_api = pytest.importorskip("playwright.sync_api")

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bill</title>
<style>html, body { margin: 0; font: 16px sans-serif; } .menu div { padding: 6px; cursor: pointer; }</style>
<script>
window.presses = 0; window.entryPresses = 0;
function menu() {
  const m = document.createElement('div');
  m.className = 'menu';
  for (const text of ['Accessibility PDF', 'Regular PDF']) {
    const d = document.createElement('div');
    d.textContent = text;
    if (text === 'Regular PDF') d.onclick = () => { window.entryPresses++; fetch('/bill.pdf'); };
    m.append(d);
  }
  return m;
}
window.then = %s;
</script></head>
<body><nav><a href="/home">Home</a></nav>
<main><h1>Bill for June 2026</h1>
<div class="actions"><button id="get" type="button"
  onclick="window.presses++; window.then(this);">Download PDF</button></div>
</main></body></html>"""

BESIDE = "(el) => el.after(menu())"
AT_THE_END = "(el) => document.body.append(menu())"
DRAWN_ANEW = ("(el) => { const b = document.createElement('button'); b.type = 'button';"
              " b.textContent = 'Download PDF'; el.replaceWith(b); b.after(menu()); }")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.startswith("/bill.pdf"):
            body, kind = _PDF, "application/pdf"
        else:
            body, kind = self.server.page.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def capture(browser, tmp_path, monkeypatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 700})
    monkeypatch.setattr(site, "is_safe_url", lambda url: (
        urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == port))
    monkeypatch.setattr(pressing, "PRESS_MS", 3000)

    def run(then):
        httpd.page = PAGE % then
        page = context.new_page()
        page.goto("http://127.0.0.1:%d/bill" % port)
        own_wait = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: own_wait(min(ms, 30))
        out = tmp_path / "2026-06-30 Bill.pdf"
        staging = tmp_path / "downloads"
        staging.mkdir(exist_ok=True)
        trace, pressed = [], []
        page.result = {"trace": trace, "out": out, "pressed": pressed,
                       "saved": site._catch_pdf(page, page.locator("#get"), "Download PDF", out,
                                                trace, staging, pressed)}
        return page

    yield run
    context.close()
    httpd.shutdown()
    httpd.server_close()


def _where(trace):
    return [t["where"] for t in trace if t.get("note") == "where the menu entry sits"]


def test_the_menu_beside_download_pdf_saves_the_regular_bill(capture):
    page = capture(BESIDE)
    assert page.result["saved"] is True
    assert page.result["out"].read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1 and page.evaluate("window.entryPresses") == 1
    assert _where(page.result["trace"]) == ["beside the pressed control"]


def test_a_menu_drawn_at_the_end_of_the_page_still_saves_it_and_says_where(capture):
    """Not yet required, since where AT&T draws the menu is not known. The
    trace says where it sat, so a tester's file can settle it."""
    page = capture(AT_THE_END)
    assert page.result["saved"] is True
    assert _where(page.result["trace"]) == ["elsewhere on the page"]


def test_a_menu_once_download_pdf_was_drawn_anew_is_not_pressed(capture):
    page = capture(DRAWN_ANEW)
    assert page.result["saved"] is False
    assert not page.result["out"].exists()
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.entryPresses") == 0, "a menu entry was pressed after the bill was drawn anew"
    assert _where(page.result["trace"]) == ["the pressed control left the page"]
    assert site._LEFT_THE_PAGE in page.result["pressed"], \
        "download_bill would go on to press the View/print PDF showing now"


def test_a_bill_saved_from_the_menu_beside_download_pdf_is_not_marked_gone(capture):
    page = capture(BESIDE)
    assert site._LEFT_THE_PAGE not in page.result["pressed"]
