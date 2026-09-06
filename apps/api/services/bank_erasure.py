"""
Why a bank account cannot be permanently deleted — the statute, the date, and
the same two-reason split the party deletes got in task #129.

WHAT WAS WRONG

`DELETE /banking/accounts/{id}` refused with a joined list of referential
reasons — "bank statements have been imported for it; it has been reconciled" —
and the Accounts panel rendered the same list into its own sentence in the
browser. Neither named a law, neither gave a date, and neither ever lapses.

That is the failure this codebase has now fixed in three other places, and bank
data is the one where it mattered most and was missed: the retention position
written in #126 had NO CATEGORY FOR BANK DATA AT ALL. The product has held
statements since migration 006.

TWO REASONS, SAID SEPARATELY

  RETENTION — Companies Act s. 128(5) requires the vouchers relevant to any
  entry kept for eight financial years, and a bank statement is the voucher for
  every receipt and payment posted off it. This one HAS AN END, computable from
  the financial year the newest statement covers.

  REFERENTIAL — reconciliations, payroll runs and posted journal lines point at
  the account or at its ledger. That does not lapse while they exist, and it is
  what actually makes the row undeletable: bank_statements, bank_reconciliations
  and payroll_runs all FK to bank_accounts with NO ACTION.

WHY THE STATEMENT DATE, AND WHY THE NEWEST ONE

`bank_statements.statement_to` is the last day the statement covers, so its
financial year is the year the record belongs to. The NEWEST statement is held
longest, so it is the only one that decides whether the account may go — the
same rule `decision_for_record_date` states for the party deletes.

An account blocked only by reconciliations, payroll or a posted ledger, with no
statement imported, has no date to anchor a duty to. It says so, rather than
invoking a statute it cannot date.
"""
from __future__ import annotations

from datetime import date

from domain.dpdp.retention import decision_for_record_date

#: The category in domain/dpdp/retention.py this path erases under.
CATEGORY = "bank_data"

_DEACTIVATE = ("Deactivate it instead — that keeps its history and takes it out "
               "of the pickers.")


def _parse(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def refusal(
    reasons: list[str],
    *,
    latest_statement_end: str | None,
    today: date | None = None,
) -> str:
    """The sentence a CA reads when a bank account cannot be deleted.

    `reasons` are the referential blockers, already in the order a CA cares
    about. `latest_statement_end` is `statement_to` of the newest statement
    imported for the account, or None when none was.

    Callers must not call this with an empty `reasons` — an account with no
    blocker at all is deleted, not refused.
    """
    joined = "; ".join(reasons)
    parsed = _parse(latest_statement_end)

    if parsed is None:
        # No statement, so nothing here to date a retention duty from. The
        # blockers are records of other categories (a reconciliation, a payroll
        # run, a posted journal line) and the honest reason is referential.
        return (f"This bank account cannot be deleted because {joined}. "
                f"{_DEACTIVATE}")

    decision = decision_for_record_date(CATEGORY, parsed, today=today)

    if decision.erasable:
        # Every duty over the statements has lapsed. The account still does not
        # go: the rows pointing at it are what stop it, and saying so lets a CA
        # see that the remaining obstacle is the books rather than the law.
        return (f"Statutory retention over this account's bank statements has "
                f"lapsed — no law now requires them kept. It still cannot be "
                f"deleted because {joined}. {_DEACTIVATE}")

    return (f"{decision.reason} Until then this bank account cannot be "
            f"deleted; separately, {joined}. {_DEACTIVATE}")
