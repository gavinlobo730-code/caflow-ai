"""The accounting and year-end working tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
accounting tranche, part 1 of 2).

THE PREMISE
    `schedule_iii_ratio_explanations` (the CA's sentence on why a Schedule III ratio moved more than 25%, which clause (Q) requires),
    `schedule_iii_ratio_inputs` (the principal repaid that Debt Service Coverage needs), `schedule_iii_unbilled_reviews` (the review that
    lets the unbilled-dues note print a nil), `account_budgets`, `cost_centres` and `year_end_checklist_items` are granted to the signed-in
    role behind policies that ask the firm (and on the first five the client assignment) and NO role tier: a Reviewer, who writes nothing
    through the API, could rewrite the explanation printed on a signed statement or tick a year-end checklist item with their own sign-in.
    The browser writes none of them; every writer is the API's. Found by POST-A-008's list of the tables a signed-in session reaches outside
    the access matrix (`fixtures/tables_a_signed_in_session_reaches_outside_the_matrix.txt`).

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the six is made with the privileged
    client now, which carries no row security, so what the policies did is the route's to assert, and it does: the person's permission
    (`accounting` write, or `year_end` write for the checklist), the client (`assert_client_access`, or the engagement's own client through
    `_assert_engagement_scope`), and the firm and the client on every update and delete, or the firm and the engagement on the checklist,
    whose rows carry no client of their own.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"schedule_iii_ratio_explanations", "schedule_iii_ratio_inputs", "schedule_iii_unbilled_reviews", "account_budgets",
                    "cost_centres", "year_end_checklist_items"})

#: A checklist item hangs from its engagement and has no client column; the route asserts the engagement's client.
KEYS = {"year_end_checklist_items": ("firm_id", "engagement_id")}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"schedule_iii_ratio_explanations": 2, "schedule_iii_ratio_inputs": 1, "schedule_iii_unbilled_reviews": 2,
               "account_budgets": 3, "cost_centres": 2, "year_end_checklist_items": 2}


def test_every_write_to_the_accounting_working_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to an accounting working table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_client_or_the_engagement():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, ("an update or a delete of an accounting working table does not name the firm and the client (the engagement, for a "
                     "checklist item):\n  " + "\n  ".join(bad))


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"year_end_checklist_items", "account_budgets"})
    src = ('def f(db):\n'
           '    db.table("account_budgets").delete().eq("firm_id", 1).eq("client_id", 2).execute()\n'
           '    privileged_for(db).table("year_end_checklist_items").update({}).eq("id", 1).eq("firm_id", 2).execute()\n'
           '    privileged_for(db).table("year_end_checklist_items").update({}).eq("id", 1).eq("firm_id", 2).eq("engagement_id", 3).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True, True]
    assert pw.unscoped_updates_and_deletes(src, t, KEYS) == ["year_end_checklist_items at line 3"]
    # Without the named keys a checklist item is asked for a client it does not have, so both its updates are reported.
    assert pw.unscoped_updates_and_deletes(src, t) == ["year_end_checklist_items at line 3", "year_end_checklist_items at line 4"]
