"""Anthem's member documents, ID cards and letters stay inside the run's
scope, as its EOBs do.

Anthem takes these from lists of their own, after its EOBs, and saves them
in one loop (App._save_collected). The EOBs pass through _in_scope, which
reads --year, --start-date, --end-date and the config's default_start_date.
That loop read none of them. So a plain run with a year or dates took every
member document, ID card and letter of every year, and a Download again,
which the panel offers only with a year or both dates so that a whole
history is never asked for again by accident, skipped its already saved
check and took every one of them again, saving a second copy beside each.

Here the app is built by its own parser and __init__ with a made-up config,
the lists are read by Anthem's own code from answers in the shapes its site
hands over, and only those answers and each document's PDF are stood in.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import testkit  # noqa: E402

site = app_mod.site


def period(year: int) -> str:
    """A coverage period of one calendar year, in the shape Anthem keys it."""
    return "79DM-%d0101-%d1231-MED-000000A00A" % (year, year)


def epoch_ms(day: str) -> int:
    when = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(when.timestamp() * 1000)


# Made up. One member document a coverage year, two members' cards that took
# effect in different years, and a letter a year.
CARD_DAYS = {"JANE": "2024-03-01", "JOHN": "2026-01-01"}
LETTER_DAYS = {"u-2024": "2024-06-01", "u-2025": "2025-06-01", "u-2026": "2026-02-01"}

LISTS = {
    "member documents": {"status": 200, "rows": [
        {"coverageKey": period(y), "documentType": "SBC"} for y in (2024, 2025, 2026)]},
    "ID card": {"status": 200, "body": {"result": {"data": {"patient": [
        {"name": {"given": [given], "family": "DOE"},
         "healthIdentificationCard": [{"cardType": "normal", "effectiveDate": day}]}
        for given, day in CARD_DAYS.items()]}}}},
    "message": {"status": 200, "messages": [
        {"msgUid": uid, "subject": "Your claim was processed", "body": "<p>%s</p>" % uid,
         "createDtTime": epoch_ms(day), "isRead": True} for uid, day in LETTER_DAYS.items()]},
}

# Every document the lists hold, by the date Anthem's code files it under.
DATED = {
    **{site.member_doc_id(period(y), "SBC"): "%d-01-01" % y for y in (2024, 2025, 2026)},
    **{"IdCard|%s Doe|normal|0" % given.title(): day for given, day in CARD_DAYS.items()},
    **{"Letter|" + uid: day for uid, day in LETTER_DAYS.items()},
}


@pytest.fixture
def build(tmp_path, monkeypatch):
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    fetched = []

    def pdf_of(doc_id: str) -> bytes:
        fetched.append(doc_id)
        return testkit.text_pdf(["the document " + doc_id])

    monkeypatch.setattr(site, "_prime_and_fetch",
                        lambda _page, _target, _bucket, _js, what, **_kw: LISTS[what])
    monkeypatch.setattr(site, "download_member_document",
                        lambda _pg, key, dtype: pdf_of(site.member_doc_id(key, dtype)))
    monkeypatch.setattr(site, "download_id_card",
                        lambda _pg, patient, kind, ordinal=0: pdf_of(
                            "IdCard|%s|%s|%d" % (patient, kind, ordinal)))
    monkeypatch.setattr(site, "render_letter",
                        lambda _pg, _label, body, _date="": pdf_of(
                            "Letter|" + body[len("<p>"):-len("</p>")]))

    def made(*flags, floor: str = ""):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(config, default_start_date=floor)), encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), *flags])
        app = app_mod.App(args)
        page = SimpleNamespace(url="https://membersecure.anthem.com/member/documents")
        app._on_its_site = lambda: page
        app.check_session = lambda *_a, **_kw: None
        del fetched[:]
        return app, fetched
    return made


def take(app) -> None:
    """The three lists, as Run All and Resume take them after the EOBs."""
    app.cmd_documents()
    app.cmd_id_cards()
    app.cmd_letters()
    app.progress.save()


def pdfs(app) -> list:
    return sorted(p.name for p in Path(app.paths.root).rglob("*.pdf"))


def inside(year: str = "", start: str = "", end: str = "") -> set:
    return {doc_id for doc_id, day in DATED.items()
            if (not year or day.startswith(year))
            and (not start or day >= start) and (not end or day <= end)}


SCOPES = [
    (("--year", "2025"), "", inside(year="2025")),
    (("--start-date", "2025-01-01", "--end-date", "2025-12-31"), "",
     inside(start="2025-01-01", end="2025-12-31")),
    (("--start-date", "2026-01-01"), "", inside(start="2026-01-01")),
    (("--end-date", "2024-12-31"), "", inside(end="2024-12-31")),
    ((), "2025-01-01", inside(start="2025-01-01")),
]
IDS = ["year", "both dates", "from date", "to date", "config start date"]


def test_the_lists_hold_documents_on_both_sides_of_every_scope():
    for _flags, _floor, wanted in SCOPES:
        assert wanted and wanted != set(DATED)


@pytest.mark.parametrize("flags,floor,wanted", SCOPES, ids=IDS)
def test_a_scoped_run_takes_only_what_falls_in_its_dates(build, flags, floor, wanted):
    app, fetched = build("--all", "--yes", *flags, floor=floor)
    take(app)
    assert set(fetched) == wanted
    assert len(pdfs(app)) == len(wanted)
    assert app.stats["skipped_out_of_scope"] == len(DATED) - len(wanted)


@pytest.mark.parametrize("flags", [("--year", "2025"),
                                   ("--start-date", "2025-01-01", "--end-date", "2025-12-31")],
                         ids=["year", "both dates"])
def test_a_download_again_takes_again_only_what_falls_in_its_dates(build, flags):
    app, fetched = build("--all", "--yes")
    take(app)
    assert set(fetched) == set(DATED)
    saved = pdfs(app)
    assert len(saved) == len(DATED)

    app, fetched = build("--all", "--yes", "--redownload", *flags)
    take(app)
    wanted = inside(year="2025")
    assert set(fetched) == wanted, "a Download again of 2025 took %s" % sorted(set(fetched) - wanted)
    # Each document taken again adds its one second copy, and only those.
    assert len(pdfs(app)) == len(saved) + len(wanted)


def test_an_unscoped_run_still_takes_every_document(build):
    app, fetched = build("--all", "--yes")
    take(app)
    assert set(fetched) == set(DATED)
    assert app.stats["skipped_out_of_scope"] == 0


def test_run_all_takes_the_lists_inside_its_year(build, monkeypatch):
    """Run All itself, from its EOB list (stood in as empty) through the
    three lists after it."""
    app, fetched = build("--all", "--yes", "--redownload", "--year", "2025")
    page = SimpleNamespace(url="https://membersecure.anthem.com/member/documents")
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(site, "ensure_statements", lambda _pg: True)
    monkeypatch.setattr(site, "collect_documents", lambda _pg: [])
    app.cmd_run("all")
    assert set(fetched) == inside(year="2025")
