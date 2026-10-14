"""A relationship-health score is the client's; the fee figures beside it are the practice's (POST-B-024, stage one).

WHAT WAS WRONG
    `compute_relationship_health` and `compute_recommendations` read the fee invoices as the caller and printed what
    they found: a count of overdue invoices and an amount outstanding, to every member of staff (`ai:read` is
    all-staff). That has two problems, and the second is the one that matters once fee rows are a Partner's to read.

      * the amounts and counts ARE the practice's fee economics, which core/permissions reserves to `billing:read`;
      * a caller whose own read of the fee table is empty (what a Partner-only rule does to everyone else) would see
        the payment third of every score pinned at 40, no payment recommendation, and the screen printing "0" and
        "Rs 0.00" as values, which tells a Manager that a client who owes the practice money owes none.

    The score now reads the client's invoices through `invoice_repo.find_for_health` (four columns, privileged client,
    the firm's own scope), so it is the same for every role, and a caller without `billing:read` is given the score and
    NO figures: `overdue_invoices` and `outstanding_paise` are None, `fees_withheld` is true, and the recommendation
    sentences say a payment is overdue without a count or an amount.

NEGATIVE CONTROL (each of these fails against the previous code)
    * test_the_score_does_not_depend_on_what_the_callers_own_read_of_the_fee_table_returns
    * test_a_caller_without_billing_read_is_given_the_score_and_no_figures
    * test_the_withheld_recommendation_names_no_amount
    * test_the_routes_withhold_the_figures_from_a_manager_and_give_them_to_a_partner
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
from repositories.invoice_repository import invoice_repo
from core.ist_clock import ist_today
from services import intelligence_service as svc

FIRM = "firm-001"
CLIENT = "c-int-1"


class _Clients:
    @staticmethod
    def find_all(firm_id=None, **k):
        return [{"id": CLIENT, "client_name": "Acme Traders", "firm_id": FIRM}]


class _Tasks:
    @staticmethod
    def find_all(firm_id=None, **k):
        return []


def _invoices(*statuses):
    recent = (ist_today() - timedelta(days=5)).isoformat()  # inside the 90 days that count as recent activity
    return [{"client_id": CLIENT, "status": st, "invoice_date": recent, "total_paise": 5_000_00}
            for st in statuses]


@pytest.fixture
def stubbed(monkeypatch):
    import repositories.client_repository as cr
    import repositories.task_repository as tr
    monkeypatch.setattr(cr, "client_repo", _Clients)
    monkeypatch.setattr(tr, "task_repo", _Tasks)

    def set_invoices(rows, *, callers_own_read=()):
        # raising=False: against the previous code there is no find_for_health, and the test must fail on what it
        # ASSERTS and not on a missing attribute.
        monkeypatch.setattr(invoice_repo, "find_for_health", lambda firm_id: list(rows), raising=False)
        monkeypatch.setattr(invoice_repo, "find_all", lambda *a, **k: list(callers_own_read))
    return set_invoices


def test_the_score_does_not_depend_on_what_the_callers_own_read_of_the_fee_table_returns(stubbed):
    stubbed(_invoices("Overdue", "Overdue", "Paid"), callers_own_read=[])  # a caller the fee rows are hidden from
    row = svc.compute_relationship_health(FIRM)["clients"][0]
    # Tasks 40 (none open) + payment round(40 * (1 - 2/3)) = 13 + recent activity 20. Were the invoices invisible the
    # payment third would be the full 40 and the score 100.
    assert row["health_score"] == 40 + 13 + 20
    assert row["overdue_invoices"] == 2
    assert row["outstanding_paise"] == 2 * 5_000_00


def test_a_caller_without_billing_read_is_given_the_score_and_no_figures(stubbed):
    stubbed(_invoices("Overdue", "Issued", "Paid"))
    full = svc.compute_relationship_health(FIRM, include_fee_figures=True)
    redacted = svc.compute_relationship_health(FIRM, include_fee_figures=False)
    a, b = full["clients"][0], redacted["clients"][0]
    assert a["health_score"] == b["health_score"], "the score is the client's: it must not differ by who is looking"
    assert a["health_level"] == b["health_level"]
    assert a["overdue_invoices"] == 1 and a["outstanding_paise"] == 2 * 5_000_00
    assert b["overdue_invoices"] is None and b["outstanding_paise"] is None, (
        "withheld means absent, never 0: a zero is a value and tells the reader the client owes nothing")
    assert full["fees_withheld"] is False and redacted["fees_withheld"] is True


def test_the_withheld_recommendation_names_no_amount(stubbed, monkeypatch):
    stubbed(_invoices("Overdue", "Overdue", "Overdue"))
    monkeypatch.setattr(svc, "compute_compliance_risk", lambda *a, **k: {"clients": []})
    monkeypatch.setattr(svc, "compute_journal_suggestions", lambda *a, **k: {"suggestions": [], "month": "2026-10"})
    shown = svc.compute_recommendations(FIRM, include_fee_figures=True)["recommendations"]
    hidden = svc.compute_recommendations(FIRM, include_fee_figures=False)["recommendations"]
    client_recs = [r for r in hidden if r["category"] == "client"]
    assert client_recs, "a late payment is still worth saying to a role that may not see the amount"
    for r in client_recs:
        assert "₹" not in r["detail"] and not re.search(r"\d+ overdue invoice", r["detail"]), r["detail"]
    assert any("₹" in r["detail"] for r in shown if r["category"] == "client"), "vacuity: the unredacted text has it"


# ── the routes ─────────────────────────────────────────────────────────────────────────────────────────────────────

client = TestClient(app)


@pytest.mark.usefixtures("dev_header_auth")
def test_the_routes_withhold_the_figures_from_a_manager_and_give_them_to_a_partner(stubbed):
    stubbed(_invoices("Overdue", "Issued"))
    manager = {"X-User-Role": "manager", "X-Firm-Id": FIRM, "X-User-Id": "user-002"}
    partner = {"X-User-Role": "partner", "X-Firm-Id": FIRM, "X-User-Id": "user-001"}
    m = client.get("/api/intelligence/relationship-health", headers=manager)
    p = client.get("/api/intelligence/relationship-health", headers=partner)
    assert m.status_code == 200 and p.status_code == 200, (m.text, p.text)
    assert m.json()["data"]["fees_withheld"] is True
    assert p.json()["data"]["fees_withheld"] is False
    for row in m.json()["data"]["clients"]:
        assert row["overdue_invoices"] is None and row["outstanding_paise"] is None
    for row in p.json()["data"]["clients"]:
        assert isinstance(row["outstanding_paise"], int)
