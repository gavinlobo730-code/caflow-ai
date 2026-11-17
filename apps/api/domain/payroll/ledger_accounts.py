"""The payroll ledger accounts: one vocabulary, and the one rule that picks an account for a client.

Every payroll writer (the accrual, a leaver's settlement, the salary disbursement) and every payroll reader (the 24Q tie-out
against "TDS Payable - Salary", the salary challan's link to the ledger, the ESI and professional-tax remittance's link) names
its accounts through this module and finds them through `services/payroll_ledger_accounts.resolve`, which asks `choose` below.
Before it each of them carried its own spelling (an ILIKE pattern in the posting, an exact name in the 24Q tie-out and the
challan register, another ILIKE in the remittance register), so a renamed account could be found by one and missed by another,
and the accrual and its readers could look at two different accounts without anything saying so (POST-A-083).

THE KEY IS THE DECISION, THE NAME IS THE FALLBACK. `chart_of_accounts.system_account_key` carries one of the keys below
(migration 640 stamps it where exactly one firm-level active account matched and no client-level one did; a new firm's chart
is seeded with it). An account found by its key is found after a rename. An unkeyed chart is still served by the pattern the
posting has always used, so no firm that finalises today stops finalising.

WHICH ROW, IN ORDER: the client's own row carrying the key, a firm-level row carrying the key, the client's own row matching
the pattern, a firm-level row matching the pattern. Another client's row is never a candidate (migration 360's trigger would
refuse it on a journal line anyway). Within one step, two candidates are not resolved by an unordered `limit(1)`: two
carrying the key cannot exist (migration 640's unique index), and of two matching the pattern the one whose name IS the
canonical name wins, or the lookup is refused with both names, because a coin toss between two payables is how a liability
is credited to one account and cleared from another.

The keys are prefixed `payroll_` so they cannot collide with the control-account keys of migration 092 (`tds_payable`, which
that migration stamped on BOTH TDS accounts, is the reason the salary account needs a key of its own).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class PayrollLedger:
    key: str        # chart_of_accounts.system_account_key
    name: str       # the canonical name on the standard chart (coa_seed_service.STANDARD_COA)
    code: str       # its code on the standard chart
    pattern: str    # the ILIKE pattern an unkeyed chart is still searched with (the posting's own, unchanged)
    what: str       # what the account is for, in a person's words


SALARIES_EXPENSE = PayrollLedger("payroll_salaries_expense", "Salaries Expense", "5002", "%Salaries Expense%",
                                 "salaries and wages (the gross pay debited on a payroll accrual)")
EMPLOYER_CONTRIBUTION = PayrollLedger("payroll_employer_contribution", "Contribution to Provident and Other Funds", "5016",
                                      "%Contribution to Provident%",
                                      "the employer's PF, EDLI, EPF administration charge and ESI")
NET_SALARY_PAYABLE = PayrollLedger("payroll_net_salary_payable", "Net Salary Payable", "2008", "%Net Salary Payable%",
                                   "net pay owed to employees")
PF_PAYABLE = PayrollLedger("payroll_pf_payable", "PF Payable", "2005", "%PF Payable%",
                           "provident fund contributions owed to the EPFO")
ESI_PAYABLE = PayrollLedger("payroll_esi_payable", "ESI Payable", "2006", "%ESI Payable%",
                            "ESI contributions owed to the ESIC")
PT_PAYABLE = PayrollLedger("payroll_pt_payable", "PT Payable", "2007", "%PT Payable%",
                           "professional tax deducted and not yet paid")
TDS_PAYABLE_SALARY = PayrollLedger("payroll_tds_payable_salary", "TDS Payable - Salary", "2004", "%TDS Payable - Salary%",
                                   "tax deducted from salary and not yet deposited")
EMPLOYEE_LOANS = PayrollLedger("payroll_employee_loans", "Employee Loans & Advances", "1240", "%Employee Loans%",
                               "loans and advances given to employees and recovered from pay")

ALL: tuple[PayrollLedger, ...] = (SALARIES_EXPENSE, EMPLOYER_CONTRIBUTION, NET_SALARY_PAYABLE, PF_PAYABLE, ESI_PAYABLE,
                                  PT_PAYABLE, TDS_PAYABLE_SALARY, EMPLOYEE_LOANS)
BY_KEY: Mapping[str, PayrollLedger] = {ledger.key: ledger for ledger in ALL}
BY_CODE: Mapping[str, PayrollLedger] = {ledger.code: ledger for ledger in ALL}

#: The statutory dues among them: the year-end TDS-and-statutory schedule tab lists these whatever they are called.
STATUTORY_LIABILITY_KEYS = frozenset({NET_SALARY_PAYABLE.key, PF_PAYABLE.key, ESI_PAYABLE.key, PT_PAYABLE.key,
                                      TDS_PAYABLE_SALARY.key})

#: How a resolution was made, carried on the answer so a screen can say it.
BY_KEY_VIA, BY_NAME_VIA = "key", "name"


@dataclass(frozen=True)
class Resolved:
    id: str
    account_name: str
    via: str            # BY_KEY_VIA or BY_NAME_VIA


class PayrollLedgerError(ValueError):
    """A payroll account could not be chosen. A ValueError so every posting path that already re-raises one keeps doing so."""

    def __init__(self, ledger: PayrollLedger, sentence: str):
        super().__init__(sentence)
        self.ledger = ledger
        self.sentence = sentence


class PayrollLedgerMissing(PayrollLedgerError):
    pass


class PayrollLedgerAmbiguous(PayrollLedgerError):
    pass


def _matches(name: str, pattern: str) -> bool:
    """ILIKE with only leading/trailing '%' wildcards, which is every pattern in ALL."""
    core = pattern.strip("%").lower()
    hay = (name or "").lower()
    if pattern.startswith("%") and pattern.endswith("%"):
        return core in hay
    if pattern.endswith("%"):
        return hay.startswith(core)
    if pattern.startswith("%"):
        return hay.endswith(core)
    return hay == core


def _tiers(rows: Iterable[Mapping], client_id: Optional[str]) -> tuple[list[Mapping], list[Mapping]]:
    rows = [r for r in rows if r.get("is_active", True)]
    own = [r for r in rows if client_id and str(r.get("client_id") or "") == str(client_id)]
    firm = [r for r in rows if not r.get("client_id")]
    return own, firm


def missing_sentence(ledger: PayrollLedger) -> str:
    return (f'No active ledger for {ledger.what} was found in this client\'s chart of accounts: the product looks for the '
            f'account marked as the payroll "{ledger.name}" ledger, or one whose name contains "{ledger.pattern.strip("%")}". '
            f'Add or reactivate it before this is posted.')


def choose(ledger: PayrollLedger, *, key_rows: Sequence[Mapping], name_rows: Sequence[Mapping],
           client_id: Optional[str]) -> Optional[Resolved]:
    """The account for `ledger` in this client's view, or None when there is none. Raises PayrollLedgerAmbiguous rather than
    pick between two. `key_rows` are the firm's active rows carrying the key and `name_rows` those matching the pattern, each
    already narrowed to this client's own rows and the firm-level ones (a row of another client is dropped here as well)."""
    own, firm = _tiers([r for r in key_rows if r.get("system_account_key") == ledger.key], client_id)
    for tier in (own, firm):
        if len(tier) == 1:
            return Resolved(str(tier[0]["id"]), str(tier[0].get("account_name") or ledger.name), BY_KEY_VIA)
        if len(tier) > 1:
            raise PayrollLedgerAmbiguous(ledger, _ambiguous(ledger, tier, "are each marked as that ledger"))
    own, firm = _tiers([r for r in name_rows if _matches(str(r.get("account_name") or ""), ledger.pattern)], client_id)
    for tier in (own, firm):
        if len(tier) == 1:
            return Resolved(str(tier[0]["id"]), str(tier[0].get("account_name") or ledger.name), BY_NAME_VIA)
        if len(tier) > 1:
            exact = [r for r in tier if str(r.get("account_name") or "").strip().lower() == ledger.name.lower()]
            if len(exact) == 1:
                return Resolved(str(exact[0]["id"]), str(exact[0]["account_name"]), BY_NAME_VIA)
            raise PayrollLedgerAmbiguous(ledger, _ambiguous(ledger, tier, "each match the name it is looked for by"))
    return None


def _ambiguous(ledger: PayrollLedger, tier: Sequence[Mapping], how: str) -> str:
    names = sorted(f'"{r.get("account_name")}"' for r in tier)
    return (f"More than one ledger could be the one for {ledger.what}: {', '.join(names)} {how}. The product will not "
            f'choose between them. Rename or deactivate all but one, or name one exactly "{ledger.name}".')
