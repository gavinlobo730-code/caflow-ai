"""Migration 784, proved against real PostgreSQL: a payment to a supplier is recorded in ONE transaction, in each of its four shapes
(one bill or several, rupees or a foreign currency) (ledger POST-A-575, the database half; POST-A-580).

WHAT IS WRONG TODAY
    The API reserves the bill or posts the entry first, then inserts the payment, then moves each bill with a compare-and-set, then
    writes the allocations and the record of the realised exchange difference, each a separate statement, and compensates on a
    failure. Under a real race an earlier bill's paid amount stays when a later one fails. Nothing calls this function yet: the
    service change follows it, and this file is the proof of the function alone.

WHAT THIS HOLDS
    * THE FOUR SHAPES: a rupee payment across several bills (the entry with its lines in order, the payment row with the tax withheld
      on its unallocated part, an allocation row per bill, each bill's paid amount and status); a rupee payment that names its bill
      on its own row (the older shape: the bill moves, no allocation row); the same two in a foreign currency, with the bill's
      foreign paid amount, its status judged by the FOREIGN total and the record of the realised difference tied to the entry.
    * THE PAYMENT ROW IS THE PAYLOAD'S: a column the caller names is stored, one it leaves out takes the table's default, and a
      key that is no column fails the whole call and stores nothing.
    * ALL OR NOTHING: a refusal at the LAST bill of several leaves nothing (no entry, no payment, no allocation, no exchange record,
      the first bill untouched). Each refusal is tried: a bill that no longer reads as the caller read it (paid, foreign paid or
      debited), with the function's own state VP001 and never 40001, which the gateway re-runs by itself; an allocation that does
      not say what was read, and rows for one bill that say different things; another currency; more than is outstanding in either
      amount; no foreign amount; a rupee payment against a foreign bill; another supplier's bill; a draft or a cancelled bill; a
      bill of another client; and, for the older shape, a settlement of another bill, of nothing, or of less than the whole payment.
    * A REAL RACE, AT THE DATABASE: two psql sessions pay the same bill from the same read, dated in different months so that the
      bill is the only row they share. The second waits on the first's row lock, then is refused whole (VP001 for a foreign payment,
      what is left for a rupee one); one payment, one entry and one settlement exist afterwards. The same race with the lock taken
      out of the function stores both payments (the negative control). The lock is FOR NO KEY UPDATE: a key share held on the bill
      does not make a payment wait, which is what keeps two payments that name one bill from deadlocking. Nothing here goes
      through the gateway.
    * WHAT THE FUNCTION CHECKS OF THE CALLER'S ARITHMETIC: a rupee payment's unallocated figure adds up, a payment is not recorded
      as reversed, no allocation relieves a negative amount, and a foreign payment that names its bill relieves it of the cash
      paid plus the exchange difference.
    * THE DOOR: the payment and its journal must name one firm and one client, the client must be the firm's, a date in a closed
      year (the firm's locked year, the client's finalised one) is refused in the closure's own sentence, and a date that cannot be
      read is refused. The bill's settlement is in the edit log under the person the call carried.
    * THE FUNCTIONS' ATTRIBUTES (SECURITY DEFINER, the search path, executable by the service role and by nobody signed in or
      anonymous), and the two files: the rollback drops both functions, and each file runs twice.

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

F784 = MIGRATIONS / "784_a_supplier_payment_is_recorded_in_one_transaction.sql"
R784 = MIGRATIONS / "784_a_supplier_payment_is_recorded_in_one_transaction_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the supplier-payment proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, OTHER_CLIENT, OTHER_FIRM = (str(uuid.uuid4()) for _ in range(4))
VENDOR, OTHER_VENDOR = str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AP_ACC, FX_ACC, TDS_ACC = (str(uuid.uuid4()) for _ in range(4))
USER, AUTH = str(uuid.uuid4()), str(uuid.uuid4())
B_INR, B_INR_2, B_USD, B_USD_2, B_EUR, B_OTHER_VENDOR, B_DRAFT, B_CANCELLED, B_OTHER_CLIENT = (str(uuid.uuid4()) for _ in range(9))
WRAPPER = "public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb)"
BODY = "public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"
MOVED = "changed while this payment was being prepared"
WATCHED = (B_INR, B_INR_2, B_USD, B_USD_2)


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
    """One client with a supplier it owes in rupees (1,000.00 and 500.00), in dollars (two bills of 1,000.00 USD booked at 80) and in
    euros, a bill from another supplier, a draft, a cancelled bill, and a bill of another client of the firm."""
    sql = f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','784 Firm','f784@test.in'), ('{OTHER_FIRM}','784 Other Firm','o784@test.in');
    INSERT INTO auth.users (id, email) VALUES ('{AUTH}','p784@test.in');
    INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES ('{USER}','{FIRM}','{AUTH}','A Partner','p784@test.in','Partner');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','784 Client','Private Limited'),
                                                                     ('{OTHER_CLIENT}','{FIRM}','784 Other Client','Private Limited');
    INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}','{FIRM}','{CLIENT}','784 Supplier'),
                                                              ('{OTHER_VENDOR}','{FIRM}','{CLIENT}','784 Another Supplier');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AP_ACC}','{FIRM}','{CLIENT}','AP-1','Trade Payables','Liability'),
      ('{TDS_ACC}','{FIRM}','{CLIENT}','TDS-1','TDS Payable','Liability'),
      ('{FX_ACC}','{FIRM}','{CLIENT}','FX-1','Foreign Exchange Gain or Loss','Revenue');
    INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, total_paise, net_payable_paise, status) VALUES
      ('{B_INR}','{FIRM}','{CLIENT}','{VENDOR}','INR-1','2026-04-01',100000,100000,'received'),
      ('{B_INR_2}','{FIRM}','{CLIENT}','{VENDOR}','INR-2','2026-04-01',50000,50000,'received'),
      ('{B_OTHER_VENDOR}','{FIRM}','{CLIENT}','{OTHER_VENDOR}','OV-1','2026-04-01',100000,100000,'received'),
      ('{B_DRAFT}','{FIRM}','{CLIENT}','{VENDOR}','DR-1','2026-04-01',100000,100000,'draft'),
      ('{B_CANCELLED}','{FIRM}','{CLIENT}','{VENDOR}','CX-1','2026-04-01',100000,100000,'cancelled');
    INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, total_paise, net_payable_paise, status,
                                txn_currency, exchange_rate, txn_net_payable, paid_txn) VALUES
      ('{B_USD}','{FIRM}','{CLIENT}','{VENDOR}','USD-1','2026-04-01',8000000,8000000,'received','USD',80,100000,0),
      ('{B_USD_2}','{FIRM}','{CLIENT}','{VENDOR}','USD-2','2026-04-01',8000000,8000000,'received','USD',80,100000,0),
      ('{B_EUR}','{FIRM}','{CLIENT}','{VENDOR}','EUR-1','2026-04-01',9000000,9000000,'received','EUR',90,100000,0);
    """
    r = _run(dsn, sql)
    assert r.returncode == 0, r.stderr
    other_vendor = str(uuid.uuid4())
    r = _run(dsn, f"""INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{other_vendor}','{FIRM}','{OTHER_CLIENT}','Elsewhere');
                      INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, total_paise, net_payable_paise, status)
                      VALUES ('{B_OTHER_CLIENT}','{FIRM}','{OTHER_CLIENT}','{other_vendor}','OC-1','2026-04-01',100000,100000,'received');""")
    assert r.returncode == 0, r.stderr


