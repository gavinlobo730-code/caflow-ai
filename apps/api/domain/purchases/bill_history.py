"""What a supplier's earlier bills say about the next one (ai-23).

THE IDEA IS THE BANK QUEUE'S, APPLIED TO A DIFFERENT DOCUMENT
    `domain/banking/history.py` learns a coding from a payee's past decisions and
    returns the EVIDENCE for it — "coded to Rent 8 of the last 9 times, once to
    Repairs" — rather than a score, and never applies it. That has been wired into
    the bank work queue since Tier 1.4. It did not exist for a purchase bill: an
    extracted line got an exact HSN match to a catalogue item in the browser and
    nothing else, `expense_account_id` was always blank, and the CA re-chose the
    account, the ITC treatment and the TDS section for the fourth rent bill from
    the same landlord exactly as for the first — although the three before it
    were sitting in the same database, each recording what a human decided.

WHAT IS LEARNED, AND FROM WHAT
    From the RECEIVED bills of ONE supplier of ONE client of ONE firm — the caller
    has already scoped the rows, and this module never sees another supplier's.
    Two scopes, the more specific first:

      * per HSN/SAC  — "for HSN 9983, this supplier's lines went to Rent"
      * per supplier — the same, across every line, for a line with no HSN or an
                       HSN this supplier has not been billed under before

    and three subjects:

      * the EXPENSE ACCOUNT of a line;
      * ITC ELIGIBILITY of a line — surfaced ONLY when the winner is BLOCKED
        (CGST §17(5)). `purchase_bill_lines.itc_eligible` is NOT NULL DEFAULT
        true (migration 240), so "eligible, 5 of 5" restates the default and is
        not information; "blocked as motor-vehicle expense, 3 of 3" is;
      * the TDS SECTION — a NOTICE, not a click: a bill's TDS section is decided
        from the supplier record when the bill is created and is frozen there
        (`PurchaseBillUpdateIn` has no vendor_id, so it cannot be changed on the
        bill). So it is surfaced only where the earlier bills disagree with the
        supplier record as it stands now, which is the one case a CA needs told:
        a section that was withheld under three times and has since been cleared
        from the supplier, so this bill will withhold nothing.

WHY IT RETURNS EVIDENCE, AND WHY THERE IS NO THRESHOLD
    A bare confidence is unauditable. The suggestion carries `times_seen`,
    `total_seen`, the alternatives that lost and the date it was last seen, so
    "coded this way 3 of 3 times" is a claim somebody can act on or dismiss on
    sight. No minimum count is invented: one earlier bill is one human decision
    and the sentence says "once before", which is the honest size of it.

THE TIE RULE IS THE BANK'S, AND A TEST HOLDS THE TWO TOGETHER
    Most used, then most recent — two accounts used four times each is a real
    disagreement and the later decision is the better guess, but the loser still
    appears in `alternatives` so the CA sees the disagreement rather than a
    confident-looking coin flip. A third key (the value itself) makes the order
    TOTAL, so the same history reads the same on every request.

NOTHING HERE APPLIES ANYTHING
    It annotates. The editor shows each suggestion beside the field it concerns
    with the evidence, and a click sets the field. A suggestion is never written
    to a bill, never posts, and never changes what the document says.

A SUGGESTION NEVER NAMES AN ACCOUNT THE CLIENT CANNOT USE
    The account a line was coded to may since have been deactivated or may belong
    to another client's chart. The caller passes `usable_accounts` (id -> label)
    and a winner outside it is NOT suggested — the line is reported in `gaps`
    instead. Dropping the unusable rows and tallying the rest would be wrong in
    the other direction: five of six lines went to a deactivated account, so
    "coded to Repairs 1 of 1 times" would misstate what was done.

Pure and side-effect free: no database, no clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

BASIS_HSN = "hsn"
BASIS_SUPPLIER = "supplier"

#: How many bills the service reads, newest first. A supplier with years of
#: bills does not need all of them to answer "what do we usually do" — and the
#: recent decisions are the better evidence when the practice has changed how it
#: codes. Named here so the service, the tests and this header agree.
HISTORY_BILLS = 100

#: The most distinct HSN/SAC codes one request may ask about. A bill with more
#: lines than that is not a bill a CA types, and the answer must stay
#: proportional to the question.
MAX_HSNS = 100


@dataclass(frozen=True)
class Option:
    """One way this supplier's lines have gone before."""
    value: Any
    label: Optional[str]
    times: int
    last_seen: Optional[str]


