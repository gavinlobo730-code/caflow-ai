"""Migration 535 — the record that a return was filed is written by the API only (ledger POST-A-319).

WHAT WAS WRONG
    `filings` is what `period_lock_reason` and `journal_period_lock_reason` read to refuse a posting, an edit or a discard inside
    a period whose GSTR-1 or GSTR-3B has gone to the portal. The table was granted INSERT, UPDATE and DELETE to `authenticated`
    with the firm and the assignment scope as its only policies, so an assigned Reviewer read "GSTR-3B covering this date was
    filed on 20 Jul 2025", deleted the row (DELETE 1), and the same function then answered open. The only writer in the API is
    `gst_filing_record_service.record_filing`, which took the request's own client.

WHAT THIS HOLDS (real Postgres)
    * a signed-in role holds NO write privilege on `filings` at table, column or PUBLIC level (proved again from a database that
      granted everything), `service_role` keeps its writes, and a signed-in member still READS it, scoped to their clients;
    * a Partner, a Manager, an Executive and a Reviewer assigned to the client are each refused INSERT, UPDATE and DELETE BY THE
      PRIVILEGE, the row survives and both period functions still call the date closed;
    * the real `record_filing`, run with the request's client as an assigned Manager and the service role as the privileged
      one, records the filing (the lock then closes the date), is idempotent, refuses a client of another firm and writes
      nothing, and without a privileged client it would be refused by the database (the control);
    * the rollback gives the verbs back and the Reviewer's delete lifts the lock again (the defect, reproduced); a re-apply ends
      it; applying twice is harmless.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")
_STEM = "535_the_record_that_a_return_was_filed_is_written_by_the_api_only"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the filings proof requires HARNESS_PG + psql",
)

FIRM = "53500000-0000-0000-0000-000000000001"
OTHER_FIRM = "53500000-0000-0000-0000-000000000002"
CLIENT_A = "53500000-0000-0000-0000-0000000000a1"
CLIENT_B = "53500000-0000-0000-0000-0000000000b2"
OTHER_CLIENT = "53500000-0000-0000-0000-0000000000c3"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("53500000-0000-0000-0000-00000000000a", "53500000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("53500000-0000-0000-0000-00000000000b", "53500000-1111-0000-0000-000000000002", "Manager"),
    "executive_a": ("53500000-0000-0000-0000-00000000000e", "53500000-1111-0000-0000-000000000004", "Executive"),
    "reviewer_a": ("53500000-0000-0000-0000-000000000011", "53500000-1111-0000-0000-000000000007", "Reviewer"),
    "manager_none": ("53500000-0000-0000-0000-00000000000c", "53500000-1111-0000-0000-000000000003", "Manager"),
}
TABLE = "filings"
FILED_DAY = "2025-07-15"                  # inside July 2025, whose GSTR-3B was filed on 20 August
DENIED = f"permission denied for table {TABLE}"
CLOSED = "GSTR-3B covering this date was filed on"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _one(dsn: str, sql: str) -> str:
    return _rows(dsn, sql)[0][0]


def _call(dsn: str, who: str, sql: str) -> tuple[bool, str]:
    prefix = f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", prefix + sql], capture_output=True, text=True)
    if r.returncode != 0:
        m = re.search(r"ERROR:\s+(.*)", r.stderr)
        return False, (m.group(1) if m else r.stderr).strip()
    out = [l for l in r.stdout.splitlines() if l.strip() and l.strip() != "SET"]
    return True, (out[-1].strip() if out else "")


def _reason(dsn: str, fn: str = "period_lock_reason", client: str = CLIENT_A, who: str | None = None) -> str:
    sql = f"SELECT coalesce(public.{fn}('{FIRM}', '{client}', '{FILED_DAY}'::date), '<open>')"
    if who is None:
        return _one(dsn, sql)
    ok, out = _call(dsn, who, sql)
    assert ok, out
    return out


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e535_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship'),
                        ('{OTHER_CLIENT}', '{OTHER_FIRM}', 'X', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}');
            INSERT INTO filings (client_id, firm_id, filing_type, period_start, period_end, filed_date, status)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'GSTR-3B', '2025-07-01', '2025-07-31', '2025-08-20', 'filed');
        """)
        assert seed.returncode == 0, seed.stderr
        assert CLOSED in _reason(d), "the fixture is wrong: the filed return must close the date"
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── PRIVILEGES ──────────────────────────────────────────────────────────────────

