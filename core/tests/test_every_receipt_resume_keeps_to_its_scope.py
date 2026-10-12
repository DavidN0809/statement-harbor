"""Every receipt app's Resume takes only the purchases inside the run's scope.

Pilot and Run All choose their purchases through the app's own selection,
which keeps to --year, --start-date, --end-date and the config's
default_start_date. The panel's Scope row reaches Resume too, so a Resume
with one year chosen is asked for that year. This drives each app's own
main with incomplete purchases inside and outside the scope and watches
which ones it hands over, one at a time, to be fetched.

What stands in is only what the provider would hand over. The page is a
made-up object and each purchase's own fetch (process_one) is watched
rather than run, so nothing here can reach a browser or a site. The
listing is one an earlier run read whole, so Resume does not read it
again.
"""
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import listing, models
from paperpull_core.models import Purchase, State
from paperpull_core.run_reporting import PREFIX

REPO = Path(__file__).resolve().parents[2]

RESUME = ("--resume", "--yes")
RUN_ALL = ("--all", "--yes")
YEARS = ("2024", "2025", "2026")
DATES = {"2024": "2024-06-10", "2025": "2025-03-04", "2026": "2026-02-11"}


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


def keeps_purchases(app: Path) -> bool:
    """An app whose discovery keeps the core's Purchase records and whose
    Resume carries on from them, found by what it is made of."""
    text = entry_of(app).read_text(encoding="utf-8-sig")
    return ("from paperpull_core.models import" in text and "Purchase" in text
            and "def cmd_resume(self" in text and "def cmd_discover(self" in text)


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and keeps_purchases(d))
IDS = [d.name for d in APPS]


def test_there_are_receipt_apps_to_check():
    assert len(APPS) >= 14, IDS


class NoBrowser:
    """sync_playwright() that refuses every attach and launch, and counts
    each one."""

    def __init__(self):
        self.asked = 0

        def refuse(*_a, **_kw):
            self.asked += 1
            raise Exception("connect ECONNREFUSED 127.0.0.1:9")
        self.chromium = SimpleNamespace(connect_over_cdp=refuse,
                                        launch_persistent_context=refuse, launch=refuse)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


class Home:
    """One app with a made-up config and output folder, run through its own
    main, and each purchase it handed over to be fetched."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch, capsys, floor=""):
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        example = app / "config.example.json"
        config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": floor,
        })
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.out = Path(config["output_dir"])
        self.browser = NoBrowser()
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", self.browser)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr("builtins.input", self._no_console)
        self.fetched = []
        self.listed = 0
        cls = self.mod.App
        page = SimpleNamespace(url="about:blank")
        monkeypatch.setattr(cls, "page", lambda app, *a, **kw: page)
        if hasattr(cls, "_catch_prints"):
            # Target listens on the browser for print dialogs.
            monkeypatch.setattr(cls, "_catch_prints", lambda app, *a, **kw: None)

        def fetch(app, _page, purchase, *a, **kw):
            self.fetched.append((purchase.key, kw.get("by_dates")))
        # Whether the app's own fetch places a purchase by its page's date.
        self.places = "by_dates" in inspect.signature(cls.process_one).parameters
        monkeypatch.setattr(cls, "process_one", fetch)

        def whole(app, *_a, **_kw):
            self.listed += 1
            listing.started(app)
            listing.read_whole(app)
            return {}
        monkeypatch.setattr(cls, "cmd_discover", whole)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def run(self, *args):
        self.capsys.readouterr()
        try:
            ended = ("returned", self.mod.main(["--config", str(self.cfg), *args]))
        except SystemExit as e:
            ended = ("exit", e.code)
        out = self.capsys.readouterr().out
        results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
                   if line.startswith(PREFIX)]
        return " ".join(out.split()), (results[-1] if results else None), ended

    def listed_before(self, done=()):
        """One purchase dated in each of YEARS, listed by an earlier run read
        whole, and the years in `done` downloaded."""
        kinds = getattr(self.mod, "PURCHASE_TYPES", models.PURCHASE_TYPES)
        found, progress = {}, {}
        self.keys = {}
        for n, year in enumerate(YEARS, 1):
            p = Purchase(purchase_type=kinds[0], purchase_date=DATES[year],
                         order_number="10000000%02d" % n, total="12.34")
            rec = dict(p.to_dict(), state=State.DISCOVERED.value)
            found[p.key] = rec
            self.keys[year] = p.key
            if year in done:
                progress[p.key] = dict(rec, state=State.COMPLETED.value, downloaded_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "discovery.json").write_text(json.dumps(found), encoding="utf-8")
        if progress:
            (self.out / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        (self.out / "last-listing.json").write_text(
            json.dumps({"complete": True, "at": "2026-01-20T10:00:00"}), encoding="utf-8")

    def years_fetched(self):
        by_key = {k: y for y, k in self.keys.items()}
        return sorted(by_key[k] for k, _ in self.fetched)


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def report(home, said):
    return "%s fetched %s\n%s" % (home.app.name, home.fetched, said[-1500:])


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_unscoped_resume_takes_every_incomplete_purchase(home):
    """The control. With no scope Resume carries on with every purchase not
    done, of any year, and leaves a done one alone."""
    home.listed_before(done=("2024",))
    said, _result, _ended = home.run(*RESUME)
    assert home.years_fetched() == ["2025", "2026"], report(home, said)
    assert home.listed == 0 and home.browser.asked == 0, report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_scoped_run_all_takes_only_its_year(home):
    """What a scope means to the same app's Run All, for comparison."""
    home.listed_before()
    said, _result, _ended = home.run(*RUN_ALL, "--year", "2025")
    assert home.years_fetched() == ["2025"], report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_with_a_year_takes_only_that_year(home):
    home.listed_before()
    said, _result, _ended = home.run(*RESUME, "--year", "2025")
    assert home.years_fetched() == ["2025"], report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_with_dates_takes_only_those_dates(home):
    home.listed_before()
    said, _result, _ended = home.run(*RESUME, "--start-date", "2025-01-01",
                                     "--end-date", "2025-12-31")
    assert home.years_fetched() == ["2025"], report(home, said)


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_resume_keeps_to_the_configured_start_date(app, tmp_path, monkeypatch, capsys):
    """default_start_date is the floor every Pilot and Run All keeps to, for
    an archive that already holds the years before it."""
    home = Home(app, tmp_path, monkeypatch, capsys, floor="2025-01-01")
    home.listed_before()
    said, _result, _ended = home.run(*RESUME)
    assert home.years_fetched() == ["2025", "2026"], report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_downloading_again_keeps_to_its_year(home):
    """--resume --redownload from a terminal, with a year. Everything is
    done, and only that year is fetched again, never the whole history."""
    home.listed_before(done=YEARS)
    said, _result, _ended = home.run(*RESUME, "--redownload", "--year", "2025")
    assert home.years_fetched() == ["2025"], report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_scoped_resume_places_each_purchase_by_its_dates(home):
    """An app whose fetch places a purchase by the date its own page shows
    is told the run is held to dates, as its Run All tells it."""
    home.listed_before()
    home.run(*RESUME, "--year", "2025")
    told = {by for _key, by in home.fetched}
    assert told == ({True} if home.places else {None}), (home.app.name, home.fetched)

