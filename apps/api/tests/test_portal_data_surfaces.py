"""
Phase 4.5.2 — Portal Data Surfaces (client-facing, read-only).

These surfaces expose ONLY the firm↔client fee relationship (invoices the firm
issued to the client, canonical dues, statements, payment reminders) plus the
client's own compliance status. They must NEVER leak the client's own accounting
ledger or any internal field (journal ids, the internal customer/client linkage,
assignees, fees, notes, risk, escalation, provider ids).

Coverage:
  • pure client-safe projections drop every internal field
  • fee-scope resolution (portal client → internal client + linked customer)
  • invoice listing is scoped to the linked customer's invoices in the internal
    client's books (firm / client / customer isolation)
  • canonical AR dues (integer paise) — reads invoices, never `transactions`
  • PDF ownership gate (in-scope true / out-of-scope false)
  • reminder history scoped to in-scope invoices
  • compliance projection strips internal fields
  • statement delegates to the 4.1 engine with the resolved internal scope
"""
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import services.portal_data_service as pds

FIRM = "F1"
OTHER_FIRM = "F2"
PORTAL_CLIENT = "PC-1"          # the external portal client
INTERNAL_CLIENT = "INT-CL"      # the firm's own internal books
LINKED_CUSTOMER = "CUST-LINK"   # the customer (in internal books) = this portal client
TODAY = date(2024, 6, 1)


# ── Minimal in-memory Supabase double (only the chains these functions use) ──

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._filters: list[tuple] = []
        self._is: list[tuple] = []
        self._in = None
        self._limit = None
        self._order = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def is_(self, col, val):
        # Mirrors PostgREST .is_("col", "null") → rows whose col IS NULL.
        self._is.append((col, val))
        return self

    def in_(self, col, vals):
        self._in = (col, list(vals))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def _match(self, row) -> bool:
        if any(row.get(c) != v for c, v in self._filters):
            return False
        for col, val in self._is:
            if val == "null" and row.get(col) is not None:
                return False
        if self._in and row.get(self._in[0]) not in self._in[1]:
            return False
        return True

    def execute(self):
        rows = self._db.data.setdefault(self._table, [])
        out = [dict(r) for r in rows if self._match(r)]
        if self._order:
            col, desc = self._order
            out.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]
        return _Result(out)


class FakeDB:
    def __init__(self):
        self.data: dict[str, list] = {}

    def table(self, name):
        return _Query(self, name)

    def seed(self, table, row):
        self.data.setdefault(table, []).append(dict(row))
        return row


def _inv(iid, *, firm=FIRM, client=INTERNAL_CLIENT, customer=LINKED_CUSTOMER,
         status="issued", total=100000, paid=0, due="2024-01-01",
         invoice_date="2023-12-01", deleted_at=None):
    """An internal-books sales invoice (the firm's fee invoice to the client)."""
    return {
        "id": iid, "firm_id": firm, "client_id": client, "customer_id": customer,
        "invoice_no": f"SINV-{iid}", "invoice_date": invoice_date, "due_date": due,
        "total_paise": total, "paid_paise": paid, "status": status,
        "deleted_at": deleted_at,
        # internal-only fields that must NEVER reach the client:
        "journal_entry_id": f"JE-{iid}", "source": "manual", "created_by": "staff-9",
    }


@pytest.fixture
def db(monkeypatch):
    """A FakeDB with the firm↔client link wired, and the internal-client resolver
    pinned to INTERNAL_CLIENT for FIRM (None for any other firm)."""
    d = FakeDB()
    d.seed("client_firm_customer_links",
           {"firm_id": FIRM, "client_id": PORTAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER})

    import services.internal_client_service as ics
    monkeypatch.setattr(ics, "get_internal_client_id",
                        lambda firm_id: INTERNAL_CLIENT if firm_id == FIRM else None)
    return d


# ── Pure client-safe projections ──────────────────────────────────────────────

_SAFE_INVOICE_KEYS = {"id", "invoice_no", "invoice_date", "due_date", "total_paise",
                      "paid_paise", "outstanding_paise", "status", "is_overdue", "days_overdue"}
_INTERNAL_INVOICE_KEYS = {"journal_entry_id", "source", "created_by", "customer_id", "client_id", "firm_id"}


def test_safe_invoice_strips_internal_fields():
    out = pds.safe_invoice(_inv("A", total=118000, paid=18000, due="2024-01-01"), TODAY)
    assert set(out) == _SAFE_INVOICE_KEYS
    assert _INTERNAL_INVOICE_KEYS.isdisjoint(out)
    # derived, integer-paise outstanding + overdue (due 2024-01-01 vs TODAY 2024-06-01)
    assert out["outstanding_paise"] == 100000
    assert out["is_overdue"] is True and out["days_overdue"] > 0


