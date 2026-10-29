"""The people-and-companies register says it is read by every member of the firm, and the sentence is held to the policies (POST-A-357).

WHAT WAS FOUND. `entities` holds a PAN, a GSTIN, a date of birth, a phone number and an address, and its read policy asks the firm and nothing
narrower, so a member assigned to client A can read the details of a person who stands behind client B only. The independent review of
migration 531 recorded that as intended ("shared across clients on purpose"), and the third catalog population (POST-A-305) lists the three
register tables as `firm_wide`, with the category checked against the table's own policies. Nothing on any screen said it.

WHAT WAS DECIDED (29-10-2026, under the owner's standing instructions: lawful, safe for the data of a CA's clients, best for the product).
The firm-wide read stays and the screen says so. Narrowing it to "a member sees an entity only when a link ties it to a client in reach" would
defeat what the register is for: the entity picker and the cross-client match detection exist to find a person already known through ANOTHER
client, and a narrowed read would hide that person and make a duplicate. Every member who can open Relationships is a member of this one firm;
the register's write side was already taken away from the signed-in role (migration 562), so the exposure is a read by a colleague, not a
change by one. If a pilot firm asks for a narrower read, the policy and this sentence change together, and this test is what makes them.

WHY A SOURCE GUARD ON THE PYTHON SIDE. The sentence is true only while the three tables are `firm_wide` in the catalog, and the catalog is
checked against the policies by `test_a_table_with_no_client_is_firm_level_on_purpose_pg`. A guard written in `apps/web` would assert the
screen against a copy of itself. This one reads the catalog (the side that owns the fact) and the screen (the side that says it), so narrowing
the read without changing the sentence, or changing the sentence without narrowing the read, is a red test.

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


def test_the_three_register_tables_are_firm_wide_in_the_catalog_the_policies_are_checked_against():
    tables = json.loads(CATALOG.read_text())["tables"]
    for name in REGISTER_TABLES:
        assert name in tables, f"{name} left the firm-level catalog: the screen's sentence about it needs a new basis"
        assert tables[name]["category"] == "firm_wide", (
            f"{name} is now `{tables[name]['category']}` in the catalog, so the register is no longer read by every member of the firm: "
            "change the notice on the Entity Registry screen in the same commit, because it still says it is"
        )


def test_the_screen_says_every_member_who_can_open_the_register_sees_all_of_it():
    src = _page()
    assert 'title="This register is shared across the whole practice"' in src, "the register's notice is gone from the screen"
    flat = " ".join(src.split())
    for must in ("Everyone in the firm who can open Relationships sees every person and company here",
                 "whichever clients they are assigned to",
                 "PAN, GSTIN, date of birth, phone and address"):
        assert must in flat, f"the notice no longer says: {must}"


def test_the_notice_names_the_fields_the_register_really_holds():
    """A sentence that lists what is shared is a claim about the columns, so it is held to the table."""
    sql = "\n".join(p.read_text() for p in sorted((API / "migrations").glob("*.sql")) if "rollback" not in p.name)
    created = re.search(r"CREATE TABLE IF NOT EXISTS entities \((.*?)\n\);", sql, flags=re.S)
    assert created, "the entities table is no longer created where this guard looks"
    body = created.group(1)
    for column in ("pan", "gstin", "phone", "address"):
        assert re.search(rf"(?m)^\s*{column}\s", body), f"`entities` has no `{column}` column, but the notice names it"
    assert re.search(r"ALTER TABLE entities ADD COLUMN IF NOT EXISTS date_of_birth\b", sql), "`entities` has no date_of_birth column"
