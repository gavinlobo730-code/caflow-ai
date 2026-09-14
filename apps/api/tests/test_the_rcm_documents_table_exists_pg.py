"""Migration 388 — the two reverse-charge documents, on real PostgreSQL
(PUR-19).

WHY THIS NEEDS A REAL DATABASE. Most of the design is constraints rather than
code: that a document hangs off EXACTLY ONE parent and that the parent matches
its kind, that only one document may exist per bill and per payment, that the
number is unique per client PER KIND (so the two series cannot collide), that
`vendors.gst_registration_status` is nullable with no default so the third state
is real, and the grant model. None of it is observable in mock mode, where the
in-memory double accepts anything.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
VENDOR = "33333333-3333-3333-3333-333333333333"
BILL = "44444444-4444-4444-4444-444444444444"
BILL2 = "55555555-5555-5555-5555-555555555555"
PAYMENT = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"rcm_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO vendors (id, firm_id, client_id, name)
            VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Ramesh Transport');
            INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_date)
            VALUES ('{BILL}',  '{FIRM}', '{CLIENT}', '{VENDOR}', DATE '2026-06-10'),
                   ('{BILL2}', '{FIRM}', '{CLIENT}', '{VENDOR}', DATE '2026-06-11');
            INSERT INTO purchase_payments
                   (id, firm_id, client_id, vendor_id, payment_no, payment_date, amount_paise)
            VALUES ('{PAYMENT}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'PMT-1',
                    DATE '2026-07-02', 100000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _doc(dsn, *, kind="self_invoice", bill=BILL, payment=None,
         no="RCM-SI/2026-27/001", date="2026-06-10"):
    bill_sql = f"'{bill}'" if bill else "NULL"
    pay_sql = f"'{payment}'" if payment else "NULL"
    return _psql(dsn, f"""
        INSERT INTO rcm_documents
               (firm_id, client_id, vendor_id, kind, purchase_bill_id,
                purchase_payment_id, document_no, document_date)
        VALUES ('{FIRM}', '{CLIENT}', '{VENDOR}', '{kind}', {bill_sql}, {pay_sql},
                '{no}', DATE '{date}');
    """)


# ── the kinds ───────────────────────────────────────────────────────────────

def test_the_kind_check_accepts_exactly_the_engines_vocabulary(db):
    """Compared against the ENGINE's own tuple, not a list spelled here: a
    guard that names two strings passes a WIDENED constraint."""
    from domain.gst import rcm_documents as rd
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.rcm_documents'::regclass
           AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%kind%'
           AND pg_get_constraintdef(oid) NOT LIKE '%purchase_bill_id%';
    """)
    assert definition, "the kind CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(rd.KINDS)


# ── the parent ──────────────────────────────────────────────────────────────

def test_a_self_invoice_hangs_off_a_bill(db):
    assert _doc(db).returncode == 0


def test_a_payment_voucher_hangs_off_a_payment(db):
    assert _doc(db, kind="payment_voucher", bill=None, payment=PAYMENT,
                no="RCM-PV/2026-27/001").returncode == 0


def test_a_document_with_NO_parent_is_refused(db):
    assert _doc(db, bill=None).returncode != 0


def test_a_document_with_BOTH_parents_is_refused(db):
    assert _doc(db, bill=BILL, payment=PAYMENT).returncode != 0


def test_a_voucher_pointing_at_a_bill_is_refused(db):
    """s.31(3)(g) dates the document at the PAYMENT. A voucher hanging off a
    bill would take the wrong date and state tax for a consideration nobody had
    paid yet."""
    assert _doc(db, kind="payment_voucher", bill=BILL).returncode != 0


def test_a_self_invoice_pointing_at_a_payment_is_refused(db):
    assert _doc(db, kind="self_invoice", bill=None, payment=PAYMENT).returncode != 0


# ── one per parent ──────────────────────────────────────────────────────────

