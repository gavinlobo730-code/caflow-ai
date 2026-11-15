"""The relationship tables and the treaty readings are WRITTEN with the privileged client, and the source says so at the write (POST-A-008,
the relationships tranche, part 1 of 2).

THE PREMISE
    `entity_roles` (a person or entity as a client's director, partner or shareholder, with the share held), `properties` (a client's house
    property, whose cost and rent feed the house-property working), `related_party_loans` (a loan to or from a related party, which the
    Section 185 and 186 flags read) and `dtaa_treaty_rates` (the firm's own reading of a tax treaty's rate for a country and a nature of
    income, which a payment to a non-resident is withheld on) are granted to the signed-in role behind policies that ask the firm (and the
    client assignment where a row names a client) and NO role tier: a Reviewer could add a director to a client or change the rate a
    non-resident is withheld at with their own sign-in. The browser writes none of them; every writer is the API's. Found by POST-A-008's
    list of the tables a signed-in session reaches outside the access matrix.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write to the four is made with the privileged
    client now, and every delete names its scope. One did not: removing a role named the role and the firm alone, and now names the client
    its scope check resolved, so a role id cannot reach another client's role.

    The loan is written through a constant (`db.table(LOANS_TABLE)`), which the shared census did not read until this change: it now reads a
    table named by a module-level string constant as the same write as one named in place. No table already closed had a writer hidden that
    way (measured when the census learnt it).

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group and its census.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"entity_roles", "properties", "related_party_loans", "dtaa_treaty_rates"})

#: A treaty reading is the firm's, with no client: it is named by its id and the firm.
KEYS = {"dtaa_treaty_rates": ("firm_id", "id")}

#: How many write sites each table has today. A change that adds or removes one updates this.
WRITE_SITES = {"entity_roles": 2, "properties": 1, "related_party_loans": 1, "dtaa_treaty_rates": 2}


def test_every_write_to_the_relationship_and_treaty_tables_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to a relationship table or the treaty readings is made with the caller's own client: the migration that "
                     "follows takes that client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  "
                     + "\n  ".join(bad))


def test_every_update_and_delete_names_its_scope():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update or delete of a relationship table or the treaty readings does not name its scope:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    t = frozenset({"entity_roles"})
    src = ('def f(db):\n'
           '    db.table("entity_roles").insert({}).execute()\n'
           '    privileged_for(db).table("entity_roles").delete().eq("id", 1).eq("firm_id", 2).execute()\n')
    sites = pw.write_sites(src, t)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, t) == ["entity_roles at line 3"]


def test_a_table_named_through_a_module_constant_is_read_as_that_table():
    t = frozenset({"related_party_loans"})
    src = ('LOANS_TABLE = "related_party_loans"\n'
           'OTHER: str = "related_party_loans"\n'
           'def f(db):\n'
           '    db.table(LOANS_TABLE).insert({}).execute()\n'
           '    privileged_for(db).table(OTHER).update({}).eq("id", 1).execute()\n'
           '    db.table(UNKNOWN).insert({}).execute()\n')
    sites = pw.write_sites(src, t)
    assert [(table, line, ok) for table, _fn, line, ok, _r in sites] == [
        ("related_party_loans", 4, False), ("related_party_loans", 5, True)]
    assert pw.unscoped_updates_and_deletes(src, t) == ["related_party_loans at line 5"]
