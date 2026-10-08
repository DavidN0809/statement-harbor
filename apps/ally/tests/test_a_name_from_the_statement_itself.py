"""Rename keeps the name a statement was given from the PDF itself.

Ally describes several statements of one date alike, so once a statement is
downloaded the app reads which accounts it covers, and who it was addressed
to, from the PDF's own first page and renames the file after that
(_name_from_contents). The record of it in the run state says so, but the
listing's record still holds the summary and account the list gave it, and
Rename reads the listing's record over the run state's (renaming._Known,
since 4f171012). So under the very pattern the files were saved by, Rename
offered "2026-09-12 Ally Account Statement - Savings + Checking (Pat
Sample).pdf" the listing's name back, "... Account Statement - Trust.pdf",
and --apply would have taken it. A pattern with {account} took the trust's
name where the download had put the addressee's.

The name from the PDF was also given its own place with nothing to tell it
apart, so a second copy of one statement addressed to one person was saved
" (2)", where a download of it tells it apart by the last of its id, and
Rename then offered it that ending.

And a statement listed without Ally's id is kept under its date, title and
account, so writing the addressee over the account filed its record under
another key, and the next run took it again.

Each statement here is listed by the app's own listing code, downloaded by
its own process and download_one with only Ally's page and the bytes of the
PDF stood in, and renamed by its own Rename with --apply, as the panel runs
it. Every name, number and id is invented.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from paperpull_core import testkit

ROOT = Path(__file__).resolve().parents[3]
ALLY = ROOT / "apps" / "ally"
DATE = "2026-09-12"
TRUST = "PAT SAMPLE TRUST"


def _rename_census():
    """The rename census, for the harness that builds an app as it is at
    home and runs its own Rename."""
    path = ROOT / "core" / "tests" / "test_every_app_renames_each_file_for_its_own_record.py"
    spec = importlib.util.spec_from_file_location("rename_census_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _rename_census()


def listed(app, doc_id="", label="Trust"):
    """One statement as Ally's list gives it, with its id or, as the page's
    rows give it when the list API answers nothing, without one."""
    row = {"date": DATE, "title": "Statement", "account": TRUST}
    if label:
        row["label"] = label
    if doc_id:
        row["documentId"] = doc_id
    return app._record_ally_doc(row)


class Ally:
    """Ally's page and each statement's PDF, stood in. A PDF carries what
    it says about itself, which accounts it covers and who it went to."""

    def __init__(self, home, monkeypatch, says):
        self.home, self.says, self.taken = home, says, []
        site = home.mod.site
        monkeypatch.setattr(site, "ensure_statements", lambda *_a, **_k: True)
        monkeypatch.setattr(site, "ally_download", self.download)
        monkeypatch.setattr(site, "read_statement_facts", self.facts)

    def download(self, page, ctx, account, date, out_path, occurrence=0,
                 document_id="", kind="statement", title=""):
        which = document_id or "occurrence %d" % occurrence
        self.taken.append(which)
        Path(out_path).write_bytes(testkit.text_pdf(["statement " + which]))
        return True

    def facts(self, path):
        text = Path(path).read_bytes()
        for which, (accounts, addressee) in self.says.items():
            if ("statement " + which).encode() in text:
                return self.home.mod.site.StatementFacts(list(accounts), addressee)
        raise AssertionError(path)


def run(home, app):
    """A run of the app over what it has listed, as Resume runs it."""
    page = SimpleNamespace(context=None, url="https://secure.ally.com/")
    app.check_session = lambda *_a, **_k: None
    app._on_its_site = lambda: page
    app.process(app._select())
    app.progress.save()
    app.discovery.save()


def names(home):
    return sorted(p.name for p in home.files().values())


def renamed_nothing(home):
    """The app's own Rename with --apply, and the files as it left them."""
    before = names(home)
    said = home.rename("--apply")
    assert names(home) == before, said
    assert "Every file is already named" in said, said


SAVINGS_AND_CHECKING = [("Savings", "1234"), ("Checking", "5678")]


def test_rename_keeps_the_name_the_pdf_gave(tmp_path, monkeypatch, capsys):
    home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
    app = home.build()
    assert listed(app, "DOCAAAA1111") == 1
    Ally(home, monkeypatch, {"DOCAAAA1111": (SAVINGS_AND_CHECKING, "PAT SAMPLE")})
    run(home, app)
    assert names(home) == [
        "2026-09-12 Ally Account Statement - Savings + Checking (Pat Sample).pdf"]
    renamed_nothing(home)


def test_an_account_pattern_keeps_the_addressee(tmp_path, monkeypatch, capsys):
    home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
    home.set_pattern("{date} {account} {summary}")
    app = home.build()
    assert listed(app, "DOCAAAA1111") == 1
    Ally(home, monkeypatch, {"DOCAAAA1111": (SAVINGS_AND_CHECKING, "PAT SAMPLE")})
    run(home, app)
    [name] = names(home)
    assert "PAT SAMPLE " in name and "TRUST" not in name, name
    renamed_nothing(home)


def test_two_copies_to_one_person_are_told_apart_by_their_ids(
        tmp_path, monkeypatch, capsys):
    home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
    app = home.build()
    assert listed(app, "DOCAAAA1111") == 1
    assert listed(app, "DOCBBBB2222") == 1
    Ally(home, monkeypatch, {"DOCAAAA1111": (SAVINGS_AND_CHECKING, "PAT SAMPLE"),
                             "DOCBBBB2222": (SAVINGS_AND_CHECKING, "PAT SAMPLE")})
    run(home, app)
    named = "2026-09-12 Ally Account Statement - Savings + Checking (Pat Sample)"
    found = names(home)
    assert len(found) == 2 and named + ".pdf" in found, found
    [other] = [n for n in found if n != named + ".pdf"]
    assert other in (named + " AA1111.pdf", named + " BB2222.pdf"), found
    renamed_nothing(home)


def test_a_pdf_naming_what_the_list_said_keeps_its_id_ending(
        tmp_path, monkeypatch, capsys):
    # Two statements of one date for one label, each covering the one
    # account the label names and addressed to nobody it can read, so the
    # PDF gives each the very name the list gave it. The second was told
    # apart by its id when it was saved and is not moved on to " (2)".
    home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
    app = home.build()
    assert listed(app, "DOCAAAA1111") == 1
    assert listed(app, "DOCBBBB2222") == 1
    Ally(home, monkeypatch, {"DOCAAAA1111": ([("Trust", "1234")], ""),
                             "DOCBBBB2222": ([("Trust", "1234")], "")})
    run(home, app)
    named = "2026-09-12 Ally Account Statement - Trust"
    found = names(home)
    assert len(found) == 2 and named + ".pdf" in found, found
    [other] = [n for n in found if n != named + ".pdf"]
    assert other in (named + " AA1111.pdf", named + " BB2222.pdf"), found
    renamed_nothing(home)


def test_a_statement_listed_without_an_id_is_taken_once(
        tmp_path, monkeypatch, capsys):
    home = census.Home(ALLY, tmp_path, monkeypatch, capsys)
    app = home.build()
    assert listed(app) == 1
    keys = set(app.discovery.data)
    ally = Ally(home, monkeypatch, {"occurrence 0": (SAVINGS_AND_CHECKING, "PAT SAMPLE")})
    run(home, app)
    assert ally.taken == ["occurrence 0"]
    assert set(app.discovery.data) == keys
    assert set(app.progress.data) == keys

    # The next run, of the app built afresh from what the first one left.
    run(home, home.build())
    assert ally.taken == ["occurrence 0"], "the statement was taken again"
    renamed_nothing(home)
