"""What the desktop opens a folder for, PaperPull Server hands the browser.

Two places in the panel showed a folder on the desktop and nothing on the
server, whose folders are on the server and not on the computer the panel
is used from.

  A support report or a recording says to attach its file to an issue.
  /api/diagnostics/download gives the browser the survey Diagnose wrote,
  or the recording, from the last hour, the way the failure file is given.
  A screenshot is never among them, since it is a picture of the page.

  A run that sets documents aside says they are in the Manual Review
  folder. /api/aside/download gives the browser what is in it, as one zip.

On the server the data folder is usually a share others can write to, so
neither follows a link, and neither takes a path from the page, only the
app, the account and, for a report, which of the two. Both answer only on
the server. Every name here is invented.
"""
import asyncio
import io
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]
PDF = b"%PDF-1.4\n% invented\n%%EOF\n"


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """A provider on the server with two people, each with a folder."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    install = tmp_path / "data" / "Shop Receipts"
    install.mkdir(parents=True)
    (install / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    (install / "config.robin.json").write_text('{"output_dir": "robin"}', encoding="utf-8")
    meta = {"name": "Shop Receipts", "dir": str(install), "accounts": ["primary", "robin"]}
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"Shop Receipts": meta})
    return install


def asked(fn, **query):
    """(status, response) for one call of a route."""
    try:
        return 200, fn(**query)
    except fastapi.HTTPException as e:
        return e.status_code, str(e.detail)


def named(response) -> str:
    """The file name the browser is told, in either of the forms it takes."""
    told = response.headers["content-disposition"]
    if "filename*=utf-8''" in told:
        return urllib.parse.unquote(told.split("filename*=utf-8''", 1)[1])
    return told.split('filename="', 1)[1].rstrip('"')


def body_of(response) -> bytes:
    data = Path(response.path).read_bytes()
    if response.background is not None:
        asyncio.run(response.background())
    return data


def written(folder: Path, name: str, data: bytes = b"{}", age: float = 0) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    if age:
        then = time.time() - age
        os.utime(path, (then, then))
    return path


def can_link(tmp_path) -> bool:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path)
        return True
    except (OSError, NotImplementedError):
        return False


# -- a support report or a recording ------------------------------------------------

def test_the_newest_survey_from_the_last_hour_is_given(shop):
    diag = shop / "Diagnostics"
    written(diag, "survey-diagnose-20260101-090000.json", b'{"old": 1}', age=7200)
    written(diag, "survey-diagnose-20260101-100000.json", b'{"new": 1}')
    written(diag, "diagnose-documents.json", b'{"detailed": 1}')
    written(diag, "diagnose-page.png", b"picture")
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        action="diagnose")
    assert status == 200, got
    assert Path(got.path).name == "survey-diagnose-20260101-100000.json"
    assert body_of(got) == b'{"new": 1}'


def test_a_recording_from_the_last_hour_is_given_and_an_older_one_is_not(shop):
    diag = shop / "Diagnostics"
    written(diag, "recording.json", b'{"steps": []}')
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        action="record")
    assert status == 200 and Path(got.path).name == "recording.json"
    written(diag, "recording.json", b'{"steps": []}', age=7200)
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      action="record")
    assert status == 404


def test_a_second_persons_report_is_their_own(shop):
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json", b'{"first": 1}')
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      account="robin", action="diagnose")
    assert status == 404, "the first person's survey is not the second's"
    written(shop / "robin" / "Diagnostics", "survey-diagnose-20260101-100000.json",
            b'{"robin": 1}')
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        account="robin", action="diagnose")
    assert status == 200 and body_of(got) == b'{"robin": 1}'


@pytest.mark.parametrize("query,code", [
    ({"app": "Shop Receipts", "action": "screenshot"}, 400),
    ({"app": "Shop Receipts", "action": ""}, 400),
    ({"app": "Nobody", "action": "diagnose"}, 404),
    ({"app": "Shop Receipts", "account": "stranger", "action": "diagnose"}, 404),
])
def test_a_report_asked_wrongly_is_refused(shop, query, code):
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json")
    assert asked(app_module.api_diagnostics_download, **query)[0] == code


def test_a_linked_survey_is_not_given(shop, tmp_path):
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles", "Cookies", b"signed in")
    (shop / "Diagnostics").mkdir()
    (shop / "Diagnostics" / "survey-diagnose-20260101-100000.json").symlink_to(secret)
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      action="diagnose")
    assert status == 404


# -- what was set aside --------------------------------------------------------------

def test_what_was_set_aside_comes_as_one_zip_and_its_folder_goes(shop):
    aside = shop / "Manual Review"
    written(aside, "2026-05-14 Shop Unsure Receipt.pdf", PDF)
    written(aside / "Invoices", "2026-05-14 Shop Invoice (1 of 2).pdf", PDF + b"2")
    written(aside, ".2026-05-14 Shop Half.pdf.part", b"half")
    written(shop / "Online", "2026-05-14 Shop Filed Receipt.pdf", PDF)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200, got
    assert got.media_type == "application/zip"
    assert named(got) == "Shop Receipts set aside.zip"
    folder = Path(got.path).parent
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert sorted(z.namelist()) == [
            "Manual Review/2026-05-14 Shop Unsure Receipt.pdf",
            "Manual Review/Invoices/2026-05-14 Shop Invoice (1 of 2).pdf"]
        assert z.read("Manual Review/2026-05-14 Shop Unsure Receipt.pdf") == PDF
    assert not folder.exists(), "the zip is made for one answer and removed after it"


def test_nothing_set_aside_is_said(shop):
    (shop / "Manual Review").mkdir()
    status, detail = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 404 and detail == "Nothing is set aside for this account now."


def test_a_second_persons_set_aside_is_their_own(shop):
    written(shop / "Manual Review", "first.pdf", PDF)
    written(shop / "robin" / "Manual Review", "robin.pdf", PDF)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts", account="robin")
    assert status == 200
    assert named(got) == "Shop Receipts robin set aside.zip"
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/robin.pdf"]


def test_links_in_the_set_aside_folder_are_left_out(shop, tmp_path):
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles" / "Default", "Cookies", b"signed in")
    aside = shop / "Manual Review"
    written(aside, "real.pdf", PDF)
    (aside / "cookies.pdf").symlink_to(secret)
    (aside / "profile").symlink_to(secret.parent, target_is_directory=True)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/real.pdf"]
        assert all(b"signed in" not in z.read(n) for n in z.namelist())


@pytest.mark.parametrize("query", [{"app": "Nobody"},
                                   {"app": "Shop Receipts", "account": "stranger"}])
def test_set_aside_asked_wrongly_is_refused(shop, query):
    written(shop / "Manual Review", "real.pdf", PDF)
    assert asked(app_module.api_aside_download, **query)[0] == 404


# -- only the server -----------------------------------------------------------------

def test_neither_answers_on_the_desktop(shop, monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER")
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json")
    written(shop / "Manual Review", "real.pdf", PDF)
    assert asked(app_module.api_diagnostics_download, app="Shop Receipts",
                 action="diagnose")[0] == 404
    assert asked(app_module.api_aside_download, app="Shop Receipts")[0] == 404


def test_the_page_offers_them_on_the_server_and_a_folder_on_the_desktop():
    script = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "(SERVER ? '<button type=\"button\" class=\"btn btn-s\" data-do=\"report-download\"" in script
    assert "const aside = SERVER && o.aside;" in script
    assert "const folder = !SERVER && !inSample() && (o.aside || !o.names);" in script
    assert "'/api/diagnostics/download?'" in script and "'/api/aside/download?'" in script
