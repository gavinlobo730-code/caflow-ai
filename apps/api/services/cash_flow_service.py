"""Fetches what `domain/cash_flow/forecast.py` needs, and decides nothing.

THE OPENING POSITION COMES OFF THE LEDGER. The screen this replaces asked the
CA to TYPE it, and every closing figure on a six-month statement is carried
forward from that one number — so a client whose bank ledger the product holds
had their whole projection hung off a keystroke. It is the sum of every
bank-and-cash ledger's balance, inception to date, read through
`ReportingService.period_net_by_account`: one window, ONE bucket read of
`account_period_balances`, so a client with 12,836 journal entries costs the
same as one with ten. `trial_balance` would have answered too and would have
fetched the chart and the buckets a second time for a figure this one already
has.

⚠️ THE WINDOW STARTS AT 1900-01-01 AND THAT IS NOT A SENTINEL DATE BEING
ABUSED. `period_net_by_account` is documented as exact when its windows are
MONTH-ALIGNED, and the 1st of January is; the answer is Σ(debit − credit) over
every posted line, which for an asset ledger IS the balance. A later start
would silently drop the opening balances that `opening_balance_service` posts.

WHICH LEDGERS ARE CASH is `domain/banking/account_category._looks_like_bank_or_cash`,
asked rather than re-spelled. Its Asset restriction is exactly right here and
is not a limitation to work around: a credit card's and an overdraft's ledgers
are LIABILITIES, and an overdrawn facility is borrowing rather than cash — a
forecast that added the card's balance to the bank's would report money the
client does not have.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.banking.account_category import _looks_like_bank_or_cash
from domain.cash_flow import forecast as rule

_logger = logging.getLogger("caflow.cash_flow")

#: Inception. See the module docstring — month-aligned, and early enough that
#: no opening balance falls before it.
_INCEPTION = "1900-01-01"

#: Migration 050's own vocabularies, minus the three that owe nothing.
#:
#: ⚠️ A DRAFT IS EXCLUDED BY STATUS AND WOULD NOT FALL OUT ON ITS OWN.
#: `outstanding_paise` is GENERATED from total less paid less credited
#: (migration 278), so a draft invoice — total set, nothing paid — reports its
#: whole value as outstanding. It is not a debt: nobody has been billed, and
#: counting it would forecast cash from an invoice the CA has not issued.
#: `paid` and `cancelled` owe nothing by construction and are out for the
#: ordinary reason.
_OPEN_SALES_STATUSES = ("issued", "partially_paid")
_OPEN_BILL_STATUSES = ("received", "partially_paid")


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def opening_cash_paise(svc, firm_id: str, client_id: str,
                       as_at: date) -> tuple[int, list[str]]:
    """Every bank-and-cash ledger's balance, added up, as at `as_at`."""
    gaps: list[str] = []
    answer = svc.period_net_by_account(
        firm_id, client_id,
        [("position", _INCEPTION, as_at.isoformat())],
    )
    accounts = answer.get("accounts") or {}
    nets = (answer.get("net_paise") or {}).get("position") or {}
    total = 0
    counted = 0
    for account_id, net in nets.items():
        meta = accounts.get(account_id) or {}
        if _looks_like_bank_or_cash({
            "account_type": meta.get("account_type"),
            "account_name": meta.get("account_name"),
            "account_subtype": meta.get("account_subtype"),
        }):
            total += int(net or 0)
            counted += 1
    if counted == 0:
        gaps.append(
            "No bank or cash ledger was found in this client's chart, so the "
            "opening position is nil. Every closing balance below is carried "
            "forward from it."
        )
    return total, gaps


def _receivables(db, firm_id: str, client_id: str):
    def page():
        return (db.table("client_sales_invoices")
                .select("id, invoice_no, invoice_date, due_date, "
                        "outstanding_paise, status, customer_name")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("status", list(_OPEN_SALES_STATUSES)))
    return fetch_all(page, key="id", label="cash_flow.receivables")


def _payables(db, firm_id: str, client_id: str):
    def page():
        return (db.table("purchase_bills")
                .select("id, bill_no, our_reference, bill_date, due_date, "
                        "outstanding_paise, status, vendor_name")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("status", list(_OPEN_BILL_STATUSES)))
    return fetch_all(page, key="id", label="cash_flow.payables")


