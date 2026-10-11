"""Carry your download history to another computer, so nothing is fetched twice.

The PDFs are not the important part. What matters is the record of what has
already been downloaded, because that is what makes a re-run skip a statement
instead of pulling it again. Move that, and a fresh install on a new machine
picks up exactly where the old one left off, whether or not you copied a single
PDF across.

    python migrate.py --export history.ppz
    python migrate.py --import history.ppz --dry-run
    python migrate.py --import history.ppz

The control panel does the same with Export history and Import a history file
on its Status tab, on the desktop and on PaperPull Server alike, and its import also
sets up each provider and each person the file names that is not set up yet,
with their settings (#67). This command only fills in what is already set up.

WHAT COMES ACROSS

For each provider, and for each second person on it (a config.<name>.json),
the progress.json its runs keep, which is a dict of records keyed by a stable
document identity. Two fields in each record decide whether a document is
skipped on the next run, and BOTH are needed:

  * downloaded_ok, the permanent marker, set once a PDF has been written
  * state, because records made before that marker existed are skipped on a
    terminal state alone, and that is most of them

An import never deletes and never downgrades. A document marked done stays
done, and anything the target install already knew about it is kept.

Each person's settings come along too, the ones somebody chose rather than
the ones that name a computer. That is every key the provider's
config.example.json lists, the file name patterns, and nothing in
MACHINE_KEYS, the download folder, the browser profile, the browser and its
debugging port, which the new machine decides for itself. An import writes
settings only into a provider or person it sets up, never over one already
there.

PATHS ARE REWRITTEN

Records carry the absolute path the PDF was written to. On another machine
those point at a folder that does not exist, so the folder is rewritten to the
target's as the records are merged. Where a path cannot be rewritten, or would
lead out of that folder, it is cleared rather than left pointing somewhere
false, because one part of the skip logic asks whether a review copy is still
on disk and a stale path would answer that wrongly.

THE EXPORT FILE HOLDS PERSONAL DATA

It is a plain zip, so treat it like the archive it describes. Depending on
which apps you run it can contain account labels and the last four digits of
account numbers, document titles, order numbers and purchase totals, itemized
purchases, store locations and the account holders' names. It holds no
passwords, no cookies and no session tokens.

--minimal writes only the fields a skip decision reads, and no settings. On a
real archive that took the file from 330 KB to 64 KB and removed every item
name, order number and purchase total. Be clear about what it does NOT remove:
the recorded PDF path stays, and filenames embed account labels, so a line
like "Statements\\2026-08-18 Statement - FREEDOM (...0962).pdf" survives. It
is a much smaller and much less revealing file, not an anonymous one. The
cost is that the new machine starts with no history to report on until it
runs.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import posixpath
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# The core beside this tool comes first, so an older copy installed in the
# interpreter's own environment never stands in for it.
_CORE = Path(__file__).resolve().parents[1] / "core"
if (_CORE / "paperpull_core").is_dir():
    sys.path.insert(0, str(_CORE))
from paperpull_core.not_shown import DAYS_KEY, asked_again, set_aside  # noqa: E402

# The file this writes. Version 1 had one entry per folder and no people or
# settings, and still imports.
SCHEMA = 2
READS = (1, 2)

# The fields a skip decision actually reads. Everything else is history.
# The days a receipt page showed nothing are read too, since a receipt they
# set aside is final in Meijer only while its record holds them, and every
# receipt app's skip line says why from them (paperpull_core.not_shown).
SKIP_FIELDS = ("state", "downloaded_ok", "pdf_path", "discovered_at", "updated_at",
               DAYS_KEY)

# Read out of an install's own storage.py, the same way the status report does,
# so an install is identified by what it IS rather than what its folder is
# called. Folders get renamed; a provider does not.
# Either quote, and a double-quoted name may hold an apostrophe ("Lowe's").
PROVIDER_RE = re.compile(r"""provider\s*=\s*["']((?<=")[^"]+(?=")|(?<=')[^']+(?='))""")
KIND_RE = re.compile(r"kind\s*=\s*(DOCUMENT|RECEIPT)")
# An app's own script, as the control panel finds it, never a hidden file.
ENTRY_RE = re.compile(r"[^.].*_(receipts|docs)\.py$")

# A terminal state means done even without the downloaded_ok marker. Kept in
# step with the apps' own should_skip.
TERMINAL = {"Completed", "PDF Verified", "No Receipt Available", "Canceled"}

# Settings that name this computer. Another machine has its own folders, its
# own profiles and its own browser, so these never travel, and an import
# never writes them, whatever a file says.
MACHINE_KEYS = ("output_dir", "profile_dir", "cdp_url", "browser")
# The control panel's File names tab writes these, and no config.example.json
# lists them.
NAMING_KEYS = ("filename_pattern", "filename_pattern_receipts",
               "filename_pattern_statements")
# What load_config gives every app, so an install made before its
# config.example.json existed still carries them.
CORE_SETTINGS = ("owner", "owner_in_filename", "default_start_date", "min_pdf_bytes",
                 "max_path_length", "delay_min_seconds", "delay_max_seconds")
# The longest a setting may be once written as JSON. The longest real one is a
# list of account labels.
MAX_SETTING_CHARS = 4000

# How much of a file handed over is read. A real archive of thirty providers
# exported to 330 KB, so these stop only a file that is not one, including a
# zip that says it is small and unpacks to far more.
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RECORDS_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 2000


class NotAnExport(Exception):
    """A file this cannot import, with a sentence saying why."""


def _say(line=""):
    """Console-safe. Account labels are scraped from bank pages and can hold
    characters the Windows console codepage cannot encode, which would
    otherwise end the run with a UnicodeEncodeError instead of a report."""
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(
            encoding="utf-8").strip()
    except OSError:
        return ""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _entry_script(folder: Path):
    try:
        for p in sorted(folder.glob("*.py")):
            if ENTRY_RE.match(p.name):
                return p
    except OSError:
        pass
    return None


def _provider_kind(folder: Path):
    """(provider, kind) from the folder's storage.py, the folder's name and
    None when it has none."""
    src = ""
    try:
        src = (folder / "storage.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    p = PROVIDER_RE.search(src)
    k = KIND_RE.search(src)
    return (p.group(1) if p else folder.name), (k.group(1) if k else None)


def identify(install: Path):
    """(provider, kind) for an install folder, or (None, None) if it is not one."""
    if not (install / "progress.json").is_file():
        return None, None
    return _provider_kind(install)


def _records(path: Path):
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


# -- where each person's history is kept ---------------------------------------

def account_configs(install: Path) -> list:
    """(label, config file) for every person on an install, the first one,
    "primary", first."""
    out = [("primary", install / "config.json")]
    for p in sorted(install.glob("config.*.json")):
        if p.name != "config.example.json":
            out.append((p.name[len("config."):-len(".json")], p))
    return out


def output_dir_of(install: Path, cfg: dict, provider: str) -> Path:
    """Where a person's runs keep their records. A relative folder is the
    install's, since a run starts there, and none at all is load_config's
    default."""
    raw = str(cfg.get("output_dir") or "") or str(Path.home() / "Downloads" / provider)
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = install / p
    return Path(os.path.normpath(str(p)))


def settings_allowed(install: Path) -> set:
    """The settings that travel for an install. Every key its own
    config.example.json lists, the core's and the file name patterns, and
    never one that names this computer or a comment."""
    example = _read_json(install / "config.example.json")
    keys = set(example) if isinstance(example, dict) else set()
    keys |= set(CORE_SETTINGS) | set(NAMING_KEYS)
    return {k for k in keys if not k.startswith("//") and k not in MACHINE_KEYS}


def _fits(value) -> bool:
    try:
        return len(json.dumps(value)) <= MAX_SETTING_CHARS
    except (TypeError, ValueError):
        return False


def settings_of(install: Path, cfg: dict) -> dict:
    """The settings a person chose, as an export carries them."""
    allowed = settings_allowed(install)
    return {k: cfg[k] for k in sorted(allowed) if k in cfg and _fits(cfg[k])}


def _same_kind(ref, value) -> bool:
    """Whether a value is the kind of thing the install's own setting is, so
    a file cannot turn a number into a list or a switch into a word."""
    if isinstance(ref, bool) or isinstance(value, bool):
        return isinstance(ref, bool) and isinstance(value, bool)
    if isinstance(ref, (int, float)):
        return isinstance(value, (int, float))
    for kind in (str, list, dict):
        if isinstance(ref, kind):
            return isinstance(value, kind)
    return value is None or isinstance(value, (str, int, float))


def settings_to_apply(install: Path, cfg: dict, settings: dict, check_pattern=None) -> dict:
    """What of a file's settings may be written into a config this import
    just made. Only the keys settings_allowed gives this install, each the
    same kind as the install's own value, and a file name pattern only when
    check_pattern finds nothing wrong with it. With no way to check a
    pattern, none is taken."""
    if not isinstance(settings, dict):
        return {}
    allowed = settings_allowed(install)
    example = _read_json(install / "config.example.json")
    example = example if isinstance(example, dict) else {}
    out = {}
    for key, value in settings.items():
        if key not in allowed or not _fits(value):
            continue
        ref = example.get(key, cfg.get(key))
        if ref is not None and not _same_kind(ref, value):
            continue
        if key in NAMING_KEYS:
            if not isinstance(value, str):
                continue
            if value and (check_pattern is None or check_pattern(value)):
                continue
        if key == "owner":
            value = str(value or "").strip()[:80]
        out[key] = value
    return out


def scan(root: Path) -> list:
    """Every place under root that keeps a history, one for each person on
    each install, then any folder with a history and no app of its own.

    A second person's folder sits beside the install, holding records and
    no app, so it is found through the person's config and not again as a
    folder of its own."""
    found, claimed = [], set()
    try:
        children = [c for c in sorted(root.iterdir())
                    if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        return found
    for install in children:
        script = _entry_script(install)
        if script is None:
            continue
        provider, kind = _provider_kind(install)
        for label, cfg_path in account_configs(install):
            if cfg_path.is_file():
                cfg = _read_json(cfg_path)
                if not isinstance(cfg, dict):
                    _say("  skipping %s, its %s could not be read" % (install.name, cfg_path.name))
                    continue
                where = output_dir_of(install, cfg, provider)
            else:
                # Not set up yet, or set up before configs, when the
                # records sat beside the app.
                cfg, where = {}, install
            key = os.path.normcase(str(where))
            if key in claimed:
                continue
            claimed.add(key)
            recs = {}
            if (where / "progress.json").is_file():
                recs = _records(where / "progress.json")
                if recs is None:
                    _say("  skipping %s, its progress.json could not be read" % where.name)
                    continue
            found.append({"folder": where.name, "install": install.name, "account": label,
                          "provider": provider, "kind": kind, "path": where,
                          "records": recs, "settings": settings_of(install, cfg),
                          "config": cfg_path if cfg_path.is_file() else None})
    for child in children:
        if os.path.normcase(str(child)) in claimed or _entry_script(child) is not None:
            continue
        provider, kind = identify(child)
        if provider is None:
            continue
        recs = _records(child / "progress.json")
        if recs is None:
            _say("  skipping %s, its progress.json could not be read" % child.name)
            continue
        found.append({"folder": child.name, "install": child.name, "account": "primary",
                      "provider": provider, "kind": kind, "path": child,
                      "records": recs, "settings": {}, "config": None})
    return found


def _done(rec: dict) -> bool:
    """Skipped by the app, as its own _already_done decides. A record an
    older version finished when the receipt page did not show the receipt
    is asked for again, so it is not done (paperpull_core.not_shown)."""
    return bool(rec.get("downloaded_ok")
                or (rec.get("state") in TERMINAL and not asked_again(rec)))


def _skip_fields(rec: dict) -> dict:
    """The fields a skip decision reads. For a record asked for again that
    is its last note too, one of the fixed words an older version wrote,
    which says nothing of the purchase."""
    out = {f: rec[f] for f in SKIP_FIELDS if f in rec}
    if asked_again(rec):
        out["notes"] = str(rec.get("notes") or "").rsplit("; ", 1)[-1].strip()
    return out


def describe(entry: dict) -> str:
    """A provider, and the person when it is not the first one."""
    acct = entry.get("account") or "primary"
    return entry["provider"] if acct == "primary" else "%s (%s)" % (entry["provider"], acct)


# -- export ------------------------------------------------------------------

def build(root: Path, minimal: bool = False):
    """(the export file's bytes, its manifest), or (None, None) when nothing
    under root keeps a history. Written in memory, so the control panel can
    hand it to a browser without leaving a copy anywhere."""
    places = scan(root)
    if not places:
        return None, None
    manifest = {"schema": SCHEMA, "created": datetime.now().isoformat(timespec="seconds"),
                "version": _version(), "source_root": str(root), "minimal": bool(minimal),
                "apps": []}
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for place in places:
            recs = place["records"]
            if minimal:
                recs = {k: _skip_fields(v) for k, v in recs.items()}
            name, n = place["folder"], 2
            while name.lower() in used:
                name, n = "%s (%d)" % (place["folder"], n), n + 1
            used.add(name.lower())
            member = "apps/%s/progress.json" % name
            entry = {"folder": place["folder"], "install": place["install"],
                     "account": place["account"], "provider": place["provider"],
                     "kind": place["kind"], "source_dir": str(place["path"]),
                     "records": len(recs),
                     "already_downloaded": sum(1 for r in place["records"].values() if _done(r)),
                     "file": member}
            if not minimal:
                entry["settings"] = place["settings"]
            manifest["apps"].append(entry)
            z.writestr(member, json.dumps(recs, indent=2, ensure_ascii=False))
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("README.txt", _READ_ME)
    return buf.getvalue(), manifest


def export(root: Path, out: Path, minimal: bool = False) -> int:
    data, manifest = build(root, minimal)
    if data is None:
        _say("No installs with a download history were found under %s" % root)
        return 1
    out.write_bytes(data)

    total = sum(a["records"] for a in manifest["apps"])
    _say("Exported %d records from %d places" % (total, len(manifest["apps"])))
    _say("  to %s" % out)
    for a in manifest["apps"]:
        _say("    %-32s %5d records, %d already downloaded"
             % (describe(a)[:32], a["records"], a["already_downloaded"]))
    _say()
    _say("This file describes your archive, so keep it as private as the archive.")
    _say("It holds no passwords, cookies or session tokens.")
    if minimal:
        _say("Written with --minimal, so item names, order numbers, totals and")
        _say("settings are left out. Recorded filenames remain, and those name accounts.")
    else:
        _say("It can contain account labels, document titles, order numbers,")
        _say("purchase totals, itemized purchases and account holders' names.")
        _say("Use --minimal to leave most of that out.")
    return 0


_READ_ME = """PaperPull download history.

Made by PaperPull's Export history, or by tools/migrate.py. Bring it to
another computer, or to PaperPull Server, with Import a history file on the
control panel's Status tab, or with:

    python migrate.py --import <this file>

It carries the record of which documents have already been downloaded, so a
fresh install skips them instead of fetching them again, and each provider's
and person's settings. It does NOT contain any PDF, and it does NOT contain
any password, cookie or session token.

Depending on which apps you run it may contain account labels, document
titles, order numbers, purchase totals, store locations and the account
holders' names. Keep it as private as the archive it describes.
"""


# -- reading a file ----------------------------------------------------------

def _member(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """One file inside the zip, read no further than limit, whatever size
    the zip says it is."""
    try:
        with z.open(name) as f:
            data = f.read(limit + 1)
    except KeyError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, EOFError) as e:
        raise NotAnExport("Part of that file could not be read (%s)." % str(e)[:80])
    if len(data) > limit:
        raise NotAnExport("That file is far larger than any download history, "
                          "so it was not read.")
    return data


def _entry(raw: dict, schema: int):
    """One provider or person from a manifest, in the shape this version
    reads, or None when it names nothing."""
    folder = str(raw.get("folder") or "")
    provider = str(raw.get("provider") or folder)
    if not provider:
        return None
    account = str(raw.get("account") or "primary").strip().lower() if schema >= 2 else "primary"
    member = str(raw.get("file") or "") if schema >= 2 else ""
    settings = raw.get("settings") if schema >= 2 else None
    return {"folder": folder, "provider": provider,
            "kind": raw.get("kind") if raw.get("kind") in ("DOCUMENT", "RECEIPT") else None,
            "account": account or "primary",
            "source_dir": str(raw.get("source_dir") or "") if schema >= 2 else "",
            "settings": settings if isinstance(settings, dict) else {},
            "file": member or "apps/%s/progress.json" % folder,
            "incoming": None}


def read(source) -> dict:
    """An export's manifest, every entry with the records it carries under
    "incoming" (None when the file lacks them), from a path or the file's
    bytes. Raises NotAnExport with a sentence for a file it will not read."""
    try:
        z = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray))
                            else source)
    except (OSError, zipfile.BadZipFile, ValueError):
        raise NotAnExport("That is not a readable export file.")
    with z:
        try:
            manifest = json.loads(_member(z, "manifest.json", MAX_MANIFEST_BYTES).decode("utf-8"))
        except (KeyError, ValueError):
            raise NotAnExport("That file has no manifest, so it was not made by PaperPull.")
        if not isinstance(manifest, dict):
            raise NotAnExport("That file has no manifest, so it was not made by PaperPull.")
        schema = manifest.get("schema")
        if schema not in READS:
            raise NotAnExport("That export was written by a different version of PaperPull "
                              "(schema %s, this one reads %s)."
                              % (schema, " and ".join(str(s) for s in READS)))
        apps = manifest.get("apps")
        if not isinstance(apps, list) or len(apps) > MAX_ENTRIES:
            raise NotAnExport("That file's manifest lists no providers.")
        entries, total = [], 0
        for raw in apps:
            entry = _entry(raw, schema) if isinstance(raw, dict) else None
            if entry is None:
                continue
            entries.append(entry)
            try:
                data = _member(z, entry["file"], MAX_RECORDS_BYTES)
            except KeyError:
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise NotAnExport("That file is far larger than any download history, "
                                  "so it was not read.")
            try:
                recs = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(recs, dict):
                entry["incoming"] = {str(k): v for k, v in recs.items() if isinstance(v, dict)}
    out = {k: v for k, v in manifest.items() if k != "apps"}
    out["schema"] = schema
    out["apps"] = entries
    return out