def test_safe_reminder_strips_internal_fields():
    delivery = {"status": "sent", "sent_at": "2024-05-01T00:00:00Z", "created_at": "2024-05-01T00:00:00Z",
                "sent_by_user_id": "u-1", "provider_message_id": "prov-xyz", "error": "boom",
                "recipient_email": "client@example.com", "invoice_id": "A", "kind": "reminder"}
    out = pds.safe_reminder(delivery, "SINV-A")
    assert set(out) == {"invoice_no", "status", "sent_at", "created_at"}
    assert out["invoice_no"] == "SINV-A" and out["status"] == "sent"
    for leaked in ("sent_by_user_id", "provider_message_id", "error", "recipient_email", "invoice_id"):
        assert leaked not in out


def test_safe_compliance_strips_internal_fields():
    rec = {"compliance_type": "GST", "obligation_type": "GSTR-3B", "period_label": "May 2024",
           "period_start": "2024-05-01", "period_end": "2024-05-31", "due_date": "2024-06-20",
           "status": "pending", "filed_date": None, "acknowledgement_no": None,
           # internal-only:
           "notes": "chase the client", "assigned_to": "staff-2", "preparer_id": "p-1",
           "reviewer_id": "r-1", "approver_id": "a-1", "priority": "high", "risk_score": 88,
           "escalation_level": 2, "engagement_id": "ENG-1"}
    out = pds.safe_compliance(rec)
    assert set(out) == {"compliance_type", "obligation_type", "period_label", "period_start",
                        "period_end", "due_date", "status", "filed_date", "acknowledgement_no"}
    for leaked in ("notes", "assigned_to", "preparer_id", "reviewer_id", "approver_id",
                   "priority", "risk_score", "escalation_level", "engagement_id"):
        assert leaked not in out


# ── Fee-scope resolution ───────────────────────────────────────────────────────

def test_resolve_fee_scope_ok(db):
    scope = pds.resolve_fee_scope(FIRM, PORTAL_CLIENT, db)
    assert scope == {"internal_client_id": INTERNAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER}


def test_resolve_fee_scope_none_when_no_link(db):
    assert pds.resolve_fee_scope(FIRM, "PC-UNLINKED", db) is None


def test_resolve_fee_scope_none_when_no_internal_client(db):
    # OTHER_FIRM has no internal client per the pinned resolver.
    db.seed("client_firm_customer_links",
            {"firm_id": OTHER_FIRM, "client_id": PORTAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER})
    assert pds.resolve_fee_scope(OTHER_FIRM, PORTAL_CLIENT, db) is None


def test_resolve_fee_scope_none_in_mock_mode():
    assert pds.resolve_fee_scope(FIRM, PORTAL_CLIENT, None) is None


# ── Invoice listing (scoping + isolation + projection) ──────────────────────────

def test_list_invoices_scoped_and_isolated(db):
    db.seed("client_sales_invoices", _inv("OWN1"))
    db.seed("client_sales_invoices", _inv("OWN2", due="2024-12-31", total=50000, paid=10000))
    # Out-of-scope rows that must NOT appear:
    db.seed("client_sales_invoices", _inv("OTHER_CUST", customer="CUST-OTHER"))
    db.seed("client_sales_invoices", _inv("OTHER_CLIENT", client="INT-CL-OTHER"))
    db.seed("client_sales_invoices", _inv("OTHER_FIRM", firm=OTHER_FIRM))
    db.seed("client_sales_invoices", _inv("DELETED", deleted_at="2024-02-02T00:00:00Z"))

    rows = pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    ids = {r["id"] for r in rows}
    assert ids == {"OWN1", "OWN2"}
    # projection is client-safe
    for r in rows:
        assert set(r) == _SAFE_INVOICE_KEYS
        assert _INTERNAL_INVOICE_KEYS.isdisjoint(r)


def test_list_invoices_empty_without_link(db):
    db.seed("client_sales_invoices", _inv("OWN1"))
    assert pds.list_invoices(FIRM, "PC-UNLINKED", db=db, today=TODAY) == []


def test_list_invoices_empty_in_mock_mode():
    # db defaults to _db() → None in mock mode → no scope → [].
    assert pds.list_invoices(FIRM, PORTAL_CLIENT, today=TODAY) == []


# ── Canonical AR dues (integer paise; reads invoices, not `transactions`) ───────

