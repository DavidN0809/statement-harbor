"""A history moved with --minimal skips what the old computer skipped.

tools/migrate.py --minimal writes only the fields a skip decision reads, so
a history can move to another computer with far less of a person's
purchases and accounts in it. A field an app's _already_done reads that the
tool leaves out makes that app download again on the new computer what it
saved before, and quietly, since a second download looks like a first.
Robinhood finds a tax form listed again without its year through the
undated key it was saved under, and a crypto statement saved under its old
key through the page that listed it, and --minimal carried neither.

So it is asked two ways. By reading, every record field each app's
_already_done reads, followed through what it calls in the app's own
modules and in the core, is one the tool carries for that app's provider.
So is every field read off a record any method of the app walks to among
all the saved ones, since American Family looks there for another bill's
statement with the very bytes it just took, and with nothing to compare
saved a statement of one bill as another's. By running, each app's own
_already_done answers the same for a record and for that record as
--minimal cuts it, over every state, marker, note, day and review copy a
record holds, and Robinhood's records go through a real export and import,
as American Family's do in its own suite. Every name and number is
invented.
"""
import argparse
import ast
import importlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from paperpull_core import not_shown
from paperpull_core import storage as core_storage
from paperpull_core.models import State

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "paperpull_core"

sys.path.insert(0, str(REPO / "tools"))
migrate = pytest.importorskip("migrate")

# Dicts a skip decision reads that are not a record. Anything else it reads
# a field of is taken for a record, so a new one is looked at, not passed.
NOT_RECORDS = {"self.config"}

# A field read only inside one core function, which the tool carries
# exactly when that function needs it. _skip_fields keeps a record's last
# note when not_shown.asked_again holds, the only note that reads.
CARRIED_FOR = {("paperpull_core.not_shown", "asked_again"): {"notes"}}

# Fields an app's skip decisions read that decide nothing, each with why. One
# no longer read fails, so the list cannot outlive its reason.
DECIDES_NOTHING = {
    "robinhood": {
        "period": "copied onto a form moved to the key of its year",
        "tax_year": "read off the page's listing of the form, not a saved record",
    },
}

# Methods that walk the saved records only to put right what Rename reads,
# never to decide a download, each with why. A record without the fields
# matches nothing there and changes nothing. One that no longer walks fails.
WALKS_FOR_RENAME = {
    "golden1": {
        "_carry_index_rows": "gives an index row the title its record was carried to, "
                             "and the index does not move with a history",
    },
}


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))
IDS = [d.name for d in APPS]


def provider_of(app: Path) -> str:
    """The provider the tool reads from the install's storage.py."""
    found = migrate.PROVIDER_RE.search((app / "storage.py").read_text(encoding="utf-8"))
    return found.group(1) if found else app.name


# -- by reading ---------------------------------------------------------------

class Module:
    """One module's functions, string constants and imports, by the names
    its own code reaches them by."""

    def __init__(self, name: str, path: Path):
        self.name = name
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        self.funcs, self.consts, self.aliases, self.imported = {}, {}, {}, {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.funcs.setdefault("self." + sub.name, sub)
                        self.funcs["%s.%s" % (node.name, sub.name)] = sub
            elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.consts[target.id] = node.value.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.aliases[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom):
                # The core's own modules import each other relatively.
                source = ("paperpull_core" + ("." + node.module if node.module else "")
                          if node.level else node.module)
                for a in node.names:
                    if source == "paperpull_core":
                        self.aliases[a.asname or a.name] = "paperpull_core." + a.name
                    elif source:
                        self.imported[a.asname or a.name] = (source, a.name)


CORE_MODULES = {"paperpull_core." + p.stem: Module("paperpull_core." + p.stem, p)
                for p in sorted(CORE.glob("*.py"))}


def modules_of(app: Path) -> dict:
    found = dict(CORE_MODULES)
    for path in sorted(app.glob("*.py")):
        found[path.stem] = Module(path.stem, path)
    return found


def _string(node, mod: Module, modules: dict):
    """The string a key expression holds, a constant or a name for one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in mod.consts:
            return mod.consts[node.id]
        source = mod.imported.get(node.id)
        if source and source[0] in modules:
            return modules[source[0]].consts.get(source[1])
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        other = modules.get(mod.aliases.get(node.value.id, ""))
        if other is not None:
            return other.consts.get(node.attr)
    return None


def _reads(fn, mod: Module, modules: dict):
    """(dict expression, key) for every key this function reads."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "pop", "setdefault") and node.args):
            key = _string(node.args[0], mod, modules)
            if key is not None:
                yield ast.unparse(node.func.value), key
        elif isinstance(node, ast.Subscript):
            key = _string(node.slice, mod, modules)
            if key is not None:
                yield ast.unparse(node.value), key
        elif (isinstance(node, ast.Compare)
                and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)):
            key = _string(node.left, mod, modules)
            if key is not None:
                yield ast.unparse(node.comparators[0]), key