def match(entry: dict, places: list):
    """The place here that keeps this entry's history. The same provider and
    person, then, for a file from before people were told apart, a folder
    of the same name, which is how a second person's folder came across."""
    provider = entry["provider"].lower()
    for place in places:
        if place["provider"].lower() == provider and place["account"] == entry["account"]:
            return place
    folder = (entry.get("folder") or "").lower()
    if folder:
        for place in places:
            if place["folder"].lower() == folder:
                return place
    return None


def bases_of(entry: dict, manifest: dict) -> list:
    """The folders an entry's paths were written under on the other machine."""
    out = []
    if entry.get("source_dir"):
        out.append(entry["source_dir"])
    root = str(manifest.get("source_root") or "")
    if root and entry.get("folder"):
        out.append(root.rstrip("\\/") + "/" + entry["folder"])
    return out


# -- import ------------------------------------------------------------------

def _is_absolute(path: str) -> bool:
    """True for a path that names a particular machine, on either platform.

    Path.is_absolute answers for the platform this code is running on, and an
    export written on Windows can be imported on a Mac, where a drive-letter
    path would otherwise look relative and be kept as-is.
    """
    p = (path or "").replace("\\", "/")
    return p.startswith("/") or (len(p) > 2 and p[1] == ":" and p[2] == "/")


