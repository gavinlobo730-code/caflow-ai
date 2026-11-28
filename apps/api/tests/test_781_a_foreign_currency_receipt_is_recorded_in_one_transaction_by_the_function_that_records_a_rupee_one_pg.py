"""Migration 781, proved against real PostgreSQL: a receipt in a foreign currency is recorded in ONE transaction, by the function that
records a rupee one, and a rupee receipt is stored exactly as it was (ledger POST-A-095).

WHAT WAS WRONG
    A rupee receipt posts its entry, its row and every invoice it settles in one database transaction (`settle_receipt_atomic`). A
    receipt in a foreign currency did not: the API posted the entry, inserted the receipt, updated each invoice with a compare-and-set,
    wrote the allocations and then the record of the realised exchange difference, each a separate statement, and compensated on a
    failure. Under a real race an earlier invoice's paid amount stayed when a later one failed.

WHAT THIS HOLDS
    * THE CASE: one call stores the entry (with the rate provenance the posting kernel stamps), its lines in both currencies, the
      receipt with its eight currency columns, each allocation in both amounts, each invoice's two paid amounts and its status by the
      FOREIGN total, and the record of the realised difference tied to the entry; the returned JSON says the same.
    * ALL OR NOTHING: a refusal at the LAST invoice of several leaves nothing of the receipt (no entry, no receipt, no allocation, no
      realised-difference record, the first invoice untouched). The refusals are each tried: an invoice that no longer reads as the
      caller read it (paid, foreign paid or credited), the function's own state RC001 and never 40001, which PostgREST re-runs by
      itself; an allocation that does not say what was read, and two rows for one invoice that say different things (their own
      words, NOT that state, so a caller never answers them by sending the same thing again); an invoice in another currency; more
      foreign money than is outstanding; no foreign amount.
    * A REAL RACE, AT THE DATABASE: two psql sessions record a receipt against the same invoice from the same read (under two numbers,
      which the API's own two receipts would not have: there the second is refused for the duplicate number first and takes the next
      one). The second waits on the first's row lock, then is refused whole with RC001; one receipt, one entry and one settlement
      exist afterwards. Nothing here goes through PostgREST.
    * A RUPEE RECEIPT IS UNCHANGED BUT FOR ITS LINES' ORDER: the same rupee call through this function and through the function 781
      replaced stores the same receipt, entry, lines, allocation and invoice, column for column, except `journal_lines.line_order`,
      which 781 records (0, 1, ...) and the earlier body left empty; a rupee receipt that carries a realised-difference key writes no
      such record.
    * THE PERSON: the invoice's settlement by a foreign receipt is in the edit log under the person the call carried.
    * THE FUNCTION'S ATTRIBUTES are the previous function's (SECURITY DEFINER, its search path, not executable by a signed-in or
      anonymous role, executable by the service role), the rollback restores migration 574's body exactly, and both files run twice.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_S781 = "781_a_foreign_currency_receipt_is_recorded_in_one_transaction_by_the_function_that_records_a_rupee_one"
F781, R781 = MIGRATIONS / f"{_S781}.sql", MIGRATIONS / f"{_S781}_rollback.sql"
F574 = MIGRATIONS / "574_a_receipt_recorded_through_the_database_function_keeps_its_id_its_bank_account_and_its_advance_fields.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the foreign-receipt proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AR_ACC, FX_ACC = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
USER, AUTH = str(uuid.uuid4()), str(uuid.uuid4())
INV_USD, INV_USD_2, INV_EUR, INV_INR = (str(uuid.uuid4()) for _ in range(4))
FUNCTION = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"
MOVED = "changed while this receipt was being prepared"


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    # VERBOSITY=verbose puts the SQLSTATE in the error line, which is how a refusal's code is read here
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _json(dsn: str, sql: str):
    return json.loads(_scalar(dsn, sql))


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _seed(dsn: str) -> None:
    """One client that bills in dollars: two USD invoices of 1,000.00 booked at 80 (8,00,000.00 rupees each), one EUR, one rupee."""
    sql = f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','781 Firm','f781@test.in');
    INSERT INTO auth.users (id, email) VALUES ('{AUTH}','p781@test.in');
    INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES ('{USER}','{FIRM}','{AUTH}','A Partner','p781@test.in','Partner');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','781 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}','{FIRM}','{CLIENT}','781 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset'),
      ('{FX_ACC}','{FIRM}','{CLIENT}','FX-1','Foreign Exchange Gain or Loss','Revenue');
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise,
                                       txn_currency, exchange_rate, txn_total, paid_txn)
    VALUES ('{INV_USD}','{FIRM}','{CLIENT}','{CUSTOMER}','USD-1','2026-04-01',8000000,'issued',0,0,'USD',80,100000,0),
           ('{INV_USD_2}','{FIRM}','{CLIENT}','{CUSTOMER}','USD-2','2026-04-01',8000000,'issued',0,0,'USD',80,100000,0),
           ('{INV_EUR}','{FIRM}','{CLIENT}','{CUSTOMER}','EUR-1','2026-04-01',9000000,'issued',0,0,'EUR',90,100000,0);
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES ('{INV_INR}','{FIRM}','{CLIENT}','{CUSTOMER}','INR-1','2026-04-01',100000,'issued',0,0);
    """
    r = _run(dsn, sql)
    assert r.returncode == 0, r.stderr


