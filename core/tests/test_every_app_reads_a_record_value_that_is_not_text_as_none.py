"""A record value that is not text reads as none, in every app's load, Rename
and Review Names.

progress.json and discovery.json are files a person can open and edit, and
files a crash can leave damaged. Kroger read a record's store_info as text,
so a store_info that was a number in a record marked store_read stopped its
Rename and its Review Names with an AttributeError. Chase handed a record's
title and account to sanitize_component when it upgraded its old keys on
loading, so a title that was a number stopped every Chase command, Rename
included, before anything ran. AT&T made a key of a saved bill's account
and kind as it loaded, so an account that was a list stopped every AT&T
command.

The fields are found by what each app does, every key its own code reads
from a mapping and every field of the record class it builds from one, and
each is damaged in a record of its own, so no damaged field keeps the app
from reaching another. Each record holds every other field empty, as text,
as a value the app's code compares it with, or that and what a finished
download writes, so a field read only beside a marker (Kroger's
store_read), in one kind of record (Robinhood's tax forms) or in a saved
one (AT&T's bills) is reached. Each app runs its own Rename
through its own main, and each receipt app its own Review Names, over a
file the app holds whose own record is damaged as well. Every name, number
and file is invented.
"""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

from paperpull_core import doc_types
from paperpull_core import renaming
from paperpull_core import storage as core_storage
from paperpull_core.models import Purchase, State


def _harness(file: str, name: str):
    """A sibling test file, for the harness that builds an app as it is at
    home and runs its own Rename or Review Names."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renames = _harness("test_every_app_renames_only_a_file_it_holds.py", "not_text_rename_harness")
reviews = _harness("test_every_app_reviews_a_name_once.py", "not_text_review_harness")

# What a hand edit or a damaged file can leave where text belongs.
DAMAGED = {"a number": 5, "a list": ["Invented"], "a mapping": {"k": "Invented"}}
# A path and the names beside it are read through renaming, and
# test_every_app_renames_past_a_damaged_record.py damages them there. The
# held file's record keeps naming it here.
NAMING = {"pdf_path", "pdf_filename", "invoices", "items", "summary"}
# What a finished download writes in its record.
SAVED = {"date": "2026-05-14", "downloaded_ok": True, "state": State.COMPLETED.value,
         "pdf_size": 2000, "pdf_pages": 1}


def _code(app: Path):
    for file in [*sorted(app.glob("*.py")),
                 Path(core_storage.__file__).with_name("renaming.py")]:
        if not file.name.startswith("test_"):
            yield ast.parse(file.read_text(encoding="utf-8-sig"))


def _key(node):
    """The key a .get("key") or a ["key"] reads, or None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop", "setdefault") and node.args
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return node.args[0].value
    if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)):
        return node.slice.value
    if isinstance(node, ast.BoolOp):
        return next(filter(None, map(_key, node.values)), None)
    return None


