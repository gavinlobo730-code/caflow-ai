"""The recurring and billing tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the
recurring-billing tranche, part 1 of 2).

THE PREMISE
    `billing_schedules` (the practice's retainers, which generate its own fee invoices), the lines of the recurring invoice and purchase bill
    templates (`recurring_invoice_template_lines`, `recurring_purchase_bill_template_lines`), and the run logs of the three recurring kinds
    (`recurring_invoice_runs`, `recurring_purchase_bill_runs`, `recurring_journal_runs`) are granted to the signed-in role behind policies that
    ask the firm (and on a schedule the client assignment) and NO role tier: a signed-in member could rewrite the lines a template will next
    raise as an invoice or a bill, or mark a run as done so the sweep skips it. The browser writes none of them; every writer is the API's.
    Found by POST-A-008's list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the six is made with the privileged
    client now, and every update and delete names its scope. A schedule's update and its advance named the firm only and now name the
    schedule's client too (the route passes the client it checked). A template's lines carry no firm or client of their own: they hang from
    the template, which the route reads under the firm and whose client it asserts, so their delete names the template.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"billing_schedules", "recurring_invoice_template_lines", "recurring_purchase_bill_template_lines", "recurring_invoice_runs",
                    "recurring_purchase_bill_runs", "recurring_journal_runs"})

#: A template's lines have no firm or client column: they are scoped by the template the route read under the firm.
KEYS = {"recurring_invoice_template_lines": ("template_id",), "recurring_purchase_bill_template_lines": ("template_id",)}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"billing_schedules": 3, "recurring_invoice_template_lines": 3, "recurring_purchase_bill_template_lines": 2,
               "recurring_invoice_runs": 1, "recurring_purchase_bill_runs": 1, "recurring_journal_runs": 1}


def test_every_write_to_the_recurring_billing_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a recurring or billing table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_and_delete_names_its_scope():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, ("an update or a delete of a recurring or billing table does not name the firm and the client (the template, for a "
                     "template's lines):\n  " + "\n  ".join(bad))


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"billing_schedules", "recurring_invoice_template_lines"})
    src = ('def f(db):\n'
           '    db.table("recurring_invoice_template_lines").insert([]).execute()\n'
           '    privileged_for(db).table("billing_schedules").update({}).eq("id", 1).eq("firm_id", 2).execute()\n'
           '    privileged_for(db).table("recurring_invoice_template_lines").delete().eq("id", 1).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True, True]
    assert sorted(pw.unscoped_updates_and_deletes(src, t, KEYS)) == ["billing_schedules at line 3", "recurring_invoice_template_lines at line 4"]
