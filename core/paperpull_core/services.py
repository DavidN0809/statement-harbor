"""Explicitly configured homelab services. Never accepts URLs from mail or PDFs."""
from __future__ import annotations

import json
import os
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler


def configuration():
    path = Path(os.environ.get("HARBOR_INTEGRATIONS") or
                str(Path(os.environ.get("PAPERPULL_CONFIG") or "/config") / "integrations.json"))
    if not path.is_file():
        return {}
    if path.stat().st_size > 262144:
        raise ValueError("integration configuration too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid integration configuration")
    return value


def secret(path):
    path = Path(path)
    if path.stat().st_size > 8192:
        raise ValueError("invalid secret")
    value = path.read_text(encoding="utf-8").strip()
    if not value or len(value) > 8192 or any(c in value for c in "\r\n\0"):
        raise ValueError("invalid secret")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Service:
    def __init__(self, config, scheme="Token"):
        self.base = config["url"].rstrip("/")
        parsed = urlsplit(self.base)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {"", "/"}):
            raise ValueError("service URL must be an explicit origin")
        if parsed.scheme == "http" and config.get("allow_private_http") is not True:
            raise ValueError("HTTP requires explicit private-network opt-in")
        self.token = secret(config["token_file"])
        self.scheme = scheme
        # Ignore proxy environment, preserve TLS verification, reject redirects.
        context = ssl.create_default_context(cafile=config.get("ca_file"))
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))

    def request(self, path, method="GET", data=None, content_type="application/json", binary=False):
        if not re.fullmatch(r"/api/[A-Za-z0-9_/?=&.%+-]+", path) or ".." in path:
            raise ValueError("invalid service API path")
        headers = {"Authorization": self.scheme + " " + self.token,
                   "Accept": "application/json; version=9", "Content-Type": content_type}
        request = Request(self.base + path, data=data, headers=headers, method=method)
        with self.opener.open(request, timeout=30) as response:
            maximum = 64 * 1024 * 1024 if binary else 2 * 1024 * 1024
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError("service response too large")
            return raw if binary else json.loads(raw)

    def json(self, path, value):
        return self.request(path, "POST", json.dumps(value).encode())
