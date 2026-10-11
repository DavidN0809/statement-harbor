"""Browser setup and the host guard, against nothing but invented values."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optum_docs as docs
import optum_site as site


@pytest.mark.parametrize("url", [
    "http://account.optumbank.com/", "https://account.optumbank.com.example.org/",
    "https://account.optumbank.com" + "@" + "evil.example/",
    "https://account.optumbank.com:444/", "https://optumbank.com/", "file:///example"])
def test_off_host_requests_are_refused(url):
    assert not site.is_safe_url(url)


def _open_browser(tmp_path, monkeypatch, config):
    profile = tmp_path / "provider-profile"
    config["profile_dir"] = str(profile)
    captured = []
    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser",
                        lambda *a, **kw: captured.append((a, kw)) or "synthetic browser")
    app = docs.App.__new__(docs.App)
    app.config = config
    app.cmd_open_browser()
    args, kwargs = captured[0]
    assert args[0] == str(profile)
    assert kwargs["mode"] == "auto"
    assert site.is_safe_url(args[2])
    return str(args[1])


def test_open_browser_uses_its_own_profile_and_port(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    assert config["profile_dir"] == "./browser-profile"
    assert config["cdp_url"] == "http://127.0.0.1:9285"
    assert _open_browser(tmp_path, monkeypatch, config) == "9285"


def test_a_config_without_an_address_still_opens_on_its_own_port(tmp_path, monkeypatch):
    """9283 is Nelnet's and 9284 Interactive Brokers'. A config that names
    no address opens Optum's own port, never another app's."""
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    del config["cdp_url"]
    assert _open_browser(tmp_path, monkeypatch, config) == "9285"
