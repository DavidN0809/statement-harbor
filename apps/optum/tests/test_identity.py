"""Which document is which, against nothing but invented values.

A document is remembered for good once it is saved, so a key that moves
under an archive makes every document in it look new, and a key two
documents share drops one of them for good. These run the app's own
listing and record code over a page that is a stand-in."""
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import listing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optum_docs as docs
import optum_site as site

HOST = "account.optumbank.com"
# Invented product ids. The second ends in the same four digits as the first.
PID, TWIN, OTHER = "12345678", "87655678", "23456789"
DAY = "2026-08-31"


def statement(pid, day=DAY, doc="900001", how="link"):
    return {"text": day, "path": f"/account/products/{pid}/statements/{doc}.pdf",
            "host": HOST, "how": how}


def tax(pid, title="Rendered EOY 5498-SA Notices-2025", doc="777"):
    return {"text": title, "path": f"/account/products/{pid}/tax_documents/{doc}.pdf",
            "host": HOST, "how": "link"}


def latest(pid):
    """The forms page's "Download latest statement" link for one product."""
    return {**statement(pid, doc="1"), "text": "Download latest statement"}


class Shown:
    """What a locator finds, never a password field or a row, and the
    page's own words."""

    def __init__(self, text):
        self.text = text

    def count(self):
        return 0

    def inner_text(self, **_kw):
        return self.text


class Page:
    """A signed-in tab, by address. Each address answers the entries the
    app's own page script would read there and the words it shows, and
    nothing is pressed."""

    def __init__(self, pages, said=None):
        self.pages = pages
        self.said = said or {}
        self.url = f"https://{HOST}/account"

    def goto(self, url, **_kw):
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def title(self):
        return ""

    def wait_for_selector(self, _sel, **_kw):
        # A page with nothing to read waits out its time.
        if not self.pages.get(self.url):
            raise TimeoutError("nothing appeared")

    def locator(self, _sel):
        return Shown(self.said.get(self.url, ""))

    def evaluate(self, _js):
        return self.pages.get(self.url, [])


def statements_url(pid):
    return f"https://{HOST}/account/products/{pid}/statements"


@pytest.fixture
def make_app(tmp_path):
    def make(out="out"):
        """The app as its own main builds it, over an output folder of its
        own name, so two builds of one name are two runs of one archive."""
        config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
        config.update({"owner": "Tester", "output_dir": str(tmp_path / out)})
        cfg = tmp_path / ("config-%s.json" % out)
        cfg.write_text(json.dumps(config))
        return docs.App(docs.build_parser().parse_args(["--discover", "--config", str(cfg)]))
    return make


def listed(app, pages, said=None) -> dict:
    """Every document the app's own Discover records from these pages, by
    key, with its record."""
    page = Page(pages, said)
    app.page = lambda: page
    app.check_session = lambda _page: None
    app.cmd_discover(quiet=True)
    return dict(app.discovery.data)


def test_a_second_product_changes_nothing_about_the_first_ones_documents(make_app):
    """The forms page linked one product, and then two. Every title of the
    first product gained " (product 5678)", so each key was new and its
    whole history was downloaded again as " (2)" files, a file deleted
    after importing it elsewhere included."""
    first_product = {statements_url(PID): [statement(PID), tax(PID)]}
    alone = listed(make_app("alone"), {site.FORMS_URL: [latest(PID)], **first_product})
    both = listed(make_app("both"), {site.FORMS_URL: [latest(PID), latest(OTHER)], **first_product,
                                     statements_url(OTHER): [statement(OTHER, doc="900011")]})
    assert len(alone) == 2 and set(alone) < set(both)
    assert {r["title"] for r in both.values()} == {f"HSA Statement {DAY}",
                                                  "Rendered EOY 5498-SA Notices-2025"}


def test_two_products_statements_of_one_day_are_two_documents_with_two_names(make_app):
    app = make_app()
    found = listed(app, {site.FORMS_URL: [latest(PID), latest(TWIN)],
                         statements_url(PID): [statement(PID)],
                         statements_url(TWIN): [statement(TWIN, doc="900011")]})
    # Two ids ending in the same four digits are still two products.
    assert sorted(r["account"] for r in found.values()) == sorted([PID, TWIN])
    names = []
    for rec in found.values():
        doc = docs.Document.from_dict(rec)
        name = docs.build_pdf_filename(doc.date, doc.summary, "", record=doc)
        path = docs.unique_path(app.paths.folder_for(doc.category), name, 240,
                                distinguisher=docs.told_apart_by(rec))
        path.write_bytes(b"%PDF-1.4")
        names.append(path.name)
    assert names[0] == f"{DAY} Optum Bank Monthly Statement.pdf", names
    assert names[1] == f"{DAY} Optum Bank Monthly Statement product 5678.pdf", names


