"""A receipt already saved keeps its record when Download again saves no
copy of its own.

The panel's Download again runs an app with --redownload, so a receipt
app takes every purchase in scope again, the ones it saved before
included. The purchase it works on comes from discovery.json, which holds
no file, and every step of the attempt wrote the whole purchase into its
record. One that saved nothing left the record of a receipt the person has
naming no file, or the copy it put aside in Manual Review, with this
attempt's summary and a state of Needs Manual Review, No Receipt Available
or Failed, while downloaded_ok from the first save stayed. A page that was
not the purchase's had its own facts read into the record as well.

So the Pilot report listed a saved receipt as needing attention, Rename
found no record naming the saved file and named it from the failed
attempt's summary, another purchase's after a wrong page, and Review Names
left the saved copy's record alone, since that record no longer named it.
Apple and Uber read the state discovery keeps to decide which purchases
are settled, so a failed attempt had their next Discover open those again.
Target went further and wrote downloaded_ok False after an invoice walk
that fell short, so a failed Download again turned an order saved for good
into one fetched on every run.

These drive each receipt app's own _record_state, _write_csv_rows and the
branches that end an attempt without a copy, over an output folder on
disk. Every name, number, amount and answer is invented.
"""
import argparse
import ast
import collections
import importlib
import inspect
import sys
from pathlib import Path

import pytest

from paperpull_core import receipt_pdf, renaming
from paperpull_core.models import ONLINE, Item, Purchase, State, ValidationResult

REPO = Path(__file__).resolve().parents[2]

ORDER = "ORDER-0001"
DATE = "2026-05-14"
SAVED_SUMMARY = "Garden Hose"


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


def downloads_again(app: Path) -> bool:
    """An app whose purchases are saved once for good and fetched again
    under --redownload, found by what its App does. Its skip decision reads
    both the flag and downloaded_ok, and it records each step and checks
    each saved copy."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App"), None)
    if cls is None:
        return False
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    skip = methods.get("_already_done")
    return bool(skip and {"_record_state", "_write_csv_rows", "_finish_pdf"} <= set(methods)
                and "redownload" in ast.unparse(skip)
                and "downloaded_ok" in ast.unparse(skip))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and downloads_again(d))
IDS = [d.name for d in APPS]


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


@pytest.fixture(autouse=True)
def default_names():
    """Files named the default way, whatever a test before this one chose."""
    from paperpull_core import storage
    storage.set_filename_owner("")
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def app_in(mod, out: Path, redownload: bool):
    """The app's own downloader over an output folder on disk, without its
    __init__, which would want a config file and a console. A new one is
    a new run, as each press of a button in the panel is."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 2000, "owner": ""}
    inst.args = argparse.Namespace(redownload=redownload)
    inst.paths = storage.Paths(out)
    inst.paths.ensure()
    backups = inst.paths.backups
    inst.progress = storage.JsonStore(inst.paths.progress_json, backups)
    inst.discovery = storage.JsonStore(inst.paths.discovery_json, backups)
    inst.progress.load()                        # as the app's own __init__ does
    inst.discovery.load()
    inst.index_csv = storage.CsvFile(inst.paths.receipt_index_csv,
                                     storage.RECEIPT_INDEX_COLUMNS, backups)
    inst.order_csv = storage.CsvFile(inst.paths.order_history_csv,
                                     storage.ORDER_HISTORY_COLUMNS, backups)
    inst.stats = collections.defaultdict(int)
    inst.stats["new_files"] = []
    inst.stats["dates_processed"] = []
    inst.write_failure = lambda *a, **k: None
    inst._block = None                          # Walmart's invoice block, none printed
    return inst


