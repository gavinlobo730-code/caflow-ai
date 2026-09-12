"""What the client may actually CLAIM off Form 26AS — IT-31.

THE GAP. The 26AS reconciliation produced matched / mismatch / missing counts
and an `unsupported_credit_paise` figure, and nothing wrote a total back:
`ITRComputeRequest.tds_deducted_paise` is a plain input and the computation
screen collected it from a free-text box. A CA who had just run the
reconciliation, and therefore knew exactly which credits were supported, then
retyped the total into a different tab by hand with no check that the two
agreed.

WHY THE FIGURE COMES OFF 26AS AND NOT OFF THE BOOKS. Rule 37BA(1) gives credit
for tax deducted "on the basis of information relating to deduction of tax
furnished by the deductor to the income-tax authority" — the deductor's own
statement, which is what 26AS reproduces. The books are the CHECK on that, not
the source: a credit the books claim and 26AS does not report is precisely the
one Rule 37BA(1) does not allow, which is what `unsupported_credit_paise`
measures.

That also makes this right for the case the reconciliation's books side cannot
see at all. `_load_book_credits` reads `receipts` — tax a CUSTOMER withheld —
so a salaried client's §192 credit has no books counterpart and the
reconciliation reports it as "missing in books" for ever. The claimable figure
does not care: it is read off 26AS, where the credit is.

FOUR FIGURES, NOT ONE, BECAUSE THE RETURN HAS FOUR LINES.

  • TDS is Schedule TDS-1 / TDS-2.
  • TCS is Schedule TCS and a different charging provision (§206C(4)). Summing
    it into the TDS figure would put it on the wrong schedule, and the two
    reconcile against different statements at the department's end.
  • Tax the client paid ITSELF — 26AS Part C, advance tax and
    self-assessment — is neither. It reduces the same liability and belongs on
    its own line; `ITRComputeRequest` already has `advance_tax_paid_paise` for
    it, separate from `tds_deducted_paise`.
  • A refund already received (Part D) is not a credit at all and is excluded.

WHAT IS NOT FINAL IS NOT CLAIMABLE YET. TRACES booking status 'F' means the
deductor's statement has been matched to a challan actually paid; 'U'
(unmatched), 'P' (provisional) and 'O' (overbooked) mean the money has not
been traced to the government. A blank status is NOT read as final either —
26AS text pasted without that column is missing the information, and reading
absence as "settled" is the optimistic direction, which is the wrong way for a
tax credit to fail. Those rows are reported as `provisional_paise` with a
sentence, never folded into the claim: claiming an unmatched credit is what
produces a §143(1) intimation with a demand months later.

NOTHING HERE FILES ANYTHING. This is a working paper the CA reads before the
return is filed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

# One rupee formatter, Indian-grouped — `f"{n:,}"` gives 500,000, which no
# Indian document uses, and the browser formats the same figure with
# Intl.NumberFormat("en-IN").
from domain.reporting.amount_words import indian_rupees

# The record types domain/income_tax/form26as_service assigns per 26AS part.
# Kept as literals rather than imported so a change to that mapping shows up
# here as a failing test rather than as a silently different claim.
TDS_RECORD_TYPES = frozenset({"tds_salary", "tds_other"})
TCS_RECORD_TYPES = frozenset({"tcs_collected"})
SELF_PAID_RECORD_TYPES = frozenset({"tax_paid_by_client"})
# Part D. A refund already received reduces nothing on the next return.
EXCLUDED_RECORD_TYPES = frozenset({"refund_received"})

FINAL_BOOKING_STATUS = "F"

RULE_37BA = (
    "Rule 37BA(1) gives credit on the basis of the deductor's own statement to "
    "the department, which is what Form 26AS reproduces — so the claim is the "
    "26AS figure and the books are the check on it, not the source."
)


def _is_final(booking_status: Optional[str]) -> bool:
    return (booking_status or "").strip().upper() == FINAL_BOOKING_STATUS


@dataclass(frozen=True)
class ClaimableLine:
    """One deductor's contribution to the claim, for Schedule TDS-2."""
    deductor_name: str
    deductor_tan: Optional[str]
    kind: str                      # "tds" | "tcs"
    claimable_paise: int
    provisional_paise: int
    entry_count: int


