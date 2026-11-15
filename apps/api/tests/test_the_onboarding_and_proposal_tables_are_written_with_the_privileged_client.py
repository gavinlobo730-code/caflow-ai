"""The onboarding and proposal tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
onboarding tranche, part 1 of 2).

THE PREMISE
    `onboarding_checklists` with their `onboarding_checklist_steps`, `onboarding_tasks`, `proposals` and `engagement_events` (the history of
    an engagement letter: sent, viewed, signed) are granted to the signed-in role behind policies that ask the firm (and the client assignment
    where a row names a client) and NO role tier: a signed-in member could tick a client's onboarding complete, accept a proposal or write an
    engagement letter's history with their own sign-in. The browser writes none of them; every writer is the API's. Found by POST-A-008's list
    of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the five is made with the privileged
    client now, and every update names its scope. Four did not: an onboarding task's update named the task alone (it now names its workflow
    and the firm, so a task id cannot reach another workflow's task); a checklist step's update and the checklist's progress named the row
    alone (they now name the workflow or the checklist's client, which the route's scope check asserted, and the firm); and a checklist's
    completion named the row alone (it now names the firm and the checklist's client).

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"onboarding_checklists", "onboarding_checklist_steps", "onboarding_tasks", "proposals", "engagement_events"})

#: A step or a task hangs from its workflow and has no client column; a proposal may be a lead's, with no client, and the route's row scope
#: asserts its client where it has one, so it is named by its id and the firm.
KEYS = {"onboarding_checklist_steps": ("firm_id", "workflow_id"), "onboarding_tasks": ("firm_id", "workflow_id"),
        "proposals": ("firm_id", "id")}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"onboarding_checklists": 3, "onboarding_checklist_steps": 2, "onboarding_tasks": 3, "proposals": 2, "engagement_events": 1}


def test_every_write_to_the_onboarding_and_proposal_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to an onboarding or proposal table is made with the caller's own client: the migration that follows takes "
                     "that client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_names_its_scope():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update of an onboarding or proposal table does not name its scope:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"onboarding_tasks"})
    src = ('def f(db):\n'
           '    db.table("onboarding_tasks").insert({}).execute()\n'
           '    privileged_for(db).table("onboarding_tasks").update({}).eq("id", 1).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t, KEYS) == ["onboarding_tasks at line 3"]
