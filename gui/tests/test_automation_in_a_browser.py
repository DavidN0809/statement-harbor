"""Dashboard interactions against a real local server, entirely synthetic."""
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as panel
import server_mode


def test_dashboard_schedule_controls_and_intervention_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(panel, "discover_apps", lambda: {"Synthetic Bank": {
        "accounts": ["primary", "second"], "runnable": True}})
    server_mode.set_password("synthetic browser test passphrase")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(panel.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        store = panel.app.state.automation
        store.put("Synthetic Bank", "primary", enabled=True)
        store.finish("Synthetic Bank", "primary", "CHALLENGE_REQUIRED")
        base = "http://127.0.0.1:" + str(port)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + "/login")
                page.locator("#password").fill("synthetic browser test passphrase")
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.wait_for_url(base + "/")
                page.goto(base + "/automation")
                page.wait_for_function("document.getElementById('rows').children.length === 1")
                assert "Complete MFA" in page.locator("#attention").inner_text()
                assert "CHALLENGE_REQUIRED" in page.locator("#events").inner_text()
                page.locator("#account").select_option("second")
                page.locator("#frequency").select_option("0 9 * * 1")
                assert page.locator("#cron").input_value() == "0 9 * * 1"
                page.locator("#enabled").check()
                with page.expect_response("**/api/automation/schedule") as response:
                    page.get_by_role("button", name="Save account", exact=True).click()
                assert response.value.status == 200
                page.wait_for_function("document.getElementById('rows').children.length === 2")
                assert store.rows()[1]["cron"] == "0 9 * * 1"
                with page.expect_response("**/api/automation/provider"):
                    page.get_by_role("button", name="Disable provider", exact=True).first.click()
                page.wait_for_function("document.querySelectorAll('#rows button').length > 0 && [...document.querySelectorAll('#rows button')].some(b => b.textContent === 'Enable provider')")
                assert all(not row["provider_enabled"] for row in store.rows())
                page.locator("#rules").fill('[{"start":"2026-01-01","cycle":"quarterly"}]')
                with page.expect_response("**/api/automation/expectations") as saved:
                    page.get_by_role("button", name="Save expectations", exact=True).click()
                assert saved.value.status == 200
                page.locator("#rules").fill('[]')
                page.locator("#loadRules").click()
                assert 'quarterly' in page.locator("#rules").input_value()
                assert page.locator("#pendingProviders").count() == 0
                assert not errors, errors
                output = Path(__file__).resolve().parents[2] / "test-output"
                output.mkdir(exist_ok=True)
                page.screenshot(path=str(output / "automation.png"), full_page=True)
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(10)
        server_mode._SESSIONS.clear()
