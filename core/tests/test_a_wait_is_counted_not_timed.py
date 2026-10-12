"""testkit.Waits notes the waits code takes, so a test can say how long
code waited without timing it.

A check of a test's own seconds failed on a slow CI runner that stopped
for about 53 s inside a drive whose one wait was half a second. Several
tests now count waits instead, and some assert that nothing waited at all,
which a recorder that noted nothing would pass. So this shows it notes a
pause, a wait of Playwright's that ran out by either way one can run out,
and a sleep, and leaves out a read, a sleep on another thread and anything
outside counted(), and that its clock moves by the waits alone.
"""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.testkit import Wait, Waits  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")

PAGE = "<button id=off disabled>Download</button>"


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
def page(browser):
    context = browser.new_context(accept_downloads=True)
    pg = context.new_page()
    pg.set_content(PAGE)
    yield pg
    context.close()


def test_a_pause_is_noted_and_a_read_is_not(page, monkeypatch):
    with Waits(monkeypatch).counted() as taken:
        page.evaluate("1 + 1")
        page.locator("#off").is_visible()
        page.wait_for_timeout(30)
        page.main_frame.wait_for_timeout(20)
    assert taken == [Wait("paused", 30.0), Wait("paused", 20.0)]


def test_an_action_that_ran_out_is_noted_with_its_time(page, monkeypatch):
    with Waits(monkeypatch).counted() as taken:
        with pytest.raises(sync_api.TimeoutError):
            page.locator("#off").click(timeout=200)
    assert len(taken) == 1, taken
    assert taken[0].what.startswith("Locator.click: Timeout 200ms exceeded"), taken
    assert taken[0].ms == 200


def test_a_wait_for_an_event_that_ran_out_is_noted_either_way(page, monkeypatch):
    """wait_for_event runs out inside the call, and expect_download when its
    block ends, where Playwright reads the event's value."""
    with Waits(monkeypatch).counted() as taken:
        with pytest.raises(sync_api.TimeoutError):
            page.wait_for_event("download", timeout=150)
        with pytest.raises(sync_api.TimeoutError):
            with page.expect_download(timeout=120):
                pass
    assert [w.ms for w in taken] == [150, 120], taken
    assert all("Timeout" in w.what for w in taken), taken


def test_a_sleep_is_noted_on_its_own_thread_only(monkeypatch):
    waits = Waits(monkeypatch)
    with waits.counted() as taken:
        time.sleep(0.01)
        apart = threading.Thread(target=time.sleep, args=(0.01,))
        apart.start()
        apart.join()
    time.sleep(0.01)
    assert taken == [Wait("slept", 10.0)]


def test_the_clock_moves_by_the_waits_alone(page, monkeypatch):
    waits = Waits(monkeypatch)
    module = SimpleNamespace(time=time)
    waits.clock(monkeypatch, module)
    with waits.counted():
        start = module.time.monotonic()
        time.sleep(0.05)
        apart = threading.Thread(target=time.sleep, args=(0.05,))
        apart.start()
        apart.join()
        assert module.time.monotonic() == pytest.approx(start + 0.05), \
            "only the sleep on this thread moved it"
        page.wait_for_timeout(40)
        with pytest.raises(sync_api.TimeoutError):
            page.locator("#off").click(timeout=100)
        page.evaluate("1 + 1")
        assert module.time.monotonic() == pytest.approx(start + 0.19)
    assert module.time.time() > 1e9, "everything else is the real time module"