@dataclass(frozen=True)
class Suggestion:
    """What history proposes for one field, with the evidence for it."""
    value: Any
    label: Optional[str]
    times_seen: int
    total_seen: int
    last_seen: Optional[str]
    basis: str                                   # BASIS_HSN | BASIS_SUPPLIER
    scope: str                                   # the HSN, or "" for the supplier
    alternatives: tuple[Option, ...]
    #: ITC only: the §17(5) clause the winning lines carried, most recent first.
    reason: Optional[str] = None

    @property
    def share_bps(self) -> int:
        """The winner's share in basis points. Integer arithmetic — a percentage
        is a display, never a stored figure."""
        return (self.times_seen * 10000) // self.total_seen if self.total_seen > 0 else 0

    @property
    def sentence(self) -> str:
        """A sentence a CA can judge on sight."""
        where = (f"for HSN/SAC {self.scope}" if self.basis == BASIS_HSN
                 else "across this supplier's earlier bills")
        if self.total_seen == 1:
            return f"Coded this way once before, {where}"
        return f"Coded this way {self.times_seen} of {self.total_seen} times, {where}"

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "label": self.label,
            "times_seen": self.times_seen,
            "total_seen": self.total_seen,
            "share_bps": self.share_bps,
            "last_seen": self.last_seen,
            "basis": self.basis,
            "scope": self.scope,
            "reason": self.reason,
            "sentence": self.sentence,
            "alternatives": [
                {"value": o.value, "label": o.label, "times": o.times,
                 "last_seen": o.last_seen} for o in self.alternatives],
        }


def clean_hsn(value: Any) -> str:
    """An HSN/SAC as the lines compare it: trimmed, and nothing else.

    No digit-count normalisation and no case folding of a number: the CODE is
    what the supplier printed and what this client's lines carry, and two
    different codes are two different scopes.
    """
    return str(value or "").strip()


def _ranked(observations: Iterable[tuple[Any, str]]) -> list[Option]:
    """Tally (value, seen_at) pairs: most used first, then most recent, then the
    value itself so the order is total."""
    tally: dict[Any, dict] = {}
    for value, seen_at in observations:
        slot = tally.setdefault(value, {"times": 0, "last": ""})
        slot["times"] += 1
        if seen_at and seen_at > slot["last"]:
            slot["last"] = seen_at
    options = [Option(value=v, label=None, times=s["times"], last_seen=s["last"] or None)
               for v, s in tally.items()]
    options.sort(key=lambda o: (o.times, o.last_seen or "", str(o.value)), reverse=True)
    return options


def _seen(line: dict) -> str:
    return str(line.get("bill_date") or "")


def _account_suggestion(lines: list[dict], usable: dict[str, str], *,
                        basis: str, scope: str) -> tuple[bool, Optional[Suggestion], Optional[str]]:
    """(has_history, suggestion, gap) for the expense account over `lines`.

    `has_history` is whether ANY line in scope carries an account — it decides
    whether the supplier-level answer may stand in for this scope, which it may
    only when this scope has no evidence at all (a scope whose winner was
    unusable has evidence and is NOT silently replaced by a broader one).
    """
    coded = [ln for ln in lines if ln.get("expense_account_id")]
    if not coded:
        return False, None, None
    options = _ranked((str(ln["expense_account_id"]), _seen(ln)) for ln in coded)
    winner, rest = options[0], options[1:]
    if winner.value not in usable:
        return True, None, (
            "The account used most often on earlier bills is no longer an active "
            "account in this client's chart, so none is suggested.")
    total = sum(o.times for o in options)
    return True, Suggestion(
        value=winner.value, label=usable[winner.value],
        times_seen=winner.times, total_seen=total, last_seen=winner.last_seen,
        basis=basis, scope=scope,
        alternatives=tuple(Option(o.value, usable.get(o.value), o.times, o.last_seen)
                           for o in rest),
    ), None


def _itc_suggestion(lines: list[dict], *, basis: str, scope: str
                    ) -> tuple[bool, Optional[Suggestion]]:
    """(has_history, suggestion) for ITC eligibility over `lines`.

    A suggestion exists only when the winner is BLOCKED — see the module header.
    A NULL `itc_eligible` reads as ELIGIBLE, matching migration 240's default.
    """
    if not lines:
        return False, None
    options = _ranked((ln.get("itc_eligible") is not False, _seen(ln)) for ln in lines)
    winner, rest = options[0], options[1:]
    if winner.value is True:
        return True, None
    blocked = [ln for ln in lines if ln.get("itc_eligible") is False]
    blocked.sort(key=_seen, reverse=True)
    reason = next((str(ln["blocked_credit_reason"]).strip() for ln in blocked
                   if (ln.get("blocked_credit_reason") or "").strip()), None)
    total = sum(o.times for o in options)
    return True, Suggestion(
        value=False, label="ITC blocked (§17(5))",
        times_seen=winner.times, total_seen=total, last_seen=winner.last_seen,
        basis=basis, scope=scope,
        alternatives=tuple(Option(True, "ITC eligible", o.times, o.last_seen) for o in rest),
        reason=reason,
    )