def legacy(title, pid, doc="900001", kind="statements", **extra) -> dict:
    """A record as this app wrote it before a document's product was part
    of its key, saved, with the path it was listed at."""
    category = "Statement" if kind == "statements" else "Tax Document"
    date = DAY if kind == "statements" else "2025-12-31"
    rec = {"title": title, "category": category, "summary": "Monthly Statement", "date": date,
           "account": "", "href": f"/account/products/{pid}/{kind}/{doc}.pdf",
           "state": "Completed", "downloaded_ok": True, "pdf_path": "", **extra}
    return rec


def pid_of(rec):
    return rec["href"].split("/")[3]


def saved_before(app_factory, records):
    """An archive whose progress and discovery hold these records under the
    keys this app gave them then."""
    app = app_factory()
    for rec in records:
        key = docs.Document.from_dict(rec).key
        assert pid_of(rec) not in key, "a key from before carried no product"
        app.progress.update(key, dict(rec))
        app.discovery.update(key, dict(rec))
    app.progress.save()
    app.discovery.save()


def test_an_archive_saved_before_with_one_product_downloads_nothing_again(make_app):
    saved_before(make_app, [legacy(f"HSA Statement {DAY}", PID),
                            legacy("Rendered EOY 5498-SA Notices-2025", PID, doc="777",
                                   kind="tax_documents")])
    app = make_app()
    found = listed(app, {site.FORMS_URL: [latest(PID)],
                         statements_url(PID): [statement(PID), tax(PID)]})
    assert len(found) == 2 and len(app.progress.data) == 2
    for rec in found.values():
        assert app._already_done(docs.Document.from_dict(rec)), rec["title"]


def test_an_archive_saved_before_with_two_products_downloads_nothing_again(make_app):
    """Titles then carried " (product NNNN)", which is taken off as the
    record moves to the key with the product."""
    saved_before(make_app, [legacy(f"HSA Statement {DAY} (product 5678)", PID),
                            legacy(f"HSA Statement {DAY} (product 6789)", OTHER, doc="900011")])
    app = make_app()
    found = listed(app, {site.FORMS_URL: [latest(PID), latest(OTHER)],
                         statements_url(PID): [statement(PID)],
                         statements_url(OTHER): [statement(OTHER, doc="900011")]})
    assert len(found) == 2 and len(app.progress.data) == 2
    for rec in found.values():
        assert app._already_done(docs.Document.from_dict(rec)), rec["account"]


def test_only_a_record_stored_under_its_own_key_is_moved():
    """A record whose key its fields do not build, or whose path names no
    product, is left where it is, since whose it is would be a guess."""
    rec = legacy(f"HSA Statement {DAY}", PID)
    records = {"something else": dict(rec),
               docs.Document.from_dict(dict(rec, href="")).key: dict(rec, href="")}
    before = json.dumps(records, sort_keys=True)
    assert docs.adopt_product_keys(records) == 0
    assert json.dumps(records, sort_keys=True) == before


def test_a_finished_record_is_never_replaced_by_one_that_is_not():
    rec = legacy(f"HSA Statement {DAY}", PID)
    new_key = docs.Document.from_dict(dict(rec, account=PID)).key
    records = {docs.Document.from_dict(rec).key: dict(rec),
               new_key: dict(rec, account=PID, state="Discovered", downloaded_ok=False)}
    assert docs.adopt_product_keys(records) == 1
    assert list(records) == [new_key] and records[new_key]["downloaded_ok"] is True


# -- a tax form listed twice ---------------------------------------------------

def form_path(doc):
    return f"/account/products/{PID}/tax_documents/{doc}.pdf"


def forms_of(found) -> dict:
    """Each tax form the listing recorded, by the id its path ends in."""
    return {site.document_id_of(r["href"]): r for r in found.values()
            if r["category"] == "Tax Document"}


