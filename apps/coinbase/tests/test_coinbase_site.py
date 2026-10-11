"""The checks that have to pass before this app touches a real account.
Run:  <bundled python> -m unittest discover -s tests   (from the install folder)
No browser, no network: pages, locators and HTTP answers are fakes."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import coinbase_site as site  # noqa: E402
import coinbase_docs as docs  # noqa: E402


class Guard(unittest.TestCase):
    def test_allows_document_controls(self):
        for label in ["PDF", "Download PDF", "Download statement", "Monthly statement",
                      "View document", "Download", "Load more", "Download\n\U000f0382"]:
            self.assertTrue(site.is_safe_control(label), label)

    def test_denies_everything_else(self):
        for label in ["Download and continue", "Generate custom statement", "Generate",
                      "Request report", "Settings", "Advanced trade", "Buy", "Sell", "Send",
                      "Convert", "Export CSV", "CSV", "HTML", "Create API key", "Sign in",
                      "Statement settings", "Mark as read", "", None, "   ", "Deposit",
                      "Manage funds", "Allow all", "Confirm my choices"]:
            self.assertFalse(site.is_safe_control(label), repr(label))


class Hosts(unittest.TestCase):
    def test_exact_hosts(self):
        for u in ["https://accounts.coinbase.com/statements", "https://accounts.coinbase.com/a/b.pdf",
                  "https://accounts.coinbase.com/", "https://www.coinbase.com/", "https://www.coinbase.com/home"]:
            self.assertTrue(site.is_safe_url(u), u)
        for u in ["http://accounts.coinbase.com/statements", "https://accounts.coinbase.com:8443/statements",
                  "https://coinbase.com/statements", "https://login.coinbase.com/signin",
                  "https://api.coinbase.com/v2/accounts", "https://accounts.coinbase.com.evil.test/statements",
                  "https://accounts.coinbase.com@evil.test/statements", "https://notcoinbase.com/", "", None]:
            self.assertFalse(site.is_safe_url(u), repr(u))

    def test_list_calls_keep_to_their_paths(self):
        for u in ["https://accounts.coinbase.com/statements", "https://accounts.coinbase.com/taxes/documents",
                  "https://accounts.coinbase.com/v2/tax/forms?types=1099-DA&year=2025",
                  "https://accounts.coinbase.com/v2/tax/owner-info", "https://www.coinbase.com/"]:
            self.assertTrue(site.is_list_url(u), u)
        for u in ["https://accounts.coinbase.com/settings", "https://accounts.coinbase.com/v2/tax/forms/abc/mark-read",
                  "https://accounts.coinbase.com/v2/tax/transactions", "https://www.coinbase.com/advanced-markets",
                  "https://www.coinbase.com/settings", "https://login.coinbase.com/signin", "",
                  # A path left open below v1/statements took ".." as one of its parts.
                  "https://accounts.coinbase.com/v1/statements/../settings",
                  "https://accounts.coinbase.com/v1/statements/../../v2/accounts",
                  "https://accounts.coinbase.com/v1/statements/abc",
                  "https://accounts.coinbase.com/v2/tax/forms/../../settings"]:
            self.assertFalse(site.is_list_url(u), repr(u))

    def test_download_hosts_exact(self):
        self.assertTrue(site.is_download_url("https://statements-report-persistent-production.s3.amazonaws.com/a_b__pdf.pdf"))
        self.assertTrue(site.is_download_url("https://tax-center-forms-production.s3.amazonaws.com/2025/x/y.pdf?X-Amz-Signature=abc"))
        for u in ["https://s3.amazonaws.com/statements-report-persistent-production/a.pdf",
                  "https://evil.s3.amazonaws.com/a.pdf", "http://tax-center-forms-production.s3.amazonaws.com/a.pdf",
                  "https://accounts.coinbase.com/statements", "https://tax-center-forms-production.s3.amazonaws.com.evil.test/a.pdf", ""]:
            self.assertFalse(site.is_download_url(u), u)


class Rows(unittest.TestCase):
    def test_month_to_iso(self):
        self.assertEqual(site.month_to_iso("September 2026"), "2026-09-30")
        self.assertEqual(site.month_to_iso("February 2024"), "2024-02-29")
        self.assertEqual(site.month_to_iso("Last 30 days"), "")
        self.assertEqual(site.month_to_iso(""), "")
        self.assertEqual(site.month_to_iso("Sept 2026"), "")

    def test_row_binding_is_exact(self):
        rows = [{"label": "Last 30 days", "button": "PDF", "i": 0},
                {"label": "September 2026", "button": "PDF", "i": 1},
                {"label": "August 2026", "button": "PDF", "i": 2}]
        self.assertEqual(site.row_index_for(rows, "August 2026"), (2, "PDF"))
        self.assertEqual(site.row_index_for(rows, "July 2026"), (-1, ""))
        twice = rows + [{"label": "August 2026", "button": "PDF", "i": 3}]
        self.assertEqual(site.row_index_for(twice, "August 2026"), (-1, ""),
                         "two rows with one label: nothing is chosen")

    def test_statement_title_roundtrip(self):
        d = site.RawDoc(title="Monthly Statement September 2026", date_text="2026-09-30")
        m = site._STATEMENT_TITLE_RE.match(d.title)
        self.assertEqual(site.month_to_iso(m.group(1)), d.date_text)


def row(label, i):
    return {"label": label, "button": "PDF", "i": i}


class ListPage:
    """A statements page showing these rows, with no Load more unless a test
    gives it one. Every wait is a moment, and is counted."""
    url = site.STATEMENTS_URL

    def __init__(self, rows, load_more=None):
        self.rows, self.load_more, self.waits = list(rows), load_more, []

    def locator(self, sel):
        if sel == site._LOAD_MORE and self.load_more is not None:
            return self.load_more
        page = self

        class L:
            def count(s): return 0 if sel == site._LOAD_MORE else len(page.rows)
            def is_visible(s): return False
            def is_enabled(s, **kw): return False
            @property
            def first(s): return s
        return L()

    def evaluate(self, js): return list(self.rows)

    def wait_for_timeout(self, ms): self.waits.append(ms)


class LoadMore:
    """A Load more that shows, or not, at each look, as `shows` says, and is
    turned on as `on` says."""

    def __init__(self, shows, on=True):
        self.shows, self.on, self.looks = list(shows), on, 0

    @property
    def first(self): return self

    def count(self):
        self.looks += 1
        return 1 if (self.shows.pop(0) if self.shows else False) else 0

    def is_visible(self): return True
    def is_enabled(self, **kw): return self.on
    def inner_text(self, **kw): return "Load more"
    def get_attribute(self, name): return None


class StatementList(unittest.TestCase):
    """The statements list is called whole only when it is."""

    TODAY = date(2026, 10, 11)
    MONTHS = [row("Last 30 days", 0), row("September 2026", 1), row("August 2026", 2)]

    def test_two_last_30_days_rows_stop_the_list(self):
        rows = self.MONTHS + [row("Last 30 days", 3)]
        with self.assertRaises(site.ListStopped):
            site._collect_statements(ListPage(rows), "2026-08-03", self.TODAY)

    def test_a_list_reaching_the_first_month_is_whole(self):
        got = site._collect_statements(ListPage(self.MONTHS), "2026-08-03", self.TODAY)
        self.assertEqual([d.date_text for d in got], ["2026-09-30", "2026-08-31"])
        got = site._collect_statements(ListPage(self.MONTHS), "2026-09-20", self.TODAY)
        self.assertEqual(len(got), 2, "months before the first transaction are kept too")

    def test_a_list_short_of_the_first_month_stops_holding_what_it_read(self):
        with self.assertRaises(site.ListStopped) as stopped:
            site._collect_statements(ListPage(self.MONTHS), "2021-04-03", self.TODAY)
        self.assertEqual([d.date_text for d in stopped.exception.docs], ["2026-09-30", "2026-08-31"])
        with self.assertRaises(site.ListStopped):
            site._collect_statements(ListPage(self.MONTHS), "2026-07-31", self.TODAY)

    def test_a_list_of_no_month_is_not_read_as_an_empty_one(self):
        """Every month row read as something else used to leave nothing to
        list, and the listing was called whole."""
        page = ListPage([row("Last 30 days", 0)])
        with self.assertRaises(site.ListStopped):
            site._collect_statements(page, "2024-01-05", self.TODAY)
        self.assertEqual(sum(page.waits[:-1]), site.MONTH_ROWS_WAIT_MS, "the month rows were waited for")

    def test_an_account_with_no_complete_month_lists_none(self):
        page = ListPage([row("Last 30 days", 0)])
        self.assertEqual(site._collect_statements(page, "2026-10-02", self.TODAY), [])

    def test_an_account_whose_first_transaction_is_not_said_stops_the_list(self):
        with self.assertRaises(site.ListStopped):
            site._collect_statements(ListPage(self.MONTHS), "", self.TODAY)

    def test_the_first_transaction_is_read_from_owner_info(self):
        for answer, first in (({"first_transaction_date": "2021-04-03T10:00:00Z"}, "2021-04-03"),
                              ({"first_transaction_date": ""}, ""), ({}, ""), (None, ""),
                              ([{"first_transaction_date": "2021-04-03"}], ""),
                              ({"first_transaction_date": "2021-13-03"}, "")):
            with mock.patch.object(site, "_get_json", lambda page, url, a=answer: a):
                self.assertEqual(site._first_transaction(object()), first, answer)
        self.assertEqual(site._first_tax_year("2021-04-03"), 2021)
        self.assertEqual(site._first_tax_year(""), 2012)

    def test_load_more_is_looked_for_once_more_before_the_end(self):
        page = ListPage(self.MONTHS, load_more=LoadMore([False, True]))
        pressed = []

        def click(pg, loc, **kw):
            pressed.append(kw["step"])
            pg.rows.append(row("July 2026", 3))
        with mock.patch.object(site.pressing, "click", click):
            self.assertTrue(site._press_load_more(page))
        self.assertEqual(pressed, ["load more of the list"])
        self.assertIn(site.LOAD_MORE_LOOK_AGAIN_MS, page.waits)

    def test_no_load_more_at_either_look_is_the_end(self):
        lm = LoadMore([False, False])
        page = ListPage(self.MONTHS, load_more=lm)
        with mock.patch.object(site.pressing, "click") as click:
            self.assertFalse(site._press_load_more(page))
        self.assertEqual(click.call_count, 0)
        self.assertEqual(lm.looks, 2)
        self.assertEqual(page.waits, [site.LOAD_MORE_LOOK_AGAIN_MS])

    def test_a_turned_off_load_more_is_not_pressed(self):
        page = ListPage(self.MONTHS, load_more=LoadMore([True, True], on=False))
        with mock.patch.object(site.pressing, "click") as click:
            self.assertFalse(site._press_load_more(page))
        self.assertEqual(click.call_count, 0)


class TaxList(unittest.TestCase):
    def test_duplicate_forms_keep_both(self):
        forms = {2025: [{"id": "11111111-2222-3333-4444-555555555555", "form_type": "1099-DA"},
                        {"id": "aaaa1111-bbbb-2222-cccc-333344445555", "form_type": "1099-DA"},
                        {"id": "x", "form_type": "1099-MISC"}]}
        reports = [{"id": "rpt00001", "name": "PregeneratedGainLossPDF", "year": 2021,
                    "file": {"file_type": "PDF", "url": "https://tax-center-forms-production.s3.amazonaws.com/x?sig=1"}}]
        out = site.tax_rawdocs(forms, reports)
        titles = [d.title for d in out]
        self.assertEqual(titles, ["1099-DA Tax Year 2025 (#11111111222233334444555555555555)",
                                  "1099-DA Tax Year 2025 (#aaaa1111bbbb2222cccc333344445555)",
                                  "1099-MISC Tax Year 2025", "Gain Loss Report Tax Year 2021"])
        two = reports + [dict(reports[0], id="ffff0000")]
        rt = [d.title for d in site.tax_rawdocs({}, two)]
        self.assertEqual(rt, ["Gain Loss Report Tax Year 2021 (#rpt00001)", "Gain Loss Report Tax Year 2021 (#ffff0000)"])
        same_prefix = {2025: [{"id": "form0001-1111", "form_type": "1099-DA"}, {"id": "form0001-2222", "form_type": "1099-DA"}]}
        self.assertEqual(len({d.title for d in site.tax_rawdocs(same_prefix, [])}), 2)
        for d in out:
            self.assertTrue(site._TAX_TITLE_RE.match(d.title), d.title)
            self.assertNotIn("?", d.href); self.assertNotIn("http", d.href)
            self.assertRegex(d.date_text, r"^\d{4}-12-31$")

    def test_unreadable_rows_stop_the_statement_list(self):
        first, today = "2026-09-12", date(2026, 10, 11)
        ok = [{"label": "Last 30 days", "button": "PDF", "i": 0}, {"label": "September 2026", "button": "PDF", "i": 1}]
        self.assertEqual([d.date_text for d in site._collect_statements(ListPage(ok), first, today)],
                         ["2026-09-30"])
        for bad in ([{"label": "", "button": "PDF", "i": 0}],
                    [{"label": "September 2026", "button": "PDF", "i": 0}, {"label": "September 2026", "button": "PDF", "i": 1}],
                    [{"label": "Credit Card", "button": "PDF", "i": 0}], []):
            with self.assertRaises(site.ListStopped):
                site._collect_statements(ListPage(bad), first, today)

    def test_tax_pages_that_cannot_be_exhausted_stop_the_list(self):
        answers = []
        class Resp:
            ok, status, url, headers = True, 200, "", {}
            def json(self): return answers.pop(0)
            def dispose(self): pass
        class Req:
            def get(self, url, **kw): return Resp()
        class Ctx: request = Req()
        class Page: context = Ctx()
        answers[:] = [{"data": [{"id": "a"}], "next_cursor": "c1"}, {"data": [{"id": "b"}], "next_cursor": "c1"}]
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        answers[:] = [{"data": [{"id": "x"}], "next_cursor": "c%d" % i} for i in range(1, 40)]
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        answers[:] = [{"data": [{"id": "a"}], "next_cursor": "c1"}, {"data": [{"id": "b"}], "next_cursor": ""}]
        self.assertEqual([i["id"] for i in site._tax_forms_for(Page(), 2025)], ["a", "b"])

    @staticmethod
    def _answering(*answers):
        """A page whose list calls answer these, one per call, in order."""
        left = list(answers)

        class Resp:
            ok, status, url, headers = True, 200, "", {}
            def json(self): return left.pop(0)
            def dispose(self): pass

        class Req:
            def get(self, url, **kw): return Resp()

        class Ctx: request = Req()

        class Page: context = Ctx()
        return Page()

    def test_a_form_that_names_another_year_stops_the_list(self):
        for said in ({"tax_year": 2024}, {"year": "2024"}):
            page = self._answering({"data": [dict({"id": "form0001"}, **said)], "next_cursor": ""})
            with self.assertRaises(site.ListStopped):
                site._tax_forms_for(page, 2025)
        for said in ({"tax_year": 2025}, {"year": "2025"}, {}):
            page = self._answering({"data": [dict({"id": "form0001"}, **said)], "next_cursor": ""})
            self.assertEqual([i["id"] for i in site._tax_forms_for(page, 2025)], ["form0001"])

    def test_a_forms_answer_that_is_not_a_list_of_forms_stops_the_list(self):
        for answer in ([{"id": "form0001"}], {"data": ["form0001"]}, {"data": {"id": "form0001"}}):
            with self.assertRaises(site.ListStopped):
                site._tax_forms_for(self._answering(answer), 2025)

    def test_a_reports_list_with_more_than_one_page_stops_the_list(self):
        pdf = {"id": "rpt0001", "name": "PregeneratedGainLossPDF", "year": 2024, "file": {"file_type": "PDF"}}
        csv = {"id": "rpt0002", "name": "PregeneratedGainLossCSV", "year": 2024, "file": {"file_type": "CSV"}}
        for answer in ({"data": [pdf], "next_cursor": "c1"},
                       {"data": [pdf], "pagination": {"next_uri": "/v2/tax/tax-reports?starting_after=x"}},
                       {"data": [dict(pdf, id="rpt%04d" % i) for i in range(200)]}):
            with self.assertRaises(site.ListStopped):
                site._tax_reports(self._answering(answer))
        got = site._tax_reports(self._answering({"data": [pdf, csv], "next_cursor": "",
                                                 "pagination": {"next_uri": None}}))
        self.assertEqual([r["id"] for r in got], ["rpt0001"])

    def test_documents_without_an_id_or_a_year_stop_the_list(self):
        with self.assertRaises(site.ListStopped):
            site.tax_rawdocs({2025: [{"id": "", "form_type": "1099-DA"}]}, [])
        with self.assertRaises(site.ListStopped):
            site.tax_rawdocs({2025: [{"id": "same", "form_type": "1099-DA"}, {"id": "same", "form_type": "1099-MISC"}]}, [])
        with self.assertRaises(site.ListStopped):
            site.tax_rawdocs({}, [{"id": "r1", "name": "PregeneratedGainLossPDF", "file": {"file_type": "PDF", "url": "x"}}])
        with self.assertRaises(site.ListStopped):
            site.tax_rawdocs({}, [{"id": "", "name": "PregeneratedGainLossPDF", "year": 2021}])

    def test_unreadable_year_stops_the_list(self):
        class Resp:
            ok, status, url, headers = False, 500, "", {}
            def json(self): return {}
            def dispose(self): pass
        class Req:
            def get(self, url, **kw): return Resp()
        class Ctx: request = Req()
        class Page: context = Ctx()
        with self.assertRaises(site.ListStopped):
            site._tax_forms_for(Page(), 2025)
        with self.assertRaises(site.ListStopped):
            site._tax_reports(Page())

    def _fetch(self, title, forms, document_id=""):
        """_fetch_tax_pdf over a list of these forms, with Coinbase's tax host
        answering a PDF. Returns whether it saved and what it asked for."""
        asked = []

        class Resp:
            ok, status = True, 200
            def body(self): return b"%PDF-1.4 invented"

        class Req:
            def get(self, url, **kw): asked.append(url); return Resp()

        class Ctx: request = Req()

        class Page: context = Ctx()
        with mock.patch.object(site, "_tax_forms_for", lambda p, y: forms):
            with tempfile.TemporaryDirectory() as td:
                ok = site._fetch_tax_pdf(Page(), title, Path(td) / "out.pdf", [], document_id)
        return ok, asked

    @staticmethod
    def _form(did, form_type=None):
        out = {"id": did, "files": [{"file_type": "pdf",
                                     "url": "https://tax-center-forms-production.s3.amazonaws.com/%s.pdf" % did}]}
        if form_type is not None:
            out["form_type"] = form_type
        return out

    def test_a_form_the_list_names_no_type_for_is_found_by_its_title(self):
        forms = [self._form("form0001")]
        title = site.tax_rawdocs({2025: forms}, [])[0].title
        self.assertEqual(title, "Tax Form Tax Year 2025")
        ok, asked = self._fetch(title, forms)
        self.assertTrue(ok)
        self.assertEqual(len(asked), 1)

    def test_each_tax_document_keeps_its_own_id(self):
        forms = [self._form("form0001", "1099-DA"), self._form("form0002", "1099-DA")]
        reports = [{"id": "rpt0001", "name": "PregeneratedGainLossPDF", "year": 2024,
                    "file": {"file_type": "PDF", "url": "https://tax-center-forms-production.s3.amazonaws.com/r.pdf"}}]
        got = site.tax_rawdocs({2025: forms}, reports)
        self.assertEqual([d.document_id for d in got], ["form0001", "form0002", "rpt0001"])

    def test_a_second_form_of_a_year_leaves_the_first_s_key_as_it_was(self):
        first = self._form("form0001", "1099-DA")
        alone = site.tax_rawdocs({2025: [first]}, [])[0]
        beside = site.tax_rawdocs({2025: [first, self._form("form0002", "1099-DA")]}, [])[0]
        self.assertNotEqual(alone.title, beside.title, "the first form's title takes the suffix")
        key = lambda r: docs.Document(title=r.title, category="Tax Document", date=r.date_text,
                                      document_id=r.document_id).key
        self.assertEqual(key(alone), key(beside))

    def test_a_tax_document_is_fetched_by_the_id_its_record_keeps(self):
        """The first form was listed alone, so its title has no suffix, and
        a second form of that year came since."""
        forms = [self._form("form0001", "1099-DA"), self._form("form0002", "1099-DA")]
        ok, asked = self._fetch("1099-DA Tax Year 2025", forms, document_id="form0001")
        self.assertTrue(ok)
        self.assertEqual(asked, ["https://tax-center-forms-production.s3.amazonaws.com/form0001.pdf"])
        ok, asked = self._fetch("1099-DA Tax Year 2025", forms, document_id="form0009")
        self.assertFalse(ok, "an id the list no longer names fetches nothing")
        self.assertEqual(asked, [])

    def test_a_listed_tax_document_is_recorded_and_fetched_by_its_id(self):
        app, _failures = built_app(self)
        first = self._form("form0001", "1099-DA")
        for r in site.tax_rawdocs({2025: [first]}, []):
            app._record_rawdoc(r, site.BILLING_URL)
        for r in site.tax_rawdocs({2025: [first, self._form("form0002", "1099-DA")]}, []):
            app._record_rawdoc(r, site.BILLING_URL)
        self.assertEqual(sorted(app.discovery.data), ["id:form0001", "id:form0002"])
        doc = docs.Document.from_dict(app.discovery.get("id:form0001"))
        self.assertEqual(doc.title, "1099-DA Tax Year 2025")
        handed = []

        def hands_over(page, dl_dir, iso, out_path, title="", trace=None, document_id=""):
            handed.append((title, document_id))
            return False
        with mock.patch.object(site, "goto_documents", lambda page: True), \
                mock.patch.object(site, "download_bill", hands_over), \
                mock.patch.object(docs, "write_shaped", lambda *a, **kw: None):
            app.download_one(mock.Mock(url=site.TAX_URL), doc, "2025-12-31 Coinbase 1099-DA Tax Form.pdf")
        self.assertEqual(handed, [("1099-DA Tax Year 2025", "form0001")])

    def test_tax_pdf_link_off_host_is_refused(self):
        page = object()
        orig = site._tax_forms_for
        site._tax_forms_for = lambda p, y: [{"id": "abc", "form_type": "1099-DA",
                                            "files": [{"file_type": "pdf", "url": "https://evil.example/x.pdf"}]}]
        try:
            trace = []
            with tempfile.TemporaryDirectory() as td:
                ok = site._fetch_tax_pdf(page, "1099-DA Tax Year 2025", Path(td) / "out.pdf", trace)
            self.assertFalse(ok)
            self.assertEqual(trace[-1]["note"], "document link refused")
            self.assertNotIn("url", trace[-1]); self.assertEqual(trace[-1]["host"], "evil.example")
        finally:
            site._tax_forms_for = orig


class StatementDownload(unittest.TestCase):
    """The one PDF button is pressed, through the core, and a download from
    any host but the exact one is refused."""

    ROWS = [{"label": "Last 30 days", "button": "PDF", "i": 0},
            {"label": "September 2026", "button": "PDF", "i": 1},
            {"label": "August 2026", "button": "PDF", "i": 2}]

    def make_page(self, dl_url, rows=None):
        """A statements page with these rows, whose PDF buttons, pressed,
        hand the browser one download from `dl_url`. Each button reads its
        own row's label as the page shows it (page.row_says), so a test can
        draw a row anew under a button."""
        site_ref = site
        class Download:
            url = dl_url; suggested_filename = "x.pdf"; cancelled = False; event_bytes = b"%PDF-1.4 fake"
            def cancel(self): self.cancelled = True
            def save_as(self, path): Path(path).write_bytes(self.event_bytes)
        dl = Download()
        class Resp:
            ok, status = True, 200
            def body(self): return b"%PDF-1.4 fetched"
        class Req:
            def __init__(self): self.asked = []
            def get(self, url, **kw): self.asked.append((url, kw.get("max_redirects"))); return Resp()
        class Ctx:
            def __init__(self): self.request, self.pages = Req(), []
        class El:
            """One PDF button held as an element. The core's own reads of it
            find nothing, as on a page that lets no script answer, and its
            row label is read from the page."""
            def __init__(self, page, i): self.page, self.i = page, i
            def evaluate(self, js, arg=None):
                if js == site_ref._LABEL_OF_JS:
                    return self.page.row_says.get(self.i, self.page.rows[self.i]["label"])
                return None
            def scroll_into_view_if_needed(self, **kw): pass
            def dispose(self): self.page.disposed += 1
            def click(self, **kw):
                self.page.clicked += 1
                for ev, cb in list(self.page.handlers):
                    if ev == "download":
                        for d in [dl] + self.page.also:
                            cb(d)
        class Button:
            def __init__(self, page, i): self.page, self.i = page, i
            def element_handle(self, **kw): return El(self.page, self.i)
        class Loc:
            def __init__(self, n, page): self.n, self.page = n, page
            def count(self): return self.n
            def is_visible(self): return self.n > 0
            @property
            def first(self): return self
            def nth(self, i): return Button(self.page, i)
        class Page:
            url = site_ref.STATEMENTS_URL
            main_frame = object()
            def __init__(self):
                self.clicked, self.disposed, self.handlers, self.context = 0, 0, [], Ctx()
                self.rows, self.row_says = list(rows if rows is not None else StatementDownload.ROWS), {}
                # Downloads a press hands over beside its own, and one that is
                # on its way as the capture starts listening.
                self.also, self.early = [], None
            def on(self, ev, cb):
                self.handlers.append((ev, cb))
                if ev == "download" and self.early:
                    cb(self.early)
            def remove_listener(self, ev, cb): self.handlers.remove((ev, cb))
            def locator(self, sel):
                return Loc(0, self) if sel == site_ref._LOAD_MORE else Loc(len(self.rows), self)
            def evaluate(self, js): return list(self.rows)
            def wait_for_timeout(self, ms): pass
        return Page(), dl

    S3 = "https://statements-report-persistent-production.s3.amazonaws.com/a__pdf.pdf"

    def test_off_host_download_is_refused_and_cancelled(self):
        page, dl = self.make_page("https://evil.example/statement.pdf")
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok); self.assertTrue(dl.cancelled); self.assertEqual(page.clicked, 1)
            self.assertFalse((Path(td) / "out.pdf").exists())
            self.assertEqual(trace[-1], {"note": "download refused", "host": "evil.example"})

    def test_exact_host_download_is_taken(self):
        page, dl = self.make_page(self.S3)
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertTrue(ok); self.assertEqual(page.clicked, 1)
            self.assertTrue((Path(td) / "out.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(page.handlers, [], "every listener was removed")
        self.assertEqual(page.disposed, 1, "the held button was let go")

    def test_present_row_needs_no_load_more(self):
        page, dl = self.make_page(self.S3)
        with mock.patch.object(site.pressing, "click") as load_more:
            with tempfile.TemporaryDirectory() as td:
                ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
                self.assertTrue(ok)
        self.assertEqual(load_more.call_count, 0)
        self.assertEqual(page.handlers, [], "the download listener was removed")

    def test_empty_event_file_is_not_a_document_and_nothing_else_is_taken(self):
        page, dl = self.make_page(self.S3)
        dl.event_bytes = b""
        with tempfile.TemporaryDirectory() as td:
            dl_dir = Path(td) / "dl"; dl_dir.mkdir()
            (dl_dir / "stray.pdf").write_bytes(b"%PDF-1.4 not ours")
            trace = []
            ok = site._catch_statement(page, dl_dir, "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok, "an empty event file and a stranger in the folder: nothing is taken")
            self.assertFalse((Path(td) / "out.pdf").exists())
            self.assertEqual(page.context.request.asked, [], "the document is never asked for a second time")
            self.assertTrue((dl_dir / "stray.pdf").exists())

    def test_off_host_event_is_never_fetched(self):
        page, dl = self.make_page("https://evil.example/a.pdf")
        with tempfile.TemporaryDirectory() as td:
            site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
            self.assertEqual(page.context.request.asked, [])

    def test_ambiguous_row_is_not_pressed(self):
        page, dl = self.make_page(self.S3, rows=[{"label": "August 2026", "button": "PDF", "i": 0},
                                                 {"label": "August 2026", "button": "PDF", "i": 1}])
        with tempfile.TemporaryDirectory() as td:
            ok = site._catch_statement(page, Path(td) / "dl", "August 2026", Path(td) / "out.pdf", [])
            self.assertFalse(ok); self.assertEqual(page.clicked, 0)

    def test_unsafe_button_label_is_not_pressed(self):
        page, dl = self.make_page(self.S3, rows=[{"label": "August 2026", "button": "Generate", "i": 0}])
        with tempfile.TemporaryDirectory() as td:
            ok = site._catch_statement(page, Path(td) / "dl", "August 2026", Path(td) / "out.pdf", [])
            self.assertFalse(ok); self.assertEqual(page.clicked, 0)

    def test_the_press_goes_through_the_core_with_the_guard_and_the_row(self):
        page, dl = self.make_page(self.S3)
        real = site.pressing.press_once
        asked = []

        def recorded(pg, el, **kw):
            asked.append(dict(kw, check_said=kw["check"]()))
            return real(pg, el, **kw)
        with mock.patch.object(site.pressing, "press_once", recorded):
            with tempfile.TemporaryDirectory() as td:
                ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
        self.assertTrue(ok)
        self.assertEqual(len(asked), 1)
        self.assertIs(asked[0]["guard"], site.is_safe_control)
        self.assertEqual(asked[0]["check_said"], "", "the row reads its month at the press")
        self.assertTrue(asked[0]["brought"](), "a download that came is what the press brought")

    def test_a_row_that_reads_another_month_at_the_press_is_not_pressed(self):
        """The list was read when the button was found, and the row under it
        reads August by the press. Nothing is pressed."""
        page, dl = self.make_page(self.S3)
        page.row_says[1] = "August 2026"
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
        self.assertFalse(ok); self.assertEqual(page.clicked, 0)
        self.assertEqual(trace[-1]["note"], "the PDF button's row no longer reads this month")

    def test_press_once_s_check_says_when_the_row_changed(self):
        page, dl = self.make_page(self.S3)
        said = []

        def drawn_anew_then_pressed(pg, el, **kw):
            pg.row_says[1] = "August 2026"
            said.append(kw["check"]())
            return site.pressing.Pressed(site.pressing.GONE)
        with mock.patch.object(site.pressing, "press_once", drawn_anew_then_pressed):
            with tempfile.TemporaryDirectory() as td:
                ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
        self.assertFalse(ok)
        self.assertEqual(said, ["its row reads another month"])

    def test_a_turned_off_button_leaves_the_statement_and_the_run_goes_on(self):
        page, dl = self.make_page(self.S3)
        off = site.pressing.TurnedOff("press a control", "the control is turned off", ["off"])
        with mock.patch.object(site.pressing, "press_once", side_effect=off):
            with tempfile.TemporaryDirectory() as td:
                trace = []
                ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
        self.assertFalse(ok)
        self.assertIn("turned off", trace[-1]["note"])
        self.assertEqual(page.handlers, [])

    def test_something_over_the_button_stops_the_run(self):
        """A prompt drawn over the list is no challenge to
        detect_security_challenge while rows show, and the core's own look
        at the press stops the run."""
        page, dl = self.make_page(self.S3)
        covered = site.pressing.Covered("press a control", "something on the page is over the control",
                                        ["covered"], after_a_press=True)
        with mock.patch.object(site.pressing, "press_once", side_effect=covered):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(site.pressing.Covered):
                    site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", [])
        self.assertEqual(page.handlers, [])

    def _with_load_more(self, page, adds):
        """Give the page a Load more that shows, and rows `adds` drawn once
        it is pressed through the core."""
        real_locator = page.locator

        class LM:
            def count(s): return 1
            def is_visible(s): return True
            def is_enabled(s, **kw): return True
            @property
            def first(s): return s
            def inner_text(s, **kw): return "Load more"
            def get_attribute(s, a): return None
        page.locator = lambda sel: LM() if sel == site._LOAD_MORE else real_locator(sel)
        presses = []

        def click(pg, loc, **kw):
            presses.append(kw)
            pg.rows.extend(adds)
        return presses, click

    def test_load_more_is_pressed_through_the_core(self):
        page, dl = self.make_page(self.S3)
        presses, click = self._with_load_more(page, [{"label": "July 2026", "button": "PDF", "i": 3}])
        with mock.patch.object(site.pressing, "click", click):
            with tempfile.TemporaryDirectory() as td:
                ok = site._catch_statement(page, Path(td) / "dl", "July 2026", Path(td) / "out.pdf", [])
        self.assertTrue(ok)
        self.assertEqual(len(presses), 1)
        self.assertEqual(presses[0]["css"], site._LOAD_MORE)
        self.assertEqual(presses[0]["step"], "load more of the list")

    def test_something_over_load_more_stops_the_run(self):
        """A stop at the press of Load more is not taken for a list that
        stopped partway, which would only leave the statement for review."""
        page, dl = self.make_page(self.S3)
        self._with_load_more(page, [])
        covered = site.pressing.Covered("load more of the list", "something on the page is over the control",
                                        ["covered"])
        with mock.patch.object(site.pressing, "click", side_effect=covered):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(site.pressing.Covered):
                    site._catch_statement(page, Path(td) / "dl", "July 2026", Path(td) / "out.pdf", [])
        self.assertEqual(page.clicked, 0)


    def test_a_second_download_after_one_press_takes_neither(self):
        """An earlier month's download, still on its way, comes during this
        press beside this one's own. Which is which cannot be told."""
        page, dl = self.make_page(self.S3)
        _, other = self.make_page(self.S3)
        page.also = [other]
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok)
            self.assertFalse((Path(td) / "out.pdf").exists())
        self.assertTrue(dl.cancelled and other.cancelled)
        self.assertEqual(page.clicked, 1)
        self.assertEqual(trace[-1]["downloads"], 2)

    def test_a_download_on_its_way_before_the_press_presses_nothing(self):
        page, dl = self.make_page(self.S3)
        _, early = self.make_page(self.S3)
        page.early = early
        with tempfile.TemporaryDirectory() as td:
            trace = []
            ok = site._catch_statement(page, Path(td) / "dl", "September 2026", Path(td) / "out.pdf", trace)
            self.assertFalse(ok)
            self.assertFalse((Path(td) / "out.pdf").exists())
        self.assertEqual(page.clicked, 0)
        self.assertTrue(early.cancelled)
        self.assertEqual(page.handlers, [])


