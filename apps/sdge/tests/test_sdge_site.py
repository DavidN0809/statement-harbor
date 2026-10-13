"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import io
import json
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import sdge_site as site  # noqa: E402
import sdge_docs as docs  # noqa: E402

HOST = "myenergycenter.com"
ID1, ID2, ID3 = "ISU000000000101", "ISU000000000102", "ISU000000000103"
PDF_URL = f"https://{HOST}/portal/BillingHistory/DownloadBillPdf?invoiceId={ID1}"
ROWS = [{"id": ID1, "date": "Sep 12, 2026"}, {"id": ID2, "date": "Aug 13, 2026"},
        {"id": ID3, "date": "Jul 14, 2026"}]
# Invented account details, which must never leave through a log, the
# console or a diagnostic.
FAKE_ACCOUNT = "987650001234"
FAKE_CONTRACT = "876540009876"
FAKE_STREET = "Zyxwvut"


class Resp:
    def __init__(self, status=200, ctype="application/pdf", body=b"%PDF-1.4 x", location="", extra=None):
        self.status, self.ok = status, status == 200
        self.headers = {"content-type": ctype, **({"location": location} if location else {}), **(extra or {})}
        self._body, self.url, self.disposed = body, "", False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


class Req:
    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_redirects")))
        r = self.answers.pop(0)
        r.url = url
        return r


class Locator:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n

    def inner_text(self, **kw):
        return ""


class Page:
    """Billing History as the portal draws it, with nothing pressed."""

    def __init__(self, rows=ROWS, empty="", ready=True, settled=None, password=False,
                 answers=(), accounts=1, start=f"https://{HOST}/portal/Dashboard/index"):
        self.rows, self.empty, self.ready, self.settled = list(rows), empty, ready, settled
        self.password, self.accounts, self.url, self.gotos = password, accounts, start, []
        page = self

        class Ctx:
            request = Req(answers)
            pages = [page]
        self.context = Ctx()

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = self.settled or url

    def wait_for_selector(self, sel, **kw):
        if self.rows and self.ready:
            return
        if "dataTables_empty" in sel and self.empty and self.ready:
            return
        raise TimeoutError("waited")

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        return Locator(1 if ("password" in sel and self.password) else 0)

    def title(self):
        return "My Energy Center"

    def evaluate(self, js):
        if "accountList" in js:
            words = []
            for i in range(self.accounts):
                words += [f"{FAKE_ACCOUNT}{i}", f"{FAKE_ACCOUNT}{i}", f"{FAKE_CONTRACT}{i}",
                          f"100 {FAKE_STREET} Ave San Diego CA", f"{FAKE_ACCOUNT}{i} - 100 {FAKE_STREET} Ave"]
            return {"count": self.accounts, "words": words + [FAKE_CONTRACT]}
        return {"rows": [dict(r) for r in self.rows], "empty": self.empty}


class Dead:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


