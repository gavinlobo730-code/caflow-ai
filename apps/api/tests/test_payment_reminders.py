"""
Phase 4.2 — Payment Reminders (customer-facing collections).

Reminders email the CUSTOMER an overdue-payment notice (+ the invoice PDF) and
record the send in invoice_deliveries (kind='reminder'). They are purely a
collections / informational feature: they post NO journal and change NO
accounting figure (no statement / GST / cash-flow impact). Manual and
CA-initiated only — a CA opens one invoice and sends one reminder. These tests
cover the dispatch + delivery recording, the manual single reminder, the
reminder history, firm isolation, and the no-accounting-side-effects guarantee.

There used to also be an automatic bulk cadence run (coll.run_due_reminders,
plus a nightly scheduler job) covered here. It's removed: on a firm with a
large overdue backlog it looped every open invoice with no bound, could never
finish a pass, and silently starved every job scheduled after it in the
nightly sweep for that firm, every day, indefinitely.
"""
from datetime import date, datetime, timezone, timedelta
from uuid import uuid4

import pytest

import services.collections_service as coll

FIRM = "F1"
OTHER_FIRM = "F2"


# ── Minimal in-memory Supabase double (only the chains these functions use) ──

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._filters: list[tuple] = []
        self._in = None
        self._op = "select"
        self._payload = None
        self._on_conflict = None
        self._limit = None
        self._order = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op, self._payload, self._on_conflict = "upsert", payload, on_conflict
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
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
        if self._in and row.get(self._in[0]) not in self._in[1]:
            return False
        return True

    def execute(self):
        rows = self._db.data.setdefault(self._table, [])
        if self._op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            if self._order:
                col, desc = self._order
                out.sort(key=lambda r: r.get(col) or "", reverse=desc)
            if self._limit is not None:
                out = out[: self._limit]
            return _Result(out)
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                r = dict(p)
                r.setdefault("id", f"{self._table[:3]}-{uuid4().hex[:8]}")
                r.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                rows.append(r)
                inserted.append(dict(r))
            return _Result(inserted)
        if self._op == "update":
            updated = []
            for r in rows:
                if self._match(r):
                    r.update(self._payload)
                    updated.append(dict(r))
            return _Result(updated)
        if self._op == "upsert":
            key = self._on_conflict
            if key:
                for r in rows:
                    if r.get(key) == self._payload.get(key):
                        r.update(self._payload)
                        return _Result([dict(r)])
            r = dict(self._payload)
            rows.append(r)
            return _Result([dict(r)])
        return _Result([])


class FakeDB:
    def __init__(self):
        self.data: dict[str, list] = {}

    def table(self, name):
        return _Query(self, name)

    # convenience seeding
    def seed(self, table, row):
        self.data.setdefault(table, []).append(dict(row))
        return row


def _inv(iid="A", firm=FIRM, status="issued", total=118000, paid=0,
         due="2020-01-01", customer_id="CUST-1", reminder_count=0,
         last_reminded_at=None, client_id="CL-1"):
    return {"id": iid, "firm_id": firm, "client_id": client_id, "customer_id": customer_id,
            "invoice_no": f"SINV-{iid}", "invoice_date": "2019-12-01", "due_date": due,
            "total_paise": total, "paid_paise": paid, "status": status,
            "reminder_count": reminder_count, "last_reminded_at": last_reminded_at}


@pytest.fixture
def email_calls(monkeypatch):
    """Capture reminder emails; default send succeeds. Stub PDF + firm + side-effects."""
    calls: list[dict] = []

    def _fake_email(**kw):
        calls.append(kw)
        return True, "prov-" + uuid4().hex[:6]

    import services.email_service as es
    import services.invoice_pdf_service as pdf
    import services.timeline_service as ts
    import services.audit_service as au

    monkeypatch.setattr(es, "send_payment_reminder_to_customer", _fake_email)
    monkeypatch.setattr(pdf, "get_sales_invoice_pdf", lambda iid, fid: (b"%PDF-1.4 fake", f"{iid}.pdf"))
    monkeypatch.setattr(pdf, "_load_firm", lambda fid: {"name": "Test & Co Chartered Accountants"})
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)

    audit: list[tuple] = []
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audit.append((a, k)))
    calls_holder = {"emails": calls, "audit": audit}
    return calls_holder


@pytest.fixture
def db(monkeypatch):
    """Force the non-mock DB path and route _db()/_open_invoices through a FakeDB."""
    fake = FakeDB()
    monkeypatch.setattr(coll, "_USE_MOCK", False)
    monkeypatch.setattr(coll, "_db", lambda: fake)
    return fake


# ── Dispatch one reminder ────────────────────────────────────────────────────

def test_dispatch_records_delivery_and_bumps_counters(db, email_calls):
    inv = _inv("A", reminder_count=0)
    db.seed("client_sales_invoices", inv)
    customer = {"id": "CUST-1", "name": "Acme Ltd", "email": "ap@acme.test"}

    ok = coll._dispatch_invoice_reminder(db, FIRM, inv, customer, reminder_number=1)
    assert ok is True

    # delivery row recorded as a reminder, marked sent, with provider id
    deliveries = db.data["invoice_deliveries"]
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d["kind"] == "reminder" and d["status"] == "sent"
    assert d["invoice_id"] == "A" and d["sent_to"] == "ap@acme.test"
    assert d.get("provider_message_id", "").startswith("prov-")
    assert d.get("sent_at")

    # invoice counters advanced (no financial field touched)
    row = db.data["client_sales_invoices"][0]
    assert row["reminder_count"] == 1 and row["last_reminded_at"]
    assert row["status"] == "issued" and row["total_paise"] == 118000 and row["paid_paise"] == 0

    # email carried the escalation number and the attached invoice PDF
    sent = email_calls["emails"][0]
    assert sent["reminder_number"] == 1
    assert sent["pdf_bytes"] == b"%PDF-1.4 fake" and sent["pdf_filename"] == "A.pdf"
    assert sent["outstanding_paise"] == 118000

    # audit recorded a reminder_sent event (collections), never a journal action
    actions = [a[0][3] for a in email_calls["audit"]]
    assert "reminder_sent" in actions