def _entry(payment: dict, *, actor: bool = False, foreign: bool = False) -> dict:
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": payment["payment_date"], "reference_no": payment["payment_no"],
             "narration": f"Vendor payment {payment['payment_no']}", "entry_type": "Payment", "is_posted": True, "status": "posted",
             "posted_at": "2026-04-05T10:30:00+00:00", "posted_by": USER, "created_by": USER, "source_type": "purchase_payment",
             "source_id": payment["id"]}
    if foreign:
        entry.update({"rate_overridden": True, "rate_selected_by": USER, "rate_selected_at": "2026-04-05T10:30:00+00:00"})
    if actor:
        entry["audit_actor"] = AUTH
    return entry


def _rupee(payment_no: str, amount: int, allocations: list[dict], *, single: str | None = None, tds: int = 0, extra: dict | None = None,
           actor: bool = False, day: str = "2026-04-05") -> dict:
    """The call the API will make for a rupee payment. `single` names the bill on the payment's own row (the older shape)."""
    allocated = sum(a["allocated_paise"] for a in allocations)
    payment = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": VENDOR, "purchase_bill_id": single,
               "payment_no": payment_no, "payment_date": day, "amount_paise": amount, "payment_mode": "neft",
               "unallocated_paise": 0 if single else amount - allocated, "reference_no": "UTR-784", "notes": "a note",
               "created_at": "2026-04-05T10:30:00+00:00", "updated_at": "2026-04-05T10:30:00+00:00", **(extra or {})}
    if tds:
        payment.update({"tds_paise": tds, "tds_base_paise": amount - allocated, "tds_section": "194C", "tds_rate_bps": 200,
                        "tds_basis": "advance"})
    lines = [{"account_id": AP_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "Trade payable cleared", "rate_type": "booking",
              "rate_date": day, "rate_source": "identity"},
             {"account_id": BANK_ACC, "debit_paise": 0, "credit_paise": amount - tds, "narration": "Bank payment to vendor", "rate_type": "booking",
              "rate_date": day, "rate_source": "identity"}]
    if tds:
        lines.append({"account_id": TDS_ACC, "debit_paise": 0, "credit_paise": tds, "narration": "TDS payable on advance", "rate_type": "booking",
                      "rate_date": day, "rate_source": "identity"})
    return {"payment": payment, "entry": _entry(payment, actor=actor), "lines": lines, "allocs": allocations}


def _foreign(payment_no: str, foreign: int, rate: str, allocations: list[dict], *, single: str | None = None, currency: str = "USD",
             actor: bool = False, day: str = "2026-04-05") -> dict:
    """The call the API will make for a payment of `foreign` minor units at `rate`: the bills are relieved at THEIR booked rate (the
    rupees each allocation names), the cash leaves at the payment's rate, and the difference is the realised gain or loss."""
    cash = int(foreign * float(rate))
    relieved = sum(a["allocated_paise"] for a in allocations)
    settled_foreign = sum(a.get("allocated_txn", 0) for a in allocations)
    unallocated = int((foreign - settled_foreign) * float(rate))
    fx = relieved + unallocated - cash          # + a gain (fewer rupees left than the payable relieved), - a loss
    payment = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": VENDOR, "purchase_bill_id": single,
               "payment_no": payment_no, "payment_date": day, "amount_paise": cash, "payment_mode": "bank",
               "reference_no": f"SWIFT-{payment_no}", "notes": None, "created_at": "2026-04-05T10:30:00+00:00",
               "updated_at": "2026-04-05T10:30:00+00:00", "txn_currency": currency, "exchange_rate": rate, "txn_amount": foreign,
               "rate_source": "manual-override", "rate_type": "booking", "rate_date": day, "rate_selected_by": USER,
               "rate_overridden": True}
    if not single:
        payment["unallocated_paise"] = unallocated
    if fx:
        payment["fx_adjustment"] = {"settlement_rate": rate, "base_delta_paise": fx, "rate_source": "manual-override", "created_by": USER}
    both = {"txn_currency": currency, "base_currency": "INR", "exchange_rate": rate, "rate_source": "manual-override", "rate_type": "booking",
            "rate_date": day}
    lines = [
        {"account_id": AP_ACC, "debit_paise": relieved + unallocated, "credit_paise": 0, "narration": "Trade payable settled at booked rate",
         "txn_debit": foreign, "txn_credit": 0, **both},
        {"account_id": BANK_ACC, "debit_paise": 0, "credit_paise": cash, "narration": "Bank payment (foreign)", "txn_debit": 0,
         "txn_credit": foreign, **both},
    ]
    if fx:
        lines.append({"account_id": FX_ACC, "debit_paise": max(-fx, 0), "credit_paise": max(fx, 0), "narration": "Realized FX", "txn_debit": 0,
                      "txn_credit": 0, **both})
    return {"payment": payment, "entry": _entry(payment, actor=actor, foreign=True), "lines": lines, "allocs": allocations}


def _alloc(bill: str, rupees: int, foreign: int | None = None, *, paid: int | None = 0, paid_txn: int | None = 0, debited: int | None = None) -> dict:
    row = {"purchase_bill_id": bill, "allocated_paise": rupees}
    if foreign is not None:
        row["allocated_txn"] = foreign
        for key, value in (("expect_paid_paise", paid), ("expect_paid_txn", paid_txn), ("expect_debited_paise", debited)):
            if value is not None:
                row[key] = value
    return row


def _call_sql(p: dict, function: str = "public.settle_payment_atomic") -> str:
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    return (f"SELECT {function}('{j(p['payment'])}'::jsonb,'{j(p['entry'])}'::jsonb,"
            f"'{j(p['lines'])}'::jsonb,'{j(p['allocs'])}'::jsonb)::text;")


