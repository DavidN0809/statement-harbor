"""Run an existing trusted provider engine with noninteractive stop signals.

This is an entry point, not another scraper. It wraps the provider's existing
session detectors so its own navigation and download safeguards stay intact.
"""
from __future__ import annotations

import runpy
import sys
import os
from pathlib import Path
from urllib.parse import urlsplit

PREFIX = "HARBOR_STATE "


class RateWatch:
    def __init__(self, allowed):
        self.allowed = allowed
        self.limited = False

    def observe(self, response):
        # Observe status and host only, never response bodies or headers.
        if response.status == 429 and self.allowed(response.url):
            self.limited = True

    def check(self):
        if self.limited:
            stop("RATE_LIMITED")


def stop(state):
    print(PREFIX + state, flush=True)
    raise SystemExit(4)


def guard_site(site):
    # Fail closed for a provider lacking a known noninteractive session contract.
    if not all(callable(getattr(site, key, None)) for key in
               ("looks_signed_out", "detect_security_challenge", "is_safe_url")):
        stop("PAUSED")
    signed_out = site.looks_signed_out
    challenge = site.detect_security_challenge
    safe_url = site.is_safe_url
    rate = RateWatch(safe_url)

    def check_challenge(page, *args, **kwargs):
        rate.check()
        if challenge(page, *args, **kwargs):
            stop("CHALLENGE_REQUIRED")
        return None

    def check_auth(page, *args, **kwargs):
        check_challenge(page)
        if signed_out(page, *args, **kwargs):
            stop("AUTH_REQUIRED")
        return False

    site.detect_security_challenge = check_challenge
    site.looks_signed_out = check_auth
    def checked_url(url, *args, **kwargs):
        rate.check()
        return safe_url(url, *args, **kwargs)
    site.is_safe_url = checked_url
    # These upstream helpers extend inactivity sessions. Scheduled work never
    # presses them, even though a supervised upstream run may do so.
    if hasattr(site, "dismiss_timeout"):
        site.dismiss_timeout = lambda page: None
    return rate


def run_provider():
    script, *flags = sys.argv[1:]
    # The panel supplies an absolute image path with -P and a trusted PYTHONPATH.
    sys.argv = [script, *flags]
    module = runpy.run_path(script, run_name="__harbor_provider__")
    if not callable(module.get("build_parser")) or not callable(module.get("main")):
        stop("PAUSED")
    site = module.get("site")
    rate = guard_site(site)
    provider = module.get("App")
    if callable(getattr(provider, "browser", None)):
        browser_method = provider.browser
        seen = set()
        def observed_browser(self, *args, **kwargs):
            context = browser_method(self, *args, **kwargs)
            if id(context) not in seen and hasattr(context, "on"):
                context.on("response", rate.observe)
                seen.add(id(context))
            return context
        provider.browser = observed_browser
    # Scheduled output is consumed as counts/enums, never kept as raw logs.
    import logging
    logging.disable(logging.CRITICAL)
    if hasattr(module.get("App"), "_setup_logging"):
        module["App"]._setup_logging = lambda self: None
    from . import browser, storage
    args = module["build_parser"]().parse_args(flags)
    config = storage.load_config(getattr(args, "config", None))
    expected = os.environ.get("HARBOR_EXPECTED_PROFILE")
    if not expected or Path(config["profile_dir"]).resolve() != Path(expected).resolve():
        stop("PAUSED")
    cdp = urlsplit(config.get("cdp_url") or "")
    if cdp.scheme != "http" or cdp.hostname not in {"127.0.0.1", "localhost"} or not cdp.port:
        stop("PAUSED")
    # Restore the existing profile without opening an authentication endpoint.
    # Never use open_signin_browser on a held port: that opens a login tab.
    if not browser.debug_port_holder(str(cdp.port)):
        if not browser.open_signin_browser(config["profile_dir"], str(cdp.port), "about:blank",
                                           mode=config.get("browser", "auto"), allow_fetch=False):
            stop("AUTH_REQUIRED")
    try:
        return module["main"]()
    finally:
        rate.check()


def main():
    from .process_lock import ProcessLock
    path = os.environ.get("HARBOR_ACCOUNT_LOCK")
    if not path:
        stop("PAUSED")
    try:
        lock = ProcessLock(path)
    except (OSError, RuntimeError):
        stop("PAUSED")
    with lock:
        return run_provider()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
