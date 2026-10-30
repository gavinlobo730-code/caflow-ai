"""A grant of access names a member of the firm, and a client of the firm, that writes it, and a grant that does not grants
nothing (migration 530, POST-A-308 and the same hole in `user_permissions`).

WHAT WAS WRONG
    `user_client_assignments` and `user_permissions` decide what a member of a firm may reach: `my_assigned_client_ids()` and
    `can_access_client()` read the first, `my_permission()` the second, each by the member alone. The write policies asked that
    the row's `firm_id` was the caller's firm and that the caller was a Partner; nothing asked that the row's `user_id` was a
    member of that firm or, for an assignment, its `client_id` a client of it. A Partner of firm G could therefore write
    (firm G, a member of firm F, a client of firm F), or (firm G, a member of F, 'assignment', 'write', true), and F's member
    read that client's rows from then on, or assigned themselves the rest, with F's own Partners unable to see the row.

WHAT THIS HOLDS
    * THE REFUSALS: a Partner of the OTHER firm is refused every shape of the cross-firm row, in both tables, by INSERT and by
      an UPDATE that re-points an existing row; the firm's own Partner is refused a member or a client of another firm too,
      and the row of their own firm and their own members is accepted (the same statement, so it is the policy that refused).
    * A PLANTED ROW GRANTS NOTHING: rows already in either table (written while the hole was open, simulated by the admin)
      are not counted by `my_assigned_client_ids()`, `can_access_client()` or `my_permission()`, the victim's member reads
      none of the victim's client's rows through them and cannot assign themselves more, and a legitimate row next to them
      still works; with the migration rolled back the same rows open the client and grant the permission (the negative
      control).
    * THE HELPERS answer about the caller's firm only: true for a member (client) of the caller's firm, false for one of
      another firm, for an id that does not exist, for NULL, and for a suspended or signed-out caller, and the foreign and the
      absent id cannot be told apart.
    * THE WARNING counts the rows that name another firm, in each table (a row whose only defect is its member, one whose
      only defect is its client, and one with both), and removes none of them; applied through the REAL runner, its line is in
      the run's report (`messages`), which is where the production apply log shows it. A NOTICE there reached nobody.
    * EACH CONDITION of the readers is needed on its own: a row whose only defect is the client's firm, and one whose only
      defect is the row's firm, are each ignored by `my_assigned_client_ids()` and `can_access_client()`.
    * A REFUSAL IS THE POLICY'S: the statements the policies refuse fail with SQLSTATE 42501 (row-level security), not with a
      constraint or a missing grant that would make the check pass for the wrong reason.
    * THE ROLLBACK restores the policies and the functions exactly, a re-apply closes the hole, and a second run changes nothing.
    * THE PLAN: a signed-in scan of a client table still asks the callers' clients once (a hashed sub-plan), and the function
      that returns them takes the member and the firm ONCE (as scalar sub-selects) and not once per assigned row.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from tests._cross_tenant_rows import LEGACY_ROWS_ALLOWED, allow_legacy_rows

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the cross-firm assignment proof requires HARNESS_PG + psql",
)

_STEM = "530_a_grant_of_access_names_a_member_and_a_client_of_the_firm_that_writes_it"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

F = "53000000-0000-0000-0000-00000000000f"          # the victim firm
G = "53000000-0000-0000-0000-00000000000a"          # the firm of the Partner who writes the row
CLIENT_F1 = "53000000-0000-0000-0000-0000000000f1"
CLIENT_F2 = "53000000-0000-0000-0000-0000000000f2"
CLIENT_G1 = "53000000-0000-0000-0000-0000000000a1"
CLIENT_G2 = "53000000-0000-0000-0000-0000000000a2"
PEOPLE = {            # name: (users.id, auth id, role, firm, active)
    "partner_f": ("53000000-0000-0000-0000-000000000001", "53000000-1111-0000-0000-000000000001", "Partner", F, True),
    "manager_f": ("53000000-0000-0000-0000-000000000002", "53000000-1111-0000-0000-000000000002", "Manager", F, True),
    "partner_g": ("53000000-0000-0000-0000-000000000003", "53000000-1111-0000-0000-000000000003", "Partner", G, True),
    "manager_g": ("53000000-0000-0000-0000-000000000004", "53000000-1111-0000-0000-000000000004", "Manager", G, True),
    "suspended_f": ("53000000-0000-0000-0000-000000000005", "53000000-1111-0000-0000-000000000005", "Partner", F, False),
}
UID = {name: v[0] for name, v in PEOPLE.items()}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err'; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _refusal_of(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, undo it, and report `ok` or the `SQLSTATE: message` the database refused it with."""
    do = (f"DO $$ BEGIN BEGIN {dml}; RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN RAISE NOTICE 'refusal=ok'; "
          f"WHEN OTHERS THEN RAISE NOTICE 'refusal=%: %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+refusal=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _insert(firm: str, user: str, client: str) -> str:
    return f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{firm}', '{UID[user]}', '{client}')"


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e530_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f, _act) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', {'true' if act else 'false'})"
                            for n, (i, a, r, f, act) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'F', 'f@t.in'), ('{G}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_F1}', '{F}', 'F one', 'Proprietorship'), ('{CLIENT_F2}', '{F}', 'F two', 'Proprietorship'),
                        ('{CLIENT_G1}', '{G}', 'G one', 'Proprietorship'), ('{CLIENT_G2}', '{G}', 'G two', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO customers (firm_id, client_id, name)
                 VALUES ('{F}', '{CLIENT_F1}', 'cust F1'), ('{F}', '{CLIENT_F2}', 'cust F2'), ('{G}', '{CLIENT_G1}', 'cust G1');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{F}', '{UID["manager_f"]}', '{CLIENT_F1}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE REFUSALS ────────────────────────────────────────────────────────────────

def test_a_partner_of_another_firm_cannot_write_an_assignment_naming_the_victims_member_or_client(dsn):
    # the row the review reproduced: their firm, the victim's member, the victim's client
    assert _count_op(dsn, "partner_g", _insert(G, "manager_f", CLIENT_F2)) == "err", "the planting of the review is still possible"
    assert _count_op(dsn, "partner_g", _insert(G, "manager_f", CLIENT_G1)) == "err", "a member of another firm was assigned to my client"
    assert _count_op(dsn, "partner_g", _insert(G, "manager_g", CLIENT_F2)) == "err", "my member was assigned to another firm's client"
    # a row that names the victim's firm is refused by 478's own rule
    assert _count_op(dsn, "partner_g", _insert(F, "manager_f", CLIENT_F2)) == "err"
    # the same statement shape with everything their own is accepted, so it is the check that refused the others
    assert _count_op(dsn, "partner_g", _insert(G, "manager_g", CLIENT_G1)) == "1"


def test_the_firms_own_partner_assigns_their_members_to_their_clients_and_to_nobody_elses(dsn):
    assert _count_op(dsn, "partner_f", _insert(F, "manager_f", CLIENT_F2)) == "1", "a Partner cannot assign their own member to their own client"
    assert _count_op(dsn, "partner_f", _insert(F, "manager_f", CLIENT_G1)) == "err", "a Partner assigned a member to another firm's client"
    assert _count_op(dsn, "partner_f", _insert(F, "manager_g", CLIENT_F2)) == "err", "a Partner assigned another firm's member to their client"
    assert _count_op(dsn, "partner_f", _insert(G, "manager_f", CLIENT_F2)) == "err", "a Partner wrote a row naming another firm"


def test_a_member_who_is_not_a_partner_still_cannot_write_an_assignment(dsn):
    assert _count_op(dsn, "manager_f", _insert(F, "manager_f", CLIENT_F2)) == "err"


def test_an_update_cannot_re_point_a_row_at_a_member_or_a_client_of_another_firm(dsn):
    row = f"user_id = '{UID['manager_f']}' AND client_id = '{CLIENT_F1}'"
    assert _count_op(dsn, "partner_f", f"UPDATE user_client_assignments SET client_id = '{CLIENT_G1}' WHERE {row}") == "err"
    assert _count_op(dsn, "partner_f", f"UPDATE user_client_assignments SET user_id = '{UID['manager_g']}' WHERE {row}") == "err"
    assert _count_op(dsn, "partner_f", f"UPDATE user_client_assignments SET client_id = '{CLIENT_F2}' WHERE {row}") == "1"
    # the other firm's Partner cannot reach the row at all, and cannot re-point one of their own at the victim
    assert _count_op(dsn, "partner_g", f"UPDATE user_client_assignments SET client_id = '{CLIENT_F2}' WHERE {row}") == "0"
    assert _psql(dsn, _insert(G, "manager_g", CLIENT_G1)).returncode == 0
    mine = f"user_id = '{UID['manager_g']}' AND client_id = '{CLIENT_G1}'"
    assert _count_op(dsn, "partner_g", f"UPDATE user_client_assignments SET client_id = '{CLIENT_F1}' WHERE {mine}") == "err"
    assert _count_op(dsn, "partner_g", f"UPDATE user_client_assignments SET user_id = '{UID['manager_f']}' WHERE {mine}") == "err"


def test_a_suspended_partner_writes_nothing(dsn):
    assert _count_op(dsn, "suspended_f", _insert(F, "manager_f", CLIENT_F2)) == "err"


def test_every_refusal_is_row_level_security_and_nothing_else(dsn):
    """`_count_op` reports any failure as `err`, so a refusal for the wrong reason (a unique key, a missing grant) would pass
    for the check. Each refusal below is the policy's: SQLSTATE 42501 with the row-security message."""
    refused = [
        ("partner_g", _insert(G, "manager_f", CLIENT_F2)),
        ("partner_g", _insert(G, "manager_f", CLIENT_G1)),
        ("partner_g", _insert(G, "manager_g", CLIENT_F2)),
        ("partner_f", _insert(F, "manager_f", CLIENT_G1)),
        ("partner_f", _insert(F, "manager_g", CLIENT_F2)),
        ("partner_g", _grant(G, "manager_f")),
        ("partner_f", _grant(G, "manager_f")),
        ("partner_f", _grant(F, "manager_g")),
        ("manager_f", _insert(F, "manager_f", CLIENT_F2)),
        ("manager_f", _grant(F, "manager_f")),
        ("suspended_f", _insert(F, "manager_f", CLIENT_F2)),
    ]
    for who, dml in refused:
        got = _refusal_of(dsn, who, dml)
        assert got.startswith("42501:") and "row-level security" in got, (who, dml, got)
    # and the same statement shape accepted, so the refusals above are not the table refusing everything
    assert _refusal_of(dsn, "partner_f", _insert(F, "manager_f", CLIENT_F2)) == "ok"
    assert _refusal_of(dsn, "partner_f", _grant(F, "manager_f")) == "ok"


# ── A PLANTED ROW GRANTS NOTHING ────────────────────────────────────────────────

def _plant(dsn: str) -> None:
    """Rows as the hole wrote them: the other firm's id on the row, the victim's member and the victim's client; and the other
    firm's member on the victim's client. The admin writes them, because the policy no longer lets anyone else."""
    # Migration 565 refuses these two rows now (the other firm's id on the victim's client), and legacy data may still hold them:
    # the assignment readers must go on ignoring them, so they are planted with 565's triggers off.
    done = _psql(dsn, LEGACY_ROWS_ALLOWED + f"{_insert(G, 'manager_f', CLIENT_F2)}; {_insert(G, 'manager_g', CLIENT_F1)}")
    assert done.returncode == 0, done.stderr


def test_a_planted_row_grants_nothing_and_a_legitimate_assignment_still_does(dsn):
    _plant(dsn)
    f_sees = _lines_as(dsn, "manager_f", "SELECT count(*) FROM customers;")[-1]
    assert f_sees == "1", f"the victim's member reads {f_sees} customers: only client F one's, which the firm assigned them"
    ids = sorted(_lines_as(dsn, "manager_f", "SELECT my_assigned_client_ids();"))
    assert ids == [CLIENT_F1], ids
    assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{CLIENT_F2}');")[-1] == "f"
    assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{CLIENT_F1}');")[-1] == "t"
    # the other firm's member is no better placed by a row naming the victim's client
    assert _lines_as(dsn, "manager_g", f"SELECT can_access_client('{CLIENT_F1}');")[-1] == "f"
    assert _lines_as(dsn, "manager_g", "SELECT count(*) FROM customers;")[-1] == "0"


def test_each_condition_of_the_readers_is_needed_on_its_own(dsn):
    """`_plant`'s rows are each excluded by BOTH conditions, so either one alone could be deleted without a test noticing.
    These two have one defect each: the client of another firm on a row of the member's own firm, and a client of the row's
    own firm on a row the member's firm did not write."""
    # Planted with migration 565's triggers off (it refuses the client of another firm on a row, and legacy data may hold one).
    done = _psql(dsn, LEGACY_ROWS_ALLOWED + f"{_insert(F, 'manager_f', CLIENT_G1)}; {_insert(G, 'manager_f', CLIENT_G2)}")
    assert done.returncode == 0, done.stderr
    assert sorted(_lines_as(dsn, "manager_f", "SELECT my_assigned_client_ids();")) == [CLIENT_F1], "a row with one defect was counted"
    for client in (CLIENT_G1, CLIENT_G2, CLIENT_F2):
        assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{client}');")[-1] == "f", client
    assert _lines_as(dsn, "manager_f", "SELECT count(*) FROM customers;")[-1] == "1"


def test_the_rows_that_were_planted_would_have_granted_access_before_the_migration(dsn):
    """The negative control inside the file: with the migration rolled back, the same planted row opens the victim's client."""
    allow_legacy_rows(dsn)   # migration 565 would refuse the planting before the rolled-back policy is asked; this is the control for 530
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _count_op(dsn, "partner_g", _insert(G, "manager_f", CLIENT_F2)) == "1", "the rolled-back policy no longer lets the planting through"
    _plant(dsn)
    assert _lines_as(dsn, "manager_f", "SELECT count(*) FROM customers;")[-1] == "2", "the planted row did not open the client"
    assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{CLIENT_F2}');")[-1] == "t", "can_access_client does not read the planted row"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _lines_as(dsn, "manager_f", "SELECT count(*) FROM customers;")[-1] == "1", "the migration did not close what the planted row opened"
    assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{CLIENT_F2}');")[-1] == "f"
    # and the rollback puts the function back as it was: the planted row opens the client to it again
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _lines_as(dsn, "manager_f", f"SELECT can_access_client('{CLIENT_F2}');")[-1] == "t", "the rollback did not restore can_access_client"
    assert _psql_file(dsn, MIGRATION).returncode == 0


# ── THE SAME HOLE IN user_permissions ───────────────────────────────────────────

def _grant(firm: str, user: str, resource: str = "assignment", action: str = "write", granted: str = "true") -> str:
    return (f"INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) "
            f"VALUES ('{firm}', '{UID[user]}', '{resource}', '{action}', {granted})")


def test_a_partner_of_another_firm_cannot_write_a_permission_for_the_victims_member(dsn):
    assert _count_op(dsn, "partner_g", _grant(G, "manager_f")) == "err", "a permission was written for a member of another firm"
    assert _count_op(dsn, "partner_g", _grant(G, "manager_f", "client", "read", "false")) == "err", "a permission was taken from a member of another firm"
    assert _count_op(dsn, "partner_g", _grant(F, "manager_f")) == "err", "a row naming the other firm was written"
    # a member of the caller's OWN firm on a row that names ANOTHER firm: only the firm half of the check refuses it
    assert _count_op(dsn, "partner_f", _grant(G, "manager_f")) == "err", "a Partner wrote a permission row in another firm"
    assert _count_op(dsn, "partner_g", _grant(G, "manager_g")) == "1", "the other firm's Partner cannot grant their own member"
    assert _count_op(dsn, "partner_f", _grant(F, "manager_f")) == "1", "a Partner cannot grant their own member"
    assert _count_op(dsn, "partner_f", _grant(F, "manager_g")) == "err", "a Partner granted a member of another firm"
    assert _count_op(dsn, "manager_f", _grant(F, "manager_f")) == "err", "a Manager wrote a permission"


def test_an_update_cannot_re_point_a_permission_at_a_member_of_another_firm(dsn):
    assert _psql(dsn, _grant(F, "manager_f", "client", "read", "true")).returncode == 0
    assert _psql(dsn, _grant(G, "manager_g", "client", "read", "true")).returncode == 0
    mine = f"user_id = '{UID['manager_f']}' AND resource = 'client' AND action = 'read'"
    assert _count_op(dsn, "partner_f", f"UPDATE user_permissions SET user_id = '{UID['manager_g']}' WHERE {mine}") == "err"
    assert _count_op(dsn, "partner_f", f"UPDATE user_permissions SET granted = false WHERE {mine}") == "1"
    theirs = f"user_id = '{UID['manager_g']}' AND resource = 'client' AND action = 'read'"
    assert _count_op(dsn, "partner_g", f"UPDATE user_permissions SET user_id = '{UID['manager_f']}' WHERE {theirs}") == "err"


def _plant_permissions(dsn: str) -> None:
    # The rows name a member of ANOTHER firm on purpose: that is the planting 530 closed. Migration 566 would refuse the planting first.
    done = _psql(dsn, LEGACY_ROWS_ALLOWED + f"{_grant(G, 'manager_f', 'assignment', 'write', 'true')}; {_grant(G, 'manager_f', 'client', 'read', 'false')}")
    assert done.returncode == 0, done.stderr


def test_a_planted_permission_grants_nothing_and_takes_nothing_away(dsn):
    _plant_permissions(dsn)
    can = lambda resource, action, role: _lines_as(dsn, "manager_f", f"SELECT my_permission('{resource}', '{action}', '{role}');")[-1]
    assert can("assignment", "write", "Partner") == "f", "a permission written in another firm opened the assignment door"
    assert can("client", "read", "Manager") == "t", "a permission written in another firm took the client read away"
    # the escalation the review walked: with the planted grant, the Manager assigns themselves F's other client
    assert _count_op(dsn, "manager_f", _insert(F, "manager_f", CLIENT_F2)) == "err"
    # and a permission written in their own firm still counts (on another pair: the planted row occupies the unique key of its
    # own, which is the reason a planted row is counted in the notice and not left to be found)
    assert _psql(dsn, _grant(F, "manager_f", "client", "write", "false")).returncode == 0
    assert can("client", "write", "Executive") == "f"
    assert _psql(dsn, _grant(F, "manager_f", "client", "read", "false")).returncode != 0, "the planted pair no longer occupies its key"


def test_the_planted_permission_would_have_opened_the_door_before_the_migration(dsn):
    allow_legacy_rows(dsn)   # migrations 565 and 566 would refuse the planting before the rolled-back 530 policy is asked; this is the control for 530
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _count_op(dsn, "partner_g", _grant(G, "manager_f")) == "1", "the rolled-back policy no longer lets the planting through"
    _plant_permissions(dsn)
    assert _lines_as(dsn, "manager_f", "SELECT my_permission('assignment', 'write', 'Partner');")[-1] == "t"
    assert _count_op(dsn, "manager_f", _insert(F, "manager_f", CLIENT_F2)) == "1", "the escalation is no longer reachable with the migration rolled back"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _lines_as(dsn, "manager_f", "SELECT my_permission('assignment', 'write', 'Partner');")[-1] == "f"


# ── THE HELPERS ─────────────────────────────────────────────────────────────────

def test_the_helpers_answer_about_the_callers_firm_only(dsn):
    def ask(who: str, fn: str, arg: str | None) -> str:
        lit = "NULL::uuid" if arg is None else f"'{arg}'::uuid"
        return _lines_as(dsn, who, f"SELECT {fn}({lit});")[-1]

    assert ask("partner_f", "user_is_in_my_firm", UID["manager_f"]) == "t"
    assert ask("partner_f", "user_is_in_my_firm", UID["manager_g"]) == "f"
    assert ask("partner_f", "user_is_in_my_firm", str(uuid.uuid4())) == "f", "a foreign id and an absent one must read the same"
    assert ask("partner_f", "user_is_in_my_firm", None) == "f"
    assert ask("partner_f", "client_is_in_my_firm", CLIENT_F1) == "t"
    assert ask("partner_f", "client_is_in_my_firm", CLIENT_G1) == "f"
    assert ask("partner_f", "client_is_in_my_firm", str(uuid.uuid4())) == "f"
    assert ask("partner_f", "client_is_in_my_firm", None) == "f"
    assert ask("suspended_f", "user_is_in_my_firm", UID["manager_f"]) == "f", "a suspended member asked the firm"
    assert ask("suspended_f", "client_is_in_my_firm", CLIENT_F1) == "f"


def test_the_helpers_run_as_their_owner_with_a_pinned_search_path(dsn):
    got = _rows(dsn, "SELECT proname, prosecdef, provolatile, proconfig::text FROM pg_proc "
                     "WHERE pronamespace = 'public'::regnamespace AND proname IN ('user_is_in_my_firm', 'client_is_in_my_firm') ORDER BY 1")
    assert [r[0] for r in got] == ["client_is_in_my_firm", "user_is_in_my_firm"], got
    for name, definer, volatility, config in got:
        assert definer == "t" and volatility == "s", (name, definer, volatility)
        assert "search_path=public, pg_catalog" in config, (name, config)


def test_the_helpers_are_not_callable_by_the_public_key(dsn):
    for fn in ("user_is_in_my_firm", "client_is_in_my_firm"):
        got = _rows(dsn, f"SELECT has_function_privilege('anon', 'public.{fn}(uuid)', 'EXECUTE'), "
                         f"has_function_privilege('authenticated', 'public.{fn}(uuid)', 'EXECUTE')")
        assert got == [["f", "t"]], (fn, got)


# ── THE NOTICE, THE ROLLBACK, THE SECOND RUN, THE PLAN ──────────────────────────

def test_the_warning_counts_the_rows_that_name_another_firm_removes_none_and_reaches_the_runners_report(dsn, tmp_path):
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    _plant(dsn)                                                                  # a row with both defects, one with the client's
    assert _psql(dsn, _insert(G, "manager_f", CLIENT_G1)).returncode == 0         # the member of another firm and nothing else wrong
    assert _psql(dsn, _insert(F, "manager_f", CLIENT_G2)).returncode == 0         # the client of another firm and nothing else wrong
    _plant_permissions(dsn)
    before = _rows(dsn, "SELECT count(*) FROM user_client_assignments")[0][0]
    # The production path: the runner, which runs psql at client_min_messages=warning and discards a clean run's output. A
    # NOTICE never got through it (the review of this migration planted two rows and saw neither count); a WARNING that
    # opens with 'migration <number>:' lands in the report's `messages`, which is what the Actions log prints.
    folder = tmp_path / "m"
    folder.mkdir()
    shutil.copy(MIGRATION, folder / MIGRATION.name)
    assert _psql(dsn, "DO $$ BEGIN IF to_regclass('public.schema_migrations') IS NOT NULL THEN "
                      f"DELETE FROM public.schema_migrations WHERE filename = '{MIGRATION.name}'; END IF; END $$;").returncode == 0
    ran = subprocess.run([sys.executable, str(RUNNER), "--dsn", dsn, "--migrations-dir", str(folder), "--json"],
                         capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    report = json.loads(ran.stdout)
    assert report["applied"] == [MIGRATION.name] and report["failed"] == [], report
    said = report["messages"].get(MIGRATION.name)
    assert said and len(said) == 1, report
    assert said[0].startswith("migration 530: 4 assignment row(s) and 2 permission row(s) name a member or a client of another firm"), said
    assert _rows(dsn, "SELECT count(*) FROM user_client_assignments")[0][0] == before, "the migration removed an assignment row"
    assert _rows(dsn, "SELECT count(*) FROM user_permissions")[0][0] == "2", "the migration removed a permission row"


def test_the_rollback_restores_the_policies_and_the_functions_and_a_second_run_changes_nothing(dsn):
    def snapshot() -> list:
        return _rows(dsn, "SELECT 'policy', polname, polcmd, pg_get_expr(polqual, polrelid), pg_get_expr(polwithcheck, polrelid) "
                          "FROM pg_policy WHERE polrelid IN ('public.user_client_assignments'::regclass, 'public.user_permissions'::regclass) "
                          "UNION ALL SELECT 'function', proname, '', replace(pg_get_functiondef(oid), E'\\n', ' '), '' FROM pg_proc "
                          "WHERE pronamespace = 'public'::regnamespace AND proname IN ('my_assigned_client_ids', 'can_access_client', "
                          "'user_is_in_my_firm', 'client_is_in_my_firm', 'my_permission') ORDER BY 1, 2")
    # 530 is applied once first and the state AFTER that is the one compared: migration 537 narrows the two assignment policies
    # again (the practice cannot be assigned), so the state the template starts in is not the state 530 leaves
    assert _psql_file(dsn, MIGRATION).returncode == 0
    migrated = snapshot()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == migrated, "a second run changed something"

    allow_legacy_rows(dsn)   # the rolled-back policy is what is measured below; migration 565 would refuse the same insert first
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    rolled = snapshot()
    assert not [r for r in rolled if r[1] in ("user_is_in_my_firm", "client_is_in_my_firm")], "the rollback left a helper"
    insert = next(r for r in rolled if r[1] == "partners_insert_assignments")
    assert "user_is_in_my_firm" not in insert[4] and "my_permission" in insert[4], insert
    perm = next(r for r in rolled if r[1] == "firm_user_permissions")
    assert "user_is_in_my_firm" not in perm[4], perm
    assert _count_op(dsn, "partner_g", _insert(G, "manager_f", CLIENT_F2)) == "1"
    assert _count_op(dsn, "partner_g", _grant(G, "manager_f")) == "1"

    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == migrated, "a re-apply after the rollback is not the migrated state"


def test_a_signed_in_scan_of_a_client_table_still_asks_the_callers_clients_once(dsn):
    plan = "\n".join(_lines_as(dsn, "manager_f", "EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM customers;"))
    assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
    assert "can_access_client" not in plan, plan


def test_the_function_that_returns_the_callers_clients_takes_the_member_and_the_firm_once(dsn):
    """Called as `get_my_firm_id()` in the WHERE, the firm was asked once per assigned row: a Manager with 3,000 assignments
    paid 160 ms where the old function paid 2. Written as scalar sub-selects the planner takes each once. This pins the form
    (a plan cannot see inside a SQL function)."""
    body = _rows(dsn, "SELECT replace(prosrc, E'\\n', ' ') FROM pg_proc WHERE proname = 'my_assigned_client_ids' "
                      "AND pronamespace = 'public'::regnamespace")[0][0]
    assert "(SELECT public.get_my_firm_id())" in body and "(SELECT public.get_my_user_id())" in body, body