class StatementsPageAfresh(unittest.TestCase):
    """The statements page is loaded again before every statement's press,
    even when the tab shows it already, so no earlier month's page is left
    polling for its PDF."""

    def make_page(self):
        class Loc:
            def count(self): return 0
        class Page:
            url = site.STATEMENTS_URL
            def __init__(self): self.loads = []
            def goto(self, url, **kw): self.loads.append(url)
            def locator(self, sel): return Loc()
            def wait_for_selector(self, sel, **kw): return True
        return Page()

    def test_reload_statements_loads_the_page_it_is_on(self):
        page = self.make_page()
        self.assertTrue(site.reload_statements(page))
        self.assertEqual(page.loads, [site.STATEMENTS_URL])

    def test_goto_documents_still_leaves_a_page_that_shows_its_list(self):
        page = self.make_page()
        self.assertTrue(site.goto_documents(page))
        self.assertEqual(page.loads, [])

    def test_every_statement_is_pressed_on_a_page_loaded_for_it(self):
        page = self.make_page()
        said = []

        def caught(pg, dl_dir, label, out_path, trace):
            said.append(("pressed", label, len(pg.loads)))
            return True
        with mock.patch.object(site, "_catch_statement", caught):
            with tempfile.TemporaryDirectory() as td:
                for title, iso in (("Monthly Statement September 2026", "2026-09-30"),
                                   ("Monthly Statement August 2026", "2026-08-31")):
                    self.assertTrue(site.download_bill(page, Path(td), iso, Path(td) / "out.pdf",
                                                       title=title, trace=[]))
        self.assertEqual(said, [("pressed", "September 2026", 1), ("pressed", "August 2026", 2)])


