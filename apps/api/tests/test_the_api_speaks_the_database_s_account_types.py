"""The API's account types are the database's account types.

THE DEFECT THIS EXISTS FOR

`chart_of_accounts.account_type` has carried
`CHECK (account_type IN ('Asset','Liability','Equity','Revenue','Expense'))`
since migration 003. `models.accounting.AccountType` said `INCOME = "Income"`
and had no REVENUE member at all, and `routers/accounting.py` writes
`data.account_type.value` verbatim. So the one revenue-shaped option the API
accepted was the one value the database refuses: a CA opening Account Groups
and adding a revenue ledger got a CHECK violation they read as "could not
create the account", and there was NO WAY to create one through that endpoint.

Measured on production before the fix: Asset 42, Expense 40, Liability 24,
Revenue 19, Equity 8 — and ZERO 'Income'. That is what a constraint refusing
every one of them looks like from outside.

WHY ~12,000 TESTS PASSED OVER IT

Mock mode has no CHECK constraint. The mock path accepts "Income" happily, so
the whole suite exercised the broken value and went green — and the real
failure only ever happened in a deployment with a database.

WHY THIS TEST READS THE MIGRATION RATHER THAN RESTATING IT

A test that listed the five strings would be a THIRD copy of the vocabulary,
free to drift from both the enum and the schema — which is exactly the shape
of the bug. It parses the constraint out of the migration instead, so the
migration stays the single authority and this fails the moment the two
disagree. Source-only, so it runs in the required mock-mode job where a
real-Postgres test would not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from models.accounting import AccountType

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

#: The migration that declares the constraint. Named rather than searched, so
#: a later migration that RELAXES it has to be pointed at here deliberately.
_DECLARING_MIGRATION = "003_phase3a_foundation.sql"


def _types_the_database_allows() -> set[str]:
    """Read the CHECK out of the migration that declares it."""
    sql = (MIGRATIONS / _DECLARING_MIGRATION).read_text()
    m = re.search(
        r"account_type\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*account_type\s+IN\s*\(([^)]*)\)",
        sql, re.I)
    assert m, (
        f"{_DECLARING_MIGRATION} no longer declares chart_of_accounts."
        f"account_type's CHECK in the shape this test reads. If the constraint "
        f"MOVED, point _DECLARING_MIGRATION at its new home; if it was DROPPED, "
        f"that is a decision this test should be told about rather than deleted "
        f"around.")
    return {v.strip().strip("'\"") for v in m.group(1).split(",") if v.strip()}


def test_the_migration_still_declares_the_constraint():
    """The control on every assertion below: if the parse silently returned
    nothing, each comparison would pass against an empty set."""
    assert len(_types_the_database_allows()) == 5


def test_every_type_the_api_accepts_is_one_the_database_allows():
    """The direction that was broken. An API value the CHECK refuses is a 422
    the CA cannot act on, and it is raised by Postgres rather than by the
    request model, so the message names a constraint instead of a field."""
    allowed = _types_the_database_allows()
    offenders = {t.value for t in AccountType} - allowed
    assert not offenders, (
        f"AccountType accepts {sorted(offenders)}, which chart_of_accounts' "
        f"CHECK refuses. routers/accounting.py writes account_type.value "
        f"verbatim, so every one of these is a create that fails in the "
        f"database. The database is the authority — change the enum.")


def test_every_type_the_database_allows_can_be_asked_for():
    """The other direction, and the one that made this unfixable from the
    screen: 'Revenue' was allowed by the database, produced by the seed, and
    classified by Schedule III — and no API value could reach it."""
    allowed = _types_the_database_allows()
    missing = allowed - {t.value for t in AccountType}
    assert not missing, (
        f"The database allows {sorted(missing)} and no AccountType member asks "
        f"for it, so no caller can create one. That is how 'Revenue' became "
        f"unreachable while 'Income' was the only revenue-shaped option.")


def test_income_is_still_accepted_and_folds_to_revenue():
    """The alias, in the shape schedule_iii.CAPTION_ALIASES uses: one canonical
    spelling, the older one honoured on the way IN so nothing that already
    sends it starts failing. `services/coa_seed_service.py` records that both
    have been in circulation and migration 098 queries for both."""
    assert AccountType("Income") is AccountType.REVENUE
    assert AccountType("Income").value == "Revenue"


def test_the_alias_is_case_folded():
    """A caller sending 'income' or 'REVENUE' means the same type, and a 422
    there teaches nothing."""
    assert AccountType("income") is AccountType.REVENUE
    assert AccountType("REVENUE") is AccountType.REVENUE
    assert AccountType("  Asset  ") is AccountType.ASSET


def test_something_that_is_not_an_account_type_is_still_refused():
    """The alias must not become "accept anything"."""
    for bad in ("Incomes", "Turnover", "", "Sales", "revenue account"):
        with pytest.raises(ValueError):
            AccountType(bad)


def test_the_schedule_iii_classifier_reads_the_same_word():
    """The third copy of this vocabulary, and the reason 'Income' was not
    merely refused but would ALSO have been dropped from the P&L had it ever
    been stored: `pl_bucket` tests `typ == "revenue"`."""
    from domain.reporting.schedule_iii import pl_bucket
    assert pl_bucket(AccountType.REVENUE.value, "Sales Revenue") is not None
    assert pl_bucket("Income", "Sales Revenue") is None, (
        "If this starts passing, the classifier has grown a second spelling "
        "and the canonical one is no longer the only one — which is the "
        "condition this whole file exists to prevent.")


def test_the_seeded_chart_uses_the_canonical_spelling():
    """The seed is what most firms' charts are made of, so it is the strongest
    evidence of which spelling is real."""
    from services.coa_seed_service import STANDARD_COA
    types = {row[2] for row in STANDARD_COA}
    assert "Revenue" in types
    assert "Income" not in types
