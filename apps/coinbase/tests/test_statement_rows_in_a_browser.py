"""Each statement row is read by its own month, or by nothing.

The statements page lists "Last 30 days" first and then one row per month,
each with HTML, PDF and CSV buttons. A PDF button's month is read upward
from the button, from the nearest element whose text starts with a month.
A row whose own text began with something else, a badge say, climbed on to
the list around every row, whose text starts with "Last 30 days", and was
read as that row. The list skipped "Last 30 days" however often it came, so
that month was dropped without a word. Now an element holding a second PDF
button is the list, not a row, and the climb stops there with no label,
which stops the listing.

Every row here is invented and the browser is refused the network.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import coinbase_site as site

BUTTONS = ("<div><button type='button'>HTML</button>"
           "<button type='button' data-testid='statements-pdf-v2'>PDF</button>"
           "<button type='button'>CSV</button></div>")


def statements(*rows: str) -> str:
    return ("<!doctype html><html><body><main><div class='list'>%s</div></main></body></html>"
            % "".join("<div class='row'>%s%s</div>" % (r, BUTTONS) for r in rows))


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    yield ctx.new_page()
    browser.close()
    driver.stop()


def test_each_row_reads_its_own_month(page):
    page.set_content(statements("<span>Last 30 days</span>", "<span>September 2026</span>",
                                "<span>August 2026</span>"))
    assert [r["label"] for r in site._read_rows(page)] == ["Last 30 days", "September 2026",
                                                           "August 2026"]


def test_a_row_that_does_not_start_with_its_month_reads_nothing(page):
    page.set_content(statements("<span>Last 30 days</span>", "<span>September 2026</span>",
                                "<span>New</span> <span>August 2026</span>"))
    assert [r["label"] for r in site._read_rows(page)] == ["Last 30 days", "September 2026", ""]


def test_that_row_stops_the_listing_rather_than_dropping_its_month(page, monkeypatch):
    monkeypatch.setattr(site, "LOAD_MORE_LOOK_AGAIN_MS", 10)
    page.set_content(statements("<span>Last 30 days</span>", "<span>September 2026</span>",
                                "<span>New</span> <span>August 2026</span>"))
    with pytest.raises(site.ListStopped) as stopped:
        site._collect_statements(page, "2026-08-03", date(2026, 10, 11))
    assert [d.date_text for d in stopped.value.docs] == ["2026-09-30"]
