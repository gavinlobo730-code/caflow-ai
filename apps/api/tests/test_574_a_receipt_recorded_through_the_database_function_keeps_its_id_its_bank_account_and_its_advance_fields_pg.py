"""Migrations 574 and 575, proved against real PostgreSQL: a receipt recorded through `settle_receipt_atomic` keeps the id its ledger entry names,
the bank account it was paid into and the GSTR-1 Table 11A fields the CA supplied, and the 101 existing entries are pointed at their receipts.

WHAT WAS WRONG (found by the post-merge review of migration 572; production read on 2-11-2026)
    `settle_receipt_atomic__unguarded`, migration 235's body renamed by 486, inserted the receipt with a fixed column list written before the API sent
    `bank_account_id` (342), `gst_rate_bps` / `place_of_supply` / `is_interstate` (286) and a pre-generated `id`. The function dropped all five
    without an error: the Receipts tab said a receipt was posted to the general Bank ledger when its journal debited the CA's chosen bank, an
    advance receipt kept no rate or place of supply so Table 11A listed it as a gap, and the receipt's id was not the `source_id` of its own
    journal entry, so the ledger's "open the document" opened nothing: 101 of 101 receipt entries on production named an id that is no receipt.

WHAT THIS HOLDS
    574  THE CASE: the call the API makes stores id, bank account, rate, place of supply and the interstate flag, and the journal entry's
         `source_id` is the receipt's id; the same call is run through the ROLLED-BACK function first to show the hole (the negative control);
         absent and blank values are NULL and an absent id is generated; everything else the function does is unchanged (allocation, invoice
         status, the balance guard, the draft-invoice refusal, the returned JSON); the attributes are exactly the previous function's
         (SECURITY DEFINER, its search path, no EXECUTE for a signed-in role, EXECUTE for service_role) and the wrapper still passes the payload
         through; the rollback restores the text production held (md5 pinned) and the file can be run again.
    575  THE REPAIR, end to end: receipts recorded by the rolled-back function (so with the real defect) are repaired by the file, a reversal of such
         an entry follows its original, an entry that names a real receipt, one tied to two receipts, one tied to none and one of another source
         type are NOT touched, only the link column changes, the edit log records each change, the allowance does not outlive the file (a posted
         entry cannot be edited directly afterwards), and a second run changes nothing.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_S574 = "574_a_receipt_recorded_through_the_database_function_keeps_its_id_its_bank_account_and_its_advance_fields"
F574, R574 = MIGRATIONS / f"{_S574}.sql", MIGRATIONS / f"{_S574}_rollback.sql"
_S575 = "575_a_receipts_ledger_entry_names_the_receipt_it_belongs_to"
F575, R575 = MIGRATIONS / f"{_S575}.sql", MIGRATIONS / f"{_S575}_rollback.sql"

#: What production held before 574 (read on 2-11-2026): the md5 of the function's source and its length. The rollback must restore exactly it.
PRODUCTION_BEFORE_574 = ("45807d07a4e02711c88dafe36fabe40f", 6462)

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the receipt-function proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AR_ACC, BANK_ROW = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
INV_A, INV_DRAFT = str(uuid.uuid4()), str(uuid.uuid4())
FUNCTION = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _body(dsn: str) -> tuple[str, int]:
    row = _scalar(dsn, f"SELECT md5(prosrc) || '|' || length(prosrc) FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")
    digest, length = row.split("|")
    return digest, int(length)


def _seed(dsn: str) -> None:
    sql = f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','574 Firm','f574@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','574 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}','{FIRM}','{CLIENT}','574 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset');
    INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no, coa_account_id)
      VALUES ('{BANK_ROW}','{FIRM}','{CLIENT}','Test Bank','574001','{BANK_ACC}');
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES ('{INV_A}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-A','2026-04-01',100000,'issued',0,0),
           ('{INV_DRAFT}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-D','2026-04-02',100000,'draft',0,0);
    """
    r = _run(dsn, sql)
    assert r.returncode == 0, r.stderr