def _foreign(receipt_no: str, foreign: int, rate: str, allocations: list[dict], *, relieved: int | None = None, currency: str = "USD",
             actor: bool = False) -> dict:
    """The call the API makes for a receipt of `foreign` minor units at `rate`. `allocations` are the function's own rows; `relieved` is
    the rupees of receivable they relieve in all (their sum by default)."""
    cash = int(foreign * float(rate))
    relieved = sum(a["allocated_paise"] for a in allocations) if relieved is None else relieved
    settled_foreign = sum(a.get("allocated_txn", 0) for a in allocations)
    unallocated = int((foreign - settled_foreign) * float(rate))
    fx = (cash - unallocated) - relieved
    receipt = {
        "id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "receipt_no": receipt_no,
        "receipt_date": "2026-04-05", "amount_paise": cash, "tds_paise": 0, "unallocated_paise": unallocated, "payment_mode": "bank",
        "reference_no": f"SWIFT-{receipt_no}", "notes": "", "created_at": "2026-04-05T10:30:00+00:00",
        "txn_currency": currency, "exchange_rate": rate, "txn_amount": foreign, "rate_source": "manual-override", "rate_type": "booking",
        "rate_date": "2026-04-05", "rate_selected_by": USER, "rate_overridden": True,
    }
    if fx:
        receipt["fx_adjustment"] = {"settlement_rate": rate, "base_delta_paise": fx, "rate_source": "manual-override", "created_by": USER}
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": receipt_no, "narration": "Receipt (foreign)",
             "entry_type": "Receipt", "is_posted": True, "status": "posted", "posted_by": USER, "created_by": USER,
             "source_type": "receipt", "source_id": receipt["id"], "rate_overridden": True, "rate_selected_by": USER,
             "rate_selected_at": "2026-04-05T10:30:00+00:00"}
    if actor:
        entry["audit_actor"] = AUTH
    both = {"txn_currency": currency, "base_currency": "INR", "exchange_rate": rate, "rate_source": "manual-override", "rate_type": "booking",
            "rate_date": "2026-04-05"}
    lines = [
        {"account_id": BANK_ACC, "debit_paise": cash, "credit_paise": 0, "narration": "Bank receipt (foreign)", "txn_debit": foreign, "txn_credit": 0, **both},
        {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": relieved + unallocated, "narration": "Trade receivable settled at booked rate",
         "txn_debit": 0, "txn_credit": foreign, **both},
    ]
    if fx:
        lines.append({"account_id": FX_ACC, "debit_paise": max(-fx, 0), "credit_paise": max(fx, 0), "narration": "Realized FX", "txn_debit": 0,
                      "txn_credit": 0, **both})
    return {"receipt": receipt, "entry": entry, "lines": lines, "allocs": allocations}


def _alloc(invoice: str, foreign: int, rupees: int, *, paid: int | None = 0, paid_txn: int | None = 0, credited: int | None = 0) -> dict:
    row = {"sales_invoice_id": invoice, "allocated_paise": rupees, "allocated_txn": foreign}
    for key, value in (("expect_paid_paise", paid), ("expect_paid_txn", paid_txn), ("expect_credited_paise", credited)):
        if value is not None:
            row[key] = value
    return row


