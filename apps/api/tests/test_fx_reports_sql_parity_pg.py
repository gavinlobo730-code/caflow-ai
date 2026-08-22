"""
Migration 281 — the SQL FX reads must equal the Python ones, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    Moving two FX reads into the database is what makes them cheap:
    fx_foreign_bank_balances replaces a per-account reconciliation that fetched
    every posted entry (12,838 on the live client) plus every line for the
    account, and fx_dated_adjustments replaces a {entry_id: entry_date} dict over
    all of them, built twice.

    It also creates the thing CLAUDE.md warns about — two implementations of one
    rule, which drift. They are safe only while something proves they agree, and
    that is this file. The Python survives because mock mode and local dev have
    no DATABASE_URL and no SQL functions; production runs the SQL; every scenario
    below goes through BOTH and is compared.

HOW BOTH HALVES RUN OVER ONE FIXTURE
    fx_reporting_service takes a Supabase-shaped `db`. _SqlRpcDB below is that
    shape with exactly one thing swapped: .rpc() executes the real function in
    Postgres, while table reads still come from the FakeDB holding the identical
    rows. So a report can be run with only its SQL half substituted, and any
    difference in the output is the function's, not the fixture's.

    The Python side needs no substitution — FakeDB.rpc() raises on an unknown
    function, which is precisely the production fallback path, so calling the
    service with a plain FakeDB exercises the Python implementation as written.

WHAT IS COMPARED
    The reports' own output, not the functions' raw rows: realized_fx,
    exchange_rate_audit and open_foreign_balances, whole. A function that
    returned defensible-looking rows the report then mis-read would pass a
    narrower test.
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

from services.fx_reporting_service import fx_reporting_service as FXR  # noqa: E402
from tests.e2e_harness import FakeDB, _apply_generated                 # noqa: E402

FIRM = "f8100000-0000-0000-0000-000000000001"
CLIENT = "c8100000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c8100000-0000-0000-0000-000000000002"
COA_USD = "a8100000-0000-0000-0000-000000000001"
COA_EUR = "a8100000-0000-0000-0000-000000000002"
COA_INR = "a8100000-0000-0000-0000-000000000003"
BANK_USD = "b8100000-0000-0000-0000-000000000001"
BANK_EUR = "b8100000-0000-0000-0000-000000000002"
BANK_INR = "b8100000-0000-0000-0000-000000000003"

START, END = "2026-04-01", "2027-03-31"


# ── fixture construction ─────────────────────────────────────────────────────

def _entry(eid: str, when: str, posted: bool = True, deleted: bool = False,
           client: str = CLIENT) -> dict:
    return {"id": eid, "firm_id": FIRM, "client_id": client, "entry_date": when,
            "reference_no": f"REF-{eid[:8]}", "narration": "n", "entry_type": "Journal",
            "is_posted": posted, "status": "posted" if posted else "draft",
            "deleted_at": "2026-05-01T00:00:00+00:00" if deleted else None}


def _line(eid: str, account: str, dr: int, cr: int, currency: str = "USD",
          txn_dr=None, txn_cr=None) -> dict:
    return {"id": str(uuid.uuid4()), "journal_entry_id": eid, "account_id": account,
            "debit_paise": dr, "credit_paise": cr, "txn_currency": currency,
            "base_currency": "INR", "exchange_rate": "83.5", "rate_type": "booking",
            "txn_debit": txn_dr, "txn_credit": txn_cr}


def _bank(bid: str, name: str, currency: str, coa) -> dict:
    return {"id": bid, "firm_id": FIRM, "client_id": CLIENT, "bank_name": name,
            "account_no": f"AC-{name}", "account_type": "Current", "currency": currency,
            "coa_account_id": coa, "opening_balance_paise": 0, "is_active": True}


def _adj(aid: str, kind: str, currency: str, delta: int, entry_id, created: str,
         doc_type: str = "receipt", client: str = CLIENT) -> dict:
    # Rates as FLOATS, not strings: a numeric column reaches the service as a
    # JSON number through PostgREST, which json.loads makes a float, and the
    # reports render it with str(). A fixture holding "84.0000" would compare the
    # SQL path against a Python path that never runs in production, and the first
    # thing this file found was exactly that — str(84.0) is "84.0".
    return {"id": aid, "firm_id": FIRM, "client_id": client, "kind": kind,
            "document_type": doc_type, "document_id": str(uuid.uuid4()),
            "currency": currency, "original_rate": 83.0, "settlement_rate": 84.0,
            "closing_rate": None, "base_delta_paise": delta,
            "journal_entry_id": entry_id, "rate_source": "settlement",
            "created_at": created, "created_by": None}


def _u(i: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fxparity.entry.{i}"))


def _scenarios() -> list[tuple[str, dict]]:
    """Every scenario is a whole store: what the tables hold. Each one isolates a
    rule the Python applied in memory and the SQL now applies in the query."""
    out: list[tuple[str, dict]] = []

    def store(entries=(), lines=(), banks=(), adjustments=()):
        return {"journal_entries": list(entries), "journal_lines": list(lines),
                "bank_accounts": list(banks), "fx_adjustments": list(adjustments),
                "client_sales_invoices": [], "purchase_bills": []}

    # 1. Nothing at all. The empty case is where a jsonb_agg over no rows returns
    #    NULL instead of [] if COALESCE is forgotten.
    out.append(("empty", store()))

    # 2. One USD bank with a plain receipt and payment.
    e1, e2 = _u(1), _u(2)
    out.append(("usd_bank_two_movements", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 0, 250_500, "USD", 0, 3_000)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 3. A base-INR revaluation overlay posted back onto the SAME account. It is
    #    stamped txn_currency='INR', and counting it would drift the reported
    #    foreign holding away from the booked value.
    e3 = _u(3)
    out.append(("inr_overlay_on_the_foreign_account", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e3, "2027-03-31")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e3, COA_USD, 15_000, 0, "INR", None, None)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 4. An UNPOSTED entry must not move the balance.
    out.append(("unposted_entry_excluded", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01", posted=False)],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 835_000, 0, "USD", 10_000, 0)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 5. A SOFT-DELETED entry must not move it either.
    out.append(("deleted_entry_excluded", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01", deleted=True)],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 835_000, 0, "USD", 10_000, 0)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 6. Another client's entry on the same account. Tenancy, in the function.
    out.append(("other_clients_entry_excluded", store(
        entries=[_entry(e1, "2026-05-01"),
                 _entry(e2, "2026-06-01", client=OTHER_CLIENT)],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 835_000, 0, "USD", 10_000, 0)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 7. NULL txn_debit/txn_credit on a foreign line. Python read these as
    #    `int(x or 0)`; SQL's NULL arithmetic would drop the whole line from the
    #    sum unless every term is COALESCEd separately.
    out.append(("null_txn_amounts", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 100_000, 0, "USD", None, None)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 8. An INR bank and a foreign bank with no chart account: neither is an open
    #    foreign balance, for different reasons.
    out.append(("inr_bank_and_unmapped_bank", store(
        entries=[_entry(e1, "2026-05-01")],
        lines=[_line(e1, COA_INR, 835_000, 0, "INR", None, None)],
        banks=[_bank(BANK_INR, "SBI", "INR", COA_INR),
               _bank(BANK_EUR, "Unmapped EUR", "EUR", None)])))

    # 9. A foreign account whose movements net to zero is not an open balance.
    out.append(("nets_to_zero", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 0, 835_000, "USD", 0, 10_000)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)])))

    # 10. Two foreign banks in different currencies.
    out.append(("two_currencies", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_EUR, 900_000, 0, "EUR", 9_500, 0)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD),
               _bank(BANK_EUR, "HSBC EUR", "EUR", COA_EUR)])))

    # 11. Adjustments dated by their entry's POSTING date, not by created_at.
    #     The created_at here sits in the previous financial year on purpose.
    a1, a2 = _u(101), _u(102)
    out.append(("adjustments_dated_by_settlement", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-12-15")],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2025-01-01T00:00:00+00:00"),
                     _adj(a2, "realized", "USD", -20_000, e2, "2025-01-01T00:00:00+00:00")])))

    # 12. An adjustment whose entry is unposted falls back to its own timestamp,
    #     which is what the Python's `entry_dates.get(...) or created_at` did.
    out.append(("adjustment_falls_back_to_created_at", store(
        entries=[_entry(e1, "2026-05-01", posted=False)],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2026-09-09T10:30:00+00:00")])))

    # 13. An adjustment with no journal entry at all.
    out.append(("adjustment_with_no_entry", store(
        adjustments=[_adj(a1, "realized", "USD", 50_000, None, "2026-09-09T10:30:00+00:00")])))

    # 14. Both window edges, inclusive, and one entry outside each.
    e4, e5, e6, e7 = _u(4), _u(5), _u(6), _u(7)
    out.append(("window_edges", store(
        entries=[_entry(e4, "2026-03-31"), _entry(e5, START),
                 _entry(e6, END), _entry(e7, "2027-04-01")],
        adjustments=[_adj(_u(104), "realized", "USD", 1_000, e4, "2026-03-31T00:00:00+00:00"),
                     _adj(_u(105), "realized", "USD", 2_000, e5, "2026-04-01T00:00:00+00:00"),
                     _adj(_u(106), "realized", "USD", 4_000, e6, "2027-03-31T00:00:00+00:00"),
                     _adj(_u(107), "realized", "USD", 8_000, e7, "2027-04-01T00:00:00+00:00")])))

    # 15. Mixed kinds — realized_fx must see only its own, the rate audit both.
    out.append(("mixed_kinds", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2026-05-01T00:00:00+00:00"),
                     _adj(a2, "unrealized", "USD", -7_000, e2, "2026-06-01T00:00:00+00:00")])))

    # 16. Another client's adjustment, on this firm.
    out.append(("other_clients_adjustment_excluded", store(
        entries=[_entry(e1, "2026-05-01"),
                 _entry(e2, "2026-06-01", client=OTHER_CLIENT)],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2026-05-01T00:00:00+00:00"),
                     _adj(a2, "realized", "USD", 99_000, e2, "2026-06-01T00:00:00+00:00",
                          client=OTHER_CLIENT)])))

    # 17. Gains and losses in two currencies, so the by_currency split is real.
    out.append(("gains_and_losses_two_currencies", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01"), _entry(e3, "2026-07-01")],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2026-05-01T00:00:00+00:00"),
                     _adj(a2, "realized", "USD", -20_000, e2, "2026-06-01T00:00:00+00:00"),
                     _adj(_u(103), "realized", "EUR", -5_000, e3, "2026-07-01T00:00:00+00:00")])))

    # 18. Banks and adjustments together — the shape a real client has.
    out.append(("banks_and_adjustments_together", store(
        entries=[_entry(e1, "2026-05-01"), _entry(e2, "2026-06-01")],
        lines=[_line(e1, COA_USD, 835_000, 0, "USD", 10_000, 0),
               _line(e2, COA_USD, 0, 250_500, "USD", 0, 3_000)],
        banks=[_bank(BANK_USD, "HSBC USD", "USD", COA_USD)],
        adjustments=[_adj(a1, "realized", "USD", 50_000, e1, "2026-05-01T00:00:00+00:00"),
                     _adj(a2, "unrealized", "USD", -7_000, e2, "2026-06-01T00:00:00+00:00")])))

    return out


SCENARIOS = _scenarios()


# ── the two databases ────────────────────────────────────────────────────────

def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _insert(table: str, row: dict, columns: list[str]) -> str:
    cols = ", ".join(columns)
    vals = ", ".join(_q(row.get(c)) for c in columns)
    return f"INSERT INTO {table} ({cols}) VALUES ({vals});"


def _seed_sql(store: dict) -> str:
    clients = {CLIENT, OTHER_CLIENT}
    out = [f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'FX Parity', 'fx@parity.in');"]
    for c in sorted(clients):
        out.append("INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES "
                   f"('{c}', '{FIRM}', 'FX Co {c[:8]}', 'Proprietorship');")
    for coa, code, name in ((COA_USD, "1010", "Bank — USD"),
                            (COA_EUR, "1011", "Bank — EUR"),
                            (COA_INR, "1000", "Bank — INR")):
        out.append("INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, "
                   "account_name, account_type, account_subtype, system_account_key) VALUES ("
                   f"'{coa}', '{FIRM}', '{CLIENT}', '{code}', '{name}', 'Asset', 'Bank', NULL);")
    for e in store["journal_entries"]:
        out.append(_insert("journal_entries", e, [
            "id", "firm_id", "client_id", "entry_date", "reference_no", "narration",
            "entry_type", "is_posted", "status", "deleted_at"]))
    for l in store["journal_lines"]:
        out.append(_insert("journal_lines", l, [
            "id", "journal_entry_id", "account_id", "debit_paise", "credit_paise",
            "txn_currency", "base_currency", "exchange_rate", "rate_type",
            "txn_debit", "txn_credit"]))
    for b in store["bank_accounts"]:
        out.append(_insert("bank_accounts", b, [
            "id", "firm_id", "client_id", "bank_name", "account_no", "account_type",
            "currency", "coa_account_id", "opening_balance_paise", "is_active"]))
    for a in store["fx_adjustments"]:
        out.append(_insert("fx_adjustments", a, [
            "id", "firm_id", "client_id", "kind", "document_type", "document_id",
            "currency", "original_rate", "settlement_rate", "closing_rate",
            "base_delta_paise", "journal_entry_id", "rate_source", "created_at",
            "created_by"]))
    return "\n".join(out)


class _PgRpc:
    """One .rpc() call, executed as the real function in Postgres."""

    _SIG = {
        "fx_foreign_bank_balances": ["p_firm", "p_client"],
        "fx_dated_adjustments": ["p_firm", "p_client", "p_start", "p_end", "p_kind"],
    }
    _CAST = {"p_firm": "uuid", "p_client": "uuid", "p_start": "date",
             "p_end": "date", "p_kind": "text"}

    def __init__(self, dsn: str, fn: str, params: dict):
        self.dsn, self.fn, self.params = dsn, fn, params

    def execute(self):
        args = ", ".join(
            f"{name} => {_q(self.params.get(name))}::{self._CAST[name]}"
            for name in self._SIG[self.fn]
        )
        r = _psql(self.dsn, f"SELECT public.{self.fn}({args});", tuples=True)
        assert r.returncode == 0, f"{self.fn} failed: {r.stderr}"
        return type("R", (), {"data": json.loads(r.stdout.strip())})()


class _SqlRpcDB:
    """Supabase-shaped, with exactly one thing swapped: .rpc() runs the real
    function in Postgres. Table reads still come from the FakeDB holding the
    identical rows, so any difference in a report's output is the function's."""

    def __init__(self, fake: FakeDB, dsn: str):
        self._fake, self._dsn = fake, dsn

    def table(self, name):
        return self._fake.table(name)

    def rpc(self, fn: str, params=None):
        return _PgRpc(self._dsn, fn, params or {})


def _fake_db(store: dict) -> FakeDB:
    db = FakeDB()
    for name, rows in store.items():
        _apply_generated(name, rows)
    db._tables.update({k: [dict(r) for r in v] for k, v in store.items()})
    return db


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"fxpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _both(dsn: str, store: dict):
    """(python_db, sql_db) over one fixture, seeded into both."""
    seed = _psql(dsn, _seed_sql(store))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"
    fake = _fake_db(store)
    return fake, _SqlRpcDB(_fake_db(store), dsn)


def _sorted_banks(rows: list[dict]) -> list[dict]:
    return sorted(({k: r[k] for k in sorted(r)} for r in rows),
                  key=lambda r: (str(r.get("name")), str(r.get("id"))))


# ── the parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,store", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_foreign_bank_balances_sql_matches_python(db, name, store):
    py_db, sql_db = _both(db, store)
    assert _sorted_banks(FXR._foreign_bank_balances(sql_db, FIRM, CLIENT)) == \
           _sorted_banks(FXR._foreign_bank_balances(py_db, FIRM, CLIENT)), name


@pytest.mark.parametrize("name,store", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_realized_fx_sql_matches_python(db, name, store):
    py_db, sql_db = _both(db, store)
    assert FXR.realized_fx(sql_db, FIRM, CLIENT, START, END) == \
           FXR.realized_fx(py_db, FIRM, CLIENT, START, END), name


@pytest.mark.parametrize("name,store", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_rate_audit_sql_matches_python(db, name, store):
    py_db, sql_db = _both(db, store)
    assert FXR.exchange_rate_audit(sql_db, FIRM, CLIENT, START, END) == \
           FXR.exchange_rate_audit(py_db, FIRM, CLIENT, START, END), name


@pytest.mark.parametrize("name,store", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_open_foreign_balances_sql_matches_python(db, name, store):
    """open_foreign_balances routes only its BANK half through the function; the
    receivable and payable halves are ordinary filtered queries. Comparing the
    whole report checks the function's rows survive assembly unchanged."""
    py_db, sql_db = _both(db, store)
    a = FXR.open_foreign_balances(sql_db, FIRM, CLIENT, as_of=END)
    b = FXR.open_foreign_balances(py_db, FIRM, CLIENT, as_of=END)
    a["bank_accounts"] = _sorted_banks(a["bank_accounts"])
    b["bank_accounts"] = _sorted_banks(b["bank_accounts"])
    assert a == b, name


@pytest.mark.parametrize("name,store", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_currency_exposure_sql_matches_python(db, name, store):
    py_db, sql_db = _both(db, store)
    assert FXR.currency_exposure(sql_db, FIRM, CLIENT, as_of=END) == \
           FXR.currency_exposure(py_db, FIRM, CLIENT, as_of=END), name


def test_the_sql_half_is_actually_being_exercised(db):
    """The guard on the four tests above. Every one of them would also pass if
    _SqlRpcDB quietly fell back to the Python — a broken function, an unusable
    fixture, a typo in the rpc name — and would then prove nothing at all. This
    asserts the function really ran and really returned the balance."""
    store = dict(SCENARIOS[1][1])
    _, sql_db = _both(db, store)
    rows = sql_db.rpc("fx_foreign_bank_balances",
                      {"p_firm": FIRM, "p_client": CLIENT}).execute().data
    assert rows and rows[0]["foreign_balance_minor"] == 7_000, rows
    assert rows[0]["base_balance_paise"] == 584_500, rows