def _no_write(dsn: str) -> None:
    for role in ("authenticated", "anon"):
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _one(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{verb}')") == "f", (role, verb)
        for verb in ("INSERT", "UPDATE"):
            assert _one(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{TABLE}', '{verb}')") == "f", (role, verb)
    held = _rows(dsn, f"""SELECT a.privilege_type FROM pg_class c, aclexplode(c.relacl) a
                           WHERE c.oid = 'public.{TABLE}'::regclass AND a.grantee = 0 AND a.privilege_type IN
                                 ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')""")
    assert held == [], held


def test_no_signed_in_role_holds_a_write_on_the_table_and_the_service_role_keeps_its_own(dsn):
    _no_write(dsn)
    for verb in ("INSERT", "UPDATE", "DELETE", "SELECT"):
        assert _one(dsn, f"SELECT has_table_privilege('service_role', 'public.{TABLE}', '{verb}')") == "t", verb
    assert _one(dsn, f"SELECT has_table_privilege('authenticated', 'public.{TABLE}', 'SELECT')") == "t"
    assert _one(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'SELECT')") == "f"


def test_the_migration_takes_every_privilege_away_from_a_database_that_granted_them_all(dsn):
    """Production's platform defaults grant more than a migration-built database does (anon and PUBLIC), so the revocation is
    proved from the worst case: grant everything first, then apply the migration."""
    assert _psql(dsn, f"GRANT ALL ON public.{TABLE} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _one(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'DELETE')") == "t", "the fixture must start open"
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    _no_write(dsn)
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _one(dsn, f"SELECT has_table_privilege('service_role', 'public.{TABLE}', '{verb}')") == "t", verb


# ── THE FORGERY THE REVIEW FOUND ────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "reviewer_a"])
def test_every_write_is_refused_by_the_privilege_and_the_lock_still_holds(dsn, who):
    for label, sql in {
        "delete the record": f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'",
        "move it to another month": f"UPDATE {TABLE} SET period_start = '2025-09-01', period_end = '2025-09-30' WHERE client_id = '{CLIENT_A}'",
        "un-file it": f"UPDATE {TABLE} SET filed_date = NULL WHERE client_id = '{CLIENT_A}'",
        "add one": f"INSERT INTO {TABLE} (client_id, firm_id, filing_type, period_start, period_end, status) "
                   f"VALUES ('{CLIENT_A}', '{FIRM}', 'GSTR-1', '2025-07-01', '2025-07-31', 'draft')",
    }.items():
        ok, msg = _call(dsn, who, sql)
        assert not ok and DENIED in msg, (who, label, msg)
    assert _one(dsn, f"SELECT count(*) FROM {TABLE}") == "1"
    for fn in ("period_lock_reason", "journal_period_lock_reason"):
        assert CLOSED in _reason(dsn, fn, who=who), (who, fn)


def test_reads_are_unchanged_and_scoped_to_the_callers_clients(dsn):
    def count(who: str) -> int:
        ok, out = _call(dsn, who, f"SELECT count(*) FROM {TABLE}")
        assert ok, out
        return int(out)

    assert count("partner") == 1 and count("manager_a") == 1 and count("reviewer_a") == 1
    assert count("manager_none") == 0


# ── THE REAL WRITER ─────────────────────────────────────────────────────────────

@pytest.fixture()
def writer(dsn, monkeypatch):
    import core.db_provider
    import services.gst_filing_record_service as svc

    class W:
        pass

    w = W()
    w.svc = svc
    w.request = SignedInDb(dsn, role="authenticated", auth_user_id=PEOPLE["manager_a"][1])
    w.service = SignedInDb(dsn, role="service_role")
    w.dsn = dsn
    w.patch = monkeypatch
    w.provider = core.db_provider
    w.privileged = lambda: monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: w.service)
    w.none = lambda: monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    return w


def _record(w, client=CLIENT_B, firm=FIRM, **kw):
    kw.setdefault("filed_date", "2025-08-11")
    return w.svc.record_filing(w.request, firm_id=firm, client_id=client, filing_type="GSTR-3B", period="072025", **kw)


def test_record_filing_writes_with_the_privileged_client_and_the_lock_then_closes_the_date(writer):
    writer.privileged()
    before = _reason(writer.dsn, client=CLIENT_B)
    assert before == "<open>"
    row = _record(writer)
    assert row["client_id"] == CLIENT_B
    assert CLOSED in _reason(writer.dsn, client=CLIENT_B)
    assert _one(writer.dsn, f"SELECT count(*) FROM {TABLE} WHERE client_id = '{CLIENT_B}'") == "1"


def test_record_filing_twice_leaves_one_row_and_updates_the_date(writer):
    writer.privileged()
    _record(writer, filed_date="2025-08-11", arn="AA270825000001A")
    _record(writer, filed_date="2025-08-12", arn="AA270825000002B")
    assert _rows(writer.dsn, f"SELECT filed_date, acknowledgement_number FROM {TABLE} WHERE client_id = '{CLIENT_B}'") == \
        [["2025-08-12", "AA270825000002B"]]


def test_record_filing_revives_a_filing_somebody_soft_deleted_and_the_lock_closes_again(writer):
    """Before 535 an assigned member could soft-delete the row over PostgREST, and the period functions read live rows only. The
    lookup finds the deleted row, so recording the return again must clear `deleted_at`: updating a row the lock cannot see would
    answer 'locked' on the screen while the books stay open."""
    writer.privileged()
    assert _psql(writer.dsn, f"UPDATE {TABLE} SET deleted_at = now() WHERE client_id = '{CLIENT_A}'").returncode == 0
    assert _reason(writer.dsn) == "<open>", "the fixture must start with the lock lifted"
    row = _record(writer, client=CLIENT_A, filed_date="2025-08-20")
    assert row["client_id"] == CLIENT_A
    assert _rows(writer.dsn, f"SELECT count(*), count(deleted_at) FROM {TABLE} WHERE client_id = '{CLIENT_A}'") == [["1", "0"]]
    assert CLOSED in _reason(writer.dsn)


def test_record_filing_refuses_a_client_of_another_firm_and_writes_nothing(writer):
    writer.privileged()
    from core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        _record(writer, client=OTHER_CLIENT)
    assert _one(writer.dsn, f"SELECT count(*) FROM {TABLE} WHERE client_id = '{OTHER_CLIENT}'") == "0"


def test_without_a_privileged_client_the_signed_in_write_is_refused_the_control(writer):
    """The previous behaviour: the request's own client. The database refuses it, which is why the swap exists."""
    writer.none()
    with pytest.raises(SignedInError) as e:
        _record(writer)
    assert DENIED in e.value.message
    assert _one(writer.dsn, f"SELECT count(*) FROM {TABLE} WHERE client_id = '{CLIENT_B}'") == "0"


# ── THE ROLLBACK, THE DEFECT AND A SECOND APPLY ─────────────────────────────────

def test_the_rollback_brings_the_lifted_lock_back_and_a_reapply_ends_it_and_twice_is_harmless(dsn):
    delete = f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'"
    assert not _call(dsn, "reviewer_a", delete)[0]
    done = _psql_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    ok, msg = _call(dsn, "reviewer_a", delete)
    assert ok, f"after the rollback the Reviewer deletes the record (the negative control): {msg}"
    assert _reason(dsn, who="reviewer_a") == "<open>", "and the same function now answers open for a filed month"
    assert _psql(dsn, f"INSERT INTO {TABLE} (client_id, firm_id, filing_type, period_start, period_end, filed_date, status) "
                      f"VALUES ('{CLIENT_A}', '{FIRM}', 'GSTR-3B', '2025-07-01', '2025-07-31', '2025-08-20', 'filed')").returncode == 0
    for _ in range(2):
        done = _psql_file(dsn, MIGRATION)
        assert done.returncode == 0, done.stderr
    ok, msg = _call(dsn, "reviewer_a", delete)
    assert not ok and DENIED in msg, msg