def _settle(dsn: str, p: dict, *, scalar: bool = False) -> subprocess.CompletedProcess:
    """The call the API will make: the guarded door, as the database owner (the server's own client has no signed-in person)."""
    return _run(dsn, _call_sql(p), scalar=scalar)


def _counts(dsn: str) -> dict:
    return _json(dsn, "SELECT json_build_object('entries', (SELECT count(*) FROM journal_entries), 'lines', (SELECT count(*) FROM journal_lines), "
                      "'payments', (SELECT count(*) FROM purchase_payments), 'allocations', (SELECT count(*) FROM purchase_payment_allocations), "
                      "'fx', (SELECT count(*) FROM fx_adjustments))::text;")


def _bill(dsn: str, bill: str) -> dict:
    return _json(dsn, f"SELECT json_build_object('status', status, 'paid_paise', paid_paise, 'paid_txn', paid_txn)::text FROM purchase_bills WHERE id = '{bill}';")


def _payment(dsn: str, payment_no: str) -> dict:
    return _json(dsn, f"SELECT row_to_json(p)::text FROM purchase_payments p WHERE payment_no = '{payment_no}';")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t784_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("784_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the four shapes ───────────────────────────────────────────────────────────────────

def test_a_rupee_payment_across_two_bills_is_stored_whole_by_one_call(db):
    """2,000.00 paid: 1,000.00 clears the first bill, 300.00 goes to the second, and 700.00 is an advance on which 14.00 is withheld."""
    p = _rupee("VPMT-784-1", 200000, [_alloc(B_INR, 100000), _alloc(B_INR_2, 30000)], tds=1400)
    r = _settle(db, p, scalar=True)
    assert r.returncode == 0, r.stderr
    returned = json.loads(r.stdout)
    payment = _payment(db, "VPMT-784-1")
    assert payment["id"] == p["payment"]["id"] == returned["payment_id"]
    assert (payment["vendor_id"], payment["purchase_bill_id"], payment["amount_paise"], payment["unallocated_paise"], payment["payment_mode"],
            payment["reference_no"], payment["notes"]) == (VENDOR, None, 200000, 70000, "neft", "UTR-784", "a note")
    # the tax withheld on the advance: every column the payload named is on the row
    assert (payment["tds_paise"], payment["tds_base_paise"], payment["tds_section"], payment["tds_rate_bps"], payment["tds_basis"]) == \
        (1400, 70000, "194C", 200, "advance")
    # and the ones it did not name took the table's defaults
    assert (payment["txn_currency"].strip(), float(payment["exchange_rate"]), payment["txn_amount"], payment["rate_overridden"],
            payment["is_reversed"], payment["tds_surcharge_paise"]) == ("INR", 1.0, None, False, False, 0)

    entry = _json(db, f"SELECT row_to_json(j)::text FROM journal_entries j WHERE id = '{payment['journal_entry_id']}';")
    assert (entry["source_type"], entry["source_id"], entry["reference_no"], entry["status"], entry["entry_type"], entry["is_posted"],
            entry["posted_by"], entry["created_by"]) == ("purchase_payment", payment["id"], "VPMT-784-1", "posted", "Payment", True, USER, USER)
    lines = _json(db, "SELECT json_agg(json_build_object('account', account_id::text, 'dr', debit_paise, 'cr', credit_paise, 'order', line_order) "
                      f"ORDER BY line_order)::text FROM journal_lines WHERE journal_entry_id = '{entry['id']}';")
    assert lines == [{"account": AP_ACC, "dr": 200000, "cr": 0, "order": 0}, {"account": BANK_ACC, "dr": 0, "cr": 198600, "order": 1},
                     {"account": TDS_ACC, "dr": 0, "cr": 1400, "order": 2}]

    allocations = _json(db, "SELECT json_agg(json_build_object('bill', purchase_bill_id::text, 'paise', allocated_paise, 'txn', allocated_txn, 'voided', is_voided) "
                            f"ORDER BY allocated_paise DESC)::text FROM purchase_payment_allocations WHERE purchase_payment_id = '{payment['id']}';")
    assert allocations == [{"bill": B_INR, "paise": 100000, "txn": None, "voided": False}, {"bill": B_INR_2, "paise": 30000, "txn": None, "voided": False}]
    assert _bill(db, B_INR) == {"status": "paid", "paid_paise": 100000, "paid_txn": 0}
    assert _bill(db, B_INR_2) == {"status": "partially_paid", "paid_paise": 30000, "paid_txn": 0}

    assert returned["journal_entry_id"] == entry["id"] and returned["realized_fx_paise"] == 0
    assert sorted(returned["allocations"], key=lambda a: -a["allocated_paise"]) == [
        {"purchase_bill_id": B_INR, "allocated_paise": 100000, "new_paid_paise": 100000, "new_status": "paid"},
        {"purchase_bill_id": B_INR_2, "allocated_paise": 30000, "new_paid_paise": 30000, "new_status": "partially_paid"}]
    assert returned["payment"]["journal_entry_id"] == entry["id"] and "fx_adjustment" not in returned["payment"]
    assert _counts(db) == {"entries": 1, "lines": 3, "payments": 1, "allocations": 2, "fx": 0}


def test_a_rupee_payment_that_names_its_bill_moves_the_bill_and_writes_no_allocation_row(db):
    """The older shape, which the reversal reads to know how to roll the bill back: the bill is on the payment's own row."""
    p = _rupee("VPMT-784-2", 40000, [_alloc(B_INR, 40000)], single=B_INR)
    assert _settle(db, p).returncode == 0
    payment = _payment(db, "VPMT-784-2")
    assert (payment["purchase_bill_id"], payment["amount_paise"], payment["unallocated_paise"]) == (B_INR, 40000, 0)
    assert _bill(db, B_INR) == {"status": "partially_paid", "paid_paise": 40000, "paid_txn": 0}
    assert _counts(db) == {"entries": 1, "lines": 2, "payments": 1, "allocations": 0, "fx": 0}
    # a second one clears it
    assert _settle(db, _rupee("VPMT-784-2B", 60000, [_alloc(B_INR, 60000)], single=B_INR)).returncode == 0
    assert _bill(db, B_INR) == {"status": "paid", "paid_paise": 100000, "paid_txn": 0}


def test_a_payment_with_no_bill_at_all_is_an_advance(db):
    p = _rupee("VPMT-784-3", 50000, [])
    assert _settle(db, p).returncode == 0
    assert _payment(db, "VPMT-784-3")["unallocated_paise"] == 50000
    assert _counts(db) == {"entries": 1, "lines": 2, "payments": 1, "allocations": 0, "fx": 0}


def test_a_foreign_payment_across_two_bills_is_stored_whole_by_one_call(db):
    """1,500.00 USD paid at 83: the first bill (1,000.00 booked at 80) is cleared, 400.00 goes to the second, 100.00 is an advance.
    1,12,000.00 rupees of payable are relieved for 1,16,200.00 rupees of cash: a loss of 4,200.00."""
    p = _foreign("VPMT-784-4", 150000, "83", [_alloc(B_USD, 8000000, 100000), _alloc(B_USD_2, 3200000, 40000)])
    r = _settle(db, p, scalar=True)
    assert r.returncode == 0, r.stderr
    returned = json.loads(r.stdout)
    payment = _payment(db, "VPMT-784-4")
    assert (payment["txn_currency"], float(payment["exchange_rate"]), payment["txn_amount"], payment["rate_source"], payment["rate_type"],
            payment["rate_date"], payment["rate_selected_by"], payment["rate_overridden"]) == \
        ("USD", 83.0, 150000, "manual-override", "booking", "2026-04-05", USER, True)
    assert (payment["amount_paise"], payment["unallocated_paise"], payment["purchase_bill_id"]) == (12450000, 830000, None)

    entry = _json(db, f"SELECT row_to_json(j)::text FROM journal_entries j WHERE id = '{payment['journal_entry_id']}';")
    assert (entry["rate_overridden"], entry["rate_selected_by"]) == (True, USER) and entry["rate_selected_at"].startswith("2026-04-05T10:30:00")
    lines = _json(db, "SELECT json_agg(json_build_object('account', account_id::text, 'dr', debit_paise, 'cr', credit_paise, 'ccy', btrim(txn_currency), "
                      "'rate', exchange_rate::float8, 'tdr', txn_debit, 'tcr', txn_credit, 'src', rate_source) ORDER BY line_order)::text "
                      f"FROM journal_lines WHERE journal_entry_id = '{entry['id']}';")
    common = {"ccy": "USD", "rate": 83.0, "src": "manual-override"}
    assert lines == [
        {"account": AP_ACC, "dr": 12030000, "cr": 0, "tdr": 150000, "tcr": 0, **common},
        {"account": BANK_ACC, "dr": 0, "cr": 12450000, "tdr": 0, "tcr": 150000, **common},
        {"account": FX_ACC, "dr": 420000, "cr": 0, "tdr": 0, "tcr": 0, **common},
    ]
    allocations = _json(db, "SELECT json_agg(json_build_object('bill', purchase_bill_id::text, 'paise', allocated_paise, 'txn', allocated_txn) "
                            f"ORDER BY allocated_paise DESC)::text FROM purchase_payment_allocations WHERE purchase_payment_id = '{payment['id']}';")
    assert allocations == [{"bill": B_USD, "paise": 8000000, "txn": 100000}, {"bill": B_USD_2, "paise": 3200000, "txn": 40000}]
    assert _bill(db, B_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}
    assert _bill(db, B_USD_2) == {"status": "partially_paid", "paid_paise": 3200000, "paid_txn": 40000}

    fx = _json(db, f"SELECT row_to_json(f)::text FROM fx_adjustments f WHERE document_id = '{payment['id']}';")
    assert (fx["firm_id"], fx["client_id"], fx["kind"], fx["document_type"], fx["currency"].strip(), float(fx["settlement_rate"]), fx["base_delta_paise"],
            fx["journal_entry_id"], fx["rate_source"], fx["created_by"]) == \
        (FIRM, CLIENT, "realized", "purchase_payment", "USD", 83.0, -420000, entry["id"], "manual-override", USER)
    assert returned["realized_fx_paise"] == -420000
    assert sorted(returned["allocations"], key=lambda a: -a["allocated_paise"]) == [
        {"purchase_bill_id": B_USD, "allocated_paise": 8000000, "allocated_txn": 100000, "new_paid_paise": 8000000, "new_paid_txn": 100000, "new_status": "paid"},
        {"purchase_bill_id": B_USD_2, "allocated_paise": 3200000, "allocated_txn": 40000, "new_paid_paise": 3200000, "new_paid_txn": 40000,
         "new_status": "partially_paid"}]


def test_a_foreign_payment_that_names_its_bill_moves_both_paid_amounts_and_writes_no_allocation_row(db):
    """400.00 USD at 79 (a gain), then the remaining 600.00 at 80: the bill is part paid until its FOREIGN total is met."""
    first = _foreign("VPMT-784-5A", 40000, "79", [_alloc(B_USD, 3200000, 40000)], single=B_USD)
    assert _settle(db, first).returncode == 0
    assert _bill(db, B_USD) == {"status": "partially_paid", "paid_paise": 3200000, "paid_txn": 40000}
    assert _scalar(db, f"SELECT base_delta_paise FROM fx_adjustments WHERE document_id = '{first['payment']['id']}';") == "40000"
    second = _foreign("VPMT-784-5B", 60000, "80", [_alloc(B_USD, 4800000, 60000, paid=3200000, paid_txn=40000)], single=B_USD)
    assert _settle(db, second).returncode == 0
    assert _bill(db, B_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}
    assert _scalar(db, f"SELECT count(*) FROM fx_adjustments WHERE document_id = '{second['payment']['id']}';") == "0"
    assert _counts(db)["allocations"] == 0 and _payment(db, "VPMT-784-5A")["purchase_bill_id"] == B_USD


def test_rows_for_one_bill_are_one_settlement_and_one_allocation_row(db):
    """The table allows one row per payment and bill; the API's own path wrote one per row sent, and the second collided."""
    p = _rupee("VPMT-784-6", 100000, [_alloc(B_INR, 30000), _alloc(B_INR, 70000)])
    assert _settle(db, p).returncode == 0
    assert _scalar(db, f"SELECT string_agg(allocated_paise::text, ',') FROM purchase_payment_allocations WHERE purchase_payment_id = '{p['payment']['id']}';") == "100000"
    assert _bill(db, B_INR)["status"] == "paid"
    q = _foreign("VPMT-784-6F", 100000, "80", [_alloc(B_USD, 2400000, 30000), _alloc(B_USD, 5600000, 70000)])
    assert _settle(db, q).returncode == 0
    assert _bill(db, B_USD) == {"status": "paid", "paid_paise": 8000000, "paid_txn": 100000}


def test_a_debit_note_and_a_purchase_credit_note_move_what_is_left_to_pay(db):
    """A debit note lowers what still needs cash; a purchase credit note (the increase document) raises it."""
    _run(db, f"UPDATE purchase_bills SET debited_paise = 20000 WHERE id = '{B_INR}'; UPDATE purchase_bills SET credit_note_paise = 10000 WHERE id = '{B_INR_2}';")
    assert _settle(db, _rupee("VPMT-784-7", 140000, [_alloc(B_INR, 80000), _alloc(B_INR_2, 60000)])).returncode == 0
    assert _bill(db, B_INR)["status"] == "paid" and _bill(db, B_INR_2)["status"] == "paid"


# ── the payment row is the payload's ──────────────────────────────────────────────────

def test_a_key_that_is_no_column_fails_the_whole_call_and_stores_nothing(db):
    before = _counts(db)
    r = _settle(db, _rupee("VPMT-784-8", 40000, [_alloc(B_INR, 40000)], extra={"no_such_column": 1}))
    assert r.returncode != 0 and "no_such_column" in r.stderr, r.stderr
    assert _counts(db) == before and _bill(db, B_INR)["paid_paise"] == 0


def test_the_entrys_id_on_the_row_is_the_functions_and_not_the_callers(db):
    """A caller that names an entry cannot attach the payment to it: the row carries the entry this call posted."""
    stray = str(uuid.uuid4())
    p = _rupee("VPMT-784-9", 40000, [_alloc(B_INR, 40000)], extra={"journal_entry_id": stray})
    assert _settle(db, p).returncode == 0
    row = _payment(db, "VPMT-784-9")
    assert row["journal_entry_id"] != stray
    assert _scalar(db, f"SELECT source_id::text FROM journal_entries WHERE id = '{row['journal_entry_id']}';") == row["id"]


# ── all or nothing ────────────────────────────────────────────────────────────────────

def _refused(db, p: dict, words: str, *, code: str | None = None) -> None:
    before, bills = _counts(db), [_bill(db, b) for b in WATCHED]
    r = _settle(db, p)
    assert r.returncode != 0 and words in r.stderr, r.stderr
    if code:
        assert f"ERROR:  {code}:" in r.stderr, r.stderr
    else:
        assert "ERROR:  VP001:" not in r.stderr and "ERROR:  40001:" not in r.stderr, r.stderr
    assert _counts(db) == before, "a refused payment left something behind"
    assert [_bill(db, b) for b in WATCHED] == bills, "a refused payment moved a bill"


def test_a_refusal_at_the_second_bill_leaves_nothing_of_the_payment_not_even_the_first_bills_settlement(db):
    """The defect itself, in rupees: the second bill has less left than is sent. Before, the first bill kept its paid amount."""
    _refused(db, _rupee("VPMT-784-10", 160000, [_alloc(B_INR, 100000), _alloc(B_INR_2, 60000)]), "exceeds its outstanding")


def test_a_refusal_at_the_second_foreign_bill_leaves_nothing_of_the_payment(db):
    _run(db, f"UPDATE purchase_bills SET paid_paise = 800000, paid_txn = 10000, status = 'partially_paid' WHERE id = '{B_USD_2}';")
    p = _foreign("VPMT-784-11", 200000, "83", [_alloc(B_USD, 8000000, 100000), _alloc(B_USD_2, 8000000, 100000)])
    _refused(db, p, MOVED, code="VP001")


@pytest.mark.parametrize("change", ["paid_paise = 100", "paid_txn = 1"])
def test_a_bill_that_no_longer_reads_as_the_caller_read_it_refuses_the_payment_with_its_own_state(db, change):
    _run(db, f"UPDATE purchase_bills SET {change} WHERE id = '{B_USD}';")
    _refused(db, _foreign("VPMT-784-12", 40000, "83", [_alloc(B_USD, 3200000, 40000)]), MOVED, code="VP001")


def test_a_debit_note_that_landed_since_the_read_refuses_the_payment_when_the_caller_said_what_it_read(db):
    _run(db, f"UPDATE purchase_bills SET debited_paise = 500 WHERE id = '{B_USD}';")
    _refused(db, _foreign("VPMT-784-13", 40000, "83", [_alloc(B_USD, 3200000, 40000, debited=0)]), MOVED, code="VP001")


def test_an_allocation_that_does_not_say_what_was_read_is_refused_in_its_own_words_and_not_as_a_changed_bill(db):
    _refused(db, _foreign("VPMT-784-14", 40000, "83", [_alloc(B_USD, 3200000, 40000, paid=None, paid_txn=None)]),
             "does not say what was read of the bill")


def test_rows_for_one_bill_that_say_different_things_about_what_was_read_are_refused(db):
    _refused(db, _foreign("VPMT-784-15", 100000, "80", [_alloc(B_USD, 2400000, 30000), _alloc(B_USD, 5600000, 70000, paid=999, paid_txn=7)]),
             "do not agree about what was read")


def test_a_bill_in_another_currency_is_refused(db):
    _refused(db, _foreign("VPMT-784-16", 40000, "83", [_alloc(B_EUR, 3600000, 40000)]), "is billed in EUR")


def test_more_foreign_money_than_is_outstanding_is_refused(db):
    """The rupees fit and the foreign amount does not: 1,000.01 USD against 1,000.00."""
    _refused(db, _foreign("VPMT-784-17", 100001, "83", [_alloc(B_USD, 7999999, 100001)]), "exceeds its outstanding")


def test_an_allocation_with_rupees_and_no_foreign_amount_is_refused(db):
    row = {"purchase_bill_id": B_USD, "allocated_paise": 3200000, "expect_paid_paise": 0, "expect_paid_txn": 0}
    _refused(db, _foreign("VPMT-784-18", 40000, "83", [row]), "names no foreign amount")


def test_a_rupee_payment_does_not_settle_a_bill_billed_in_a_foreign_currency(db):
    _refused(db, _rupee("VPMT-784-19", 40000, [_alloc(B_USD, 40000)]), "is in rupees and bill")
    _refused(db, _rupee("VPMT-784-19B", 40000, [_alloc(B_USD, 40000)], single=B_USD), "is in rupees and bill")


def test_one_suppliers_payment_does_not_settle_another_suppliers_bill(db):
    """POST-A-580: the route for several bills never asked whose the bill was."""
    _refused(db, _rupee("VPMT-784-20", 140000, [_alloc(B_INR, 100000), _alloc(B_OTHER_VENDOR, 40000)]), "was raised by another supplier")
    _refused(db, _rupee("VPMT-784-20B", 40000, [_alloc(B_OTHER_VENDOR, 40000)], single=B_OTHER_VENDOR), "was raised by another supplier")


# stable ids: the bills' uuids are drawn at import, so without them every parallel worker would name the case differently and
# pytest-xdist would refuse to collect the file (found on 28-11-2026 by a full local run)
@pytest.mark.parametrize("bill, word", [(B_DRAFT, "draft"), (B_CANCELLED, "cancelled")], ids=["draft", "cancelled"])
def test_a_draft_or_a_cancelled_bill_cannot_be_paid(db, bill, word):
    _refused(db, _rupee("VPMT-784-21", 40000, [_alloc(bill, 40000)]), f"is {word} and cannot be paid")


def test_a_bill_of_another_client_or_of_nobody_is_refused(db):
    _refused(db, _rupee("VPMT-784-22", 40000, [_alloc(B_OTHER_CLIENT, 40000)]), "is not part of this client's books")
    _refused(db, _rupee("VPMT-784-22B", 40000, [_alloc(str(uuid.uuid4()), 40000)]), "is not part of this client's books")


def test_a_payment_that_names_its_bill_settles_that_bill_alone_and_for_its_whole_amount(db):
    # another bill
    _refused(db, _rupee("VPMT-784-23", 40000, [_alloc(B_INR_2, 40000)], single=B_INR), "and its settlement names bill")
    # nothing
    _refused(db, _rupee("VPMT-784-23B", 40000, [], single=B_INR), "and settles nothing against it")
    # less than the whole payment (the reversal would give the bill back more than it took)
    _refused(db, _rupee("VPMT-784-23C", 40000, [_alloc(B_INR, 30000)], single=B_INR), "settles it for the payment's whole amount")
    # the same for the foreign amount
    _refused(db, _foreign("VPMT-784-23D", 40000, "83", [_alloc(B_USD, 2400000, 30000)], single=B_USD), "whole foreign amount")


def test_an_entry_that_does_not_balance_or_names_another_document_is_refused(db):
    p = _rupee("VPMT-784-24", 40000, [_alloc(B_INR, 40000)])
    p["lines"][1]["credit_paise"] = 39999
    _refused(db, p, "journal imbalance")
    q = _rupee("VPMT-784-24B", 40000, [_alloc(B_INR, 40000)])
    q["entry"]["source_id"] = str(uuid.uuid4())
    _refused(db, q, "does not name this payment as its source")
    z = _rupee("VPMT-784-24C", 40000, [_alloc(B_INR, 40000)])
    del z["payment"]["id"]
    _refused(db, z, "carries no id")


def test_a_number_already_taken_is_refused_whole_as_a_duplicate(db):
    """The API answers a duplicate number by taking the next one; here it must fail the whole call and say which kind of failure."""
    assert _settle(db, _rupee("VPMT-784-25", 40000, [_alloc(B_INR, 40000)])).returncode == 0
    before = _counts(db)
    r = _settle(db, _rupee("VPMT-784-25", 30000, [_alloc(B_INR, 30000)]))
    assert r.returncode != 0 and "ERROR:  23505:" in r.stderr, r.stderr
    assert _counts(db) == before and _bill(db, B_INR)["paid_paise"] == 40000


def test_two_payments_racing_for_one_bill_from_the_same_read_record_one_and_refuse_the_other_whole(db):
    """A real race. The first session records its payment and holds its transaction open; the second, built from the same read of
    the bill, waits on the row lock, then finds the bill moved and is refused. Nothing of the second exists afterwards."""
    first = _foreign("VPMT-784-R1", 60000, "83", [_alloc(B_USD, 4800000, 60000)])
    # dated in ANOTHER MONTH: an entry's lines update one monthly balance row per account, and two payments of one month would
    # queue there, before either reached the bill, so the race would pass with no lock on the bill at all (found by the review)
    second = _foreign("VPMT-784-R2", 60000, "84", [_alloc(B_USD, 4800000, 60000)], day="2026-05-05")
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                               f"BEGIN; {_call_sql(first)} SELECT pg_sleep(3); COMMIT;"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:      # wait until the first session holds the bill's row lock
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'purchase_bills' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        started = time.time()
        r = _settle(db, second)
        waited = time.time() - started
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    assert r.returncode != 0 and MOVED in r.stderr and "ERROR:  VP001:" in r.stderr, r.stderr
    assert waited > 1.0, f"the second payment did not wait for the first's lock ({waited:.2f}s): the race was not exercised"
    assert _bill(db, B_USD) == {"status": "partially_paid", "paid_paise": 4800000, "paid_txn": 60000}
    assert _counts(db) == {"entries": 1, "lines": 3, "payments": 1, "allocations": 1, "fx": 1}
    assert _scalar(db, "SELECT string_agg(payment_no, ',') FROM purchase_payments;") == "VPMT-784-R1"


def test_two_rupee_payments_racing_for_one_bill_cannot_both_take_what_is_left(db):
    """In rupees there is no reading to compare: the second waits for the lock and is judged against what the first left."""
    first = _rupee("VPMT-784-R3", 70000, [_alloc(B_INR, 70000)])
    second = _rupee("VPMT-784-R4", 70000, [_alloc(B_INR, 70000)], day="2026-05-05")      # another month: only the bill is shared
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                               f"BEGIN; {_call_sql(first)} SELECT pg_sleep(3); COMMIT;"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'purchase_bills' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        r = _settle(db, second)
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    assert r.returncode != 0 and "exceeds its outstanding" in r.stderr, r.stderr
    assert _bill(db, B_INR) == {"status": "partially_paid", "paid_paise": 70000, "paid_txn": 0}
    assert _counts(db) == {"entries": 1, "lines": 2, "payments": 1, "allocations": 1, "fx": 0}


def _race(db, first: dict, second: dict) -> tuple[subprocess.CompletedProcess, float]:
    """The first call in a session that holds its transaction open for three seconds; the second in another session meanwhile."""
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                               f"BEGIN; {_call_sql(first)} SELECT pg_sleep(3); COMMIT;"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:      # until the first session holds a row lock on the bill
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'purchase_bills' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        started = time.time()
        r = _settle(db, second)
        waited = time.time() - started
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    return r, waited


def test_two_payments_that_name_the_same_bill_on_their_own_row_cannot_both_take_what_is_left(db):
    """The older shape, in which the payment row itself points at the bill (and its foreign-key check holds a key share on it)."""
    first = _rupee("VPMT-784-R5", 70000, [_alloc(B_INR, 70000)], single=B_INR)
    second = _rupee("VPMT-784-R6", 70000, [_alloc(B_INR, 70000)], single=B_INR, day="2026-05-05")
    r, waited = _race(db, first, second)
    assert r.returncode != 0 and "exceeds its outstanding" in r.stderr and "deadlock" not in r.stderr, r.stderr
    assert waited > 1.0, f"the second payment did not wait for the first ({waited:.2f}s): the race was not exercised"
    assert _bill(db, B_INR) == {"status": "partially_paid", "paid_paise": 70000, "paid_txn": 0}
    assert _counts(db) == {"entries": 1, "lines": 2, "payments": 1, "allocations": 0, "fx": 0}


def test_without_the_row_lock_the_same_race_stores_both_payments_against_one_bill(db):
    """The negative control, and the defect in one picture. The same function with its row lock taken out: both payments read the
    bill before either wrote, both are stored, and the bill shows one payment's worth paid while two were recorded."""
    r = _run(db, "DO $do$ DECLARE d text; BEGIN "
                 f"SELECT pg_get_functiondef('{BODY}'::regprocedure) INTO d; "
                 "IF position('FOR NO KEY UPDATE;' IN d) = 0 THEN RAISE EXCEPTION 'the lock clause was not found'; END IF; "
                 "EXECUTE replace(d, 'FOR NO KEY UPDATE;', ';'); END $do$;")
    assert r.returncode == 0, r.stderr
    first = _rupee("VPMT-784-R7", 70000, [_alloc(B_INR, 70000)])
    second = _rupee("VPMT-784-R8", 70000, [_alloc(B_INR, 70000)], day="2026-05-05")
    r, _waited = _race(db, first, second)
    assert r.returncode == 0, "without the lock the second payment was still refused: the control no longer shows the defect"
    assert _counts(db)["payments"] == 2 and _bill(db, B_INR)["paid_paise"] == 70000, (_counts(db), _bill(db, B_INR))


def test_a_key_share_held_on_the_bill_by_another_transaction_does_not_make_the_payment_wait(db):
    """Why the lock is FOR NO KEY UPDATE and not FOR UPDATE. Another transaction that only REFERS to the bill (a payment row that
    names it, an allocation, a debit note: each holds a key share from its foreign-key check) must not block a payment, and two
    payments that name one bill must not each wait for the other's key share to go (a deadlock, one of them killed). The stronger
    lock waits here for the three seconds the other transaction stays open."""
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                               f"BEGIN; SELECT 1 FROM purchase_bills WHERE id = '{B_INR}' FOR KEY SHARE; SELECT pg_sleep(3); COMMIT;"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'purchase_bills' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        started = time.time()
        r = _settle(db, _rupee("VPMT-784-R9", 40000, [_alloc(B_INR, 40000)], single=B_INR))
        waited = time.time() - started
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    assert r.returncode == 0, r.stderr
    assert waited < 2.0, f"the payment waited {waited:.2f}s for a key share: the bill is locked FOR UPDATE again"
    import re
    body = re.sub(r"--[^\n]*", "", _scalar(db, f"SELECT prosrc FROM pg_proc WHERE oid = '{BODY}'::regprocedure;"))     # the statements, not the comments
    assert "FOR NO KEY UPDATE" in body and "FOR UPDATE" not in body.replace("FOR NO KEY UPDATE", "")
    # and the bills are taken in one order, so two payments across the same bills cannot each hold what the other wants
    assert re.search(r"GROUP BY \(x->>'purchase_bill_id'\)::uuid\s+ORDER BY 1", body)


def test_a_number_another_client_of_the_firm_already_carries_fails_the_whole_call_after_the_entry_was_written(db):
    """A payment's number is unique in the FIRM. Another client's payment took it: this client's entry and lines go in first (no
    entry of this client carries the number), then the payment row is refused, and the entry goes with it."""
    r = _run(db, f"""INSERT INTO purchase_payments (firm_id, client_id, vendor_id, payment_no, payment_date, amount_paise)
                     SELECT '{FIRM}', '{OTHER_CLIENT}', v.id, 'VPMT-784-26', '2026-04-05', 1 FROM vendors v WHERE v.client_id = '{OTHER_CLIENT}' LIMIT 1;""")
    assert r.returncode == 0, r.stderr
    before = _counts(db)
    r = _settle(db, _rupee("VPMT-784-26", 40000, [_alloc(B_INR, 40000)]))
    assert r.returncode != 0 and "ERROR:  23505:" in r.stderr and "purchase_payments_firm_payment_no_key" in r.stderr, r.stderr
    assert _counts(db) == before and _bill(db, B_INR)["paid_paise"] == 0


# ── what the function checks of the caller's arithmetic ───────────────────────────────

def test_a_rupee_payment_must_say_what_is_left_of_it_and_it_must_add_up(db):
    p = _rupee("VPMT-784-27", 100000, [_alloc(B_INR, 40000)])
    p["payment"]["unallocated_paise"] = 0                       # 60,000 are left and the row would say none: a lost advance
    _refused(db, p, "are left of it")
    q = _rupee("VPMT-784-27B", 40000, [_alloc(B_INR, 40000)], single=B_INR)
    q["payment"]["unallocated_paise"] = 40000                   # a payment that names its bill has nothing left
    _refused(db, q, "are left of it")


def test_a_payment_is_not_recorded_as_already_reversed_and_no_allocation_relieves_a_negative_amount(db):
    _refused(db, _rupee("VPMT-784-28", 40000, [_alloc(B_INR, 40000)], extra={"is_reversed": True}), "not recorded as already reversed")
    # an entry that is itself sound, with a settlement that would take rupees back from the bill
    p = _foreign("VPMT-784-28B", 40000, "83", [_alloc(B_USD, 3200000, 40000)])
    p["allocs"][0]["allocated_paise"] = -100
    _refused(db, p, "relieves a negative amount")


def test_a_foreign_payment_that_names_its_bill_relieves_it_of_the_cash_paid_plus_the_exchange_difference(db):
    """The figure the reversal works out from the payment's row and the exchange record. 400.00 USD at 79 is 31,600.00 of cash, and
    the bill (booked at 80) is relieved of 32,000.00: a gain of 400.00. A payload whose three figures do not agree is refused."""
    p = _foreign("VPMT-784-29", 40000, "79", [_alloc(B_USD, 3200000, 40000)], single=B_USD)
    p["payment"]["fx_adjustment"]["base_delta_paise"] = 30000          # says 300.00 where the lines and the allocation say 400.00
    p["lines"][2]["credit_paise"] = 30000
    p["lines"][0]["debit_paise"] = 3190000
    _refused(db, p, "the cash paid plus the exchange difference")
    assert _settle(db, _foreign("VPMT-784-29B", 40000, "79", [_alloc(B_USD, 3200000, 40000)], single=B_USD)).returncode == 0


# ── the door ──────────────────────────────────────────────────────────────────────────

def test_the_payment_and_its_journal_name_one_firm_and_one_client_and_the_client_is_the_firms(db):
    p = _rupee("VPMT-784-30", 40000, [_alloc(B_INR, 40000)])
    p["entry"]["client_id"] = OTHER_CLIENT
    _refused(db, p, "name different firms or clients")
    q = _rupee("VPMT-784-30B", 40000, [_alloc(B_INR, 40000)])
    q["payment"]["firm_id"] = q["entry"]["firm_id"] = OTHER_FIRM
    _refused(db, q, "is not a client of firm")


def test_a_date_in_a_closed_year_is_refused_in_the_closures_own_sentence_and_an_unreadable_date_is_refused(db):
    _run(db, f"UPDATE firms SET locked_financial_years = ARRAY['2024-25'] WHERE id = '{FIRM}';")
    _refused(db, _rupee("VPMT-784-31", 40000, [_alloc(B_INR, 40000)], day="2024-06-10"), "2024-25")
    r = _run(db, f"INSERT INTO client_year_locks (firm_id, client_id, financial_year, reason) VALUES ('{FIRM}','{CLIENT}','2025-26','year end finalised');")
    assert r.returncode == 0, r.stderr
    _refused(db, _rupee("VPMT-784-31B", 40000, [_alloc(B_INR, 40000)], day="2025-06-10"), "2025-26")
    # the payment's own date is asked as well as the entry's
    p = _rupee("VPMT-784-31C", 40000, [_alloc(B_INR, 40000)])
    p["payment"]["payment_date"] = "2025-06-10"
    _refused(db, p, "2025-26")
    q = _rupee("VPMT-784-31D", 40000, [_alloc(B_INR, 40000)])
    q["entry"]["entry_date"] = "the fifth"
    _refused(db, q, "is not a posting date")
    # an open year still posts
    assert _settle(db, _rupee("VPMT-784-31E", 40000, [_alloc(B_INR, 40000)])).returncode == 0


def test_the_bills_settlement_is_in_the_edit_log_under_the_person_the_call_carried(db):
    p = _foreign("VPMT-784-32", 100000, "83", [_alloc(B_USD, 8000000, 100000)], actor=True)
    assert _settle(db, p).returncode == 0
    rows = _json(db, "SELECT coalesce(json_agg(json_build_object('actor', actor_id::text, 'email', actor_email, 'paid_txn', new_data->>'paid_txn')), '[]'::json)::text "
                     f"FROM audit_log WHERE entity_id = '{B_USD}' AND action = 'update';")
    assert rows and all(row["actor"] == AUTH and row["email"] == "p784@test.in" for row in rows), rows
    assert any(row["paid_txn"] == "100000" for row in rows), rows
    # the payment row's own insert is under the same person
    made = _json(db, "SELECT coalesce(json_agg(actor_id::text), '[]'::json)::text FROM audit_log "
                     f"WHERE entity_id = '{p['payment']['id']}' AND action = 'create';")
    assert made == [AUTH], made


def test_a_signed_in_member_cannot_call_either_function(db):
    for fn in ("public.settle_payment_atomic", "public.settle_payment_atomic__unguarded"):
        p = _rupee("VPMT-784-33", 40000, [_alloc(B_INR, 40000)])
        sql = (f"SET ROLE authenticated; SELECT set_config('request.jwt.claims', '{{\"sub\":\"{AUTH}\",\"role\":\"authenticated\"}}', false); "
               + _call_sql(p, fn))
        r = _run(db, sql)
        assert r.returncode != 0 and "ERROR:  42501:" in r.stderr and "permission denied for function" in r.stderr, r.stderr
    assert _counts(db)["payments"] == 0


# ── the functions' attributes, and the two files ──────────────────────────────────────

def test_the_functions_run_as_their_owner_and_only_the_server_may_execute_them(db):
    for fn in (WRAPPER, BODY):
        row = _json(db, f"""SELECT json_build_object('definer', p.prosecdef, 'config', p.proconfig, 'lang', l.lanname,
            'auth', has_function_privilege('authenticated', p.oid, 'EXECUTE'), 'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
            'service', has_function_privilege('service_role', p.oid, 'EXECUTE'))::text
            FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang WHERE p.oid = '{fn}'::regprocedure;""")
        assert row == {"definer": True, "config": ["search_path=public, pg_catalog"], "lang": "plpgsql", "auth": False, "anon": False, "service": True}, fn


def test_the_rollback_drops_both_functions_and_both_files_run_twice(db):
    md5 = lambda: _scalar(db, f"SELECT md5(prosrc) FROM pg_proc WHERE oid = '{BODY}'::regprocedure;")      # noqa: E731
    before = md5()
    assert _file(db, F784).returncode == 0 and md5() == before, "running 784 again changed the function"
    for _ in range(2):
        assert _file(db, R784).returncode == 0
        assert _scalar(db, "SELECT count(*) FROM pg_proc WHERE proname LIKE 'settle_payment_atomic%';") == "0"
    assert _file(db, F784).returncode == 0 and md5() == before
    assert _settle(db, _rupee("VPMT-784-40", 40000, [_alloc(B_INR, 40000)])).returncode == 0


# ── the in-memory double's list of the payment table's columns (POST-A-575, the service half) ──

def test_the_doubles_list_of_payment_columns_is_the_tables(db):
    """The function builds its INSERT from the payload's keys and the catalogue; the double (tests/e2e_harness.py) has no catalogue and
    asks tests/_payment_function_source.py. A migration that adds a column to purchase_payments fails here until the list has it, and
    the defaults the double gives a column the payload leaves out are the table's own."""
    from tests._payment_function_source import COLUMN_DEFAULTS, PURCHASE_PAYMENT_COLUMNS
    real = set(_json(db, "SELECT json_agg(column_name)::text FROM information_schema.columns "
                         "WHERE table_schema = 'public' AND table_name = 'purchase_payments';"))
    assert real == set(PURCHASE_PAYMENT_COLUMNS), {"only in the table": sorted(real - PURCHASE_PAYMENT_COLUMNS),
                                                   "only in the list": sorted(PURCHASE_PAYMENT_COLUMNS - real)}
    # a payment that names only what it must: every other column is the table's default
    p = _rupee("VPMT-784-50", 40000, [])
    for key in ("payment_mode", "reference_no", "notes", "created_at", "updated_at", "purchase_bill_id"):
        p["payment"].pop(key, None)        # (unallocated_paise stays: the function holds a rupee payment to its own arithmetic)
    assert _settle(db, p).returncode == 0
    row = _payment(db, "VPMT-784-50")
    for column, value in COLUMN_DEFAULTS.items():
        if column in p["payment"]:
            continue                      # the payload named it: it is the caller's value and not the table's default
        stored = row[column].strip() if isinstance(row[column], str) else row[column]
        assert (float(stored) if column == "exchange_rate" else stored) == value, (column, stored, value)
