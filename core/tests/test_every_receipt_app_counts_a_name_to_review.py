"""Every receipt app counts a receipt it saved under a name it was unsure of
as one to name, apart from one it set aside.

Each counts such a receipt in manual_review, the same count as a document
set aside in the Manual Review folder, and the panel said every one of them
sat in that folder. On a real Target account the folder was empty, since the
receipt was filed where it belonged and waited only for Review names. Each
app now counts it in name_review as well (run_reporting carries it), so the
panel can say which is which.

This reads every receipt app's source. Each block that counts a receipt
under review because its name was unsure (if review_needed) counts it in
name_review too.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(REPO.glob("apps/*/*_receipts.py"))


def _counts(node, stat):
    """Whether a block adds to self.stats[stat]."""
    for n in ast.walk(node):
        target = n.target if isinstance(n, ast.AugAssign) else (
            n.targets[0] if isinstance(n, ast.Assign) and len(n.targets) == 1 else None)
        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute)
                and target.value.attr == "stats" and isinstance(target.slice, ast.Constant)
                and target.slice.value == stat):
            return True
    return False


def unsure_blocks(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "review_needed"
            and _counts(ast.Module(body=n.body, type_ignores=[]), "manual_review")]


def test_every_receipt_app_counts_a_name_to_review():
    counted, missing = [], []
    for path in APPS:
        for block in unsure_blocks(path):
            ok = _counts(ast.Module(body=block.body, type_ignores=[]), "name_review")
            (counted if ok else missing).append("%s:%d" % (path.parent.name, block.lineno))
    assert not missing, ("counts a receipt saved under an unsure name in manual_review alone, "
                         "so the panel sends the person to an empty Manual Review folder", missing)
    # Not a census of nothing. Uber names its receipts from Uber's own and is
    # never unsure of one.
    assert len(counted) >= 13, counted


def test_the_census_finds_a_block_that_forgets():
    source = (
        "class App:\n"
        "    def save(self, review_needed):\n"
        "        if review_needed:\n"
        "            self.stats['manual_review'] += 1\n")
    tree = ast.parse(source)
    block = next(n for n in ast.walk(tree) if isinstance(n, ast.If))
    assert _counts(ast.Module(body=block.body, type_ignores=[]), "manual_review")
    assert not _counts(ast.Module(body=block.body, type_ignores=[]), "name_review")