def _payload(receipt_no: str, amount: int, allocations: list[tuple[str, int]], extra: dict | None = None, *, with_id: bool = True) -> dict:
    allocated = sum(a for _, a in allocations)
    receipt = {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "receipt_no": receipt_no, "receipt_date": "2026-04-05",
        "amount_paise": amount, "tds_paise": 1250, "unallocated_paise": amount - allocated, "payment_mode": "upi", "reference_no": f"UTR-{receipt_no}",
        "notes": f"note for {receipt_no}", "created_at": "2026-04-05T10:30:00+00:00",
        **(extra or {}),
    }
    if with_id:
        receipt["id"] = str(uuid.uuid4())
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": receipt_no, "narration": "Receipt",
             "entry_type": "Receipt", "is_posted": True, "status": "posted", "source_type": "receipt", "source_id": receipt.get("id")}
    lines = [
        {"account_id": BANK_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "bank", "rate_type": "booking", "rate_date": "2026-04-05"},
        {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount, "narration": "ar", "rate_type": "booking", "rate_date": "2026-04-05"},
    ]
    allocs = [{"sales_invoice_id": i, "allocated_paise": a} for i, a in allocations]
    return {"receipt": receipt, "entry": entry, "lines": lines, "allocs": allocs}


def _settle(dsn: str, p: dict, *, scalar: bool = False) -> subprocess.CompletedProcess:
    """The call the API's plain receipt makes (the wrapper, as the owner). With `scalar`, stdout is the returned JSON text alone."""
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    return _run(dsn, f"SELECT public.settle_receipt_atomic('{j(p['receipt'])}'::jsonb,'{j(p['entry'])}'::jsonb,"
                     f"'{j(p['lines'])}'::jsonb,'{j(p['allocs'])}'::jsonb)::text;", scalar=scalar)


def _row(dsn: str, receipt_no: str) -> dict:
    out = _scalar(dsn, "SELECT row_to_json(r)::text FROM (SELECT r.id::text, r.bank_account_id::text, r.gst_rate_bps, r.place_of_supply, "
                       "r.is_interstate, r.journal_entry_id::text, j.source_id::text AS entry_source_id, j.source_type AS entry_source_type "
                       f"FROM receipts r JOIN journal_entries j ON j.id = r.journal_entry_id WHERE r.receipt_no = '{receipt_no}') r;")
    return json.loads(out)


def _entries_but_the_link(dsn: str) -> str:
    """A hash of every column of every ledger entry except the link 575 repairs (and the stamp the platform's own trigger moves with it)."""
    return _scalar(dsn, "SELECT coalesce(md5(string_agg((to_jsonb(j) - 'source_id' - 'updated_at')::text, ',' ORDER BY j.id)), '') FROM journal_entries j;")


def _lines_hash(dsn: str) -> str:
    return _scalar(dsn, "SELECT coalesce(md5(string_agg(to_jsonb(l)::text, ',' ORDER BY l.id)), '') FROM journal_lines l;")


def _receipts_hash(dsn: str) -> str:
    return _scalar(dsn, "SELECT coalesce(md5(string_agg(to_jsonb(r)::text, ',' ORDER BY r.id)), '') FROM receipts r;")


def _audit_rows(dsn: str) -> list[dict]:
    return json.loads(_scalar(dsn, "SELECT coalesce(json_agg(json_build_object('entry', entity_id, 'firm', firm_id::text, 'old', old_data->>'source_id', "
                                   "'new', new_data->>'source_id', 'actor', actor_id, 'action', action) ORDER BY entity_id), '[]'::json)::text "
                                   "FROM audit_log WHERE entity_type = 'journal_entry' AND metadata->>'source' = 'migration 575';"))


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t574_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith(("574_", "575_")) for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


ADVANCE = {"bank_account_id": BANK_ROW, "gst_rate_bps": 1800, "place_of_supply": "27", "is_interstate": False}


