"""Capital One and Schwab take each document as the one its record names.

Both keep a document under its account, type, title and date, and tell two
documents sharing all four apart by their place in the provider's list,
since their ids are opaque (Schwab's README says not stable). Each download
lists that day again and takes whatever stands in the record's place.

When the provider lists such documents in another order, or lists a new one
ahead of one already saved, the place no longer names the same document.
One document was saved twice under two records and the other never, and
since both records then say saved, no later run took it.

Each app here runs through its own main, as the panel runs it, with a
made-up config and output folder. Only what the provider answers is stood
in, the list it gives in the order it gives it and a PDF for an id, each
PDF carrying the id of the document it is.
"""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import storage as core_storage

REPO = Path(__file__).resolve().parents[2]
DATE = "2026-09-12"
PAGE = SimpleNamespace(url="about:blank")


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(app.name + "_docs")
    finally:
        sys.path.pop(0)


def pdf_of(document_id: str) -> bytes:
    """A PDF that opens, with a page, carrying which document it is."""
    import io

    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "document %s" % document_id})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def whose(body: bytes) -> str:
    """The id of the document whose PDF this is."""
    return body.split(b"(document ", 1)[1].split(b")", 1)[0].decode()


class Provider:
    """The list in the order the provider gives it, and a PDF for an id.
    A document in `refused` answers an error, and taking one in `stop_at`
    stops the run there, as Stop does. `days` gives a document a day of its
    own, DATE otherwise.

    With `lasting` False the provider hands each document a new id in each
    session (`new_session`), and an id from an earlier session is refused,
    the way Schwab's README says its ids are not stable."""

    def __init__(self):
        self.ids = []
        self.refused = set()
        self.stop_at = set()
        self.asked = []
        self.days = {}
        self.lasting = True
        self.session = 1

    def new_session(self):
        self.session += 1

    def id_of(self, document: str) -> str:
        return document if self.lasting else "%sV%d" % (document, self.session)

    def day_of(self, document: str) -> str:
        return self.days.get(document, DATE)

    def listed(self):
        return [(self.id_of(document), self.day_of(document)) for document in self.ids]

    def pdf(self, document_id: str):
        self.asked.append(document_id)
        document = document_id if self.lasting else document_id.split("V")[0]
        if document_id != self.id_of(document):
            return 404, b""
        if document in self.stop_at:
            raise KeyboardInterrupt
        if document in self.refused:
            return 500, b""
        return 200, pdf_of(document)


class CapitalOne(Provider):
    """A bank account's statements of one day."""

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_documents", lambda page: True)
        monkeypatch.setattr(site, "_fetch_json", self._json)
        monkeypatch.setattr(site, "fetch_pdf",
                            lambda page, doc_type, ref, rec: self.pdf(rec["document_id"]))

    def _json(self, page, url, headers, body=None):
        listed = []
        if url == self.site.API["search"]:
            listed = [{"documentId": i, "documentType": self.site.TYPE_BANK_STATEMENT,
                       "documentCategory": "STATEMENT", "documentName": "Monthly Statement",
                       "documentDate": day, "description": "360 Checking...1111",
                       "account": {"accountReferenceId": "REF1111"}}
                      for i, day in self.listed()]
        return {"status": 200, "body": {"documents": listed}}


class Schwab(Provider):
    """A brokerage account's trade confirmations of one day, two buys of
    one fund."""

    def __init__(self, site, monkeypatch):
        super().__init__()
        self.site = site
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "_gateway_call", self._call)
        monkeypatch.setattr(site, "fetch_pdf", lambda page, doc: self.pdf(doc["documentId"]))

    def _call(self, page, url, headers, post_body=None):
        if url == self.site.API["accounts"]:
            body = {"accountSelectorData": {"brokerageAccountList": {"brokerageAccounts": [
                {"id": "11111111", "nickName": "Brokerage"}]}}}
        else:
            body = {"documents": [
                {"documentId": i, "documentName": "Confirm - EXAMPLE - Bought",
                 "type": self.site.TYPE_CONFIRMS, "onDemandDocumentType": "TradeConfirms",
                 "date": "%s/%s/%s" % (day[5:7], day[8:], day[:4]),
                 "accountDisplayName": "1111-1111"} for i, day in self.listed()]}
        return {"status": 200, "body": body}


PROVIDERS = {"capitalone": CapitalOne, "schwab": Schwab}
APPS = [REPO / "apps" / name for name in PROVIDERS]