@dataclass(frozen=True)
class ClaimableCredit:
    tds_claimable_paise: int = 0
    tcs_claimable_paise: int = 0
    provisional_paise: int = 0
    tax_paid_by_client_paise: int = 0
    refund_already_received_paise: int = 0
    by_deductor: list[ClaimableLine] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tds_claimable_paise": self.tds_claimable_paise,
            "tcs_claimable_paise": self.tcs_claimable_paise,
            "provisional_paise": self.provisional_paise,
            "tax_paid_by_client_paise": self.tax_paid_by_client_paise,
            "refund_already_received_paise": self.refund_already_received_paise,
            "by_deductor": [
                {
                    "deductor_name": d.deductor_name,
                    "deductor_tan": d.deductor_tan,
                    "kind": d.kind,
                    "claimable_paise": d.claimable_paise,
                    "provisional_paise": d.provisional_paise,
                    "entry_count": d.entry_count,
                }
                for d in self.by_deductor
            ],
            "caveats": self.caveats,
            "basis": RULE_37BA,
        }


def claimable_from_records(records: Iterable[Mapping]) -> ClaimableCredit:
    """The claim, from the parsed 26AS rows of ONE upload.

    Takes the raw `form_26as_records` rows rather than the matcher's entries,
    because the matcher is handed only the TDS-credit subset — and three of the
    four figures here come from the parts it never sees.
    """
    tds = tcs = provisional = self_paid = refunds = 0
    # (name, tan, kind) → [claimable, provisional, count]
    bucket: dict[tuple[str, Optional[str], str], list[int]] = {}
    saw_blank_status = False

    for r in records:
        rtype = (r.get("record_type") or "").strip()
        amount = int(r.get("tds_deposited_paise") or 0)

        if rtype in EXCLUDED_RECORD_TYPES:
            refunds += amount
            continue
        if rtype in SELF_PAID_RECORD_TYPES:
            # No booking status to test: the client paid this themselves and
            # the challan IS the evidence.
            self_paid += amount
            continue

        kind = ("tds" if rtype in TDS_RECORD_TYPES
                else "tcs" if rtype in TCS_RECORD_TYPES else None)
        if kind is None:
            # A record type nobody has classified. Not claimed and not silently
            # dropped — it is named in the caveats below.
            continue

        status = r.get("booking_status")
        if not (status or "").strip():
            saw_blank_status = True
        final = _is_final(status)
        key = ((r.get("deductor_name") or "").strip() or "(deductor not named)",
               (r.get("deductor_tan") or None), kind)
        slot = bucket.setdefault(key, [0, 0, 0])
        slot[2] += 1
        if final:
            slot[0] += amount
            if kind == "tds":
                tds += amount
            else:
                tcs += amount
        else:
            slot[1] += amount
            provisional += amount

    lines = [
        ClaimableLine(deductor_name=name, deductor_tan=tan, kind=kind,
                      claimable_paise=v[0], provisional_paise=v[1], entry_count=v[2])
        for (name, tan, kind), v in bucket.items()
    ]
    lines.sort(key=lambda d: (-d.claimable_paise, d.deductor_name))

    caveats: list[str] = []
    if provisional:
        caveats.append(
            f"₹{indian_rupees(provisional)} of credit is not booked final at TRACES "
            f"(status U, P, O or blank) and is excluded from the claim. Credit "
            f"under Rule 37BA(1) follows the deductor's statement once it is "
            f"matched to a challan actually paid; claiming it before then is "
            f"what produces a §143(1) intimation with a demand."
        )
    if saw_blank_status:
        caveats.append(
            "Some rows carry no TRACES booking status. A blank is treated as "
            "NOT final rather than assumed settled — 26AS pasted without that "
            "column is missing the information, and the optimistic reading is "
            "the wrong way for a tax credit to fail."
        )
    if tcs:
        caveats.append(
            f"₹{indian_rupees(tcs)} is TCS collected under §206C and belongs in Schedule "
            f"TCS, not in the TDS figure. It is reported separately for that "
            f"reason."
        )
    if self_paid:
        caveats.append(
            f"₹{indian_rupees(self_paid)} in Part C is tax the client paid itself — "
            f"advance tax or self-assessment. It reduces the same liability "
            f"but is its own line on the return "
            f"(`advance_tax_paid_paise`), not part of the TDS claim."
        )
    unclassified = sum(
        int(r.get("tds_deposited_paise") or 0) for r in records
        if (r.get("record_type") or "").strip() not in (
            TDS_RECORD_TYPES | TCS_RECORD_TYPES | SELF_PAID_RECORD_TYPES
            | EXCLUDED_RECORD_TYPES)
    )
    if unclassified:
        caveats.append(
            f"₹{indian_rupees(unclassified)} sits in rows whose 26AS part the parser could "
            f"not classify. Nothing is claimed for them; read the statement and "
            f"add them by hand if they are a credit."
        )

    return ClaimableCredit(
        tds_claimable_paise=tds,
        tcs_claimable_paise=tcs,
        provisional_paise=provisional,
        tax_paid_by_client_paise=self_paid,
        refund_already_received_paise=refunds,
        by_deductor=lines,
        caveats=caveats,
    )
