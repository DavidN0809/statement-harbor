"""A Download again of a receipt saved before keeps the banner it reads.

Download again runs with --redownload, and until the run has saved a copy
of its own, the record of a receipt saved before stays as it was
(paperpull_core.saved_copy). The banner was marked read only by the write
made when the receipt page was read, and that write was held, and the
purchase list was told only then, which was skipped. The writes made once
the new copy was saved carried the banner with no mark, so it was not
kept. Review Names then named the new copy without its banner, and the
next Rename read it off the PDF and renamed the file again. Found by the
review of Costco's store (#60), which took this design from Kroger. Every
number, store and item here is invented."""
import contextlib
import io
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage
import kroger_receipts as kr
import kroger_site as site
from paperpull_core import storage as core_storage
from paperpull_core.journal import Journal
from paperpull_core.models import IN_STORE, Classification, Item, Purchase, State

from test_banner_and_items import BODY, HEADER, PATTERN, STORE, _app, _text_pdf

NUMBER = "540~00123~2026-09-20~101~1234567"


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    yield
    core_storage.set_filename_patterns({})


def _listed(store="In-Store"):
    """A purchase as a list from 0.40 gives it, the purchase type where the
    store goes."""
    return Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=NUMBER,
                    total="$21.48", store_info=store)


def _saved_before(app):
    """A receipt saved before its banner was read, whose file the person
    has since deleted, the usual reason for a Download again."""
    p = _listed()
    gone = app.paths.folder_for(IN_STORE, "Receipt") / "2026-09-20 Kroger Groceries Receipt.pdf"
    app.progress.update(p.key, dict(p.to_dict(), summary="Groceries", confidence="High",
                                    pdf_path=str(gone), pdf_filename=gone.name,
                                    state=State.COMPLETED.value, downloaded_ok=True))
    app.discovery.update(p.key, dict(p.to_dict(), state=State.COMPLETED.value))
    return p


def _download_again(app, monkeypatch, unsure=False):
    """The run Download again starts, from the purchase list, its receipt
    page naming Metro Market."""
    app.args = SimpleNamespace(apply=True, redownload=True)
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.rules = None
    app._journal = Journal()
    page = SimpleNamespace(url="https://www.kroger.com/mypurchases/image/" + NUMBER)
    app.page = lambda: page
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: None)

    def read(page, purchase):
        purchase.store_info = "Metro Market"
        purchase.items = [Item(name="Invented Cold Brew Coffee, 32 oz")]
        return purchase
    monkeypatch.setattr(site, "extract_details", read)
    if unsure:
        monkeypatch.setattr(kr.classification, "classify_items",
                            lambda items, rules: Classification("Mixed Purchases", "Low"))

    def saved(page, purchase):
        """How a real save ends, a copy of its own on disk and PDF_VERIFIED
        with downloaded_ok."""
        purchase.document_type = "Receipt"
        name = storage.build_pdf_filename(purchase.purchase_date, purchase.summary,
                                          purchase.document_type, record=purchase)
        path = app.paths.folder_for(IN_STORE, "Receipt") / name
        _text_pdf(path, HEADER[1:] + STORE + BODY[:3])
        purchase.pdf_path, purchase.pdf_filename = str(path), path.name
        purchase.receipt_count = 1
        app._record_state(purchase, State.PDF_VERIFIED, extra={
            "pdf_size": path.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
        return True
    app._save_receipt = saved
    purchase = Purchase.from_dict(app.discovery.get(_listed().key))
    with contextlib.redirect_stdout(io.StringIO()):
        app.process_purchases([purchase])


@pytest.mark.parametrize("store, read", [
    ("Metro Market", True), ("", False), ("   ", False), (["Metro Market"], False)])
def test_every_write_says_whether_its_store_was_read(tmp_path, store, read):
    """The write that saves a copy marks the store as well, from the store
    itself, so no write after a held one leaves a banner unmarked."""
    app = _app(tmp_path)
    p = _listed(store)
    app._record_state(p, State.PDF_VERIFIED, extra={"downloaded_ok": True})
    assert app.progress.get(p.key).get("store_read") is read


def test_a_download_again_leaves_the_banner_marked_in_the_record_and_the_list(
        tmp_path, monkeypatch):
    app = _app(tmp_path)
    p = _saved_before(app)
    _download_again(app, monkeypatch)
    rec = app.progress.get(p.key)
    assert rec["downloaded_ok"] is True and Path(rec["pdf_path"]).exists(), \
        "the run saved a copy of its own"
    for rec in (app.progress.get(p.key), app.discovery.get(p.key)):
        assert (rec["store_info"], rec.get("store_read")) == ("Metro Market", True)
    assert app._store_kept(p.key) == "Metro Market"


def test_review_names_keeps_the_banner_of_a_copy_a_download_again_saved(tmp_path, monkeypatch):
    """The name a person gives keeps the banner, so a Rename after it has
    nothing to put back."""
    app = _app(tmp_path)
    _saved_before(app)
    _download_again(app, monkeypatch, unsure=True)
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    assert sorted(f.name for f in folder.glob("*.pdf")) == [
        "2026-09-20 Metro Market Mixed Purchases Receipt.pdf"]
    monkeypatch.setattr(kr, "ask", lambda prompt: "snacks")
    with contextlib.redirect_stdout(io.StringIO()):
        app.cmd_review_names()
    assert sorted(f.name for f in folder.glob("*.pdf")) == [
        "2026-09-20 Metro Market Snacks Receipt.pdf"]