def _loans(db, firm_id: str, client_id: str):
    def page():
        return (db.table("loans")
                .select("id, lender_name, emi_paise, disbursement_date, "
                        "maturity_date, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("status", "active"))
    return fetch_all(page, key="id", label="cash_flow.loans")


def _collect(rows, *, kind: str, ref_keys: tuple[str, ...], party_key: str):
    """Split a document set into dated flows and the undated ones, which are
    NAMED rather than guessed into a month."""
    dated: list[rule.ExpectedFlow] = []
    undated: list[rule.UndatedFlow] = []
    for row in rows:
        amount = int(row.get("outstanding_paise") or 0)
        if amount <= 0:
            continue
        reference = next(
            (str(row[k]) for k in ref_keys if row.get(k)), "—")
        party = str(row.get(party_key) or "")
        due = _as_date(row.get("due_date"))
        if due is None:
            undated.append(rule.UndatedFlow(
                amount_paise=amount, kind=kind,
                reference=reference, party=party))
            continue
        dated.append(rule.ExpectedFlow(
            due_on=due, amount_paise=amount, kind=kind,
            reference=reference, party=party))
    return dated, undated


def forecast_for_client(svc, db, firm_id: str, client_id: str, *,
                        months: int = 6,
                        as_at: Optional[date] = None) -> rule.Forecast:
    """The whole answer. `svc` is a `ReportingService` built for the caller's
    own scope; `db` may be None in mock mode, where there are no documents to
    read and the answer is the opening position and the named gaps."""
    today = as_at or ist_today()
    opening, gaps = opening_cash_paise(svc, firm_id, client_id, today)

    flows: list[rule.ExpectedFlow] = []
    undated: list[rule.UndatedFlow] = []

    if db is not None:
        sales, sales_undated = _collect(
            _receivables(db, firm_id, client_id),
            kind="receivable", ref_keys=("invoice_no",), party_key="customer_name")
        bills, bills_undated = _collect(
            _payables(db, firm_id, client_id),
            kind="payable", ref_keys=("bill_no", "our_reference"),
            party_key="vendor_name")
        flows.extend(sales)
        flows.extend(bills)
        undated.extend(sales_undated)
        undated.extend(bills_undated)

        # ⚠️ THIS MONTH'S EMI IS REPORTED, NOT COUNTED, AND THAT IS THE ONE
        # PLACE THE FORECAST REFUSES TO CHOOSE. Nothing records the DAY of the
        # month an EMI falls, and the opening position above is the bank
        # balance as it stands today — so an EMI already paid this month is
        # in that balance, and adding it again would charge it twice; while
        # one still to come is a real outflow the month needs. Both readings
        # are given, the way `late_filing.interest_on_rule_37_reversal` gives
        # both readings of a clock the rule does not settle. Every LATER month
        # is counted normally: nothing has been paid for those.
        this_month_emi = 0
        for loan in _loans(db, firm_id, client_id):
            emi = int(loan.get("emi_paise") or 0)
            disbursed = _as_date(loan.get("disbursement_date"))
            if emi <= 0 or disbursed is None:
                continue
            lender = str(loan.get("lender_name") or "Loan")
            for due in rule.emi_months(
                as_at=today, months=months,
                disbursed_on=disbursed,
                matures_on=_as_date(loan.get("maturity_date")),
            ):
                if (due.year, due.month) == (today.year, today.month):
                    this_month_emi += emi
                    continue
                flows.append(rule.ExpectedFlow(
                    due_on=due, amount_paise=emi,
                    kind="loan_emi", reference="EMI", party=lender))
        if this_month_emi:
            gaps.append(
                f"{this_month_emi} paise of loan EMI falls in the current "
                "month. Whether it has already gone out is not recorded — the "
                "loan carries no EMI date — and the opening position above "
                "already reflects anything paid, so it is NOT in the figures "
                "below. If it is still to come, this month's closing and every "
                "one after it is lower by that much."
            )
    else:
        gaps.append(
            "No database is configured, so no document was read — the figures "
            "below are the opening position alone."
        )

    return rule.build(as_at=today, opening_paise=opening, flows=flows,
                      undated=undated, months=months, gaps=gaps)
