"""What the people-and-companies register screen says about who reads it is held to the server and to the policies (POST-A-357, POST-A-544).

THE FIRST DECISION (POST-A-357, 29-10-2026). `entities` holds a PAN, a GSTIN, a date of birth, a phone number and an address, and its read
policy asks the firm and nothing narrower. It was decided to keep the firm-wide read and say so on the screen, because a narrowed read would
hide a person already known through another client from the entity picker and produce a duplicate.

WHAT CHANGED (POST-A-544, 21-11-2026). The owner decided that what a member of staff sees is limited to their own clients, and the map made
for that decision counted this register as the one list of people that was not. The SERVER now narrows it: a member who is not firm-wide is
shown an entity only when it holds a role at one of their clients, or no role at all, and the answer carries `scoped`. The picker's problem,
which is why this was not built in October, has an answer now: one PAN is one entity in a firm, so a PAN that a hidden entity holds is
refused in a sentence that says a Partner can attach it. The screen says which answer the server gave, in two sentences keyed on `scoped`.

THE DATABASE HALF IS CLOSED (POST-A-544, migration 777, 22-11-2026). The three tables were `firm_wide` in the catalog of firm-level tables
(a hand-made request to the database's own API, by any signed-in member of staff, was answered with the whole register) until the
server's own statements were moved to its own client and then the signed-in role's every privilege on the three was revoked. No signed-in
session reaches them now, so they are in NO list of tables a session reaches, and the ledger line is closed. This file holds that together:
the screen's two sentences, the server's `scoped`, and the three tables out of both lists with the line gone. Whoever gives the signed-in
role a read of the register back fails here and has to say on the screen, in the same commit, who reads it.

WHY A SOURCE GUARD ON THE PYTHON SIDE. A guard written in `apps/web` would assert the screen against a copy of itself. This one reads the
catalog and the route (the sides that own the facts) and the screen (the side that says them).

It reads `apps/web/app/relationships/page.tsx`, so the `browser contract` CI job selects it for a pull request that touches only the web app
(`scripts/ci/tests_reading_the_browser.py`).
"""
from __future__ import annotations

import json
import pathlib
import re

API = pathlib.Path(__file__).resolve().parents[1]
PAGE = API.parent / "web" / "app" / "relationships" / "page.tsx"
CATALOG = API / "tests" / "fixtures" / "firm_level_tables.json"

REGISTER_TABLES = ("entities", "entity_relationships", "entity_to_entity_relationships")


def _page() -> str:
    text = PAGE.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//[^\n]*$", "", text)


LEDGER = API.parent.parent / "docs" / "open-items" / "new-findings.md"   # docs/open-items/new-findings.md
ROUTER = API / "routers" / "relationships.py"


REACHED_OUTSIDE_THE_MATRIX = API / "tests" / "fixtures" / "tables_a_signed_in_session_reaches_outside_the_matrix.txt"


def test_no_signed_in_session_reaches_the_register_and_the_ledger_line_is_closed():
    """The lists of what a signed-in session reaches are held to the database itself by their own real-Postgres tests
    (`test_a_table_with_no_client_is_firm_level_on_purpose_pg`, `test_every_table_a_signed_in_session_reaches_is_observed_or_named_pg`),
    so reading them here is reading the privileges."""
    firm_level = json.loads(CATALOG.read_text())["tables"]
    reached = {line.split("\t")[0] for line in REACHED_OUTSIDE_THE_MATRIX.read_text().splitlines() if line and not line.startswith("#")}
    for name in REGISTER_TABLES:
        assert name not in firm_level, (
            f"{name} is in the catalog of firm-level tables a signed-in session reaches again: the screen must say who reads the register")
        assert name not in reached, f"{name} is reached by a signed-in session again: the screen must say who reads the register"
    migration = API / "migrations" / "777_no_signed_in_session_reads_the_related_party_register.sql"
    assert migration.exists() and "REVOKE ALL ON public.%I FROM PUBLIC, authenticated, anon" in migration.read_text(), (
        "the migration that took the signed-in role's read of the register away is gone or no longer revokes it")
    assert not any(line.startswith("- **POST-A-544**") for line in LEDGER.read_text().splitlines()), (
        "the database is narrowed and POST-A-544 is still open: close the line in the same commit")


