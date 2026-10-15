"""Local archive expectations. No institution requests, URLs or account numbers."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def periods(rule, today):
    start = date.fromisoformat(rule["start"])
    step = {"monthly": 1, "quarterly": 3, "annual": 12}[rule.get("cycle", "monthly")]
    day = int(rule.get("available_day", 10))
    grace = int(rule.get("grace_days", 7))
    lag = int(rule.get("publication_lag_months", 1))
    if not 1 <= day <= 31 or not 0 <= grace <= 90 or not 0 <= lag <= 12:
        raise ValueError("invalid publication date")
    month = start.year * 12 + start.month - 1
    end = today.year * 12 + today.month - 1
    if end - month > 120:
        raise ValueError("expectation history exceeds ten years")
    while month <= end:
        y, m = divmod(month, 12)
        due_y, due_m = divmod(month + lag, 12)
        due = date(due_y, due_m + 1, min(day, calendar.monthrange(due_y, due_m + 1)[1])) + timedelta(days=grace)
        if today >= due:
            yield f"{y:04d}-{m + 1:02d}"
        month += step


def missing(rule, root, today=None):
    today = today or datetime.now(ZoneInfo(rule.get("zone", "America/New_York"))).date()
    root = Path(root).resolve()
    try:
        raw = json.loads((root / "progress.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raw = {}
    found = set()
    for rec in raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []:
        if not isinstance(rec, dict) or not rec.get("downloaded_ok"):
            continue
        category = rec.get("category", "").lower()
        category = {"tax document": "tax"}.get(category, category)
        if category != rule.get("document_type", "statement").lower():
            continue
        # For multiple financial subaccounts under one login, require an exact
        # keyed hash match; never treat one account's statement as all accounts'.
        if rule.get("account_key"):
            field = rule.get("account_field", "account")
            actual = hashlib.sha256(str(rec.get(field, "")).encode()).hexdigest()
            if actual != rule["account_key"]:
                continue
        value = str(rec.get("period") or "")[:7]
        if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", value):
            value = str(rec.get("date") or "")[:7]
        if re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", value):
            path = Path(rec.get("pdf_path") or "")
            path = (path if path.is_absolute() else root / path).resolve()
            if root in path.parents and path.is_file():
                found.add(value)
    return sorted(set(periods(rule, today)) - found)
