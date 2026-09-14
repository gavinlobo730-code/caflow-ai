"""CGST Rule 37A — the supplier did not file their GSTR-3B, so the credit goes back.

WHY THIS IS NOT RULE 37 (GST-28, second half)
    Rule 37 is about what the RECIPIENT did: the consideration went unpaid for
    180 days, so the credit is reversed. `domain/gst/itc_reversal.py` is that
    rule and `services/itc_reversal_service.py` reports it.

    Rule 37A is about what the SUPPLIER did. Inserted by Notification
    26/2022-Central Tax (26-12-2022): where a supplier has furnished the
    details of an invoice in GSTR-1 but has NOT furnished the return in FORM
    GSTR-3B for that period by the **30th of September** following the end of
    the financial year in which the credit was availed, the recipient shall
    reverse that credit on or before the **30th of November** following the
    end of that financial year — and where it is not reversed, it is payable
    with interest under s.50.

    The two rules share a reason code in `itc_reversal_register` and a box on
    GSTR-3B (Table 4(B)(2), reclaimable), and they are otherwise unrelated:
    one is measured from the bill's own date, the other from a financial year;
    one the client can fix by paying, the other only the supplier can fix.

THE ONE FACT THIS PRODUCT DOES NOT HOLD, AND WILL NOT GUESS
    Whether the supplier furnished their GSTR-3B. GSTR-2B is generated FROM
    filed GSTR-1s, so a document appearing in it proves the GSTR-1 and says
    nothing about the 3B — `domain/gst/gstr2b.py` parses the whole envelope
    and there is no such field in it. GSTR-2A's `cfs` carries a counter-party
    filing status; this product reconciles against 2B, which is what
    s.16(2)(aa) makes decisive.

    So every answer NAMES the gap and says where to look, and no credit is
    reported as reversible on a supplier nobody has checked. Guessing "filed"
    would leave a reversal undone with s.50 interest running; guessing "not
    filed" would reverse credit the client is entitled to.

WHAT IS NARROWED, AND HOW
    The population is NOT every bill. Rule 37A reaches a supply whose invoice
    the supplier DID declare in GSTR-1 — that is its opening words — so the
    bills at risk are exactly the ones the GSTR-2B reconciliation MATCHED. A
    bill missing from 2B is a different problem entirely (s.16(2)(aa): the
    credit is not available at all), and reporting it here would tell the CA
    to chase the wrong thing.

⚠️ GRADING. The rule's text, both dates and the re-availment limb are
`[S]`-graded — written from knowledge, because this environment's proxy
refuses every `.gov.in`. Each is pinned by a test so a later change is
deliberate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

#: Notification 26/2022-CT. The supplier's own deadline: file the GSTR-3B for
#: the period by 30 September following the end of the FY in which the
#: recipient availed the credit.
SUPPLIER_DEADLINE_MONTH_DAY = (9, 30)
#: And the recipient's: reverse by 30 November following the end of that FY.
RECIPIENT_DEADLINE_MONTH_DAY = (11, 30)

RULE = "CGST Rule 37A (Notification 26/2022-Central Tax, 26-12-2022)"

#: Said once, here, so no screen paraphrases the one thing the product cannot
#: answer.
SUPPLIER_FILING_NOT_HELD = (
    "Whether the supplier furnished their GSTR-3B for the period is not "
    "recorded anywhere in these books, and it cannot be derived: GSTR-2B is "
    "generated FROM filed GSTR-1s, so a document appearing in it proves the "
    "GSTR-1 and says nothing about the 3B. Check each supplier on the portal "
    "(Search Taxpayer, then Returns filed) before reversing — guessing 'filed' "
    "leaves a reversal undone with s.50 interest running, and guessing 'not "
    "filed' reverses credit the client is entitled to."
)

#: The other half of the rule, which is why a reversal here is RECLAIMABLE and
#: sits in GSTR-3B Table 4(B)(2) rather than 4(B)(1).
RE_AVAILMENT = (
    "Where the supplier subsequently furnishes the GSTR-3B for that period, "
    "the credit may be re-availed. That is why a Rule 37A reversal is "
    "RECLAIMABLE — GSTR-3B Table 4(B)(2), released into 4(D)(1) when it comes "
    "back — and not an absolute reversal under 4(B)(1)."
)

#: What is deliberately NOT computed, and why.
NOT_COMPUTED = (
    "The interest under s.50 is not computed here. Rule 37A makes the "
    "unreversed credit 'payable ... along with interest payable under section "
    "50', and s.50(1)'s 18% is settled — but the DATE it runs from is not "
    "stated in the rule, and `domain/gst/late_filing.py` already records that "
    "the same silence in Rule 37 is why that report shows two readings rather "
    "than one. A single figure here would be a third answer to a question the "
    "Act leaves open."
)

#: A reversal under this rule is NOT posted from here, for the reason
#: `services/itc_register_service.py` records for Rule 37: the CA raises the
#: journal and registers it with ground `rule_37a`.
POSTS_NOTHING = (
    "Nothing is posted. The CA raises the reversal journal and registers it "
    "with ground 'rule_37a', which the ITC reversal register has accepted "
    "since migration 362."
)


def _fy_end_year(financial_year: str) -> int:
    """'2025-26' -> 2026. The year the FY ENDS in, which both dates hang off."""
    parts = str(financial_year or "").split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or not parts[0].isdigit():
        raise ValueError(
            f"Financial year {financial_year!r} is not in the '2025-26' form.")
    return int(parts[0]) + 1


def supplier_deadline(financial_year: str) -> date:
    """30 September following the end of the FY the credit was availed in."""
    return date(_fy_end_year(financial_year), *SUPPLIER_DEADLINE_MONTH_DAY)


def recipient_deadline(financial_year: str) -> date:
    """30 November following the end of that same FY.

    NOT "sixty days after the supplier's date" and not "the FY's own 30
    November". Both are easy misreadings and both are wrong by a year or by
    two months: the FY in which the credit was AVAILED ends on 31 March, so
    for FY 2025-26 the supplier's date is 30 September 2026 and the
    recipient's is 30 November 2026.
    """
    return date(_fy_end_year(financial_year), *RECIPIENT_DEADLINE_MONTH_DAY)


@dataclass(frozen=True)
class SupplierExposure:
    """One supplier's credit at risk under this rule, for one financial year."""
    vendor_id: Optional[str]
    vendor_name: str
    vendor_gstin: Optional[str]
    bill_count: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def total_paise(self) -> int:
        return (self.igst_paise + self.cgst_paise + self.sgst_paise
                + self.cess_paise)

    def as_dict(self) -> dict:
        return {
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "vendor_gstin": self.vendor_gstin,
            "bill_count": self.bill_count,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "total_paise": self.total_paise,
            # NEVER a verdict. Whether this supplier filed is the one fact
            # nobody here holds.
            "supplier_filed_gstr3b": None,
        }


