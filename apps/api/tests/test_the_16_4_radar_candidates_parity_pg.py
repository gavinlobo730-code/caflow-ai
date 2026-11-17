"""Migration 616 against real PostgreSQL: the database keeps exactly the bills the s.16(2)(aa) pass would not allow (POST-A-062).

WHY THIS FILE IS THE POINT OF THE CHANGE
    `public.itc_time_bar_candidates` lets the s.16(4) radar read only the bills whose credit could be withheld, so what crosses the wire
    is proportional to the answer and not to the client's purchases. To do that it has to know which bills the pass ALLOWS, which is a
    second statement of a rule that lives in `domain/gst/rule_36_4`. A second statement is safe only while something proves the two
    agree, so every scenario below is written ONCE, as rows in a real database, and asked of both halves:

      * the database: the function's answer;
      * Python: the same rows read back as they are, filtered the way the radar's own read filters them, folded the way
        `gst_return_service._two_b_by_document` and `_documents_the_recon_never_saw` fold them, and judged by `rule_36_4.assess`.

    The function must return EXACTLY the bills the pass does not allow (no more, which would only cost reading; and no fewer, which
    would hide a withheld credit from the radar), and for each the same inputs the pass reads: the heads net of s.17(5), whether it was
    examined, and the summed 2B heads, the blocked flag and the reason code.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.accounting import opening_documents as _opening
from domain.gst import rule_36_4
from services import gst_return_service as returns

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "616_the_16_4_radar_reads_only_the_bills_whose_credit_is_withheld"
FILE, ROLLBACK = MIGRATIONS / f"{_STEM}.sql", MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")
FUNCTION = "public.itc_time_bar_candidates(uuid, uuid, date, date, text[])"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the radar's SQL/Python parity proof requires HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "f6160000-0000-0000-0000-000000000001", "f6160000-0000-0000-0000-0000000000ff"
CLIENT, OTHER_CLIENT = "c6160000-0000-0000-0000-000000000001", "c6160000-0000-0000-0000-000000000002"
VENDOR = "a6160000-0000-0000-0000-000000000001"
FROM, TO = "2025-04-01", "2025-07-31"
PERIODS = ["042025", "052025", "062025"]          # 072025 is in the window and nobody reconciled it
RECONCILED_AT = "2025-08-20 10:00:00+00"
BEFORE, AFTER = "2025-08-01 09:00:00+00", "2025-08-25 09:00:00+00"


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _json(dsn: str, sql: str):
    return json.loads(_scalar(dsn, sql) or "null")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t616_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("616_") for f in pg_template.failed), pg_template.failed
        yield f"{admin} dbname={name}"
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


_seq = iter(range(1, 100_000))


def _bill(dsn, label, bill_date, *, status="received", cgst=9_000, sgst=9_000, igst=0, cess=0, created=BEFORE,
          firm=FIRM, client=CLIENT, opening=False, deleted=False, rc=False, ineligible=(0, 0, 0, 0)) -> str:
    bid = str(uuid.uuid4())
    n = next(_seq)
    total = 100_000 + cgst + sgst + igst + cess
    r = _run(dsn, "SET session_replication_role = replica; "
             "INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, status, taxable_amount_paise, "
             "cgst_paise, sgst_paise, igst_paise, cess_paise, total_paise, net_payable_paise, is_opening, is_reverse_charge, "
             "created_at, deleted_at, ineligible_itc_igst_paise, ineligible_itc_cgst_paise, ineligible_itc_sgst_paise, "
             "ineligible_itc_cess_paise) VALUES "
             f"('{bid}', '{firm}', '{client}', '{VENDOR}', '{label}', '{bill_date}', '{status}', 100000, {cgst}, {sgst}, {igst}, "
             f"{cess}, {total}, {total}, {str(opening).lower()}, {str(rc).lower()}, '{created}', "
             f"{'now()' if deleted else 'NULL'}, {ineligible[0]}, {ineligible[1]}, {ineligible[2]}, {ineligible[3]});")
    assert r.returncode == 0, (label, n, r.stderr)
    return bid


def _two_b(dsn, bill_id, period, *, cgst=9_000, sgst=9_000, igst=0, cess=0, avail="Y", reason=None, number=None):
    r = _run(dsn, "SET session_replication_role = replica; "
             "INSERT INTO gstr2a_records (id, firm_id, client_id, return_period, section, document_type, supplier_gstin, "
             "invoice_number, invoice_date, taxable_value_paise, igst_paise, cgst_paise, sgst_paise, cess_paise, "
             "purchase_bill_id, match_status, itc_available, itc_unavailable_reason_code) VALUES "
             f"(gen_random_uuid(), '{FIRM}', '{CLIENT}', '{period}', 'b2b', 'invoice', '29AAAAA1111A1Z5', "
             f"'{number or uuid.uuid4().hex[:10]}', '2025-04-10', 100000, {igst}, {cgst}, {sgst}, {cess}, "
             f"{'NULL' if bill_id is None else repr(bill_id)}, 'matched', '{avail}', {repr(reason or '')});")
    assert r.returncode == 0, r.stderr


def _world(dsn) -> dict[str, str]:
    """Every scenario at once, so a filter that is right for one and wrong for another shows up as a difference."""
    r = _run(dsn, "SET session_replication_role = replica; "
             f"INSERT INTO vendors (id, firm_id, client_id, name, gstin) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Acme', '29AAAAA1111A1Z5');"
             + "".join(f"INSERT INTO gstr2b_reconciliations (firm_id, client_id, return_period, reconciled_at) "
                       f"VALUES ('{FIRM}', '{CLIENT}', '{p}', '{RECONCILED_AT}');" for p in PERIODS))
    assert r.returncode == 0, r.stderr
    b = {}
    b["matched"] = _bill(dsn, "MATCHED", "2025-04-10"); _two_b(dsn, b["matched"], "042025")
    b["not_in_2b"] = _bill(dsn, "NOT-IN-2B", "2025-04-11")
    b["blocked"] = _bill(dsn, "BLOCKED", "2025-04-12"); _two_b(dsn, b["blocked"], "042025", avail="N", reason="P")
    b["over_cgst"] = _bill(dsn, "OVER", "2025-05-01", cgst=12_000); _two_b(dsn, b["over_cgst"], "052025")
    b["heads_swapped"] = _bill(dsn, "SWAPPED", "2025-05-02", cgst=0, sgst=0, igst=18_000); _two_b(dsn, b["heads_swapped"], "052025")
    b["reverse_charge"] = _bill(dsn, "RCM", "2025-05-03", rc=True)
    b["all_blocked_17_5"] = _bill(dsn, "BLOCKED-17-5", "2025-05-04", ineligible=(0, 9_000, 9_000, 0))
    b["part_blocked_17_5"] = _bill(dsn, "PART-17-5", "2025-05-05", cgst=12_000, sgst=12_000, ineligible=(0, 3_000, 3_000, 0))
    _two_b(dsn, b["part_blocked_17_5"], "052025")
    b["recorded_after"] = _bill(dsn, "AFTER", "2025-06-01", created=AFTER); _two_b(dsn, b["recorded_after"], "062025")
    b["recorded_exactly_at"] = _bill(dsn, "AT", "2025-06-02", created=RECONCILED_AT); _two_b(dsn, b["recorded_exactly_at"], "062025")
    b["opening"] = _bill(dsn, "OPENING", "2025-06-03", opening=True)
    b["deleted"] = _bill(dsn, "DELETED", "2025-06-04", deleted=True)
    b["draft"] = _bill(dsn, "DRAFT", "2025-06-05", status="draft")
    b["paid_not_in_2b"] = _bill(dsn, "PAID", "2025-06-06", status="paid")
    b["unreconciled_month"] = _bill(dsn, "JULY", "2025-07-01")
    b["two_rows_one_blocked"] = _bill(dsn, "TWO-ROWS-BLOCKED", "2025-06-07")
    _two_b(dsn, b["two_rows_one_blocked"], "062025", cgst=4_000, sgst=4_000)
    _two_b(dsn, b["two_rows_one_blocked"], "062025", cgst=5_000, sgst=5_000, avail="N", reason="C")
    b["two_rows_summing"] = _bill(dsn, "TWO-ROWS", "2025-06-08")
    _two_b(dsn, b["two_rows_summing"], "062025", cgst=4_000, sgst=4_000)
    _two_b(dsn, b["two_rows_summing"], "062025", cgst=5_000, sgst=5_000)
    b["row_outside_the_months"] = _bill(dsn, "ROW-IN-AUGUST", "2025-04-13"); _two_b(dsn, b["row_outside_the_months"], "082025")
    b["cess_over"] = _bill(dsn, "CESS", "2025-04-14", cess=5_000); _two_b(dsn, b["cess_over"], "042025", cess=4_000)
    b["more_in_2b"] = _bill(dsn, "LESS-IN-BOOKS", "2025-04-15", cgst=8_000, sgst=8_000); _two_b(dsn, b["more_in_2b"], "042025")
    b["other_client"] = _bill(dsn, "OTHER-CLIENT", "2025-04-16", client=OTHER_CLIENT)
    b["other_firm"] = _bill(dsn, "OTHER-FIRM", "2025-04-17", firm=OTHER_FIRM)
    _two_b(dsn, None, "042025", number="UNBOOKED")
    return b


def _database(dsn) -> dict[str, dict]:
    rows = _json(dsn, f"SELECT public.itc_time_bar_candidates('{FIRM}', '{CLIENT}', '{FROM}', '{TO}', "
                      f"ARRAY{PERIODS}::text[]);")
    return {r["id"]: r for r in rows}


def _python(dsn) -> tuple[dict, dict, set, set]:
    """The radar's own read and pass, over the rows as they are (`itc_time_bar_service._read_here` and the verdict loop)."""
    bills = _json(dsn, "SELECT coalesce(json_agg(row_to_json(b)), '[]'::json) FROM purchase_bills b "
                       f"WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}' AND deleted_at IS NULL "
                       f"AND status IN ('received', 'partially_paid', 'paid') AND bill_date BETWEEN '{FROM}' AND '{TO}';")
    bills = [b for b in _opening.without_carried_over(bills) if f"{b['bill_date'][5:7]}{b['bill_date'][:4]}" in PERIODS]
    stored = _json(dsn, "SELECT coalesce(json_agg(row_to_json(g) ORDER BY g.id), '[]'::json) FROM gstr2a_records g "
                        f"WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}' AND return_period = ANY (ARRAY{PERIODS}::text[]);")
    headers = {h["return_period"]: h["reconciled_at"] for h in _json(
        dsn, f"SELECT coalesce(json_agg(row_to_json(h)), '[]'::json) FROM gstr2b_reconciliations h WHERE client_id = '{CLIENT}';")}
    two_b = returns._two_b_by_document(stored)
    unexamined = returns._documents_the_recon_never_saw(bills, headers)
    net = {}
    verdicts = []
    for period in PERIODS:
        docs = []
        for b in (x for x in bills if f"{x['bill_date'][5:7]}{x['bill_date'][:4]}" == period):
            heads = {h: int(b[f"{h}_paise"] or 0) - int(b[f"ineligible_itc_{h}_paise"] or 0) for h in ("igst", "cgst", "sgst", "cess")}
            net[b["id"]] = heads
            docs.append(rule_36_4.BookDocument(
                document_id=b["id"], label=b["bill_no"], supplier="", is_reverse_charge=bool(b["is_reverse_charge"]),
                was_examined=b["id"] not in unexamined, **{f"{h}_paise": v for h, v in heads.items()}))
        verdicts.extend(rule_36_4.assess(docs, two_b, True).verdicts)
    not_allowed = {v.document_id for v in verdicts if v.verdict not in (rule_36_4.ALLOWED, rule_36_4.SELF_ASSESSED)}
    return two_b, net, unexamined, not_allowed