def _rupee(receipt_no: str, amount: int, allocated: int, extra: dict | None = None) -> dict:
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "receipt_no": receipt_no,
               "receipt_date": "2026-04-05", "amount_paise": amount, "tds_paise": 0, "unallocated_paise": amount - allocated,
               "payment_mode": "upi", "reference_no": "UTR-1", "notes": "a note", "created_at": "2026-04-05T10:30:00+00:00", **(extra or {})}
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": receipt_no, "narration": "Receipt",
             "entry_type": "Receipt", "is_posted": True, "status": "posted", "posted_by": USER, "created_by": USER,
             "source_type": "receipt", "source_id": receipt["id"]}
    lines = [{"account_id": BANK_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "bank", "rate_type": "booking", "rate_date": "2026-04-05"},
             {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount, "narration": "ar", "rate_type": "booking", "rate_date": "2026-04-05"}]
    return {"receipt": receipt, "entry": entry, "lines": lines, "allocs": [{"sales_invoice_id": INV_INR, "allocated_paise": allocated}]}


def _call_sql(p: dict) -> str:
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    return (f"SELECT public.settle_receipt_atomic('{j(p['receipt'])}'::jsonb,'{j(p['entry'])}'::jsonb,"
            f"'{j(p['lines'])}'::jsonb,'{j(p['allocs'])}'::jsonb)::text;")


def _settle(dsn: str, p: dict, *, scalar: bool = False) -> subprocess.CompletedProcess:
    """The call the API makes: the guarded wrapper, as the database owner (the server's own client has no signed-in person)."""
    return _run(dsn, _call_sql(p), scalar=scalar)


def _counts(dsn: str) -> dict:
    return _json(dsn, "SELECT json_build_object('entries', (SELECT count(*) FROM journal_entries), 'lines', (SELECT count(*) FROM journal_lines), "
                      "'receipts', (SELECT count(*) FROM receipts), 'allocations', (SELECT count(*) FROM receipt_allocations), "
                      "'fx', (SELECT count(*) FROM fx_adjustments))::text;")


def _invoice(dsn: str, invoice: str) -> dict:
    return _json(dsn, f"SELECT json_build_object('status', status, 'paid_paise', paid_paise, 'paid_txn', paid_txn)::text FROM client_sales_invoices WHERE id = '{invoice}';")