def pdf_saying(text: str) -> bytes:
    """A one page PDF whose text is `text`, written by hand so its words
    can be read back. Every word given here is made up."""
    stream = ("BT /F1 11 Tf 40 740 Td (%s) Tj ET" % text).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def built_app(case):
    """The app as its own main builds it, over a made-up config and output
    folder that go when `case` ends, with nothing that reaches a browser.
    Returns the run and the list its failure files would be written to."""
    td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    case.addCleanup(td.cleanup)
    root = Path(td.name)
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"owner": "Dana Example", "output_dir": str(root / "out"),
                               "profile_dir": str(root / "profile"), "min_pdf_bytes": 100,
                               "document_types": ["Statement", "Tax Document"]}), encoding="utf-8")
    with mock.patch.object(docs.App, "_setup_logging", lambda self: None):
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
    app._dl_dir = root / ".dl"
    app.check_session = lambda page: None
    failures = []
    app.write_failure = lambda *a, **kw: failures.append(a)
    app._journal = mock.MagicMock()
    return app, failures


SEPTEMBER = "Invented monthly statement for the period September 1, 2026 to September 30, 2026"
OCTOBER = "Invented monthly statement for the period October 1, 2026 to October 31, 2026"
NO_MONTH = "Invented monthly statement of account activity and balances for this holder"


