"""The income-tax working tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the income-tax
tranche, part 1 of 2).

THE PREMISE
    `ais_uploads`, `ais_records` and `ais_reconciliations` (the Annual Information Statement a CA reconciles against the books, line by line),
    `ais_computation_decisions` (which AIS lines the CA took into the computation), `form_26as_records` (the 26AS credits and their
    reconciliation outcome), `income_tax_asset_blocks` (the s.32 blocks and the return row each is declared on), `income_tax_worksheets`
    (the house-property and capital-gains workings), `itr_filing_versions` (each version of a return's JSON) and `tax_deduction_claims` (the
    Chapter VI-A claims) are granted to the signed-in role behind policies that ask the firm and the client assignment and NO role tier: a
    Reviewer assigned to a client, who writes nothing through the API, could rewrite the working a s.143(1)(a) adjustment is answered from,
    or add a deduction claim, with their own sign-in. The browser writes none of them; every writer is the API's. Found by POST-A-008's list
    of the tables a signed-in session reaches outside the access matrix (`fixtures/tables_a_signed_in_session_reaches_outside_the_matrix.txt`).

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the nine is made with the privileged
    client now, which carries no row security, so what the policies did is the route's to assert, and it does: the person's `income_tax`
    permission (`rbac`, compute for every write), the client (`assert_client_access`, or the row's own client through `_assert_filing_scope`,
    `_assert_upload_scope` and the AIS delete's record lookup), and the firm and the client on every update and delete. The asset-block
    writers in `routers/income_tax.py` already wrote with the privileged client.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"ais_uploads", "ais_records", "ais_reconciliations", "ais_computation_decisions", "form_26as_records",
                    "income_tax_asset_blocks", "income_tax_worksheets", "itr_filing_versions", "tax_deduction_claims"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"ais_uploads": 2, "ais_records": 2, "ais_reconciliations": 2, "ais_computation_decisions": 2, "form_26as_records": 3,
               "income_tax_asset_blocks": 2, "income_tax_worksheets": 1, "itr_filing_versions": 1, "tax_deduction_claims": 1}


def test_every_write_to_the_income_tax_working_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to an income-tax working table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update or a delete of an income-tax working table does not name both the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"ais_records"})
    src = ('def f(sb):\n'
           '    sb.table("ais_records").delete().eq("id", 1).eq("firm_id", 2).execute()\n'
           '    privileged_for(sb).table("ais_records").delete().eq("id", 1).eq("firm_id", 2).eq("client_id", 3).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["ais_records at line 2"]
