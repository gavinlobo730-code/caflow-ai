"""
Migration 356 — the SQL Bank Reconciliation Statement must equal the Python one.

WHY THIS FILE IS THE POINT OF THE CHANGE
    Deciding whether a book entry has been seen by the bank is an anti-join
    against one account's statement lines inside a date window, over rows that
    are proportional to transaction volume — so it belongs in the database
    (CLAUDE.md's reporting rule). That creates the thing the same file warns
    about: two implementations of one rule, which drift.

    They are safe only while something proves they agree. That is this file.
    domain/banking/brs.py stays as the no-database fallback for mock mode and
    local dev; public.bank_reconciling_items is what production runs; and every
    scenario below goes through BOTH and is compared key for key.

FIVE PLACES THE TWO SIDES COULD DIVERGE, EACH WITH A SCENARIO

    1. THE DATE TEST. A cheque entered on 28 March and presented on 5 April is
       linked to a statement line permanently. At 31 March it must STILL be an
       unpresented cheque, because on 31 March the bank had not paid it. A side
       that tested the link without testing the line's date would drop it, and
       every historical BRS would change the moment the next month was imported.

    2. THE TIE-BREAK. Two items share a date, so the id decides the order, and
       the two sides must break it the same way. Note what this scenario does
       NOT prove: a uuid's text is hex digits and hyphens in fixed positions,
       which glibc and C order alike, so it cannot demonstrate a collation
       difference the way the bank register's parity test can with descriptions.
       COLLATE "C" is on the SQL side because Python's compare is by code point
       and the two must not drift if these keys ever stop being uuids. What is
       proved here is that a tie-break exists and that both sides apply it.

    3. LINE VERSUS ENTRY. One entry carries TWO lines on the bank account. They
       must appear as two rows ordered by LINE id — a side keyed on the entry
       would collapse or mis-order them — while the bank-link test still works
       on the entry.

    4. THE NARRATION FALLBACK. The line's own narration where it has one, else
       the entry's, with an EMPTY STRING counting as absent. One line has NULL,
       one has '', one has its own text.

    5. THE CAP. The item lists are capped; the totals are not. A scenario runs
       with a cap of 1 against buckets of 2 and 3, so `listed`, `count` and
       `total_paise` all have to disagree with each other correctly.
"""
from __future__ import annotations

import json
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
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.banking.brs import reconciling_items  # noqa: E402

FIRM = "f3560000-0000-0000-0000-000000000001"
CLIENT = "c3560000-0000-0000-0000-000000000001"
ACCOUNT = "b3560000-0000-0000-0000-000000000001"
GL_BANK = "a3560000-0000-0000-0000-000000000001"
GL_OTHER = "a3560000-0000-0000-0000-000000000002"
STMT = "53560000-0000-0000-0000-000000000001"


def _u(tag: str) -> str:
    """A uuid whose text form sorts by `tag` — so a scenario can choose the
    order two same-dated rows must come out in."""
    return f"{tag}-0000-0000-0000-000000000001"


# (entry suffix, date, reference, entry narration, posted, deleted)
ENTRIES = [
    # (1) Entered 28 March, presented 5 April. Unpresented at 31 March.
    ("e1000000", "2026-03-28", "CHQ 004411", "Rent — March", True, False),
    # Seen by the bank inside the window: not a reconciling item.
    ("e2000000", "2026-03-10", "UTR 99881", "Receipt from Zenith Systems", True, False),
    # (2) Same date as e4, id sorts EARLIER in C collation than e4's.
    ("e3000000", "2026-03-30", None, "Cash deposit — Andheri branch", True, False),
    ("e4000000", "2026-03-30", None, "Cash deposit — Powai branch", True, False),
    # (3) ONE entry, TWO lines on the bank account.
    ("e5000000", "2026-03-15", "CHQ 004412", "Two legs on the bank account", True, False),
    # Excluded: not posted.
    ("e6000000", "2026-03-16", None, "Draft, never posted", False, False),
    # Excluded: soft-deleted.
    ("e7000000", "2026-03-17", None, "Deleted entry", True, True),
    # Excluded: after the as-at date.
    ("e8000000", "2026-04-02", None, "April, out of the window", True, False),
    # (4) The narration fallback, three ways.
    ("e9000000", "2026-03-20", None, "Entry narration wins where the line is NULL",
     True, False),
]

