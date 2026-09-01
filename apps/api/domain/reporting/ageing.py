"""
The Schedule III ageing schedules — trade receivables and trade payables.

WHAT THIS IS
    MCA Notification G.S.R. 207(E) of 24 March 2021 amended Schedule III to the
    Companies Act 2013, with effect from 1 April 2021, to require two ageing
    schedules in the notes to the balance sheet. This is the rule that produces
    them: which row a document belongs in, and which column.

    These are DIVISION I (Accounting Standards) tables, matching the rest of the
    engine — routers/accounting.py's get_schedule_iii builds Division I.
    Division II (Ind AS) splits the doubtful receivables row into "which have
    significant increase in credit risk" and "credit impaired", after Ind AS
    109's expected-credit-loss language. The payables table is the same in both.

WHY THIS FILE EXISTS BESIDE THE SQL
    public.schedule_iii_ageing (migration 303) is what production runs: the
    answer is twenty-four numbers and the input is every open document, so
    CLAUDE.md's reporting rule puts the aggregation in the database. This is the
    identical rule for everything with no DATABASE_URL — mock mode, local dev,
    the in-memory suite — and tests/test_schedule_iii_ageing_parity_pg.py runs
    every scenario through BOTH and asserts the documents are equal, so the two
    cannot drift.

THE TWO TABLES ARE NOT THE SAME SHAPE
    Receivables age in five prescribed columns starting at six months; payables
    in four starting at one year. The row sets differ too. Getting the payables
    table five columns wide is the easy mistake, and it is why the bucket
    functions are separate rather than parameterised.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

# ── The prescribed tables ────────────────────────────────────────────────────

# "Not due" is NOT one of the prescribed columns. The prescribed table has none,
# and every outstanding amount must still appear somewhere for the total to tie
# to the balance sheet — an amount not yet due has been outstanding from its due
# date for a negative period, so folding it into the first bucket is the common
# filing choice and it overstates the ageing of a current book. Both figures are
# returned so either presentation can be made from one answer: a filer showing
# the prescribed columns adds not_due into the first bucket. The row totals are
# the same number either way.
RECEIVABLE_BUCKETS: tuple[tuple[str, str, bool], ...] = (
    ("not_due", "Not due",           False),
    ("lt_6m",   "Less than 6 months", True),
    ("m6_y1",   "6 months - 1 year",  True),
    ("y1_y2",   "1-2 years",          True),
    ("y2_y3",   "2-3 years",          True),
    ("gt_y3",   "More than 3 years",  True),
)

PAYABLE_BUCKETS: tuple[tuple[str, str, bool], ...] = (
    ("not_due", "Not due",          False),
    ("lt_y1",   "Less than 1 year",  True),
    ("y1_y2",   "1-2 years",         True),
    ("y2_y3",   "2-3 years",         True),
    ("gt_y3",   "More than 3 years", True),
)

RECEIVABLE_ROWS: tuple[tuple[str, str], ...] = (
    ("undisputed_good",     "(i) Undisputed Trade receivables – considered good"),
    ("undisputed_doubtful", "(ii) Undisputed Trade Receivables – considered doubtful"),
    ("disputed_good",       "(iii) Disputed Trade Receivables – considered good"),
    ("disputed_doubtful",   "(iv) Disputed Trade Receivables – considered doubtful"),
)

PAYABLE_ROWS: tuple[tuple[str, str], ...] = (
    ("msme",            "(i) MSME"),
    ("others",          "(ii) Others"),
    ("disputed_msme",   "(iii) Disputed dues – MSME"),
    ("disputed_others", "(iv) Disputed dues – Others"),
)

STATUTE = ("Schedule III to the Companies Act 2013, as amended by MCA "
           "Notification G.S.R. 207(E) dated 24 March 2021")
AGEING_FROM = ("due date of payment; where none is specified, the date of the "
               "transaction")

# MSMED Act 2006 classifications. NULL/None is not one of them: an unclassified
# vendor is a gap, never an "Other".
MSME_STATUSES: tuple[str, ...] = ("micro", "small", "medium", "not_registered")

# Row (i) of the payables table is "MSME", and it is read with the balance-sheet
# line item Schedule III already prescribes — "total outstanding dues of micro
# enterprises and small enterprises" — which comes from MSMED s.22 and stops at
# small. MSMED s.15, and so IT Act s.43B(h), works off "supplier", which s.2(n)
# also confines to micro and small. A MEDIUM enterprise is registered under
# MSMED and still belongs in Others.
MSME_ROW_STATUSES = frozenset({"micro", "small"})


# ── Gaps ─────────────────────────────────────────────────────────────────────
# Named, not silent. A zero and "not modelled" are opposite claims, and the
# unclassified-vendor one is the reason msme_status has no default at all.

# UNBILLED DUES, AND WHY THEY WERE LOOKED FOR IN THE WRONG PLACE
#
# Both notes end "Unbilled dues shall be disclosed separately." This used to
# report a permanent gap saying the platform held no unbilled-revenue document
# keyed to a party. That was true and it was beside the point: an unbilled due
# has NO DOCUMENT — having no document is what makes it unbilled. The accrual
# lives in the ledger, as the balance on an accrued-income or accrued-liability
# account, and Schedule III asks for one figure disclosed separately under each
# table rather than an aged or party-attributed one. An account balance is
# exactly that shape.
#
# WHY THEY ARE NOT AGED. The tables age from the due date of payment, or where
# none is specified from the date of the transaction. An unbilled due has
# neither — no invoice, no due date — which is precisely why the statute says
# "separately" rather than giving it a row. So it is one figure beside the
# table, never a bucket.
#
# WHICH ACCOUNTS HOLD THEM IS A HUMAN STEP, like the MSMED classification and
# the ITR schemas. No keyword on an account name can be trusted to decide it:
# "Accrued Interest" may be income receivable or an expense payable, and reading
# it wrong puts a liability in the receivables note. So an account carries an
# explicit `unbilled_dues_side` and nothing infers one.
#
# AND AN UNREVIEWED NIL IS NOT A NIL. If no account is marked, the honest answer
# is not zero — nobody has looked. A zero on a signed note asserts the client
# has no unbilled dues. So the figure stays NULL until a human records that they
# have been through this client's chart of accounts, after which zero is a real
# answer they have affirmed.

# 'receivable' is an ASSET balance (accrued income / unbilled revenue);
# 'payable' is a LIABILITY balance (accrued expenses / goods received not
# invoiced). The database enforces the pairing so a revenue account cannot be
# marked at all.
UNBILLED_SIDES: tuple[str, ...] = ("receivable", "payable")

GAP_UNBILLED_NOT_REVIEWED = (
    "unbilled_dues_not_reviewed",
    "Schedule III requires unbilled dues to be disclosed separately under both "
    "ageing schedules, and nobody has yet been through this client's chart of "
    "accounts to say which accounts hold them. No figure is shown, because a "
    "zero would claim there are none rather than that nobody has looked. Mark "
    "the accrued-income and accrued-liability accounts, then record the review "
    "— if there genuinely are none, recording the review discloses a nil that "
    "somebody has affirmed.",
)

GAP_UNBILLED_WRONG_SIGN = (
    "unbilled_account_in_contra_balance",
    "An account marked as holding unbilled dues has a balance on the wrong "
    "side — accrued income in credit, or an accrued liability in debit. The "
    "figure below includes it at its real (negative) balance rather than "
    "hiding it, but a contra balance on an accrual account is usually a "
    "reversal that was posted twice or an accrual that was never released.",
)

GAP_UNCLASSIFIED = (
    "vendors_unclassified",
    "One or more vendors with an open bill have no MSMED classification, so "
    "their balances are excluded from both the MSME and the Others rows. "
    "Classify them before signing the note: IT Act s.43B(h) makes the "
    "micro/small distinction change taxable income, not just presentation.",
)

GAP_AS_AT = (
    "as_at_is_current_balance",
    "Amounts are each document's balance outstanding TODAY, aged against the "
    "requested date. A document settled between that date and today is not "
    "included, so the schedule understates the position as at that date. Run "
    "it at the reporting date for an exact figure.",
)


# ── Date arithmetic ──────────────────────────────────────────────────────────

def minus_months(d: date, months: int) -> date:
    """`d` less `months` calendar months, clamped to a real date — identical to
    Postgres `d - interval 'N months'`, which is what the SQL half uses.

    Clamping is the whole reason this is not day arithmetic: 2026-03-31 less six
    months is 2025-09-30, and "six months" in the statute means six calendar
    months, not 180 days. The parity test pins month-end as-of dates for exactly
    this."""
    total = (d.year * 12 + (d.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _bucket(ref: Optional[date], as_of: date, cutoffs: tuple[tuple[int, str], ...],
            oldest: str, undated: str) -> str:
    """Shared bucketing. `cutoffs` is (months back, bucket) in youngest-first
    order; the first cutoff whose date the reference is strictly LATER than
    wins, so an amount outstanding for exactly six months is not "less than six
    months". A document with no reference date at all falls in the youngest
    prescribed bucket, which is what an undated document is assumed to be."""
    if ref is None:
        return undated
    if ref > as_of:
        return "not_due"
    for months, name in cutoffs:
        if ref > minus_months(as_of, months):
            return name
    return oldest


_AR_CUTOFFS = ((6, "lt_6m"), (12, "m6_y1"), (24, "y1_y2"), (36, "y2_y3"))
_AP_CUTOFFS = ((12, "lt_y1"), (24, "y1_y2"), (36, "y2_y3"))


def receivable_bucket(ref: Optional[date], as_of: date) -> str:
    """Five prescribed columns from six months, plus Not due."""
    return _bucket(ref, as_of, _AR_CUTOFFS, "gt_y3", "lt_6m")


def payable_bucket(ref: Optional[date], as_of: date) -> str:
    """Four prescribed columns from one year, plus Not due. Deliberately not the
    same function as receivable_bucket — the statute gives the two tables
    different columns."""
    return _bucket(ref, as_of, _AP_CUTOFFS, "gt_y3", "lt_y1")


def receivable_row_key(disputed: bool, doubtful: bool) -> str:
    if disputed:
        return "disputed_doubtful" if doubtful else "disputed_good"
    return "undisputed_doubtful" if doubtful else "undisputed_good"


def payable_row_key(disputed: bool, msme_status: Optional[str]) -> Optional[str]:
    """None where the vendor is unclassified — the caller must NOT fold that
    into Others. See MSME_ROW_STATUSES for why medium is Others and why an
    unclassified vendor is a gap rather than a default."""
    if msme_status is None:
        return None
    is_msme = msme_status in MSME_ROW_STATUSES
    if disputed:
        return "disputed_msme" if is_msme else "disputed_others"
    return "msme" if is_msme else "others"


# ── Inputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Receivable:
    """One open sales invoice. `ref_date` is its due date, or its invoice date
    where no due date is specified."""
    outstanding_paise: int
    ref_date: Optional[date]
    disputed: bool = False
    doubtful: bool = False


@dataclass(frozen=True)
class Payable:
    """One open purchase bill. `msme_status` is the VENDOR's classification, or
    None where nobody has classified them."""
    outstanding_paise: int
    ref_date: Optional[date]
    disputed: bool = False
    msme_status: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None


@dataclass(frozen=True)
class UnbilledAccount:
    """A GL account somebody has marked as holding unbilled dues. `side` is one
    of UNBILLED_SIDES and is recorded, never inferred from the name."""
    account_id: str
    account_code: str
    account_name: str
    side: str


@dataclass(frozen=True)
class PostingLine:
    """One posted journal line against one of those accounts. Raw debit and
    credit rather than a signed figure, because which way round they net is the
    rule this module owns — see unbilled_composition."""
    account_id: str
    entry_date: Optional[date]
    debit_paise: int = 0
    credit_paise: int = 0


# ── The schedules ────────────────────────────────────────────────────────────

def unbilled_composition(accounts: Iterable[UnbilledAccount],
                         lines: Iterable[PostingLine],
                         as_of: date) -> dict[str, list[dict]]:
    """Each marked account's balance as at `as_of`, per side.

    THE SIGN IS THE RULE, and it is per side rather than global. Accrued income
    is an asset and reads debit less credit; an accrued liability reads credit
    less debit. Using one convention for both would report every payable
    accrual as a negative receivable — the same money with the sign inverted,
    which on a note beside a balance sheet is not a rounding difference.

    Bounded by `as_of` inclusively, on the entry date, so the figure is the
    balance on the reporting date rather than today's. A line with no date
    cannot be placed in time and is left out; the ledger does not produce one.

    Accounts with no postings still appear, at zero. Somebody marked them, and a
    marked account missing from the composition reads as an account nobody
    marked.
    """
    totals: dict[str, int] = {}
    by_account: dict[str, UnbilledAccount] = {a.account_id: a for a in accounts}
    for ln in lines:
        acct = by_account.get(ln.account_id)
        if acct is None or ln.entry_date is None or ln.entry_date > as_of:
            continue
        debit, credit = int(ln.debit_paise or 0), int(ln.credit_paise or 0)
        signed = debit - credit if acct.side == "receivable" else credit - debit
        totals[acct.account_id] = totals.get(acct.account_id, 0) + signed

    out: dict[str, list[dict]] = {side: [] for side in UNBILLED_SIDES}
    for a in by_account.values():
        if a.side not in out:
            continue
        out[a.side].append({
            "account_id": a.account_id,
            "account_code": a.account_code,
            "account_name": a.account_name,
            "balance_paise": totals.get(a.account_id, 0),
        })
    # Largest first, then by CODE in byte order — the SQL half sorts
    # `ORDER BY balance DESC, account_code COLLATE "C"` so the two agree
    # without depending on the database's locale.
    for side in out:
        out[side].sort(key=lambda r: (-r["balance_paise"], r["account_code"].encode()))
    return out


def _empty(buckets) -> dict[str, int]:
    return {key: 0 for key, _label, _prescribed in buckets}


def _bucket_json(buckets) -> list[dict]:
    return [{"key": k, "label": lb, "prescribed": p} for k, lb, p in buckets]


def _table(rows, buckets, tallies: dict[str, dict[str, int]],
           unbilled: Optional[list[dict]]) -> dict:
    out_rows = []
    for key, label in rows:
        amounts = tallies.get(key) or _empty(buckets)
        out_rows.append({
            "key": key, "label": label, "amounts": amounts,
            "total_paise": sum(amounts.values()),
        })
    column_totals = {
        b: sum(r["amounts"][b] for r in out_rows)
        for b, _label, _prescribed in buckets
    }
    return {
        "buckets": _bucket_json(buckets),
        "rows": out_rows,
        "column_totals": column_totals,
        "total_paise": sum(r["total_paise"] for r in out_rows),
        # Beside the table, never inside it — the statute says "separately",
        # and an unbilled due has no due date to age from. None (not zero)
        # until somebody has reviewed the chart of accounts: see
        # GAP_UNBILLED_NOT_REVIEWED.
        "unbilled_dues_paise": None if unbilled is None
                               else sum(a["balance_paise"] for a in unbilled),
        "unbilled_accounts": [] if unbilled is None else unbilled,
    }


def build(receivables: Iterable[Receivable], payables: Iterable[Payable],
          as_of: date, today: date,
          unbilled_accounts: Iterable[UnbilledAccount] = (),
          unbilled_lines: Iterable[PostingLine] = (),
          unbilled_reviewed_on: Optional[date] = None) -> dict:
    """The two ageing schedules, in the shape public.schedule_iii_ageing returns.

    `today` is passed rather than read so the SQL half's CURRENT_DATE and this
    one can be held to the same value in the parity test; both mean the same
    thing, which is the date the outstanding balances are true as at.

    `unbilled_reviewed_on` is the date somebody recorded that they had been
    through this client's chart of accounts. None means nobody has, and that is
    what makes the unbilled figure None rather than zero — the two are opposite
    claims on a note somebody signs.
    """
    ar_tallies: dict[str, dict[str, int]] = {}
    for r in receivables:
        amt = int(r.outstanding_paise or 0)
        if amt <= 0:
            continue
        key = receivable_row_key(bool(r.disputed), bool(r.doubtful))
        ar_tallies.setdefault(key, _empty(RECEIVABLE_BUCKETS))
        ar_tallies[key][receivable_bucket(r.ref_date, as_of)] += amt

    ap_tallies: dict[str, dict[str, int]] = {}
    unclassified: dict[tuple[Optional[str], str], int] = {}
    for p in payables:
        amt = int(p.outstanding_paise or 0)
        if amt <= 0:
            continue
        key = payable_row_key(bool(p.disputed), p.msme_status)
        if key is None:
            slot = (p.vendor_id, p.vendor_name or "(vendor not found)")
            unclassified[slot] = unclassified.get(slot, 0) + amt
            continue
        ap_tallies.setdefault(key, _empty(PAYABLE_BUCKETS))
        ap_tallies[key][payable_bucket(p.ref_date, as_of)] += amt

    composition = unbilled_composition(unbilled_accounts, unbilled_lines, as_of)
    reviewed = unbilled_reviewed_on is not None

    receivables_table = _table(RECEIVABLE_ROWS, RECEIVABLE_BUCKETS, ar_tallies,
                               composition["receivable"] if reviewed else None)
    receivables_table["title"] = "Trade Receivables ageing schedule"

    payables_table = _table(PAYABLE_ROWS, PAYABLE_BUCKETS, ap_tallies,
                            composition["payable"] if reviewed else None)
    payables_table["title"] = "Trade Payables ageing schedule"
    payables_table["unclassified_paise"] = sum(unclassified.values())
    # Largest first, then by name in BYTE order — the SQL half sorts
    # `ORDER BY amt DESC, vendor_name COLLATE "C"` so the two agree without
    # depending on the database's locale.
    payables_table["unclassified_vendors"] = [
        {"vendor_id": vid, "vendor_name": name, "outstanding_paise": amt}
        for (vid, name), amt in sorted(unclassified.items(),
                                       key=lambda kv: (-kv[1], kv[0][1].encode()))
    ]

    gaps = []
    if not reviewed:
        gaps.append(GAP_UNBILLED_NOT_REVIEWED)
    elif any(a["balance_paise"] < 0
             for side in composition.values() for a in side):
        gaps.append(GAP_UNBILLED_WRONG_SIGN)
    if unclassified:
        gaps.append(GAP_UNCLASSIFIED)
    if as_of < today:
        gaps.append(GAP_AS_AT)

    return {
        "as_of": as_of.isoformat(),
        "division": "I",
        "statute": STATUTE,
        "ageing_from": AGEING_FROM,
        "unbilled_reviewed_on": unbilled_reviewed_on.isoformat() if reviewed else None,
        "receivables": receivables_table,
        "payables": payables_table,
        "gaps": [{"code": c, "message": m} for c, m in gaps],
    }
