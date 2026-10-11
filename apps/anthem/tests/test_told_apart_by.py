"""What Anthem adds to a file's name when another file already has it.

The last six characters of the id, which other apps add, said nothing a
person could read here, " rmal1" for a second ID card and " A1095" for a
1095-B listed under its other type code. anthem_docs.told_apart_by reads
the id each kind of document keeps and gives what tells it apart in
words. Every id here is made up.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthem_docs  # noqa: E402
import anthem_site as site  # noqa: E402

PERIOD = "79DM-20250101-20251231-MED-000000A00A"


@pytest.mark.parametrize("doc_id, ending", [
    (site.make_doc_id("Medical", "1234500AA0001", "EOB", 1), "EOB 1"),
    (site.make_doc_id("Pharmacy", "1234500AA0001", "EOB Check", 0), "EOB Check 0"),
    # An id written before the sequence number was added reads as the first.
    ("Medical|1234500AA0001|EOB", "EOB 0"),
    ("MemberDoc|%s|1095" % PERIOD, "type 1095"),
    ("MemberDoc|%s|1095B" % PERIOD, "type 1095B"),
    ("IdCard|Jane Doe|normal|0", "No. 1"),
    ("IdCard|Jane Doe|dental|2", "No. 3"),
    ("Letter|u-7302bb", "7302bb"),
    ("Letter|u-1", "u-1"),
])
def test_each_kind_of_document_is_told_apart_in_words(doc_id, ending):
    assert anthem_docs.told_apart_by({"document_id": doc_id}) == ending


@pytest.mark.parametrize("record, ending", [
    # A shape this rule does not know is told apart the usual way.
    ({"document_id": "SOMETHING-ELSE-12345678"}, "345678"),
    ({"document_id": "IdCard|Jane Doe|normal|x"}, "rmal|x"),
    ({"document_id": "MemberDoc|%s|" % PERIOD}, "%s|" % PERIOD[-5:]),
    ({"document_id": ""}, ""),
    ({}, ""),
    (None, ""),
])
def test_anything_else_is_told_apart_the_usual_way(record, ending):
    assert anthem_docs.told_apart_by(record) == ending
