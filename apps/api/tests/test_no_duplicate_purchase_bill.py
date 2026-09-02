"""One supplier invoice, one bill.

purchase_bills carried exactly one unique index — its primary key. The bulk
import had an application-level duplicate guard; the ordinary create path and
the AI-extraction draft had none.

Walking a client with foreign suppliers through a year booked HEL/04 twice —
same vendor, same number, same date, same amount — and got two bills, two
posted journals and TWO Form 27Q rows for one supplier invoice: Rs 1,04,000
withheld where Rs 52,000 was due, with no warning.

A duplicated purchase bill is double-counted expenditure, double input GST
credit under CGST s.16, and a duplicated deductee in a filed TDS return. It
survives review precisely because both copies look correct.

Migration 313's partial unique index is the real guard — it closes the bulk
path and the direct PostgREST writes too. These tests hold the application's
matching rule and the index's predicate together, because the two disagreeing
is how a CA meets a raw 23505 or how duplicates come back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION = (Path(__file__).resolve().parents[1]
             / "migrations" / "313_one_bill_per_vendor_invoice.sql").read_text()


class _DB:
    def __init__(self, rows):
        self._rows = rows
        self._f: dict = {}

    def table(self, name):
        assert name == "purchase_bills", name
        self._f = {}
        return self

    def select(self, *a):
        return self

    def eq(self, col, val):
        self._f[col] = val
        return self

    def neq(self, col, val):
        self._f[f"not_{col}"] = val
        return self

    def is_(self, col, val):
        return self

    def execute(self):
        out = [r for r in self._rows
               if all(r.get(k) == v for k, v in self._f.items() if not k.startswith("not_"))
               and all(r.get(k[4:]) != v for k, v in self._f.items() if k.startswith("not_"))]
        return type("R", (), {"data": out})()


def _dup(rows, bill_no, client="c1", vendor="v1"):
    from routers.purchase_bills import _duplicate_bill_id
    return _duplicate_bill_id(_DB(rows), client, vendor, bill_no)


LIVE = {"id": "b1", "client_id": "c1", "vendor_id": "v1",
        "bill_no": "INV-001", "status": "received"}


# ── The application's matching rule ─────────────────────────────────────────

def test_the_same_number_is_a_duplicate():
    assert _dup([LIVE], "INV-001") == "b1"


@pytest.mark.parametrize("typed", ["inv-001", " INV-001 ", "Inv-001", "  inv-001"])
def test_case_and_whitespace_do_not_make_it_a_different_invoice(typed):
    """"INV-001" and "inv-001" are one supplier invoice, and a CA typing the
    second one is making exactly the mistake this exists to catch."""
    assert _dup([LIVE], typed) == "b1"


def test_a_different_number_is_not_a_duplicate():
    assert _dup([LIVE], "INV-002") is None


def test_another_vendor_s_invoice_number_is_not_a_duplicate():
    """Two suppliers numbering their own invoices from 1 is ordinary."""
    assert _dup([LIVE], "INV-001", vendor="v2") is None


def test_another_client_s_bill_is_not_a_duplicate():
    assert _dup([LIVE], "INV-001", client="c2") is None


def test_a_cancelled_bill_does_not_block_re_entering_it():
    """Cancelling is a credit undone. A CA who cancels INV-001 because the
    amount was wrong and re-enters it correctly is doing the right thing, and
    refusing that would be worse than the bug."""
    assert _dup([{**LIVE, "status": "cancelled"}], "INV-001") is None


def test_a_blank_number_is_never_a_duplicate():
    """Blank is not a value: several unnumbered bills from one vendor are not
    duplicates of each other."""
    for blank in (None, "", "   "):
        assert _dup([{**LIVE, "bill_no": blank}], blank) is None


def test_a_failed_lookup_does_not_block_a_legitimate_bill():
    """The index still refuses a real duplicate; this only chooses the wording,
    so it must never be the thing that stops a bill being booked."""
    class _Boom(_DB):
        def execute(self):
            raise RuntimeError("unreachable")
    from routers.purchase_bills import _duplicate_bill_id
    assert _duplicate_bill_id(_Boom([]), "c1", "v1", "INV-001") is None


# ── The index has to match the application, predicate for predicate ─────────

def test_the_index_is_unique_and_partial():
    assert "CREATE UNIQUE INDEX" in MIGRATION
    assert "uq_purchase_bills_vendor_invoice" in MIGRATION


def test_the_index_keys_on_client_vendor_and_the_normalised_number():
    body = re.search(r"ON public\.purchase_bills \((.*?)\)\s*\n", MIGRATION, re.S)
    assert body, "could not find the index's column list"
    cols = body.group(1)
    assert "client_id" in cols and "vendor_id" in cols
    assert "lower(btrim(bill_no))" in cols, (
        "the index must normalise case and whitespace the same way "
        "_duplicate_bill_id does, or the two disagree")


@pytest.mark.parametrize("clause,why", [
    ("deleted_at IS NULL", "a soft-deleted bill is not live"),
    ("status <> 'cancelled'", "cancelling is a credit undone"),
    ("coalesce(btrim(bill_no), '') <> ''", "blank is not a value"),
])
def test_the_index_excludes_what_the_application_excludes(clause, why):
    assert clause in MIGRATION, f"index predicate is missing: {clause} — {why}"


def test_nothing_upserts_purchase_bills():
    """A PARTIAL unique index is only inferable for ON CONFLICT when the
    statement repeats its predicate, and PostgREST emits none — migration 307
    learned this the hard way. A partial index here is safe only while every
    write is a plain INSERT."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for py in root.rglob("*.py"):
        if "/tests/" in str(py):
            continue
        src = py.read_text(errors="ignore")
        for m in re.finditer(r'table\(\s*["\']purchase_bills["\']\s*\)\.upsert', src):
            offenders.append(str(py.relative_to(root)))
    assert not offenders, (
        f"these upsert purchase_bills, which a partial unique index cannot "
        f"serve for ON CONFLICT: {sorted(set(offenders))}")


# ── Both insert paths, and the bulk guard, use it ───────────────────────────

def test_the_ordinary_create_path_checks_before_inserting():
    import inspect
    from routers import purchase_bills as m
    src = inspect.getsource(m)
    core = src[src.index("bill_resp = db.table(\"purchase_bills\").insert") - 1200:
               src.index("bill_resp = db.table(\"purchase_bills\").insert")]
    assert "_duplicate_bill_id(" in core


def test_the_ai_extraction_draft_checks_too():
    """An upload retried after a timeout is exactly how the same invoice
    arrives twice."""
    import inspect
    from routers import purchase_bills as m
    src = inspect.getsource(m)
    i = src.index('pb_resp = db.table("purchase_bills").insert')
    assert "_duplicate_bill_id(" in src[i - 800:i]


def test_the_bulk_guard_ignores_cancelled_bills_like_the_index_does():
    """Without this the guard refused the FIX: a CA who cancelled a wrong
    INV-001 and re-uploaded it corrected had the corrected row silently
    skipped."""
    import inspect
    from routers.purchase_bills import bulk_create_purchase_bills
    src = inspect.getsource(bulk_create_purchase_bills)
    assert '.neq("status", "cancelled")' in src


def test_the_refusal_says_what_it_costs_and_what_to_do():
    from routers.purchase_bills import _duplicate_bill_message
    msg = _duplicate_bill_message("INV-001", "b1")
    assert "INV-001" in msg and "b1" in msg
    assert "s.16" in msg          # names the input-credit consequence
    assert "cancel" in msg.lower()  # names the way out
