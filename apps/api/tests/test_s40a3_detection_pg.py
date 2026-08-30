"""§40A(3) auto-detection reads the side of the ledger money LEAVES by.

WHY THIS FILE EXISTS
    The shipped detector (migration 156) selected `jl.debit_paise` on cash
    accounts. In double entry a cash PAYMENT credits cash; debiting cash is
    money coming IN. So it returned the client's cash RECEIPTS and called them
    disallowable payments, and the client's real cash payments were never
    surfaced at all.

    Both halves matter and both are tested here. The fabricated add-backs
    would overstate tax if a CA accepted them; the silence on real payments is
    worse, because a clean run reads as a clean bill of health on the very
    exposure the tool exists to find.

WHY A REAL DATABASE
    The bug is one word in a SQL function. A double can prove the function was
    called; only Postgres can prove which column it reads.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="§40A(3) SQL proof requires HARNESS_PG + psql",
)

FIRM = "f8000000-0000-0000-0000-000000000001"
CLIENT = "c8000000-0000-0000-0000-000000000001"
LIMIT = 1_000_000  # ₹10,000 in paise — §40A(3)

CASH = "a8000000-0000-0000-0000-00000000cash".replace("cash", "0001")
RENT = "a8000000-0000-0000-0000-000000000002"
FREIGHT = "a8000000-0000-0000-0000-000000000003"
SALES = "a8000000-0000-0000-0000-000000000004"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA", "-F", "|"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"s40a3_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _seed(dsn: str) -> None:
    """One ledger carrying every case the rule turns on."""
    sql = f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'S40A3', 's@s40a3.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Cash Heavy Traders', 'Proprietorship');

INSERT INTO chart_of_accounts
  (id, firm_id, client_id, account_code, account_name, account_type, account_subtype)
VALUES
  ('{CASH}',    '{FIRM}', '{CLIENT}', '1010', 'Cash in Hand',  'Asset',   'Cash'),
  ('{RENT}',    '{FIRM}', '{CLIENT}', '5010', 'Godown Rent',   'Expense', 'Operating Expense'),
  ('{FREIGHT}', '{FIRM}', '{CLIENT}', '5020', 'Freight',       'Expense', 'Operating Expense'),
  ('{SALES}',   '{FIRM}', '{CLIENT}', '4010', 'Cash Sales',    'Revenue', 'Sales');
"""
    entries = [
        # (id, date, narration, [(account, debit, credit), ...])
        # A single cash payment over the limit — the case that must be caught.
        ("e1", "2026-05-04", "Rent paid in cash",
         [(RENT, 1_500_000, 0), (CASH, 0, 1_500_000)]),
        # A cash RECEIPT far over the limit. §40A(3) is about expenditure, so
        # this must never appear — it is what the broken version returned.
        ("e2", "2026-05-05", "Cash sales banked",
         [(CASH, 9_000_000, 0), (SALES, 0, 9_000_000)]),
        # Three payments to one account on one day: ₹4,000 each, none over the
        # limit alone, ₹12,000 in aggregate. The per-line test missed these.
        ("e3", "2026-06-10", "Freight lorry 1", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        ("e4", "2026-06-10", "Freight lorry 2", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        ("e5", "2026-06-10", "Freight lorry 3", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        # The same three amounts spread across different days stay under the
        # limit on each day and must NOT be reported.
        ("e6", "2026-07-01", "Freight later 1", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        ("e7", "2026-07-02", "Freight later 2", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        ("e8", "2026-07-03", "Freight later 3", [(FREIGHT, 400_000, 0), (CASH, 0, 400_000)]),
        # Exactly at the limit — §40A(3) bites where the payment EXCEEDS
        # ₹10,000, so ₹10,000 on the nose is not caught.
        ("e9", "2026-08-01", "Rent exactly at limit",
         [(RENT, 1_000_000, 0), (CASH, 0, 1_000_000)]),
    ]
    parts = [sql]
    for eid, date, narr, lines in entries:
        euid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"s40a3.{eid}"))
        parts.append(
            "INSERT INTO journal_entries (id, firm_id, client_id, entry_date, "
            "reference_no, narration, entry_type, is_posted) VALUES ("
            f"'{euid}', '{FIRM}', '{CLIENT}', '{date}', '{eid}', "
            f"'{narr}', 'Payment', true);"
        )
        for acct, dr, cr in lines:
            parts.append(
                "INSERT INTO journal_lines (journal_entry_id, account_id, "
                f"debit_paise, credit_paise) VALUES ('{euid}', '{acct}', {dr}, {cr});"
            )
    r = _psql(dsn, "\n".join(parts))
    assert r.returncode == 0, f"seed failed: {r.stderr}"


def _detect(dsn: str) -> list[dict]:
    r = _psql(dsn, f"""
        SELECT amount_paise, entry_date, counterparty_account, entry_count
          FROM public.get_cash_payments_above_threshold(
                 '{FIRM}'::uuid, '{CLIENT}'::uuid, {LIMIT}::bigint)
         ORDER BY entry_date;
    """, tuples=True)
    assert r.returncode == 0, f"detection failed: {r.stderr}"
    rows = []
    for line in r.stdout.strip().splitlines():
        if not line.strip():
            continue
        amount, date, account, count = line.split("|")
        rows.append({"amount_paise": int(amount), "entry_date": date,
                     "account": account, "count": int(count)})
    return rows


def test_a_cash_payment_over_the_limit_is_found(db):
    """The single thing the tool is for, and the thing it never did."""
    _seed(db)
    rows = _detect(db)
    rent = [r for r in rows if r["account"] == "Godown Rent"]
    assert len(rent) == 1, f"the ₹15,000 cash rent payment must be found, got {rows}"
    assert rent[0]["amount_paise"] == 1_500_000
    assert rent[0]["entry_date"] == "2026-05-04"


def test_a_cash_receipt_is_never_reported_as_a_payment(db):
    """The fabrication half of the bug.

    ₹90,000 of cash SALES is money coming in. §40A(3) disallows expenditure;
    a receipt is not expenditure and can never be disallowed under it. The
    broken version returned exactly this row."""
    _seed(db)
    rows = _detect(db)
    assert not any(r["account"] == "Cash Sales" for r in rows), (
        "a cash receipt is being reported as a disallowable payment — the "
        "detector is reading the debit side of the cash account again"
    )
    assert not any(r["amount_paise"] == 9_000_000 for r in rows)


def test_payments_to_one_account_on_one_day_aggregate(db):
    """Finance Act 2008: the limit applies to the aggregate paid to a person
    in a day, not to each voucher. Three ₹4,000 freight payments on one date
    are ₹12,000 and disallowable; the per-line test found none of them."""
    _seed(db)
    rows = _detect(db)
    june = [r for r in rows if r["entry_date"] == "2026-06-10"]
    assert len(june) == 1, f"the day's freight payments must aggregate: {rows}"
    assert june[0]["amount_paise"] == 1_200_000
    assert june[0]["count"] == 3
    assert june[0]["account"] == "Freight"


def test_the_same_payments_on_different_days_do_not_aggregate(db):
    """The other side of that rule — aggregating across days would invent a
    disallowance the Act does not create."""
    _seed(db)
    rows = _detect(db)
    july = [r for r in rows if r["entry_date"].startswith("2026-07")]
    assert july == [], (
        f"₹4,000 on each of three separate days is under the limit every day; "
        f"got {july}"
    )


def test_a_payment_exactly_at_the_limit_is_not_caught(db):
    """§40A(3) bites where the payment EXCEEDS ₹10,000."""
    _seed(db)
    rows = _detect(db)
    assert not any(r["entry_date"] == "2026-08-01" for r in rows), (
        "₹10,000 exactly does not exceed ₹10,000"
    )


def test_another_firms_ledger_is_out_of_reach(db):
    """The function is SECURITY DEFINER, so its own scoping is the only
    control on it."""
    _seed(db)
    other = str(uuid.uuid4())
    r = _psql(db, f"""
        SELECT count(*) FROM public.get_cash_payments_above_threshold(
            '{other}'::uuid, '{CLIENT}'::uuid, {LIMIT}::bigint);
    """, tuples=True)
    assert r.returncode == 0
    assert r.stdout.strip() == "0"
