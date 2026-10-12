"""The checks that have to pass before this app touches the household parcel. No browser, no network."""
import base64, json, re, sys, tempfile, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import shelbycounty_site as site  # noqa: E402
import shelbycounty_docs as docs  # noqa: E402

PARCEL = "012345 00099"
OWNER_BLOB = base64.b64encode(json.dumps({"parcel": PARCEL, "primaryName": "DOE JANE", "billNumber": 11223344}).encode()).decode()
TX = "/Transaction?billNumberData=" + OWNER_BLOB


def row(cells, bill=False, receipt=False, i=0):
    return {"i": i, "cells": cells, "hasBillLink": bill, "hasPrintReceipt": receipt, "printLabel": "Print Receipt" if receipt else ""}


class Guard(unittest.TestCase):
    def test_allows_only_the_four_controls(self):
        for label in ["Print Receipt", "PRINT NOTICE Balances Due", "NEXT", "PREVIOUS"]:
            self.assertTrue(site.is_safe_control(label), label)
        for label in ["MAKE PAYMENT EXTERNAL", "Make Payment", "Pay", "Yes, Proceed", "Add to cart", "Checkout", "Continue to payment",
                      "REGISTER GIS EXTERNAL", "LEGAL DESCRIPTION", "Owner", "Property", "Parcel", "COLUMNS", "Back", "Appeal",
                      "Apply for tax relief", "Sign up for eBill", "Print Receipt and pay", "ManagedPay", "", None, "Search"]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Hosts(unittest.TestCase):
    def test_pages(self):
        self.assertTrue(site.is_safe_url("https://apps2.shelbycountytrustee.com/Parcel?parcel=1"))
        for u in ["https://payments.shelbycountytrustee.com/", "https://www.shelbycountytrustee.com/103", "https://shelbycountytrustee.com/",
                  "https://apps2.shelbycountytrustee.com.evil.test/", "http://apps2.shelbycountytrustee.com/Parcel", "https://go.payitgov.com/", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_blob_origin(self):
        self.assertTrue(site.is_download_url("blob:https://apps2.shelbycountytrustee.com/0b1e-uuid"))
        for u in ["blob:https://payments.shelbycountytrustee.com/x", "https://apps2.shelbycountytrustee.com/x.pdf", "blob:http://apps2.shelbycountytrustee.com/x",
                  "blob:https://apps2.shelbycountytrustee.com:8443/x", "blob:null/x", "", None]:
            self.assertFalse(site.is_download_url(u), repr(u))

    def test_sign_in_pages_are_noticed_and_the_lookup_is_not(self):
        class Page:
            def __init__(self, url): self.url = url
            def locator(self, sel): return self
            def count(self): return 0
        self.assertFalse(site.looks_signed_out(Page("https://apps2.shelbycountytrustee.com/Parcel?parcel=x")))
        self.assertTrue(site.looks_signed_out(Page("https://payments.shelbycountytrustee.com/login")))
        class Dead:
            @property
            def url(self): raise RuntimeError("closed")
        with self.assertRaises(RuntimeError):
            site.looks_signed_out(Dead())

    def test_only_the_configured_parcels_own_page_counts_as_open(self):
        site.configure("012345 00001")
        try:
            self.assertTrue(site.landed_on_parcel("https://apps2.shelbycountytrustee.com/Parcel?parcel=012345%2000001"))
            self.assertTrue(site.landed_on_parcel("https://apps2.shelbycountytrustee.com/Parcel?parcel=012345+00001"))
            for u in ["https://apps2.shelbycountytrustee.com/Parcel?parcel=012345%2000002",
                      "https://apps2.shelbycountytrustee.com/Parcel", "https://apps2.shelbycountytrustee.com/",
                      "https://apps2.shelbycountytrustee.com/Parcel?parcel=012345%2000001&parcel=9",
                      "https://payments.shelbycountytrustee.com/Parcel?parcel=012345%2000001", ""]:
                self.assertFalse(site.landed_on_parcel(u), u)
            site.configure("")
            self.assertFalse(site.landed_on_parcel("https://apps2.shelbycountytrustee.com/Parcel?parcel="))
        finally:
            site.configure("")

    def test_the_guard_takes_its_own_documents_and_refuses_the_rest(self):
        for ok in ["Print Receipt", "View Receipt", "Download Property Tax Receipt", "Property Tax Notice", "NEXT"]:
            self.assertTrue(site.is_safe_control(ok), ok)
        for bad in ["Print Receipt | Make a payment", "Pay Property Tax", "Property Search", "View Receipt | Sign Out", ""]:
            self.assertFalse(site.is_safe_control(bad), bad)


class Tables(unittest.TestCase):
    def test_footer(self):
        self.assertEqual(site.footer_counts("PAGE 1 OF 2  ROWS: 5 10 20  TOTAL RECORDS: 16"), (1, 2, 16))
        self.assertIsNone(site.footer_counts("no footer here"))

    def test_bill_rows(self):
        rows = [row(["11", "2026", "SHELBY", "$0.00"], bill=True, i=0), row(["12", "2025", "SHELBY", "$0.00"], bill=True, i=1)]
        self.assertEqual([b["year"] for b in site.bill_rows(rows)], ["2026", "2025"])
        for bad in ([row(["11", "2026"], bill=False)], [row(["11", "20x6"], bill=True)],
                    [row(["11", "2026"], bill=True, i=0), row(["12", "2026"], bill=True, i=1)]):
            with self.assertRaises(site.ListStopped):
                site.bill_rows(bad)

    def test_receipt_docs(self):
        rows = [row(["Print Receipt", "7887623", "02/27/2025", "TAX", "$1,856.87"], receipt=True, i=0),
                row(["Print Receipt", "7887624", "03/01/2025", "TAX", "$10.00"], receipt=True, i=1)]
        d = site.receipt_docs(rows, "2024")
        self.assertEqual([(x.title, x.date_text) for x in d], [("Property Tax Receipt Tax Year 2024", "2025-02-27"), ("Property Tax Receipt Tax Year 2024", "2025-03-01")])
        for x in d:
            self.assertEqual(x.href, ""); self.assertNotIn("7887623", json.dumps(x.__dict__))
        for bad in ([row(["Print Receipt", "1", "02/30/2025", "TAX", "$1"], receipt=True)],
                    [row(["Print Receipt", "1", "02/27/2025"], receipt=False)],
                    [row(["Print Receipt", "1", "02/27/2025", "TAX"], receipt=True, i=0), row(["Print Receipt", "2", "02/27/2025", "TAX"], receipt=True, i=1)],
                    [row(["Print Receipt", "7881234", "02/27/2025", "TAX"], receipt=True, i=0), row(["Print Receipt", "9991234", "02/27/2025", "TAX"], receipt=True, i=1)]):
            with self.assertRaises(site.ListStopped):
                site.receipt_docs(bad, "2024")
        self.assertEqual(site.receipt_docs([], "2024"), [])
        two = site.receipt_docs([row(["Print Receipt", "7887623", "03/13/2020", "TAX", "$1"], receipt=True, i=0),
                                 row(["Print Receipt", "7887650", "03/13/2020", "INTEREST", "$1"], receipt=True, i=1)], "2019")
        self.assertEqual([d.title for d in two], ["Property Tax Receipt Tax Year 2019 (#7623)", "Property Tax Receipt Tax Year 2019 (#7650)"])
        for d in two:
            self.assertRegex(d.title, site._RECEIPT_TITLE_RE); self.assertNotIn("788", d.title)
        self.assertTrue(site._row_matches(row(["Print Receipt", "7887650", "03/13/2020", "INTEREST"]), "2020-03-13", "7650"))
        self.assertFalse(site._row_matches(row(["Print Receipt", "7887623", "03/13/2020", "TAX"]), "2020-03-13", "7650"))

    def test_mdy(self):
        self.assertEqual(site.mdy_to_iso("11/23/2016"), "2016-11-23"); self.assertEqual(site.mdy_to_iso("13/23/2016"), ""); self.assertEqual(site.mdy_to_iso("2016-11-23"), "")


class Blob(unittest.TestCase):
    PDF = base64.b64encode(b"%PDF-1.4 receipt").decode()
    OK = {"blobs": [{"type": "application/pdf", "size": 16, "url": "blob:https://apps2.shelbycountytrustee.com/abc"}],
          "opened": ["blob:https://apps2.shelbycountytrustee.com/abc"], "b64": PDF}

    def test_accepts_exactly_the_surveyed_shape(self):
        data, why = site.accept_blob(self.OK); self.assertTrue(data.startswith(b"%PDF-")); self.assertEqual(why, "")

    def test_refuses_everything_else(self):
        cases = {"two blobs": {**self.OK, "blobs": self.OK["blobs"] * 2}, "no blob": {**self.OK, "blobs": []},
                 "wrong type": {**self.OK, "blobs": [{**self.OK["blobs"][0], "type": "application/octet-stream"}]},
                 "wrong origin": {**self.OK, "blobs": [{**self.OK["blobs"][0], "url": "blob:https://payments.shelbycountytrustee.com/abc"}],
                                  "opened": ["blob:https://payments.shelbycountytrustee.com/abc"]},
                 "opened elsewhere": {**self.OK, "opened": ["https://payments.shelbycountytrustee.com/"]},
                 "opened twice": {**self.OK, "opened": self.OK["opened"] * 2},
                 "not a pdf": {**self.OK, "b64": base64.b64encode(b"<html>").decode()}, "no bytes": {**self.OK, "b64": ""}}
        for name, r in cases.items():
            data, why = site.accept_blob(r); self.assertEqual(data, b"", name); self.assertTrue(why, name)


class Press(unittest.TestCase):
    """_press_for_blob reads the capture only once it holds still, and a late second blob is refused."""

    def make_page(self, polls, result):
        class El:
            def click(self, **kw): pass
        class Page:
            url = "https://apps2.shelbycountytrustee.com/Transaction?billNumberData=x"
            def __init__(s):
                class Ctx: pass
                s.context = Ctx(); s.context.pages = [s]; s.polls = list(polls); s.evaluated = []
            def evaluate(s, js, arg=None):
                s.evaluated.append(js[:30])
                if "window.__pp = " in js: return None
                if "blobs.length" in js and "opened.length" in js: return s.polls.pop(0) if len(s.polls) > 1 else s.polls[0]
                return result
            def wait_for_timeout(s, ms): pass
        return Page(), El()

    def test_late_second_blob_is_refused(self):
        pdf = base64.b64encode(b"%PDF-1.4 x").decode()
        two = {"blobs": [{"type": "application/pdf", "size": 1, "url": "blob:https://apps2.shelbycountytrustee.com/a"}] * 2,
               "opened": ["blob:https://apps2.shelbycountytrustee.com/a"], "b64": pdf}
        page, el = self.make_page([[0, 0], [1, 1], [1, 1], [2, 1], [2, 1], [2, 1]], two)
        with tempfile.TemporaryDirectory() as td:
            trace = []
            self.assertFalse(site._press_for_blob(page, el, "Print Receipt", Path(td) / "o.pdf", trace))
            self.assertEqual(trace[-1]["note"], "blob refused"); self.assertFalse((Path(td) / "o.pdf").exists())

    def test_one_still_blob_is_taken(self):
        pdf = base64.b64encode(b"%PDF-1.4 x").decode()
        one = {"blobs": [{"type": "application/pdf", "size": 1, "url": "blob:https://apps2.shelbycountytrustee.com/a"}],
               "opened": ["blob:https://apps2.shelbycountytrustee.com/a"], "b64": pdf}
        page, el = self.make_page([[0, 0], [1, 1], [1, 1], [1, 1], [1, 1]], one)
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(site._press_for_blob(page, el, "Print Receipt", Path(td) / "o.pdf", []))
            self.assertTrue((Path(td) / "o.pdf").read_bytes().startswith(b"%PDF-"))


class Navigation(unittest.TestCase):
    def make_page(self, url, extra_pages=0):
        class P:
            def __init__(s, u): s.url = u; s.closed = False
            def close(s): s.closed = True
        class Ctx: pass
        page = P(url); ctx = Ctx(); extras = [P("https://payments.shelbycountytrustee.com/") for _ in range(extra_pages)]
        ctx.pages = [page] + extras; page.context = ctx
        return page, extras

    def test_settled_off_host_stops(self):
        page, _ = self.make_page("https://payments.shelbycountytrustee.com/checkout")
        with self.assertRaises(site.ListStopped):
            site.settled_here(page, "a goto")

    def test_a_new_tab_is_closed_and_stops(self):
        page, extras = self.make_page("https://apps2.shelbycountytrustee.com/Parcel?parcel=1", extra_pages=1)
        with self.assertRaises(site.ListStopped):
            site.settled_here(page, "a press", before={page})
        self.assertTrue(all(e.closed for e in extras))

    def test_a_tab_that_was_already_there_is_left_alone(self):
        page, extras = self.make_page("https://apps2.shelbycountytrustee.com/Parcel?parcel=1", extra_pages=2)
        site.settled_here(page, "a goto", before=site.tabs_now(page))
        self.assertFalse(any(e.closed for e in extras), "the panel's own tabs are not this app's to close")

    def test_on_host_alone_passes(self):
        page, _ = self.make_page("https://apps2.shelbycountytrustee.com/Transaction?billNumberData=x")
        site.settled_here(page, "a goto")


class Paging(unittest.TestCase):
    """A fake two-page table: NEXT shows the second page; indexes are the page's own."""

    class Page:
        url = "https://apps2.shelbycountytrustee.com/Transaction?billNumberData=x"
        def __init__(self, pages):
            self.pages = pages; self.at = 0; self.presses = 0
            class Ctx: pass
            self.context = Ctx(); self.context.pages = [self]
        def evaluate(self, js, arg=None):
            if "PAGE" in js:
                return "PAGE %d OF %d  ROWS: 10  TOTAL RECORDS: %d" % (self.at + 1, len(self.pages), sum(len(p) for p in self.pages))
            return self.pages[self.at]
        def get_by_role(self, role, name=None):
            page = self
            class L:
                def count(s): return 1
                @property
                def first(s): return s
                def is_disabled(s): return page.at >= len(page.pages) - 1
                def inner_text(s, **kw): return "NEXT"
                def click(s, **kw): page.at += 1; page.presses += 1
            return L()
        def wait_for_timeout(self, ms): pass

    def test_whole_table_and_page_local_index(self):
        p1 = [row(["Print Receipt", "1", "02/27/2025", "TAX", "$1"], receipt=True, i=0)]
        p2 = [row(["Print Receipt", "2", "02/28/2024", "TAX", "$1"], receipt=True, i=0)]
        page = self.Page([p1, p2])
        rows = site.read_whole_table(page, "payment history"); self.assertEqual(len(rows), 2); self.assertEqual(page.presses, 1)
        page = self.Page([p1, p2])
        self.assertEqual(site._receipt_index(page, "2024-02-28"), 0, "the row's index on ITS page, after paging to it")
        self.assertEqual(page.at, 1)
        page = self.Page([p1, p2])
        with self.assertRaises(site.ListStopped):
            site._receipt_index(page, "2020-01-01")

    def test_table_must_start_at_page_one_and_advance_by_one(self):
        p1 = [row(["Print Receipt", "1", "02/27/2025", "TAX", "$1"], receipt=True)]
        page = self.Page([p1, p1]); page.at = 1          # landed on page 2 of 2
        with self.assertRaises(site.ListStopped):
            site.read_whole_table(page, "payment history")
        page = self.Page([p1, p1, p1])
        real = page.get_by_role
        def skipping(role, name=None):
            L = real(role, name)
            orig = L.click
            def click(**kw): orig(**kw); page.at += 1      # NEXT jumps two pages
            L.click = click; return L
        page.get_by_role = skipping
        with self.assertRaises(site.ListStopped):
            site.read_whole_table(page, "payment history")
        page = self.Page([p1, p1]); real_eval = page.evaluate
        page.evaluate = lambda js, arg=None: ("PAGE %d OF 2  TOTAL RECORDS: %d" % (page.at + 1, 2 + page.at) if "PAGE" in js else real_eval(js, arg))
        with self.assertRaises(site.ListStopped, msg="a total that changes between pages"):
            site.read_whole_table(page, "payment history")

    def test_empty_table_needs_the_page_to_say_so(self):
        page = self.Page([[]]); page.evaluate = lambda js, arg=None: ("" if "PAGE" in js else [])
        page.locator = lambda sel: type("L", (), {"inner_text": lambda s, **kw: "PAYMENT HISTORY\nNo transactions for selected tax year"})()
        self.assertEqual(site.read_whole_table(page, "payment history"), [])
        page.locator = lambda sel: type("L", (), {"inner_text": lambda s, **kw: "PAYMENT HISTORY"})()
        with self.assertRaises(site.ListStopped):
            site.read_whole_table(page, "payment history")

    def test_footer_disagreement_stops(self):
        page = self.Page([[row(["Print Receipt", "1", "02/27/2025", "TAX", "$1"], receipt=True)]])
        page.evaluate = lambda js, arg=None: ("PAGE 1 OF 1  TOTAL RECORDS: 3" if "PAGE" in js else page.pages[0])
        with self.assertRaises(site.ListStopped):
            site.read_whole_table(page, "payment history")


class Privacy(unittest.TestCase):
    def test_parcel_and_owner_never_in_records_or_redacted_text(self):
        site.configure(PARCEL, owner="Doe Jane")
        self.assertEqual(site.URLS["documents"], "https://apps2.shelbycountytrustee.com/Parcel?parcel=012345%2000099")
        out = site.redact("saw https://apps2.shelbycountytrustee.com/Parcel?parcel=012345%2000099 and " + PARCEL + " and 01234500099 and Doe Jane")
        for private in (PARCEL, "01234500099", "012345%2000099", "Doe Jane"):
            self.assertNotIn(private, out)
        d = site.receipt_docs([row(["Print Receipt", "7887623", "02/27/2025", "TAX", "$1"], receipt=True)], "2024")[0]
        self.assertNotIn(PARCEL, json.dumps(d.__dict__)); self.assertNotIn("billNumberData", json.dumps(d.__dict__))

    def test_no_address_is_ever_formatted_into_a_log_or_trace(self):
        src = (HERE / "shelbycounty_site.py").read_text()
        for line in src.splitlines():
            if ("log." in line or "trace.append" in line) and re.search(r"page\.url|href|parcel_url\(|billNumberData|urlsplit\(", line):
                self.fail("an address reaches a log or trace: " + line.strip()[:100])
        self.assertIn("site.configure(", (HERE / "shelbycounty_docs.py").read_text())

    def test_rules(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        self.assertEqual(doc_types.classify_document("Property Tax Receipt Tax Year 2024", rules)[:2], ("Tax Document", "Property Tax Receipt"))
        self.assertEqual(doc_types.classify_document("Property Tax Notice Tax Year 2026", rules)[:2], ("Tax Document", "Property Tax Notice"))

    def test_no_product_migration_survives(self):
        src = (HERE / "shelbycounty_docs.py").read_text()
        self.assertNotIn("adopt_product_keys", src)
        self.assertIsNone(site.DOCUMENT_PATH_RE.match(""), "an empty href must not look like a product path")
        self.assertNotIn("HSA", src.split('"""')[1])

    def test_no_click_outside_the_three_controls(self):
        src = (HERE / "shelbycounty_site.py").read_text()
        self.assertEqual(src.count(".click("), 2, "NEXT and the one guarded press")
        for verb in (".fill(", ".select_option(", ".check(", ".type(", ".press("):
            self.assertNotIn(verb, src)
        self.assertEqual(docs.persistable("/x?billNumberData=abc"), "/x")


if __name__ == "__main__":
    unittest.main()