def test_dues_canonical_ar(db):
    db.seed("client_sales_invoices", _inv("OV", status="issued", total=100000, paid=0, due="2024-01-01"))
    db.seed("client_sales_invoices", _inv("OPEN", status="issued", total=50000, paid=10000, due="2024-12-31"))
    db.seed("client_sales_invoices", _inv("PARTIAL", status="partially_paid", total=30000, paid=5000, due="2024-12-31"))
    db.seed("client_sales_invoices", _inv("PAID", status="paid", total=20000, paid=20000, due="2024-01-01"))
    # A stray transactions row proves dues NEVER reads the legacy source.
    db.seed("transactions", {"firm_id": FIRM, "client_id": PORTAL_CLIENT, "total_paise": 999999, "status": "pending"})

    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    due_ids = {d["id"] for d in out["dues"]}
    assert due_ids == {"OV", "OPEN", "PARTIAL"}                     # PAID excluded (outstanding 0)
    assert out["total_outstanding_paise"] == 100000 + 40000 + 25000  # integer paise
    assert out["overdue_paise"] == 100000                           # only OV is past due
    assert out["overdue_count"] == 1
    assert 999999 not in [d["total_paise"] for d in out["dues"]]    # transactions ignored


def test_dues_empty_in_mock_mode():
    out = pds.dues(FIRM, PORTAL_CLIENT, today=TODAY)
    assert out == {"dues": [], "total_outstanding_paise": 0, "overdue_paise": 0, "overdue_count": 0}


# ── PDF ownership gate ──────────────────────────────────────────────────────────

def test_invoice_in_scope_true_for_owned(db):
    db.seed("client_sales_invoices", _inv("OWN1"))
    assert pds.invoice_in_scope(FIRM, PORTAL_CLIENT, "OWN1", db=db) is True


def test_invoice_in_scope_false_for_other_customer(db):
    db.seed("client_sales_invoices", _inv("X", customer="CUST-OTHER"))
    assert pds.invoice_in_scope(FIRM, PORTAL_CLIENT, "X", db=db) is False


def test_invoice_in_scope_false_for_other_firm(db):
    db.seed("client_sales_invoices", _inv("X", firm=OTHER_FIRM))
    assert pds.invoice_in_scope(FIRM, PORTAL_CLIENT, "X", db=db) is False


def test_invoice_in_scope_false_for_deleted(db):
    db.seed("client_sales_invoices", _inv("X", deleted_at="2024-02-02T00:00:00Z"))
    assert pds.invoice_in_scope(FIRM, PORTAL_CLIENT, "X", db=db) is False


def test_invoice_in_scope_false_without_link(db):
    db.seed("client_sales_invoices", _inv("OWN1"))
    assert pds.invoice_in_scope(FIRM, "PC-UNLINKED", "OWN1", db=db) is False


# ── Reminder history (scoped + projection) ──────────────────────────────────────

