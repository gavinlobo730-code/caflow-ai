"""What day the AI copilot thinks it is, and what an instant is written as.

── THE LIVE DEFECT ──────────────────────────────────────────────────────────
`_build_context` opened the copilot's system prompt with

    f"DATE: {datetime.utcnow().strftime('%d %B %Y')}"

and four more places told the model "REAL DATA AS OF <date>" the same way.
**Between 00:00 and 05:30 IST the UTC date is YESTERDAY**, so a CA working late
— which, in an Indian practice in the week before the 20th, is when they are
working — asked the copilot what was due and it reasoned from the wrong day.
"GSTR-3B is due on the 20th and today is the 19th" is a different answer from
"today is the 20th", and this is the one line the model takes the date from.

That is the same defect `recurring_task_service` carried, found the same way,
and CLAUDE.md already states the rule it breaks: a date a PERSON reads is the
Indian day; a stored instant is UTC.

── AND THE HARDENING THAT MADE THE FIX SAFE ─────────────────────────────────
`now` in the same module is used for BOTH — the "as of" line AND `expires_at`
arithmetic on a cached summary. Setting it to `ist_now()` wholesale would have
written `expires_at` as `"...+05:30"` while
`ai_copilot_repository._now()` compared it, as a STRING in the mock branch,
against a bare `utcnow()` — two shapes whose ordering is not the ordering of
the instants they name.

So the two questions are separated rather than merged: an INSTANT is
`datetime.now(timezone.utc)`, aware, on both sides of every comparison; a DATE
told to a person or to the model is `ist_now()`.

⚠️ **The string comparison was NOT broken before this change and is not claimed
to have been.** Both sides were naive UTC, so they agreed. What it was is one
edit away from breaking silently, in a way no test would have caught, and this
is that edit. `datetime.utcnow()` is also deprecated from Python 3.12 exactly
because it returns a naive datetime that only convention calls UTC.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

API = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")

_FILES = ("domain/ai_copilot_service.py", "repositories/ai_copilot_repository.py")


def _code(rel: str) -> str:
    """Docstrings and comments blanked in place — this module's own prose names
    the defect, and a guard that reads its own explanation is vacuous."""
    s = (API / rel).read_text()
    out = list(s)
    for m in re.finditer(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', s):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "
    t = "".join(out)
    for m in re.finditer(r"(?m)^\s*#.*$", t):
        out[m.start():m.end()] = " " * (m.end() - m.start())
    return "".join(out)


@pytest.mark.parametrize("rel", _FILES)
def test_no_naive_utc_clock_read_survives(rel: str):
    """`utcnow()` returns a datetime that only convention calls UTC, and is
    deprecated from 3.12. Every instant here is `datetime.now(timezone.utc)`."""
    body = _code(rel)
    assert "utcnow(" not in body, (
        f"{rel} reads a naive UTC clock again. An instant is "
        "`datetime.now(timezone.utc)`; a date a person reads is `ist_now()`.")


def test_every_date_the_model_is_told_is_the_indian_one():
    """The date-of-today strings, matched on their SHAPE rather than on the
    five sentences that happened to carry them on 24 September."""
    body = _code("domain/ai_copilot_service.py")
    told = re.findall(r"\{([^{}]*?)\.strftime\('%d %B %Y'\)\}", body)
    assert told, (
        "the probe finds no date-of-today string in the copilot's prompts — "
        "if the wording moved, point this guard at it rather than deleting it")
    wrong = [t for t in told if "ist_now" not in t]
    assert not wrong, (
        f"{len(wrong)} prompt(s) tell the model a date that is not the Indian "
        f"day: {wrong}. Between 00:00 and 05:30 IST the UTC date is yesterday, "
        "and this is the line the model reasons from when a CA asks what is due.")


def test_an_instant_and_a_date_are_asked_of_different_clocks():
    """Both are present, and neither answers the other's question. A module
    that used one clock for both is exactly what this separates."""
    body = _code("domain/ai_copilot_service.py")
    assert "datetime.now(timezone.utc)" in body, "no aware UTC instant remains"
    assert "ist_now()" in body, "no Indian date remains"


def test_the_cached_summary_and_its_reader_write_an_instant_the_same_way():
    """`expires_at` is written by the service and compared by the repository —
    as a STRING in the mock branch. Two shapes for one instant is what makes a
    string comparison lie, so both must be aware UTC."""
    svc = _code("domain/ai_copilot_service.py")
    repo = _code("repositories/ai_copilot_repository.py")
    assert re.search(r"expires_at\"?\s*:\s*\(now \+ timedelta", svc), (
        "expires_at is no longer built from `now` — check the reader still "
        "compares the same shape")
    assert "datetime.now(timezone.utc).isoformat()" in repo, (
        "ai_copilot_repository._now() no longer writes an aware instant, so it "
        "compares a different shape from the one the service stores")
    assert "ist_now" not in repo, (
        "the repository reads an IST clock. `expires_at` is an INSTANT and is "
        "compared against a timestamptz — an IST offset there sorts five and a "
        "half hours away from the instant it names.")


# ── The behaviour, not just the source ───────────────────────────────────────

def test_the_two_clocks_really_do_disagree_in_the_window():
    """A premise check. If UTC and IST named the same day at 01:30 there would
    be no defect and this whole guard would be noise."""
    late = datetime(2026, 7, 1, 1, 30, tzinfo=IST)
    assert late.strftime("%d %B %Y") == "01 July 2026"
    assert late.astimezone(timezone.utc).strftime("%d %B %Y") == "30 June 2026"


def test_an_aware_instant_and_a_naive_one_do_not_compare_as_strings():
    """The premise behind writing both sides aware. An IST-offset string and a
    UTC one name the same instant and sort five and a half hours apart."""
    inst = datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc)
    as_utc = inst.isoformat()                      # 2026-09-24T02:00:00+00:00
    as_ist = inst.astimezone(IST).isoformat()      # 2026-09-24T07:30:00+05:30
    assert as_utc != as_ist
    assert as_ist > as_utc, (
        "these name the SAME instant; compared as strings the IST one sorts "
        "later, which is why a TTL written in IST and read in UTC would never "
        "expire")


def test_a_ttl_built_on_the_aware_clock_still_expires():
    """End to end on the arithmetic the service does: six hours from an aware
    now is in the future, and six hours before it is in the past, under the
    same string comparison the repository's mock branch uses."""
    now = datetime.now(timezone.utc)
    assert (now + timedelta(hours=6)).isoformat() > now.isoformat()
    assert (now - timedelta(hours=6)).isoformat() < now.isoformat()
