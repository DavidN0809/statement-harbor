"""Which document is which, against nothing but invented values.

A document is remembered for good once it is saved, so a key that moves
under an archive makes every document in it look new, and a key two
documents share drops one of them for good. These run the app's own
listing and record code over a page that is a stand-in."""
import json
import sys
from pathlib import Path

import pytest

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


class Nothing:
    def count(self):
        return 0


class Page:
    """A signed-in tab, by address. Each address answers the entries the
    app's own page script would read there, and nothing is pressed."""

    def __init__(self, pages):
        self.pages = pages
        self.url = f"https://{HOST}/account"

    def goto(self, url, **_kw):
        self.url = url

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, _sel, **_kw):
        pass

    def locator(self, _sel):
        return Nothing()

    def evaluate(self, _js):
        return self.pages.get(self.url, [])


def statements_url(pid):
    return f"https://{HOST}/account/products/{pid}/statements"


@pytest.fixture
def make_app(tmp_path):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    config.update({"owner": "Tester", "output_dir": str(tmp_path / "out")})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))

    def make():
        return docs.App(docs.build_parser().parse_args(["--discover", "--config", str(cfg)]))
    return make


def listed(app, pages) -> dict:
    """Every document the app's own listing records from these pages, by
    key, with its record."""
    for r in site.collect_download_docs(Page(pages)):
        app._record_rawdoc(r, site.BILLING_URL)
    return dict(app.discovery.data)


def test_a_second_product_changes_nothing_about_the_first_ones_documents(make_app):
    """The forms page linked one product, and then two. Every title of the
    first product gained " (product 5678)", so each key was new and its
    whole history was downloaded again as " (2)" files, a file deleted
    after importing it elsewhere included."""
    first_product = {statements_url(PID): [statement(PID), tax(PID)]}
    alone = listed(make_app(), {site.FORMS_URL: [latest(PID)], **first_product})
    both = listed(make_app(), {site.FORMS_URL: [latest(PID), latest(OTHER)], **first_product,
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


def saved_before(app_factory, records):
    """An archive whose progress and discovery hold these records under the
    keys this app gave them then."""
    app = app_factory()
    for rec in records:
        key = docs.Document.from_dict(rec).key
        assert key.endswith(":"), "a key from before carried no product"
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
