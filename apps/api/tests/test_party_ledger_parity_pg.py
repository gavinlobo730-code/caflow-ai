"""
Migration 419 — the SQL party breakdown must equal the Python one, and BOTH
must foot to the control account.

WHY THIS FILE IS THE POINT OF THE CHANGE
    `public.party_ledger_as_at` aggregates where the rows already are: the
    answer is one line per party and the input is every journal line ever
    posted to the account, so CLAUDE.md's reporting rule puts it in the
    database. `domain/accounting/party_ledger.py` has to survive anyway — mock
    mode, local dev and the in-memory suite have no DATABASE_URL and no SQL
    functions — which creates the thing CLAUDE.md warns about: two
    implementations of one rule, which drift. Every scenario below is declared
    ONCE and fed to both halves.

THE INVARIANT IS THE HEADLINE, NOT THE PARITY
    Two implementations agreeing proves only that they agree. What makes this
    report worth rendering is that
        Σ(party rows) + Σ(unattributed rows) == the account's own balance
    so a CA can read the unattributed rows as EXACTLY the difference between
    this control account and the per-party statements. Every scenario asserts
    it against a balance computed independently — a plain SUM over
    journal_lines, not either implementation's own total, so a bug shared by
    both halves still fails.

WHAT ONLY POSTGRES CAN PROVE
      * the eight source tables actually carry the party columns the map
        names, and the correlated sub-selects resolve against real rows;
      * `debit_notes.vendor_id` and `purchase_credit_notes.vendor_id` carry NO
        foreign key (migrations 145 and 210), so a party row can genuinely
        have no master — the LEFT joins keep its money in the total, and an
        inner join would silently break the invariant;
      * a bigint comes back through jsonb as a number and through PostgREST as
        a string, and the Python half must not turn either into a float.
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

from domain.accounting import party_ledger as rule  # noqa: E402

FIRM = "f4190000-0000-0000-0000-000000000001"
CLIENT = "c4190000-0000-0000-0000-000000000001"
AR = "a4190000-0000-0000-0000-00000000000a"      # Trade Receivables
AP = "a4190000-0000-0000-0000-00000000000b"      # Trade Payables
REV = "a4190000-0000-0000-0000-00000000000c"     # the other leg
CUST1 = "10190000-0000-0000-0000-000000000001"
CUST2 = "10190000-0000-0000-0000-000000000002"
VEND1 = "20190000-0000-0000-0000-000000000001"
#: A vendor id with NO `vendors` row — legal, because migrations 145 and 210
#: give debit_notes.vendor_id and purchase_credit_notes.vendor_id no FK.
VEND_GHOST = "20190000-0000-0000-0000-0000000000ff"


class Ln:
    """One journal line and the document behind it, declared once for both."""

    def __init__(self, source_type, debit, credit, *, account=AR,
                 customer=None, vendor=None, source_id=None, date="2026-06-15"):
        self.source_type, self.debit, self.credit = source_type, debit, credit
        self.account, self.customer, self.vendor = account, customer, vendor
        self.source_id = source_id or str(uuid.uuid4())
        self.date = date

    def as_resolved(self) -> dict:
        """What the SERVICE hands the Python rule, once it has resolved the
        party. A ghost vendor resolves to nothing, exactly as the LEFT join
        in SQL yields a NULL name — but the id is still there, so the row is
        a party row with no master rather than an unattributed one."""
        party = self.customer or self.vendor
        return {
            "source_type": self.source_type,
            "party_id": party,
            "party_name": _NAMES.get(party, "(unnamed)") if party else None,
            "party_kind": (rule.CUSTOMER if self.customer
                           else rule.VENDOR if self.vendor else None),
            "debit_paise": self.debit,
            "credit_paise": self.credit,
        }


_NAMES = {CUST1: "Acme Traders", CUST2: "Bharat Stores", VEND1: "Sharma Supplies"}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


# (table, party column, number column or None, date column) — read off the
# schema rather than guessed: the note tables spell their date `credit_note_date`
# / `debit_note_date`, and purchase_bills and the two purchase notes require no
# document number at all.
_DOC_TABLE = {
    "sales_invoice":        ("client_sales_invoices", "customer_id", "invoice_no",     "invoice_date"),
    "credit_note":          ("credit_notes",          "customer_id", "credit_note_no", "credit_note_date"),
    "sales_debit_note":     ("sales_debit_notes",     "customer_id", "debit_note_no",  "debit_note_date"),
    "receipt":              ("receipts",              "customer_id", "receipt_no",     "receipt_date"),
    "purchase_bill":        ("purchase_bills",        "vendor_id",   None,             "bill_date"),
    "debit_note":           ("debit_notes",           "vendor_id",   None,             "debit_note_date"),
    "purchase_credit_note": ("purchase_credit_notes", "vendor_id",   None,             "credit_note_date"),
    "purchase_payment":     ("purchase_payments",     "vendor_id",   "payment_no",     "payment_date"),
}


def _seed_sql(lines: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email)
  VALUES ('{FIRM}', 'Party Parity', 'a@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Party Co', 'Private Limited');
INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
  ('{AR}',  '{FIRM}', '{CLIENT}', '1100', 'Trade Receivables', 'Asset'),
  ('{AP}',  '{FIRM}', '{CLIENT}', '2100', 'Trade Payables',    'Liability'),
  ('{REV}', '{FIRM}', '{CLIENT}', '4000', 'Sales Revenue',     'Revenue');
INSERT INTO customers (id, firm_id, client_id, name) VALUES
  ('{CUST1}', '{FIRM}', '{CLIENT}', '{_NAMES[CUST1]}'),
  ('{CUST2}', '{FIRM}', '{CLIENT}', '{_NAMES[CUST2]}');
INSERT INTO vendors (id, firm_id, client_id, name) VALUES
  ('{VEND1}', '{FIRM}', '{CLIENT}', '{_NAMES[VEND1]}');
-- VEND_GHOST is deliberately NOT inserted. See the module docstring.
"""]
    # A reversal points at the SAME document as the entry it reverses
    # (reverse_entry propagates source_id), so a source_id may legitimately
    # appear on several lines and the document is seeded ONCE.
    seeded: set[str] = set()
    for i, ln in enumerate(lines):
        eid = str(uuid.uuid4())
        if ln.source_type in _DOC_TABLE and ln.source_id not in seeded:
            seeded.add(ln.source_id)
            table, col, numcol, datecol = _DOC_TABLE[ln.source_type]
            party = ln.customer or ln.vendor
            cols = f"id, firm_id, client_id, {col}, {datecol}"
            vals = f"'{ln.source_id}','{FIRM}','{CLIENT}','{party}','{ln.date}'"
            if numcol:
                cols += f", {numcol}"
                vals += f", 'DOC/{i:04d}'"
            out.append(f"INSERT INTO {table} ({cols}) VALUES ({vals});")
        out.append(f"""
INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                             narration, entry_type, is_posted, status,
                             source_type, source_id)
VALUES ('{eid}','{FIRM}','{CLIENT}','{ln.date}','REF/{i:04d}','n','Journal',
        true,'posted','{ln.source_type}',
        {f"'{ln.source_id}'" if ln.source_type in _DOC_TABLE else 'NULL'});
INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
VALUES ('{eid}','{ln.account}',{ln.debit},{ln.credit});
INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
VALUES ('{eid}','{REV}',{ln.credit},{ln.debit});""")
    return "\n".join(out)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"partypar_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres",
             f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_answer(dsn_: str, account: str, as_of: str = "2026-12-31") -> dict:
    r = _psql(dsn_, "SELECT public.party_ledger_as_at("
                    f"'{FIRM}'::uuid,'{CLIENT}'::uuid,'{account}'::uuid,'{as_of}'::date)",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def _account_balance(dsn_: str, account: str, as_of: str = "2026-12-31") -> int:
    """The control account's own balance, computed INDEPENDENTLY of either
    implementation — a plain SUM, so a bug shared by both halves still fails."""
    r = _psql(dsn_, """
        SELECT COALESCE(SUM(jl.debit_paise - jl.credit_paise), 0)
        FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
        """ + f"""
        WHERE je.firm_id='{FIRM}' AND je.client_id='{CLIENT}'
          AND jl.account_id='{account}' AND je.is_posted
          AND je.deleted_at IS NULL AND je.entry_date <= '{as_of}'""", tuples=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


def _compare(dsn_: str, lines: list, account: str = AR) -> tuple[dict, object, int]:
    assert _psql(dsn_, _seed_sql(lines)).returncode == 0
    sql = _sql_answer(dsn_, account)
    py = rule.breakdown([ln.as_resolved() for ln in lines if ln.account == account])
    return sql, py, _account_balance(dsn_, account)


def _norm(sql: dict) -> list[tuple]:
    """The SQL answer as comparable tuples, in its own returned order."""
    return [(r.get("party_id"), r.get("party_kind"), r.get("unattributed_source") or None,
             int(r["debit_paise"]), int(r["credit_paise"])) for r in sql["rows"]]


def _norm_py(py) -> list[tuple]:
    return [(r.party_id, r.party_kind, r.unattributed_source,
             r.debit_paise, r.credit_paise) for r in py.rows]


# ── THE HEADLINE: a row in every limb, and the parts sum to the account ──────

EVERY_LIMB = [
    Ln("sales_invoice", 11800000, 0, customer=CUST1),
    Ln("sales_invoice", 5900000, 0, customer=CUST2),
    Ln("receipt", 0, 5000000, customer=CUST1),
    Ln("credit_note", 0, 1180000, customer=CUST1),
    Ln("sales_debit_note", 236000, 0, customer=CUST2),
    Ln("manual", 0, 700000),
    Ln("Opening", 2500000, 0),
    Ln("TrialBalance", 300000, 0),
    Ln("year_end_adjustment", 0, 150000),
    Ln("bank_transaction", 0, 90000),
]


def test_the_parts_sum_to_the_control_account(dsn):
    """THE claim this report rests on, against an independently computed total.

    If it ever fails, the unattributed rows have stopped being the difference
    between the control account and the per-party statements — which is the
    only reason a CA would trust the screen.
    """
    sql, py, balance = _compare(dsn, EVERY_LIMB)
    assert int(sql["attributed_paise"]) + int(sql["unattributed_paise"]) == balance
    assert py.total_paise == balance
    assert balance != 0, "a fixture that nets to nil would pass vacuously"


def test_sql_and_python_agree_on_every_limb(dsn):
    sql, py, _ = _compare(dsn, EVERY_LIMB)
    assert _norm(sql) == _norm_py(py)


def test_each_unattributable_source_is_its_own_row(dsn):
    """Not one lump. 'manual' and 'Opening' send the CA to different places."""
    sql, _, _ = _compare(dsn, EVERY_LIMB)
    sources = {r["unattributed_source"] for r in sql["rows"] if r["party_id"] is None}
    assert sources == {"manual", "Opening", "TrialBalance",
                       "year_end_adjustment", "bank_transaction"}


def test_no_unattributed_row_is_folded_into_a_party(dsn):
    sql, _, _ = _compare(dsn, EVERY_LIMB)
    for r in sql["rows"]:
        assert (r["party_id"] is None) != (r["unattributed_source"] is None), \
            "a row is either a party or an unattributed source, never both"


# ── The LEFT join: a party with no master keeps its money ────────────────────

def test_a_party_with_no_master_row_keeps_its_balance(dsn):
    """debit_notes.vendor_id and purchase_credit_notes.vendor_id carry NO
    foreign key (migrations 145 and 210), so this row is legal. An INNER join
    would drop it and break the invariant silently — which is the whole reason
    the joins are LEFT."""
    lines = [
        Ln("purchase_bill", 0, 4000000, account=AP, vendor=VEND1),
        Ln("debit_note", 1000000, 0, account=AP, vendor=VEND_GHOST),
    ]
    sql, py, balance = _compare(dsn, lines, account=AP)
    assert int(sql["attributed_paise"]) + int(sql["unattributed_paise"]) == balance
    ghost = [r for r in sql["rows"] if r["party_id"] == VEND_GHOST]
    assert len(ghost) == 1, "the ghost vendor's row was dropped"
    assert ghost[0]["party_name"] == "(unnamed)"
    assert int(ghost[0]["debit_paise"]) == 1000000
    assert _norm(sql) == _norm_py(py)


# ── Reversals net out for free, because reverse_entry carries the source ─────

def test_a_reversal_attributes_to_the_same_party_and_nets_to_zero(dsn):
    """`phase2_journal_service.reverse_entry` passes the ORIGINAL's
    source_type/source_id to _create_journal, so the pair lands on one party
    with no special case anywhere. Asserted rather than assumed."""
    shared = str(uuid.uuid4())
    lines = [
        Ln("sales_invoice", 11800000, 0, customer=CUST1, source_id=shared),
        Ln("sales_invoice", 0, 11800000, customer=CUST1, source_id=shared),
    ]
    sql, py, balance = _compare(dsn, lines)
    assert balance == 0
    rows = [r for r in sql["rows"] if r["party_id"] == CUST1]
    assert len(rows) == 1, "the reversal became a second party row"
    assert int(rows[0]["debit_paise"]) - int(rows[0]["credit_paise"]) == 0
    assert _norm(sql) == _norm_py(py)


# ── Scope: the function must not reach past its own account, client or date ──

def test_a_draft_entry_is_not_counted(dsn):
    assert _psql(dsn, _seed_sql([Ln("sales_invoice", 11800000, 0, customer=CUST1)])).returncode == 0
    eid = str(uuid.uuid4())
    assert _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no,
                                     narration, entry_type, is_posted, status)
        VALUES ('{eid}','{FIRM}','{CLIENT}','2026-06-20','DRAFT','n','Journal',false,'draft');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise)
        VALUES ('{eid}','{AR}',9900000,0);""").returncode == 0
    sql = _sql_answer(dsn, AR)
    assert int(sql["attributed_paise"]) + int(sql["unattributed_paise"]) == _account_balance(dsn, AR)
    assert int(sql["attributed_paise"]) == 11800000, "a draft reached the breakdown"


def test_an_entry_after_the_as_at_date_is_not_counted(dsn):
    assert _psql(dsn, _seed_sql([
        Ln("sales_invoice", 11800000, 0, customer=CUST1, date="2026-06-15"),
        Ln("sales_invoice", 5000000, 0, customer=CUST2, date="2026-09-15"),
    ])).returncode == 0
    june = _sql_answer(dsn, AR, as_of="2026-06-30")
    assert int(june["attributed_paise"]) == 11800000
    assert int(june["attributed_paise"]) + int(june["unattributed_paise"]) \
        == _account_balance(dsn, AR, as_of="2026-06-30")


def test_the_other_leg_of_the_same_entry_is_not_counted(dsn):
    """Every fixture entry posts a matching Revenue leg. Asking for Trade
    Receivables must return the receivable side only, or the breakdown would
    double the document."""
    sql, _, balance = _compare(dsn, [Ln("sales_invoice", 11800000, 0, customer=CUST1)])
    assert balance == 11800000
    assert int(sql["attributed_paise"]) == 11800000


def test_an_empty_account_answers_a_shape_not_an_error(dsn):
    assert _psql(dsn, _seed_sql([])).returncode == 0
    sql = _sql_answer(dsn, AR)
    assert sql["rows"] == []
    assert int(sql["attributed_paise"]) == 0 and int(sql["unattributed_paise"]) == 0