def _callee(call: ast.Call, mod: Module, modules: dict):
    """(module, function) a call reaches in the app or the core, or None."""
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in mod.funcs:
            return mod, mod.funcs[f.id]
        source = mod.imported.get(f.id)
        other = modules.get(source[0]) if source else None
        if other is not None and source[1] in other.funcs:
            return other, other.funcs[source[1]]
        return None
    if isinstance(f, ast.Attribute):
        base = ast.unparse(f.value)
        name = "%s.%s" % (base, f.attr)
        if name in mod.funcs:
            return mod, mod.funcs[name]
        other = modules.get(mod.aliases.get(base, ""))
        if other is not None and f.attr in other.funcs:
            return other, other.funcs[f.attr]
    return None


def _finds_a_saved_record(fn) -> bool:
    """A function that goes through every saved record and asks whether one
    is done, to find the saved copy of a listed document."""
    walks = any(isinstance(n, (ast.For, ast.comprehension))
                and "self.progress.data" in ast.unparse(n.iter) for n in ast.walk(fn))
    asks = any(isinstance(n, ast.Call) and ast.unparse(n.func).endswith("is_done")
               for n in ast.walk(fn))
    return walks and (asks or "'downloaded_ok'" in ast.unparse(fn))


def skip_decisions(app: Path, mod: Module):
    """The app's _already_done, and every other method of its App that
    finds a saved record of a listed document, as Robinhood does for a tax
    form the page now lists under its year."""
    start = mod.funcs.get("App._already_done")
    assert start is not None, "%s has no App._already_done to read" % app.name
    return [start] + [fn for name, fn in sorted(mod.funcs.items())
                      if name.startswith("App.") and fn is not start
                      and _finds_a_saved_record(fn)]


def fields_read(app: Path) -> dict:
    """{field: [where]} for every record field the app's skip decisions
    read, and everything they call in the app's own modules and the core."""
    modules = modules_of(app)
    mod = modules[entry_of(app).stem]
    found, seen = {}, set()
    todo = [(mod, fn) for fn in skip_decisions(app, mod)]
    while todo:
        mod, fn = todo.pop()
        if id(fn) in seen:
            continue
        seen.add(id(fn))
        for obj, key in _reads(fn, mod, modules):
            if obj in NOT_RECORDS or key in CARRIED_FOR.get((mod.name, fn.name), ()):
                continue
            found.setdefault(key, []).append("%s.%s" % (mod.name, fn.name))
        for call in ast.walk(fn):
            if isinstance(call, ast.Call):
                reached = _callee(call, mod, modules)
                if reached is not None:
                    todo.append(reached)
    return found


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_field_a_skip_decision_reads_goes_with_minimal(app):
    read = fields_read(app)
    # Not a census of nothing. Every skip decision reads both of these.
    assert {"downloaded_ok", "state"} <= set(read), (app.name, sorted(read))
    idle = DECIDES_NOTHING.get(app.name, {})
    assert set(idle) <= set(read), (app.name, "no longer read", set(idle) - set(read))
    carried = set(migrate.skip_fields_of(provider_of(app)))
    left_out = {k: v for k, v in read.items() if k not in carried and k not in idle}
    assert not left_out, (
        "%s's skip decisions read %s, which --minimal leaves out, so a history "
        "moved with it is downloaded again. Carry it in tools/migrate.py "
        "(PROVIDER_SKIP_FIELDS when only this app reads it) if it names no "
        "person or account, or say in the tool's docstring what --minimal "
        "then carries" % (app.name, left_out))


