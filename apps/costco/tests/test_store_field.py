"""The part of Costco a receipt came from, as {store} in a file name (#60).

A member asked for a field that tells a gas station receipt from a warehouse
one, the way Kroger's {store} carries its banner. Every row on the Warehouse
tab says In-Warehouse, gas included, so the list cannot say it. The receipt
can, since Costco heads each one with what it is, In-Warehouse Receipt,
Gas Station Receipt and the like, and a saved PDF is rendered from that same
dialog. Food court, pharmacy and tire center receipts have no heading of
their own anyone has seen, so they are warehouse receipts here.

Driven through the orchestrator where the store is decided, as the gas
receipt's tests are. Every receipt, place and number here is invented."""
import contextlib
import io
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import costco_receipts as app_mod
import costco_site as site
from paperpull_core import storage as core_storage
from paperpull_core.journal import Journal
from paperpull_core.models import IN_STORE, ONLINE, Purchase, State

PATTERN = "{date:yyyy-mm-dd} Costco[ {store}] {summary}[ {kind}]"


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


WAREHOUSE = ["In-Warehouse Receipt", "SPRINGFIELD #1234",
             "E 123456 KS PAPER TOWELS 19.99 Y", "E 234567 BANANAS 1.99 3",
             "SUBTOTAL 21.98", "**** TOTAL 21.98"]
GAS = ["Gas Station Receipt", "SPRINGFIELD #1234", "Pump", "Gallons", "Price",
       "4", "11.204", "$3.299", "Product", "Amount", "Regular", "$36.96",
       "Total Sale", "$36.96"]


# -- the heading -------------------------------------------------------------------

@pytest.mark.parametrize("heading, store", [
    ("In-Warehouse Receipt", "Warehouse"),
    ("In Warehouse Receipt", "Warehouse"),
    ("Gas Station Receipt", "Gas Station"),
    ("Car Wash Receipt", "Car Wash"),
    ("Gas & Car Wash Receipt", "Gas and Car Wash"),
    ("Gas and Car Wash Receipt", "Gas and Car Wash"),
])
def test_each_heading_names_its_part_of_costco(heading, store):
    assert site.store_from_receipt("Close\n%s\nSPRINGFIELD #1234" % heading) == store


def test_a_heading_nobody_has_seen_names_no_part_of_costco():
    """A pharmacy or food court receipt is not known to have a heading of
    its own, and a guess would name a file wrongly."""
    assert site.store_from_receipt("Pharmacy Receipt\nSPRINGFIELD #1234") == ""
    assert site.store_from_receipt("Receipt\nSPRINGFIELD #1234") == ""


def test_only_the_heading_names_the_part_of_costco():
    """A line further down, an item or a note, never does."""
    text = "\n".join(WAREHOUSE[:1] + ["x"] * 8 + ["Gas Station Receipt"])
    assert site.store_from_receipt(text) == "Warehouse"
    assert site.store_from_receipt("\n".join(["x"] * 8 + ["Gas Station Receipt"])) == ""


def test_a_warehouse_visit_is_still_named_by_its_items():
    """Warehouse names a place, not a purchase, so it never becomes the
    summary the way Gas Station does."""
    assert site.kind_from_receipt("\n".join(WAREHOUSE)) == ""
    assert site.kind_from_receipt("\n".join(GAS)) == "Gas Station"


# -- a run ---------------------------------------------------------------------------

class _Store:
    def __init__(self):
        self.data = {}

    def update(self, key, rec=None, **kw):
        self.data.setdefault(key, {}).update(rec or {})

    def append_rows(self, *a, **kw):
        pass

    def get(self, key, *a, **kw):
        return self.data.get(key)


class _Page:
    url = "https://www.costco.com/myaccount/#/app/ordersandpurchases"


def _run_app(monkeypatch, receipt):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress, app.discovery = _Store(), _Store()
    app.rules = None
    app._journal = Journal()
    app.page = lambda: _Page()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: None)
    monkeypatch.setattr(site, "receipt_text", lambda page: "\n".join(receipt))
    return app


def _listed(kind=IN_STORE, store="In-Warehouse", number="wh-20260315-3696-SPRINGFIELD"):
    """What a list row becomes."""
    return Purchase(purchase_type=kind, order_number=number, purchase_date="2026-03-15",
                    total="$36.96", store_info=store)


def _process(app, purchase):
    with contextlib.redirect_stdout(io.StringIO()):
        app.process_purchases([purchase], dry_run=True)


