"""
Phase 4.2 — Payment Reminders (customer-facing collections).

Reminders email the CUSTOMER an overdue-payment notice (+ the invoice PDF) and
record the send in invoice_deliveries (kind='reminder'). They are purely a
collections / informational feature: they post NO journal and change NO
accounting figure (no statement / GST / cash-flow impact). These tests cover the
pure cadence math, the dispatch + delivery recording, the automatic cadence run
(incl. anti-spam + disabled), the manual single reminder (bypasses the cap), the
reminder history, firm isolation, and the no-accounting-side-effects guarantee.
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


# ── Pure cadence math ────────────────────────────────────────────────────────

def test_reminder_due_number_cadence():
    f = coll.reminder_due_number
    assert f(6, 0) is None           # before the 7-day interval → nothing
    assert f(7, 0) == 1              # first reminder at 7 days
    assert f(7, 1) is None           # already sent #1 at this stage
    assert f(13, 1) is None          # not yet at the 14-day mark
    assert f(14, 1) == 2             # second reminder at 14 days
    assert f(21, 2) == 3             # third reminder at 21 days
    assert f(28, 3) is None          # capped at max_reminders (3)
    assert f(99, 3) is None          # cap holds no matter how overdue


def test_reminder_due_number_never_before_interval_and_caps():
    f = coll.reminder_due_number
    # very overdue but none sent yet → still starts at #1 (one at a time)
    assert f(100, 0) == 1
    assert f(100, 2) == 3
    assert f(100, 3) is None
    # custom policy: 5-day interval, max 2
    assert f(4, 0, interval_days=5, max_reminders=2) is None
    assert f(5, 0, interval_days=5, max_reminders=2) == 1
    assert f(10, 1, interval_days=5, max_reminders=2) == 2
    assert f(15, 2, interval_days=5, max_reminders=2) is None


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


# ── Automatic cadence run ────────────────────────────────────────────────────

def test_run_due_reminders_cadence(db, email_calls):
    today = date(2026, 6, 22)
    # 7d overdue, none sent → due #1
    db.seed("client_sales_invoices", _inv("A", due="2026-06-15", reminder_count=0))
    # 14d overdue, one sent → due #2
    db.seed("client_sales_invoices", _inv("B", due="2026-06-08", reminder_count=1))
    # only 5d overdue → not yet due
    db.seed("client_sales_invoices", _inv("C", due="2026-06-17", reminder_count=0))
    # already at the cap (3) → no more automatic reminders
    db.seed("client_sales_invoices", _inv("D", due="2026-01-01", reminder_count=3))
    for cid in ("CUST-1",):
        db.seed("customers", {"id": cid, "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    res = coll.run_due_reminders(FIRM, today=today)
    assert res["reminders_sent"] == 2                   # A and B only

    by_id = {r["id"]: r for r in db.data["client_sales_invoices"]}
    assert by_id["A"]["reminder_count"] == 1
    assert by_id["B"]["reminder_count"] == 2
    assert by_id["C"]["reminder_count"] == 0
    assert by_id["D"]["reminder_count"] == 3


def test_run_due_reminders_anti_spam(db, email_calls):
    db.seed("client_sales_invoices", _inv("A", due="2026-06-15", reminder_count=0))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    first = coll.run_due_reminders(FIRM, today=date(2026, 6, 22))   # 7d → #1
    assert first["reminders_sent"] == 1
    # even though by day 14 a #2 would be due, last_reminded_at is within the
    # cadence window → suppressed (anti-spam)
    second = coll.run_due_reminders(FIRM, today=date(2026, 6, 29))
    assert second["reminders_sent"] == 0


def test_run_due_reminders_respects_disabled_setting(db, email_calls):
    db.seed("reminder_settings", {"firm_id": FIRM, "enabled": False,
                                  "interval_days": 7, "max_reminders": 3, "attach_pdf": True})
    db.seed("client_sales_invoices", _inv("A", due="2026-06-15"))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    res = coll.run_due_reminders(FIRM, today=date(2026, 6, 22))
    assert res["reminders_sent"] == 0 and res.get("skipped") == "reminders disabled"
    assert email_calls["emails"] == []


def test_run_due_reminders_custom_settings(db, email_calls):
    # 5-day interval, max 2 — a row 5 days overdue becomes due immediately
    db.seed("reminder_settings", {"firm_id": FIRM, "enabled": True,
                                  "interval_days": 5, "max_reminders": 2, "attach_pdf": False})
    db.seed("client_sales_invoices", _inv("A", due="2026-06-17", reminder_count=0))
    db.seed("customers", {"id": "CUST-1", "firm_id": FIRM, "name": "Acme", "email": "ap@acme.test"})

    res = coll.run_due_reminders(FIRM, today=date(2026, 6, 22))      # 5d overdue
    assert res["reminders_sent"] == 1
    assert email_calls["emails"][0]["pdf_bytes"] is None             # attach_pdf=False honoured


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
