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

GAP_UNBILLED = (
    "unbilled_dues_not_modelled",
    "Schedule III requires unbilled dues to be disclosed separately under both "
    "ageing schedules. This platform has no unbilled revenue or accrued-"
    "liability document keyed to a customer or vendor, so there is nothing to "
    "report from and no figure is shown. A zero would claim there are none.",
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


# ── The schedules ────────────────────────────────────────────────────────────

def _empty(buckets) -> dict[str, int]:
    return {key: 0 for key, _label, _prescribed in buckets}


def _bucket_json(buckets) -> list[dict]:
    return [{"key": k, "label": lb, "prescribed": p} for k, lb, p in buckets]


def _table(rows, buckets, tallies: dict[str, dict[str, int]]) -> dict:
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
        # Not zero. Schedule III wants unbilled dues disclosed separately and
        # nothing in this schema holds them — see GAP_UNBILLED.
        "unbilled_dues_paise": None,
    }


def build(receivables: Iterable[Receivable], payables: Iterable[Payable],
          as_of: date, today: date) -> dict:
    """The two ageing schedules, in the shape public.schedule_iii_ageing returns.

    `today` is passed rather than read so the SQL half's CURRENT_DATE and this
    one can be held to the same value in the parity test; both mean the same
    thing, which is the date the outstanding balances are true as at.
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

    receivables_table = _table(RECEIVABLE_ROWS, RECEIVABLE_BUCKETS, ar_tallies)
    receivables_table["title"] = "Trade Receivables ageing schedule"

    payables_table = _table(PAYABLE_ROWS, PAYABLE_BUCKETS, ap_tallies)
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

    gaps = [GAP_UNBILLED]
    if unclassified:
        gaps.append(GAP_UNCLASSIFIED)
    if as_of < today:
        gaps.append(GAP_AS_AT)

    return {
        "as_of": as_of.isoformat(),
        "division": "I",
        "statute": STATUTE,
        "ageing_from": AGEING_FROM,
        "receivables": receivables_table,
        "payables": payables_table,
        "gaps": [{"code": c, "message": m} for c, m in gaps],
    }
