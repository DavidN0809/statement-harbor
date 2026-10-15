"""The wrapper executes real synthetic provider main(), under -P like production."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("state,expected", [("ready", None), ("signedout", "AUTH_REQUIRED"),
                                           ("challenge", "CHALLENGE_REQUIRED")])
def test_existing_provider_entry_point_reports_fixed_stop_state(tmp_path, state, expected):
    script = tmp_path / "fixture_docs.py"
    script.write_text('''
import argparse, json, os
from pathlib import Path
from types import SimpleNamespace
from paperpull_core import browser, storage
from paperpull_core.spec import AppSpec
storage.bind(AppSpec(provider="Synthetic", project_dir=Path(__file__).parent))
site = SimpleNamespace(looks_signed_out=lambda page: os.environ["TEST_STATE"]=="signedout",
    detect_security_challenge=lambda page: "sensitive page words" if os.environ["TEST_STATE"]=="challenge" else None,
    is_safe_url=lambda url: True, dismiss_timeout=lambda page: (_ for _ in ()).throw(AssertionError("keepalive forbidden")))
browser.debug_port_holder=lambda port: "synthetic browser"
def build_parser():
    parser=argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser
def main():
    site.dismiss_timeout(object())
    site.looks_signed_out(object())
    print("PAPERPULL_RUN_RESULT " + json.dumps(dict(new_files=0, failed=0, manual_review=0, validation_failures=0)))
    return 0
''', encoding="utf-8")
    profile = tmp_path / "profiles" / "one"
    (tmp_path / "config.json").write_text(json.dumps({"profile_dir": str(profile),
                                                    "cdp_url": "http://127.0.0.1:9999"}))
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               HARBOR_SCHEDULED="1", HARBOR_EXPECTED_PROFILE=str(profile), TEST_STATE=state,
               HARBOR_ACCOUNT_LOCK=str(tmp_path / "account.lock"))
    env.pop("PAPERPULL_DATA_DIR", None)
    env.pop("PAPERPULL_SERVER", None)
    done = subprocess.run([sys.executable, "-P", "-m", "paperpull_core.automation_runner",
                           str(script), "--all", "--yes"], env=env, capture_output=True, text=True, timeout=15)
    assert done.returncode == (4 if expected else 0), done.stderr
    assert "sensitive page words" not in done.stdout + done.stderr
    assert ("HARBOR_STATE " + expected in done.stdout) if expected else "PAPERPULL_RUN_RESULT" in done.stdout


def test_scheduled_names_exclude_account_fields_and_leave_config_unchanged(tmp_path, monkeypatch):
    from paperpull_core import storage
    config = tmp_path / "config.json"
    original = {"owner": "Private Person", "owner_in_filename": True,
                "filename_pattern": "{account} {summary} {owner}"}
    config.write_text(json.dumps(original))
    monkeypatch.setenv("HARBOR_SCHEDULED", "1")
    cfg = storage.load_config(config)
    name = storage.build_pdf_filename("2026-10-01", "Statement for 123456789", "")
    assert "123456789" not in name and "Private" not in name
    assert not cfg["owner_in_filename"]
    assert json.loads(config.read_text()) == original