class Home:
    """One app with a made-up config and output folder, run through its own
    main, and what the provider answers it."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch, capsys):
        for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        config = json.loads((app / "config.example.json").read_text(encoding="utf-8"))
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
        })
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.out = Path(config["output_dir"])
        monkeypatch.setattr(self.mod.App, "page", lambda app: PAGE)
        monkeypatch.setattr(self.mod.App, "_on_its_site", lambda app: PAGE)
        monkeypatch.setattr(self.mod.App, "check_session", lambda app, *_a, **_kw: None)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        self.provider = PROVIDERS[app.name](self.mod.site, monkeypatch)

    def run(self, *flags) -> str:
        """The app's own main, as the panel starts it, and what it said."""
        self.capsys.readouterr()
        self.mod.main(["--config", str(self.cfg), *flags])
        return " ".join(self.capsys.readouterr().out.split())

    def run_all(self, *flags) -> str:
        return self.run("--all", "--yes", *flags)

    def on_disk(self) -> list:
        """Whose PDF each file under the output folder holds."""
        return sorted(whose(p.read_bytes()) for p in self.out.rglob("*.pdf"))

    def held(self) -> dict:
        """Whose PDF each saved record's file holds, by key."""
        progress = json.loads((self.out / "progress.json").read_text(encoding="utf-8"))
        return {key: whose(Path(rec["pdf_path"]).read_bytes())
                for key, rec in sorted(progress.items())
                if isinstance(rec, dict) and rec.get("downloaded_ok")}

    def left_for_a_person(self) -> dict:
        """The notes of every record marked for manual review, by key."""
        progress = json.loads((self.out / "progress.json").read_text(encoding="utf-8"))
        return {key: rec.get("notes", "") for key, rec in sorted(progress.items())
                if isinstance(rec, dict) and rec.get("state") == "Needs Manual Review"}


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


each_app = pytest.mark.parametrize("home", APPS, ids=list(PROVIDERS), indirect=True)