def test_the_database_keeps_exactly_the_bills_the_pass_does_not_allow(db):
    b = _world(db)
    got = _database(db)
    two_b, net, unexamined, not_allowed = _python(db)
    names = {v: k for k, v in b.items()}
    assert {names[i] for i in got} == {names[i] for i in not_allowed}
    # The scenarios are not vacuous: each kind of verdict is among them, and so is each kind of exclusion.
    assert {"not_in_2b", "blocked", "over_cgst", "heads_swapped", "recorded_after", "two_rows_one_blocked", "row_outside_the_months",
            "cess_over", "paid_not_in_2b"} <= {names[i] for i in got}
    assert not ({"matched", "reverse_charge", "all_blocked_17_5", "part_blocked_17_5", "recorded_exactly_at", "opening", "deleted",
                 "draft", "unreconciled_month", "two_rows_summing", "more_in_2b", "other_client", "other_firm"}
                & {names[i] for i in got})


def test_each_candidate_carries_the_inputs_the_pass_reads(db):
    _world(db)
    got = _database(db)
    two_b, net, unexamined, _ = _python(db)
    assert got
    for bid, row in got.items():
        assert {h: row[f"{h}_paise"] for h in ("igst", "cgst", "sgst", "cess")} == net[bid]
        assert row["examined"] is (bid not in unexamined)
        doc = two_b.get(bid)
        assert row["matched"] is (doc is not None)
        if doc is not None:
            assert (row["blocked"], row["reason_code"]) == (doc.itc_available == "N", doc.reason_code)
            assert (row["filed_igst_paise"], row["filed_cgst_paise"], row["filed_sgst_paise"], row["filed_cess_paise"]) == \
                (doc.igst_paise, doc.cgst_paise, doc.sgst_paise, doc.cess_paise)
        assert row["vendor_name"] == "Acme" and row["vendor_gstin"] == "29AAAAA1111A1Z5"