class StatementMonth(unittest.TestCase):
    """A saved statement is filed under its month only when its own text
    names that month more plainly than the month before or after it."""

    def test_the_identity_is_the_month_and_its_neighbors(self):
        mine, rivals = site.statement_identity("Monthly Statement January 2026")
        self.assertEqual((mine.period, mine.start, mine.date), ("2026-01", "2026-01-01", "2026-01-31"))
        self.assertEqual([(r.period, r.start, r.date) for r in rivals],
                         [("2025-12", "2025-12-01", "2025-12-31"), ("2026-02", "2026-02-01", "2026-02-28")])
        self.assertIsNone(site.statement_identity("1099-DA Tax Year 2025"))
        self.assertIsNone(site.statement_identity(""))

    def test_each_text_gets_its_verdict(self):
        from paperpull_core import identity
        mine, rivals = site.statement_identity("Monthly Statement September 2026")
        for text, outcome in ((SEPTEMBER, identity.VERIFIED), (OCTOBER, identity.REFUSED),
                              (NO_MONTH, identity.UNCHECKED)):
            got = identity.distinguish(None, mine, rivals, text=text)
            self.assertEqual(got.outcome, outcome, text)

    def run_download_one(self, text: str):
        """The app's own download_one for the September statement, with the
        site handing over a PDF that says `text`. Returns the run, the
        document, where it was to be saved and the failures it wrote."""
        app, failures = built_app(self)
        doc = docs.Document(title="Monthly Statement September 2026", category="Statement",
                            summary="Monthly Statement", date="2026-09-30")
        saved_to = []

        def hands_over(page, dl_dir, iso, out_path, title="", trace=None, **kw):
            Path(out_path).write_bytes(pdf_saying(text))
            saved_to.append(Path(out_path))
            return True
        with mock.patch.object(site, "goto_documents", lambda page: True), \
                mock.patch.object(site, "download_bill", hands_over):
            app.download_one(object(), doc, "2026-09-30 Coinbase Monthly Statement.pdf")
        return app, doc, saved_to[0], failures

    def test_a_statement_naming_its_month_is_filed(self):
        app, doc, out, failures = self.run_download_one(SEPTEMBER)
        rec = app.progress.get(doc.key)
        self.assertEqual(rec["state"], docs.State.COMPLETED.value)
        self.assertTrue(rec["downloaded_ok"])
        self.assertTrue(out.exists())
        self.assertEqual(failures, [])

    def test_a_statement_naming_another_month_is_not_kept(self):
        app, doc, out, failures = self.run_download_one(OCTOBER)
        rec = app.progress.get(doc.key)
        self.assertEqual(rec["state"], docs.State.NEEDS_MANUAL_REVIEW.value)
        self.assertFalse(rec.get("downloaded_ok"))
        self.assertEqual(rec["pdf_path"], "")
        self.assertIn("names another month", rec["notes"])
        self.assertFalse(out.exists(), "another month's statement was left under this month's name")
        self.assertEqual(list(app.paths.manual_review.glob("*.pdf")), [])
        self.assertFalse(app._already_done(doc), "the next run does not ask for this month again")
        self.assertEqual(failures[0][0], "check the saved statement")

    def test_a_statement_whose_month_cannot_be_told_goes_to_review(self):
        app, doc, out, failures = self.run_download_one(NO_MONTH)
        rec = app.progress.get(doc.key)
        self.assertEqual(rec["state"], docs.State.NEEDS_MANUAL_REVIEW.value)
        self.assertFalse(out.exists(), "a statement not checked was filed")
        kept = Path(rec["pdf_path"])
        self.assertEqual(kept.parent, app.paths.manual_review)
        self.assertTrue(kept.exists())
        self.assertIn("could not be checked", rec["notes"])


