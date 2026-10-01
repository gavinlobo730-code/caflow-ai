"""Migration 474, against a real Postgres: what the credit-ledger chain stands on
(gst-06).

WHAT IS ASSERTED
    * `gstr3b_returns` takes the ten credit columns as SETS — all four closing
      heads and their date together or none, all four opening heads together or
      none — and never a negative one. A mock suite cannot see a CHECK, and a
      closing balance with a missing head would be read as nil by the next return.
    * A return saved before 474 (all ten NULL) is still valid: NULL is "nobody
      recorded this", and NOT VALID-then-VALIDATE must not have refused it.
    * `gst_credit_ledger_openings` is one row per (client, GSTIN, window), never
      negative.
    * It is assignment-scoped the way every client table is: a member not assigned
      to the client cannot read a keyed balance, another firm cannot, and a
      member of the right firm can READ it but not WRITE it — `authenticated` has
      SELECT only and the one door that writes is the route, under the service key.
    * The browser's own save (the firm-level screen upserts `gstr3b_returns` as
      `authenticated`) can write the ten columns, because that is the call it makes.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="the credit-ledger chain proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000474"
OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000475"
CLIENT_A = "cccccccc-0000-0000-0000-00000000a474"   # the Executive is assigned here
CLIENT_B = "cccccccc-0000-0000-0000-00000000b474"   # ... and NOT here
AUTH_PARTNER = "11111111-1111-1111-1111-111111111474"
AUTH_EXEC = "22222222-2222-2222-2222-222222222474"
AUTH_OTHER = "33333333-3333-3333-3333-333333333474"
USER_PARTNER = "bbbbbbbb-0000-0000-0000-00000000a474"
USER_EXEC = "bbbbbbbb-0000-0000-0000-00000000b474"
USER_OTHER = "bbbbbbbb-0000-0000-0000-00000000c474"
GSTIN = "27AAPFU0939F1ZV"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA", "-F", "|"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\", "
            f"\"role\": \"authenticated\"}}'; SET ROLE authenticated; ")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m474_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_PARTNER}','p474@test.in'), ('{AUTH_EXEC}','e474@test.in'),
              ('{AUTH_OTHER}','o474@test.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M474 Firm','m474@test.in'),
              ('{OTHER_FIRM}','M474 Other Firm','m474o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) VALUES
              ('{USER_PARTNER}','{FIRM}','{AUTH_PARTNER}','p474@test.in','Partner 474','Partner'),
              ('{USER_EXEC}',   '{FIRM}','{AUTH_EXEC}',   'e474@test.in','Exec 474','Executive'),
              ('{USER_OTHER}',  '{OTHER_FIRM}','{AUTH_OTHER}','o474@test.in','Other 474','Partner');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A 474','Private Limited'),
              ('{CLIENT_B}','{FIRM}','Client B 474','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
              ('{FIRM}','{USER_EXEC}','{CLIENT_A}');
            INSERT INTO gst_credit_ledger_openings
              (firm_id, client_id, gstin, window_start, igst_paise, cgst_paise, sgst_paise, cess_paise)
            VALUES
              ('{FIRM}','{CLIENT_A}','{GSTIN}','2026-05-01', 365496165, 0, 0, 0),
              ('{FIRM}','{CLIENT_B}','{GSTIN}','2026-05-01', 111, 0, 0, 0);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _return(period: str, extra_cols: str = "", extra_vals: str = "") -> str:
    return (f"INSERT INTO gstr3b_returns (firm_id, client_id, period, gstin, status{extra_cols}) "
            f"VALUES ('{FIRM}','{CLIENT_A}','{period}','{GSTIN}','draft'{extra_vals});")


FULL_CLOSING = ("credit_closing_igst_paise, credit_closing_cgst_paise, credit_closing_sgst_paise, "
                "credit_closing_cess_paise, credit_closing_as_of")


def test_a_return_saved_before_474_with_all_ten_columns_null_is_valid(db):
    assert _psql(db, _return("042026")).returncode == 0


def test_a_whole_closing_and_a_whole_opening_are_accepted(db):
    r = _psql(db, _return(
        "052026",
        ", credit_opening_igst_paise, credit_opening_cgst_paise, credit_opening_sgst_paise, "
        f"credit_opening_cess_paise, {FULL_CLOSING}, credit_opening_source",
        ", 365496165, 0, 0, 0, 365396165, 0, 0, 0, '2026-05-31', 'recorded'"))
    assert r.returncode == 0, r.stderr


def test_a_closing_with_a_head_missing_is_refused_not_read_as_nil(db):
    r = _psql(db, _return(
        "052026", f", credit_closing_igst_paise, credit_closing_as_of",
        ", 5, '2026-05-31'"))
    assert r.returncode != 0 and "credit_closing_is_a_set" in r.stderr


def test_a_closing_balance_with_no_date_is_refused(db):
    r = _psql(db, _return(
        "052026",
        ", credit_closing_igst_paise, credit_closing_cgst_paise, credit_closing_sgst_paise, "
        "credit_closing_cess_paise", ", 1, 2, 3, 4"))
    assert r.returncode != 0 and "credit_closing_is_a_set" in r.stderr


def test_an_opening_with_a_head_missing_is_refused(db):
    r = _psql(db, _return("052026", ", credit_opening_igst_paise, credit_opening_cgst_paise",
                          ", 1, 2"))
    assert r.returncode != 0 and "credit_opening_is_a_set" in r.stderr


def test_a_negative_balance_is_refused_in_either_column_set(db):
    r = _psql(db, _return(
        "052026", f", {FULL_CLOSING}", ", -1, 0, 0, 0, '2026-05-31'"))
    assert r.returncode != 0 and "credit_is_never_negative" in r.stderr
    k = _psql(db, f"UPDATE gst_credit_ledger_openings SET cgst_paise = -5 WHERE client_id = '{CLIENT_A}';")
    assert k.returncode != 0 and "never_negative" in k.stderr


def test_an_unknown_opening_source_is_refused(db):
    r = _psql(db, _return("052026", ", credit_opening_source", ", 'guessed'"))
    assert r.returncode != 0 and "opening_source_check" in r.stderr


def test_one_balance_per_client_registration_and_window(db):
    r = _psql(db, f"""INSERT INTO gst_credit_ledger_openings (firm_id, client_id, gstin, window_start)
                      VALUES ('{FIRM}','{CLIENT_A}','{GSTIN}','2026-05-01');""")
    assert r.returncode != 0 and "one_per_window" in r.stderr


# ── Who may read a keyed balance, and who may write one ─────────────────────

def _count(db, who: str, client: str) -> int:
    r = _psql(db, _as(who) + f"SELECT count(*) FROM gst_credit_ledger_openings WHERE client_id='{client}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def test_a_partner_reads_every_clients_balance_and_an_assigned_executive_only_theirs(db):
    assert _count(db, AUTH_PARTNER, CLIENT_A) == 1
    assert _count(db, AUTH_PARTNER, CLIENT_B) == 1
    assert _count(db, AUTH_EXEC, CLIENT_A) == 1
    assert _count(db, AUTH_EXEC, CLIENT_B) == 0, (
        "the RESTRICTIVE assignment policy hides a client the member is not assigned to")


def test_another_firms_partner_reads_nothing(db):
    assert _count(db, AUTH_OTHER, CLIENT_A) == 0
    assert _count(db, AUTH_OTHER, CLIENT_B) == 0


def test_authenticated_cannot_write_a_keyed_balance_only_the_route_can(db):
    r = _psql(db, _as(AUTH_PARTNER) + f"""
        INSERT INTO gst_credit_ledger_openings (firm_id, client_id, gstin, window_start, igst_paise)
        VALUES ('{FIRM}','{CLIENT_A}','{GSTIN}','2026-06-01', 999);""")
    assert r.returncode != 0 and "permission denied" in r.stderr
    u = _psql(db, _as(AUTH_PARTNER) + "UPDATE gst_credit_ledger_openings SET igst_paise = 1;")
    assert u.returncode != 0 and "permission denied" in u.stderr


def test_the_service_role_can_write_it(db):
    r = _psql(db, f"""SET ROLE service_role;
        INSERT INTO gst_credit_ledger_openings (firm_id, client_id, gstin, window_start, igst_paise)
        VALUES ('{FIRM}','{CLIENT_A}','{GSTIN}','2026-06-01', 999);""")
    assert r.returncode == 0, r.stderr


def test_the_firm_level_screens_own_save_can_write_the_ten_columns_as_authenticated(db):
    """`saveGSTR3BReturn` upserts `gstr3b_returns` over PostgREST as the member."""
    r = _psql(db, _as(AUTH_PARTNER) + _return(
        "062026",
        f", {FULL_CLOSING}, credit_opening_source",
        ", 1, 2, 3, 4, '2026-06-30', 'previous_return'"))
    assert r.returncode == 0, r.stderr


def test_the_chain_lookup_finds_the_return_ending_the_day_before(db):
    _psql(db, _return("052026", f", {FULL_CLOSING}", ", 7, 8, 9, 10, '2026-05-31'"))
    r = _psql(db, f"""SELECT period, credit_closing_igst_paise FROM gstr3b_returns
                      WHERE client_id='{CLIENT_A}' AND gstin='{GSTIN}'
                        AND credit_closing_as_of = DATE '2026-06-01' - 1;""", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "052026|7"


def test_the_rollback_leaves_a_database_without_the_chain(db):
    sql = (API_ROOT / "migrations"
           / "474_the_credit_ledger_opens_with_what_the_last_return_left_in_it_rollback.sql"
           ).read_text(encoding="utf-8")
    assert _psql(db, sql).returncode == 0
    gone = _psql(db, """SELECT count(*) FROM information_schema.columns
                        WHERE table_name='gstr3b_returns' AND column_name LIKE 'credit\\_%';""",
                 tuples=True)
    assert gone.stdout.strip() == "0"
    t = _psql(db, "SELECT to_regclass('public.gst_credit_ledger_openings');", tuples=True)
    assert t.stdout.strip() == ""
    # and the forward migration applies again cleanly (idempotent)
    fwd = (API_ROOT / "migrations"
           / "474_the_credit_ledger_opens_with_what_the_last_return_left_in_it.sql"
           ).read_text(encoding="utf-8")
    assert _psql(db, fwd).returncode == 0
    assert _psql(db, fwd).returncode == 0
