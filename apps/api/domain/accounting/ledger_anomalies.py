"""
Which accounts in a client's ledger look wrong — the rule, and nothing else.

WHAT THIS IS FOR. A CA closing a set of books has one question that no report
in this product answers: of these hundred-odd accounts, which ones should I
look at? The Trial Balance shows every account at once and says nothing about
which figure is odd; the Balance Sheet nets them into captions. Tally's users
reach for "Exception Reports" for exactly this, and it is the single most-used
thing in a close.

REPORT-ONLY, AND EVERY ANSWER IS A HEURISTIC — WHICH IS SAID OUT LOUD. Nothing
here is a statutory rule and nothing here is certain: each anomaly is a reason
to LOOK, carries the innocent explanation beside the guilty one, and is never
presented as a defect. That is the whole design constraint. A screen that
flags forty accounts on every client is worse than no screen, because the CA
stops reading it; so each check below is written to stay quiet on the ordinary
case, and the exclusions are as load-bearing as the tests.

IT READS THE POSTED ENTRIES, NOT `account_period_balances`, AND THAT IS
DELIBERATE. The buckets would be the cheaper source and the plan named them —
but migration 227's own header says the table "is a derived cache ... never a
source of truth on its own", and `services/balance_cache_service.
audit_and_heal_firm` exists because it can drift. A check whose entire job is
to find things that look wrong with the ledger must not read a cache that can
itself be wrong: it would either report an anomaly that is an artefact of the
drift, or stay silent about a real one because the cache is behind. And the
cost argument disappears on inspection — `run_reconciliation` already fetches
the posted ledger once and hands it to all nine existing checks, so deriving
the months here costs no round trip at all, while reading the buckets would
add one.

NO DATABASE HANDLE. Inputs are already-fetched accounts and monthly movements;
`services/reconciliation_service.check_ledger_anomalies` is the only caller and
does the fetching (which is to say: does none, because the runner has the
entries already).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


# ── What is normal for an account type ───────────────────────────────────────

#: An account type's normal balance side. Asset and Expense are debit-normal;
#: Liability, Equity and Revenue are credit-normal. "Income" is here beside
#: "Revenue" because production seeds use Revenue and the legacy mock used
#: Income — `domain/reporting/model.INCOME_TYPES` records the same pair, and
#: this reads that constant rather than restating it.
from domain.reporting.model import INCOME_TYPES  # noqa: E402

DEBIT_NORMAL: frozenset[str] = frozenset({"Asset", "Expense"})
CREDIT_NORMAL: frozenset[str] = frozenset({"Liability", "Equity"}) | INCOME_TYPES


def normal_side(account_type: Optional[str]) -> Optional[str]:
    """"Dr", "Cr", or None for a type this module does not recognise.

    None is a THIRD STATE and is never read as "Dr": `chart_of_accounts.
    account_type` carries a CHECK over five values, so an unrecognised one
    means the vocabulary MOVED, and guessing a side would flag every account
    of the new type as contra on the day it is added.
    """
    t = (account_type or "").strip()
    if t in DEBIT_NORMAL:
        return "Dr"
    if t in CREDIT_NORMAL:
        return "Cr"
    return None


# ── The exclusions, each for its own reason ──────────────────────────────────

#: An account whose balance sits on the opposite side to its type BY
#: CONSTRUCTION. Accumulated Depreciation is an Asset that is permanently in
#: credit; Drawings is Equity permanently in debit. Flagging them would put a
#: finding on every client, every month, for ever — the fastest way to teach a
#: CA to ignore the whole screen.
#:
#: MATCHED ON THE SUBTYPE **AND** THE NAME, because this repository has seeded
#: one account two ways: migration 054 gives Accumulated Depreciation the
#: subtype 'Contra Asset' and migration 093's chart gives it 'Fixed Asset'.
#: A subtype test alone is right for one of them and silent on the other.
CONTRA_SUBTYPE_PREFIX = "contra"

#: Lower-case fragments of `account_name`. Every entry can only ever SUPPRESS a
#: flag, so a phrase that also matches a normally-sided account (a "Provision
#: for Taxation" is a Liability in credit, which is its normal side) costs
#: nothing — there was no flag there to suppress.
CONTRA_NAME_FRAGMENTS: tuple[str, ...] = (
    "accumulated depreciation",
    "accumulated amortisation",
    "accumulated amortization",
    "provision for",
    "allowance for",
    "drawings",
)

#: A plain bank or cash ledger. A current account goes overdrawn, which puts an
#: Asset in credit and is entirely ordinary (BANK-21: an OVERDRAFT drawn
#: against a bank account is printed by the bank as a negative balance). A
#: client who runs a separate OD or credit-card facility has a LIABILITY ledger
#: for it — `domain/banking/account_kind._LEDGER_SHAPES` — which is
#: credit-normal and was never a candidate here.
BANK_OR_CASH_SUBTYPES: frozenset[str] = frozenset({"bank", "cash"})


def is_contra(name: Optional[str], subtype: Optional[str]) -> bool:
    if (subtype or "").strip().lower().startswith(CONTRA_SUBTYPE_PREFIX):
        return True
    low = (name or "").strip().lower()
    return any(frag in low for frag in CONTRA_NAME_FRAGMENTS)


def is_bank_or_cash(subtype: Optional[str], system_key: Optional[str]) -> bool:
    return ((subtype or "").strip().lower() in BANK_OR_CASH_SUBTYPES
            or (system_key or "").strip().lower() == "bank")


# ── Thresholds, each stated rather than buried ───────────────────────────────

#: Below this, a contra balance or a dormant balance is a rounding artefact
#: rather than a finding. ₹100.
#:
#: There is no correct universal figure — materiality is a judgement about the
#: client's own size, and a fixed number is wrong for a ₹10 lakh client and a
#: ₹100 crore one alike. It is a PARAMETER, it defaults low, and **every answer
#: states the floor it used**, so "no anomalies" can never be read as
#: "materially clean" by somebody who does not know what was ignored. Low
#: rather than high because over-reporting costs a glance and under-reporting
#: hides a misposting.
DEFAULT_MATERIALITY_PAISE = 100_00

#: How long an account must have been still, measured against the END OF THE
#: LEDGER rather than against its own last movement, before a balance on it is
#: worth asking about. Twelve months: a full financial year having gone by
#: without a single posting is the point at which "is this still real?" becomes
#: the question, and anything shorter would flag the ordinary annual rhythm —
#: an insurance prepayment, a yearly licence, an audit-fee accrual.
#:
#: ⚠️ THE FIRST DRAFT OF THIS CHECK COULD NEVER FIRE. It asked for a material
#: closing balance AND every month nil — and the closing balance IS the sum of
#: the months, so the two are contradictory and the branch was unreachable.
#: Caught by its own test, which had been written to assert the emptiness. The
#: rule was always about a WINDOW: the balance is inception-to-date and the
#: silence is recent.
DORMANT_MONTHS = 12

#: A month whose absolute net movement is this many times the MEDIAN of the
#: account's other non-nil months is called out. Six, because the error this
#: catches is a keyed extra zero — a factor of ten — while a genuine seasonal
#: peak in an Indian practice's book (March salary with the annual bonus, a
#: yearly insurance premium, the March advance-tax instalment) is rarely more
#: than three or four times an ordinary month.
OUTLIER_MULTIPLE = 6

#: How many OTHER non-nil months an account needs before a median means
#: anything. Four (so five including the candidate month). Below it the check
#: simply does not fire — and it does not emit "not enough history" either,
#: because that is not something wrong with the books, it is a client three
#: months old. The catalogue entry the screen renders says so instead.
MIN_MONTHS_FOR_A_MEDIAN = 4

#: THE MEDIAN AND NOT THE MEAN, and the reason is narrower than it first looks
#: — which is worth writing down, because the obvious justification is wrong.
#: The candidate month is already excluded from the comparison set, so on a
#: series with ONE odd month a mean and a median agree exactly. Where they part
#: is a SECOND large month: eleven ₹50,000 months and two of ₹5,00,000 leave
#: the other outlier inside the comparison set, so the mean rises to ₹1,25,000
#: and the ratio falls from 10x to 4x — under the threshold, and neither error
#: is reported. Two keying mistakes hiding each other is not a rare case; it is
#: what a recurring wrong template does every month it is used. The median does
#: not move.
#:
#: ⚠️ Recorded because the first draft of this comment claimed the mean would
#: be dragged up by the outlier ITSELF, and a negative control that swapped
#: `_median` for a mean passed every test — the reasoning was right about
#: medians and wrong about this arithmetic.


# ── The vocabulary ───────────────────────────────────────────────────────────

CONTRA_BALANCE = "ledger_contra_balance"
DORMANT_BALANCE = "ledger_dormant_balance"
OUTLIER_MONTH = "ledger_outlier_month"

#: Every kind this module can emit. A caller rendering these must be able to
#: enumerate them, and a list kept anywhere else is a second vocabulary.
ALL_KINDS: tuple[str, ...] = (CONTRA_BALANCE, DORMANT_BALANCE, OUTLIER_MONTH)

#: What this scan CANNOT see, named so a clean result is not read as a clean
#: set of books. Rendered beside the answer, the `table_4a_gaps` discipline.
NOT_CHECKED: tuple[str, ...] = (
    "Whether a posting is to the RIGHT account — an expense coded to the wrong "
    "head nets to the same trial balance and is invisible here.",
    "Whether a document exists behind an entry. The nine other checks in this "
    "engine cover the sub-ledgers; this one reads only the general ledger.",
    "Cut-off — an invoice dated in the wrong period moves a month's figure and "
    "looks exactly like trading.",
    "Anything about a client's FIRST four months, for the outlier check: a "
    "median needs a history, and inventing one from two data points would "
    "call an ordinary second month an anomaly.",
)


@dataclass(frozen=True)
class MonthlyMovement:
    """One account's net movement in one calendar month, as a DEBIT-positive
    figure in integer paise. `period_month` is the month's first day, ISO —
    the same key `account_period_balances.period_month` uses, so a future
    caller reading the buckets instead needs no translation."""
    period_month: str
    net_paise: int


@dataclass(frozen=True)
class LedgerAccount:
    id: str
    code: str
    name: str
    type: str
    subtype: Optional[str] = None
    system_key: Optional[str] = None


@dataclass(frozen=True)
class Anomaly:
    kind: str
    account_id: str
    account_code: str
    account_name: str
    #: One sentence saying what was seen, in a CA's words.
    summary: str
    #: The innocent explanation, always present. An anomaly with no benign
    #: reading would be a defect and would belong in one of the other checks.
    also_could_be: str
    amount_paise: int
    #: Set only where the anomaly is about one month.
    period_month: Optional[str] = None


def _median(values: list[int]) -> int:
    """Integer median. An even-length series takes `(a + b) // 2`, which floors
    — and flooring is the safe direction here because a SMALLER median makes
    the ratio larger and so flags rather than hides."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _closing(movements: Iterable[MonthlyMovement]) -> int:
    return sum(m.net_paise for m in movements)


