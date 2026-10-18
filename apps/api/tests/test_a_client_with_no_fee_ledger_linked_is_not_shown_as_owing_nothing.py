"""A portal client whose fee ledger cannot be read is told so, and is not told it owes nothing (POST-A-245).

THE DEFECT
    `portal_data_service.resolve_fee_scope` answers None for a client with no `client_firm_customer_links` row and for a firm
    with no internal client. `list_invoices` turned that into an empty list, so `dues` answered three zeros and both the
    client portal and the staff "Client Portal Preview" printed "No outstanding dues" (and the portal's invoice list
    "No invoices yet."): an unknown shown as a value. The product cannot tell what such a client owes, because the fee
    invoices it may have been billed live behind a link nobody has made. The statement already said so for the same case
    (`available: False`); the dues and the invoice list did not.

WHAT IS HELD
    * the dues of an unlinked client are `available: False`, the three totals are None (not 0) and a sentence is served;
    * a linked client with nothing outstanding is still a genuine zero, `available: True`, so the fix does not turn every
      paid-up client into an unknown;
    * a firm with no internal client is the same unknown;
    * the invoice list says the same thing, and `list_invoices` (the lookup the reminder history uses) keeps returning a
      plain list;
    * both screens read the flag: neither prints "No outstanding dues" for a response that says the ledger is unavailable,
      and the portal does not render the three headline figures for it or fall back to `?? 0`;
    * (POST-A-256) the payment-reminders list is the same: a client whose fee ledger cannot be read is told so, and is not told
      "No reminders have been sent", which would be a claim about a ledger nobody could read. A linked client with no reminder
      is still a genuine empty list.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import services.portal_data_service as pds
from tests.test_portal_data_surfaces import (
    FIRM, INTERNAL_CLIENT, LINKED_CUSTOMER, OTHER_FIRM, PORTAL_CLIENT, TODAY, FakeDB, _inv,
)

WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "app"
PREVIEW = WEB / "client-portal" / "page.tsx"
PORTAL = WEB / "portal" / "dashboard" / "page.tsx"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.seed("client_firm_customer_links",
           {"firm_id": FIRM, "client_id": PORTAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER})
    import services.internal_client_service as ics
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: INTERNAL_CLIENT if firm_id == FIRM else None)
    return d


def test_an_unlinked_clients_dues_are_unavailable_and_not_zero(db):
    out = pds.dues(FIRM, "PC-UNLINKED", db=db, today=TODAY)
    assert out["available"] is False
    assert out["reason"] == pds.FEE_LEDGER_NOT_LINKED and out["reason"]
    assert out["dues"] == []
    assert out["total_outstanding_paise"] is None and out["overdue_paise"] is None and out["overdue_count"] is None


def test_a_firm_with_no_internal_client_is_the_same_unknown(db):
    db.seed("client_firm_customer_links",
            {"firm_id": OTHER_FIRM, "client_id": PORTAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER})
    out = pds.dues(OTHER_FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert out["available"] is False and out["total_outstanding_paise"] is None


def test_a_linked_client_with_nothing_outstanding_is_a_genuine_zero(db):
    db.seed("client_sales_invoices", _inv("PAID", status="paid", total=20000, paid=20000))
    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert out["available"] is True and out["reason"] is None
    assert out["total_outstanding_paise"] == 0 and out["overdue_paise"] == 0 and out["overdue_count"] == 0


def test_a_linked_client_with_no_invoices_at_all_is_a_genuine_zero_too(db):
    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert out["available"] is True and out["total_outstanding_paise"] == 0


def test_the_lookup_keeps_returning_a_plain_list_and_the_unknown_is_kept_apart(db):
    assert pds.list_invoices(FIRM, "PC-UNLINKED", db=db, today=TODAY) == []
    assert pds.fee_invoices_or_none(FIRM, "PC-UNLINKED", db=db, today=TODAY) is None
    assert pds.fee_invoices_or_none(FIRM, PORTAL_CLIENT, db=db, today=TODAY) == []


@pytest.fixture
def client(db, monkeypatch):
    from fastapi.testclient import TestClient
    from core.portal_auth import get_current_portal_client
    from main import app
    monkeypatch.setattr(pds, "_db", lambda: db)

    def _as(client_id):
        app.dependency_overrides[get_current_portal_client] = lambda: {
            "portal": True, "client_id": client_id, "firm_id": FIRM, "portal_contact_id": "c-1",
            "email": "a@c.test", "name": "Alice", "role": "PortalClient",
            "memberships": [{"client_id": client_id, "name": "Alice"}],
        }
        return TestClient(app)

    yield _as
    app.dependency_overrides.clear()


def test_the_invoice_list_route_says_the_ledger_is_unavailable(client):
    body = client("PC-UNLINKED").get("/api/portal/self/invoices").json()
    assert body["success"] is True
    assert body["data"] == {"invoices": [], "available": False, "reason": pds.FEE_LEDGER_NOT_LINKED}


def test_the_invoice_list_route_of_a_linked_client_is_available(client, db):
    db.seed("client_sales_invoices", _inv("A", status="issued", total=50000, due="2099-01-01"))
    data = client(PORTAL_CLIENT).get("/api/portal/self/invoices").json()["data"]
    assert data["available"] is True and data["reason"] is None
    assert [i["id"] for i in data["invoices"]] == ["A"]


def test_the_dues_route_says_the_ledger_is_unavailable(client):
    data = client("PC-UNLINKED").get("/api/portal/self/dues").json()["data"]
    assert data["available"] is False and data["total_outstanding_paise"] is None


def test_the_reminder_history_of_an_unlinked_client_is_unknown_and_of_a_linked_one_is_a_genuine_list(db):
    assert pds.reminder_history_or_none(FIRM, "PC-UNLINKED", db=db, today=TODAY) is None
    assert pds.reminder_history_or_none(FIRM, PORTAL_CLIENT, db=db, today=TODAY) == []
    assert pds.reminder_history(FIRM, "PC-UNLINKED", db=db, today=TODAY) == [], "the plain lookup keeps returning a list"


def test_a_reminder_sent_about_a_linked_clients_invoice_is_listed(db):
    db.seed("client_sales_invoices", _inv("OWN1", status="issued", total=50000, due="2099-01-01"))
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "OWN1", "kind": "reminder", "status": "sent",
                                   "sent_at": "2026-10-01T10:00:00+00:00", "created_at": "2026-10-01T10:00:00+00:00"})
    rows = pds.reminder_history_or_none(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert rows is not None and len(rows) == 1 and rows[0]["invoice_no"]


def test_the_reminders_route_says_the_ledger_is_unavailable(client):
    body = client("PC-UNLINKED").get("/api/portal/self/reminders").json()
    assert body["success"] is True
    assert body["data"] == {"reminders": [], "available": False, "reason": pds.FEE_LEDGER_NOT_LINKED}


def test_the_reminders_route_of_a_linked_client_is_available_even_when_empty(client):
    data = client(PORTAL_CLIENT).get("/api/portal/self/reminders").json()["data"]
    assert data == {"reminders": [], "available": True, "reason": None}


def _code(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def test_the_staff_preview_reads_the_flag_and_does_not_call_it_no_dues():
    code = _code(PREVIEW)
    assert "available === false" in code, "the preview must read the server's `available` flag"
    i_flag = code.index("duesUnavailable !== null")
    i_none = code.index("No outstanding dues for this client")
    assert i_flag < i_none, "the unavailable state must be answered before the empty-list sentence"


def test_the_portal_reads_the_flag_for_the_headline_figures_and_the_invoice_list():
    code = _code(PORTAL)
    assert re.search(r"dues\.available\s*!==\s*false", code), "the figures render only for an available ledger"
    assert "duesFigures" in code and "dues.total_outstanding_paise ?? 0" not in code
    assert "invoicesUnavailable ??" in code, "the empty invoice list must name the unavailable ledger, not 'No invoices yet.'"


def test_the_portal_names_the_unavailable_ledger_instead_of_no_reminders():
    code = _code(PORTAL)
    assert "remindersUnavailable ??" in code, "the empty reminders list must name the unavailable ledger"
    assert code.count('"No reminders have been sent."') == 1, "the plain sentence is only the fallback after the unknown"
    assert code.index("remindersUnavailable ??") < code.index('"No reminders have been sent."')
    assert "setRemindersUnavailable(r.data?.available === false" in code


def test_negative_control_the_old_screens_would_be_caught():
    old_portal = "{dues && (<p>{formatPaise(dues.total_outstanding_paise)}</p>)}"
    assert not re.search(r"dues\.available\s*!==\s*false", old_portal)