@dataclass
class Rule37AReport:
    financial_year: str
    as_of: str
    rule: str = RULE
    supplier_deadline: str = ""
    recipient_deadline: str = ""
    #: True once the supplier's own date has passed — which is when the
    #: recipient has something to check rather than something to do.
    supplier_deadline_passed: bool = False
    #: True once the recipient's date has passed. An unreversed credit is then
    #: payable with s.50 interest.
    recipient_deadline_passed: bool = False
    suppliers: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "as_of": self.as_of,
            "rule": self.rule,
            "supplier_deadline": self.supplier_deadline,
            "recipient_deadline": self.recipient_deadline,
            "supplier_deadline_passed": self.supplier_deadline_passed,
            "recipient_deadline_passed": self.recipient_deadline_passed,
            "suppliers": [s.as_dict() if isinstance(s, SupplierExposure) else s
                          for s in self.suppliers],
            "totals": dict(self.totals),
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            # CA REVIEW REQUIRED — this reports. It posts nothing and files
            # nothing.
            "ca_review_required": True,
        }


def build(*, financial_year: str, as_of: date, matched_bills: list,
          vendors: Optional[dict] = None) -> Rule37AReport:
    """The credit at risk under Rule 37A, by supplier, for one financial year.

    `matched_bills` are the bills the GSTR-2B reconciliation MATCHED — the
    population the rule's own opening words describe, because it reaches a
    supply whose invoice the supplier DID declare in GSTR-1. A bill missing
    from 2B is a s.16(2)(aa) problem and belongs in the reconciliation, not
    here.
    """
    out = Rule37AReport(financial_year=financial_year, as_of=as_of.isoformat())
    sup = supplier_deadline(financial_year)
    rec = recipient_deadline(financial_year)
    out.supplier_deadline = sup.isoformat()
    out.recipient_deadline = rec.isoformat()
    out.supplier_deadline_passed = as_of > sup
    out.recipient_deadline_passed = as_of > rec
    out.caveats = [SUPPLIER_FILING_NOT_HELD, RE_AVAILMENT, NOT_COMPUTED,
                   POSTS_NOTHING]

    by_vendor: dict = {}
    for b in matched_bills or []:
        vid = b.get("vendor_id")
        key = str(vid) if vid else ""
        acc = by_vendor.setdefault(key, {
            "vendor_id": vid, "bill_count": 0,
            "igst": 0, "cgst": 0, "sgst": 0, "cess": 0})
        acc["bill_count"] += 1
        acc["igst"] += int(b.get("igst_paise") or 0)
        acc["cgst"] += int(b.get("cgst_paise") or 0)
        acc["sgst"] += int(b.get("sgst_paise") or 0)
        acc["cess"] += int(b.get("cess_paise") or 0)

    names = vendors or {}
    rows: list = []
    for key, acc in by_vendor.items():
        v = names.get(key) or {}
        rows.append(SupplierExposure(
            vendor_id=acc["vendor_id"],
            vendor_name=str(v.get("name") or acc["vendor_id"] or "—"),
            vendor_gstin=v.get("gstin"),
            bill_count=acc["bill_count"],
            igst_paise=acc["igst"], cgst_paise=acc["cgst"],
            sgst_paise=acc["sgst"], cess_paise=acc["cess"]))
        if not v.get("gstin"):
            out.gaps.append(
                f"{rows[-1].vendor_name}: no GSTIN recorded, so the supplier's "
                f"return filing cannot be looked up on the portal.")

    # Largest exposure first: that is the supplier worth checking without
    # scrolling.
    rows.sort(key=lambda r: (-r.total_paise, r.vendor_name))
    out.suppliers = rows
    out.totals = {
        "igst_paise": sum(r.igst_paise for r in rows),
        "cgst_paise": sum(r.cgst_paise for r in rows),
        "sgst_paise": sum(r.sgst_paise for r in rows),
        "cess_paise": sum(r.cess_paise for r in rows),
        "total_paise": sum(r.total_paise for r in rows),
        "supplier_count": len(rows),
        "bill_count": sum(r.bill_count for r in rows),
    }
    if not rows:
        out.gaps.append(
            "No purchase bill for this year has been matched to a GSTR-2B, so "
            "there is nothing Rule 37A reaches. Run the GSTR-2B reconciliation "
            "first — the rule applies to a supply whose invoice the supplier "
            "DID declare in GSTR-1.")
    return out
