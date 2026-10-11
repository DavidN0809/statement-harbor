"""Robinhood Crypto statements are read, and are documents of their own (#62).

The tester's individual investing statements all came down and none of the
Robinhood Crypto ones did. The app read one statements page, the individual
one. The crypto page had been on the list when the app was built and was
taken off only because the account it was built on does not trade crypto.

It is read again, the same way and under the same guards. A crypto
statement can carry the same title as an individual statement of the same
month, and a title and a date were all a key was made of, so the second
would have been taken as done, and its page could be pressed for the first.
A statement now belongs to the account of the page that lists it. The
individual page names no account, so every key and file name saved before
stays exactly as it was, and a crypto statement saved under its old key
when the crypto page was read before still counts as done.

The crypto page is read only as itself, at its own address and after the
individual page, and a document on it with the title and date of an
individual one is refused, and the run says so.

The retirement page, read since #74, is read only at its own address and
only when a heading of its own names a retirement account, since its
statements can share a title and a date with the individual ones and the
list alone cannot say whose they are.

The titles here are invented, in the shape the statement links take.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402  binds this provider's AppSpec
import robinhood_docs  # noqa: E402
import robinhood_site as site  # noqa: E402
from paperpull_core import doc_types  # noqa: E402
from paperpull_core import listing  # noqa: E402
from paperpull_core import storage as core_storage  # noqa: E402

INDIVIDUAL = "https://robinhood.com/account/reports-statements/individual"
RETIREMENT = "https://robinhood.com/account/reports-statements/retirement"
CRYPTO = "https://robinhood.com/account/reports-statements/crypto"
TAX = "https://robinhood.com/account/reports-statements/tax"


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def _app(tmp_path):
    app = object.__new__(robinhood_docs.App)
    app.args = SimpleNamespace(start_date=None, redownload=False)
    app.config = {"document_types": ["Statement", "Tax Document"],
                  "default_start_date": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.rules = doc_types.load_rules()
    app.stats = {"skipped_out_of_scope": 0}
    return app


def _record(app, title, url, date_text=""):
    r = site.RawDoc(title=title, date_text=date_text, text=title)
    app._record_rawdoc(r, url)


def _docs(app):
    return {k: robinhood_docs.Document.from_dict(v) for k, v in app.discovery.data.items()}


def test_the_crypto_statements_page_is_read():
    urls = [u for u, _label in site.document_source_urls()]
    assert urls == [INDIVIDUAL, RETIREMENT, CRYPTO, TAX]
    for u in urls:
        assert site.is_safe_url(u), u
    assert site.account_for(CRYPTO) == "Crypto"
    assert site.account_for(INDIVIDUAL) == ""
    assert site.account_for(TAX) == ""


def test_a_crypto_statement_is_a_document_of_its_own(tmp_path):
    app = _app(tmp_path)
    _record(app, "January 2022 Monthly Statement", INDIVIDUAL, "2022-01-31")
    _record(app, "January 2022 Monthly Statement", CRYPTO, "2022-01-31")
    docs = _docs(app)
    assert len(docs) == 2, "the crypto statement was taken for the individual one"
    by_page = {d.source_url: d for d in docs.values()}
    ind, cry = by_page[INDIVIDUAL], by_page[CRYPTO]
    assert cry.account == "Crypto" and ind.account == ""
    assert cry.summary == "Crypto Monthly Statement"
    assert storage.build_pdf_filename(cry.date, cry.summary, "", record=cry) == \
        "2022-01-31 Robinhood Crypto Monthly Statement.pdf"
    # the download goes to the page that lists it, and nothing on another
    assert cry.source_url == CRYPTO


def test_an_individual_statement_keeps_the_key_and_name_it_always_had(tmp_path):
    """Every statement the individual page has ever given was saved under
    this key and this name. A change to either would fetch all of them
    again beside the copies already saved."""
    app = _app(tmp_path)
    _record(app, "January 2022 Monthly Statement", INDIVIDUAL, "2022-01-31")
    (key, doc), = _docs(app).items()
    # An empty account has always been written into the key as "Unnamed".
    assert key == "Statement:2022-01-31:January 2022 Monthly Statement:Unnamed"
    assert doc.summary == "Monthly Statement"
    assert storage.build_pdf_filename(doc.date, doc.summary, "", record=doc) == \
        "2022-01-31 Robinhood Monthly Statement.pdf"


def test_a_title_that_says_crypto_does_not_say_it_twice(tmp_path):
    app = _app(tmp_path)
    _record(app, "January 2022 Crypto Statement", CRYPTO, "2022-01-31")
    (doc,) = _docs(app).values()
    assert doc.summary == "Crypto Statement"


def test_a_tax_form_a_statements_page_lists_is_the_tax_pages_form(tmp_path):
    """A statements page that also shows a 1099 is showing the tax page's
    form. It keeps that key, so it is one document and not two."""
    app = _app(tmp_path)
    _record(app, "2022 Robinhood Crypto 1099", CRYPTO)
    _record(app, "2022 Robinhood Crypto 1099", TAX)
    docs = _docs(app)
    assert len(docs) == 1
    (doc,) = docs.values()
    assert doc.account == "" and doc.summary == "Crypto 1099 Tax Form"


# -- a crypto statement saved when the crypto page was read before -------------

TITLE = "January 2022 Monthly Statement"


def _legacy(app, source):
    """A statement saved before its account was part of its key."""
    old = robinhood_docs.Document(title=TITLE, category=doc_types.STATEMENT,
                                  summary="Monthly Statement", date="2022-01-31",
                                  source_url=source)
    old.downloaded_ok, old.state = True, "Completed"
    old.pdf_filename = "2022-01-31 Robinhood Monthly Statement.pdf"
    app.progress.update(old.key, old.to_dict())
    app.discovery.update(old.key, old.to_dict())
    return old


def _crypto():
    return robinhood_docs.Document(title=TITLE, category=doc_types.STATEMENT,
                                   summary="Crypto Monthly Statement", date="2022-01-31",
                                   source_url=CRYPTO, account="Crypto")


def test_a_crypto_statement_saved_under_its_old_key_is_done(tmp_path):
    app = _app(tmp_path)
    old = _legacy(app, CRYPTO)
    assert old.key.endswith(":Unnamed")
    assert app._already_done(_crypto())
    # the same key saved from the individual page is not the crypto statement
    app = _app(tmp_path / "individual")
    _legacy(app, INDIVIDUAL)
    assert not app._already_done(_crypto())


def test_discovery_keeps_it_under_its_new_key(tmp_path):
    app = _app(tmp_path)
    old = _legacy(app, CRYPTO)
    _record(app, TITLE, CRYPTO, "2022-01-31")
    rec = app.progress.get(_crypto().key)
    assert rec and rec["downloaded_ok"] and rec["summary"] == "Crypto Monthly Statement"
    assert app.progress.get(old.key) is None
    assert app.discovery.get(old.key) is None, "the old crypto listing would be pressed again"


# -- the crypto page is read only as itself ------------------------------------

class _Tab:
    """A tab that goes where it is sent, unless the site sends it on or the
    page is `broken`, and shows the headings `headings` gives for the
    address it is at."""

    def __init__(self, lands=None, broken=(), headings=None):
        self.url, self.lands, self.broken = "", lands or {}, broken
        self.headings = dict(headings or {})

    def goto(self, url, **kw):
        if url in self.broken:
            raise RuntimeError("could not open")
        self.url = self.lands.get(url, url)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg=None):
        return self.headings.get(self.url) if js == site._HEADINGS_JS else None


def _run(tmp_path, monkeypatch, listings, stops=(), repeated=None, **tab):
    """Discover over made-up pages. `stops` are the pages whose View More
    stops before the end of their list, and `repeated` the titles a page
    shows twice."""
    repeated = dict(repeated or {})
    app = _app(tmp_path)
    app.config.update(delay_min_seconds=0, delay_max_seconds=0)
    app.stats = {"mode": "all", "started": "", "ended": "", "discovered": 0,
                 "statements": 0, "tax_documents": 0, "insurance_documents": 0,
                 "other": 0, "skipped_completed": 0, "skipped_out_of_scope": 0,
                 "manual_review": 0, "failed": 0, "duplicate_filenames": 0,
                 "validation_failures": 0, "dates": [], "new_files": [],
                 "crypto_refused": 0, "wrong_document": 0, "notes": []}
    page = _Tab(**tab)
    app.page = lambda: page
    app.check_session = lambda page: False
    monkeypatch.setattr(site, "collect_download_docs", lambda page, **kw: site.Listed(
        [site.RawDoc(title=t, date_text=d, text=t) for t, d in listings.get(page.url, [])],
        repeated.get(page.url, [])))
    monkeypatch.setattr(site, "expand_all", lambda page: page.url not in stops)
    monkeypatch.setattr(site, "scroll_full_page", lambda page, **kw: None)
    app.cmd_discover(quiet=True)
    return app


def test_a_crypto_page_showing_the_individual_list_is_refused_and_said(tmp_path, monkeypatch):
    same = [(TITLE, "2022-01-31")]
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: same, CRYPTO: same})
    assert [d.account for d in _docs(app).values()] == [""], "saved twice"
    assert app.stats["crypto_refused"] == 1 and app.stats["wrong_document"] == 1
    assert any("crypto statements page were not read" in n for n in app.stats["notes"])
    app.write_run_summary()
    assert "Crypto listings refused:   1" in app.paths.run_summary.read_text(encoding="utf-8")


def test_a_crypto_address_that_opens_elsewhere_is_not_read(tmp_path, monkeypatch):
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: [(TITLE, "2022-01-31")]},
               lands={CRYPTO: "https://robinhood.com/account"})
    assert [d.account for d in _docs(app).values()] == [""]
    assert any("opened another address" in n for n in app.stats["notes"])


def test_the_crypto_page_waits_for_the_individual_one(tmp_path, monkeypatch):
    """It is checked against the individual page, so without that page in
    the same run it is not read."""
    app = _run(tmp_path, monkeypatch, {CRYPTO: [(TITLE, "2022-01-31")]},
               broken=(INDIVIDUAL,))
    assert _docs(app) == {}
    assert any("were not read in this run" in n for n in app.stats["notes"])


# -- the retirement page is read only as itself --------------------------------

def test_a_retirement_page_showing_the_individual_list_is_not_read(tmp_path, monkeypatch):
    """An account without a retirement account can be shown the individual
    list at the retirement address, as the crypto address did, and every
    individual statement would be saved again as a Retirement Monthly
    Statement.
    Nothing in the list says whose it is, and the page's own heading does."""
    same = [(TITLE, "2022-01-31")]
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: same, RETIREMENT: same},
               headings={RETIREMENT: ["Individual investing", "Statements"]})
    assert [d.account for d in _docs(app).values()] == [""], "saved twice"
    assert any("retirement statements page does not name a retirement account" in n
               for n in app.stats["notes"])
    # An account with no retirement account has nothing on that page to
    # list, so the list is not short for it.
    assert listing.last(app) == listing.COMPLETE


