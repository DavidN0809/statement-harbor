"""A Rename never ends with its files moved and a ledger naming them by the
names they had.

Rename renamed the files and only then wrote the index, the order history
and the run state. With the index open in Excel, the write waited its
minute and gave up with PermissionError, and the files had already moved.
Neither the index nor progress.json followed them. Verify then reported
every renamed file missing, and the next Rename, reading rows whose files
were gone, said every file was already named the way the app names them,
so nothing ever pointed the ledgers at the files again. A review showed it
on 2026-10-07.

Now each ledger is shown to be writable before any file moves, waiting the
minute a write waits while another program holds it, and nothing moves
while one cannot be written. When a write still fails after the files
moved, each ledger already written is written back, the run state is put
back in memory as well (every app saves it on its way out), every file
goes back under the name it had, and Rename says so and stops with exit
code 1, so the panel does not report the files renamed.

Every ledger here is a real file written by the core's own CsvFile and
JsonStore. A write is refused where the real one gives up, or on Windows
the file is held open the way Excel holds a workbook it has open.
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import renaming, storage  # noqa: E402

DATE = "2026-09-12"
INDEX = "Testco Receipt Index.csv"
HISTORY = "Testco Order History.csv"
INDEX_COLUMNS = ["Purchase Date", "Order or Receipt Number", "Purchase Summary",
                 "Document Type", "PDF Filename", "PDF Full Path", "Processing Status",
                 "Notes"]
HISTORY_COLUMNS = ["Purchase Date", "Order or Receipt Number", "Purchase Summary",
                   "PDF Filename", "Processing Status", "Notes"]

on_windows = pytest.mark.skipif(os.name != "nt", reason="Windows is where an open file "
                                "cannot be replaced")


def body_of(number: str) -> bytes:
    return b"%PDF-1.4\n% the receipt of order " + number.encode() + b"\n%%EOF\n"


class _Paths:
    """The one folder the shop files its receipts in."""

    def __init__(self, folder: Path):
        self.folder = folder

    def filing_folders(self):
        return [self.folder]


class Shop:
    """Enough of a receipt app for Rename, its index, order history and run
    state real files, written as every app writes them."""

    def __init__(self, folder: Path):
        self.out = folder / "out"
        self.folder = self.out / "Online"
        self.folder.mkdir(parents=True)
        backups = self.out / "Backups"
        self.config = {"max_path_length": 240}
        self.paths = _Paths(self.folder)
        self.index_csv = storage.CsvFile(self.out / INDEX, INDEX_COLUMNS, backups)
        self.order_csv = storage.CsvFile(self.out / HISTORY, HISTORY_COLUMNS, backups)
        self.progress = storage.JsonStore(self.out / "progress.json", backups)
        self.discovery = storage.JsonStore(self.out / "discovery.json", backups)
        self.progress.load()
        self.discovery.load()

    def bought(self, number: str, summary: str, name: str) -> Path:
        """One purchase, its receipt saved under `name`."""
        path = self.folder / name
        path.write_bytes(body_of(number))
        self.index_csv.append_rows([{
            "Purchase Date": DATE, "Order or Receipt Number": number,
            "Purchase Summary": summary, "Document Type": "Receipt", "PDF Filename": name,
            "PDF Full Path": str(path), "Processing Status": "Completed", "Notes": ""}])
        self.order_csv.append_rows([{
            "Purchase Date": DATE, "Order or Receipt Number": number,
            "Purchase Summary": summary, "PDF Filename": name,
            "Processing Status": "Completed", "Notes": ""}])
        self.progress.update("Online:" + number, {
            "order_number": number, "purchase_date": DATE, "summary": summary,
            "pdf_path": str(path), "pdf_filename": name, "downloaded_ok": True})
        return path


def wanted(summary: str) -> str:
    """The name Rename gives a purchase of this summary."""
    return storage.build_pdf_filename(DATE, summary, "Receipt", record={"summary": summary})


def where_its_ledgers_say(shop: Shop, names: dict) -> None:
    """Each purchase's receipt is under the name given, holding its own
    bytes, nothing else is in the folder, and the index, the order history
    and the run state name it so, the run state both in memory and as the
    app saves it on its way out."""
    assert sorted(os.listdir(shop.folder)) == sorted(names.values())
    for number, name in names.items():
        assert (shop.folder / name).read_bytes() == body_of(number), name
    index = {r["Order or Receipt Number"]: r for r in storage.CsvFile(
        shop.out / INDEX, INDEX_COLUMNS).read_all()}
    history = {r["Order or Receipt Number"]: r for r in storage.CsvFile(
        shop.out / HISTORY, HISTORY_COLUMNS).read_all()}
    shop.progress.save()
    saved = storage.JsonStore(shop.out / "progress.json")
    saved.load()
    for number, name in names.items():
        path = str(shop.folder / name)
        assert (index[number]["PDF Full Path"], index[number]["PDF Filename"]) == (path, name)
        assert history[number]["PDF Filename"] == name
        for records in (shop.progress.data, saved.data):
            rec = records["Online:" + number]
            assert (rec["pdf_path"], rec["pdf_filename"]) == (path, name)


class Refusals:
    """Writes to refuse, by file name and how many times, after letting
    `skip` of them through, each refused as a write gives up when the file
    stayed held through its minute, unless `error` says otherwise."""

    def __init__(self):
        self.left = {}
        self.skip = {}
        self.error = PermissionError
        self.errors = {}               # a file name -> the error its writes meet instead


@pytest.fixture
def refuse(monkeypatch):
    real = storage.atomic_write_text
    refusals = Refusals()

    def write(path, text, encoding="utf-8"):
        name = Path(path).name
        if refusals.skip.get(name):
            refusals.skip[name] -= 1
        elif refusals.left.get(name):
            refusals.left[name] -= 1
            raise refusals.errors.get(name, refusals.error)(
                "%s stayed locked. Close the program using it and re-run." % path)
        return real(path, text, encoding)

    monkeypatch.setattr(storage, "atomic_write_text", write)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return refusals


def renamed(shop: Shop):
    """Rename with --apply, its exit code and what it said."""
    said = []
    try:
        renaming.run_for(shop, apply_changes=True, say=said.append)
        code = 0
    except SystemExit as stop:
        code = stop.code
    return code, " ".join(" ".join(said).split())


def two_purchases(tmp_path):
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", "old one.pdf")
    shop.bought("ORD2", "Beta", "old two.pdf")
    return shop, {"ORD1": "old one.pdf", "ORD2": "old two.pdf"}


@contextmanager
def held_like_excel(path: Path, share: int = 1):
    """The file held open as Excel holds a workbook it has open, letting
    others read it and nothing more (FILE_SHARE_READ) unless `share` says
    otherwise. Released on the way out, or earlier by calling what it
    yields."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, open_existing = 0x80000000, 3
    handle = k32.CreateFileW(str(path), generic_read, share, None, open_existing, 0, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    held = [True]

    def release():
        if held[0]:
            k32.CloseHandle(handle)
            held[0] = False

    try:
        yield release
    finally:
        release()


# -- a write that fails after the files moved ----------------------------------

def test_an_index_that_cannot_be_written_puts_every_file_back(tmp_path, refuse):
    shop, before = two_purchases(tmp_path)
    refuse.left[INDEX] = 1
    code, said = renamed(shop)
    assert code == 1, "the panel would have said the files were renamed"
    where_its_ledgers_say(shop, before)
    assert ("%s could not be written (PermissionError), so every file was put back under "
            "the name it had and nothing was renamed." % INDEX) in said
    assert "Close any program that has %s open and run Rename again." % INDEX in said
    assert "Renamed" not in said


def test_the_next_rename_offers_every_file_again_and_does_it(tmp_path, refuse):
    """What went wrong before. The next Rename found every row's file gone
    and said every file was already named the way this app names them."""
    shop, before = two_purchases(tmp_path)
    refuse.left[INDEX] = 1
    assert renamed(shop)[0] == 1
    said = []
    renaming.run_for(shop, apply_changes=False, say=said.append)
    assert "2 file(s) would be renamed." in said
    code, said = renamed(shop)
    assert code == 0 and "Renamed 2 file(s)." in said
    where_its_ledgers_say(shop, {"ORD1": wanted("Alpha"), "ORD2": wanted("Beta")})


def test_an_order_history_that_cannot_be_written_puts_the_index_back_too(tmp_path, refuse):
    shop, before = two_purchases(tmp_path)
    refuse.left[HISTORY] = 1
    code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert "%s could not be written (PermissionError)" % HISTORY in said


def test_a_run_state_that_cannot_be_saved_puts_both_csvs_back(tmp_path, refuse):
    """The run state is written last, and every app saves it again on its
    way out, so the records in memory have to be put back as well."""
    shop, before = two_purchases(tmp_path)
    refuse.left["progress.json"] = 1
    code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert "progress.json could not be written (PermissionError)" in said


def test_ctrl_c_while_the_index_is_written_puts_every_file_back(tmp_path, refuse):
    shop, before = two_purchases(tmp_path)
    refuse.left[INDEX], refuse.error = 1, KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        renaming.run_for(shop, apply_changes=True, say=lambda *_a: None)
    where_its_ledgers_say(shop, before)


def test_a_mistake_while_writing_puts_every_file_back_and_is_still_shown(tmp_path, refuse):
    shop, before = two_purchases(tmp_path)
    refuse.left[INDEX], refuse.error = 1, ValueError
    with pytest.raises(ValueError):
        renaming.run_for(shop, apply_changes=True, say=lambda *_a: None)
    where_its_ledgers_say(shop, before)


def test_files_that_swapped_names_swap_back(tmp_path, refuse):
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", wanted("Beta"))
    shop.bought("ORD2", "Beta", wanted("Alpha"))
    refuse.left[INDEX] = 1
    assert renamed(shop)[0] == 1
    where_its_ledgers_say(shop, {"ORD1": wanted("Beta"), "ORD2": wanted("Alpha")})


def test_a_chain_and_a_ring_of_three_go_back(tmp_path, refuse):
    """A file whose old name another took goes back after that one, and
    three that each took another's name go back through a name aside."""
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", "old one.pdf")       # to Alpha, which ORD2 has
    shop.bought("ORD2", "Beta", wanted("Alpha"))      # to Beta, free
    shop.bought("ORD3", "Gamma", wanted("Delta"))     # the ring of three
    shop.bought("ORD4", "Delta", wanted("Epsilon"))
    shop.bought("ORD5", "Epsilon", wanted("Gamma"))
    before = {"ORD1": "old one.pdf", "ORD2": wanted("Alpha"), "ORD3": wanted("Delta"),
              "ORD4": wanted("Epsilon"), "ORD5": wanted("Gamma")}
    said = []
    renaming.run_for(shop, apply_changes=False, say=said.append)
    assert "5 file(s) would be renamed." in said, said
    refuse.left[INDEX] = 1
    assert renamed(shop)[0] == 1
    where_its_ledgers_say(shop, before)


def test_a_name_changed_only_in_letter_case_is_changed_back(tmp_path, refuse):
    shop = Shop(tmp_path)
    old = wanted("Alpha").lower()
    assert old != wanted("Alpha")
    shop.bought("ORD1", "Alpha", old)
    refuse.left[INDEX] = 1
    assert renamed(shop)[0] == 1
    where_its_ledgers_say(shop, {"ORD1": old})


def test_a_file_that_cannot_go_back_is_named_and_nothing_is_written_over(tmp_path, refuse,
                                                                          monkeypatch):
    """Something took one file's old name while the index was waited for.
    That file stays where it is, named by both its names, and the file that
    took the name is left alone."""
    shop, _before = two_purchases(tmp_path)
    real_apply = renaming.apply

    def apply_then_taken(changes, say=print):
        result = real_apply(changes, say=say)
        (shop.folder / "old one.pdf").write_bytes(b"%PDF- somebody else's")
        return result

    monkeypatch.setattr(renaming, "apply", apply_then_taken)
    refuse.left[INDEX] = 1
    code, said = renamed(shop)
    assert code == 1
    assert sorted(os.listdir(shop.folder)) == sorted(["old one.pdf", "old two.pdf",
                                                      wanted("Alpha")])
    assert (shop.folder / "old one.pdf").read_bytes() == b"%PDF- somebody else's"
    assert (shop.folder / wanted("Alpha")).read_bytes() == body_of("ORD1")
    assert (shop.folder / "old two.pdf").read_bytes() == body_of("ORD2")
    assert ("so Rename put back the files it had renamed, all but 1. The index and the "
            "run state still give each of those the name it had, so rename each back to "
            "it by hand. %s back to old one.pdf" % wanted("Alpha")) in said


def test_when_no_file_can_go_back_it_says_so(tmp_path, refuse, monkeypatch):
    shop, _before = two_purchases(tmp_path)
    real_apply = renaming.apply

    def apply_then_taken(changes, say=print):
        result = real_apply(changes, say=say)
        for name in ("old one.pdf", "old two.pdf"):
            (shop.folder / name).write_bytes(b"%PDF- somebody else's")
        return result

    monkeypatch.setattr(renaming, "apply", apply_then_taken)
    refuse.left[INDEX] = 1
    code, said = renamed(shop)
    assert code == 1
    assert ("%s could not be written (PermissionError), and Rename could not put back the "
            "files it had renamed. The index and the run state still give each of those the "
            "name it had" % INDEX) in said
    assert "all but" not in said
    assert "%s back to old one.pdf" % wanted("Alpha") in said
    assert "%s back to old two.pdf" % wanted("Beta") in said


def test_a_file_a_ring_left_aside_goes_home_with_the_rest(tmp_path, refuse, monkeypatch):
    """Two files swapping names. The first went aside under ".renaming" and
    was refused its new name, and the second, refused its way back, kept
    the first one's old name, so apply left the first aside with the index
    and the run state to name it there. With the index refused after that,
    every file still has to go home, the one aside too, and nothing is
    counted twice for being both renamed and aside."""
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", wanted("Beta"))
    shop.bought("ORD2", "Beta", wanted("Alpha"))
    real_rename, real_apply = Path.rename, renaming.apply
    holding, refused = [False], []

    def rename(self, target):
        # A program holding both while apply runs, and neither after it.
        if holding[0] and (self.name.endswith(".renaming") or (
                self.name == wanted("Beta") and Path(target).name == wanted("Alpha"))):
            refused.append((self.name, Path(target).name))
            raise PermissionError(32, "held by another process", str(self))
        return real_rename(self, target)

    def apply_while_held(changes, say=print):
        holding[0] = True
        try:
            result = real_apply(changes, say=say)
        finally:
            holding[0] = False
        assert list(result.stranded) == [str(shop.folder / (wanted("Beta") + ".renaming"))]
        assert result.mapping[str(shop.folder / wanted("Beta"))] == str(
            shop.folder / (wanted("Beta") + ".renaming")), "the ledgers would name it aside"
        return result

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(renaming, "apply", apply_while_held)
    refuse.left[INDEX] = 1
    code, said = renamed(shop)
    assert (wanted("Beta") + ".renaming", wanted("Alpha")) in refused, refused
    assert (wanted("Beta"), wanted("Alpha")) in refused, refused
    assert code == 1
    where_its_ledgers_say(shop, {"ORD1": wanted("Beta"), "ORD2": wanted("Alpha")})
    assert "every file was put back under the name it had and nothing was renamed" in said


def test_a_ledger_that_cannot_be_written_back_points_to_its_copy(tmp_path, refuse):
    """The order history refused after the index was written, and the
    index refused too when it was to be written back. The files go home,
    and the index is named as still naming the new names, with the copy it
    had before in Backups."""
    shop, before = two_purchases(tmp_path)
    refuse.left[HISTORY] = 1
    refuse.skip[INDEX], refuse.left[INDEX] = 1, 1
    code, said = renamed(shop)
    assert code == 1
    assert sorted(os.listdir(shop.folder)) == sorted(before.values())
    assert ("%s could not be put back either, so it still names the files by their new "
            "names. The copy it had before this Rename is in the Backups folder." % INDEX) in said
    index = storage.CsvFile(shop.out / INDEX, INDEX_COLUMNS).read_all()
    assert [r["PDF Filename"] for r in index] == [wanted("Alpha"), wanted("Beta")]
    # The write back that failed made a copy of the new names first, so
    # the copy from before this Rename is one of two.
    copies = [[r["PDF Filename"] for r in storage.CsvFile(p, INDEX_COLUMNS).read_all()]
              for p in (shop.out / "Backups").glob("Testco Receipt Index.*.csv.bak")]
    assert ["old one.pdf", "old two.pdf"] in copies, copies


def test_a_stuck_file_is_not_said_to_be_named_by_an_index_left_on_new_names(tmp_path, refuse,
                                                                             monkeypatch):
    shop, _before = two_purchases(tmp_path)
    real_apply = renaming.apply

    def apply_then_taken(changes, say=print):
        result = real_apply(changes, say=say)
        (shop.folder / "old one.pdf").write_bytes(b"%PDF- somebody else's")
        return result

    monkeypatch.setattr(renaming, "apply", apply_then_taken)
    refuse.left[HISTORY] = 1
    refuse.skip[INDEX], refuse.left[INDEX] = 1, 1
    code, said = renamed(shop)
    assert code == 1
    assert ("all but 1. The run state still gives each of those the name it had, so rename "
            "each back to it by hand.") in said
    assert "The index and the run state still give" not in said
    assert "%s could not be put back either" % INDEX in said


def test_ctrl_c_while_a_ledger_is_written_back_still_sends_the_files_home(tmp_path, refuse):
    """The order history refused after the index was written, and Ctrl+C
    pressed while the index waited to be written back. That stops the wait,
    and the files go home all the same."""
    shop, before = two_purchases(tmp_path)
    refuse.left[HISTORY] = 1
    refuse.skip[INDEX], refuse.left[INDEX] = 1, 1
    refuse.errors[INDEX] = KeyboardInterrupt
    try:
        code, said = renamed(shop)
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C in the write back left the files under their new names")
    assert code == 1
    assert sorted(os.listdir(shop.folder)) == sorted(before.values())
    assert "%s could not be put back either" % INDEX in said


def test_a_file_two_rows_name_goes_home_once(tmp_path, refuse):
    """Download again saved a deleted receipt under its old name and wrote
    a second row for it, and the other purchase wants that file's name.
    apply renames the file once for both rows, and it goes back once too,
    after the other purchase's receipt has left its name."""
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", wanted("Beta"))
    shop.bought("ORD2", "Beta", "old two.pdf")
    shop.bought("ORD1", "Alpha", wanted("Beta"))      # Download again, a second row
    refuse.left[INDEX] = 1
    code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, {"ORD1": wanted("Beta"), "ORD2": "old two.pdf"})
    assert "every file was put back under the name it had and nothing was renamed" in said