def test_a_corrected_form_under_the_title_of_the_one_it_corrects_is_listed_too(make_app):
    """Both were given one key, so the second path overwrote the first and
    one form was never fetched while the list was called whole. A form
    linked twice is still one form."""
    found = forms_of(listed(make_app(), {
        site.FORMS_URL: [latest(PID)],
        statements_url(PID): [statement(PID), tax(PID, doc="777"), tax(PID, doc="888"),
                              tax(PID, doc="777")]}))
    assert sorted(found) == ["777", "888"]
    assert (found["777"]["document_id"], found["888"]["document_id"]) == ("", "888")


def test_the_form_saved_first_keeps_its_key_in_whatever_order_the_page_lists_them(make_app):
    """The corrected form listed ahead of the original took the original's
    key, so it read as saved and was never fetched, and the original was
    fetched a second time under its id."""
    first = make_app()
    listed(first, {site.FORMS_URL: [latest(PID)],
                   statements_url(PID): [statement(PID), tax(PID, doc="777")]})
    key, rec = next((k, r) for k, r in first.discovery.data.items()
                    if r["category"] == "Tax Document")
    first.progress.update(key, dict(rec, state="Completed", downloaded_ok=True))

    app = make_app()
    found = forms_of(listed(app, {
        site.FORMS_URL: [latest(PID)],
        statements_url(PID): [statement(PID), tax(PID, doc="888"), tax(PID, doc="777")]}))
    assert found["777"]["document_id"] == "" and found["777"]["href"] == form_path("777")
    assert app._already_done(docs.Document.from_dict(found["777"]))
    assert found["888"]["document_id"] == "888"
    assert not app._already_done(docs.Document.from_dict(found["888"]))


def test_a_corrected_form_is_named_apart_by_the_end_of_its_id():
    assert docs.told_apart_by({"account": PID, "document_id": "4400888"}) == "400888"
    assert docs.told_apart_by({"account": PID}) == "product 5678"


# -- which products are read ---------------------------------------------------

def link(path, text="Overview"):
    return {"text": text, "path": path, "host": HOST, "how": "link"}


def test_a_link_to_a_products_overview_or_settings_names_no_product_to_read():
    """Every link into /account/products/ named a product, nav links
    included, so a product with no statements page stopped every Discover."""
    entries = [latest(PID), link(f"/account/products/{OTHER}"),
               link(f"/account/products/{OTHER}/settings", "Card settings")]
    assert site.product_ids(entries) == [PID]
    assert site.product_ids(entries + [link(f"/account/products/{OTHER}/statements",
                                            "Statements")]) == [PID, OTHER]


SECOND = {site.FORMS_URL: [latest(PID), link(f"/account/products/{OTHER}/statements", "Statements")],
          statements_url(PID): [statement(PID)]}


def test_a_product_whose_page_says_it_has_no_statements_is_read_as_empty(make_app):
    app = make_app()
    found = listed(app, SECOND, said={statements_url(OTHER): "Statements\nYou have no statements yet."})
    assert [r["account"] for r in found.values()] == [PID]
    assert listing.last(app) == listing.COMPLETE


def test_a_product_page_that_shows_nothing_and_says_nothing_still_stops(make_app):
    """Help text that says what happens if there are none says nothing of
    this product, so the list is not called whole."""
    app = make_app()
    app.write_failure = lambda *_a, **_kw: None
    with pytest.raises(SystemExit):
        listed(app, SECOND, said={statements_url(OTHER): "If there are no statements, call us."})
    assert listing.last(app) == listing.STOPPED
    assert [r["account"] for r in app.discovery.data.values()] == [PID]


# -- the sign-in check ---------------------------------------------------------

def logged_in_says(make_app, capsys, forms) -> str:
    app = make_app()
    page = Page({site.FORMS_URL: forms})
    app.page = lambda: page
    capsys.readouterr()
    app.cmd_login()
    return capsys.readouterr().out


def test_login_says_success_only_when_the_forms_page_links_a_statement(make_app, capsys):
    """A link into a product is the site's menu, which any signed-in page
    of the site draws, and the old check took it for the forms page."""
    menu_only = [link(f"/account/products/{PID}"), link(f"/account/products/{PID}/settings", "Settings")]
    said = logged_in_says(make_app, capsys, menu_only)
    assert "Success" not in said and "cannot" in said
    said = logged_in_says(make_app, capsys, menu_only + [latest(PID)])
    assert "Success" in said and "links your latest statement" in said