# ── 574: the case ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_receipt_keeps_its_id_its_bank_account_and_its_advance_fields_and_its_entry_names_it(db):
    p = _payload("R-574-1", 100000, [(INV_A, 40000)], ADVANCE)
    r = _settle(db, p)
    assert r.returncode == 0, r.stderr
    row = _row(db, "R-574-1")
    assert row["id"] == p["receipt"]["id"], "the receipt was stored under another id than the one its journal entry carries"
    assert row["entry_source_id"] == row["id"] and row["entry_source_type"] == "receipt"
    assert (row["bank_account_id"], row["gst_rate_bps"], row["place_of_supply"], row["is_interstate"]) == (BANK_ROW, 1800, "27", False)


def test_every_column_the_function_stored_before_is_still_stored_as_sent(db):
    """The function is replaced WHOLE, so a column the old INSERT stored and the new one forgot would vanish without an error: read every one back."""
    p = _payload("R-574-0", 100000, [(INV_A, 40000)], ADVANCE)
    assert _settle(db, p).returncode == 0
    stored = json.loads(_scalar(db, "SELECT row_to_json(r)::text FROM receipts r WHERE receipt_no = 'R-574-0';"))
    sent = p["receipt"]
    for column in ("id", "firm_id", "client_id", "customer_id", "receipt_no", "receipt_date", "amount_paise", "tds_paise", "unallocated_paise",
                   "payment_mode", "reference_no", "notes", "bank_account_id", "gst_rate_bps", "place_of_supply", "is_interstate"):
        assert stored[column] == sent[column], f"{column}: sent {sent[column]!r}, stored {stored[column]!r}"
    assert stored["created_at"].startswith("2026-04-05T10:30:00"), "the creation stamp the caller sent is not kept"
    assert stored["allocated_paise"] == 40000 and stored["journal_entry_id"] is not None


def test_the_returned_json_carries_the_stored_row_and_the_allocations(db):
    """`create_receipt_core` audits and answers from what the function returns, so the new columns must be in it, not only in the table."""
    p = _payload("R-574-0B", 100000, [(INV_A, 40000)], ADVANCE)
    r = _settle(db, p, scalar=True)
    assert r.returncode == 0, r.stderr
    returned = json.loads(r.stdout)
    receipt = returned["receipt"]
    assert returned["receipt_id"] == receipt["id"] == p["receipt"]["id"] and returned["journal_entry_id"] == receipt["journal_entry_id"]
    assert (receipt["bank_account_id"], receipt["gst_rate_bps"], receipt["place_of_supply"], receipt["is_interstate"]) == (BANK_ROW, 1800, "27", False)
    assert [(a["sales_invoice_id"], a["allocated_paise"], a["new_paid_paise"], a["new_status"]) for a in returned["allocations"]] == \
        [(INV_A, 40000, 40000, "partially_paid")]


def test_the_same_call_loses_all_five_through_the_function_before_574_and_so_the_test_sees_the_hole(db):
    """The negative control: roll 574 back and the identical call stores none of them and a different id."""
    assert _file(db, R574).returncode == 0
    p = _payload("R-574-2", 100000, [], ADVANCE)
    assert _settle(db, p).returncode == 0
    row = _row(db, "R-574-2")
    assert row["id"] != p["receipt"]["id"] and row["entry_source_id"] != row["id"], "the control must show the receipt under another id"
    assert (row["bank_account_id"], row["gst_rate_bps"], row["place_of_supply"], row["is_interstate"]) == (None, None, None, None)


def test_a_payload_without_those_keys_stores_nulls_and_a_generated_id(db):
    p = _payload("R-574-3", 100000, [], None, with_id=False)
    p["entry"]["source_id"] = None
    assert _settle(db, p).returncode == 0
    row = _row(db, "R-574-3")
    assert uuid.UUID(row["id"]) and (row["bank_account_id"], row["gst_rate_bps"], row["place_of_supply"], row["is_interstate"]) == (None, None, None, None)


