"""Which part of a client's business a voucher line belongs to (ACC-13, D29).

WHAT WAS MISSING

    A CA could not tag a voucher to a cost centre, a branch or a project, so
    there was no departmental or project profit and loss — a routine Tally
    expectation and the first thing a client with two shops asks for. The
    16-09-2026 re-read measured the absence: one unrelated comment in the whole
    of `apps/api` and `apps/web`, and no migration mentioning them.

IT IS A DIMENSION, NOT A SECOND SET OF BOOKS

    The column changes no figure. A cost centre does not affect the double
    entry, the trial balance, the balance sheet or any statutory output: GST,
    TDS and the ITR are computed from documents and accounts, and a
    departmental P&L is MANAGEMENT reporting rather than Schedule III. A test
    asserts no return builder mentions the column, because a dimension leaking
    into a statutory total would be the worst possible version of this feature.

⚠️ MOST LINES HAVE NO COST CENTRE, AND THAT IS THE NORM

    Even at a client who uses the dimension fully. A bank leg, a GST leg and a
    TDS leg belong to no department — only the expense and revenue legs do — so
    an unallocated balance is not a gap to be chased, and the report shows it
    as its OWN ROW rather than dropping it or folding it into a department
    nobody chose. `department_cost.NOT_RECORDED` takes the same position on the
    payroll side for the same reason: a table that silently omits rows cannot
    be checked against the ledger it came from.

WHAT IS DELIBERATELY NOT HERE

    * **No balance sheet by cost centre.** A cost centre divides what a
      business SPENDS and EARNS. Splitting Trade Receivables or a bank balance
      across departments needs an allocation basis — by revenue? by headcount?
      by floor area? — that nothing in this product records, and inventing one
      would produce a departmental balance sheet that balances and means
      nothing. Named, not half-built.
    * **No hierarchy.** Tally nests cost centres under cost CATEGORIES. A tree
      is a second set of rollup rules and a second place for a total to
      disagree with itself; a flat list answers the question a practice asks
      first, and a parent column can be added when somebody needs one.
    * **No allocation of a shared cost.** Splitting one rent invoice across
      three departments by a percentage is a real feature and a different one:
      it is a rule about how a LINE is divided, and this is a label on a line
      that already exists. A CA who needs it enters the rent as three lines,
      which the manual journal already allows.
    * **No budget per cost centre.** `account_budgets` (migration 376) is keyed
      on the ACCOUNT, and widening it is a migration of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


#: The row a report shows for lines that carry no cost centre. NAMED rather
#: than blank, and never folded into a real centre: a bank leg belongs to no
#: department, so this row is expected to be large and its size is information.
UNALLOCATED = "(no cost centre)"

UNALLOCATED_IS_EXPECTED = (
    "Most lines carry no cost centre and that is normal — a bank leg, a GST "
    "leg and a TDS leg belong to no department. This row is the balance on "
    "lines nobody allocated, shown rather than dropped so the departments sum "
    "to the account."
)

A_DIMENSION_NOT_A_LEDGER = (
    "A cost centre changes no figure in the books. It divides what the client "
    "spends and earns for management reporting; the trial balance, the "
    "financial statements and every return are unaffected."
)

NO_BALANCE_SHEET_BY_COST_CENTRE = (
    "Only income and expenditure are divided by cost centre. Splitting a bank "
    "balance or a receivable across departments needs an allocation basis "
    "nothing here records, and a departmental balance sheet built on an "
    "invented one would balance and mean nothing."
)

#: Migration 418's CHECK, restated so the door can answer in a sentence rather
#: than a SQLSTATE. The length is the column's.
CODE_MAX = 24


def normalise_code(code: Optional[str]) -> str:
    """Trim and upper-case, so `factory` and `FACTORY ` are one centre.

    The unique index is on the STORED value, so normalising at the door is what
    makes it mean anything: without it a CA who typed a trailing space would
    create a second centre that looks identical on every screen and splits the
    department's cost in two.
    """
    return (code or "").strip().upper()


def problem_with_code(code: Optional[str]) -> Optional[str]:
    """What is wrong with this code, or None.

    Shaped like `gstin.problem_with` — one shape for "what is wrong with this
    identifier" — so a door reports a sentence and the screen can show it.
    """
    c = normalise_code(code)
    if not c:
        return "A cost centre needs a code."
    if len(c) > CODE_MAX:
        return f"A cost centre code is at most {CODE_MAX} characters."
    return None


def problem_with_name(name: Optional[str]) -> Optional[str]:
    if not (name or "").strip():
        return "A cost centre needs a name."
    return None


@dataclass(frozen=True)
class AllocatedLine:
    """One posted line, as the report reads it."""
    cost_centre_id: Optional[str]
    cost_centre_name: Optional[str]
    account_id: str
    account_name: str
    #: "income" or "expense". Anything else is not on a P&L and is DROPPED —
    #: see `income_and_expenditure_only`.
    account_kind: str
    debit_paise: int
    credit_paise: int


@dataclass(frozen=True)
class CentreAccount:
    account_id: str
    account_name: str
    account_kind: str
    #: Credit-positive for income, debit-positive for expense — each read the
    #: way its own side of the P&L is read, so both are positive when the
    #: business is doing the ordinary thing. `builders.profit_loss` does the
    #: same, and a report that showed expenses negative beside income positive
    #: would invite a reader to add them.
    amount_paise: int


@dataclass(frozen=True)
class Centre:
    cost_centre_id: Optional[str]
    name: str
    income_paise: int
    expense_paise: int
    accounts: tuple[CentreAccount, ...]

    @property
    def result_paise(self) -> int:
        """Income less expenditure. NOT called profit: a cost centre's result
        is before everything that is not divided by department — tax, interest
        the treasury carries, and every unallocated line — so calling it profit
        would invite somebody to add the departments up and expect the P&L."""
        return self.income_paise - self.expense_paise


@dataclass(frozen=True)
class Allocation:
    centres: tuple[Centre, ...]
    #: The lines nobody allocated, as its own centre with a null id. ALWAYS
    #: present when there are any, never merged, never dropped.
    unallocated: Optional[Centre]
    notes: tuple[str, ...] = ()
    #: Centres this client has defined that no line reached in the period.
    #: Reported so an empty department reads as empty rather than as absent.
    centres_with_no_activity: tuple[str, ...] = ()


def income_and_expenditure_only(lines: list[AllocatedLine]) -> list[AllocatedLine]:
    """Drop everything that is not on a P&L.

    An asset or liability line legitimately carries a cost centre — the CA may
    have tagged the bank leg of a departmental payment — and including it would
    put a bank balance in a departmental result. Filtering here, once, rather
    than asking each caller: see NO_BALANCE_SHEET_BY_COST_CENTRE.
    """
    return [l for l in lines if l.account_kind in ("income", "expense")]


def allocate(lines: list[AllocatedLine],
             defined_centres: Optional[dict[str, str]] = None) -> Allocation:
    """Group the period's income and expenditure by cost centre.

    `defined_centres` maps id → name for every centre this client has, so one
    with no activity can be REPORTED as quiet rather than being invisible —
    which is the difference between "the Kolkata branch spent nothing" and
    "somebody forgot to tag the Kolkata branch".
    """
    buckets: dict[Optional[str], dict] = {}
    for l in income_and_expenditure_only(lines):
        key = l.cost_centre_id
        b = buckets.setdefault(key, {
            "name": l.cost_centre_name or (UNALLOCATED if key is None else "Unnamed"),
            "income": 0, "expense": 0, "accounts": {},
        })
        if l.account_kind == "income":
            amount = l.credit_paise - l.debit_paise
            b["income"] += amount
        else:
            amount = l.debit_paise - l.credit_paise
            b["expense"] += amount
        a = b["accounts"].setdefault(
            l.account_id,
            {"name": l.account_name, "kind": l.account_kind, "amount": 0})
        a["amount"] += amount

    def build(key: Optional[str], b: dict) -> Centre:
        return Centre(
            cost_centre_id=key,
            name=b["name"],
            income_paise=b["income"],
            expense_paise=b["expense"],
            accounts=tuple(sorted(
                (CentreAccount(account_id=aid, account_name=a["name"],
                               account_kind=a["kind"], amount_paise=a["amount"])
                 for aid, a in b["accounts"].items()),
                key=lambda x: x.account_name,
            )),
        )

    centres = tuple(sorted(
        (build(k, v) for k, v in buckets.items() if k is not None),
        key=lambda c: c.name,
    ))
    unallocated = build(None, buckets[None]) if None in buckets else None

    quiet: tuple[str, ...] = ()
    if defined_centres:
        seen = {c.cost_centre_id for c in centres}
        quiet = tuple(sorted(
            name for cid, name in defined_centres.items() if cid not in seen))

    notes = [A_DIMENSION_NOT_A_LEDGER, NO_BALANCE_SHEET_BY_COST_CENTRE]
    if unallocated is not None:
        notes.append(UNALLOCATED_IS_EXPECTED)

    return Allocation(centres=centres, unallocated=unallocated,
                      notes=tuple(notes), centres_with_no_activity=quiet)