def opening_pdf(path: Path) -> Path:
    """A one page PDF of invented words that opens and is larger than the
    smallest the app takes."""
    from pypdf import PdfWriter
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 200})
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def failing_copy(path: Path) -> Path:
    """What a capture that went wrong leaves, too small to pass any check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% an invented blank print\n%%EOF\n")
    return path


def listed() -> Purchase:
    """The purchase as discovery.json gives it to a run, with no file."""
    return Purchase(purchase_type=ONLINE, purchase_date=DATE, order_number=ORDER,
                    total="11.11", status="Delivered")


def name_for(summary: str) -> str:
    from paperpull_core.storage import build_pdf_filename
    return build_pdf_filename(DATE, summary, "Receipt")


def saved_by_a_first_run(mod, out: Path, low: bool = False):
    """The receipt as a first run leaves it, written by the app's own
    _record_state and _write_csv_rows in the order process_one writes them.
    `low` is a receipt saved and marked for review for its name alone.
    Returns the saved file, its record and what discovery says of it."""
    inst = app_in(mod, out, redownload=False)
    p = listed()
    p.items = [Item(name="Invented Garden Hose", quantity="1", line_total="11.11")]
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = SAVED_SUMMARY, ("Low" if low else "High")
    inst._record_state(p, State.RECEIPT_LOCATED)
    path = opening_pdf(inst.paths.folder_for(ONLINE) / name_for(SAVED_SUMMARY))
    p.pdf_path, p.pdf_filename = str(path), path.name
    inst._record_state(p, State.PDF_SAVED)
    inst._record_state(p, State.PDF_VERIFIED, extra={
        "pdf_size": path.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
    inst._write_csv_rows(p, receipt_status="Downloaded",
                         processing_status="Review Needed" if low else "Completed")
    if low:
        inst._record_state(p, State.NEEDS_MANUAL_REVIEW, notes="Low classification confidence")
    else:
        inst._record_state(p, State.COMPLETED)
    return path, dict(inst.progress.get(p.key)), dict(inst.discovery.get(p.key) or {})


def a_wrong_page(p: Purchase) -> Purchase:
    """What a page that is not this purchase's reads into it."""
    p.items = [Item(name="Invented Patio Chair", quantity="1", line_total="22.22")]
    p.total = "22.22"
    p.summary, p.confidence = "Patio Chair", "High"
    return p


# -- the ways an attempt ends with no copy of its own --------------------------------

def details_would_not_open(inst, p, saved):
    inst._record_state(p, State.NEEDS_MANUAL_REVIEW, notes="Details page failed to load twice")
    return State.NEEDS_MANUAL_REVIEW


def page_not_this_purchase(inst, p, saved):
    a_wrong_page(p)
    inst._record_state(p, State.DETAILS_EXTRACTED)
    why = "the page is not this purchase's"
    if hasattr(inst, "_refuse_page"):
        inst._refuse_page(p, why)
    else:
        inst._record_state(p, State.NEEDS_MANUAL_REVIEW, notes=why)
    return State.NEEDS_MANUAL_REVIEW


def no_receipt_on_the_page(inst, p, saved):
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = "Hose Reel", "High"
    inst._record_state(p, State.NO_RECEIPT_AVAILABLE, notes="No printable receipt available")
    inst._write_csv_rows(p, receipt_status="No printable receipt available",
                         processing_status=State.NEEDS_MANUAL_REVIEW.value,
                         notes_extra="No Print receipts control found")
    return State.NO_RECEIPT_AVAILABLE


def a_control_left_unread(inst, p, saved):
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = "Hose Reel", "High"
    if hasattr(inst, "_left_unread"):
        inst._left_unread(p, "the receipt")
    else:
        inst._record_state(p, State.FAILED,
                           notes="A control naming the receipt could not be read")
    return State.FAILED


def an_error_partway(inst, p, saved):
    inst._record_state(p, State.DETAILS_EXTRACTED)
    inst._record_state(p, State.FAILED, notes="Unhandled error: an invented one")
    return State.FAILED


def canceled_since(inst, p, saved):
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.status = "Canceled"
    inst._record_state(p, State.CANCELED, notes="Order canceled; no receipt downloaded")
    inst._write_csv_rows(p, receipt_status="Canceled", processing_status=State.CANCELED.value)
    return State.CANCELED


def finish(inst, p, out_path: Path):
    """The app's own _finish_pdf on a copy already on disk, with no page to
    print again."""
    params = inspect.signature(inst._finish_pdf).parameters
    if "page" in params:
        return inst._finish_pdf(None, p, out_path)
    return inst._finish_pdf(p, out_path)


def put_aside_beside_the_saved_copy(inst, p, saved):
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = "Hose Reel", "High"
    inst._record_state(p, State.RECEIPT_LOCATED)
    from paperpull_core.storage import unique_path
    out_path = unique_path(inst.paths.folder_for(ONLINE), name_for(SAVED_SUMMARY), 240,
                           distinguisher=ORDER)
    assert out_path != saved
    assert finish(inst, p, failing_copy(out_path)) is False
    return State.NEEDS_MANUAL_REVIEW


def put_aside_after_the_copy_was_deleted(inst, p, saved):
    """The usual reason for Download again. The person deleted the saved
    file after importing it elsewhere, so the attempt saves under the very
    name the record holds."""
    saved.unlink()
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = SAVED_SUMMARY, "High"
    inst._record_state(p, State.RECEIPT_LOCATED)
    out_path = inst.paths.folder_for(ONLINE) / name_for(SAVED_SUMMARY)
    assert str(out_path) == str(saved)
    assert finish(inst, p, failing_copy(out_path)) is False
    return State.NEEDS_MANUAL_REVIEW


