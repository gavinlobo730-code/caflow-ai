"""The online-payment tables are WRITTEN with the privileged client, and the source says so at the write (POST-A-008, the payments tranche,
part 1 of 2).

THE PREMISE
    `customer_payment_links` (a hosted payment link for an invoice's outstanding balance), `customer_payments` (what a gateway reported paid,
    and the receipt it settled into) and `customer_payment_events` (each webhook delivery, the replay guard) are granted to the signed-in role
    behind policies that ask the firm (and the client assignment where a row names a client) and NO role tier: a signed-in member could mark a
    payment captured, point it at another receipt or forge a delivery row with their own sign-in. The browser writes none of them; every
    writer is `services/payment_service.py`, which three routes reach: staff making a link (their own sign-in), a portal client paying (theirs)
    and the gateway's webhook (none). Found by POST-A-008's list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the three is made with the privileged
    client now, and every update names its scope. None did: the link's activation, the payment's claim, its release after a failed
    settlement, its capture, its plain status change and the link's "paid" each named the row's id alone. They now name the firm and the
    client too (the invoice's for the link, the payment row's own for the rest), so an id cannot reach another client's row.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"customer_payment_links", "customer_payments", "customer_payment_events"})

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"customer_payment_links": 3, "customer_payments": 5, "customer_payment_events": 1}


def test_every_write_to_the_online_payment_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to an online-payment table is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update of an online-payment table does not name the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"customer_payments"})
    src = ('def f(db):\n'
           '    db.table("customer_payments").insert({}).execute()\n'
           '    privileged_for(db).table("customer_payments").update({}).eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["customer_payments at line 3"]