# (line suffix, entry suffix, account, debit, credit, line narration or None)
LINES = [
    ("d1000000", "e1000000", GL_BANK, 0, 1_000_000, None),
    ("d2000000", "e2000000", GL_BANK, 2_000_000, 0, None),
    ("d3000000", "e3000000", GL_BANK, 500_000, 0, None),
    ("d4000000", "e4000000", GL_BANK, 250_000, 0, None),
    # Two legs, same entry, same date — ordered by LINE id.
    ("d5000000", "e5000000", GL_BANK, 0, 300_000, "First leg"),
    ("d6000000", "e5000000", GL_BANK, 0, 400_000, "Second leg"),
    ("d7000000", "e6000000", GL_BANK, 0, 111_111, None),
    ("d8000000", "e7000000", GL_BANK, 0, 222_222, None),
    ("d9000000", "e8000000", GL_BANK, 0, 333_333, None),
    # Same entry, a line on ANOTHER account: never a bank reconciling item.
    ("da000000", "e1000000", GL_OTHER, 1_000_000, 0, None),
    # The narration fallback: '' must fall back exactly as NULL does.
    ("db000000", "e9000000", GL_BANK, 0, 123_456, ""),
]

# (txn suffix, date, description, reference, debit, credit, linked entry or None)
TXNS = [
    ("fa000000", "2026-03-10", "NEFT ZENITH SYSTEMS", "UTR 99881", 0, 2_000_000, "e2000000"),
    # (1) The April line that pays the March cheque. Outside the window.
    ("fd000000", "2026-04-05", "CHQ 004411 PAID", "004411", 1_000_000, 0, "e1000000"),
    # Bank-only: charges and interest.
    ("fc000000", "2026-03-31", "SERVICE CHARGES INCL GST", None, 11_800, 0, None),
    ("ff000000", "2026-03-31", "INTEREST CREDITED", None, 0, 4_275, None),
    # (2) Same date as t3, and the id sorts before it under C.
    ("fb000000", "2026-03-31", "ATM WDL", None, 50_000, 0, None),
]

AS_OF = "2026-03-31"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1"]
    cmd += ["-tAc", sql] if tuples else ["-c", sql]
    return subprocess.run(cmd, capture_output=True, text=True)


