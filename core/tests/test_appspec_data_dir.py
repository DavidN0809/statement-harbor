"""On PaperPull Server the data anchor is the /data install, not the code.

AppSpec.project_dir is the app's data folder. On the desktop the code and
the data sit together, so it stays where the app declared. On the server
the code is loaded from the read-only image and only the data lives in the
writable /data share, so AppSpec repoints project_dir to PAPERPULL_DATA_DIR
when PAPERPULL_SERVER is on. These tests pin that behavior, which is what
keeps config, rules and output resolving to /data after the code moved to
the image.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperpull_core.spec import AppSpec, DOCUMENT


def _spec(project_dir):
    return AppSpec(provider="Testco", project_dir=project_dir, kind=DOCUMENT)


def test_server_repoints_project_dir_to_the_data_folder(tmp_path, monkeypatch):
    code = tmp_path / "image" / "templates" / "apps" / "testco"
    data = tmp_path / "data" / "Testco Statements"
    code.mkdir(parents=True)
    data.mkdir(parents=True)
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_DATA_DIR", str(data))
    sp = _spec(code)
    assert sp.project_dir == data
    assert sp.rules_path is None
    # Config, rules and the profile default all read project_dir, so they
    # follow to /data with no further change.


def test_desktop_leaves_project_dir_where_the_app_declared(tmp_path, monkeypatch):
    here = tmp_path / "Chase Statements"
    here.mkdir()
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setenv("PAPERPULL_DATA_DIR", str(tmp_path / "elsewhere"))
    sp = _spec(here)
    assert sp.project_dir == here


def test_server_without_a_data_dir_changes_nothing(tmp_path, monkeypatch):
    here = tmp_path / "Chase Statements"
    here.mkdir()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.delenv("PAPERPULL_DATA_DIR", raising=False)
    sp = _spec(here)
    assert sp.project_dir == here


def test_an_empty_data_dir_is_ignored(tmp_path, monkeypatch):
    here = tmp_path / "Chase Statements"
    here.mkdir()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_DATA_DIR", "")
    sp = _spec(here)
    assert sp.project_dir == here