def test_blank_values_are_null_and_a_json_null_is_null(db):
    p = _payload("R-574-4", 100000, [], {"bank_account_id": "", "gst_rate_bps": "", "place_of_supply": "", "is_interstate": ""})
    assert _settle(db, p).returncode == 0
    row = _row(db, "R-574-4")
    assert (row["bank_account_id"], row["gst_rate_bps"], row["place_of_supply"], row["is_interstate"]) == (None, None, None, None)
    p = _payload("R-574-5", 100000, [], {"bank_account_id": None, "gst_rate_bps": None, "place_of_supply": None, "is_interstate": None})
    assert _settle(db, p).returncode == 0
    assert _row(db, "R-574-5")["gst_rate_bps"] is None


def test_the_interstate_flag_keeps_true_and_false_apart_from_unknown(db):
    for no, value, expected in (("R-574-6", True, True), ("R-574-7", False, False), ("R-574-8", None, None)):
        assert _settle(db, _payload(no, 100000, [], {"is_interstate": value})).returncode == 0
        assert _row(db, no)["is_interstate"] is expected, no


def test_a_bank_account_that_is_no_bank_account_is_refused_by_the_key_and_nothing_is_posted(db):
    before = _scalar(db, "SELECT count(*) FROM journal_entries;")
    r = _settle(db, _payload("R-574-9", 100000, [], {"bank_account_id": str(uuid.uuid4())}))
    assert r.returncode != 0 and "foreign key" in r.stderr
    assert _scalar(db, "SELECT count(*) FROM journal_entries;") == before and _scalar(db, "SELECT count(*) FROM receipts WHERE receipt_no = 'R-574-9';") == "0"


# ── 574: everything else is unchanged ────────────────────────────────────────────────────────────────────────────────

def test_the_allocation_still_settles_the_invoice_and_the_total_is_kept(db):
    p = _payload("R-574-10", 100000, [(INV_A, 100000)], ADVANCE)
    assert _settle(db, p).returncode == 0
    assert _scalar(db, f"SELECT status || '|' || paid_paise FROM client_sales_invoices WHERE id = '{INV_A}';") == "paid|100000"
    assert _scalar(db, "SELECT allocated_paise FROM receipts WHERE receipt_no = 'R-574-10';") == "100000"


def test_the_guards_the_function_had_still_refuse(db):
    unbalanced = _payload("R-574-11", 100000, [])
    unbalanced["lines"][1]["credit_paise"] = 99999
    r = _settle(db, unbalanced)
    assert r.returncode != 0 and "journal imbalance" in r.stderr
    r = _settle(db, _payload("R-574-12", 100000, [(INV_DRAFT, 1000)]))
    assert r.returncode != 0 and "is draft and cannot receive a payment" in r.stderr
    r = _settle(db, _payload("R-574-13", 100000, [(INV_A, 100001)]))
    assert r.returncode != 0 and "exceeds its outstanding" in r.stderr
    assert _scalar(db, "SELECT count(*) FROM receipts WHERE receipt_no LIKE 'R-574-1%';") == "0", "a refusal must leave no receipt behind"


def test_the_attributes_are_exactly_the_previous_functions(db):
    assert _scalar(db, f"SELECT prosecdef::text || '|' || array_to_string(proconfig, ',') FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;") == \
        "true|search_path=public, pg_catalog"
    grantees = _scalar(db, f"SELECT string_agg(coalesce(NULLIF(a.grantee, 0)::regrole::text, 'PUBLIC'), ',' ORDER BY 1) "
                           f"FROM pg_proc p, aclexplode(p.proacl) a WHERE p.oid = '{FUNCTION}'::regprocedure;")
    assert grantees == "postgres,service_role", grantees
    for role in ("anon", "authenticated"):
        assert _scalar(db, f"SELECT has_function_privilege('{role}', '{FUNCTION}', 'EXECUTE');") == "f", role