def _q(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _seed_sql() -> str:
    parts = [f"""
        INSERT INTO firms (id, name, email)
          VALUES ('{FIRM}', 'BRS Firm', 'brs@test.local');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'BRS Client', 'Private Limited');
        INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type)
          VALUES ('{GL_BANK}', '{FIRM}', '{CLIENT}', '1100', 'Bank — HDFC', 'Asset'),
                 ('{GL_OTHER}', '{FIRM}', '{CLIENT}', '5100', 'Rent', 'Expense');
        INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no, coa_account_id)
          VALUES ('{ACCOUNT}', '{FIRM}', '{CLIENT}', 'HDFC', '000111', '{GL_BANK}');
        INSERT INTO bank_statements (id, firm_id, client_id, bank_name, bank_account_id,
                                     statement_from, statement_to)
          VALUES ('{STMT}', '{FIRM}', '{CLIENT}', 'HDFC', '{ACCOUNT}',
                  '2026-03-01', '2026-04-30');
    """]
    for suffix, date, ref, narration, posted, deleted in ENTRIES:
        parts.append(f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                                     narration, entry_type, is_posted, deleted_at)
          VALUES ('{_u(suffix)}', '{FIRM}', '{CLIENT}', '{date}', {_q(ref)},
                  {_q(narration)}, 'Journal', {str(posted).lower()},
                  {"NOW()" if deleted else "NULL"});""")
    for suffix, entry, account, debit, credit, narration in LINES:
        parts.append(f"""
        INSERT INTO journal_lines (id, journal_entry_id, account_id, debit_paise,
                                   credit_paise, narration)
          VALUES ('{_u(suffix)}', '{_u(entry)}', '{account}', {debit}, {credit},
                  {_q(narration)});""")
    for suffix, date, desc, ref, debit, credit, entry in TXNS:
        parts.append(f"""
        INSERT INTO bank_transactions (id, statement_id, firm_id, client_id,
                                       transaction_date, description, reference_no,
                                       debit_paise, credit_paise, posted_journal_id)
          VALUES ('{_u(suffix)}', '{STMT}', '{FIRM}', '{CLIENT}', '{date}', {_q(desc)},
                  {_q(ref)}, {debit}, {credit},
                  {("'" + _u(entry) + "'") if entry else "NULL"});""")
    return "\n".join(parts)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"brspar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, _seed_sql())
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── The two sides ────────────────────────────────────────────────────────────

def _sql(dsn: str, *, as_of=AS_OF, statement_balance=None, cap=500) -> dict:
    bal = "NULL" if statement_balance is None else str(statement_balance)
    r = _psql(dsn, f"""SELECT public.bank_reconciling_items(
        '{FIRM}', '{CLIENT}', '{ACCOUNT}', '{GL_BANK}', '{as_of}', {bal}, {cap});""",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def _python(dsn: str, *, as_of=AS_OF, statement_balance=None, cap=500) -> dict:
    """The twin, over the rows the service assembles for it (`_brs_rows`)."""
    r = _psql(dsn, f"""
        SELECT COALESCE(json_agg(row_to_json(x)), '[]') FROM (
          SELECT jl.id AS line_id, je.id AS entry_id,
                 to_char(je.entry_date, 'YYYY-MM-DD') AS entry_date,
                 COALESCE(NULLIF(jl.narration, ''), je.narration, '') AS narration,
                 je.reference_no, jl.debit_paise, jl.credit_paise
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
           WHERE je.firm_id = '{FIRM}' AND je.client_id = '{CLIENT}'
             AND je.is_posted AND je.deleted_at IS NULL
             AND je.entry_date <= '{as_of}' AND jl.account_id = '{GL_BANK}') x;""",
              tuples=True)
    assert r.returncode == 0, r.stderr
    book = json.loads(r.stdout.strip())

    r = _psql(dsn, f"""
        SELECT COALESCE(json_agg(row_to_json(y)), '[]') FROM (
          SELECT t.id, to_char(t.transaction_date, 'YYYY-MM-DD') AS transaction_date,
                 COALESCE(t.description, '') AS description, t.reference_no,
                 t.debit_paise, t.credit_paise, t.posted_journal_id
            FROM bank_transactions t JOIN bank_statements s ON s.id = t.statement_id
           WHERE t.firm_id = '{FIRM}' AND s.bank_account_id = '{ACCOUNT}'
             AND t.transaction_date <= '{as_of}') y;""", tuples=True)
    assert r.returncode == 0, r.stderr
    bank = json.loads(r.stdout.strip())

    return reconciling_items(book, bank, as_of=as_of,
                             statement_balance_paise=statement_balance, list_cap=cap)


def _assert_same(sql: dict, py: dict) -> None:
    assert set(sql) == set(py), "the two answers have different keys"
    for key in sorted(sql):
        assert sql[key] == py[key], f"{key}: SQL {sql[key]!r} != Python {py[key]!r}"


# ── Parity, scenario by scenario ─────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {},
    {"statement_balance": 1_942_475},
    {"statement_balance": 0},
    {"statement_balance": -5_000},
    {"cap": 1},
    {"cap": 2},
    {"as_of": "2026-03-15"},
    {"as_of": "2026-04-30"},
    {"as_of": "2026-04-30", "statement_balance": 942_475},
    {"as_of": "2026-01-01"},
    {"as_of": "2026-03-31", "statement_balance": 1_942_475, "cap": 1},
], ids=["plain", "with-balance", "zero-balance", "negative-balance", "cap-1", "cap-2",
        "mid-month", "after-the-cheque-clears", "after-with-balance",
        "before-everything", "balance-and-cap"])
def test_the_two_implementations_agree(db, kw):
    _assert_same(_sql(db, **kw), _python(db, **kw))


# ── And that they agree on the RIGHT answer ──────────────────────────────────

def test_a_cheque_presented_next_month_is_unpresented_this_month(db):
    """Scenario 1, stated as a fact rather than as parity: the two sides could
    agree on a wrong answer."""
    march = _sql(db, as_of="2026-03-31")
    # Date first, then the line id — 15 March's two legs, 20 March, 28 March.
    assert [i["reference_no"] for i in march["unpresented_cheques"]["items"]] \
        == ["CHQ 004412", "CHQ 004412", None, "CHQ 004411"]
    april = _sql(db, as_of="2026-04-30")
    assert "CHQ 004411" not in [i["reference_no"]
                                for i in april["unpresented_cheques"]["items"]]


def test_two_lines_of_one_entry_are_two_rows_in_line_order(db):
    got = [i for i in _sql(db)["unpresented_cheques"]["items"]
           if i["reference_no"] == "CHQ 004412"]
    assert [i["particulars"] for i in got] == ["First leg", "Second leg"]
    assert [i["amount_paise"] for i in got] == [300_000, 400_000]


def test_the_narration_falls_back_from_an_empty_string_too(db):
    got = next(i for i in _sql(db)["unpresented_cheques"]["items"]
               if i["amount_paise"] == 123_456)
    assert got["particulars"] == "Entry narration wins where the line is NULL"


def test_unposted_deleted_and_other_account_lines_are_absent(db):
    everything = json.dumps(_sql(db, as_of="2026-12-31"))
    for absent in ("111111", "222222", "Draft, never posted", "Deleted entry"):
        assert absent not in everything, absent


def test_the_totals_ignore_the_cap(db):
    full = _sql(db)["unpresented_cheques"]
    capped = _sql(db, cap=1)["unpresented_cheques"]
    assert capped["total_paise"] == full["total_paise"]
    assert capped["count"] == full["count"] and capped["listed"] == 1


def test_an_empty_bucket_is_present_with_zeros(db):
    """A missing key is not the same answer as an empty one — the caller would
    read `undefined` where it should read zero."""
    before = _sql(db, as_of="2026-01-01")
    for key in ("unpresented_cheques", "deposits_in_transit",
                "bank_credits_not_in_books", "bank_debits_not_in_books"):
        assert before[key] == {"items": [], "total_paise": 0, "count": 0, "listed": 0}
    assert before["book_balance_paise"] == 0


def test_the_statement_balances_to_the_bank(db):
    """The whole arithmetic, end to end, against a figure worked by hand.

    Book at 31 March: −10,000 (cheque) + 20,000 (receipt) + 5,000 + 2,500
    (deposits) − 3,000 − 4,000 (the two legs) − 1,234.56 = 9,265.44
    Bank at 31 March: +20,000 − 118 + 42.75 − 500 = 19,424.75
    """
    got = _sql(db, statement_balance=1_942_475)
    assert got["book_balance_paise"] == 926_544
    assert got["computed_bank_balance_paise"] == 1_942_475
    assert got["difference_paise"] == 0 and got["agrees"] is True


def test_without_a_stated_balance_it_says_so_rather_than_assuming_zero(db):
    got = _sql(db)
    assert got["statement_balance_paise"] is None
    assert got["agrees"] is None and got["difference_paise"] is None
    assert "nothing has confirmed" in got["gap"]