def _stays_inside(rel: str) -> bool:
    """Whether a path relative to a folder stays inside it."""
    p = rel.replace("\\", "/")
    if not p or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return False
    norm = posixpath.normpath(p)
    return norm not in (".", "..") and not norm.startswith("../")


def _rewrite_path(old: str, old_bases, new_base: Path) -> str:
    """Point a recorded PDF path at this machine, or clear it.

    A path that cannot be rewritten is CLEARED rather than left alone. The
    skip logic asks whether a manual-review copy is still on disk, and a path
    from another computer would answer that question wrongly. So is one that
    would lead out of the folder, which no app ever writes.
    """
    if not old:
        return ""
    # The apps do not agree on this. Some record a path relative to their own
    # folder, others the full absolute one. A relative path is already portable
    # and is left exactly as it is. Only an absolute path names a machine.
    if not _is_absolute(old):
        return old if _stays_inside(old) else ""
    norm = old.replace("\\", "/")
    for base in old_bases or ():
        b = str(base or "").replace("\\", "/").rstrip("/")
        # The folder itself and then a separator, so "Bank Statements" is
        # never taken for the start of "Bank Statements - spouse".
        if b and norm.lower().startswith(b.lower() + "/"):
            tail = norm[len(b) + 1:]
            if _stays_inside(tail):
                return str(new_base / Path(posixpath.normpath(tail)))
            return ""
    return ""