def test_one_self_invoice_per_bill(db):
    assert _doc(db).returncode == 0
    assert _doc(db, no="RCM-SI/2026-27/002").returncode != 0, (
        "a second self-invoice for one bill is a duplicate statutory record")


def test_one_payment_voucher_per_payment(db):
    assert _doc(db, kind="payment_voucher", bill=None, payment=PAYMENT,
                no="RCM-PV/2026-27/001").returncode == 0
    assert _doc(db, kind="payment_voucher", bill=None, payment=PAYMENT,
                no="RCM-PV/2026-27/002").returncode != 0


def test_a_soft_deleted_document_frees_its_parent(db):
    """The uniqueness is partial on `deleted_at IS NULL`, so a document issued
    in error can be withdrawn and reissued."""
    assert _doc(db).returncode == 0
    assert _psql(db, "UPDATE rcm_documents SET deleted_at = now();").returncode == 0
    assert _doc(db, no="RCM-SI/2026-27/002").returncode == 0


# ── the number ──────────────────────────────────────────────────────────────

def test_a_number_cannot_repeat_within_one_kind(db):
    assert _doc(db).returncode == 0
    assert _doc(db, bill=BILL2).returncode != 0


def test_the_same_number_MAY_appear_in_the_other_kind(db):
    """Rule 46(b) allows 'one or multiple series' and these are two. Making the
    index kind-blind would make a self-invoice and a voucher collide on numbers
    that belong to different sequences."""
    assert _doc(db, no="RCM/001").returncode == 0
    assert _doc(db, kind="payment_voucher", bill=None, payment=PAYMENT,
                no="RCM/001").returncode == 0


def test_a_blank_number_is_refused(db):
    """CGST Rule 46(b) / 52(b) require a consecutive serial number. A blank one
    is not a number."""
    assert _doc(db, no="   ").returncode != 0


# ── the registration status ─────────────────────────────────────────────────

def test_the_registration_status_has_no_default(db):
    """NULL is the THIRD state and must be what a vendor starts in — a default
    would make every existing vendor assert an answer nobody gave."""
    assert _rows(db, f"""
        SELECT coalesce(gst_registration_status, 'NULL')
          FROM vendors WHERE id = '{VENDOR}';
    """) == ["NULL"]


@pytest.mark.parametrize("value", ["registered", "unregistered"])
def test_both_settled_answers_are_accepted(db, value):
    assert _psql(db, f"""
        UPDATE vendors SET gst_registration_status = '{value}' WHERE id = '{VENDOR}';
    """).returncode == 0


@pytest.mark.parametrize("value", ["unrecorded", "Registered", "yes", ""])
def test_a_value_the_engine_does_not_know_is_refused(db, value):
    """`unrecorded` among them: the third state is the ABSENCE of a value, and
    storing it as a string would make a NULL and an 'unrecorded' two spellings
    of one thing that code then has to test twice."""
    assert _psql(db, f"""
        UPDATE vendors SET gst_registration_status = '{value}' WHERE id = '{VENDOR}';
    """).returncode != 0


# ── access ──────────────────────────────────────────────────────────────────

def test_the_browser_may_read_and_never_write(db):
    grants = _rows(db, """
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_name = 'rcm_documents' AND grantee = 'authenticated'
         ORDER BY privilege_type;
    """)
    assert grants == ["SELECT"], (
        "every write must go through the API so rbac(), the numbering, the "
        "period lock and the s.31(3)(f) refusals all run")


def test_the_table_is_assignment_scoped(db):
    """Migration 084's loop has never run again, so a table created now is
    firm-wide unless it says otherwise — and an Executive would see every
    client's documents."""
    policies = _rows(db, """
        SELECT policyname FROM pg_policies
         WHERE tablename = 'rcm_documents' AND permissive = 'RESTRICTIVE';
    """)
    assert "rcm_documents_assignment_scope" in policies


def test_row_level_security_is_on(db):
    assert _rows(db, """
        SELECT relrowsecurity FROM pg_class WHERE relname = 'rcm_documents';
    """) == ["t"]