class Hosts(unittest.TestCase):
    def test_only_the_portal_host_over_https(self):
        for u in [f"https://{HOST}/portal/", f"https://{HOST}/portal/BillingHistory/index", PDF_URL]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["https://www.sdge.com/my-energy-center", f"http://{HOST}/portal/", f"https://user@{HOST}/portal/",
                  f"https://{HOST}@evil.test/portal/", f"https://ent.{HOST}/portal/", f"https://{HOST}.evil.test/",
                  f"https://{HOST}:8443/portal/", f"blob:https://{HOST}/0b1c", "https://sdge-ortsvc.smartcmobile.net/APIService/x",
                  "https://ipn4.paymentus.com/rotp/sdg", "javascript:alert(1)", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_a_bill_address_is_one_shape_only(self):
        self.assertTrue(site.is_download_url(PDF_URL))
        self.assertEqual(site.download_url(ID1), PDF_URL)
        base = f"https://{HOST}/portal/BillingHistory/DownloadBillPdf"
        for u in [base, f"{base}?invoiceId=", f"{base}?invoiceId=ISU12345", f"{base}?invoiceId=isu000000000101",
                  f"{base}?invoiceId=ISU0000000001011", f"{base}?invoiceId={ID1}&invoiceId={ID2}",
                  f"{base}?invoiceId={ID1}&type=Bill", f"{base}?invoiceId=%49SU000000000101", f"{base}?invoiceId={ID1}#x",
                  f"{base}/?invoiceId={ID1}", f"https://{HOST}/portal/BillingHistory/GetHistoryDownload?type=Bill",
                  PDF_URL.replace("https:", "http:"), PDF_URL.replace(HOST, "www.sdge.com"),
                  f"https://{HOST}/portal/PreLogin/Validate", f"blob:{PDF_URL}", ""]:
            self.assertFalse(site.is_download_url(u), u)
        for bad in ("", None, "ISU1", "ISU00000000010\n", "XSU000000000101"):
            self.assertEqual(site.download_url(bad), "", repr(bad))


class Controls(unittest.TestCase):
    def test_own_documents_under_view_and_download(self):
        for label in ["View Your Detailed Bill PDF", "Download Your Solar Bill", "View Bill", "Download Bill",
                      "View Utility Bill", "Download Utility Bill", "view your bill"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_everything_else_is_refused(self):
        for label in ["Make a Payment", "Auto Pay", "AutoPay", "Text to Pay", "Bank Accounts", "Payment Arrangements",
                      "Pricing Plans", "Level Pay", "Start Service", "Transfer Service", "Stop Service",
                      "Notifications Settings", "Sign Out", "Guest Pay", "Register", "Go Paperless",
                      "Download billing history (Excel)", "Export", "View Bill History", "Billing History",
                      "View Additional Solar Bill Details", "Letter of Residency", "View Bill | Make a Payment",
                      "Make a Payment | View Bill", "Download Bill and Pay", "View Bill and enroll in paperless",
                      "Pay Bill", "View Bill Now", "Details", "", "   ", None]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Rows(unittest.TestCase):
    def test_the_statement_date_is_the_first_date_cell_after_the_control_column(self):
        docs = site.bills_of([{"id": ID1, "cells": ["", "Sep 25, 2026", "Oct 14, 2026", "", "-$1.00", "$0.00", "Billed", ""]}])
        self.assertEqual([d.date_text for d in docs], ["2026-09-25"])
        with self.assertRaises(site.ListStopped):
            site.bills_of([{"id": ID1, "cells": ["", "Billed", ""]}])

    def test_good_rows(self):
        got = site.bills_of(ROWS)
        self.assertEqual([(d.title, d.date_text, d.document_id, d.kind) for d in got],
                         [("SDG&E Bill 2026-09-12", "2026-09-12", ID1, "statement"),
                          ("SDG&E Bill 2026-08-13", "2026-08-13", ID2, "statement"),
                          ("SDG&E Bill 2026-07-14", "2026-07-14", ID3, "statement")])
        for d in got:
            self.assertEqual(d.href, site.DOWNLOAD_PATH)
            self.assertEqual(d.account, "")

    def test_unreadable_rows_stop_the_list_with_what_was_read(self):
        for bad, why in [({"id": "ISU123", "date": "Jun 1, 2026"}, "bad id"),
                         ({"id": "", "date": "Jun 1, 2026"}, "no id"),
                         ({"id": ID3, "date": "Feb 30, 2026"}, "no such day"),
                         ({"id": ID3, "date": "2026-06-01"}, "another shape"),
                         ({"id": ID3, "date": "Due Jun 1, 2026"}, "a date inside other text"),
                         ({"id": ID1, "date": "Jun 1, 2026"}, "duplicate id"),
                         ({"id": ID3, "date": "Sep 12, 2026"}, "two bills one date")]:
            with self.assertRaises(site.ListStopped, msg=why) as stop:
                site.bills_of(ROWS[:2] + [bad])
            self.assertEqual([d.document_id for d in stop.exception.docs], [ID1, ID2], why)
            self.assertNotIn("ISU", str(stop.exception), why)

    def test_statement_dates(self):
        self.assertEqual(site.statement_date("Feb 28, 2026"), "2026-02-28")
        self.assertEqual(site.statement_date(" Sep  2,  2026 "), "2026-09-02")
        for bad in ("Feb 29, 2026", "Sept 2, 2026", "2026-09-02", "09/02/2026", "", None):
            self.assertIsNone(site.statement_date(bad), repr(bad))

    def test_rules_classify(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        self.assertEqual(doc_types.classify_document("SDG&E Bill 2026-09-12", rules)[:2], ("Statement", "Utility Bill"))


class ListReady(unittest.TestCase):
    def test_rows_are_read_from_the_page(self):
        page = Page()
        self.assertEqual([d.document_id for d in site.collect_download_docs(page)], [ID1, ID2, ID3])
        self.assertEqual(page.gotos, [site.DOCUMENTS_URL])
        self.assertEqual(page.context.request.asked, [], "the list asks nothing of its own")

    def test_the_empty_table_is_not_yet_read_as_no_bills(self):
        # Never seen live, so it stops the list rather than calling it whole.
        with self.assertRaises(site.ListStopped):
            site.collect_download_docs(Page(rows=[], empty="No data available in table"))

    def test_a_sign_out_during_the_wait_for_rows_is_session_expired(self):
        page = Page(rows=[], empty="Loading...")
        real = page.wait_for_selector

        def wait(sel, **kw):
            page.url = f"https://{HOST}/portal/PreLogin/Validate"
            return real(sel, **kw)
        page.wait_for_selector = wait
        with self.assertRaises(site.SessionExpired):
            site.collect_download_docs(page)

    def test_a_list_that_never_draws_stops(self):
        for page in (Page(ready=False), Page(rows=[], empty="Loading..."), Page(rows=[], empty="")):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(page)
            self.assertFalse(site.bill_list_opens(page))
        self.assertFalse(site.goto_documents(Page(ready=False)))
        self.assertTrue(site.bill_list_opens(Page()))

    def test_a_signed_out_portal_is_session_expired(self):
        for page in (Page(settled=f"https://{HOST}/portal/PreLogin/Validate"),
                     Page(ready=False, password=True)):
            with self.assertRaises(site.SessionExpired):
                site.collect_download_docs(page)

    def test_a_page_that_settles_elsewhere_is_not_read(self):
        for where in ("https://www.sdge.com/", f"https://{HOST}/portal/Dashboard/index"):
            with self.assertRaises(site.ListStopped):
                site.collect_download_docs(Page(settled=where))


class SignedOut(unittest.TestCase):
    def test_sign_in_shapes(self):
        self.assertTrue(site.looks_signed_out(Page(start=f"https://{HOST}/portal/PreLogin/Validate")))
        self.assertTrue(site.looks_signed_out(Page(start=f"https://{HOST}/portal/Accounts/Logout")))
        self.assertTrue(site.looks_signed_out(Page(start=site.DOCUMENTS_URL, password=True)))
        self.assertFalse(site.looks_signed_out(Page(start=site.DOCUMENTS_URL)))

    def test_a_dead_page_raises(self):
        with self.assertRaises(RuntimeError):
            site.looks_signed_out(Dead())


class Download(unittest.TestCase):
    def fetch(self, page, date="2026-09-12", inv=ID1, href=None):
        td = tempfile.mkdtemp()
        out = Path(td) / "o.pdf"
        ok = site.download_bill(page, None, date, out, title="SDG&E Bill " + date, trace=[],
                                href=site.DOWNLOAD_PATH if href is None else href, document_id=inv)
        return ok, out

    def test_one_request_with_the_exact_id_and_no_redirect(self):
        page = Page(answers=[Resp(ctype="Application/PDF; charset=binary",
                                  extra={"content-disposition": "attachment; filename=x.pdf"})])
        ok, out = self.fetch(page)
        self.assertTrue(ok)
        self.assertEqual(page.context.request.asked, [(PDF_URL, 0)])
        self.assertTrue(out.read_bytes().startswith(b"%PDF-"))

    def test_no_single_matching_row_means_no_request(self):
        for page, kw in [(Page(answers=[Resp()]), dict(date="2026-09-11")),
                         (Page(answers=[Resp()]), dict(inv="ISU000000000999")),
                         (Page(answers=[Resp()]), dict(inv="")),
                         (Page(answers=[Resp()]), dict(href="/portal/BillingHistory/DownloadBillPdf?invoiceId=" + ID1)),
                         (Page(rows=ROWS + [dict(ROWS[0])], answers=[Resp()]), {}),
                         (Page(rows=[], empty="No data available in table", answers=[Resp()]), {})]:
            ok, out = self.fetch(page, **kw)
            self.assertFalse(ok, kw)
            self.assertEqual(page.context.request.asked, [], kw)
            self.assertFalse(out.exists())

    def test_signed_out_answers_raise_and_save_nothing(self):
        for answer in [Resp(302, ctype="text/html", body=b"", location="/portal/PreLogin/Validate"),
                       Resp(302, ctype="text/html", body=b"", location=PDF_URL.replace(ID1, ID2)),
                       Resp(401, ctype="application/json", body=b'{"StatusCode":401}'),
                       Resp(200, ctype="application/json", body=b'{"StatusCode":401}'),
                       Resp(200, ctype="text/html; charset=utf-8", body=b"<html>Log into My Energy Center</html>"),
                       Resp(403, ctype="text/plain", body=b"no")]:
            page = Page(answers=[answer])
            with self.assertRaises(site.SessionExpired):
                self.fetch(page)
            self.assertEqual(len(page.context.request.asked), 1, "a redirect is never followed")
            self.assertEqual(page.context.request.asked[0][1], 0)

    def test_a_list_showing_the_sign_in_page_raises(self):
        with self.assertRaises(site.SessionExpired):
            self.fetch(Page(settled=f"https://{HOST}/portal/PreLogin/Validate", answers=[Resp()]))

    def test_sign_in_bodies_labelled_as_pdf_are_session_expired(self):
        for answer in [Resp(body=b"<!doctype html><html>Log in</html>"),
                       Resp(body=b'  {"StatusCode":401}'),
                       Resp(ctype="application/problem+json", body=b'{"status":401}')]:
            with self.assertRaises(site.SessionExpired):
                self.fetch(Page(answers=[answer]))

    def test_other_non_pdfs_are_refused_without_a_file(self):
        for answer in [Resp(500, ctype="text/plain"), Resp(ctype="application/octet-stream"),
                       Resp(body=b"not a pdf")]:
            ok, out = self.fetch(Page(answers=[answer]))
            self.assertFalse(ok)
            self.assertFalse(out.exists())


def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


class Orchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_persisted_record_has_no_query_and_is_keyed_by_the_id(self):
        app = make_app(self.tmp, "--discover")
        for r in site.bills_of(ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.discovery.save()
        text = app.paths.discovery_json.read_text()
        self.assertNotIn("?", text)
        self.assertNotIn("invoiceId", text)
        rec = app.discovery.get("id:" + ID1)
        self.assertEqual((rec["href"], rec["document_id"], rec["account"], rec["summary"]),
                         (site.DOWNLOAD_PATH, ID1, "", "Utility Bill"))
        self.assertEqual(docs.told_apart_by(rec), ID1[-6:], "only a taken name gets the id's end")

    def test_an_expired_session_stops_the_run_and_records_nothing(self):
        app = make_app(self.tmp, "--all")
        for r in site.bills_of(ROWS):
            app._record_rawdoc(r, site.BILLING_URL)
        app.check_session = lambda page: None
        app._on_its_site = lambda: Page()
        app._delay = lambda *a, **k: None

        def expired(*a, **k):
            raise site.SessionExpired("signed out")
        original = site.download_bill
        site.download_bill = expired
        try:
            with redirect_stdout(io.StringIO()) as said, self.assertRaises(SystemExit):
                app.process(app._select())
        finally:
            site.download_bill = original
        self.assertIn("signed out", said.getvalue())
        self.assertEqual(app.progress.data, {})
        self.assertEqual(app.stats["manual_review"] + app.stats["failed"], 0)

    def test_an_expired_session_during_discovery_stops_the_run(self):
        # check_session is not stubbed: the list opens and signs out in one
        # step, so no prompt to sign in again is ever reached.
        app = make_app(self.tmp, "--discover")
        app.page = lambda: Page(settled=f"https://{HOST}/portal/PreLogin/Validate")
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            app.cmd_discover()
        self.assertEqual(app.discovery.data, {})
        self.assertIn("signed out", out.getvalue())
        self.assertNotIn("Press Enter", out.getvalue())
        self.assertFalse(list((Path(self.tmp) / "out").rglob("*.json")) and
                         any("failure" in p.name.lower() for p in (Path(self.tmp) / "out").rglob("*")))

    def test_pilot_gate(self):
        from paperpull_core.models import State

        class D:
            def __init__(self, k):
                self.key = k
        done = {"a": {"state": State.COMPLETED.value}}
        self.assertFalse(docs.pilot_failed(done, [D("a")]))
        self.assertTrue(docs.pilot_failed({"a": {"state": State.FAILED.value}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({"a": {"state": "Needs Manual Review"}}, [D("a")]))
        self.assertTrue(docs.pilot_failed({}, [D("a")]))
        self.assertTrue(docs.pilot_failed(done, []))


class Privacy(unittest.TestCase):
    """Nothing that names the account reaches a log line or the console,
    and all of it is registered as private words."""

    def test_account_details_stay_out_of_logs_and_stdout(self):
        tmp = tempfile.mkdtemp()
        app = make_app(tmp, "--all")
        seen = io.StringIO()
        handler = logging.StreamHandler(seen)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(seen):
                page = Page(accounts=2, answers=[Resp()])
                for r in site.collect_download_docs(page):
                    app._record_rawdoc(r, site.BILLING_URL)
                app.discovery.save()
                app.check_session = lambda p: None
                app._delay = lambda *a, **k: None
                app._on_its_site = lambda: Page(accounts=2, answers=[Resp(body=b"%PDF-1.4 " + b"x" * 3000)])
                app.process(app._select(limit=1))
                bad = Page(accounts=2, rows=ROWS + [{"id": ID3, "date": "Sep 12, 2026"}])
                with self.assertRaises(site.ListStopped):
                    site.collect_download_docs(bad)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        out = seen.getvalue() + app.paths.discovery_json.read_text() + app.paths.progress_json.read_text()
        self.assertIn("accounts", seen.getvalue(), "the one-account notice was said")
        for word in (FAKE_ACCOUNT, FAKE_CONTRACT, FAKE_STREET):
            self.assertNotIn(word, out)
        for word in (FAKE_ACCOUNT + "0", FAKE_CONTRACT, FAKE_STREET):
            self.assertIn(word, site.private_words())
        self.assertIn("Tester", site.private_words(), "the owner's name is kept beside them")
        self.assertNotIn(FAKE_CONTRACT, site.redact("contract " + FAKE_CONTRACT))
        self.assertIn("CAPTCHA", site.redact("CAPTCHA Statement"), "a short address part is not a word")
        self.assertEqual(len(site.private_words()), len(set(site.private_words())), "nothing twice")
        names = [p.name for p in app.paths.root.rglob("*.pdf")]
        self.assertEqual(len(names), 1)
        self.assertNotIn("ISU", names[0])


class NothingPressed(unittest.TestCase):
    def test_the_site_layer_never_clicks_fills_selects_or_presses(self):
        tree = ast.parse((HERE / "sdge_site.py").read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                     "uncheck", "set_input_files", "dispatch_event", "press_sequentially"):
            self.assertNotIn(verb, called, verb)


if __name__ == "__main__":
    unittest.main()
