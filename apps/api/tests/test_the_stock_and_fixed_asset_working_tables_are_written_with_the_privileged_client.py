"""The stock and fixed-asset working tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
stock tranche, part 1 of 2).

THE PREMISE
    `capital_work_in_progress` and `cwip_additions` (an asset under construction and the cost that went into it, which Schedule III ages and
    the balance sheet carries), `godowns` and `inventory_batches` (where stock is kept and in which lot) and `purchase_bill_landed_costs`
    (the freight, duty and other costs AS-2 paragraph 6 puts into the cost of stock) are granted to the signed-in role behind policies that
    ask the firm and the client assignment and NO role tier: a Reviewer assigned to a client, who writes nothing through the API, could add a
    cost to a project or a landed cost to a bill with their own sign-in. The browser writes none of them; every writer is the API's. Found by
    POST-A-008's list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the five is made with the privileged
    client now, which carries no row security, so what the policies did is the route's to assert, and the firm and the client are named on
    every update and delete. Three did not name the client: removing a landed cost (it now takes the bill's own client, which the bill scope
    resolved), restating a Bill of Entry's carried duty and marking charges applied on a receipt (both name the client of the row they act
    for), and stamping a cost tranche with its journal.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"capital_work_in_progress", "cwip_additions", "godowns", "inventory_batches", "purchase_bill_landed_costs"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"capital_work_in_progress": 3, "cwip_additions": 2, "godowns": 4, "inventory_batches": 1, "purchase_bill_landed_costs": 5}


def test_every_write_to_the_stock_and_fixed_asset_working_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a stock or fixed-asset working table is made with the caller's own client: the migration that follows takes "
                     "that client's write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update or a delete of a stock or fixed-asset working table does not name the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"godowns"})
    src = ('def f(db):\n'
           '    db.table("godowns").insert({}).execute()\n'
           '    privileged_for(db).table("godowns").update({}).eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["godowns at line 3"]