def test_a_retirement_page_with_no_heading_of_its_own_is_not_read(tmp_path, monkeypatch):
    for i, headings in enumerate(([], ["Statements"], None)):
        app = _run(tmp_path / str(i), monkeypatch,
                   {INDIVIDUAL: [(TITLE, "2022-01-31")], RETIREMENT: [(TITLE, "2022-01-31")]},
                   headings={RETIREMENT: headings})
        assert [d.account for d in _docs(app).values()] == [""], headings


def test_a_retirement_page_that_names_its_account_is_read(tmp_path, monkeypatch):
    """Its statements can share a title and a date with the individual
    account's and are its own, so they are kept beside them."""
    same = [(TITLE, "2022-01-31")]
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: same, RETIREMENT: same},
               headings={RETIREMENT: ["Retirement", "Traditional IRA"]})
    by_page = {d.source_url: d for d in _docs(app).values()}
    assert sorted(by_page) == [INDIVIDUAL, RETIREMENT]
    assert by_page[RETIREMENT].account == "Retirement"
    assert by_page[RETIREMENT].summary == "Retirement Monthly Statement"
    assert app.stats["crypto_refused"] == 0


def test_a_retirement_page_that_shows_a_title_twice_is_not_read(tmp_path, monkeypatch):
    """Two IRAs can each list a statement of the same month under one
    title, and the second would be dropped as the first without a word."""
    same = [(TITLE, "2022-01-31")]
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: same, RETIREMENT: same},
               repeated={RETIREMENT: [TITLE]}, headings={RETIREMENT: ["Retirement"]})
    assert [d.account for d in _docs(app).values()] == [""], "one IRA's statements were kept"
    assert any("lists a statement title more than once" in n for n in app.stats["notes"])
    assert listing.last(app) == listing.STOPPED


