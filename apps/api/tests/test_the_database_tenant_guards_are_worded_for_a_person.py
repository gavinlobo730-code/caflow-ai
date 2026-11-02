"""The database's tenant guards reach a person as one plain sentence, whichever door tripped them (POST-A-353).

WHAT WAS WRONG
    Migrations 360, 418, 565, 566, 570 and 573 make the database refuse a row that names a ledger account, a cost centre, a ledger entry, a
    client, a customer, a supplier or a member belonging to another client or firm. The refusal is the control and it holds. What a PERSON
    was told was not: each guard raises a sentence written for a log ("a row of recurring_invoices names customer 3f2a... that belongs to
    another client": the table, and the other client's id), and the 565, 566, 360 and 418 guards raise it as a permission fault (42501),
    which the API words as "The server is not permitted to write this table. That is a configuration fault on our side": a CA who picked
    the wrong customer from a stale list was told the server was misconfigured. The ledger line (POST-A-353, part 1) asked for the answer
    at each of 26 doors that store such a link; a question at each door is a courtesy a later door forgets, and the database is already
    the control, so the sentence is said ONCE, in `core.exceptions`, for every door and for a write made through a database function.

WHAT THIS HOLDS (mock mode: the migration text, the wording function and the real middleware; the live trigger is in the `_pg` file)
    * THE RULE IS DERIVED FROM THE MIGRATIONS. Every `RAISE EXCEPTION` in any migration whose sentence says a row belongs to another
      client or firm (or that a journal line's account or cost centre does not belong to the entry's firm and client) is read, with the
      ERRCODE it raises, and must come back as "That <row> was not found." with no table, column or id in it. A guard written later
      and not worded fails here, naming the sentence and the migration, which is how the list in `core/exceptions.py` stays complete.
    * THE SCAN IS NOT BLIND: a synthetic migration with an unlisted guard is flagged, and a guard it was written for is not.
    * THE SENTENCE IS THE ONE A PER-DOOR CHECK GIVES: 404 and "That <row> was not found.", so the answer does not say whether the row
      exists under another client (`services/named_row_ownership._not_found`).
    * WHAT IT LEAVES ALONE: a business rule that happens to be P0001 keeps its own words and status, a permission fault that is not a
      tenant guard is still a server fault, a foreign-key violation is still one, and the two sentences that mention a client but are
      not about a stranger's row (the transfer's two sides, the receipt and its journal naming different firms) are not rewritten.
    * End to end through the real middleware, for the uncaught failure and for `document_failure_detail`, and a hostile exception cannot
      turn the wording into a second failure.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from core.exceptions import document_failure_detail, tenant_guard_sentence, unhandled_failure

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

RAISE = re.compile(r"RAISE\s+EXCEPTION\s+('(?:[^']|'')*')(.*?);", re.S | re.I)
ERRCODE = re.compile(r"ERRCODE\s*=\s*'(\w{5})'", re.I)
#: A sentence that says a row names something of another client or firm. The two other migration sentences that mention a client
#: ("Both sides of a transfer must belong to the same client", "the receipt and its journal name different firms or clients") say
#: something else and are not matched.
GUARD_WORDS = re.compile(r"belongs? to another (?:client|firm)|do not belong to this entry's firm and client", re.I)
UUID = "3f2a9c1e-7b44-4d0e-9a51-0c6e2b8d1f77"


class ApiError(Exception):
    """Shaped like supabase-py's APIError: code and message on the instance AND in args[0]."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


def guards_in(sql: str) -> list[tuple[str, str]]:
    """(sentence, SQLSTATE) of every tenant guard a migration's text raises. P0001 is the default of RAISE EXCEPTION."""
    found = []
    for m in RAISE.finditer(sql):
        sentence = m.group(1)[1:-1].replace("''", "'")
        if GUARD_WORDS.search(sentence):
            code = ERRCODE.search(m.group(2))
            found.append((sentence, code.group(1) if code else "P0001"))
    return found


def every_guard() -> dict[tuple[str, str], list[str]]:
    seen: dict[tuple[str, str], list[str]] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name.endswith("_rollback.sql"):
            continue
        for key in guards_in(path.read_text(encoding="utf-8")):
            seen.setdefault(key, []).append(path.name[:3])
    return seen


def as_raised(sentence: str) -> str:
    """The sentence as the database sends it: each % filled with what plpgsql would put there (a table name, a column, an id or a set)."""
    fills = iter(["recurring_invoices", "{" + UUID + "}", "assigned_to"])
    return re.sub(r"%", lambda _m: next(fills, UUID), sentence)


GUARDS = every_guard()