def test_the_wrapper_is_the_one_door_and_hands_the_receipt_to_the_body_whole(db):
    """The privileged wrapper (migrations 533, 545, 546) is not rewritten by 574: it still ends in a call to the unguarded body with the
    receipt argument as it received it, and it holds no INSERT INTO receipts of its own (a second place that dropped a key would hide this)."""
    src = " ".join(_scalar(db, "SELECT prosrc FROM pg_proc WHERE oid = 'public.settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure;").split())
    assert re.search(r"settle_receipt_atomic__unguarded\(\s*p_receipt\s*,", src), src
    assert "INSERT INTO" not in src.upper().replace("INSERT INTO PUBLIC.AUDIT_LOG", ""), "the wrapper stores something itself"


# ── 574: the file ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_rollback_restores_the_text_production_held_and_the_file_can_be_run_again(db):
    after = _body(db)
    assert after != PRODUCTION_BEFORE_574
    assert _file(db, R574).returncode == 0
    assert _body(db) == PRODUCTION_BEFORE_574, "the rollback is not the function production held before 574"
    assert _file(db, F574).returncode == 0 and _body(db) == after
    assert _file(db, F574).returncode == 0 and _body(db) == after, "running the file twice changed the function"


# ── 575: the repair ─────────────────────────────────────────────────────────────────────────────────────────────────

def _old_receipts(db, numbers):
    """Receipts recorded by the function production held (the real defect): their entries name an id that is no receipt."""
    assert _file(db, R574).returncode == 0
    for no in numbers:
        assert _settle(db, _payload(no, 100000, [])).returncode == 0
        row = _row(db, no)
        assert row["entry_source_id"] != row["id"], "the plant did not reproduce the defect"
    assert _file(db, F574).returncode == 0


def test_the_repair_points_each_receipt_entry_at_its_receipt_and_changes_only_the_link(db):
    # a decoy firm that is older than the real one, so an edit-log row that names the wrong firm cannot pass by being the only firm
    assert _run(db, "INSERT INTO firms (id, name, email, created_at) VALUES "
                    f"('{uuid.uuid4()}','Decoy','decoy574@test.in','2000-01-01T00:00:00+00');").returncode == 0
    _old_receipts(db, ["R-575-1", "R-575-2"])
    entries_before, lines_before, receipts_before = _entries_but_the_link(db), _lines_hash(db), _receipts_hash(db)
    stale = {n: _row(db, n)["entry_source_id"] for n in ("R-575-1", "R-575-2")}
    r = _file(db, F575)
    assert r.returncode == 0, r.stderr
    assert "migration 575: 2 receipt ledger entr(ies) now name their receipt; 0 receipt entr(ies) still name no receipt" in r.stderr, r.stderr
    for no in ("R-575-1", "R-575-2"):
        row = _row(db, no)
        assert row["entry_source_id"] == row["id"], no
    # EVERY other column of every entry, every line and every receipt is as it was (the link is the one thing that moved)
    assert _entries_but_the_link(db) == entries_before, "the repair changed a column of a ledger entry other than the link"
    assert _lines_hash(db) == lines_before and _receipts_hash(db) == receipts_before
    logged = _audit_rows(db)
    assert len(logged) == 2, "the edit log must record each repaired entry (the row-level trigger writes nothing for a migration)"
    for no in ("R-575-1", "R-575-2"):
        row = _row(db, no)
        mine = next(e for e in logged if e["entry"] == row["journal_entry_id"])
        assert (mine["old"], mine["new"], mine["actor"], mine["firm"], mine["action"]) == (stale[no], row["id"], None, FIRM, "update")