def test_dispatch_no_email_is_noop(db, email_calls):
    inv = _inv("A")
    db.seed("client_sales_invoices", inv)
    ok = coll._dispatch_invoice_reminder(db, FIRM, inv, {"id": "CUST-1", "name": "No Email"}, 1)
    assert ok is False
    assert db.data.get("invoice_deliveries") in (None, [])
    assert email_calls["emails"] == []


def test_dispatch_survives_pdf_failure(db, email_calls, monkeypatch):
    import services.invoice_pdf_service as pdf

    def _boom(iid, fid):
        raise RuntimeError("pdf engine down")

    monkeypatch.setattr(pdf, "get_sales_invoice_pdf", _boom)
    inv = _inv("A")
    db.seed("client_sales_invoices", inv)
    customer = {"id": "CUST-1", "name": "Acme", "email": "ap@acme.test"}

    ok = coll._dispatch_invoice_reminder(db, FIRM, inv, customer, 1)
    assert ok is True                                   # reminder still sent (text only)
    assert email_calls["emails"][0]["pdf_bytes"] is None


# ── Manual single reminder ───────────────────────────────────────────────────

def test_manual_reminder_bypasses_cap(db, email_calls):
    # already at the automatic cap, but a CA may still send manually
    db.seed("client_sales_invoices", _inv("A", due="2020-01-01", reminder_count=5))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    res = coll.send_invoice_reminder(FIRM, "A", actor_id="user-1")
    assert res == {"sent": True, "to": "ap@acme.test", "reminder_number": 6}
    assert db.data["client_sales_invoices"][0]["reminder_count"] == 6


def test_manual_reminder_404_when_missing(db, email_calls):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        coll.send_invoice_reminder(FIRM, "NOPE")
    assert ei.value.status_code == 404


def test_manual_reminder_422_when_not_overdue(db, email_calls):
    db.seed("client_sales_invoices", _inv("A", due="2099-01-01"))   # due far in future
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        coll.send_invoice_reminder(FIRM, "A")
    assert ei.value.status_code == 422


def test_manual_reminder_422_when_no_customer_email(db, email_calls):
    db.seed("client_sales_invoices", _inv("A", due="2020-01-01"))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme"})  # no email
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        coll.send_invoice_reminder(FIRM, "A")
    assert ei.value.status_code == 422


def test_manual_reminder_502_when_send_fails(db, email_calls, monkeypatch):
    import services.email_service as es
    monkeypatch.setattr(es, "send_payment_reminder_to_customer", lambda **k: (False, None))
    db.seed("client_sales_invoices", _inv("A", due="2020-01-01"))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        coll.send_invoice_reminder(FIRM, "A")
    assert ei.value.status_code == 502


# ── History + isolation ──────────────────────────────────────────────────────

def test_reminder_history_filters_kind_and_orders(db):
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "A", "kind": "invoice",
                                   "created_at": "2026-06-01T00:00:00+00:00"})
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "A", "kind": "reminder",
                                   "created_at": "2026-06-10T00:00:00+00:00"})
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "A", "kind": "reminder",
                                   "created_at": "2026-06-20T00:00:00+00:00"})
    hist = coll.invoice_reminder_history(FIRM, "A")
    assert [h["created_at"] for h in hist] == [
        "2026-06-20T00:00:00+00:00", "2026-06-10T00:00:00+00:00"]   # newest first, reminders only


def test_firm_isolation(db, email_calls):
    db.seed("client_sales_invoices", _inv("A", firm=FIRM, due="2020-01-01"))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})
    from fastapi import HTTPException
    # another firm cannot remind on F1's invoice
    with pytest.raises(HTTPException) as ei:
        coll.send_invoice_reminder(OTHER_FIRM, "A")
    assert ei.value.status_code == 404
    # nor can it see the reminder history
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "A", "kind": "reminder",
                                   "created_at": "2026-06-20T00:00:00+00:00"})
    assert coll.invoice_reminder_history(OTHER_FIRM, "A") == []


# ── The product guarantee: reminders are NOT accounting events ───────────────

def test_reminders_have_no_accounting_side_effects(db, email_calls):
    db.seed("client_sales_invoices", _inv("A", due="2020-01-01", total=118000, paid=0))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    coll.send_invoice_reminder(FIRM, "A", actor_id="user-1")

    # no journal / ledger / statement / GST tables were ever written
    for forbidden in ("journal_entries", "journal_lines", "ledger_entries",
                      "customer_statements", "gst_returns"):
        assert forbidden not in db.data
    # the invoice's money fields are untouched — only collections metadata moved
    row = db.data["client_sales_invoices"][0]
    assert row["status"] == "issued"
    assert row["total_paise"] == 118000 and row["paid_paise"] == 0
    assert row["reminder_count"] == 1
