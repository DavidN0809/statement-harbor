"""An order moved to another computer with an invoice still to fetch saves
only that one there.

Target splits an order into invoices and saves each, and counts one as
saved by the order's list of those it saved (_invoices_on_file). An order
that saved its first invoice and not its second is written down as failed,
holding that list, with no row in the receipt index, since a row is written
only once every invoice is on file. tools/migrate.py --minimal left the
list out, so on the new computer the order's next run found nothing on
file and saved the first invoice a second time under a new name, and
--redownload did the same to every invoice the list held, though its file
was copied across. A whole move fetched only the second.

Each history here goes through a real export and import, and the record is
written by the app's own code. Every number and item is invented.
"""
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parents[1] / "tools"))

import migrate  # noqa: E402
import storage  # noqa: E402,F401  binds this provider's AppSpec
import target_receipts as app_mod  # noqa: E402
from paperpull_core import testkit  # noqa: E402
from paperpull_core.models import ONLINE, Item, Purchase, State  # noqa: E402

ORDER = "902000000000071"
FIRST, SECOND = "10000000000000071", "10000000000000072"


def an_app(folder: Path, *args):
    """The app over `folder`, an output folder tools/migrate.py finds by
    the storage.py beside its progress.json."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "storage.py").write_bytes((APP / "storage.py").read_bytes())
    if not (folder / "progress.json").exists():
        (folder / "progress.json").write_text("{}", encoding="utf-8")
    cfg = folder.parent / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(folder),
        "profile_dir": str(folder.parent / "profile"), "cdp_url": "http://127.0.0.1:9",
        "include_invoices": True, "delay_min_seconds": 0, "delay_max_seconds": 0}),
        encoding="utf-8")
    return app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), *args]))


def the_order():
    return Purchase(purchase_type=ONLINE, purchase_date="2026-02-11", order_number=ORDER,
                    total="$40.00", status="Delivered",
                    items=[Item(name="Invented Garden Trowel"),
                           Item(name="Invented Seed Starter Tray")],
                    summary="Garden", document_type="Invoice")


def first_invoice_name():
    return "2026-02-11 Target Garden Invoice (1 of 2).pdf"


def saved_one_of_two(folder: Path) -> Path:
    """The old computer's history, as the app writes it for an order whose
    first invoice was saved and whose second did not print. The first's
    file is left where it was, so a path not rebased names nothing here."""
    app = an_app(folder)
    entry = {"file": str(app.paths.invoices / first_invoice_name()), "part": "1 of 2",
             "number": FIRST, "kept": True, "names": True, "size": 4000, "pages": 1}
    walk = {"tokens": [], "held": [], "missed": [], "count": 2, "list_page": None,
            "saved": [entry]}
    assert app._file_invoices(the_order(), walk) is False
    rec = app.progress.get(the_order().key)
    assert rec["state"] == State.FAILED.value and rec["downloaded_ok"] is False, rec
    assert [e["number"] for e in rec["invoices"]] == [FIRST], rec
    assert app.index_csv.read_all() == [], "no row until every invoice is on file"
    return folder.parent


def moved(tmp_path, minimal: bool, name="history.ppz") -> Path:
    """The new computer's output folder, after an import of the old one's
    history."""
    old_root = tmp_path / "old"
    if not (old_root / "Target Receipts" / "progress.json").exists():
        saved_one_of_two(old_root / "Target Receipts")
    new = tmp_path / "new" / "Target Receipts"
    an_app(new)
    archive = tmp_path / name
    assert migrate.export(old_root, archive, minimal=minimal) == 0
    assert migrate.do_import(archive, new.parent, assume_yes=True) == 0
    return new


def copied_across(new: Path) -> Path:
    """The first invoice's PDF, copied to the new computer as it was saved."""
    path = new / "Invoices" / first_invoice_name()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(testkit.text_pdf(["Invoice 1 of 2", "Invoice number: %s" % FIRST,
                                       "10000071 - Invented Garden Trowel",
                                       "Invoice total $12.00"]))
    return path


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_the_invoice_saved_before_the_move_is_not_saved_again(tmp_path, minimal):
    """The order is tried again on the new computer, and the walk counts
    the first invoice on file, so only the second is saved. Its entry names
    the file under the new computer's folder."""
    new = moved(tmp_path, minimal)
    app = an_app(new)
    order = the_order()
    assert not app._already_done(order), "the order still has an invoice to fetch"
    on_file = app._invoices_on_file(order)
    assert [e["number"] for e in on_file] == [FIRST], \
        "the first invoice would be saved a second time, %s" % app.progress.get(order.key)
    assert Path(on_file[0]["file"]) == new / "Invoices" / first_invoice_name(), on_file


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_download_again_leaves_an_invoice_copied_across(tmp_path, minimal):
    """--redownload fetches an invoice whose file is gone. One copied
    across is there under the new computer's folder, so it is on file."""
    new = moved(tmp_path, minimal)
    copy = copied_across(new)
    on_file = an_app(new, "--redownload")._invoices_on_file(the_order())
    assert [(e["number"], e["file"]) for e in on_file] == [(FIRST, str(copy))], on_file


def test_a_newer_file_fills_the_list_into_an_order_an_older_minimal_moved(tmp_path,
                                                                           monkeypatch):
    """An older --minimal brought the order here without its list. A newer
    file carries it, the import fills it into the record, and its entries
    name the new computer's folder, as they do in a record it adds."""
    with monkeypatch.context() as m:
        m.setattr(migrate, "PROVIDER_SKIP_FIELDS",
                  {k: v for k, v in migrate.PROVIDER_SKIP_FIELDS.items() if k != "Target"})
        new = moved(tmp_path, True, "older.ppz")
    assert "invoices" not in an_app(new).progress.get(the_order().key)

    moved(tmp_path, True, "newer.ppz")
    copy = copied_across(new)
    assert [e["number"] for e in an_app(new)._invoices_on_file(the_order())] == [FIRST]
    on_file = an_app(new, "--redownload")._invoices_on_file(the_order())
    assert [(e["number"], e["file"]) for e in on_file] == [(FIRST, str(copy))], on_file