def test_the_server_says_whether_it_answered_with_the_whole_register_or_the_callers_part():
    import ast
    tree = ast.parse(ROUTER.read_text())
    window = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_entity_window")
    keys = {k.value for d in ast.walk(window) if isinstance(d, ast.Dict) for k in d.keys if isinstance(k, ast.Constant)}
    assert "scoped" in keys, "the register's answer no longer carries `scoped`, which the screen's two sentences are keyed on"
    lister = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "list_entities")
    called = {c.func.id for c in ast.walk(lister) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_hidden_entity_ids" in called, "the register is listed without asking which entities the caller may not see"


def test_the_screen_says_which_answer_the_server_gave_and_never_that_everyone_sees_everything():
    src = _page()
    flat = " ".join(src.split())
    assert "registerScoped === true" in flat and "registerScoped === false" in flat, "the notice is no longer keyed on the server's answer"
    for must in ('title="You are shown part of this register"',
                 "You see the people and companies connected to the clients you are assigned to",
                 "ask a Partner to add them to yours",
                 'title="You are shown the whole register"',
                 "PAN, GSTIN, date of birth, phone and address",
                 "Other members of staff see only those connected to the clients they are assigned to"):
        assert must in flat, f"the notice no longer says: {must}"
    for gone in ("This register is shared across the whole practice",
                 "Everyone in the firm who can open Relationships sees every person and company here"):
        assert gone not in flat, f"the screen still says what the server no longer does: {gone}"


def test_the_refusal_of_a_pan_out_of_reach_is_the_sentence_the_screen_promises():
    """The screen tells a member to ask a Partner because a person cannot be added twice; the server's refusal says the same."""
    import routers.relationships as rel
    assert "Ask a Partner to add them to your client" in rel.PAN_HELD_OUT_OF_REACH


def test_the_notice_names_the_fields_the_register_really_holds():
    """A sentence that lists what is shared is a claim about the columns, so it is held to the table."""
    sql = "\n".join(p.read_text() for p in sorted((API / "migrations").glob("*.sql")) if "rollback" not in p.name)
    created = re.search(r"CREATE TABLE IF NOT EXISTS entities \((.*?)\n\);", sql, flags=re.S)
    assert created, "the entities table is no longer created where this guard looks"
    body = created.group(1)
    for column in ("pan", "gstin", "phone", "address"):
        assert re.search(rf"(?m)^\s*{column}\s", body), f"`entities` has no `{column}` column, but the notice names it"
    assert re.search(r"ALTER TABLE entities ADD COLUMN IF NOT EXISTS date_of_birth\b", sql), "`entities` has no date_of_birth column"


# ── THE DSC REGISTER IS THE SECOND ONE (POST-A-450) ────────────────────────────────────────────────────────────────────────────
# `dsc_records` is `firm_wide` in the same catalog, and its recorded reason was "the practice's own tokens", while deleting a client is
# blocked when a certificate carries the client's PAN: it holds clients' directors' certificates too. The tracker now says what the people
# register says, and these hold the sentence and the reason to the catalog the policies are checked against.
DSC_PAGE = API.parent / "web" / "app" / "settings" / "dsc-tracker" / "page.tsx"   # apps/web/app/settings/dsc-tracker/page.tsx


def _dsc_page() -> str:
    text = DSC_PAGE.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//[^\n]*$", "", text)


def test_the_dsc_register_is_firm_wide_in_the_catalog_and_its_reason_says_whose_certificates_it_holds():
    entry = json.loads(CATALOG.read_text())["tables"]["dsc_records"]
    assert entry["category"] == "firm_wide", (
        "dsc_records is no longer `firm_wide`: change the notice on the DSC tracker in the same commit, because it still says it is")
    why = entry["why"]
    assert "clients' directors" in why, "the reason no longer says the register holds clients' directors' certificates"
    assert "practice's own digital signature tokens" not in why, "the old reason, which the code contradicts, is back"


def test_the_dsc_tracker_says_every_member_sees_every_certificate():
    flat = " ".join(_dsc_page().split())
    assert 'title="This register is shared across the whole practice"' in flat, "the DSC tracker's notice is gone"
    for must in ("Everyone in the firm who can open this page sees every certificate here",
                 "whichever clients they are assigned to",
                 "holder&apos;s name, PAN and token number",
                 "global search finds a holder by name or PAN"):
        assert must in flat, f"the notice no longer says: {must}"


def test_the_search_the_notice_names_really_reads_the_dsc_register_by_name_and_pan():
    src = (API / "routers" / "search.py").read_text()
    at = src.index("# ── DSC records")
    block = src[at: at + 1500]
    assert "dsc_repo.find_all(firm_id=firm_id)" in block, "global search no longer reads the whole DSC register: correct the notice"
    assert '("holder_name", "pan")' in block, "global search no longer finds a holder by name or PAN: correct the notice"