@on_windows
def test_a_file_held_open_after_it_was_renamed_stays_named_by_both_names(tmp_path, refuse,
                                                                         monkeypatch):
    """A PDF viewer or a virus scanner had a renamed file through the few
    tries the put back makes. The index and the run state still name it by
    its old name, which is free, so that is the name Rename gives it back by
    hand."""
    shop, _before = two_purchases(tmp_path)
    real_apply = renaming.apply
    holding = []

    def apply_then_held(changes, say=print):
        result = real_apply(changes, say=say)
        holding.append(held_like_excel(shop.folder / wanted("Alpha")))
        holding[0].__enter__()
        return result

    monkeypatch.setattr(renaming, "apply", apply_then_held)
    refuse.left[INDEX] = 1
    try:
        code, said = renamed(shop)
    finally:
        holding[0].__exit__(None, None, None)
    assert code == 1
    assert sorted(os.listdir(shop.folder)) == sorted(["old two.pdf", wanted("Alpha")])
    assert (shop.folder / wanted("Alpha")).read_bytes() == body_of("ORD1")
    assert "all but 1" in said and "%s back to old one.pdf" % wanted("Alpha") in said
    index = storage.CsvFile(shop.out / INDEX, INDEX_COLUMNS).read_all()
    assert [r["PDF Filename"] for r in index] == ["old one.pdf", "old two.pdf"]