def _body_md5(dsn: str) -> str:
    return _scalar(dsn, f"SELECT md5(prosrc) FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t781_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("781_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the case ──────────────────────────────────────────────────────────────────────────

def test_a_foreign_receipt_is_stored_whole_by_one_call(db):
    """1,000.00 USD received at 83 against an invoice booked at 80: 83,00,000 paise into the bank, 80,00,000 off the receivable, a gain
    of 3,00,000."""
    p = _foreign("F-781-1", 100000, "83", [_alloc(INV_USD, 100000, 8000000)])
    r = _settle(db, p, scalar=True)
    assert r.returncode == 0, r.stderr
    returned = json.loads(r.stdout)
    receipt = _json(db, "SELECT row_to_json(r)::text FROM receipts r WHERE receipt_no = 'F-781-1';")
    assert receipt["id"] == p["receipt"]["id"] == returned["receipt_id"]
    assert (receipt["txn_currency"], float(receipt["exchange_rate"]), receipt["txn_amount"], receipt["rate_source"], receipt["rate_type"],
            receipt["rate_date"], receipt["rate_selected_by"], receipt["rate_overridden"]) == \
        ("USD", 83.0, 100000, "manual-override", "booking", "2026-04-05", USER, True)
    assert (receipt["amount_paise"], receipt["unallocated_paise"], receipt["allocated_paise"]) == (8300000, 0, 8000000)

    entry = _json(db, f"SELECT row_to_json(j)::text FROM journal_entries j WHERE id = '{receipt['journal_entry_id']}';")
    assert (entry["source_type"], entry["source_id"], entry["reference_no"], entry["status"]) == ("receipt", receipt["id"], "F-781-1", "posted")
    assert (entry["rate_overridden"], entry["rate_selected_by"]) == (True, USER) and entry["rate_selected_at"].startswith("2026-04-05T10:30:00")
    # in the order the lines were sent (`line_order`, which this function records since 781): bank, receivable, the difference
    lines = _json(db, "SELECT json_agg(json_build_object('account', account_id::text, 'dr', debit_paise, 'cr', credit_paise, 'ccy', btrim(txn_currency), "
                      "'base', btrim(base_currency), 'rate', exchange_rate::float8, 'tdr', txn_debit, 'tcr', txn_credit, 'src', rate_source, 'type', rate_type, "
                      f"'day', rate_date::text) ORDER BY line_order)::text FROM journal_lines WHERE journal_entry_id = '{entry['id']}';")
    assert _scalar(db, f"SELECT string_agg(line_order::text, ',' ORDER BY line_order) FROM journal_lines WHERE journal_entry_id = '{entry['id']}';") == "0,1,2"
    common = {"ccy": "USD", "base": "INR", "rate": 83.0, "src": "manual-override", "type": "booking", "day": "2026-04-05"}
    assert lines == [
        {"account": BANK_ACC, "dr": 8300000, "cr": 0, "tdr": 100000, "tcr": 0, **common},
        {"account": AR_ACC, "dr": 0, "cr": 8000000, "tdr": 0, "tcr": 100000, **common},
        {"account": FX_ACC, "dr": 0, "cr": 300000, "tdr": 0, "tcr": 0, **common},
    ]

    allocation = _json(db, f"SELECT row_to_json(a)::text FROM receipt_allocations a WHERE receipt_id = '{receipt['id']}';")
    assert (allocation["sales_invoice_id"], allocation["allocated_paise"], allocation["allocated_txn"]) == (INV_USD, 8000000, 100000)
    assert _invoice(db, INV_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}

    fx = _json(db, f"SELECT row_to_json(f)::text FROM fx_adjustments f WHERE document_id = '{receipt['id']}';")
    assert (fx["firm_id"], fx["client_id"], fx["kind"], fx["document_type"], fx["currency"], float(fx["settlement_rate"]), fx["base_delta_paise"],
            fx["journal_entry_id"], fx["rate_source"], fx["created_by"]) == \
        (FIRM, CLIENT, "realized", "receipt", "USD", 83.0, 300000, entry["id"], "manual-override", USER)

    assert returned["journal_entry_id"] == entry["id"] and returned["realized_fx_paise"] == 300000
    assert returned["allocations"] == [{"sales_invoice_id": INV_USD, "allocated_paise": 8000000, "allocated_txn": 100000,
                                        "new_paid_paise": 8000000, "new_paid_txn": 100000, "new_status": "paid"}]
    assert "fx_adjustment" not in returned["receipt"]


def test_a_part_settlement_is_judged_by_the_foreign_total_and_a_second_receipt_clears_it(db):
    """400.00 USD at 79 (a loss), then the remaining 600.00 at 80: the invoice is part paid until its FOREIGN total is met."""
    first = _foreign("F-781-2A", 40000, "79", [_alloc(INV_USD, 40000, 3200000)])
    assert _settle(db, first).returncode == 0
    assert _invoice(db, INV_USD) == {"status": "partially_paid", "paid_paise": 3200000, "paid_txn": 40000}
    assert _scalar(db, f"SELECT base_delta_paise FROM fx_adjustments WHERE document_id = '{first['receipt']['id']}';") == "-40000"
    second = _foreign("F-781-2B", 60000, "80", [_alloc(INV_USD, 60000, 4800000, paid=3200000, paid_txn=40000)])
    assert _settle(db, second).returncode == 0
    assert _invoice(db, INV_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}
    # no difference at the booked rate: no record of one
    assert _scalar(db, f"SELECT count(*) FROM fx_adjustments WHERE document_id = '{second['receipt']['id']}';") == "0"


def test_an_overpayment_leaves_the_excess_unallocated_at_the_receipts_rate(db):
    p = _foreign("F-781-3", 120000, "83", [_alloc(INV_USD, 100000, 8000000)])
    assert _settle(db, p).returncode == 0
    receipt = _json(db, "SELECT row_to_json(r)::text FROM receipts r WHERE receipt_no = 'F-781-3';")
    assert (receipt["amount_paise"], receipt["unallocated_paise"], receipt["allocated_paise"], receipt["txn_amount"]) == (9960000, 1660000, 8000000, 120000)
    assert _invoice(db, INV_USD)["status"] == "paid"


def test_two_rows_for_one_invoice_are_one_settlement_in_both_amounts(db):
    p = _foreign("F-781-4", 100000, "80", [_alloc(INV_USD, 30000, 2400000), _alloc(INV_USD, 70000, 5600000)])
    assert _settle(db, p).returncode == 0
    rows = _json(db, f"SELECT json_agg(json_build_object('paise', allocated_paise, 'txn', allocated_txn))::text FROM receipt_allocations WHERE receipt_id = '{p['receipt']['id']}';")
    assert rows == [{"paise": 8000000, "txn": 100000}]
    assert _invoice(db, INV_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}


# ── all or nothing ────────────────────────────────────────────────────────────────────

def _refused(db, p: dict, words: str, *, code: str | None = None) -> None:
    before, usd, usd2 = _counts(db), _invoice(db, INV_USD), _invoice(db, INV_USD_2)
    r = _settle(db, p)
    assert r.returncode != 0 and words in r.stderr, r.stderr
    if code:
        assert f"ERROR:  {code}:" in r.stderr, r.stderr
    else:
        assert "ERROR:  RC001:" not in r.stderr and "ERROR:  40001:" not in r.stderr, r.stderr
    assert _counts(db) == before, "a refused receipt left something behind"
    assert (_invoice(db, INV_USD), _invoice(db, INV_USD_2)) == (usd, usd2), "a refused receipt moved an invoice"


def test_a_refusal_at_the_second_invoice_leaves_nothing_of_the_receipt_not_even_the_first_invoices_settlement(db):
    """The defect itself: two invoices, the second one moved since it was read. Before, the first invoice kept its paid amount."""
    _run(db, f"UPDATE client_sales_invoices SET paid_paise = 800000, paid_txn = 10000, status = 'partially_paid' WHERE id = '{INV_USD_2}';")
    p = _foreign("F-781-5", 200000, "83", [_alloc(INV_USD, 100000, 8000000), _alloc(INV_USD_2, 100000, 8000000)])
    _refused(db, p, MOVED, code="RC001")


@pytest.mark.parametrize("change", ["paid_paise = 100", "paid_txn = 1", "credited_paise = 100"])
def test_an_invoice_that_no_longer_reads_as_the_caller_read_it_refuses_the_receipt_with_its_own_state(db, change):
    _run(db, f"UPDATE client_sales_invoices SET {change} WHERE id = '{INV_USD}';")
    _refused(db, _foreign("F-781-6", 40000, "83", [_alloc(INV_USD, 40000, 3200000)]), MOVED, code="RC001")


def test_an_allocation_that_does_not_say_what_was_read_is_refused_in_its_own_words_and_not_as_a_changed_invoice(db):
    _refused(db, _foreign("F-781-7", 40000, "83", [_alloc(INV_USD, 40000, 3200000, paid=None, paid_txn=None, credited=None)]),
             "does not say what was read of the invoice")


def test_two_rows_for_one_invoice_that_say_different_things_about_what_was_read_are_refused(db):
    """Several rows for one invoice are one settlement. With the least of their readings taken, a row that read the invoice rightly
    would carry a row that did not."""
    _refused(db, _foreign("F-781-7B", 100000, "80", [_alloc(INV_USD, 30000, 2400000), _alloc(INV_USD, 70000, 5600000, paid=999, paid_txn=7, credited=5)]),
             "do not agree about what was read")


def test_an_invoice_in_another_currency_is_refused(db):
    _refused(db, _foreign("F-781-8", 40000, "83", [_alloc(INV_EUR, 40000, 3600000)]), "is billed in EUR")


def test_more_foreign_money_than_is_outstanding_is_refused(db):
    """The rupees fit (the receipt relieves less than is owed) and the foreign amount does not: 1,000.01 USD against 1,000.00."""
    _refused(db, _foreign("F-781-9", 100001, "83", [_alloc(INV_USD, 100001, 7999999)]), "exceeds its outstanding")


def test_an_allocation_with_rupees_and_no_foreign_amount_is_refused(db):
    _refused(db, _foreign("F-781-10", 40000, "83", [{"sales_invoice_id": INV_USD, "allocated_paise": 3200000, "expect_paid_paise": 0, "expect_paid_txn": 0}],
                          relieved=3200000), "names no foreign amount")


def test_two_receipts_racing_for_one_invoice_from_the_same_read_record_one_and_refuse_the_other_whole(db):
    """A real race. The first session records its receipt and holds its transaction open; the second, built from the same read of the
    invoice, waits on the row lock, then finds the invoice moved and is refused. Nothing of the second exists afterwards."""
    first = _foreign("F-781-R1", 60000, "83", [_alloc(INV_USD, 60000, 4800000)])
    second = _foreign("F-781-R2", 60000, "84", [_alloc(INV_USD, 60000, 4800000)])
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                               f"BEGIN; {_call_sql(first)} SELECT pg_sleep(3); COMMIT;"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:      # wait until the first session holds the invoice's row lock
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'client_sales_invoices' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        started = time.time()
        r = _settle(db, second)
        waited = time.time() - started
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    assert r.returncode != 0 and MOVED in r.stderr and "ERROR:  RC001:" in r.stderr, r.stderr
    assert waited > 1.0, f"the second receipt did not wait for the first's lock ({waited:.2f}s): the race was not exercised"
    assert _invoice(db, INV_USD) == {"status": "partially_paid", "paid_paise": 4800000, "paid_txn": 60000}
    assert _counts(db) == {"entries": 1, "lines": 3, "receipts": 1, "allocations": 1, "fx": 1}
    assert _scalar(db, "SELECT string_agg(receipt_no, ',') FROM receipts;") == "F-781-R1"


# ── a rupee receipt is unchanged ──────────────────────────────────────────────────────

def _stored(dsn: str, receipt_no: str) -> dict:
    """Everything a receipt wrote, with the identities that differ between two receipts taken out."""
    return _json(dsn, f"""
        SELECT json_build_object(
          'receipt', to_jsonb(r) - 'id' - 'receipt_no' - 'journal_entry_id' - 'updated_at',
          'entry', to_jsonb(j) - 'id' - 'reference_no' - 'source_id' - 'created_at' - 'updated_at' - 'entry_number',
          'lines', (SELECT jsonb_agg(to_jsonb(l) - 'id' - 'journal_entry_id' - 'created_at' - 'line_order' ORDER BY l.debit_paise DESC) FROM journal_lines l WHERE l.journal_entry_id = j.id),
          'line_order', (SELECT jsonb_agg(l.line_order ORDER BY l.debit_paise DESC) FROM journal_lines l WHERE l.journal_entry_id = j.id),
          'allocations', (SELECT jsonb_agg(to_jsonb(a) - 'id' - 'receipt_id' - 'created_at') FROM receipt_allocations a WHERE a.receipt_id = r.id)
        )::text FROM receipts r JOIN journal_entries j ON j.id = r.journal_entry_id WHERE r.receipt_no = '{receipt_no}';""")


def test_a_rupee_receipt_is_stored_exactly_as_the_function_781_replaced_stored_it(db):
    """The same rupee call through this function and through migration 574's (the rollback), column for column."""
    assert _settle(db, _rupee("R-781-NEW", 60000, 40000)).returncode == 0
    new, invoice_new = _stored(db, "R-781-NEW"), _invoice(db, INV_INR)
    _run(db, f"UPDATE client_sales_invoices SET paid_paise = 0, status = 'issued' WHERE id = '{INV_INR}';")
    assert _file(db, R781).returncode == 0
    assert _settle(db, _rupee("R-781-OLD", 60000, 40000)).returncode == 0
    old = _stored(db, "R-781-OLD")
    # the one difference: 781 records each line's place in the array, the body it replaced left it empty
    assert (new.pop("line_order"), old.pop("line_order")) == ([0, 1], [None, None])
    assert new == old, "a rupee receipt is stored differently by the function of migration 781"
    assert invoice_new == _invoice(db, INV_INR) == {"status": "partially_paid", "paid_paise": 40000, "paid_txn": 0}
    assert (new["receipt"]["txn_currency"].strip(), float(new["receipt"]["exchange_rate"]), new["receipt"]["txn_amount"],
            new["receipt"]["rate_overridden"], new["entry"]["rate_overridden"], new["entry"]["rate_selected_by"]) == ("INR", 1.0, None, False, False, None)


def test_a_rupee_receipt_that_carries_a_realised_difference_writes_no_record_of_one_and_needs_no_reading(db):
    p = _rupee("R-781-FX", 60000, 40000, {"fx_adjustment": {"settlement_rate": "83", "base_delta_paise": 500, "created_by": USER}})
    r = _settle(db, p, scalar=True)
    assert r.returncode == 0, r.stderr
    assert _counts(db)["fx"] == 0 and json.loads(r.stdout)["realized_fx_paise"] == 0


# ── the person ────────────────────────────────────────────────────────────────────────

def test_the_invoices_settlement_by_a_foreign_receipt_is_in_the_edit_log_under_the_person_the_call_carried(db):
    p = _foreign("F-781-A", 100000, "83", [_alloc(INV_USD, 100000, 8000000)], actor=True)
    assert _settle(db, p).returncode == 0
    rows = _json(db, "SELECT coalesce(json_agg(json_build_object('entity', entity_type, 'action', action, 'actor', actor_id::text, 'email', actor_email, "
                     "'paid_txn', new_data->>'paid_txn')), '[]'::json)::text FROM audit_log "
                     f"WHERE entity_id = '{INV_USD}' AND action ILIKE 'update%';")
    assert rows and all(row["actor"] == AUTH and row["email"] == "p781@test.in" for row in rows), rows
    assert any(row["paid_txn"] == "100000" for row in rows), rows


# ── the function's attributes, and the two files ──────────────────────────────────────

def test_the_function_keeps_its_attributes_and_who_may_execute_it(db):
    row = _json(db, f"""SELECT json_build_object('definer', p.prosecdef, 'config', p.proconfig, 'lang', l.lanname,
        'auth', has_function_privilege('authenticated', p.oid, 'EXECUTE'), 'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
        'service', has_function_privilege('service_role', p.oid, 'EXECUTE'))::text
        FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang WHERE p.oid = '{FUNCTION}'::regprocedure;""")
    assert row == {"definer": True, "config": ["search_path=public, pg_catalog"], "lang": "plpgsql", "auth": False, "anon": False, "service": True}
    wrapper = "public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)"
    row = _json(db, f"""SELECT json_build_object('auth', has_function_privilege('authenticated', '{wrapper}'::regprocedure, 'EXECUTE'),
        'anon', has_function_privilege('anon', '{wrapper}'::regprocedure, 'EXECUTE'),
        'service', has_function_privilege('service_role', '{wrapper}'::regprocedure, 'EXECUTE'))::text;""")
    assert row == {"auth": False, "anon": False, "service": True}


def test_the_rollback_restores_migration_574s_body_and_both_files_run_twice(db):
    after_781 = _body_md5(db)
    assert _file(db, F781).returncode == 0 and _body_md5(db) == after_781, "running 781 again changed the function"
    assert _file(db, R781).returncode == 0
    rolled_back = _body_md5(db)
    assert rolled_back != after_781
    assert _file(db, F574).returncode == 0 and _body_md5(db) == rolled_back, "the rollback does not hold the body migration 574 defines"
    assert _file(db, R781).returncode == 0 and _body_md5(db) == rolled_back
    # the function before 781 stores no foreign receipt: the same foreign call loses its currency (the negative control)
    p = _foreign("F-781-OLD", 100000, "83", [_alloc(INV_USD, 100000, 8000000)])
    assert _settle(db, p).returncode == 0
    receipt = _json(db, "SELECT row_to_json(r)::text FROM receipts r WHERE receipt_no = 'F-781-OLD';")
    assert receipt["txn_currency"].strip() == "INR" and _invoice(db, INV_USD)["paid_txn"] == 0 and _counts(db)["fx"] == 0
    assert _file(db, F781).returncode == 0 and _body_md5(db) == after_781
