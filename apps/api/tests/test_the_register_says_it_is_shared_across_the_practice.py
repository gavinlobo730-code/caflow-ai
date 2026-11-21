"""What the people-and-companies register screen says about who reads it is held to the server and to the policies (POST-A-357, POST-A-544).

THE FIRST DECISION (POST-A-357, 29-10-2026). `entities` holds a PAN, a GSTIN, a date of birth, a phone number and an address, and its read
policy asks the firm and nothing narrower. It was decided to keep the firm-wide read and say so on the screen, because a narrowed read would
hide a person already known through another client from the entity picker and produce a duplicate.

WHAT CHANGED (POST-A-544, 21-11-2026). The owner decided that what a member of staff sees is limited to their own clients, and the map made
for that decision counted this register as the one list of people that was not. The SERVER now narrows it: a member who is not firm-wide is
shown an entity only when it holds a role at one of their clients, or no role at all, and the answer carries `scoped`. The picker's problem,
which is why this was not built in October, has an answer now: one PAN is one entity in a firm, so a PAN that a hidden entity holds is
refused in a sentence that says a Partner can attach it. The screen says which answer the server gave, in two sentences keyed on `scoped`.

WHAT IS STILL TRUE OF THE DATABASE, AND WHY THIS FILE STILL READS THE CATALOG. The three tables are still `firm_wide` in the catalog, and
that category is checked against the policies by `test_a_table_with_no_client_is_firm_level_on_purpose_pg`: a hand-made request to the
database's own API, by a signed-in member of staff, is still answered with the whole register. Closing that needs the server's reads moved
to its own client and then a migration, and is the open half of POST-A-544. So this file holds three things together: the screen's two
sentences, the server's `scoped`, and, WHILE the catalog says `firm_wide`, a ledger line that says the database half is open. Whoever
narrows the database changes the category and closes the line in the same commit, and this test is what makes them.

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


def test_while_the_database_still_answers_the_whole_register_the_ledger_says_that_half_is_open():
    tables = json.loads(CATALOG.read_text())["tables"]
    for name in REGISTER_TABLES:
        assert name in tables, f"{name} left the firm-level catalog: the screen's sentences about it need a new basis"
    still_firm_wide = [name for name in REGISTER_TABLES if tables[name]["category"] == "firm_wide"]
    line_open = any(line.startswith("- **POST-A-544**") for line in LEDGER.read_text().splitlines())
    if still_firm_wide:
        assert line_open, (
            f"{still_firm_wide} are still `firm_wide` in the catalog (a hand-made request to the database reads the whole register) "
            "and the ledger line that says so, POST-A-544, is gone: reopen it, or narrow the database and change the category")
        assert "server" in tables["entities"]["why"] and "POST-A-544" in tables["entities"]["why"], (
            "the catalog's reason for `entities` no longer says that the server narrows the read and the database does not yet")
    else:
        assert not line_open, "the database is narrowed and POST-A-544 is still open: close the line in the same commit"


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