@each_app
def test_a_document_listed_first_beside_one_already_saved_is_downloaded(home):
    """A second document of one day, type, title and account, listed ahead
    of the one already saved, took the saved one's place, so the saved one
    was taken again as the new one and the new one never at all."""
    home.provider.ids = ["ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_a_document_that_failed_is_the_one_taken_again(home):
    """The second of two documents failed. Listed the other way around the
    next time, the run took the first one again in its place."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.refused = set()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_resume_takes_the_document_the_run_stopped_at(home):
    """Stopped before the second of two documents, Resume lists nothing of
    its own and took whatever stood in the second place on the day it ran."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.stop_at = set()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()


@each_app
def test_download_again_takes_each_record_its_own_document(home):
    """Download again after a listing in the other order took each record's
    place afresh, so each record's new file held the other document. Both
    came back, since Download again saves beside a file and takes both, but
    a Pilot count that takes only the first leaves both records on the
    second document and the first one's earlier file held by no record."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    before = home.held()
    assert sorted(before.values()) == ["ST0001", "ST0002"]

    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all("--redownload", "--year", DATE[:4])
    assert home.held() == before


@each_app
def test_an_id_kept_for_a_document_is_never_another_documents(home):
    """When the list no longer has a record's place, the download falls back
    to the id the record keeps. A listing in the other order had written the
    first document's id over the second's, so the second's record took the
    first document."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    home.provider.ids = ["ST0002", "ST0001"]
    home.provider.refused = {"ST0001", "ST0002"}
    home.run_all()
    assert home.on_disk() == ["ST0001"]

    home.provider.refused = set()
    home.provider.ids = ["ST0001"]
    home.run("--resume")
    saved = home.on_disk()
    assert len(set(saved)) == len(saved), home.held()


@each_app
def test_a_document_listed_in_place_of_one_saved_is_downloaded_when_ids_last(home):
    """A corrected statement listed instead of the one saved, on its day and
    under its title. The ids of the other days' documents came back, which
    says this provider's ids last, so an id no record keeps is a document
    of its own."""
    home.provider.days = {"ST0009": "2026-08-12"}
    home.provider.ids = ["ST0009", "ST0001"]
    home.run_all()
    home.provider.ids = ["ST0009", "ST0002"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002", "ST0009"], home.held()


@each_app
def test_an_archive_whose_ids_a_listing_swapped_takes_neither_document_twice(home):
    """Before this, a listing in the other order wrote each document's id
    over the other's record. Such an archive, the first saved and the second
    failed, is listed again in its first order."""
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()
    found = home.out / "discovery.json"
    discovery = json.loads(found.read_text(encoding="utf-8"))
    first, second = sorted(discovery)
    discovery[first]["document_id"], discovery[second]["document_id"] = "ST0002", "ST0001"
    found.write_text(json.dumps(discovery), encoding="utf-8")

    home.provider.refused = set()
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"], home.held()
    assert home.left_for_a_person() == {}


# -- when the provider's ids do not last -------------------------------------
#
# Schwab's README says its ids are not stable. Here each session hands each
# document a new id and refuses one from an earlier session. A document alone
# on its day is still taken. Two alike, where which one was saved cannot be
# told, are left for a person rather than guessed at.

NOT_TOLD = "does not say which one this is"


@each_app
def test_two_documents_listed_together_are_each_taken_once_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"]

    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001", "ST0002"]
    assert home.left_for_a_person() == {}


@each_app
def test_a_document_alone_on_its_day_is_taken_once_when_its_id_did_not_last(home):
    """Stopped before it, then Resume in a session that lists it under a new
    id, and then a run that lists it under another."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001"]
    home.provider.stop_at = {"ST0001"}
    home.run_all()
    assert home.on_disk() == []

    home.provider.stop_at = set()
    home.provider.new_session()
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    progress = json.loads((home.out / "progress.json").read_text(encoding="utf-8"))
    assert [rec["document_id"] for rec in progress.values()] == [
        home.provider.id_of("ST0001")], "the record keeps an id it was not saved under"
    home.provider.new_session()
    home.run_all()
    assert home.on_disk() == ["ST0001"]


@each_app
def test_a_new_document_beside_one_saved_is_left_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001"]
    home.run_all()

    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    said = home.run_all()
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left
    assert NOT_TOLD in said

    for order in (["ST0001", "ST0002"], ["ST0002", "ST0001"]):
        home.provider.new_session()
        home.provider.ids = order
        home.run_all()
        home.run("--resume")
    assert home.on_disk() == ["ST0001"]


@each_app
def test_a_failed_document_is_left_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.refused = {"ST0002"}
    home.run_all()

    home.provider.refused = set()
    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run_all()
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


@each_app
def test_resume_leaves_a_document_for_a_person_when_ids_do_not_last(home):
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()

    home.provider.stop_at = set()
    home.provider.new_session()
    home.provider.ids = ["ST0002", "ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


@each_app
def test_resume_never_takes_the_one_still_listed_for_the_other_when_ids_do_not_last(home):
    """Two alike, the first saved, Stop before the second. The day's list
    then gives only one of them, under a new id, which is the one saved."""
    home.provider.lasting = False
    home.provider.ids = ["ST0001", "ST0002"]
    home.provider.stop_at = {"ST0002"}
    home.run_all()

    home.provider.stop_at = set()
    home.provider.new_session()
    home.provider.ids = ["ST0001"]
    home.run("--resume")
    assert home.on_disk() == ["ST0001"]
    left = home.left_for_a_person()
    assert len(left) == 1 and NOT_TOLD in next(iter(left.values())), left


# -- the numbering itself ------------------------------------------------------

def test_with_no_id_kept_the_numbers_are_those_an_archive_already_has():
    """told_apart numbers as stable_occurrences does whenever no id decides,
    so every key an archive has stays."""
    from paperpull_core.keys import stable_occurrences, told_apart
    fields = ("doc_type", "title", "date")

    def row(account, document_id="", doc_type="BANK", title="Monthly Statement",
            date=DATE):
        return {"doc_type": doc_type, "title": title, "date": date,
                "account": account, "document_id": document_id}

    def known(*pairs):
        return {"k%d" % i: dict(row(account), occurrence=occurrence)
                for i, (account, occurrence) in enumerate(pairs)}

    cases = [
        ([row("A"), row("B")], {}),
        ([row("B"), row("A")], known(("A", 0), ("B", 1))),
        ([row("A"), row("A"), row("A")], known(("A", 0), ("A", 1))),
        ([row("A", "x1"), row("A", "x2")], known(("A", 0), ("A", 1))),
        ([row("A"), row("B", doc_type="CARD"), row("A", date="2026-08-12")],
         known(("A", 0))),
    ]
    for rows, existing in cases:
        got = [occurrence for occurrence, _sure in told_apart(
            rows, existing, fields=fields, kind_field="doc_type")]
        assert got == stable_occurrences(rows, existing, fields=fields), (rows, existing)