def test_reminder_history_scoped_and_safe(db):
    db.seed("client_sales_invoices", _inv("OWN1"))
    db.seed("client_sales_invoices", _inv("OTHER_CUST", customer="CUST-OTHER"))
    # reminder for the in-scope invoice
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "OWN1", "kind": "reminder",
                                   "status": "sent", "sent_at": "2024-05-02T00:00:00Z",
                                   "created_at": "2024-05-02T00:00:00Z",
                                   "sent_by_user_id": "u-1", "provider_message_id": "prov-x"})
    # a non-reminder delivery (e.g. the invoice send) must be excluded
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "OWN1", "kind": "invoice",
                                   "status": "sent", "created_at": "2024-04-01T00:00:00Z"})
    # a reminder for an out-of-scope invoice must be excluded
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "OTHER_CUST", "kind": "reminder",
                                   "status": "sent", "created_at": "2024-05-03T00:00:00Z"})

    rows = pds.reminder_history(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert len(rows) == 1
    assert rows[0] == {"invoice_no": "SINV-OWN1", "status": "sent",
                       "sent_at": "2024-05-02T00:00:00Z", "created_at": "2024-05-02T00:00:00Z"}


def test_reminder_history_empty_without_invoices(db):
    assert pds.reminder_history(FIRM, "PC-UNLINKED", db=db, today=TODAY) == []


# ── Compliance projection ───────────────────────────────────────────────────────

def test_compliance_projection_strips_internal_fields(monkeypatch):
    captured = {}

    def _fake_list_records(firm_id, client_id):
        captured["args"] = (firm_id, client_id)
        return [{"compliance_type": "GST", "obligation_type": "GSTR-3B", "period_label": "May 2024",
                 "period_start": "2024-05-01", "period_end": "2024-05-31", "due_date": "2024-06-20",
                 "status": "pending", "filed_date": None, "acknowledgement_no": None,
                 "notes": "internal", "assigned_to": "staff-2", "risk_score": 90, "engagement_id": "E-1"}]

    import domain.compliance_record_service as crs
    monkeypatch.setattr(crs.compliance_record_service, "list_records", _fake_list_records)

    out = pds.compliance(FIRM, PORTAL_CLIENT)
    assert captured["args"] == (FIRM, PORTAL_CLIENT)            # keyed on the PORTAL client id
    assert len(out) == 1
    assert set(out[0]) == {"compliance_type", "obligation_type", "period_label", "period_start",
                           "period_end", "due_date", "status", "filed_date", "acknowledgement_no"}
    for leaked in ("notes", "assigned_to", "risk_score", "engagement_id"):
        assert leaked not in out[0]


# ── Statement delegation (reuses the 4.1 engine with the internal scope) ────────

def test_statement_delegates_with_internal_scope(db, monkeypatch):
    captured = {}

    def _fake_generate(_db, firm_id, client_id, customer_id, start, end):
        captured.update(firm_id=firm_id, client_id=client_id, customer_id=customer_id,
                        start=start, end=end)
        return {"customer": {"id": customer_id}, "transactions": [], "opening_balance_paise": 0,
                "closing_balance_paise": 0}

    import services.customer_statement_service as css
    monkeypatch.setattr(css.customer_statement_service, "generate", _fake_generate)

    out = pds.statement(FIRM, PORTAL_CLIENT, "2024-04-01", "2025-03-31", db=db)
    # resolved to the INTERNAL client + the LINKED customer (never the portal ids)
    assert captured["client_id"] == INTERNAL_CLIENT
    assert captured["customer_id"] == LINKED_CUSTOMER
    assert captured["start"] == "2024-04-01" and captured["end"] == "2025-03-31"
    assert out["customer"] == {"id": LINKED_CUSTOMER}


def test_statement_unavailable_without_link(db):
    out = pds.statement(FIRM, "PC-UNLINKED", "2024-04-01", "2025-03-31", db=db)
    assert out["available"] is False and out["transactions"] == []


def test_current_fy_range():
    assert pds.current_fy_range(date(2024, 6, 1)) == ("2024-04-01", "2025-03-31")
    assert pds.current_fy_range(date(2024, 3, 31)) == ("2023-04-01", "2024-03-31")


# ── Router wiring (TestClient + portal-auth override) ──────────────────────────
# Proves each endpoint is gated by get_current_portal_client (overridable here),
# returns the {success,data,error} envelope, and enforces the PDF ownership gate.

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    from core.portal_auth import get_current_portal_client
    app.dependency_overrides[get_current_portal_client] = lambda: {
        "portal": True, "client_id": PORTAL_CLIENT, "firm_id": FIRM,
        "portal_contact_id": "c-1", "email": "a@c.test", "name": "Alice",
        "role": "PortalClient", "memberships": [{"client_id": PORTAL_CLIENT, "name": "Alice"}],
    }
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_routes_use_portal_auth_and_envelope(client):
    r = client.get("/api/portal/self/dues")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["error"] is None
    # canonical AR shape (mock mode → zeros; legacy `transactions` never consulted)
    assert body["data"] == {"dues": [], "total_outstanding_paise": 0, "overdue_paise": 0, "overdue_count": 0}

    assert client.get("/api/portal/self/invoices").json()["data"] == {"invoices": []}
    assert client.get("/api/portal/self/reminders").json()["data"] == {"reminders": []}

    s = client.get("/api/portal/self/statement").json()
    assert s["success"] is True and s["data"]["available"] is False


def test_invoice_pdf_ownership_gate_blocks_unowned(client):
    # mock mode → no fee scope → ownership fails → 404 (never reveals existence)
    assert client.get("/api/portal/self/invoices/any-id/pdf").status_code == 404


def test_statement_pdf_unavailable_in_mock_mode(client):
    assert client.get("/api/portal/self/statement/pdf").status_code == 501


def test_compliance_route_strips_internal_fields(client, monkeypatch):
    import domain.compliance_record_service as crs
    monkeypatch.setattr(crs.compliance_record_service, "list_records",
                        lambda firm_id, client_id: [{
                            "compliance_type": "GST", "obligation_type": "GSTR-3B", "status": "pending",
                            "notes": "secret", "risk_score": 9, "assigned_to": "staff-x", "engagement_id": "E-1"}])
    data = client.get("/api/portal/self/compliance").json()["data"]
    assert data["compliance"][0]["compliance_type"] == "GST"
    for leaked in ("notes", "risk_score", "assigned_to", "engagement_id"):
        assert leaked not in data["compliance"][0]