ENDINGS = [details_would_not_open, page_not_this_purchase, no_receipt_on_the_page,
           a_control_left_unread, an_error_partway, canceled_since,
           put_aside_beside_the_saved_copy, put_aside_after_the_copy_was_deleted]


def test_every_receipt_app_is_covered():
    """Every receipt app, found by what it does. Not a check that passes
    because it found nobody."""
    assert len(APPS) >= 14, IDS
    assert {"amazon", "apple", "target", "uber", "walmart", "meijer"} <= set(IDS)


def rename_names_for(inst, saved: Path) -> list:
    """The names Rename would give the saved file today."""
    seen = []
    real = renaming.describe
    try:
        renaming.describe = lambda changes, **k: seen.extend(changes)
        renaming.run_for(inst, apply_changes=False, say=lambda *a: None)
    finally:
        renaming.describe = real
    return [(c.new_path.name if c.renaming and c.new_path else Path(c.old_path).name)
            for c in seen if str(c.old_path) == str(saved)]


@pytest.mark.parametrize("ending", ENDINGS, ids=[e.__name__ for e in ENDINGS])
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_download_again_that_saves_nothing_keeps_the_saved_record(app, ending, tmp_path):
    mod = load(app)
    out = tmp_path / "out"
    saved, before, found_before = saved_by_a_first_run(mod, out)

    inst = app_in(mod, out, redownload=True)
    p = listed()
    assert inst._already_done(p) is False, "Download again takes a saved receipt again"
    state = ending(inst, p, saved)

    after = inst.progress.get(p.key)
    for field in sorted(set(before) | set(after)):
        if field in ("notes", "updated_at"):
            continue
        assert after.get(field) == before.get(field), (
            "%s of the saved copy's record changed from %r to %r"
            % (field, before.get(field), after.get(field)))
    assert after["downloaded_ok"] is True
    assert state.value in after.get("notes", ""), "the record says what the attempt came to"
    assert (inst.discovery.get(p.key) or {}).get("state") == found_before.get("state")

    plain = app_in(mod, out, redownload=False)
    assert plain._already_done(listed()) is True

    # Rename names the saved file for the saved copy's own facts.
    if saved.exists():
        names = rename_names_for(plain, saved)
        assert names and all(SAVED_SUMMARY in n for n in names), names


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_the_notes_say_how_the_latest_attempt_ended(app, tmp_path):
    """Two Download agains that each saved nothing, one run after the
    other. The saved copy's own notes stay, and one entry says how the
    latest attempt ended."""
    from paperpull_core import saved_copy
    mod = load(app)
    out = tmp_path / "out"
    saved, before, _found = saved_by_a_first_run(mod, out, low=True)
    details_would_not_open(app_in(mod, out, redownload=True), listed(), saved)
    a_control_left_unread(app_in(mod, out, redownload=True), listed(), saved)
    notes = app_in(mod, out, redownload=False).progress.get(listed().key)["notes"]
    assert notes.startswith(before["notes"] + "; "), notes
    assert notes.count(saved_copy.NOTE) == 1, notes
    assert State.FAILED.value in notes and "twice" not in notes, notes


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_review_names_after_a_copy_was_put_aside(app, tmp_path, monkeypatch):
    """A receipt saved and marked for review for its name, then a Download
    again whose copy failed its check and was put aside. Review Names offers
    both. A new name for the saved copy takes the record and completes it,
    and one for the copy put aside leaves the record alone. The record named
    the copy put aside, so the saved copy's new name was left out of it and
    the failed copy's was written in, with its state Completed."""
    mod = load(app)
    out = tmp_path / "out"
    saved, before, _found = saved_by_a_first_run(mod, out, low=True)
    inst = app_in(mod, out, redownload=True)
    put_aside_beside_the_saved_copy(inst, listed(), saved)

    plain = app_in(mod, out, redownload=False)
    answers = iter(["Hose Kit", "Hose Reel Copy"])
    monkeypatch.setattr(mod, "ask", lambda prompt: next(answers))
    plain.cmd_review_names()

    rec = plain.progress.get(listed().key)
    assert "Hose Kit" in Path(rec["pdf_path"]).name, rec["pdf_path"]
    assert Path(rec["pdf_path"]).parent == saved.parent
    assert Path(rec["pdf_path"]).exists()
    assert rec["state"] == State.COMPLETED.value
    assert rec["downloaded_ok"] is True
    aside = [r for r in plain.index_csv.read_all()
             if Path(r["PDF Full Path"] or ".").parent == plain.paths.manual_review]
    assert aside and all(r["Processing Status"] != "Completed" for r in aside), aside


