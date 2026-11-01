"""Let a test plant a row migrations 565 and 566 refuse, or roll a table back to an older shape, in a throwaway database.

Migration 565 makes the database refuse a row that names a client of another firm (and a customer or vendor of another client), and 566 one that names a member of another firm. Several
test modules exist to measure the OTHER defences against exactly that shape of row: a reader that must ignore another firm's rows
even when they share a client id, a migration that must count rows written under the old hole, a parity test whose SQL half scopes by
firm and client. Those rows can still exist as LEGACY data (the apply report of 565 counts them in production), so the modules plant
them with the six triggers switched off, in a database that is thrown away. The triggers themselves are measured by
`test_565_*_pg.py` and `test_566_*_pg.py`, which never use this.

Two things are offered, both limited to the eight trigger names 565 and 566 create:

  * `LEGACY_ROWS_ALLOWED`: SQL that DISABLES them on every table, to put at the top of a seed that plants such a row;
  * `TRIGGERS_DROPPED`: SQL that DROPS them, for a test that rolls a table back to an older column shape (Postgres refuses
    `ALTER COLUMN ... TYPE` on a column a trigger names, and a dropped column leaves the statement trigger reading a name that is
    gone). In real history those migrations ran long before 565, so only the simulation needs this.

The ledger-account triggers of migration 570 are matched by their name pattern (`row_ledger_account_<column>_ins` and `_upd`). Neither touches any other trigger, so a seed that depends on the balance or audit triggers still gets them.
"""
from __future__ import annotations

import subprocess

NAMES = (
    "row_client_in_firm_ins", "row_client_in_firm_upd",
    "row_customer_in_client_ins", "row_customer_in_client_upd",
    "row_vendor_in_client_ins", "row_vendor_in_client_upd",
    # Migration 566 (POST-A-361): a row names a member of its own firm.
    "row_member_in_firm_ins", "row_member_in_firm_upd",
)


#: Migration 570 (POST-A-353): a row names a ledger account of its own client. One pair of triggers per column, named by the column.
LEDGER_ACCOUNT_PATTERN = "row\\_ledger\\_account\\_%"


def _each(action: str) -> str:
    names = ", ".join(f"'{n}'" for n in NAMES)
    return (
        "DO $m565$ DECLARE r record; BEGIN "
        f"FOR r IN SELECT g.tgrelid::regclass AS t, g.tgname AS n FROM pg_trigger g WHERE NOT g.tgisinternal "
        f"AND (g.tgname IN ({names}) OR g.tgname LIKE '{LEDGER_ACCOUNT_PATTERN}') LOOP "
        f"EXECUTE format('{action}', r.t, r.n); "
        "END LOOP; END $m565$;\n"
    )


LEGACY_ROWS_ALLOWED = _each("ALTER TABLE %s DISABLE TRIGGER %I")
# `format` takes its arguments in order: the table first, then the trigger, so the drop reads them the other way round.
TRIGGERS_DROPPED = _each("DROP TRIGGER IF EXISTS %2$I ON %1$s")


def allow_legacy_rows(dsn: str) -> None:
    """Switch the six triggers off in the database `dsn` names, for a test that plants rows with several separate statements."""
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                          input=LEGACY_ROWS_ALLOWED, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