def line_suggestions(lines: list[dict], usable_accounts: dict[str, str],
                     hsns: Iterable[str]) -> dict:
    """The expense-account and ITC suggestions for the supplier and for each
    requested HSN/SAC.

    `lines` are the supplier's earlier lines, each carrying its bill's
    `bill_date` as well as `hsn_sac`, `expense_account_id`, `itc_eligible` and
    `blocked_credit_reason`.

    Returns {"vendor": {...}, "by_hsn": {hsn: {...}}, "gaps": [...]}. For each
    HSN the specific scope answers when it has evidence and the supplier scope
    stands in only when it has NONE; each field is resolved on its own, so an HSN
    with an account on record and no ITC history takes the first from itself and
    the second from the supplier.
    """
    gaps: list[str] = []

    _, sup_account, sup_gap = _account_suggestion(
        lines, usable_accounts, basis=BASIS_SUPPLIER, scope="")
    _, sup_itc = _itc_suggestion(lines, basis=BASIS_SUPPLIER, scope="")
    if sup_gap:
        gaps.append(sup_gap)

    vendor = {"expense_account": sup_account.as_dict() if sup_account else None,
              "itc": sup_itc.as_dict() if sup_itc else None}

    by_hsn: dict[str, dict] = {}
    for hsn in sorted({clean_hsn(h) for h in hsns if clean_hsn(h)}):
        scoped = [ln for ln in lines if clean_hsn(ln.get("hsn_sac")) == hsn]
        has_acc, acc, acc_gap = _account_suggestion(
            scoped, usable_accounts, basis=BASIS_HSN, scope=hsn)
        has_itc, itc = _itc_suggestion(scoped, basis=BASIS_HSN, scope=hsn)
        if acc_gap:
            gaps.append(f"HSN/SAC {hsn}: {acc_gap}")
        account = acc if has_acc else sup_account
        itc_s = itc if has_itc else sup_itc
        by_hsn[hsn] = {"expense_account": account.as_dict() if account else None,
                       "itc": itc_s.as_dict() if itc_s else None}
    return {"vendor": vendor, "by_hsn": by_hsn, "gaps": gaps}


def tds_notice(bills: list[dict], supplier_record_section: Optional[str]) -> Optional[dict]:
    """The TDS section earlier bills used, WHEN it disagrees with the supplier
    record as it stands now; otherwise None.

    `bills` carry `tds_section` and `bill_date`. Only bills that carry a section
    are tallied: a NULL records that no section was resolved, which is what a
    supplier with TDS switched off produces and says nothing about a section.

    It is a NOTICE and not a suggestion because the bill's section cannot be set
    on the bill — it is resolved from the supplier record when the bill is
    created. Telling a CA the editor will do something it will not would be the
    worse failure, so the sentence says what the bill WILL do.
    """
    carrying = [b for b in bills if (b.get("tds_section") or "").strip()]
    if not carrying:
        return None
    options = _ranked(((b["tds_section"] or "").strip().upper(), _seen(b)) for b in carrying)
    winner, rest = options[0], options[1:]
    record = (supplier_record_section or "").strip().upper() or None
    if winner.value == record:
        return None
    total = sum(o.times for o in options)
    follows = (f"the supplier record says {record}" if record
               else "the supplier record carries no TDS section")
    return {
        "section": winner.value,
        "times_seen": winner.times,
        "total_seen": total,
        "last_seen": winner.last_seen,
        "supplier_record_section": record,
        "alternatives": [{"value": o.value, "times": o.times, "last_seen": o.last_seen}
                         for o in rest],
        "sentence": (
            f"Earlier bills from this supplier were assessed under section {winner.value} "
            f"({'once' if total == 1 else f'{winner.times} of {total} times'}), but {follows}. "
            f"This bill follows the supplier record — change the supplier if the earlier "
            f"treatment was right."),
    }


def build(lines: list[dict], bills: list[dict], usable_accounts: dict[str, str],
          hsns: Iterable[str], supplier_record_section: Optional[str]) -> dict:
    """The whole answer for one supplier: line suggestions and the TDS notice.

    `bills_considered` is stated because "nothing to suggest" over zero bills and
    over a hundred bills that disagreed are different situations to a CA.
    """
    out = line_suggestions(lines, usable_accounts, hsns)
    out["tds"] = tds_notice(bills, supplier_record_section)
    out["bills_considered"] = len(bills)
    return out