# -- every walk of the saved records ------------------------------------------

# A loop or comprehension over every saved record, by its records or by its
# keys and records, however the progress store is spelled around it.
WALK = re.compile(r"self\.progress\.data(?: or \{\}\))?\.(items|values)\(\)")


def _record_reads(scope, names, mod: Module, modules: dict):
    """Each field read off a record bound to one of `names` in `scope`. A
    field written is not read."""
    for obj, key in _reads(scope, mod, modules):
        if obj in names:
            yield key


def _walks(fn):
    """(the loop or comprehension's scope, the name it binds to each record)
    for each walk of the saved records in `fn`."""
    parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(fn):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        found = WALK.search(ast.unparse(node.iter))
        target = node.target
        if found and found.group(1) == "items" and isinstance(target, ast.Tuple):
            target = target.elts[-1]
        if found and isinstance(target, ast.Name):
            yield (node if isinstance(node, ast.For) else parents[node]), target.id


def walk_reads(app: Path) -> dict:
    """{field: {method}} for every field read off a saved record that a
    method of the app's App walks to, followed into what it hands that
    record to in the app's own modules and the core. By what the code does,
    whatever the method is called, as American Family's download_one looks
    for another bill's statement with the very bytes just taken."""
    modules = modules_of(app)
    mod = modules[entry_of(app).stem]
    todo = [(name[len("App."):], mod, scope, frozenset([bound]))
            for name, fn in sorted(mod.funcs.items()) if name.startswith("App.")
            for scope, bound in _walks(fn)]
    found, seen = {}, set()
    while todo:
        start, mod, scope, names = todo.pop()
        if (id(scope), names) in seen:
            continue
        seen.add((id(scope), names))
        for key in _record_reads(scope, names, mod, modules):
            found.setdefault(key, set()).add(start)
        for call in ast.walk(scope):
            if not isinstance(call, ast.Call):
                continue
            at = [i for i, a in enumerate(call.args) if isinstance(a, ast.Name) and a.id in names]
            named = {k.arg for k in call.keywords
                     if k.arg and isinstance(k.value, ast.Name) and k.value.id in names}
            reached = _callee(call, mod, modules) if (at or named) else None
            if reached is None:
                continue
            cmod, cfn = reached
            params = [a.arg for a in cfn.args.args]
            if params and params[0] in ("self", "cls"):
                params = params[1:]
            bound = {params[i] for i in at if i < len(params)} | named
            if bound:
                todo.append((start, cmod, cfn, frozenset(bound)))
    return found


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_walk_of_the_saved_records_reads_what_minimal_carries(app):
    read = walk_reads(app)
    idle = WALKS_FOR_RENAME.get(app.name, {})
    walking = {start for starts in read.values() for start in starts}
    assert set(idle) <= walking, (app.name, "no longer walks", set(idle) - walking)
    idle_fields = DECIDES_NOTHING.get(app.name, {})
    carried = set(migrate.skip_fields_of(provider_of(app)))
    left_out = {k: sorted(v) for k, v in read.items()
                if k not in carried and k not in idle_fields and not v <= set(idle)}
    assert not left_out, (
        "%s walks its saved records and reads %s, which --minimal leaves out, "
        "so on a new computer that check finds nothing. Carry it in "
        "tools/migrate.py (PROVIDER_SKIP_FIELDS) if it names no person or "
        "account, and say so in the tool's docstring" % (app.name, left_out))


def test_the_walk_census_reads_american_familys_twin_check():
    """Not a census of nothing. The check that found American Family's
    statement with another bill's bytes, and Robinhood's of a crypto
    statement with the individual one's."""
    amfam = walk_reads(REPO / "apps" / "amfam")
    assert {"pdf_sha256", "date", "account"} <= {k for k, v in amfam.items()
                                                 if "download_one" in v}, amfam
    robinhood = walk_reads(REPO / "apps" / "robinhood")
    assert {"pdf_sha256", "source_url"} <= {k for k, v in robinhood.items()
                                            if "_other_accounts_statement" in v}, robinhood


