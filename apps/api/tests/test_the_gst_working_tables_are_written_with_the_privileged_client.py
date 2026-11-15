"""The GST working tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the GST tranche, part 1 of 2).

THE PREMISE
    `itc_reversal_register` (the Rule 37, 42 and 43 and s.17(5) reversals that feed GSTR-3B Table 4(B)), `gstr2b_uploads` (the 2B file a
    reconciliation was made from), `gst_sync_jobs` and `gst_portal_snapshots` (what was pulled from the portal), `client_gst_turnover` (the
    aggregate turnover that decides whether an IRN is owed) and `hsn_sac_preferences` (the HSN a line is offered) are granted to the
    signed-in role behind policies that ask the firm and the client assignment and NOTHING ELSE: no role tier, so a Reviewer assigned to a
    client, who writes nothing through the API, could write a reversal into the register that feeds the return with their own sign-in. The
    browser writes none of them; every writer is the API's. Found by POST-A-008's list of the tables a signed-in session reaches outside the
    access matrix (`fixtures/tables_a_signed_in_session_reaches_outside_the_matrix.txt`).

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the six is made with the privileged
    client now, which carries no row security, so what the policies did is the route's to assert, and it does: the person's `gst` permission
    (`rbac`), the client (`assert_client_access`, or the sync job's own client through `_assert_job_scope`), the router's guard for the firm's
    own practice on a request that names a client, and the firm and the client on every update. `gst_challans`, the seventh table of the
    group, has no writer at all and is closed in the migration.

The rules are `tests/_privileged_write_sites.py`'s, shared with the next tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"itc_reversal_register", "gstr2b_uploads", "gst_sync_jobs", "gst_portal_snapshots", "client_gst_turnover",
                    "hsn_sac_preferences"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"itc_reversal_register": 2, "gstr2b_uploads": 1, "gst_sync_jobs": 4, "gst_portal_snapshots": 2, "client_gst_turnover": 2,
               "hsn_sac_preferences": 2}


def test_every_write_to_the_gst_working_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a GST working table is made with the caller's own client: the migration that follows takes that client's "
                     "write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update or a delete of a GST working table does not name both the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"gst_sync_jobs"})
    src = ('def f(db, sb):\n'
           '    db.table("gst_sync_jobs").insert({}).execute()\n'
           '    privileged_for(sb).table("gst_sync_jobs").update({}).eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["gst_sync_jobs at line 3"]
