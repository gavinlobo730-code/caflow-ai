"""Migration 560 — a draft document's lines are replaced in ONE transaction that takes the header's lock first (ledger POST-A-332).

WHAT WAS WRONG
    The API replaced the lines of a draft invoice, bill or note as a DELETE and then an INSERT, two requests. A session that issued the
    document between them left an ISSUED document with no lines (the insert was refused by migration 539's draft rule), so its PDF and
    any rate-wise or HSN build from its lines came out empty.

WHAT THIS HOLDS (real Postgres; it borrows the seeded world of the migration 539 test, which has a draft and every other state of
each of the six documents)
    * THE REPLACEMENT, for each of the six documents: the old lines go, the new ones are there, the document's own id is their foreign
      key whatever an element says (an element naming another document's id ends up on this one), the columns an element does not name
      take their defaults, an empty list leaves a draft with no lines, and the answer is the number of lines.
    * THE REFUSALS: a document that is not a draft answers `document_not_draft` for each status it can be in and keeps its lines; a
      document of another firm, an id that is nobody's and an unknown kind answer in words and change nothing; a body that is not an
      array is refused.
    * THE CALLER'S OWN RIGHTS STILL JUDGE IT (SECURITY INVOKER): an assigned Manager replaces a draft's lines; a Reviewer, who may read
      the lines and not write them, is refused and the lines are untouched.
    * THE RACE (the reason for the function): a replacement that arrives while the document is being issued waits for the issue and is
      then refused with the lines untouched; an issue that arrives while a replacement is open waits for it and the document is issued
      with the lines the replacement wrote.
    * THE FUNCTION: SECURITY INVOKER, not executable by PUBLIC or anon, executable by the two roles the API uses; the migration is
      idempotent; its rollback drops the function (the negative control: the call then fails as a missing function, which is what the
      API's fallback reads).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_m539 = importlib.import_module(
    "test_539_the_document_line_tables_take_the_accounting_write_tier_and_a_signed_in_session_edits_the_lines_of_a_draft_only_pg")
seeded = _m539.seeded          # the fixtures, so pytest finds them in this module
world = _m539.world
_psql, _rows, _as, _op, _q = _m539._psql, _m539._rows, _m539._as, _m539._op, _m539._q
SPECS, FIRM = _m539.SPECS, _m539.FIRM

from services.draft_document_lines import DOCUMENTS  # noqa: E402

MIGRATIONS = _m539.MIGRATIONS
_STEM = "560_a_draft_documents_lines_are_replaced_in_one_transaction_that_locks_the_header_first"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
FUNCTION = "public.replace_draft_document_lines(text, uuid, uuid, jsonb)"
OTHER_FIRM = "55900000-0000-0000-0000-000000000009"
NOBODY = "55900000-0000-0000-0000-0000000000ee"

pytestmark = pytest.mark.skipif(_m539._ADMIN is None, reason="the line-replacement proof requires HARNESS_PG + psql")

KINDS = sorted(DOCUMENTS)


def _table(kind: str) -> str:
    return DOCUMENTS[kind][0]


def _fk(kind: str) -> str:
    return DOCUMENTS[kind][1]


def _el(kind: str, hsn: str, **more) -> dict:
    """A line element that satisfies the table's NOT NULL columns: the two tables whose seed leaves `description` out have no such
    column (migration 539's test knows which)."""
    base = {"hsn_sac": hsn, "rate_paise": 100}
    if _table(kind) not in ("debit_note_lines", "purchase_credit_note_lines"):
        base["description"] = f"line {hsn}"
    return {**base, **more}


def _call(dsn: str, who: str, kind: str, doc: str, lines, firm: str = FIRM) -> subprocess.CompletedProcess:
    payload = json.dumps(lines).replace("'", "''")
    return subprocess.run(
        ["psql", dsn, "-X", "-q", "-tA", "-c",
         _as(who) + f"SELECT public.replace_draft_document_lines('{kind}', '{doc}', '{firm}', '{payload}'::jsonb);"],
        capture_output=True, text=True)


def _lines(dsn: str, kind: str, doc: str) -> list[str]:
    return [r[0] for r in _rows(dsn, f"SELECT coalesce(hsn_sac, '-') FROM {_table(kind)} WHERE {_fk(kind)} = '{doc}' ORDER BY hsn_sac")]


def _draft_of(world, kind: str) -> str:
    return world.ids["parent_of"][f"{_table(kind)}:draft"]


def _answer(done: subprocess.CompletedProcess) -> str:
    return done.stdout.strip().splitlines()[-1] if done.returncode == 0 and done.stdout.strip() else done.stderr


# ── THE REPLACEMENT ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_the_old_lines_go_and_the_new_ones_are_there(world, kind):
    doc = _draft_of(world, kind)
    assert _lines(world.dsn, kind, doc) != [], "the seeded draft has a line to replace"
    done = _call(world.dsn, "service_role", kind, doc, [_el(kind, "1111"), _el(kind, "2222")])
    assert done.returncode == 0, done.stderr
    assert _answer(done) == "2"
    assert _lines(world.dsn, kind, doc) == ["1111", "2222"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_documents_own_id_is_the_foreign_key_whatever_an_element_says(world, kind):
    doc = _draft_of(world, kind)
    other = world.ids["parent_of"][f"{_table(kind)}:{SPECS[_table(kind)][4][0]}"]
    done = _call(world.dsn, "service_role", kind, doc, [_el(kind, "3333", **{_fk(kind): other})])
    assert done.returncode == 0, done.stderr
    assert _lines(world.dsn, kind, doc) == ["3333"]
    assert "3333" not in _lines(world.dsn, kind, other), "a line was moved to another document through the call"


@pytest.mark.parametrize("kind", KINDS)
def test_an_empty_list_leaves_a_draft_with_no_lines_and_a_column_nobody_names_takes_its_default(world, kind):
    doc = _draft_of(world, kind)
    done = _call(world.dsn, "service_role", kind, doc, [_el(kind, "4444")])
    assert done.returncode == 0, done.stderr
    stored = _rows(world.dsn, f"SELECT id IS NOT NULL FROM {_table(kind)} WHERE {_fk(kind)} = '{doc}'")
    assert stored == [["t"]], "the id takes its default"
    done = _call(world.dsn, "service_role", kind, doc, [])
    assert done.returncode == 0, done.stderr
    assert _answer(done) == "0"
    assert _lines(world.dsn, kind, doc) == []


# ── THE PREMISE: WHAT THE TWO-STEP REPLACEMENT DID ──────────────────────────────────────────────────────────────────

def test_the_two_step_replacement_it_replaces_leaves_an_issued_invoice_with_no_lines(world):
    """The negative control, run as the old code ran it: the Manager's DELETE of the lines commits, the document is issued by
    another session, and the Manager's INSERT is refused by migration 539's draft rule. Nothing in this sequence is the function."""
    kind = "sales_invoice"
    doc = _draft_of(world, kind)
    assert _lines(world.dsn, kind, doc) != []
    gone = _psql(world.dsn, _as("manager_a") + f"DELETE FROM client_sales_invoice_lines WHERE sales_invoice_id = '{doc}';")
    assert gone.returncode == 0, gone.stderr
    issued = _psql(world.dsn, f"UPDATE client_sales_invoices SET status = 'issued' WHERE id = '{doc}';")
    assert issued.returncode == 0, issued.stderr
    refused = _psql(world.dsn, _as("manager_a") + "INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, hsn_sac, rate_paise) "
                                                  f"VALUES ('{doc}', 'new', '1234', 100);")
    assert refused.returncode != 0 and "cannot be changed from a signed-in session" in refused.stderr, refused.stderr
    assert _lines(world.dsn, kind, doc) == []
    assert _rows(world.dsn, f"SELECT status FROM client_sales_invoices WHERE id = '{doc}'") == [["issued"]]


# ── THE REFUSALS ────────────────────────────────────────────────────────────────────────────────────────────────────

CASES = [(k, s) for k in KINDS for s in SPECS[_table(k)][4]]


@pytest.mark.parametrize("kind,status", CASES)
def test_a_document_that_is_not_a_draft_keeps_its_lines(world, kind, status):
    doc = world.ids["parent_of"][f"{_table(kind)}:{status}"]
    before = _lines(world.dsn, kind, doc)
    done = _call(world.dsn, "service_role", kind, doc, [_el(kind, "9999")])
    assert done.returncode != 0 and "document_not_draft" in done.stderr, done.stderr
    assert status in done.stderr, "the status is in the detail"
    assert _lines(world.dsn, kind, doc) == before


@pytest.mark.parametrize("kind", KINDS)
def test_another_firms_document_and_nobodys_id_are_not_found_and_nothing_changes(world, kind):
    doc = _draft_of(world, kind)
    before = _lines(world.dsn, kind, doc)
    for firm, target in ((OTHER_FIRM, doc), (FIRM, NOBODY)):
        done = _call(world.dsn, "service_role", kind, target, [_el(kind, "9999")], firm=firm)
        assert done.returncode != 0 and "document_not_found" in done.stderr, done.stderr
    assert _lines(world.dsn, kind, doc) == before


def test_an_unknown_kind_and_a_body_that_is_not_an_array_are_refused(world):
    doc = _draft_of(world, "sales_invoice")
    done = _call(world.dsn, "service_role", "journal_entries", doc, [])
    assert done.returncode != 0 and "unknown document kind" in done.stderr, done.stderr
    done = _call(world.dsn, "service_role", "sales_invoice", doc, {"hsn_sac": "1"})
    assert done.returncode != 0 and "must be a JSON array" in done.stderr, done.stderr


# ── THE CALLER'S OWN RIGHTS ─────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_an_assigned_manager_replaces_a_drafts_lines_and_a_reviewer_is_refused(world, kind):
    doc = _draft_of(world, kind)
    refused = _call(world.dsn, "reviewer_a", kind, doc, [_el(kind, "5555")])
    assert refused.returncode != 0, "a Reviewer replaced a draft's lines"
    assert "5555" not in _lines(world.dsn, kind, doc)
    done = _call(world.dsn, "manager_a", kind, doc, [_el(kind, "5555")])
    assert done.returncode == 0, done.stderr
    assert _lines(world.dsn, kind, doc) == ["5555"]


# ── THE RACE ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _hold_open(dsn: str, sql: str, marker: str) -> subprocess.Popen:
    proc = subprocess.Popen(["psql", dsn, "-X", "-q", "-c", sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(60):
        held = _rows(dsn, f"SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND query LIKE '%{marker}%' AND pid <> pg_backend_pid()")
        if held == [["1"]]:
            return proc
        time.sleep(0.2)
    proc.kill()
    pytest.fail("the holding transaction never started")


def test_a_replacement_that_arrives_while_the_document_is_being_issued_waits_and_is_then_refused(world):
    kind, table = "sales_invoice", "client_sales_invoice_lines"
    doc = _draft_of(world, kind)
    before = _lines(world.dsn, kind, doc)
    issuing = _hold_open(world.dsn, f"BEGIN; UPDATE client_sales_invoices SET status = 'issued' WHERE id = '{doc}'; "
                                    "SELECT pg_sleep(6); COMMIT;", "pg_sleep(6)")
    try:
        began = time.monotonic()
        done = _call(world.dsn, "service_role", kind, doc, [_el(kind, "7777")])
        waited = time.monotonic() - began
    finally:
        issuing.communicate(timeout=60)
    assert done.returncode != 0 and "document_not_draft" in done.stderr, done.stderr
    assert waited > 2, f"the replacement did not wait for the issue ({waited:.2f}s)"
    assert _lines(world.dsn, kind, doc) == before, "an issued invoice lost or changed its lines"
    assert table


def test_an_issue_that_arrives_while_a_replacement_is_open_waits_for_it_and_finds_the_new_lines(world):
    kind = "sales_invoice"
    doc = _draft_of(world, kind)
    replacing = _hold_open(
        world.dsn,
        "BEGIN; SELECT public.replace_draft_document_lines('sales_invoice', "
        f"'{doc}', '{FIRM}', '{json.dumps([_el(kind, '8888')])}'::jsonb); SELECT pg_sleep(6) /* held */; COMMIT;", "pg_sleep(6) /* held */")
    try:
        began = time.monotonic()
        issued = _psql(world.dsn, f"UPDATE client_sales_invoices SET status = 'issued' WHERE id = '{doc}';")
        waited = time.monotonic() - began
    finally:
        replacing.communicate(timeout=60)
    assert issued.returncode == 0, issued.stderr
    assert waited > 2, f"the issue did not wait for the open replacement ({waited:.2f}s)"
    assert _lines(world.dsn, kind, doc) == ["8888"]
    assert _rows(world.dsn, f"SELECT status FROM client_sales_invoices WHERE id = '{doc}'") == [["issued"]]


# ── THE FUNCTION ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_function_runs_as_its_caller_and_is_executable_only_by_the_two_roles_the_api_uses(world):
    assert _rows(world.dsn, f"SELECT prosecdef FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure") == [["f"]]
    got = {r: _rows(world.dsn, f"SELECT has_function_privilege('{r}', '{FUNCTION}', 'EXECUTE')")[0][0]
           for r in ("anon", "authenticated", "service_role", "public")}
    assert got == {"anon": "f", "authenticated": "t", "service_role": "t", "public": "f"}, got


def test_the_migration_is_idempotent(world):
    for _ in range(2):
        done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(MIGRATION)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    assert _call(world.dsn, "service_role", "sales_invoice", _draft_of(world, "sales_invoice"), [_el("sales_invoice", "1")]).returncode == 0


def test_its_own_rollback_drops_the_function_and_the_call_then_fails_as_a_missing_function(world):
    done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'replace_draft_document_lines'") == [["0"]]
    gone = _call(world.dsn, "service_role", "sales_invoice", _draft_of(world, "sales_invoice"), [])
    assert gone.returncode != 0 and "does not exist" in gone.stderr, gone.stderr
