"""
The Schedule III fixed-assets movement, computed once.

WHAT THIS IS
    Schedule III to the Companies Act 2013, Division I, requires the note on
    property, plant and equipment to be a MOVEMENT and not a snapshot: opening
    gross block, additions, deductions, closing gross block; then the same four
    for accumulated depreciation; then the net block at both ends. A note
    printing only the closing figures cannot be tied to last year's, which is
    the first thing a reader does with it.

WHY IT IS HERE AND NOT IN A ROUTER
    It was in `routers/year_end_notes.py`, and it was the only place in the
    product that knew how to build it. The fixed-asset module's own Reports tab
    therefore had no movement at all — it re-derived a gross block and an
    accumulated depreciation in the BROWSER, from the asset list, with no
    financial year applied to either (FA-15), while the note computed the right
    figures and rendered them nowhere (FA-05).

    Two screens needing one answer is the point at which a third implementation
    gets written. This module is the one implementation; both callers fetch
    their own rows — the note over `year_end_notes`' FY end, the FA route over
    an `fy` label — and pass them in.

WHAT IT TAKES AND WHAT IT REFUSES
    Rows in, movement out: no database handle, no fetching, no I/O. That is
    what makes it testable against a hand-written register and what keeps the
    paging rule (CLAUDE.md: every read of `fixed_assets` goes through
    `core.db_paging.fetch_all`) at the callers, where the query is.

    It refuses in one direction only. With no financial year to window on it
    reports the register AS IT STANDS — closing figures, no movement — rather
    than dating every asset into a year nobody named, and says so in a gap
    sentence. A movement with no period is not a conservative answer, it is a
    wrong one.

THREE THINGS THE ORIGINAL GOT WRONG, KEPT HERE BECAUSE THEY ARE EASY TO REDO

  1. THE CHARGE WAS THEORETICAL. It was `sum(annual charge for every asset on
     the register)` — whatever had actually been posted, and with no pro-rata
     for an asset bought in December. A note is a disclosure OF THE BOOKS. The
     total now comes off the ledger (the caller reads it) and the per-class
     split comes from the register's own record of what each asset was charged
     this year; where they disagree the difference is STATED, never absorbed.
  2. IT FILTERED OUT DISPOSED ASSETS, so an asset sold during the year vanished
     from the gross block instead of appearing as a deduction — last year's
     closing then did not tie to this year's opening and the reader could not
     see why. Every asset is included; only a SOFT-DELETED row is not, because
     migration 351 makes that a row created by mistake, which was never in the
     register at all.
  3. THERE WERE NO ADDITIONS OR DEDUCTIONS COLUMNS. Four closing figures and
     nothing to reconcile them with.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

#: The ten figures of one class's movement, in the order Schedule III presents
#: them. A dict rather than a dataclass because every caller sums, renders and
#: serialises them as a set, and naming each one in three places is how a
#: column goes missing from one of them.
MOVEMENT_KEYS: tuple[str, ...] = (
    "opening_gross_paise", "additions_paise", "deductions_paise",
    "closing_gross_paise", "opening_accum_paise", "charge_paise",
    "accum_on_deductions_paise", "closing_accum_paise",
    "closing_net_paise", "opening_net_paise",
)


def fy_window(fy_end: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(first day, last day) of the financial year ending on `fy_end`.

    April to March (CLAUDE.md). Returns (None, None) where there is no FY end
    to work from, and every caller treats that as "cannot compute" rather than
    as a zero.
    """
    if not fy_end or len(str(fy_end)) < 10:
        return None, None
    end = str(fy_end)[:10]
    return f"{int(end[:4]) - 1}-04-01", end


def fy_end_for_label(fy_label: Optional[str]) -> Optional[str]:
    """"2025-26" -> "2026-03-31". The inverse of the label `fy_window` derives.

    Accepts the canonical `YYYY-YY` and the `YYYY-YYYY` spelling
    `core.ist_clock.normalise_fy_label` also takes, because a label reaching a
    report may have come from either. Returns None for anything else rather
    than guessing a year — a report dated to the wrong FY is worse than one
    that says it has no period.
    """
    text = str(fy_label or "").strip()
    if len(text) < 7 or text[4] != "-":
        return None
    head = text[:4]
    if not head.isdigit():
        return None
    return f"{int(head) + 1}-03-31"


@dataclass(frozen=True)
class Movement:
    """One client's movement, by class and in total.

    `split_known` is False where at least one asset was last depreciated in a
    DIFFERENT financial year, so the register cannot say how much of its
    accumulated depreciation belongs to this one. The class-level charge is
    then incomplete, and the caller must say so rather than presenting a split
    that silently omits an asset.
    """
    classes: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    split_known: bool = True
    financial_year: Optional[str] = None
    windowed: bool = True


def _blank() -> dict:
    return {k: 0 for k in MOVEMENT_KEYS}


