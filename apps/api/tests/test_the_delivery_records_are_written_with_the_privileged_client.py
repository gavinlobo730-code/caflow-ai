"""The delivery records are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the deliveries tranche,
part 1 of 2).

THE PREMISE
    `invoice_deliveries` (every invoice, reminder and payment link emailed to a client's customer, with what the mail service said) and
    `customer_statement_deliveries` (every statement emailed) are granted to the signed-in role behind policies that ask the firm and the
    client assignment and NO role tier: a signed-in member could mark a delivery "sent" that the mail service never accepted, which is the row
    a CA reads to know a customer was told. The browser writes neither; every writer is the API's. Found by POST-A-008's list of the tables a
    signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the two is made with the privileged
    client now, and every update names the firm and the client. Five did not: the invoice send's two updates and the reminder's (they name the
    invoice's client now), a statement delivery's finish (it takes the firm and the client the route checked), and the mail service's bounce,
    which names a message and no firm, so the rows that carry the message are read first and each is updated by its own id, firm and client.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"invoice_deliveries", "customer_statement_deliveries"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"invoice_deliveries": 7, "customer_statement_deliveries": 3}


def test_every_write_to_the_delivery_records_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a delivery record is made with the caller's own client: the migration that follows takes that client's "
                     "write grant away. Make it with `privileged_for(db)`, naming the firm and the client:\n  " + "\n  ".join(bad))


def test_every_update_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update of a delivery record does not name the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"invoice_deliveries"})
    src = ('def f(db):\n'
           '    db.table("invoice_deliveries").insert({}).execute()\n'
           '    privileged_for(db).table("invoice_deliveries").update({}).eq("provider_message_id", 1).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["invoice_deliveries at line 3"]