@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_scoped_resume_takes_what_a_scoped_run_all_takes(home):
    """The same purchases as the app's own Run All for that year, a
    purchase whose card shows no date included or left out as Run All
    leaves it. Walmart's online orders show none until their page is open,
    and its Run All takes them to be placed there."""
    home.listed_before()
    kinds = getattr(home.mod, "PURCHASE_TYPES", models.PURCHASE_TYPES)
    undated = Purchase(purchase_type=kinds[0], purchase_date="",
                       order_number="1000000099", total="12.34")
    found = json.loads((home.out / "discovery.json").read_text(encoding="utf-8"))
    found[undated.key] = dict(undated.to_dict(), state=State.DISCOVERED.value)
    (home.out / "discovery.json").write_text(json.dumps(found), encoding="utf-8")
    home.run(*RUN_ALL, "--year", "2025")
    by_run_all = sorted(home.fetched)
    home.fetched.clear()
    said, _result, _ended = home.run(*RESUME, "--year", "2025")
    assert sorted(home.fetched) == by_run_all, report(home, said)
    assert home.keys["2025"] in {k for k, _ in by_run_all}


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_scoped_resume_says_only_its_scope_is_complete(home):
    """Everything of 2025 is done and 2026 is not. A Resume for 2025 has
    nothing to do and does not call every purchase complete."""
    home.listed_before(done=("2024", "2025"))
    said, result, _ended = home.run(*RESUME, "--year", "2025")
    assert home.fetched == [], report(home, said)
    assert "everything in scope is complete" in said, said[-1500:]
    assert "all discovered purchases are complete" not in said, said[-1500:]
    assert result and result.get("stopped") == 0, said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_with_an_order_number_takes_only_that_order(home):
    home.listed_before()
    said, _result, _ended = home.run(*RESUME, "--order-number", "1000000002")
    assert home.years_fetched() == ["2025"], report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_counts_its_limit_after_the_done_ones(home):
    """--max-purchases 1 with the newest purchase done takes the next one,
    not nothing."""
    home.listed_before(done=("2026",))
    said, _result, _ended = home.run(*RESUME, "--max-purchases", "1")
    assert home.years_fetched() == ["2025"], report(home, said)
