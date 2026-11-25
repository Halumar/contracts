#!/usr/bin/env python3
"""Access hours and access switch: executable reference.

  python tools/access_ref.py fixtures/profiles/access-hours/<case>.json

access_now(access_hours, switch, now, time_zone) is what the hub sends as client_config.access.hours,
paired-client.access_now and the integration status; the integration decides <ns>.control with the same
window logic (snapshot access). Windows have the form of a bedtime window: end <= start crosses midnight
and belongs to the start day, start == end = 24 hours from start. Windows that touch or overlap are one
continuous access (until follows them to their common end, at most two weeks ahead).

An early access (a Yes to the device's request, $defs/access_early) opens the device from now until
early.until regardless of the windows; a window that starts before it ends continues it. The switch still
closes it. early is reported while early.until is after now.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
UTC = dt.timezone.utc


def _parse(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _fmt(t: dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hhmm(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def spans(windows: list[dict], day: dt.date, tz) -> list[tuple[dt.datetime, dt.datetime]]:
    """UTC spans of the windows that start on the local calendar day."""
    out = []
    for w in windows:
        if DAYS[day.weekday()] not in w["days"]:
            continue
        start_t, end_t = _hhmm(w["start"]), _hhmm(w["end"])
        start = dt.datetime.combine(day, start_t, tzinfo=tz).astimezone(UTC)
        end_day = day if end_t > start_t else day + dt.timedelta(days=1)
        end = dt.datetime.combine(end_day, end_t, tzinfo=tz).astimezone(UTC)
        if end > start:
            out.append((start, end))
    return out


def open_until(windows: list[dict], now: dt.datetime, tz, early_until: dt.datetime | None = None) -> dt.datetime | None:
    """End of the access window now is in (followed through touching windows); None outside.

    early_until is one more span from now to then."""
    local = now.astimezone(tz).date()
    all_spans = sorted(s for off in range(-1, 15) for s in spans(windows, local + dt.timedelta(days=off), tz))
    if early_until is not None and early_until > now:
        all_spans = sorted([*all_spans, (now, early_until)])
    until, point = None, now
    for _ in range(len(all_spans) + 1):
        covering = [end for start, end in all_spans if start <= point < end]
        if not covering:
            break
        point = max(covering)
        until = point
    return until


def next_open(windows: list[dict], now: dt.datetime, tz) -> dt.datetime | None:
    """Start of the next access window within 8 days (None inside one or without one)."""
    if open_until(windows, now, tz) is not None:
        return None
    local = now.astimezone(tz).date()
    starts = [s for off in range(0, 8) for s, _ in spans(windows, local + dt.timedelta(days=off), tz) if s > now]
    return min(starts) if starts else None


def access_now(
    access_hours: dict, switch: bool | None, now: dt.datetime, time_zone: str | None, early: dict | None = None
) -> dict:
    tz = ZoneInfo(time_zone) if time_zone else UTC
    schedule = bool(access_hours.get("enabled"))
    windows = (access_hours.get("windows") or []) if schedule else []
    running = early if early and _parse(early["until"]) > now else None
    early_until = _parse(running["until"]) if running else None
    until = open_until(windows, now, tz, early_until) if schedule else None
    schedule_ok = (not schedule) or until is not None
    switch_ok = switch is not False
    is_open = schedule_ok and switch_ok
    if is_open:
        reason, opens_at = None, None
    elif not switch_ok:
        reason, opens_at, until = "switch", None, None
    else:
        reason, opens_at, until = "schedule", next_open(windows, now, tz), None
    out = {
        "open": is_open,
        "reason": reason,
        "until": _fmt(until),
        "opens_at": _fmt(opens_at),
        "schedule": schedule,
        "switch": switch,
    }
    if early is not None:
        out["early"] = running
    return out


def run_access_vector(vector: dict) -> list[str]:
    errs = []
    for i, case in enumerate(vector["cases"]):
        got = access_now(
            vector["access_hours"], case["switch"], _parse(case["now"]), vector["time_zone"], case.get("early")
        )
        if got != case["expected"]:
            errs.append(f"case {i} ({case['now']}): vector {case['expected']}, reference {got}")
    return errs


if __name__ == "__main__":
    problems = run_access_vector(json.loads(Path(sys.argv[1]).read_text()))
    print("\n".join(problems) or "ok")
    sys.exit(1 if problems else 0)