# ── The rule, derived from the migrations ────────────────────────────────────────────────────────────

def test_the_scan_finds_every_guard_this_was_written_for():
    """A vacuous floor: the scan reads the six migrations that install guards and finds both SQLSTATEs they raise."""
    assert len(GUARDS) >= 12, sorted(GUARDS)
    migrations = {n for names in GUARDS.values() for n in names}
    assert {"360", "418", "565", "566", "570", "573"} <= migrations, migrations
    assert {state for _s, state in GUARDS} == {"P0001", "42501"}


@pytest.mark.parametrize("sentence,state", sorted(GUARDS), ids=lambda v: v[:48])
def test_every_tenant_guard_a_migration_installs_is_worded_for_a_person(sentence, state):
    raised = ApiError(state, as_raised(sentence))
    said = tenant_guard_sentence(raised)
    assert said, f"{sentence!r} (migrations {GUARDS[(sentence, state)]}, {state}) is a tenant guard core/exceptions.py does not word"
    assert re.fullmatch(r"That [a-z ]+ was not found\.", said), said
    for leak in (UUID, "recurring_invoices", "assigned_to", "{", "%", "_"):
        assert leak not in said, f"{said!r} repeats {leak!r}"
    assert unhandled_failure(raised) == (404, said), "the uncaught failure must answer 404 with the same sentence"
    assert document_failure_detail(raised, action="save the record") == f"Could not save the record: {said}"


def test_the_scan_is_not_blind():
    unlisted = ("CREATE FUNCTION g() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'a row of % names warehouse % that belongs to another "
                "client', TG_TABLE_NAME, NEW.warehouse_id USING ERRCODE = '42501'; END $$ LANGUAGE plpgsql;")
    [(sentence, state)] = guards_in(unlisted)
    assert state == "42501"
    assert tenant_guard_sentence(ApiError(state, as_raised(sentence))) is None, "an unlisted guard must be seen as unworded"
    listed = ("RAISE EXCEPTION 'a row of % names customer % that belongs to another client', TG_TABLE_NAME, NEW.customer_id "
              "USING ERRCODE = '42501';")
    [(sentence, state)] = guards_in(listed)
    assert tenant_guard_sentence(ApiError(state, as_raised(sentence))) == "That customer was not found."
    other = "RAISE EXCEPTION 'Both sides of a transfer must belong to the same client.';"
    assert guards_in(other) == []


# ── What it must leave alone ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,message,status", [
    ("P0001", "GSTR-3B covering this date was filed on 18 Jul 2026.", 400),
    ("P0001", "Both sides of a transfer must belong to the same client.", 400),
    ("42501", "settle_receipt_atomic: the receipt and its journal name different firms or clients", 500),
    ("42501", "permission denied for table journal_entries", 500),
    ("23503", "a row of x names customer 1 that belongs to another client", 400),
])
def test_what_is_not_a_tenant_guard_keeps_its_own_words_and_status(code, message, status):
    assert tenant_guard_sentence(ApiError(code, message)) is None
    assert unhandled_failure(ApiError(code, message))[0] == status


def test_the_wording_never_becomes_a_second_failure():
    class Hostile(Exception):
        @property
        def code(self):
            raise RuntimeError("nope")

        @property
        def message(self):
            raise RuntimeError("nope")

    assert tenant_guard_sentence(Hostile()) is None


# ── End to end, through the real middleware stack ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    @main.app.get("/__test__/names-another-clients-customer")
    def _customer():
        raise ApiError("42501", f"a row of recurring_invoices names customer {UUID} that belongs to another client")

    @main.app.get("/__test__/names-another-clients-ledger-account")
    def _account():
        raise ApiError("P0001", f"That ledger account belongs to another client or firm, so it cannot be used on this record (bank_accounts in coa_account_id: {UUID}).")

    @main.app.get("/__test__/lacks-permission")
    def _permission():
        raise ApiError("42501", "permission denied for table bank_accounts")

    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("path,sentence", [
    ("/__test__/names-another-clients-customer", "That customer was not found."),
    ("/__test__/names-another-clients-ledger-account", "That ledger account was not found."),
])
def test_a_person_is_told_one_plain_sentence_with_a_404(client, path, sentence):
    res = client.get(path)
    assert res.status_code == 404
    body = res.json()
    assert body == {"success": False, "data": None, "error": sentence}
    assert UUID not in res.text and "recurring_invoices" not in res.text and "coa_account_id" not in res.text


def test_a_real_permission_fault_is_still_a_server_fault(client):
    res = client.get("/__test__/lacks-permission")
    assert res.status_code == 500
    assert "configuration fault" in res.json()["error"]
