"""The firm's own GSTIN: a malformed one is refused, and the screen says so
(sweep-settings-hub-1-07).

WHAT THE SWEEP SAW, AND WHAT WAS ACTUALLY TRUE

It typed `INVALID_GSTIN_123` into Settings → Firm Profile, pressed Save, saw
the field turn red with "Invalid GSTIN format", and saw a `PATCH
/api/firms/profile` answer 200 — and reported that a malformed GSTIN might be
reaching the database. Production says it did not (both firms' `gstin` and
`gst_number` are NULL), and the screen's `validate()` returns before any
request. The 200 was a LATER save.

What made that misreading easy is the defect: a refused Save said nothing at
all — no toast, only a red line under one field — and the line said "format"
for every failure including a transposed check digit, naming no character. So
a CA could not tell "not sent" from "sent with a warning". The screen now says
"Not saved" and shows `gstinProblem`'s own sentence, at fifteen characters.

These tests CALL the endpoint, because `test_the_firms_own_gstin_has_one_column`
asserts the refusal on the SOURCE only — a spelling, which would stay green if
the call were moved below the write.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi import HTTPException

from domain.gst.gstin import problem_with
from routers import firms

USER = {"id": "u1", "auth_user_id": "u1", "firm_id": "firm-1", "role": "Partner"}
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def no_database(monkeypatch):
    """Any database handle is a failure: the refusal must come FIRST."""
    import core.supabase_client as sc

    def _boom():
        raise AssertionError("a refused GSTIN reached the database")
    monkeypatch.setattr(sc, "get_service_supabase", _boom)


@pytest.mark.parametrize("gstin", [
    "INVALID_GSTIN_123",   # the sweep's own value — seventeen characters
    "INVALID_GSTIN_1",     # what a 15-character maxLength leaves of it
    "27AABCS1429B1ZB",     # the right shape and a wrong check digit
    "00AABCS1429B1ZU",     # no such state
])
def test_a_malformed_gstin_is_refused_before_anything_is_written(no_database, gstin):
    with pytest.raises(HTTPException) as e:
        firms.update_firm_profile(firms.FirmProfileIn(gstin=gstin), current_user=USER)
    assert e.value.status_code == 400
    # The refusal is the authority's own sentence, not a generic "invalid".
    assert e.value.detail == problem_with(gstin.strip().upper())


def test_the_example_the_screen_teaches_is_itself_a_valid_gstin():
    """The placeholder is what a CA copies the shape of."""
    src = (WEB / "app" / "settings" / "page.tsx").read_text(encoding="utf-8")
    assert 'placeholder="e.g. 27AABCU9603R1ZN"' in src
    assert problem_with("27AABCU9603R1ZN") is None


@pytest.mark.parametrize("rel", ["app/settings/page.tsx", "app/onboarding/page.tsx"])
def test_the_screen_shows_the_authoritys_sentence_not_a_fixed_one(rel):
    # Comments stripped: the fix quotes the old message to explain itself, and
    # a guard satisfied or failed by its own explanation is no guard.
    src = "\n".join(line.split("//", 1)[0]
                    for line in (WEB / rel).read_text(encoding="utf-8").splitlines())
    assert "gstinProblem(" in src
    for fixed in ('"Invalid GSTIN format', '"Invalid GSTIN ('):
        assert fixed not in src, f"{rel} still replaces the reason with {fixed}"


def test_a_refused_save_says_nothing_was_sent():
    src = (WEB / "app" / "settings" / "page.tsx").read_text(encoding="utf-8")
    start = src.index("async function handleSave()")
    head = src[start:src.index("setSaving(true)", start)]
    assert "if (!validate())" in head
    assert "Not saved" in head, "a refused Save must say so, not only colour a field"
