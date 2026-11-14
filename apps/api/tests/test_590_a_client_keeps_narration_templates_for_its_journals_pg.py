"""Migration 590 on a real database: a client's narration templates are read by the members assigned to the client and written by the
API only (POST-A-093).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_a_client_keeps_narration_templates_for_its_journals.py`) holds the routes and the service. Here:
    * the words: the CHECK refuses an empty or a 301-character narration and takes 300; one live template per client per wording,
      ignoring case, while an archived one does not block the same words again;
    * the privileges: the signed-in role reads and holds no write (table or column), anon holds nothing, and the service role writes;
    * the policies, as each person: a Partner reads every client's templates; a Manager assigned to A reads A's and nothing else; a
      member assigned to nothing, a Partner of another firm and a principal with no member row read none; the internal practice's
      templates are a Partner's even for a member assigned to it;
    * the forgeries: an insert, an update and a delete by a signed-in member are refused, and the rows are untouched;
    * the firm checks: a row naming another firm's client, or a member of another firm as its author, is refused by the triggers
      migrations 565 and 566 install;
    * the migration runs twice without failing and its rollback removes the table, after which it applies again.

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

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(API_ROOT.glob("migrations/590_a_client_keeps_narration_templates_for_its_journals.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/590_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

T = "public.journal_narration_templates"
FIRM, OTHER_FIRM = "59000000-0000-0000-0000-000000000001", "59000000-0000-0000-0000-000000000002"
CLIENT_A, CLIENT_B = "59000000-0000-0000-0000-0000000000a1", "59000000-0000-0000-0000-0000000000b2"
INTERNAL, FOREIGN = "59000000-0000-0000-0000-0000000000c3", "59000000-0000-0000-0000-0000000000d4"
STRANGER = "59000000-1111-0000-0000-0000000000ff"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("59000000-0000-0000-0000-00000000000a", "59000000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("59000000-0000-0000-0000-00000000000b", "59000000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_internal": ("59000000-0000-0000-0000-00000000000d", "59000000-1111-0000-0000-000000000004", "Manager", FIRM),
    "manager_none": ("59000000-0000-0000-0000-00000000000c", "59000000-1111-0000-0000-000000000003", "Manager", FIRM),
    "other_firm": ("59000000-0000-0000-0000-000000000010", "59000000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _sub(who: str) -> str:
    return STRANGER if who == "stranger" else PEOPLE[who][1]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{_sub(who)}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _rows_as(dsn: str, who: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
                        _as(who) + f"SELECT narration FROM {T} ORDER BY narration;"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _refused_as(dsn: str, who: str, dml: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + dml], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e590_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items()) + f", ('{STRANGER}', 'employee@t.in')"
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        _ok(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship'),
                ('{FOREIGN}', '{OTHER_FIRM}', 'X', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
                ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'), ('{FIRM}', '{PEOPLE["manager_internal"][0]}', '{INTERNAL}');
            INSERT INTO {T} (firm_id, client_id, narration, narration_key, created_by) VALUES
                ('{FIRM}', '{CLIENT_A}', 'A rent', 'a rent', '{PEOPLE["partner"][0]}'),
                ('{FIRM}', '{CLIENT_B}', 'B salary', 'b salary', '{PEOPLE["partner"][0]}'),
                ('{FIRM}', '{INTERNAL}', 'Practice fee', 'practice fee', '{PEOPLE["partner"][0]}'),
                ('{OTHER_FIRM}', '{FOREIGN}', 'Their words', 'their words', '{PEOPLE["other_firm"][0]}');
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(dsn: str, client: str, words: str, *, firm: str = FIRM, archived: bool = False,
            key: "str | None" = None) -> subprocess.CompletedProcess:
    """A row as the API writes it: the words and their key (the API's `narration_templates.key`; ASCII words here, so lower())."""
    at = "now()" if archived else "NULL"
    k = (key if key is not None else words.strip().lower())
    return _psql(dsn, f"INSERT INTO {T} (firm_id, client_id, narration, narration_key, archived_at) "
                      f"VALUES ('{firm}', '{client}', $w${words}$w$, $k${k}$k$, {at});")


def test_the_words_are_one_line_of_1_to_300_characters_and_one_live_template_per_wording(dsn):
    assert _insert(dsn, CLIENT_A, "   ").returncode != 0
    assert _insert(dsn, CLIENT_A, "x" * 301).returncode != 0
    assert _insert(dsn, CLIENT_A, "x" * 300).returncode == 0
    r = _insert(dsn, CLIENT_A, "a RENT")                                  # the same words as 'A rent', ignoring case
    assert r.returncode != 0 and "uq_journal_narration_templates_live_words" in r.stderr
    assert _insert(dsn, CLIENT_A, "Other", key="").returncode != 0         # a row with no key is refused
    # the index is on the KEY the API computes, not on lower(): words whose keys differ are two templates, as the API says
    assert _insert(dsn, CLIENT_A, "İx rent", key="i̇x rent").returncode == 0
    assert _insert(dsn, CLIENT_A, "Ix rent", key="ix rent").returncode == 0
    assert _insert(dsn, CLIENT_B, "A rent").returncode == 0               # another client's words are its own
    _ok(dsn, f"UPDATE {T} SET archived_at = now() WHERE client_id = '{CLIENT_A}' AND narration = 'A rent';")
    assert _insert(dsn, CLIENT_A, "A rent").returncode == 0               # archived words may be saved afresh


def test_the_signed_in_role_reads_and_holds_no_write_anon_holds_nothing_and_the_service_role_writes(dsn):
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        for role in ("authenticated", "anon"):
            assert _val(dsn, f"SELECT has_table_privilege('{role}', '{T}', '{verb}')") == "f", (role, verb)
    for verb in ("INSERT", "UPDATE"):
        assert _val(dsn, f"SELECT has_any_column_privilege('authenticated', '{T}', '{verb}')") == "f", verb
    assert _val(dsn, f"SELECT has_table_privilege('authenticated', '{T}', 'SELECT')") == "t"
    assert _val(dsn, f"SELECT has_table_privilege('anon', '{T}', 'SELECT')") == "f"
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _val(dsn, f"SELECT has_table_privilege('service_role', '{T}', '{verb}')") == "t", verb
    assert _val(dsn, f"SELECT relrowsecurity FROM pg_class WHERE oid = '{T}'::regclass") == "t"


def test_each_person_reads_the_templates_of_the_clients_they_may_see_and_no_other(dsn):
    assert _rows_as(dsn, "partner") == ["A rent", "B salary", "Practice fee"]
    assert _rows_as(dsn, "manager_a") == ["A rent"]
    assert _rows_as(dsn, "manager_internal") == []                        # the internal practice is a Partner's
    assert _rows_as(dsn, "manager_none") == []
    assert _rows_as(dsn, "other_firm") == ["Their words"]
    assert _rows_as(dsn, "stranger") == []


def test_a_signed_in_member_can_neither_insert_nor_rewrite_nor_delete_a_template(dsn):
    for who in ("partner", "manager_a"):
        assert _refused_as(dsn, who, f"INSERT INTO {T} (firm_id, client_id, narration) VALUES ('{FIRM}', '{CLIENT_A}', 'Forged');")
        assert _refused_as(dsn, who, f"UPDATE {T} SET narration = 'Forged' WHERE client_id = '{CLIENT_A}';")
        assert _refused_as(dsn, who, f"DELETE FROM {T} WHERE client_id = '{CLIENT_A}';")
    assert _val(dsn, f"SELECT string_agg(narration, ',' ORDER BY narration) FROM {T} WHERE firm_id = '{FIRM}'") == \
        "A rent,B salary,Practice fee"


def test_a_row_naming_another_firms_client_or_author_is_refused_by_the_firm_checks(dsn):
    r = _insert(dsn, FOREIGN, "Cross-firm")                                # a FIRM row naming OTHER_FIRM's client
    assert r.returncode != 0 and "that belong to another firm" in r.stderr, r.stderr
    r = _psql(dsn, f"INSERT INTO {T} (firm_id, client_id, narration, narration_key, created_by) "
                   f"VALUES ('{FIRM}', '{CLIENT_A}', 'By a stranger', 'by a stranger', '{PEOPLE['other_firm'][0]}');")
    assert r.returncode != 0 and "another firm" in r.stderr, r.stderr
    names = set(_val(dsn, f"SELECT string_agg(tgname, ',') FROM pg_trigger WHERE tgrelid = '{T}'::regclass "
                           f"AND NOT tgisinternal").split(","))
    assert any(re.search("client", n) for n in names) and any(re.search("member", n) for n in names), names


def test_the_migration_runs_twice_and_its_rollback_removes_the_table_which_then_applies_again(dsn):
    _run(dsn, MIGRATION)
    assert _val(dsn, f"SELECT count(*) FROM {T}") == "4"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, "SELECT to_regclass('public.journal_narration_templates') IS NULL") == "t"
    _run(dsn, MIGRATION)
    assert _insert(dsn, CLIENT_A, "Again").returncode == 0