def test_a_provider_list_carries_only_what_that_app_reads():
    """Every field carried for one provider is a field its skip decisions
    or a walk of its saved records read, and every provider named is an
    app's, or a name nobody uses would carry nothing and a field nobody
    reads would carry for nothing."""
    by_provider = {provider_of(app): app for app in APPS}
    for provider, fields in migrate.PROVIDER_SKIP_FIELDS.items():
        assert provider in by_provider, provider
        app = by_provider[provider]
        read = set(fields_read(app)) | set(walk_reads(app))
        assert set(fields) <= read, (provider, set(fields) - read)


def test_every_app_is_read():
    """The apps with an entry script, every one of them."""
    assert len(APPS) >= 65, IDS


# -- by running ---------------------------------------------------------------

def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


@pytest.fixture
def loading(monkeypatch):
    """What loading an app sets in the core, put back after."""
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    return load


def app_over(mod, folder: Path, records: dict):
    """The app's own downloader over these records, without its __init__,
    which would want a config file and a browser."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "owner": ""}
    inst.args = argparse.Namespace(redownload=False)
    inst.paths = storage.Paths(folder)
    inst.paths.ensure()
    # Loaded first, or the first read loads the folder's file over these.
    inst.progress = storage.JsonStore(inst.paths.progress_json)
    inst.progress.load()
    inst.progress.data = records
    inst.discovery = storage.JsonStore(inst.paths.discovery_json)
    inst.discovery.load()
    return inst


class Listed:
    """A document or purchase listed again under KEY, with nothing else
    known of it."""

    key = "listed:1"

    def __getattr__(self, name):
        return ""


def opening_pdf(path: Path) -> Path:
    """A one page PDF of invented words that opens."""
    from pypdf import PdfWriter
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 200})
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


# What else a record holds, which --minimal leaves out.
HISTORY = {"title": "Invented Monthly Statement", "summary": "Invented Statement",
           "account": "INVENTED *0000", "total": "12.34", "items": "Garden Hose",
           "order_number": "INV0001", "document_id": "DOC0001",
           "date": "2026-05-14", "category": "Statement", "store_info": "Main St",
           "source_url": "https://statements.example.invalid/page",
           "undated_key": "Statement::Invented_Monthly_Statement:",
           "pdf_filename": "2026-05-14 Invented Statement.pdf", "pdf_size": "4096",
           "pdf_sha256": "ab" * 32}


def records(folder: Path):
    """A record of every state a record can hold, with and without the
    marker, a note an older version wrote or a later one, the days a
    receipt page showed nothing, and a review copy that opens, is gone or
    was never kept."""
    saved = str(opening_pdf(folder / "review" / "copy.pdf"))
    gone = str(folder / "review" / "gone.pdf")
    old_note = sorted(not_shown.OLD_NOTES)[0]
    days = ["2031-01-0%d" % d for d in range(1, not_shown.DAYS + 1)]
    for state in [s.value for s in State] + [""]:
        for marker in (None, False, True):
            for notes in (None, "Listed; " + old_note, "Listed; Invented later note"):
                for shown in (None, days):
                    for path in ("", saved, gone):
                        rec = dict(HISTORY, state=state, pdf_path=path,
                                   discovered_at="2031-01-01T10:00:00")
                        for field, value in (("downloaded_ok", marker), ("notes", notes),
                                             (not_shown.DAYS_KEY, shown)):
                            if value is not None:
                                rec[field] = value
                        yield rec


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_app_skips_a_minimal_record_as_it_skipped_the_whole_one(app, loading, tmp_path):
    mod = loading(app)
    provider = provider_of(app)
    inst = app_over(mod, tmp_path / "out", {})
    answers, differ = set(), []
    for rec in records(tmp_path):
        inst.progress.data = {Listed.key: rec}
        whole = bool(inst._already_done(Listed()))
        inst.progress.data = {Listed.key: migrate._skip_fields(rec, provider)}
        cut = bool(inst._already_done(Listed()))
        answers.add(whole)
        if cut != whole:
            differ.append((whole, {k: rec.get(k) for k in
                                   ("state", "downloaded_ok", "notes", "pdf_path")}))
    assert answers == {True, False}, (app.name, answers)
    assert not differ, (app.name, len(differ), differ[:3])


# -- Robinhood, through the tool ----------------------------------------------

ROBINHOOD = REPO / "apps" / "robinhood"


def computers(tmp_path: Path):
    """A Robinhood install on one computer and a fresh one on another, each
    an output folder with its own storage.py, as the tool finds them."""
    found = []
    for side in ("old", "new"):
        out = tmp_path / side / "Robinhood Statements"
        out.mkdir(parents=True)
        shutil.copy(ROBINHOOD / "storage.py", out / "storage.py")
        (out / "progress.json").write_text("{}", encoding="utf-8")
        found.append(out)
    return found


def moved(tmp_path: Path, old: Path, new: Path, records: dict, minimal=True) -> dict:
    """The records exported from the old computer's folder and imported
    into the new computer's."""
    (old / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    archive = tmp_path / "history.ppz"
    assert migrate.export(old.parent, archive, minimal=minimal) == 0
    assert migrate.do_import(archive, new.parent, assume_yes=True) == 0
    return json.loads((new / "progress.json").read_text(encoding="utf-8"))


def text_pdf(path: Path, lines) -> Path:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
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
    return path


def statement(mod, date="2010-01-31", account="", page=""):
    site = sys.modules["robinhood_site"]
    page = page or dict((a, u) for u, a in site.STATEMENT_PAGES)[account]
    return mod.Document(title="Invented Monthly Statement", category=mod.doc_types.STATEMENT,
                        summary="Monthly Statement", date=date, source_url=page,
                        account=account)


def saved(doc, **more) -> dict:
    return dict(doc.to_dict(), downloaded_ok=True, state=State.COMPLETED.value, **more)


def test_a_robinhood_tax_form_listed_again_without_its_year_stays_done(loading, tmp_path):
    """A form saved before its year was read is kept under its dated key,
    with the undated one it was saved under, for a page that lists it
    without a year again (#62)."""
    mod = loading(ROBINHOOD)
    site = sys.modules["robinhood_site"]
    tax = mod.doc_types.TAX
    undated = mod.Document(title="Invented Consolidated 1099", category=tax,
                           summary="Consolidated 1099", date="", source_url=site.TAX_URL)
    dated = mod.Document(title="Invented Consolidated 1099", category=tax,
                         summary="Consolidated 1099", date="2021-12-31", tax_year="2021",
                         source_url=site.TAX_URL)
    held = {dated.key: saved(dated, undated_key=undated.key)}
    old, new = computers(tmp_path)
    assert app_over(mod, old, held)._already_done(undated)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._already_done(undated), \
        "the form would be downloaded again on the new computer"
    assert got[dated.key]["undated_key"] == undated.key
    assert "summary" not in got[dated.key]


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_a_robinhood_tax_form_saved_without_a_date_moves_to_its_year(loading, tmp_path,
                                                                      minimal):
    """A form saved before its year was read, never opened since, is moved
    to the key its page now dates it by, read from its category, title and
    account and the year its file prints, here the file copied across. Or
    the form is downloaded again beside the copy already saved."""
    mod = loading(ROBINHOOD)
    site = sys.modules["robinhood_site"]
    tax = mod.doc_types.TAX
    old, new = computers(tmp_path)
    undated = mod.Document(title="Invented Consolidated 1099", category=tax,
                           summary="Consolidated 1099", date="", source_url=site.TAX_URL)
    pdf = text_pdf(app_over(mod, old, {}).paths.folder_for(tax) / "Invented 1099.pdf",
                   ["Invented Securities LLC", "2022 1099-DIV", "Tax Year 2022"])
    held = {undated.key: saved(undated, pdf_path=str(pdf))}

    got = moved(tmp_path, old, new, held, minimal=minimal)
    inst = app_over(mod, new, got)
    shutil.copy(pdf, Path(got[undated.key]["pdf_path"]))
    dated = mod.Document(title="Invented Consolidated 1099", category=tax,
                         summary="Consolidated 1099", date="2022-12-31", tax_year="2022",
                         source_url=site.TAX_URL)
    inst.discovery.data = {dated.key: dict(dated.to_dict(), state=State.DISCOVERED.value)}
    assert inst._date_saved_forms({dated.key}) == 1
    assert inst._already_done(dated), "the form would be downloaded again"


def test_another_accounts_saved_statement_is_known_after_the_move(loading, tmp_path):
    """A crypto statement with the very bytes of the individual statement
    saved for that date is that statement, not the crypto one, and goes to
    review. The saved statement is known by its account, date and digest,
    with no copy of its file on the new computer."""
    mod = loading(ROBINHOOD)
    old, new = computers(tmp_path)
    individual = statement(mod)
    held = {individual.key: saved(individual, pdf_sha256="ab" * 32)}
    crypto = statement(mod, account="Crypto")
    assert app_over(mod, old, held)._other_accounts_statement(crypto, "ab" * 32)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._other_accounts_statement(crypto, "ab" * 32), \
        "the individual statement would be saved again as the crypto one"


def test_a_robinhood_crypto_statement_under_its_old_key_stays_done(loading, tmp_path):
    """A crypto statement saved before its account was part of its key
    counts as done only when the crypto page listed it."""
    mod = loading(ROBINHOOD)
    crypto_page = statement(mod, account="Crypto").source_url
    old_doc = statement(mod, page=crypto_page)
    listed = statement(mod, account="Crypto")
    assert old_doc.key != listed.key
    held = {old_doc.key: saved(old_doc)}
    old, new = computers(tmp_path)
    assert app_over(mod, old, held)._already_done(listed)

    got = moved(tmp_path, old, new, held)
    assert app_over(mod, new, got)._already_done(listed), \
        "the statement would be downloaded again on the new computer"
    assert got[old_doc.key]["source_url"] == crypto_page
    assert "summary" not in got[old_doc.key]


@pytest.mark.parametrize("app_beside", [True, False], ids=["install", "folder-only"])
def test_a_second_persons_robinhood_history_carries_the_same(loading, tmp_path, app_beside):
    """A second person's folder sits beside the install, made by Add a
    person, and holds no storage.py of its own, so a folder with no app is
    named for itself. Its records are still Robinhood's, whether the app is
    still in the install beside it or only its storage.py is."""
    import add_account
    mod = loading(ROBINHOOD)
    crypto_page = statement(mod, account="Crypto").source_url
    old_doc = statement(mod, page=crypto_page)
    listed = statement(mod, account="Crypto")
    people = []
    for install in computers(tmp_path):
        if app_beside:
            shutil.copy(entry_of(ROBINHOOD), install / entry_of(ROBINHOOD).name)
        (install / "config.json").write_text(json.dumps(
            {"output_dir": ".", "cdp_url": "http://127.0.0.1:9226"}), encoding="utf-8")
        add_account.make_config(install, "Dana Example", taken=set())
        person = install.parent / ("%s - Dana Example" % install.name)
        assert person.is_dir() and not (person / "storage.py").exists()
        (person / "progress.json").write_text("{}", encoding="utf-8")
        people.append(person)

    got = moved(tmp_path, people[0], people[1], {old_doc.key: saved(old_doc)})
    assert app_over(mod, people[1], got)._already_done(listed), \
        "the second person's statement would be downloaded again"
    assert "summary" not in got[old_doc.key]


def test_another_app_does_not_carry_robinhoods_fields():
    """The same field can hold more in another app, so only Robinhood's
    records carry them."""
    rec = dict(HISTORY, state=State.COMPLETED.value, downloaded_ok=True)
    own = set(migrate.PROVIDER_SKIP_FIELDS["Robinhood"])
    assert own <= set(migrate._skip_fields(rec, "Robinhood"))
    for provider in ("", "Chase", "Target"):
        cut = migrate._skip_fields(rec, provider)
        assert not own & set(cut), (provider, cut)