@pytest.fixture
def waits(monkeypatch):
    """Each pause a wait for a held file takes, without the pause."""
    paused = []
    monkeypatch.setattr("time.sleep", lambda s: paused.append(s))
    return paused


# -- a ledger held open before anything moves ----------------------------------

@on_windows
def test_an_index_open_in_excel_renames_nothing(tmp_path, waits, monkeypatch):
    shop, before = two_purchases(tmp_path)

    def never(*_a, **_kw):
        raise AssertionError("a file moved while the index could not be written")

    monkeypatch.setattr(renaming, "apply", never)
    with held_like_excel(shop.out / INDEX):
        code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert len(waits) == 30 and sum(waits) == 60, "it waits the minute a write waits"
    assert said.count("is open in another program") == 1
    assert ("Nothing was renamed, since %s could not be written, and Rename writes the new "
            "names into it as it renames. Close any program that has it open and run Rename "
            "again." % INDEX) in said


@on_windows
def test_the_run_state_held_open_renames_nothing_either(tmp_path, waits, monkeypatch):
    shop, before = two_purchases(tmp_path)
    monkeypatch.setattr(renaming, "apply", None)
    with held_like_excel(shop.out / "progress.json"):
        code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert "Nothing was renamed, since progress.json could not be written" in said


