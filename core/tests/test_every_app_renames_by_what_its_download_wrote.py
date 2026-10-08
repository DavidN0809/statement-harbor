"""Every document app's Rename reads what its download changed as saved.

Rename names a file from the app's records, the listing's over the run
state's, since the listing is the one an app refreshes when it learns to
read a page better (renaming._Known, #26). Ally names a statement from what
its PDF says once the file is saved, and writes that summary and account to
the run state alone (App._name_from_contents). The listing's record kept
what the list said, so Rename offered every such file the list's name back,
and --apply took it. Rename now reads the fields an app names in run_for's
`as_saved` from the record as it was when the file was saved.

So no other app does what Ally did unseen, every document app's own code is
read here. A function that changes a document's summary or account, other
than one that writes the document into the listing whole, has to be one
whose app hands run_for that field as saved. A document is a parameter
annotated Document, one named doc with no annotation, a loop's doc, or a
name the function makes with Document(...) or Document.from_dict(...), and
a change is an assignment to its attribute, a subscript of it or setattr
with the field's name. Receipt apps are left out, since their listings
leave a purchase's summary and account empty and the run state's are the
ones Rename reads. What it does not see is a change made
through another name, a helper's return or __dict__, and the canary at the
end holds it to the shapes it must see.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("summary", "account")


def entries():
    return sorted(p for p in (ROOT / "apps").glob("*/*_docs.py"))


def _constants(tree) -> dict:
    """Module-level names bound to a tuple or list of strings."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List)):
            values = [e.value for e in node.value.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = set(values)
    return out


def as_saved_of(tree):
    """What each of the module's run_for calls hands as saved, or None when
    it does not rename through the core."""
    constants = _constants(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("run_for")):
            continue
        given = set()
        for kw in node.keywords:
            if kw.arg != "as_saved":
                continue
            if isinstance(kw.value, ast.Name):
                given = constants.get(kw.value.id, set())
            elif isinstance(kw.value, (ast.Tuple, ast.List)):
                given = {e.value for e in kw.value.elts if isinstance(e, ast.Constant)}
        found.append(given)
    if not found:
        return None
    return set.intersection(*found)


def _writes_listing_whole(func) -> bool:
    """A call to self.discovery.update handing it a record, not a dict
    written out in place, as Ally's {"state": ...}."""
    for node in ast.walk(func):
        if (isinstance(node, ast.Call)
                and ast.unparse(node.func) == "self.discovery.update"
                and len(node.args) >= 2 and not isinstance(node.args[1], ast.Dict)):
            return True
    return False


def _documents_in(func) -> set:
    names = set()
    for arg in func.args.args + func.args.kwonlyargs:
        annotation = ast.unparse(arg.annotation) if arg.annotation is not None else ""
        if annotation.strip("'\"") == "Document" or (not annotation and arg.arg == "doc"):
            names.add(arg.arg)
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) in ("Document", "Document.from_dict")):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        # A loop over documents, as process walks the ones it was handed.
        if (isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name)
                and node.target.id == "doc"):
            names.add("doc")
    return names


def _field_changed(target, docs):
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        if target.value.id in docs and target.attr in FIELDS:
            return target.attr
    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        key = target.slice
        if (target.value.id in docs and isinstance(key, ast.Constant)
                and key.value in FIELDS):
            return key.value
    return None


def changed_after_listing(tree):
    """(function, field) for each change of a document's summary or account
    outside __init__ and outside a function writing the listing whole."""
    out = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name == "__init__" or _writes_listing_whole(func):
            continue
        docs = _documents_in(func)
        if not docs:
            continue
        for node in ast.walk(func):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                field = _field_changed(target, docs)
                if field:
                    out.append((func.name, field))
            if (isinstance(node, ast.Call) and ast.unparse(node.func) == "setattr"
                    and len(node.args) >= 2 and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in docs and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in FIELDS):
                out.append((func.name, node.args[1].value))
    return out


def unread(tree):
    """Each change Rename would not read as saved."""
    given = as_saved_of(tree)
    if given is None:
        return []
    return [(name, field) for name, field in changed_after_listing(tree)
            if field not in given]


@pytest.mark.parametrize("entry", entries(), ids=lambda p: p.parent.name)
def test_rename_reads_what_the_download_changed_as_saved(entry):
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    assert unread(tree) == []


def test_the_census_reaches_every_document_app():
    found = entries()
    assert len(found) >= 45, len(found)
    renaming = [e for e in found
                if as_saved_of(ast.parse(e.read_text(encoding="utf-8-sig"))) is not None]
    assert len(renaming) >= 45, len(renaming)


def test_ally_is_the_one_that_changes_them():
    ally = ROOT / "apps" / "ally" / "ally_docs.py"
    tree = ast.parse(ally.read_text(encoding="utf-8-sig"))
    assert set(changed_after_listing(tree)) == {("_name_from_contents", "summary"),
                                                 ("_name_from_contents", "account")}
    assert as_saved_of(tree) >= set(FIELDS)


CANARY_HEAD = '''
class Document: ...
class App:
    def cmd_rename(self):
        renaming.run_for(self, apply_changes=False%s)
'''

SEEN = {
    "attribute": "    def named(self, doc: Document):\n        doc.summary = 'x'\n",
    "string annotation": "    def named(self, doc: 'Document'):\n        doc.account = 'x'\n",
    "subscript": "    def named(self, doc: Document):\n        doc['summary'] = 'x'\n",
    "setattr": "    def named(self, doc: Document):\n        setattr(doc, 'account', 'x')\n",
    "made here": "    def named(self, rec):\n        doc = Document.from_dict(rec)\n"
                 "        doc.summary = 'x'\n        self._record(doc)\n",
    "a state alone": "    def named(self, doc: Document):\n        doc.summary = 'x'\n"
                     "        self.discovery.update(doc.key, {'state': 'done'})\n",
    "unannotated doc": "    def named(self, page, doc):\n        doc.summary = 'x'\n",
    "a loop": "    def run(self, docs):\n        for doc in docs:\n            doc.summary = 'x'\n",
    "augmented":"    def named(self, doc: Document):\n        doc.summary += ' x'\n",
}

PASSED = {
    "listing whole": "    def listed(self, d):\n        doc = Document(**d)\n"
                     "        doc.summary = 'x'\n        rec = doc.to_dict()\n"
                     "        self.discovery.update(doc.key, rec)\n",
    "the constructor": "    def __init__(self, summary=''):\n        self.summary = summary\n",
    "another dict": "    def diagnose(self, page):\n        info = {}\n"
                    "        info['account'] = 'x'\n",
    "read only": "    def named(self, doc: Document):\n        return doc.summary\n",
}


@pytest.mark.parametrize("shape", sorted(SEEN))
def test_the_census_sees_a_change(shape):
    tree = ast.parse(CANARY_HEAD % "" + SEEN[shape])
    assert unread(tree), shape
    given = ast.parse(CANARY_HEAD % ", as_saved=('summary', 'account')" + SEEN[shape])
    assert unread(given) == [], shape
    named = ast.parse("SAVED = ('summary', 'account')\n"
                      + CANARY_HEAD % ", as_saved=SAVED" + SEEN[shape])
    assert unread(named) == [], shape


@pytest.mark.parametrize("shape", sorted(PASSED))
def test_the_census_passes_what_is_no_change(shape):
    tree = ast.parse(CANARY_HEAD % "" + PASSED[shape])
    assert unread(tree) == [], shape