class DiagnosePressesNothing(unittest.TestCase):
    """Diagnose says it downloads and presses nothing. It pressed Load more
    up to sixty times, once itself and once more through the listing."""

    def test_diagnose_leaves_load_more_alone(self):
        app, _failures = built_app(self)
        # Diagnose hands the owner's name to the word list, for this run only.
        self.addCleanup(site.set_private_words, [])
        rows = [row("Last 30 days", 0), row("September 2026", 1), row("August 2026", 2)]

        class LM:
            presses = 0
            def count(s): return 1
            def is_visible(s): return True
            def is_enabled(s, **kw): return True
            @property
            def first(s): return s
            def inner_text(s, **kw): return "Load more"
            def get_attribute(s, a): return None
            def click(s, **kw): LM.presses += 1

        class Loc:
            def __init__(s, n): s.n = n
            def count(s): return s.n
            @property
            def first(s): return s

        class Page:
            url = site.STATEMENTS_URL
            def title(self): return "Statements"
            def locator(self, sel):
                if sel == site._LOAD_MORE:
                    return LM()
                return Loc(0 if "password" in sel else 3)
            def evaluate(self, js, *a): return list(rows)
            def wait_for_timeout(self, ms): pass

        def answers(page, url):
            if url.startswith(site.TAX_OWNER_API):
                return {"first_transaction_date": "2026-08-03"}
            if url.startswith(site.TAX_FORMS_API):
                return {"data": [], "next_cursor": ""}
            return {"data": []}
        app.page = lambda: Page()
        with mock.patch.object(site, "goto_documents", lambda page: True), \
                mock.patch.object(site, "survey", lambda page: {}), \
                mock.patch.object(site, "_get_json", answers), \
                mock.patch.object(site.pressing, "click") as click, \
                mock.patch.object(site.pressing, "press_once") as press_once:
            app.cmd_diagnose()
        self.assertEqual((click.call_count, press_once.call_count, LM.presses), (0, 0, 0))
        info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
        self.assertNotIn("error", info)
        self.assertEqual(len(info["documents_recognized"]), 2, "the two month rows shown")