def _under(path: str, old_bases) -> bool:
    norm = path.replace("\\", "/").lower()
    return any(b and norm.startswith(b + "/")
               for b in (str(x or "").replace("\\", "/").rstrip("/").lower()
                         for x in old_bases or ()))


def _moved(rec: dict, old_bases, new_base: Path) -> dict:
    """A record from another machine with its paths pointed at this one.

    Target keeps one file for each invoice of an order as well. An invoice
    whose path names some other folder of that machine keeps it, since a
    saved invoice counts as saved whether or not its file is there, and an
    entry with no file is not counted at all. One that would lead out of
    its folder is cleared, as a PDF path is."""
    rec = dict(rec)
    rec["pdf_path"] = _rewrite_path(str(rec.get("pdf_path") or ""), old_bases, new_base)
    invoices = rec.get("invoices")
    if isinstance(invoices, list):
        out = []
        for inv in invoices:
            if isinstance(inv, dict) and isinstance(inv.get("file"), str) and inv["file"]:
                old = inv["file"]
                moved = _rewrite_path(old, old_bases, new_base)
                if not moved and _is_absolute(old) and not _under(old, old_bases):
                    moved = old
                inv = dict(inv, file=moved)
            out.append(inv)
        rec["invoices"] = out
    return rec


def _merge(target: dict, incoming: dict, old_bases, new_base: Path):
    """Fold incoming records into target. Never deletes, never downgrades.

    The caller must hand over a DEEP copy. dict(records) copies only the outer
    mapping, so the record objects stay shared, and this function edits them in
    place. The plan pass then silently applied itself, and the apply pass that
    followed found nothing left to do and reported zero changes against a plan
    that had promised several.
    """
    added = updated = 0
    for key, inc in incoming.items():
        cur = target.get(key)
        if cur is None:
            rec = _moved(inc, old_bases, new_base)
            rec["imported_at"] = datetime.now().isoformat(timespec="seconds")
            target[key] = rec
            added += 1
            continue
        # Present on both sides. The target wins on content, because it
        # describes THIS machine, but a document already downloaded anywhere
        # stays downloaded.
        changed = False
        if inc.get("downloaded_ok") and not cur.get("downloaded_ok"):
            cur["downloaded_ok"] = True
            changed = True
        if _takes_the_state(cur, inc):
            cur["state"] = inc["state"]
            # The state comes with what it was written with. A receipt set
            # aside is final in Meijer only with its days, and a note an
            # older version wrote here would have it asked for again.
            if DAYS_KEY in inc:
                cur[DAYS_KEY] = list(inc[DAYS_KEY] or [])
            if asked_again(cur):
                cur["notes"] = _last_note_replaced(cur, inc)
            changed = True
        if changed:
            cur["imported_at"] = datetime.now().isoformat(timespec="seconds")
            updated += 1
    return added, updated


