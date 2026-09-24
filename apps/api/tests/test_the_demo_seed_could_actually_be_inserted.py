"""Every demo row carries an id the schema would accept.

── THE DEFECT ───────────────────────────────────────────────────────────────
`seed/seed_data.py` describes itself as "realistic demo seed data" and defines a
firm, five users, twenty clients, a hundred tasks, a hundred compliance records
and fifty documents. Its primary keys were strings like "firm-001", "sc-003" and
"sct-017".

Every primary key in this schema is `UUID PRIMARY KEY` — migration 001 for
`firms`, and the same for everything after it. Postgres rejects a non-UUID for a
uuid column outright, so **not one row of this file could ever have been
inserted**, and THAT is why nothing has ever written it. THE-PLAN reads the
absence as a missing writer (T2-a, "make seed_data.py runnable"); the writer was
the second problem.

── THE RULE ─────────────────────────────────────────────────────────────────
An id here is a UUID **derived from its label**, not a label. Three properties
have to hold together, and each of the tests below is one of them:

  1. it is a real UUID, or the INSERT fails;
  2. it is the SAME on every run and every machine, or a seeder cannot upsert —
     which is the whole of what "idempotent" means for T2-a, and the reason a
     random uuid4 would be worse than useless here;
  3. it is unique across the whole fixture, or one row overwrites another.

The labels are kept because they are what makes the fixture readable and what
its relationships are written in — `client["id"]`, `DEMO_USERS[i % 3]["id"]` —
so hashing rather than replacing them keeps every reference intact by
construction.
"""
from __future__ import annotations

import uuid

import pytest

from seed.seed_data import (
    DEMO_FIRM, DEMO_USERS, SEED_CLIENTS, SEED_COMPLIANCE_TASKS,
    SEED_DOCUMENTS, SEED_TASKS, seed_id,
)

GROUPS = {
    "firm": [DEMO_FIRM],
    "users": DEMO_USERS,
    "clients": SEED_CLIENTS,
    "compliance_tasks": SEED_COMPLIANCE_TASKS,
    "tasks": SEED_TASKS,
    "documents": SEED_DOCUMENTS,
}
ALL_ROWS = [r for rows in GROUPS.values() for r in rows]


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_every_id_is_a_uuid_the_column_would_take(group: str):
    bad = [
        (r.get("id"), r.get("client_name") or r.get("full_name") or r.get("name"))
        for r in GROUPS[group]
        if "id" in r and not _is_uuid(r["id"])
    ]
    assert not bad, (
        f"{len(bad)} {group} rows carry an id that is not a UUID, so the INSERT "
        f"is refused by Postgres before anything else can go wrong: {bad[:3]}"
    )


def _is_uuid(value: object) -> bool:
    try:
        return str(uuid.UUID(str(value))) == str(value)
    except (ValueError, AttributeError, TypeError):
        return False


def test_an_id_is_the_same_on_every_run():
    """Stability is what makes a seeder idempotent.

    A uuid4 would satisfy the test above and break the feature: every run would
    mint new ids, so the second run duplicates the first instead of updating it.
    """
    assert seed_id("firm-001") == DEMO_FIRM["id"]
    assert seed_id("firm-001") == seed_id("firm-001")
    assert seed_id("sc-001") != seed_id("sc-002")


def test_no_two_rows_share_an_id():
    ids = [r["id"] for r in ALL_ROWS if "id" in r]
    assert len(ids) == len(set(ids)), (
        f"{len(ids) - len(set(ids))} duplicate ids across the fixture — one "
        "demo row would silently overwrite another on insert"
    )


def test_every_row_points_at_the_demo_firm_or_one_of_its_clients():
    """The references survived the change from labels to UUIDs.

    They are written as `client["id"]` and `DEMO_USERS[i % 3]["id"]` rather than
    as literals, so hashing the labels kept them intact by construction — but
    "by construction" is the kind of claim worth an assertion, because the firm
    id WAS a literal in six places before this.
    """
    client_ids = {c["id"] for c in SEED_CLIENTS}
    for row in DEMO_USERS + SEED_CLIENTS:
        assert row.get("firm_id") == DEMO_FIRM["id"], row
    for row in SEED_COMPLIANCE_TASKS + SEED_TASKS + SEED_DOCUMENTS:
        assert row.get("client_id") in client_ids, row


def test_the_fixture_is_not_empty():
    """A vacuity floor: every assertion above passes over an empty list."""
    assert len(ALL_ROWS) >= 250, f"only {len(ALL_ROWS)} seed rows — the fixture shrank"


def test_the_seed_reads_the_indian_day():
    """`date.today()` on a UTC container is the previous Indian day for the
    whole of 00:00-05:30 IST, so a seed built in that window dated every due
    date one day early. Asserted on the SOURCE, because the value is computed at
    import and a test that ran at 07:00 IST would agree either way."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "seed" / "seed_data.py"
    body = src.read_text()
    # THE RULE, NOT A SPELLING OF IT. This asserted the literal
    # `today = ist_today()` and failed on a rename that made the module MORE
    # correct, not less: `test_a_date_bound_at_import_says_so` now forbids
    # naming an import-time clock `today`, because it stops advancing the
    # moment the process boots. What this test cares about is that the seed
    # asks the INDIAN clock, so that is what it asks — the binding's name is
    # the other guard's business. Fifth time this pattern has been corrected
    # in this repository; write the rule.
    import ast
    tree = ast.parse(body)
    bound_to_ist_today = [
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "ist_today"
        for t in node.targets
        if isinstance(t, ast.Name)
    ]
    assert bound_to_ist_today, (
        "the seed must bind ist_today() at module level; found no such binding"
    )
    # COMMENTS FIRST. The module explains the defect in prose and quotes the
    # spelling it forbids, and a guard that fails on the documentation of its own
    # rule is a guard somebody deletes — which is exactly what this assertion did
    # on its first run, against the comment written to explain it.
    code = re.sub(r"#.*", "", re.sub(r'"""[\s\S]*?"""', "", body))
    assert "date.today()" not in code