@on_windows
def test_two_ledgers_held_open_are_both_named(tmp_path, waits, monkeypatch):
    shop, before = two_purchases(tmp_path)
    monkeypatch.setattr(renaming, "apply", None)
    with held_like_excel(shop.out / INDEX), held_like_excel(shop.out / HISTORY):
        code, said = renamed(shop)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert ("Nothing was renamed, since %s and %s could not be written, and Rename writes "
            "the new names into them as it renames. Close any program that has them open "
            "and run Rename again." % (INDEX, HISTORY)) in said


@on_windows
def test_an_index_closed_while_rename_waits_is_renamed(tmp_path, monkeypatch):
    shop, _before = two_purchases(tmp_path)
    with held_like_excel(shop.out / INDEX) as release:
        paused = []

        def pause(seconds):
            paused.append(seconds)
            if len(paused) == 3:
                release()                       # Excel closed in the third pause

        monkeypatch.setattr("time.sleep", pause)
        code, said = renamed(shop)
    assert code == 0 and "Renamed 2 file(s)." in said, said
    where_its_ledgers_say(shop, {"ORD1": wanted("Alpha"), "ORD2": wanted("Beta")})


@on_windows
def test_an_index_opened_while_the_files_move_puts_them_back(tmp_path, waits, monkeypatch):
    """Excel opened the index after the check, while the files were
    renamed. The real write waits its minute for it, gives up, and every
    file goes back."""
    shop, before = two_purchases(tmp_path)
    real_apply = renaming.apply
    holding = []

    def apply_then_opened(changes, say=print):
        result = real_apply(changes, say=say)
        holding.append(held_like_excel(shop.out / INDEX))
        holding[0].__enter__()
        return result

    monkeypatch.setattr(renaming, "apply", apply_then_opened)
    try:
        code, said = renamed(shop)
    finally:
        holding[0].__exit__(None, None, None)
    assert code == 1
    where_its_ledgers_say(shop, before)
    assert len(waits) == 30, "the write waited its minute before it gave up"
    assert ("%s could not be written (PermissionError), so every file was put back under "
            "the name it had and nothing was renamed." % INDEX) in said