def merged(place: dict, entry: dict, manifest: dict):
    """(the place's records with the entry's folded in, how many were added,
    how many were marked done). The place's own records are not touched, so
    a plan and the import that follows count the same."""
    out = copy.deepcopy(place["records"])
    added, updated = _merge(out, entry["incoming"] or {}, bases_of(entry, manifest),
                            Path(place["path"]))
    return out, added, updated


def write_history(where: Path, records: dict, stamp: str) -> None:
    """A place's progress.json, written in one step, with the one it
    replaces kept in its Backups first. Raises OSError."""
    path = Path(where) / "progress.json"
    Path(where).mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backups = Path(where) / "Backups"
        backups.mkdir(parents=True, exist_ok=True)
        (backups / ("progress.%s.before-import.bak" % stamp)).write_bytes(path.read_bytes())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _takes_the_state(cur: dict, inc: dict) -> bool:
    """Whether a record the target already had takes the incoming state.
    Only one this install has not finished, and only for a state that
    finishes it. A record an older version gave up on here is asked for
    again, and takes a state only from a record that settled it, a save or
    a receipt set aside. An export from before 0.45.0 carried no notes, so
    its record of the same gave-up purchase looks finished without them."""
    if not _done(dict(inc, downloaded_ok=False)):
        return False
    if cur.get("state") not in TERMINAL:
        return True
    return (asked_again(cur)
            and (inc.get("state") != "No Receipt Available" or set_aside(inc)))