def movement_from_rows(rows: Iterable[dict], fy_end: Optional[str]) -> Movement:
    """The movement per asset class over the financial year ending `fy_end`.

    `rows` are `fixed_assets` rows — every one of them, disposed included, and
    soft-deleted ones already excluded by the caller's query.

    The gross-block movement comes from the REGISTER, which holds every fact it
    needs: a purchase date, a cost, and on a disposed row the disposal date and
    the accumulated depreciation it carried out with it. The per-class charge
    comes from `accumulated_depreciation_paise` less
    `depreciation_fy_start_accum_paise`, which the posting path writes — and
    that pair speaks only for the asset's CURRENT depreciation FY, which is why
    `split_known` exists.
    """
    fy_start, fy_last = fy_window(fy_end)
    fy_label = f"{fy_start[:4]}-{fy_last[2:4]}" if fy_start else None

    by_class: dict[str, dict] = {}
    split_known = True

    for a in rows:
        cls = a.get("asset_category") or "Other"
        m = by_class.setdefault(cls, _blank())
        cost = int(a.get("purchase_cost_paise") or 0)
        accum = int(a.get("accumulated_depreciation_paise") or 0)
        bought = str(a.get("purchase_date") or "")[:10]
        sold = str(a.get("disposal_date") or "")[:10] if a.get("is_disposed") else ""

        if not fy_start:
            m["closing_gross_paise"] += cost
            m["closing_accum_paise"] += accum
            continue

        held_at_open = bool(bought) and bought < fy_start and (not sold or sold >= fy_start)
        added = bool(bought) and fy_start <= bought <= fy_last
        removed = bool(sold) and fy_start <= sold <= fy_last

        charge = 0
        if a.get("depreciation_fy") and fy_label and a["depreciation_fy"] == fy_label:
            charge = accum - int(a.get("depreciation_fy_start_accum_paise") or 0)
        elif accum:
            # It has been depreciated, but not in the year this covers — so how
            # much of that belongs to this year is not on the row.
            split_known = False

        if held_at_open:
            m["opening_gross_paise"] += cost
            m["opening_accum_paise"] += accum - charge
        if added:
            m["additions_paise"] += cost
        if removed:
            m["deductions_paise"] += cost
            m["accum_on_deductions_paise"] += accum
        m["charge_paise"] += charge

    for m in by_class.values():
        if fy_start:
            m["closing_gross_paise"] = (m["opening_gross_paise"] + m["additions_paise"]
                                        - m["deductions_paise"])
            m["closing_accum_paise"] = (m["opening_accum_paise"] + m["charge_paise"]
                                        - m["accum_on_deductions_paise"])
        m["opening_net_paise"] = m["opening_gross_paise"] - m["opening_accum_paise"]
        m["closing_net_paise"] = m["closing_gross_paise"] - m["closing_accum_paise"]

    classes = [{"asset_class": cls, **m} for cls, m in sorted(by_class.items())]
    totals = {k: sum(c[k] for c in classes) for k in MOVEMENT_KEYS}
    return Movement(classes=classes, totals=totals, split_known=split_known,
                    financial_year=fy_label, windowed=bool(fy_start))


def posted_depreciation_paise(db, firm_id: str, client_id: str,
                              fy_start: str, fy_end: str) -> Optional[int]:
    """What was actually POSTED as depreciation in the year, or None.

    THE POINT OF THE CHANGE (FA-05). This figure used to be
    `sum(_annual_depreciation_for_period(a, fy_end_month))` — the THEORETICAL
    full-year charge for every asset on the register, whatever had actually been
    posted, and with no pro-rata for an asset bought in December. A note is a
    disclosure of the books; a charge that need not match anything in the P&L is
    not one. So it is read off the ledger.

    Read from `account_period_balances` (migrations 227/228), which is twelve
    pre-aggregated rows rather than every depreciation journal of the year —
    CLAUDE.md's reporting rule, and the reason that table exists.

    None means the Depreciation Expense account could not be resolved or the
    cache had nothing for the year. The caller reports that as a GAP; a zero
    would be a claim that nothing was charged.
    """
    try:
        from services.phase2_journal_service import phase2_journal_service
        account_id = phase2_journal_service._find_account(
            db, firm_id, client_id, "%Depreciation Expense%")
    except Exception:                                             # noqa: BLE001
        return None
    if not account_id:
        return None
    rows = (db.table("account_period_balances")
            .select("debit_paise,credit_paise,period_month")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("account_id", account_id)
            .gte("period_month", fy_start).lte("period_month", fy_end)
            .execute().data or [])
    if not rows:
        return None
    # An expense account: debits are the charge, credits are reversals of it.
    return sum(int(r.get("debit_paise") or 0) - int(r.get("credit_paise") or 0)
               for r in rows)


def rupees(paise: int) -> str:
    """Paise as a plain rupee figure for a sentence a CA reads."""
    return f"Rs {paise / 100:,.2f}"


def movement_gaps(movement: Movement, posted_charge_paise: Optional[int]) -> list[str]:
    """What this movement cannot vouch for, in sentences.

    Shared by both callers deliberately. The note and the Reports tab are
    looking at the same register through the same arithmetic, so a caveat that
    applies on one applies on the other — and two hand-written sets of caveats
    is how a screen comes to show a clean figure the note qualifies.

    `posted_charge_paise` is what the LEDGER carries for the year, or None
    where it could not be read. None is a gap, never a zero: a zero would be a
    claim that nothing was charged.
    """
    gaps: list[str] = []
    if not movement.windowed:
        gaps.append("No financial year was given, so this shows the register as "
                    "it stands rather than the year's movement.")
    elif posted_charge_paise is None:
        gaps.append("The depreciation actually posted for the year could not be "
                    "read from the ledger — the Depreciation Expense account "
                    "could not be resolved, or no entries were cached for the "
                    "period. The charge shown is the register's own record.")
    elif posted_charge_paise != movement.totals.get("charge_paise", 0):
        register = movement.totals.get("charge_paise", 0)
        gaps.append(
            f"The ledger carries {rupees(posted_charge_paise)} of depreciation "
            f"for the year and the register accounts for {rupees(register)}. "
            f"The difference of {rupees(abs(posted_charge_paise - register))} is "
            f"not explained here.")
    if not movement.split_known:
        gaps.append("One or more assets were last depreciated in a different "
                    "financial year, so this year's charge could not be "
                    "attributed to their class from the register.")
    return gaps