class Persisted(unittest.TestCase):
    def test_persistable_strips_query_and_fragment(self):
        self.assertEqual(docs.persistable("https://x.s3.amazonaws.com/a.pdf?X-Amz-Signature=abc&token=1#f"),
                         "https://x.s3.amazonaws.com/a.pdf")
        self.assertEqual(docs.persistable("/v2/tax/forms/abc?token=1"), "/v2/tax/forms/abc")
        self.assertEqual(docs.persistable(""), ""); self.assertEqual(docs.persistable(None), "")

    def test_every_stored_url_goes_through_persistable(self):
        src = (HERE / "coinbase_docs.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("persistable("), 1 + 5, "def + five call sites")
        for raw in ['href=r.href,', '"href": r.href}', 'source_url=source_url)', '{"source_url": source_url}', '"Source URL": doc.href,']:
            self.assertNotIn(raw, src, raw)

    def test_the_launchers_are_the_current_ones(self):
        """login.bat runs the app on gui/.venv when it has no venv of its
        own, as every app's does, and the Mac launchers are what the
        generator makes from the .bat files."""
        bat = (HERE / "login.bat").read_text(encoding="utf-8")
        self.assertIn(r'set "PY=..\..\gui\.venv\Scripts\python.exe"', bat)
        tool = HERE.parents[1] / "tools" / "make_unix_launchers.py"
        if not tool.exists():
            self.skipTest("a folder outside a checkout has no generator")
        import importlib.util
        import shutil
        spec = importlib.util.spec_from_file_location("make_unix_launchers", tool)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "coinbase"
            app.mkdir()
            for name in ("login.bat", "setup.bat"):
                shutil.copy2(HERE / name, app)
            made = {f.name: f.read_text(encoding="utf-8") for f in gen.build(app)}
        self.assertEqual(sorted(made), ["login.command", "setup.command"])
        for name, text in made.items():
            self.assertEqual(text, (HERE / name).read_text(encoding="utf-8"), name)

    def test_its_port_is_its_own_and_named_the_same_everywhere(self):
        """The example config, the sign-in fallback and login.bat name one
        port, and no other app's example config names it."""
        from urllib.parse import urlsplit
        port = urlsplit(json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
                        ["cdp_url"]).port
        self.assertEqual(port, 9286)
        src = (HERE / "coinbase_docs.py").read_text(encoding="utf-8")
        self.assertIn('self.config.get("cdp_url", ""), "%d")' % port, src)
        self.assertIn("port %d)" % port, (HERE / "login.bat").read_text(encoding="utf-8"))
        others = []
        for cfg in sorted(HERE.parent.glob("*/config.example.json")):
            if cfg.parent == HERE:
                continue
            url = json.loads(cfg.read_text(encoding="utf-8")).get("cdp_url") or ""
            if urlsplit(url).port == port:
                others.append(cfg.parent.name)
        self.assertEqual(others, [], "another app signs in on this port")

    def test_rules_classify_coinbase_titles(self):
        from paperpull_core import doc_types
        rules = doc_types.load_rules(HERE / "document_rules.json")
        for title, cat, summ in [("1099-DA Tax Year 2025", "Tax Document", "1099-DA Tax Form"),
                                 ("1099-MISC Tax Year 2024", "Tax Document", "1099-MISC Tax Form"),
                                 ("Gain Loss Report Tax Year 2021", "Tax Document", "Gain Loss Report"),
                                 ("1042-S Tax Year 2025", "Tax Document", "1042-S Tax Form"),
                                 ("Tax Form Tax Year 2025", "Tax Document", "Tax Document"),
                                 ("Monthly Statement September 2026", "Statement", "Monthly Statement")]:
            c, s, _ = doc_types.classify_document(title, rules)
            self.assertEqual((c, s), (cat, summ), title)


if __name__ == "__main__":
    unittest.main()