def _last_note_replaced(cur: dict, inc: dict) -> str:
    """The target's notes, its last one, written with the state it gives up,
    swapped for the incoming last note. The notes before it stay."""
    kept = str(cur.get("notes") or "").rsplit("; ", 1)
    kept = kept[0] if len(kept) > 1 else ""
    last = str(inc.get("notes") or "").rsplit("; ", 1)[-1].strip()
    return "; ".join(n for n in (kept, last) if n)


def do_import(archive: Path, root: Path, dry_run: bool = False,
              assume_yes: bool = False) -> int:
    try:
        manifest = read(archive)
    except NotAnExport as e:
        _say("%s %s" % (archive, e))
        return 1

    places = scan(root)
    plan, missing = [], []
    for entry in manifest["apps"]:
        place = match(entry, places) if entry["incoming"] is not None else None
        (plan if place is not None else missing).append((entry, place))

    _say("Import plan, from %s" % archive)
    _say("  into %s" % root)
    _say()
    for entry, place in plan:
        _, added, updated = merged(place, entry, manifest)
        _say("  %-30s %4d new, %4d marked done, %d already known"
             % (describe(place)[:30], added, updated, len(place["records"])))
    for entry, _ in missing:
        why = ("ITS HISTORY IS MISSING FROM THE FILE" if entry["incoming"] is None
               else "NOT SET UP HERE")
        _say("  %-30s %s, skipped" % (describe(entry)[:30], why))
    if missing and any(e["incoming"] is not None for e, _ in missing):
        _say("  Import a history file on the control panel's Status tab sets those up.")
    if not plan:
        _say()
        _say("Nothing to import. None of those providers are installed under %s" % root)
        return 1
    _say()

    if dry_run:
        _say("Dry run, nothing was written.")
        return 0
    if not assume_yes:
        try:
            answer = input("Apply this? Existing files are backed up first [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            _say("Nothing was written.")
            return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for entry, place in plan:
        records, added, updated = merged(place, entry, manifest)
        try:
            write_history(place["path"], records, stamp)
        except OSError as e:
            _say("  could not write %s (%s), skipping it" % (describe(place), e))
            continue
        place["records"] = records
        _say("  %-30s %4d new, %4d marked done" % (describe(place)[:30], added, updated))

    _say()
    _say("Done. Run each app as usual, it will skip what you already have.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Move your PaperPull download history between computers.")
    ap.add_argument("--export", metavar="FILE", help="write a history file")
    ap.add_argument("--import", dest="imp", metavar="FILE", help="read a history file")
    ap.add_argument("--root", metavar="DIR", default=None,
                    help="the folder holding your installs (default: this file's parent)")
    ap.add_argument("--minimal", action="store_true",
                    help="export only what a skip decision needs, far less personal data")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask before writing")
    args = ap.parse_args(argv)

    if bool(args.export) == bool(args.imp):
        ap.error("choose one of --export or --import")

    root = Path(args.root).expanduser() if args.root else Path(__file__).resolve().parent
    if not root.is_dir():
        _say("%s is not a folder." % root)
        return 1

    if args.export:
        return export(root, Path(args.export).expanduser(), minimal=args.minimal)
    return do_import(Path(args.imp).expanduser(), root,
                     dry_run=args.dry_run, assume_yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
