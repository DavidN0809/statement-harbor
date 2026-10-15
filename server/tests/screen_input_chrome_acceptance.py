"""Synthetic clipboard acceptance in a disposable, network-isolated container.

Run with a read-only Chrome binaries volume and repository, never real data,
profiles or settings. The test creates its own X display, HTTP fixture and
Chrome profile. It requires no pytest or external network connection.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from playwright.async_api import async_playwright

from paperpull_core.screen_input import insert_focused_text


HTML = b"""<!doctype html><title>Disposable synthetic sign-in</title>
<form onsubmit="window.submitted++; return false" autocomplete=off>
<input id=ordinary autocomplete=off><input id=password type=password autocomplete=off>
<textarea id=multiline></textarea><button>Submit</button></form>
<p id=noneditable tabindex=0>Not editable</p>
<script>window.submitted=0; window.keys=0;
document.addEventListener('keydown',()=>window.keys++);</script>"""


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *args):
        pass


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def rejected(awaitable, label):
    try:
        await awaitable
    except Exception:
        print(label + ": safely refused", flush=True)
        return
    raise AssertionError(label + ": unexpectedly accepted")


async def cli_paste(root, script, profile, text, expected_code=0):
    """Use the production -P/-m launcher; text travels only through stdin."""
    env = dict(os.environ, PAPERPULL_DATA_DIR=str(root / "provider-data"))
    env["PYTHONPATH"] = str(script.parent) + os.pathsep + env.get("PYTHONPATH", "")
    arguments = [sys.executable, "-P", "-m", "paperpull_core.screen_input",
                 str(script), "primary", str(profile)]
    assert text not in " ".join(arguments), "secret reached command arguments"
    process = await asyncio.create_subprocess_exec(
        *arguments, cwd=script.parent, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, errors = await asyncio.wait_for(process.communicate(text.encode("utf-8")), 12)
        assert process.returncode == expected_code, "CLI returned an unexpected status"
        assert output == b"" and errors == b"", "CLI emitted protocol or error details"
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def exercise_cli(root, page, profile, chrome_url, provider_url, canary):
    template, data = root / "provider-template", root / "provider-data"
    template.mkdir()
    data.mkdir()
    script = template / "synthetic_docs.py"
    script.write_text("import fixture_site as site\n", encoding="utf-8")
    (template / "fixture_site.py").write_text(
        "def is_safe_url(url):\n    return url == " + repr(provider_url) + "\n", encoding="utf-8")
    (data / "config.json").write_text(json.dumps({
        "profile_dir": str(profile), "cdp_url": chrome_url}), encoding="utf-8")
    await page.goto(provider_url)
    for selector, text in [("#password", canary), ("#multiline", canary + "\nCLI second line")]:
        await page.locator(selector).click()
        await cli_paste(root, script, profile, text)
        assert await page.locator(selector).input_value() == text, "CLI insertion content mismatch"
        assert await page.evaluate("window.submitted") == 0, "CLI submitted the form"
        assert await page.evaluate("window.keys") == 0, "CLI simulated key commands"
    print("CLI launcher: exact password and multiline stdin text inserted; output silent", flush=True)
    await page.locator("#password").fill("")
    await cli_paste(root, script, root / "wrong-profile", canary, expected_code=1)
    assert await page.locator("#password").input_value() == "", "CLI profile refusal changed content"
    await page.goto(provider_url + "untrusted")
    await page.locator("#password").click()
    await cli_paste(root, script, profile, canary, expected_code=1)
    assert await page.locator("#password").input_value() == "", "CLI host refusal changed content"
    await page.goto(provider_url)
    await page.locator("#noneditable").focus()
    await cli_paste(root, script, profile, canary, expected_code=1)
    assert await page.locator("#password").input_value() == "", "CLI focus refusal changed content"
    print("CLI refusals: mismatched profile, untrusted URL and noneditable focus exit 1 silently", flush=True)


async def exercise(root, process, chrome_url, provider_url):
    profile = root / "profile"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(chrome_url)
        try:
            context = browser.contexts[0]
            page = context.pages[0]
            await page.goto("chrome://sandbox")
            sandbox = " ".join((await page.inner_text("body")).split())
            assert "Layer 1 Sandbox Namespace" in sandbox, "Chrome namespace sandbox is disabled"
            assert "Seccomp-BPF sandbox Yes" in sandbox, "Chrome seccomp sandbox is disabled"
            print("sandbox: namespace and seccomp active", flush=True)
            await page.goto(provider_url)
            await page.bring_to_front()
            permitted = lambda url: url == provider_url
            canary = "Synthetic-private-canary-725238-雪🔐 \"'\\$&<>"
            for selector, text in [("#ordinary", canary), ("#password", canary),
                                   ("#multiline", canary + "\nsecond line\nthird\tline")]:
                await page.locator(selector).click()
                await insert_focused_text(chrome_url, profile, text, permitted)
                assert await page.locator(selector).input_value() == text, selector + " content mismatch"
                assert await page.evaluate("window.submitted") == 0, "paste submitted the form"
                assert await page.evaluate("window.keys") == 0, "paste simulated command keystrokes"
                print(selector + ": exact text inserted without submission or key events", flush=True)

            await page.locator("#noneditable").focus()
            await rejected(insert_focused_text(chrome_url, profile, canary, permitted), "noneditable field")
            await page.locator("#password").click()
            await rejected(insert_focused_text(chrome_url, root / "wrong-profile", canary, permitted),
                           "wrong browser profile")
            await rejected(insert_focused_text(chrome_url, profile, canary, lambda url: False),
                           "untrusted page URL")
            await page.locator("#password").evaluate("element => element.disabled = true")
            await rejected(insert_focused_text(chrome_url, profile, canary, permitted), "disabled field")
            await page.locator("#password").evaluate("element => {element.disabled=false; element.readOnly=true; element.focus()}")
            await rejected(insert_focused_text(chrome_url, profile, canary, permitted), "readonly field")
            frame_url = provider_url + "frame"
            await page.evaluate("url => {document.body.innerHTML=''; const frame=document.createElement('iframe'); frame.src=url; document.body.append(frame)}", frame_url)
            frame = page.frame_locator("iframe")
            await frame.locator("#password").click()
            await rejected(insert_focused_text(chrome_url, profile, canary, permitted), "untrusted embedded frame")
            await insert_focused_text(chrome_url, profile, canary,
                                      lambda url: url in {provider_url, frame_url})
            assert await frame.locator("#password").input_value() == canary, "trusted frame content mismatch"
            print("trusted embedded frame: exact password inserted", flush=True)
            await exercise_cli(root, page, profile, chrome_url, provider_url, canary)
        finally:
            try:
                session = await browser.new_browser_cdp_session()
                await session.send("Browser.close")
            except Exception:
                pass
        process.wait(timeout=10)
        for path in root.rglob("*"):
            if path.is_file():
                assert b"Synthetic-private-canary-725238" not in path.read_bytes(), "secret reached a persistent file"
        print("privacy: synthetic paste absent from persistent files", flush=True)


def main():
    root = Path(tempfile.mkdtemp(prefix="harbor-paste-acceptance-"))
    display, chrome = None, None
    fixture = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    try:
        os.environ["DISPLAY"] = ":98"
        with (root / "xvfb.log").open("wb") as log:
            display = subprocess.Popen(["Xvfb", ":98", "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
                                       stdout=log, stderr=log)
        for _ in range(80):
            if Path("/tmp/.X11-unix/X98").exists():
                break
            time.sleep(0.1)
        assert display.poll() is None, "isolated X display did not start"
        profile = root / "profile"
        chrome_port = port()
        with (root / "chrome.log").open("wb") as log:
            chrome = subprocess.Popen([
                "/usr/bin/google-chrome-stable", "--user-data-dir=" + str(profile),
                "--remote-debugging-port=" + str(chrome_port), "--no-first-run",
                "--no-default-browser-check", "about:blank"], stdout=log, stderr=log)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", chrome_port), timeout=0.1):
                    break
            except OSError:
                if chrome.poll() is not None:
                    raise AssertionError("isolated Chrome did not start")
                time.sleep(0.1)
        asyncio.run(exercise(root, chrome, "http://127.0.0.1:" + str(chrome_port),
                             "http://127.0.0.1:%d/" % fixture.server_address[1]))
    finally:
        fixture.shutdown()
        fixture.server_close()
        for process in (chrome, display):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
