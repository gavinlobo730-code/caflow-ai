"""The client health and lifecycle tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
health tranche, part 1 of 2).

THE PREMISE
    `client_lifecycle_events` (the history of a lead and of the client it became), `client_period_metrics` (the year's figures the nightly
    sweep derives from the books and the returns) and `health_overrides` (a person's override of a client's health grade, which can mask a
    real Critical status) are granted to the signed-in role behind policies that ask the firm (and the client assignment where the row names
    a client) and NO role tier: a Reviewer, who writes nothing through the API, could set an override on a client's grade with their own
    sign-in. The browser writes none of them; every writer is the API's. Found by POST-A-008's list of the tables a signed-in session reaches
    outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the three is made with the privileged
    client now, and the one update names the firm and the client (deactivating an override named the firm only; it now names the client of
    the override the route's scope check resolved). The lead events carry no client: their route asks the lead under the firm.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"client_lifecycle_events", "client_period_metrics", "health_overrides"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"client_lifecycle_events": 6, "client_period_metrics": 1, "health_overrides": 2}


def test_every_write_to_the_health_and_lifecycle_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a health or lifecycle table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update or a delete of a health or lifecycle table does not name the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"health_overrides"})
    src = ('def f(db):\n'
           '    db.table("health_overrides").insert({}).execute()\n'
           '    privileged_for(db).table("health_overrides").update({}).eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["health_overrides at line 3"]