def test_the_allowance_does_not_outlive_the_file_not_even_in_the_same_session_and_a_second_run_changes_nothing(db, tmp_path):
    _old_receipts(db, ["R-575-3"])
    row = _row(db, "R-575-3")
    probe = tmp_path / "probe.sql"
    probe.write_text(f"UPDATE journal_entries SET narration = 'edited after 575' WHERE id = '{row['journal_entry_id']}';\n", encoding="utf-8")
    # ONE psql session runs the file and then tries to edit a posted entry: the file's `set_config(..., true)` must not leak past its COMMIT
    same = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(F575), "-f", str(probe)], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})
    assert same.returncode != 0 and "Cannot modify a posted journal entry" in same.stderr, "a posted entry stayed editable in the session that ran 575"
    assert _row(db, "R-575-3")["entry_source_id"] == row["id"], "575 itself must have committed before the probe"
    r = _run(db, f"UPDATE journal_entries SET source_id = '{uuid.uuid4()}' WHERE id = '{row['journal_entry_id']}';")
    assert r.returncode != 0 and "Cannot modify a posted journal entry" in r.stderr, "a posted entry became editable"
    logged = _audit_rows(db)
    again = _file(db, F575)
    assert again.returncode == 0 and "migration 575: 0 receipt ledger entr(ies) now name their receipt; 0 receipt entr(ies) still name no receipt" in again.stderr, again.stderr
    assert _audit_rows(db) == logged, "a second run wrote edit-log rows for entries it did not change"


def test_what_must_not_be_touched_is_not_touched_and_is_counted(db):
    _old_receipts(db, ["R-575-4", "R-575-5", "R-575-6", "R-575-7"])
    # 5: the entry already names a REAL receipt (another one, 4's): never moved
    r4, r5, r6, r7 = (_row(db, f"R-575-{n}") for n in (4, 5, 6, 7))
    assert _run(db, "SET session_replication_role = replica; "
                    f"UPDATE journal_entries SET source_id = '{r4['id']}' WHERE id = '{r5['journal_entry_id']}';").returncode == 0
    # 6: tied to two receipts (a second receipt row pointing at the same entry)
    assert _run(db, "SET session_replication_role = replica; "
                    "INSERT INTO receipts (firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise, journal_entry_id) "
                    f"VALUES ('{FIRM}','{CLIENT}','{CUSTOMER}','R-575-6B','2026-04-05',1,'{r6['journal_entry_id']}');").returncode == 0
    # 7: another source type that happens to have a stale-looking id: not ours
    assert _run(db, "SET session_replication_role = replica; "
                    f"UPDATE journal_entries SET source_type = 'sales_invoice' WHERE id = '{r7['journal_entry_id']}';").returncode == 0
    # an entry tied to no receipt at all
    assert _run(db, "SET session_replication_role = replica; "
                    "INSERT INTO journal_entries (firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status, source_type, source_id) "
                    f"VALUES ('{FIRM}','{CLIENT}','2026-04-06','ORPHAN','x','Receipt',true,'posted','receipt','{uuid.uuid4()}');").returncode == 0
    snapshot = _scalar(db, "SELECT string_agg(id::text || ':' || coalesce(source_type, '') || ':' || coalesce(source_id::text, ''), ',' ORDER BY id) "
                           f"FROM journal_entries WHERE id IN ('{r5['journal_entry_id']}','{r6['journal_entry_id']}','{r7['journal_entry_id']}') "
                           "OR reference_no = 'ORPHAN';")
    r = _file(db, F575)
    assert r.returncode == 0, r.stderr
    assert "migration 575: 1 receipt ledger entr(ies) now name their receipt; 2 receipt entr(ies) still name no receipt" in r.stderr, r.stderr
    assert _row(db, "R-575-4")["entry_source_id"] == r4["id"], "the one honest candidate was not repaired"
    assert [e["entry"] for e in _audit_rows(db)] == [_row(db, "R-575-4")["journal_entry_id"]], "an edit-log row exists for an entry that was not changed"
    assert _scalar(db, "SELECT string_agg(id::text || ':' || coalesce(source_type, '') || ':' || coalesce(source_id::text, ''), ',' ORDER BY id) "
                       f"FROM journal_entries WHERE id IN ('{r5['journal_entry_id']}','{r6['journal_entry_id']}','{r7['journal_entry_id']}') "
                       "OR reference_no = 'ORPHAN';") == snapshot