# -- an attempt that does save still takes the record --------------------------------

@pytest.fixture
def checks_pass(monkeypatch):
    """Every check a saved copy goes through passes, so a copy of invented
    words counts as this purchase's."""
    def ok(path, *a, **k):
        return ValidationResult(True, "", size_bytes=Path(path).stat().st_size, page_count=1)
    monkeypatch.setattr(receipt_pdf, "validate_pdf", ok)
    return ok


def saved_again(inst, p, out_path: Path, low: bool = False):
    """process_one's steps from a copy on disk to the end, as it takes them."""
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = "Hose Reel", ("Low" if low else "High")
    inst._record_state(p, State.RECEIPT_LOCATED)
    assert finish(inst, p, opening_pdf(out_path)) is True
    inst._write_csv_rows(p, receipt_status="Downloaded",
                         processing_status="Review Needed" if low else "Completed")
    inst._record_state(p, State.NEEDS_MANUAL_REVIEW if low else State.COMPLETED,
                       notes="Low classification confidence" if low else "")


@pytest.mark.parametrize("low", [False, True], ids=["sure", "unsure"])
@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_download_again_that_saves_a_copy_takes_the_record(app, low, tmp_path, checks_pass):
    mod = load(app)
    out = tmp_path / "out"
    saved, before, _found = saved_by_a_first_run(mod, out)
    inst = app_in(mod, out, redownload=True)
    if hasattr(inst, "_check"):
        inst._check = lambda path, *a, **k: checks_pass(path)
    p = listed()
    from paperpull_core.storage import unique_path
    new = unique_path(inst.paths.folder_for(ONLINE), name_for("Hose Reel"), 240,
                      distinguisher=ORDER)
    saved_again(inst, p, new, low=low)

    after = inst.progress.get(p.key)
    assert after["pdf_path"] == str(new)
    assert after["pdf_filename"] == new.name
    assert after["summary"] == "Hose Reel"
    assert after["downloaded_ok"] is True
    want = State.NEEDS_MANUAL_REVIEW if low else State.COMPLETED
    assert after["state"] == want.value
    assert (inst.discovery.get(p.key) or {}).get("state") == want.value


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_first_download_put_aside_is_recorded_as_before(app, tmp_path):
    """A purchase never saved has no copy to keep, so its record names the
    copy put aside, as it always did."""
    mod = load(app)
    out = tmp_path / "out"
    inst = app_in(mod, out, redownload=False)
    p = listed()
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.summary, p.confidence = SAVED_SUMMARY, "High"
    inst._record_state(p, State.RECEIPT_LOCATED)
    out_path = inst.paths.folder_for(ONLINE) / name_for(SAVED_SUMMARY)
    assert finish(inst, p, failing_copy(out_path)) is False
    rec = inst.progress.get(p.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert Path(rec["pdf_path"]).parent == inst.paths.manual_review
    assert not rec.get("downloaded_ok")
    assert (inst.discovery.get(p.key) or {}).get("state") == State.NEEDS_MANUAL_REVIEW.value


# -- Target's invoice walk ---------------------------------------------------------

def test_a_short_invoice_walk_leaves_a_saved_order_saved(tmp_path):
    """Target writes an order down as done only once every invoice it has is
    on file. A Download again whose walk fell short wrote downloaded_ok
    False over an order saved for good, so every later run fetched it."""
    app = REPO / "apps" / "target"
    mod = load(app)
    out = tmp_path / "out"
    saved, before, _found = saved_by_a_first_run(mod, out)
    inst = app_in(mod, out, redownload=True)
    p = listed()
    inst._record_state(p, State.DETAILS_EXTRACTED)
    p.document_type = "Invoice"
    first = opening_pdf(inst.paths.folder_for(ONLINE, "Invoice") / "Invented (1 of 2).pdf")
    walk = {"tokens": [], "held": [], "missed": [], "count": 2, "list_page": None,
            "listed": ORDER,
            "saved": [{"file": str(first), "part": "1 of 2", "number": "", "kept": True,
                       "names": True, "size": first.stat().st_size, "pages": 1}]}
    assert inst._file_invoices(p, walk) is False
    after = inst.progress.get(p.key)
    assert after["downloaded_ok"] is True
    assert after["pdf_path"] == before["pdf_path"]
    assert after["state"] == before["state"]
    # The invoice the walk did save is remembered, so it is not saved twice.
    assert [e["file"] for e in after["invoices"]] == [str(first)]
    plain = app_in(mod, out, redownload=False)
    assert plain._already_done(listed()) is True