def test_another_page_that_shows_a_title_twice_is_read_as_before(tmp_path, monkeypatch):
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: [(TITLE, "2022-01-31")]},
               repeated={INDIVIDUAL: [TITLE]})
    assert [d.account for d in _docs(app).values()] == [""]
    assert listing.last(app) == listing.COMPLETE


# -- a list cut short is never called whole -------------------------------------

def test_a_list_read_to_its_end_is_noted_whole(tmp_path, monkeypatch):
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: [(TITLE, "2022-01-31")]})
    assert listing.last(app) == listing.COMPLETE


def test_a_page_that_would_not_open_leaves_the_list_short(tmp_path, monkeypatch):
    """The tax page went unread, and a Resume after it called the run
    finished all the same."""
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: [(TITLE, "2022-01-31")]},
               broken=(TAX,))
    assert [d.account for d in _docs(app).values()] == [""], "what was read is kept"
    assert any("tax page would not open" in n for n in app.stats["notes"])
    assert listing.last(app) == listing.STOPPED


def test_a_view_more_that_stopped_leaves_the_list_short(tmp_path, monkeypatch):
    """What the page showed is kept, and the older statements behind the
    View More that could not be pressed are not taken as not there."""
    app = _run(tmp_path, monkeypatch, {INDIVIDUAL: [(TITLE, "2022-01-31")]},
               stops=(INDIVIDUAL,))
    assert [d.account for d in _docs(app).values()] == [""], "what showed is kept"
    assert any("statements page's View More stopped" in n for n in app.stats["notes"])
    assert listing.last(app) == listing.STOPPED
