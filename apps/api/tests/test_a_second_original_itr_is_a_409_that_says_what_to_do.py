"""
A second ORIGINAL return for the same form and year is a 409 that says what to
do — open the one that exists, or revise it — not a 500 carrying an index name.

WHAT WAS WRONG
    Migration 381's uq_itr_filings_one_original allows one original per (firm,
    client, financial_year, itr_form). create_filing wrapped the insert in
    `except Exception as e: raise HTTPException(500, detail=str(e))`, so the
    CA was shown the PostgREST payload naming the index, with a status that
    says the server broke and a retry might work. Neither is true.

    The same handler also caught its OWN HTTPExceptions in that clause, so a
    404 or 422 raised underneath it came back as a 500 with the repr of the
    exception as its detail.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import domain.income_tax.itr_workflow as wf
from routers import itr_workspace as iw

CALLER = {"firm_id": "F-dup", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


class _PgError(Exception):
    """The shape supabase-py raises: one dict arg carrying code and message."""
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message})


def _req(**over):
    base = {"client_id": "C-dup", "financial_year": "2025-26",
            "assessment_year": "2026-27", "itr_form": "itr-6"}
    base.update(over)
    return iw.CreateFilingRequest(**base)


def test_a_second_original_is_a_409_naming_the_form_and_the_way_out(monkeypatch):
    def duplicate(**_):
        raise _PgError("23505", 'duplicate key value violates unique constraint '
                                '"uq_itr_filings_one_original"')
    monkeypatch.setattr(wf, "create_itr_filing", duplicate)

    with pytest.raises(HTTPException) as e:
        iw.create_filing(_req(), CALLER)
    assert e.value.status_code == 409
    assert e.value.detail == (
        "An original ITR-6 for FY 2025-26 already exists for this client — "
        "open it, or create a revised return.")
    assert "uq_itr_filings_one_original" not in e.value.detail


def test_an_http_refusal_from_below_keeps_its_own_status(monkeypatch):
    """A 404 for an original_filing_id that is not this firm's must reach the
    CA as the 404 it is, not be re-wrapped as a 500."""
    def not_found(**_):
        raise HTTPException(status_code=404, detail="Original filing not found.")
    monkeypatch.setattr(wf, "create_itr_filing", not_found)

    with pytest.raises(HTTPException) as e:
        iw.create_filing(_req(), CALLER)
    assert e.value.status_code == 404
    assert e.value.detail == "Original filing not found."


def test_an_unknown_failure_does_not_hand_its_own_text_to_the_ca(monkeypatch):
    def explode(**_):
        raise RuntimeError("socket closed by 10.0.0.9")
    monkeypatch.setattr(wf, "create_itr_filing", explode)

    with pytest.raises(HTTPException) as e:
        iw.create_filing(_req(), CALLER)
    assert e.value.status_code == 500
    assert "10.0.0.9" not in e.value.detail
    assert "ITR filing" in e.value.detail


def test_the_ordinary_create_still_works():
    res = iw.create_filing(_req(), CALLER)
    assert res["success"] is True
    assert res["data"]["itr_form"] == "ITR-6"
    assert res["data"]["assessment_year"] == "2026-27"
