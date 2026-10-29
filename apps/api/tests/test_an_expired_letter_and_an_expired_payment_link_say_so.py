"""A letter or a payment link that has gone past its date says so, and an expired link is not handed back as live (POST-A-106).

WHAT WAS WRONG
    The status vocabulary of an engagement letter has always included "Expired" and no code ever wrote it, so a letter past its
    `expiry_date` stayed "Sent" in the staff list while the public signing page (which asks the date) refused it: two screens described
    one letter in two ways. The same was true of a payment link, created to expire in seven days, and there it was worse than a label:
    `create_link` reuses an open link of the same invoice and amount, and "open" was the stored status alone, so an invoice that was
    asked for a link a fortnight later was handed the old link back, whose gateway page no longer takes money.

WHAT IS ASSERTED
    * THE RULE IS ONE. `domain/engagement/expiry` decides it, the staff router and the public signing router both ask it, and neither
      carries date arithmetic of its own. The last day of a letter is signable; the day after is not; no date and an unreadable date
      never expire; and only a letter still waiting on the client (Sent, Viewed) can expire.
    * THE STAFF LIST SAYS WHAT IT IS NOW. Each letter carries `displayed_status`, the stored `status` is untouched, and a status filter
      is applied to the displayed one, so "Sent" does not list an expired letter and "Expired" does.
    * A PAYMENT LINK SAYS WHAT IT IS NOW, from its own expiry instant, for the two open stored statuses only (a paid link stays paid), and
      the rule that decides it is the one that already refused to email an expired link.
    * AN EXPIRED OPEN LINK IS NOT REUSED. Asked again for the same invoice and amount, the service makes a new link.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.engagement_letters as letters
import routers.engagement_sign_public as sign_public
import services.payment_service as ps
from core.auth import get_current_user
from domain.engagement import expiry
from domain.payments import availability
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API = Path(__file__).resolve().parent.parent
TODAY = date(2026, 6, 30)


# ── the letter's rule ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_last_day_is_signable_and_the_day_after_is_not():
    assert expiry.is_past_expiry("2026-06-30", today=date(2026, 6, 30)) is False
    assert expiry.is_past_expiry("2026-06-30", today=date(2026, 7, 1)) is True
    assert expiry.is_past_expiry("2026-06-30", today=date(2026, 6, 29)) is False


def test_a_letter_with_no_date_or_an_unreadable_one_never_expires():
    for value in (None, "", "soon", "30/06/2026", "2026-13-45"):
        assert expiry.is_past_expiry(value, today=date(2030, 1, 1)) is False, value


def test_a_timestamp_is_read_by_its_date_part_only():
    assert expiry.is_past_expiry("2026-06-30T23:59:59+00:00", today=date(2026, 6, 30)) is False
    assert expiry.is_past_expiry("2026-06-30T00:00:00+00:00", today=date(2026, 7, 1)) is True


@pytest.mark.parametrize("stored,shown", [
    ("Sent", "Expired"), ("Viewed", "Expired"),
    ("Draft", "Draft"), ("Generated", "Generated"), ("Signed", "Signed"), ("Rejected", "Rejected"), ("Expired", "Expired"),
])
def test_only_a_letter_waiting_on_the_client_can_expire(stored, shown):
    assert expiry.displayed_status(stored, "2026-06-01", today=TODAY) == shown


def test_an_unknown_stored_status_is_passed_through_and_never_replaced():
    assert expiry.displayed_status("Withdrawn", "2026-06-01", today=TODAY) == "Withdrawn"
    assert expiry.displayed_status(None, "2026-06-01", today=TODAY) == ""


def test_presenting_a_letter_keeps_the_stored_row_as_it_was():
    row = {"id": "e1", "status": "Sent", "expiry_date": "2026-06-01"}
    shown = expiry.present(row, today=TODAY)
    assert shown["displayed_status"] == "Expired" and shown["status"] == "Sent" and row == {"id": "e1", "status": "Sent", "expiry_date": "2026-06-01"}


def test_both_routers_ask_the_one_rule_and_carry_no_date_arithmetic_of_their_own():
    for name in ("engagement_letters", "engagement_sign_public"):
        source = (API / "routers" / f"{name}.py").read_text()
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_is_expired")
        body = ast.unparse(fn)
        assert "is_past_expiry" in body, f"{name}._is_expired no longer asks domain/engagement/expiry"
        assert "fromisoformat" not in body and "timedelta" not in body, f"{name}._is_expired carries date arithmetic of its own"
    for eng in ({"expiry_date": "2020-01-01"}, {"expiry_date": None}, {"expiry_date": "2999-01-01"}, {}):
        assert letters._is_expired(eng) is sign_public._is_expired(eng)


# ── the staff list ────────────────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "11111111-1111-1111-1111-111111111111"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture()
def staff(monkeypatch):
    long_ago, far_ahead = "2020-01-01", "2999-12-31"
    rows = [
        {"id": "sent-late", "firm_id": FIRM, "status": "Sent", "expiry_date": long_ago, "client_id": None, "created_at": "2026-01-01"},
        {"id": "viewed-late", "firm_id": FIRM, "status": "Viewed", "expiry_date": long_ago, "client_id": None, "created_at": "2026-01-02"},
        {"id": "sent-fine", "firm_id": FIRM, "status": "Sent", "expiry_date": far_ahead, "client_id": None, "created_at": "2026-01-03"},
        {"id": "signed-late", "firm_id": FIRM, "status": "Signed", "expiry_date": long_ago, "client_id": None, "created_at": "2026-01-04"},
        {"id": "draft-late", "firm_id": FIRM, "status": "Draft", "expiry_date": long_ago, "client_id": None, "created_at": "2026-01-05"},
        {"id": "no-date", "firm_id": FIRM, "status": "Sent", "expiry_date": None, "client_id": None, "created_at": "2026-01-06"},
    ]
    monkeypatch.setattr(letters, "_db", lambda: None)
    monkeypatch.setattr(letters, "_MOCK_ENGAGEMENTS", rows)
    app = FastAPI()
    app.include_router(letters.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _ids(res):
    assert res.status_code == 200, res.text
    return sorted(e["id"] for e in res.json()["data"]["engagements"])


def test_the_list_serves_the_displayed_status_beside_the_stored_one(staff):
    res = staff.get("/api/engagement-letters")
    shown = {e["id"]: (e["status"], e["displayed_status"]) for e in res.json()["data"]["engagements"]}
    assert shown["sent-late"] == ("Sent", "Expired") and shown["viewed-late"] == ("Viewed", "Expired")
    assert shown["sent-fine"] == ("Sent", "Sent") and shown["no-date"] == ("Sent", "Sent")
    assert shown["signed-late"] == ("Signed", "Signed") and shown["draft-late"] == ("Draft", "Draft")


def test_a_status_filter_is_applied_to_the_displayed_status(staff):
    assert _ids(staff.get("/api/engagement-letters?status=Expired")) == ["sent-late", "viewed-late"]
    assert _ids(staff.get("/api/engagement-letters?status=Sent")) == ["no-date", "sent-fine"]
    assert _ids(staff.get("/api/engagement-letters?status=Signed")) == ["signed-late"]
    assert len(_ids(staff.get("/api/engagement-letters"))) == 6


# ── the payment link ──────────────────────────────────────────────────────────────────────────────────────────────────────
NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _link(status, expires, provider="razorpay"):
    return {"id": "l1", "status": status, "expires_at": expires.isoformat() if expires else None, "provider": provider,
            "short_url": "https://pay.example/l1"}


@pytest.mark.parametrize("stored,delta,shown", [
    ("created", -1, "expired"), ("active", -1, "expired"), ("active", +1, "active"), ("created", +1, "created"),
    ("paid", -400, "paid"), ("captured", -400, "captured"), ("cancelled", -1, "cancelled"), ("failed", -1, "failed"),
])
def test_only_a_link_still_waiting_to_be_paid_can_expire(stored, delta, shown):
    link = _link(stored, NOW + timedelta(days=delta))
    assert availability.displayed_link_status(link, NOW) == shown


def test_a_link_with_no_readable_expiry_has_not_expired():
    assert availability.displayed_link_status(_link("active", None), NOW) == "active"
    assert availability.displayed_link_status({**_link("active", None), "expires_at": "tomorrow"}, NOW) == "active"


def test_the_listing_shape_carries_the_displayed_status_and_keeps_the_stored_one():
    shown = availability.mask_link(_link("active", datetime.now(timezone.utc) - timedelta(days=1)))
    assert shown["status"] == "active" and shown["displayed_status"] == "expired"
    masked = availability.mask_link(_link("active", datetime.now(timezone.utc) + timedelta(days=1), provider="mock"))
    assert masked["short_url"] is None and masked["displayed_status"] == "active"


def test_the_rule_that_refuses_to_email_an_expired_link_is_the_one_that_displays_it():
    expired = _link("active", NOW - timedelta(seconds=1))
    assert availability.link_is_expired(expired, NOW) is True
    assert "expired" in (availability.link_problem(expired, "razorpay", NOW) or "")
    live = _link("active", NOW + timedelta(seconds=1))
    assert availability.link_is_expired(live, NOW) is False
    assert availability.link_problem(live, "razorpay", NOW) is None


# ── an expired open link is not reused ────────────────────────────────────────────────────────────────────────────────────
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


@pytest.fixture()
def invoice_world(monkeypatch):
    import routers.sales_invoices as si
    from models.invoices import InvoiceLineIn, SalesInvoiceIn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, ps])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme Buyer", "email": "buyer@acme.test",
                          "state_code": "27", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="PAY-001",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return db, inv["id"]


def test_asked_again_a_live_link_is_reused_and_an_expired_one_is_not(invoice_world):
    db, invoice_id = invoice_world
    actor = {"auth_user_id": "u1", "email": "ca@firma.test"}
    first = ps.create_link(db, FIRM, invoice_id, actor=actor)
    assert ps.create_link(db, FIRM, invoice_id, actor=actor)["id"] == first["id"], "a live link of the same amount is reused"

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.table("customer_payment_links").update({"expires_at": past}).eq("id", first["id"]).execute()
    second = ps.create_link(db, FIRM, invoice_id, actor=actor)
    assert second["id"] != first["id"], "the link whose own expiry had passed was handed back as the invoice's link"
    assert len(db.rows("customer_payment_links")) == 2
    shown = {r["id"]: r["displayed_status"] for r in ps.list_links(db, FIRM, invoice_id, actor=CALLER)}
    assert shown[first["id"]] == "expired" and shown[second["id"]] == "active"
