"""The record of a receipt already saved, and a Download again that saves
no copy of its own.

A receipt app saves a purchase once for good. Its record in progress.json
then carries downloaded_ok and names the saved file, with the summary, the
confidence and the state it ended in, and Rename, Review Names, the Pilot
report, the panel's naming preview and its Status all read it. The panel's
Download again runs an app with --redownload, so the app takes such a
purchase again, from discovery.json, which holds no file. Every step of
the attempt wrote the whole purchase into the record. One that ended with
nothing saved, at a page that would not open, a page that was not the
purchase's, no receipt, a control it could not read, an error, or a copy
that failed its check and was put aside, left the record naming no file
or the copy put aside, with the attempt's summary and state, and after a
wrong page with another purchase's facts. Rename then named the saved file
for them, and Review Names no longer took the record for the saved copy's.

So holds() stands between each receipt app's _record_state and the record.
Until this run has saved a copy of its own for a purchase, a write to the
record of one saved before changes nothing in it but its notes, which say
what the attempt came to. Discovery's state is left as it was as well,
since Apple and Uber read it to tell which purchases are settled. A write
that saves a copy carries downloaded_ok True, and from then on the
attempt's writes take the record as they always did, since it now names
the attempt's own copy. downloaded_ok is never taken away here, so a
purchase saved once is still never fetched again by a plain run.
"""
from __future__ import annotations

# What an attempt that saved nothing adds to the saved copy's notes. A later
# attempt's takes its place, so the notes say only how the latest one ended.
NOTE = "Not downloaded again"

# The purchases this run has saved a copy of, kept on the app, since a run
# is one app object and a new run starts with none.
_SAVED_NOW = "_saved_copies_this_run"


def holds(app, key: str, rec: dict, also=()) -> bool:
    """True when `rec` is a write over the record of a purchase saved
    before, by an attempt that has saved no copy of its own in this run.
    The record then keeps everything it had, its notes say how the attempt
    ended, and the app writes nothing more, to progress or to discovery.

    `also` names keys of the attempt's own that are written all the same,
    Target's list of the invoices a walk put on disk, so that none of them
    is saved twice."""
    mine = getattr(app, _SAVED_NOW, None)
    if mine is None:
        mine = set()
        setattr(app, _SAVED_NOW, mine)
    if rec.get("downloaded_ok") is True:
        mine.add(key)
        return False
    if key in mine:
        return False
    old = app.progress.get(key) or {}
    if not old.get("downloaded_ok"):
        return False
    patch = {name: rec[name] for name in also if name in rec}
    patch["notes"] = noted(old.get("notes"), rec.get("state"), rec.get("notes"))
    app.progress.update(key, patch)
    return True


def noted(kept, state, said) -> str:
    """The saved copy's notes, with one entry for the latest attempt in
    place of any earlier one. The entries are joined the way an app joins
    a purchase's notes, so the attempt's own are joined by commas inside
    its entry, and an earlier entry is found by its first words."""
    parts = [p for p in str(kept or "").split("; ") if p and not p.startswith(NOTE)]
    what = [str(state or "")] + [p for p in str(said or "").split("; ") if p]
    parts.append("%s (%s)" % (NOTE, ", ".join(w for w in what if w)))
    return "; ".join(parts)
