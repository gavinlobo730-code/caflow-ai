"""Every person column with no key is on one of the person-column guard's four lists, and every listed column still exists (POST-A-377).

`tests/test_a_bare_person_column_takes_the_id_it_holds.py` proves the writers of the columns it maps, and fails the day a person is written
into a column it lists as not yet decided. What it cannot see from the code is a NEW column: a migration that adds `approved_by uuid` with no
key would be on no list, and nothing would ask which id its first writer puts there. This reads the migration-built schema: every uuid
column named for a person (`*_by`, `*_by_id`, `user_id`, `*_user_id`, `actor_id`, and the assignment names) that has no single-column
foreign key must be on exactly one list, and every listed column must still be such a column, so a list cannot keep a column that was
dropped or given a key.

The one column production has and a migration-built database does not (`ai_memory_triggers`, migration 507 records why) is named.
"""
from __future__ import annotations

import os
import subprocess

import pytest

_PG = os.environ.get("HARNESS_PG")

PERSON_NAMES = (r"^(.*_by|.*_by_id|user_id|.*_user_id|actor_id|assigned_to|assignee_id|assigned_manager|assigned_executive|reviewer_id"
                r"|approver_id|preparer_id|partner_id|responder_id|owner_id|member_id)$")

#: Listed, and absent from a database built from the migrations: the table exists in production only.
PRODUCTION_ONLY = {("ai_memory_triggers", "acknowledged_by")}

QUERY = f"""
select c.relname || '|' || a.attname
from pg_attribute a
join pg_class c on c.oid = a.attrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'p') and a.attnum > 0 and not a.attisdropped
  and format_type(a.atttypid, a.atttypmod) = 'uuid'
  and a.attname ~ '{PERSON_NAMES}'
  and not exists (select 1 from pg_constraint k
                  where k.conrelid = c.oid and k.contype = 'f' and k.conkey = array[a.attnum]::smallint[])
"""


@pytest.mark.skipif(not _PG, reason="needs HARNESS_PG: reads the migration-built schema")
def test_every_person_column_with_no_key_is_on_one_list_and_every_listed_one_is_still_there(pg_template):
    from tests.test_a_bare_person_column_takes_the_id_it_holds import (
        DECIDED_FROM_CODE, NO_PERSON_WRITTEN_YET, OTHER_PRINCIPALS, READ_FROM_ROWS)
    out = subprocess.run(["psql", f"{_PG} dbname={pg_template.name}", "-Atc", QUERY],
                         capture_output=True, text=True, check=True).stdout
    found = {tuple(line.split("|")) for line in out.splitlines() if line}
    assert len(found) > 80, f"the schema read found {len(found)} columns: the query is not reading what it should"
    listed = set(READ_FROM_ROWS) | set(DECIDED_FROM_CODE) | set(OTHER_PRINCIPALS) | NO_PERSON_WRITTEN_YET
    assert not (found - listed), (
        "a person column with no key is on no list: read the code that writes it and add it to DECIDED_FROM_CODE (or, if nothing writes "
        f"a person into it yet, NO_PERSON_WRITTEN_YET): {sorted(found - listed)}")
    assert not (listed - found - PRODUCTION_ONLY), (
        f"listed but no longer a person column with no key (dropped, renamed or given a key): {sorted(listed - found - PRODUCTION_ONLY)}")
    assert not (PRODUCTION_ONLY & found), "a production-only table is now built by the migrations: take it off PRODUCTION_ONLY"