@pytest.mark.parametrize("receipt, store", [(GAS, "Gas Station"), (WAREHOUSE, "Warehouse")])
def test_a_run_keeps_the_part_of_costco_its_receipt_names(monkeypatch, receipt, store):
    app = _run_app(monkeypatch, receipt)
    purchase = _listed()
    app.discovery.update(purchase.key, dict(purchase.to_dict(), store_read=False))
    _process(app, purchase)
    assert purchase.store_info == store
    rec = app.progress.get(purchase.key)
    assert (rec["store_info"], rec["store_read"]) == (store, True)
    listed = app.discovery.get(purchase.key)
    assert (listed["store_info"], listed["store_read"]) == (store, True), \
        "the list agrees with the record, since Rename reads the list over it"


def test_a_receipt_with_no_heading_it_knows_keeps_no_store(monkeypatch):
    """Not the list's In-Warehouse, which every warehouse receipt carries,
    gas included."""
    app = _run_app(monkeypatch, ["Receipt", "SPRINGFIELD #1234", "E 1 THING 1.00 Y"])
    purchase = _listed()
    _process(app, purchase)
    assert purchase.store_info == ""
    assert app.progress.get(purchase.key)["store_read"] is False


def test_an_online_order_keeps_the_lists_word_for_it(monkeypatch):
    """The print view is not a dialog and has no heading. The Online tab's
    own word is the store."""
    app = _run_app(monkeypatch, [])
    purchase = _listed(ONLINE, "Online", "1234567890")
    _process(app, purchase)
    assert purchase.store_info == "Online"
    assert app._store_kept(purchase.key) == "Online"


def test_the_list_never_brings_in_warehouse_back_over_a_store_read():
    app = object.__new__(app_mod.App)
    app.progress, app.discovery = _Store(), _Store()
    app.progress.update("In-Store:a", {"purchase_type": IN_STORE, "store_info": "Gas Station",
                                       "store_read": True})
    app.discovery.update("In-Store:a", {"purchase_type": IN_STORE, "store_info": "In-Warehouse"})
    assert app._store_kept("In-Store:a") == "Gas Station"
    app.discovery.update("In-Store:b", {"purchase_type": IN_STORE, "store_info": "In-Warehouse"})
    assert app._store_kept("In-Store:b") == "", "written by an older version, never read"
    app.progress.update("In-Store:c", {"purchase_type": IN_STORE, "store_info": ["Gas Station"],
                                       "store_read": True})
    assert app._store_kept("In-Store:c") == "", "a store that is not text names nothing"
    p = _listed(number="d")
    app.progress.update(p.key, {"purchase_type": IN_STORE, "store_info": "Car Wash",
                                "store_read": True})
    assert app._listed_store(p) == "Car Wash", "a row read again keeps what its receipt said"


ROW = {"purchaseType": "WAREHOUSE", "href": "", "createdDateTime": "2026-03-15",
       "total": "$36.96", "status": "", "where": "SPRINGFIELD", "index": 0,
       "cardText": "In-Warehouse 03/15/2026 SPRINGFIELD Total $36.96 View Receipt"}


def test_reading_the_list_again_keeps_the_store_a_receipt_named(tmp_path, monkeypatch):
    """Every row says In-Warehouse, so a list read after the receipt was
    must not put that back, in the list Rename reads over the record."""
    app = _app(tmp_path)
    app.args = SimpleNamespace(apply=True, redownload=False, start_date=None,
                               end_date=None, year=None)
    app.page = lambda: _Page()
    app._open_orders = lambda page: None
    monkeypatch.setattr(site, "history_state", lambda page: "listed")
    monkeypatch.setattr(site, "fetch_history",
                        lambda page, *a, **kw: {"records": [dict(ROW)], "last": True})
    key = site.record_to_purchase(dict(ROW)).key
    with contextlib.redirect_stdout(io.StringIO()):
        app.cmd_discover(quiet=True)
    assert (app.discovery.get(key)["store_info"], app.discovery.get(key)["store_read"]) == \
        ("", False), "a new row's In-Warehouse names no part of Costco"
    app.progress.update(key, {"purchase_type": IN_STORE, "store_info": "Gas Station",
                              "store_read": True})
    with contextlib.redirect_stdout(io.StringIO()):
        app.cmd_discover(quiet=True)
    assert (app.discovery.get(key)["store_info"], app.discovery.get(key)["store_read"]) == \
        ("Gas Station", True)


# -- receipts saved before -------------------------------------------------------------

def _text_pdf(path: Path, lines) -> None:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (760 - 14 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b" " * 4000)


