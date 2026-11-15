"""The Tally migration tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the Tally tranche,
part 1 of 2).

THE PREMISE
    `tally_migration_jobs` (one upload of a Tally export: its status, its counts, the sentence about its last run) and `tally_migration_items`
    (each master in it, what it became and why it failed) are granted to the signed-in role behind policies that ask the firm (and the client
    assignment where a job names a client) and NO role tier: a signed-in member could mark a job imported, point an item at another record
    (which the rollback then deletes) or clear a job's failures with their own sign-in. The browser writes neither; every writer is the
    API's. Found by POST-A-008's list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the two is made with the privileged
    client now (the detached importer's last word already was). Every update and delete already named the firm; none named a client,
    because a job may have none (a firm-level import) and an item is named by its id or its job.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"tally_migration_jobs", "tally_migration_items"})

#: A job may be the firm's with no client, so it is named by its id and the firm; an item is named by its own id or its job's, with the firm.
KEYS = {"tally_migration_jobs": ("firm_id", "id"), "tally_migration_items": ("firm_id",)}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"tally_migration_jobs": 8, "tally_migration_items": 4}


def test_every_write_to_the_tally_migration_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a Tally migration table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update or delete of a Tally migration table does not name its scope:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"tally_migration_jobs"})
    src = ('def f(sb):\n'
           '    sb.table("tally_migration_jobs").insert({}).execute()\n'
           '    privileged_for(sb).table("tally_migration_jobs").update({}).eq("firm_id", 1).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t, KEYS) == ["tally_migration_jobs at line 3"]