@on_windows
def test_nothing_to_rename_never_waits_for_a_held_index(tmp_path, waits):
    shop = Shop(tmp_path)
    shop.bought("ORD1", "Alpha", wanted("Alpha"))
    with held_like_excel(shop.out / INDEX):
        code, said = renamed(shop)
    assert code == 0 and not waits
    assert "Every file is already named the way this app names them." in said


# -- free_to_write ---------------------------------------------------------------

def test_a_free_file_is_free_and_left_as_it_was(tmp_path, waits):
    f = tmp_path / "index.csv"
    f.write_bytes(b"a,b\r\n1,2\r\n")
    before = os.stat(f)
    assert storage.free_to_write(f, say=lambda *_a: None)
    after = os.stat(f)
    assert f.read_bytes() == b"a,b\r\n1,2\r\n"
    assert (after.st_mtime_ns, after.st_ino) == (before.st_mtime_ns, before.st_ino)
    assert not waits


def test_a_file_not_there_yet_is_free(tmp_path, waits):
    assert storage.free_to_write(tmp_path / "nothing yet.csv", say=lambda *_a: None)
    assert not (tmp_path / "nothing yet.csv").exists()
    assert not waits


@on_windows
@pytest.mark.parametrize("share", [1, 3], ids=["like Excel", "readers and writers"])
def test_a_held_file_is_not_free_after_the_minute(tmp_path, waits, share):
    """Excel lets others read. A program that lets others write as well
    but not delete, as Python's own open does, keeps the file from being
    replaced just the same, though opening it for writing would pass."""
    f = tmp_path / "index.csv"
    f.write_bytes(b"a,b\r\n")
    said = []
    with held_like_excel(f, share=share):
        assert not storage.free_to_write(f, say=said.append)
    assert len(waits) == 30
    assert said == ["  ! index.csv is open in another program, Excel perhaps. Close it, and "
                    "this waits up to 60 seconds for it."]