def _last_month_that_moved(movements: Iterable[MonthlyMovement]) -> Optional[str]:
    moved = [m.period_month for m in movements if m.net_paise != 0]
    return max(moved) if moved else None


def _months_between(earlier: str, later: str) -> int:
    """Whole calendar months from one first-of-month to another. Calendar
    arithmetic rather than days, so the answer cannot disagree with itself
    across a leap year — `domain/fixed_assets/cwip`'s reason for the same."""
    ey, em = int(earlier[:4]), int(earlier[5:7])
    ly, lm = int(later[:4]), int(later[5:7])
    return (ly - ey) * 12 + (lm - em)


def scan(accounts: Iterable[LedgerAccount],
         movements_by_account: dict[str, list[MonthlyMovement]],
         *,
         materiality_paise: int = DEFAULT_MATERIALITY_PAISE) -> tuple[Anomaly, ...]:
    """Every anomaly, ordered largest amount first within each kind.

    `movements_by_account` is keyed on account id; an account absent from it
    has never been posted to and is skipped — a chart of accounts carries
    every account the seed created, most of which a given client never uses,
    and reporting those as dormant would be the forty-findings failure.
    """
    out: list[Anomaly] = []

    # WHEN THE BOOKS END, measured across EVERY account rather than per
    # account, because dormancy is "the client kept trading and this account
    # did not". Per account it would be circular: an account's own last
    # movement is zero months before itself, so nothing could ever be dormant.
    ledger_ends: Optional[str] = None
    for rows in movements_by_account.values():
        for row in rows:
            if ledger_ends is None or row.period_month > ledger_ends:
                ledger_ends = row.period_month

    for acct in accounts:
        months = movements_by_account.get(acct.id) or []
        if not months:
            continue
        closing = _closing(months)
        side = normal_side(acct.type)

        # ── 1. A balance on the side its own type does not carry ─────────────
        if (side is not None
                and abs(closing) >= materiality_paise
                and not is_contra(acct.name, acct.subtype)
                and not is_bank_or_cash(acct.subtype, acct.system_key)):
            on_credit = closing < 0
            if (side == "Dr" and on_credit) or (side == "Cr" and not on_credit):
                out.append(Anomaly(
                    kind=CONTRA_BALANCE,
                    account_id=acct.id, account_code=acct.code, account_name=acct.name,
                    summary=(
                        f"{acct.name} is a{'n' if acct.type[:1] in 'AEIOU' else ''} "
                        f"{acct.type} account, which normally carries a "
                        f"{'debit' if side == 'Dr' else 'credit'} balance, and it "
                        f"closes on the {'credit' if on_credit else 'debit'} side."
                    ),
                    also_could_be=(
                        "A customer advance or a supplier advance puts a control "
                        "account the other way round quite legitimately, and so "
                        "does a credit note raised before the invoice it relieves. "
                        "The usual guilty reading is a posting made the wrong way "
                        "round, or a receipt allocated to the wrong party."
                    ),
                    amount_paise=closing,
                ))

        # ── 2. Carries a balance and has been still for a year ───────────────
        last_moved = _last_month_that_moved(months)
        still_for = (_months_between(last_moved, ledger_ends)
                     if (last_moved and ledger_ends) else None)
        if (abs(closing) >= materiality_paise
                and still_for is not None
                and still_for >= DORMANT_MONTHS):
            out.append(Anomaly(
                kind=DORMANT_BALANCE,
                account_id=acct.id, account_code=acct.code, account_name=acct.name,
                summary=(
                    f"{acct.name} carries a balance and has not been posted to "
                    f"since {last_moved[:7]}, {still_for} months before the last "
                    f"entry in these books."
                ),
                also_could_be=(
                    "A rent or tender deposit, a long-term loan and a capital "
                    "account are all supposed to sit still for years. The reading "
                    "worth checking is an old receivable or payable nobody has "
                    "written off, or a figure carried over from the previous "
                    "system that was never cleared."
                ),
                amount_paise=closing,
            ))

        # ── 3. One month far above the account's own usual month ─────────────
        moved = [m for m in months if m.net_paise != 0]
        if len(moved) >= MIN_MONTHS_FOR_A_MEDIAN + 1:
            for i, candidate in enumerate(moved):
                others = [abs(m.net_paise) for j, m in enumerate(moved) if j != i]
                if len(others) < MIN_MONTHS_FOR_A_MEDIAN:
                    continue
                typical = _median(others)
                if typical <= 0:
                    continue
                size = abs(candidate.net_paise)
                if size >= typical * OUTLIER_MULTIPLE and size >= materiality_paise:
                    out.append(Anomaly(
                        kind=OUTLIER_MONTH,
                        account_id=acct.id, account_code=acct.code, account_name=acct.name,
                        summary=(
                            f"{acct.name} moved by an amount in {candidate.period_month[:7]} "
                            f"that is more than {OUTLIER_MULTIPLE} times its median "
                            f"month across the {len(moved)} months it moved."
                        ),
                        also_could_be=(
                            "March carries the annual bonus, the yearly insurance "
                            "premium and the last advance-tax instalment, and a "
                            "one-off capital purchase looks identical. The reading "
                            "worth checking is an extra zero."
                        ),
                        amount_paise=candidate.net_paise,
                        period_month=candidate.period_month,
                    ))

    out.sort(key=lambda a: (ALL_KINDS.index(a.kind), -abs(a.amount_paise)))
    return tuple(out)