def _strings(node) -> list:
    """The text a field is compared with, as written or as named
    (doc_types.TAX, State.COMPLETED.value)."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [v for e in node.elts for v in _strings(e)]
    if isinstance(node, ast.Attribute):
        try:
            value = eval(ast.unparse(node), {"doc_types": doc_types, "State": State})
        except Exception:
            return []
        return [value] if isinstance(value, str) else []
    return []


def _built_from_a_record(node) -> list:
    """The fields of a class the app builds from a record, one with a
    from_dict, by its __init__."""
    if not isinstance(node, ast.ClassDef):
        return []
    methods = {m.name: m for m in node.body if isinstance(m, ast.FunctionDef)}
    if "from_dict" not in methods or "__init__" not in methods:
        return []
    args = methods["__init__"].args
    return [a.arg for a in args.args[1:] + args.kwonlyargs]


def fields_of(app: Path) -> dict:
    """Every key the app's code reads that could name a record's field, a
    CSV column aside, with the first text its code compares it with, or
    None."""
    keys, compared = set(Purchase.__dataclass_fields__), {}
    for tree in _code(app):
        for node in ast.walk(tree):
            key = _key(node)
            if key:
                keys.add(key)
            keys.update(_built_from_a_record(node))
            if isinstance(node, ast.Compare) and _key(node.left):
                for value in (v for c in node.comparators for v in _strings(c)):
                    compared.setdefault(_key(node.left), value)
    return {k: compared.get(k) for k in sorted(keys)
            if k.isidentifier() and not k[:1].isupper()}


def records(fields: dict) -> dict:
    """Each way a record can hold the fields, empty, as text, as the app
    compares them, and that as a finished download left it."""
    compared = {f: v if v is not None else "Invented" for f, v in fields.items()}
    return {"empty": {f: "" for f in fields},
            "text": {f: "Invented" for f in fields},
            "compared": compared,
            "saved": dict(compared, **SAVED)}


def damaged_records(fields: dict) -> dict:
    """A record for each field, base and damaged value, the field damaged
    and the rest as the base holds them."""
    out = {}
    for base, rec in records(fields).items():
        for what, value in DAMAGED.items():
            for field in fields:
                if field not in NAMING:
                    out["Invented:%s %s %s" % (field, base, what)] = dict(rec, **{field: value})
    return out


def all_damaged(fields: dict):
    """Each base with every field damaged but the ones naming a file, with
    a name for it."""
    for base, rec in records(fields).items():
        for what, value in DAMAGED.items():
            yield "%s %s" % (base, what), dict(
                rec, **{f: value for f in fields if f not in NAMING})


def write(app, recs: dict):
    for path in (app.paths.progress_json, app.paths.discovery_json):
        had = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        path.write_text(json.dumps(dict(had, **recs)), encoding="utf-8")


def test_every_app_is_covered():
    """Every app, found by what it does, with the fields of the two crashes
    among those it reads."""
    assert len(renames.APPS) >= 61
    assert len(reviews.APPS) >= 14
    kroger = fields_of(renames.REPO / "apps" / "kroger")
    assert {"store_info", "store_read"} <= set(kroger)
    chase = fields_of(renames.REPO / "apps" / "chase")
    assert {"title", "account", "document_id", "period", "date_text"} <= set(chase)
    assert {"account", "category", "pdf_size"} <= set(fields_of(renames.REPO / "apps" / "att"))
    robinhood = fields_of(renames.REPO / "apps" / "robinhood")
    assert robinhood["category"] == doc_types.TAX


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return renames.Home(request.param, tmp_path, monkeypatch, capsys)


@pytest.mark.parametrize("home", renames.APPS, ids=renames.IDS, indirect=True)
def test_rename_finishes_past_a_record_value_that_is_not_text(home, monkeypatch):
    """--apply loads the records, reaches the rename and finishes, its index
    naming files that are there. Each file the app holds has its own record with every field
    damaged, and beside them is a record for each field damaged alone. A
    file whose record is so damaged may keep its name, as some apps name a
    file from its record."""
    fields = fields_of(home.app)
    app = home.build()
    filed = app.paths.folder_for(next(iter(core_storage.spec().routes), "Statement"))
    recs, held = damaged_records(fields), []
    for i, (name, rec) in enumerate(all_damaged(fields), 1):
        path = renames.pdf(filed / ("old name %d.pdf" % i), name)
        held.append(path)
        app.index_csv.append_rows([renames.a_row(app.index_csv.columns, i, path)])
        recs["Invented:held %d" % i] = dict(rec, pdf_path=str(path), pdf_filename=path.name)
    write(app, recs)
    ran, run_for = [], renaming.run_for
    monkeypatch.setattr(renaming, "run_for", lambda *a, **kw: ran.append(1) or run_for(*a, **kw))

    said, error = home.rename("--apply")

    assert error is None, "%s's Rename ended with %r\n%s" % (home.app.name, error, said[-1500:])
    assert ran, "%s's Rename stopped before renaming\n%s" % (home.app.name, said[-1500:])
    index = [Path(r["PDF Full Path"]) for r in home.build().index_csv.read_all()]
    assert len(index) == len(held) and all(p.is_file() for p in index), home.app.name


@pytest.mark.parametrize("app", reviews.APPS, ids=[a.name for a in reviews.APPS])
def test_review_names_finishes_past_a_record_value_that_is_not_text(app, tmp_path,
                                                                    monkeypatch, capsys):
    """Each receipt marked for review has every field of its own record
    damaged but its file's and its order number, by which the review tells
    it from another purchase, beside a record for each field damaged
    alone, and each is given its new name."""
    home = renames.Home(app, tmp_path, monkeypatch, capsys)
    inst = home.build()
    core_storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    fields = fields_of(app)
    filed = inst.paths.folder_for("Online")
    recs, old = damaged_records(fields), []
    for i, (name, rec) in enumerate(all_damaged(fields), 1):
        path = reviews.opening_pdf(filed, "2026-05-14 Older Words %d.pdf" % i)
        old.append(path)
        purchase = reviews.as_a_run_left_it(inst, "ORDER-%04d" % i, path, saved=True,
                                            confidence="Low")
        recs[purchase.key] = dict(inst.progress.get(purchase.key),
                                  **{f: v for f, v in rec.items()
                                     if f not in NAMING | {"order_number"}})
    write(inst, recs)
    monkeypatch.setattr(home.mod, "ask", lambda prompt: "Garden Hose")
    capsys.readouterr()

    error = None
    try:
        home.mod.main(["--config", str(home.cfg), "--review-names"])
    except SystemExit:
        pass
    except Exception as e:                       # what a person would see as a traceback
        error = e
    said = " ".join(capsys.readouterr().out.split())

    assert error is None, "%s's Review Names ended with %r\n%s" % (app.name, error, said[-1500:])
    renamed = sorted(p.name for p in filed.glob("*.pdf"))
    assert len(renamed) == len(old) and all("Garden Hose" in n for n in renamed), (
        app.name, renamed, said[-1500:])
