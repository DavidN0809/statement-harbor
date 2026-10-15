"""Transient user-directed text insertion; never a credential store or login bot."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import runpy
import sys
from urllib.parse import urlsplit

MAX_BYTES = 16384


def validate_text(text):
    if not isinstance(text, str) or not text or "\0" in text or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("invalid paste")
    return text


def profile_process(profile, port):
    """Bind the loopback endpoint to the selected persistent Linux profile."""
    profile = Path(profile).resolve()
    lock = os.readlink(profile / "SingletonLock")
    pid = int(lock.rsplit("-", 1)[1])
    arguments = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    expected = ("--user-data-dir=" + str(profile)).encode()
    debug = ("--remote-debugging-port=" + str(port)).encode()
    if expected not in arguments or debug not in arguments:
        raise ValueError("browser profile mismatch")
    return pid


EDITABLE_FOCUS = """() => {
  if (!document.hasFocus()) return false;
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el || el.disabled || el.readOnly) return false;
  return el.tagName === 'TEXTAREA' || el.isContentEditable ||
    (el.tagName === 'INPUT' && ['text','password','email','search','tel','url','number'].includes(el.type));
}"""


async def insert_focused_text(cdp_url, expected_profile, text, is_safe_url):
    validate_text(text)
    endpoint = urlsplit(cdp_url)
    if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}
            or endpoint.username or endpoint.password or endpoint.path not in {"", "/"}
            or endpoint.query or endpoint.fragment or not endpoint.port):
        raise ValueError("invalid browser endpoint")
    pid = profile_process(expected_profile, endpoint.port)
    from playwright.async_api import async_playwright
    # Stopping Playwright disconnects the driver. Never close the user's browser,
    # focus a tab, navigate, inspect field values, or submit a form.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            "http://127.0.0.1:" + str(endpoint.port), timeout=3000)
        candidates = []
        for context in browser.contexts:
            for page in context.pages:
                if not is_safe_url(page.url):
                    continue
                for frame in page.frames:
                    if not is_safe_url(frame.url):
                        continue
                    try:
                        if await frame.evaluate(EDITABLE_FOCUS):
                            candidates.append((context, page, frame))
                    except Exception:
                        continue
        if len(candidates) != 1:
            raise ValueError("focus one editable field")
        context, page, frame = candidates[0]
        if (profile_process(expected_profile, endpoint.port) != pid
                or not is_safe_url(page.url) or not is_safe_url(frame.url)
                or not await frame.evaluate(EDITABLE_FOCUS)):
            raise ValueError("browser focus changed")
        session = await context.new_cdp_session(page)
        try:
            await session.send("Input.insertText", {"text": text})
        finally:
            await session.detach()


def main():
    # All command-line arguments are image-owned paths/account aliases. The
    # sensitive text arrives only over stdin and no diagnostic is emitted.
    logging.disable(logging.CRITICAL)
    script, account, expected = sys.argv[1:]
    module = runpy.run_path(script, run_name="__harbor_screen_input__")
    site = module.get("site")
    safe = getattr(site, "is_safe_url", None)
    if not callable(safe):
        return 1
    root = Path(os.environ["PAPERPULL_DATA_DIR"])
    config_file = root / ("config.json" if account == "primary" else "config." + account + ".json")
    config = json.loads(config_file.read_text(encoding="utf-8"))
    if Path(config["profile_dir"]).resolve() != Path(expected).resolve():
        return 1
    text = sys.stdin.buffer.read(MAX_BYTES + 1).decode("utf-8")
    asyncio.run(asyncio.wait_for(insert_focused_text(config["cdp_url"], expected, text, safe), 8))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Never traceback an input operation; protocol messages can contain text.
        raise SystemExit(1) from None