def _app(tmp_path, apply=True):
    app = object.__new__(app_mod.App)
    app.args = SimpleNamespace(apply=apply, redownload=False)
    app.config = {"max_path_length": 240, "owner": "", "min_pdf_bytes": 1000}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.progress.data, app.progress._loaded = {}, True
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.discovery.data, app.discovery._loaded = {}, True
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.stats = {"mode": ""}
    return app


def _saved_before(app, where: Path, lines, summary, date, kind=IN_STORE,
                  store="In-Warehouse", number=None):
    """A receipt an older version saved, with the list's word as its store."""
    _text_pdf(where, lines)
    number = number or "wh-%s-3696-SPRINGFIELD" % date.replace("-", "")
    p = Purchase(purchase_type=kind, purchase_date=date, order_number=number,
                 summary=summary, store_info=store, pdf_filename=where.name,
                 pdf_path=str(where), state=State.COMPLETED.value)
    app.progress.update(p.key, dict(p.to_dict(), downloaded_ok=True))
    app.discovery.update(p.key, dict(p.to_dict()))
    app.index_csv.append_rows([{
        "Purchase Date": date, "Purchase Type": kind,
        "Order or Receipt Number": number, "Purchase Summary": summary,
        "Document Type": "Receipt", "PDF Filename": where.name, "PDF Full Path": str(where),
        "Processing Status": "Completed"}])
    return p


def test_receipts_saved_before_take_their_part_of_costco_at_rename(tmp_path, capsys):
    """Read off each saved PDF's heading, asking nothing of Costco, and a
    pattern with {store} then names them for it."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    gas = _saved_before(app, folder / "2026-03-15 Costco Gas Station Receipt.pdf", GAS,
                        "Gas Station", "2026-03-15")
    trip = _saved_before(app, folder / "2026-03-16 Costco Groceries Receipt.pdf", WAREHOUSE,
                         "Groceries", "2026-03-16")
    app.cmd_rename()
    assert "Read the part of Costco from 2 receipt(s)" in capsys.readouterr().out
    assert sorted(f.name for f in folder.glob("*.pdf")) == [
        "2026-03-15 Costco Gas Station Gas Station Receipt.pdf",
        "2026-03-16 Costco Warehouse Groceries Receipt.pdf"]
    for p, store in ((gas, "Gas Station"), (trip, "Warehouse")):
        for rec in (app.progress.get(p.key), app.discovery.get(p.key)):
            assert (rec["store_info"], rec["store_read"]) == (store, True)
    app.cmd_rename()
    assert "Read the part of Costco" not in capsys.readouterr().out, "read once, then kept"


def test_a_rename_preview_changes_nothing(tmp_path, capsys):
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path, apply=False)
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    old = folder / "2026-03-15 Costco Gas Station Receipt.pdf"
    p = _saved_before(app, old, GAS, "Gas Station", "2026-03-15")
    before = (dict(app.progress.get(p.key)), dict(app.discovery.get(p.key)))
    app.cmd_rename()
    assert "2026-03-15 Costco Gas Station Gas Station Receipt.pdf" in capsys.readouterr().out
    assert sorted(f.name for f in folder.glob("*.pdf")) == [old.name]
    assert (app.progress.get(p.key), app.discovery.get(p.key)) == before
    assert "store_read" not in app.progress.get(p.key), "a key it did not have is taken away"


def test_rename_reads_no_store_off_a_receipt_the_app_does_not_hold(tmp_path, capsys):
    """An index copied from another folder names a receipt there. Nothing is
    read off it into the record."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path / "out")
    outside = tmp_path / "elsewhere" / "2026-03-15 Costco Gas Station Receipt.pdf"
    p = _saved_before(app, outside, GAS, "Gas Station", "2026-03-15")
    app.cmd_rename()
    assert "Read the part of Costco" not in capsys.readouterr().out
    assert app.progress.get(p.key)["store_info"] == ""
    assert outside.is_file()


def test_an_online_order_saved_before_keeps_the_lists_word(tmp_path, capsys):
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    folder = app.paths.folder_for(ONLINE, "Receipt")
    p = _saved_before(app, folder / "2026-03-15 Costco Groceries Receipt.pdf",
                      ["Order Details", "Order # 1234567890"], "Groceries", "2026-03-15",
                      kind=ONLINE, store="Online", number="1234567890")
    app.cmd_rename()
    assert "Read the part of Costco" not in capsys.readouterr().out
    assert app.progress.get(p.key)["store_info"] == "Online"
    assert [f.name for f in folder.glob("*.pdf")] == ["2026-03-15 Costco Online Groceries Receipt.pdf"]