def test_a_receipt_of_another_firm_or_client_is_never_followed(db):
    """A corrupt link (a receipt of ANOTHER firm tied to this entry, the entry's own receipt gone) must not make the repair guess: the entry
    would be pointed at a receipt of a firm that cannot see it, and the party ledger would attribute its credit to that firm's customer."""
    _old_receipts(db, ["R-575-9"])
    row = _row(db, "R-575-9")
    other_firm, other_client, other_customer = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    assert _run(db, f"INSERT INTO firms (id, name, email) VALUES ('{other_firm}','Other','o574@test.in');"
                    f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{other_client}','{other_firm}','OC','Private Limited');"
                    f"INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{other_customer}','{other_firm}','{other_client}','OCust');").returncode == 0
    assert _run(db, "SET session_replication_role = replica; "
                    f"UPDATE receipts SET journal_entry_id = NULL WHERE id = '{row['id']}'; "
                    "INSERT INTO receipts (firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise, journal_entry_id) "
                    f"VALUES ('{other_firm}','{other_client}','{other_customer}','R-575-9X','2026-04-05',1,'{row['journal_entry_id']}');").returncode == 0
    before = _scalar(db, f"SELECT source_id::text FROM journal_entries WHERE id = '{row['journal_entry_id']}';")
    r = _file(db, F575)
    assert r.returncode == 0, r.stderr
    assert "migration 575: 0 receipt ledger entr(ies) now name their receipt; 1 receipt entr(ies) still name no receipt" in r.stderr, r.stderr
    assert _scalar(db, f"SELECT source_id::text FROM journal_entries WHERE id = '{row['journal_entry_id']}';") == before
    assert _audit_rows(db) == [], "an edit-log row exists for an entry that was left alone"


def test_the_customer_wise_breakdown_attributes_the_receipt_only_after_the_repair(db):
    """The visible effect of the defect (migration 419's party ledger finds a receipt entry's customer through `receipts WHERE id = source_id`):
    before the repair every receipt's credit falls into the unattributed row, after it each is attributed to the customer who paid."""
    _old_receipts(db, ["R-575-10"])

    def ledger() -> dict:
        return json.loads(_scalar(db, f"SELECT public.party_ledger_as_at('{FIRM}','{CLIENT}','{AR_ACC}','2026-12-31')::text;"))

    before = ledger()
    assert (before["attributed_paise"], before["unattributed_paise"]) == (0, -100000), before
    assert _file(db, F575).returncode == 0
    after = ledger()
    assert (after["attributed_paise"], after["unattributed_paise"]) == (-100000, 0), after
    assert any(r.get("party_id") == CUSTOMER for r in after["rows"]), after


def test_a_reversal_of_a_receipt_entry_follows_its_original(db):
    _old_receipts(db, ["R-575-8"])
    row = _row(db, "R-575-8")
    stale = row["entry_source_id"]
    assert _run(db, "SET session_replication_role = replica; "
                    "INSERT INTO journal_entries (firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status, source_type, source_id, reversal_of) "
                    f"VALUES ('{FIRM}','{CLIENT}','2026-04-09','REV-R-575-8','reversal','Receipt',true,'posted','receipt','{stale}','{row['journal_entry_id']}');").returncode == 0
    r = _file(db, F575)
    assert r.returncode == 0, r.stderr
    assert "now name their receipt" in r.stderr and "0 receipt entr(ies) still name no receipt" in r.stderr, r.stderr
    assert _scalar(db, "SELECT source_id::text FROM journal_entries WHERE reference_no = 'REV-R-575-8';") == row["id"]
    assert _row(db, "R-575-8")["entry_source_id"] == row["id"]
    assert sorted(e["entry"] for e in _audit_rows(db)) == sorted([row["journal_entry_id"], _scalar(db, "SELECT id::text FROM journal_entries WHERE reference_no = 'REV-R-575-8';")]), \
        "the original and its reversal are both logged, and nothing else"


def test_the_rollback_of_575_is_a_noop_that_runs(db):
    assert _file(db, R575).returncode == 0
