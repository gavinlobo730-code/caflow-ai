"""GET /api/payroll/clients/{id}/ecr-sequence names a draft run rather than
claiming none exists (apex-payroll-yearend-11).

WHAT WAS WRONG
    `ecr_sequence.outstanding_note`'s own `months_known_from` comes from
    `finalised_months`, which counts only finalised/paid runs — so a client
    with nothing but a DRAFT run answered "No wage month is outstanding — no
    month has been run here yet", which is false: a run genuinely exists and
    is right there on the Month selector on the same screen, only not yet
    finalised.

WHAT THIS PINS
    `epfo_ecr_filing_service.latest_unreleased_month` finds the most recent
    draft/review month, asked only from the router — and only when
    `finalised_months` came back empty, since a client with a real
    outstanding list has a real answer already and the draft sentence must
    never displace it.
"""
from __future__ import annotations

import routers.payroll as pay
from services import epfo_ecr_filing_service as ecr_filings
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-ECR"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}


def _db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    return db


# ── the service function ─────────────────────────────────────────────────────

def test_finds_the_most_recent_draft_or_review_month(monkeypatch):
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-07", "status": "review"})
    db.seed("payroll_runs", {"id": "R2", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-09", "status": "draft"})
    assert ecr_filings.latest_unreleased_month(
        db, firm_id=FIRM, client_id="CLI") == "2026-09"


def test_a_finalised_or_paid_run_does_not_count(monkeypatch):
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-08", "status": "finalized"})
    db.seed("payroll_runs", {"id": "R2", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-09", "status": "paid"})
    assert ecr_filings.latest_unreleased_month(
        db, firm_id=FIRM, client_id="CLI") is None


def test_no_run_at_all_answers_none(monkeypatch):
    db = _db(monkeypatch)
    assert ecr_filings.latest_unreleased_month(
        db, firm_id=FIRM, client_id="CLI") is None


def test_another_firms_run_is_invisible(monkeypatch):
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": "FIRM-OTHER",
                            "client_id": "CLI", "month": "2026-09",
                            "status": "draft"})
    assert ecr_filings.latest_unreleased_month(
        db, firm_id=FIRM, client_id="CLI") is None


# ── the endpoint, end to end ──────────────────────────────────────────────────

def test_a_client_with_only_a_draft_run_gets_the_draft_sentence(monkeypatch):
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-09", "status": "draft"})
    data = pay.client_ecr_sequence("CLI", CALLER)["data"]
    assert data["months_known_from"] is None
    assert data["outstanding"] == []
    assert "2026-09 is still a draft" in data["note"]
    assert "no month has been run here yet" not in data["note"]


def test_a_client_with_no_runs_at_all_keeps_the_original_sentence(monkeypatch):
    _db(monkeypatch)
    data = pay.client_ecr_sequence("CLI", CALLER)["data"]
    assert data["months_known_from"] is None
    assert "no month has been run here yet" in data["note"]
    assert "draft" not in data["note"]


def test_a_client_with_a_finalised_run_is_unaffected(monkeypatch):
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-08", "status": "finalized"})
    data = pay.client_ecr_sequence("CLI", CALLER)["data"]
    assert data["months_known_from"] == "2026-08"
    assert "draft" not in data["note"]


def test_a_finalised_month_and_a_later_draft_still_reports_the_real_outstanding_list(monkeypatch):
    """A client already known to EPFO must never be told about a draft
    instead of the real, outstanding month — the draft sentence is only for
    the case where finalised_months has literally nothing to say."""
    db = _db(monkeypatch)
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-08", "status": "finalized"})
    db.seed("payroll_runs", {"id": "R2", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-09", "status": "draft"})
    data = pay.client_ecr_sequence("CLI", CALLER)["data"]
    assert data["outstanding"] == ["2026-08"]
    assert "still a draft" not in data["note"]