def test_an_empty_set_of_months_answers_nothing_and_a_firm_reads_only_its_own_rows(db):
    _world(db)
    assert _json(db, f"SELECT public.itc_time_bar_candidates('{FIRM}', '{CLIENT}', '{FROM}', '{TO}', ARRAY[]::text[]);") == []
    # The other firm's one bill carries this client's id (a forged row): asked as that firm, only that row comes back, and it reads as
    # not examined because the reconciliation headers are the first firm's.
    other = _json(db, f"SELECT public.itc_time_bar_candidates('{OTHER_FIRM}', '{CLIENT}', '{FROM}', '{TO}', ARRAY{PERIODS}::text[]);")
    assert [(r["bill_no"], r["examined"], r["vendor_name"]) for r in other] == [("OTHER-FIRM", False, None)]


def test_the_function_runs_as_its_caller_writes_nothing_and_anon_cannot_call_it(db):
    assert _scalar(db, f"SELECT prosecdef::text || '|' || provolatile::text FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;") == "false|s"
    assert _scalar(db, f"SELECT has_function_privilege('anon', '{FUNCTION}', 'EXECUTE');") == "f"
    for role in ("authenticated", "service_role"):
        assert _scalar(db, f"SELECT has_function_privilege('{role}', '{FUNCTION}', 'EXECUTE');") == "t", role


def test_the_rollback_drops_it_and_the_file_can_be_run_again(db):
    def present():
        return _scalar(db, f"SELECT to_regprocedure('{FUNCTION}') IS NOT NULL;")
    assert present() == "t"
    assert subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True).returncode == 0
    assert present() == "f"
    for _ in range(2):
        assert subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(FILE)], capture_output=True).returncode == 0
    assert present() == "t"
