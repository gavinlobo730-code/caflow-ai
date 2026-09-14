"""A Bill of Entry — what an import of goods costs, and what of it is credit
(PUR-18).

WHY THIS IS A DOCUMENT OF ITS OWN
    IGST on imported goods is not charged by the supplier. IGST Act s.5(1)'s
    proviso puts the levy on goods imported into India under Customs Tariff Act
    s.3(7), collected under the Customs Act at the point of Customs Act s.12 —
    so the tax is paid to CUSTOMS, against a Bill of Entry, and the overseas
    supplier's invoice carries none of it. Putting the duty on the supplier's
    purchase bill overstates Trade Payables by the whole of it; leaving it off
    loses the credit.

THE SPLIT THIS MODULE EXISTS FOR
    CGST Act s.2(62)(a) puts "the integrated goods and services tax charged on
    import of goods" in INPUT TAX, and Rule 36(1)(d) makes the bill of entry
    the document the credit rests on. Compensation cess on imports is input
    tax on the same reasoning (s.11(2) of the Compensation Act applies the CGST
    Act mutatis mutandis), and stays in its own ledger because the proviso to
    s.11(2) lets cess credit pay only cess.

    BASIC CUSTOMS DUTY AND THE SOCIAL WELFARE SURCHARGE ARE NOT INPUT TAX.
    They are recoverable from nobody, so AS-2 (and Ind AS 2) paragraph 6 puts
    them in the cost of purchase: "duties and taxes (other than those
    subsequently recoverable by the enterprise from the taxing authorities)".
    The same sentence that keeps blocked s.17(5) GST in the cost of goods
    (INV-05a) keeps these there.

WHAT THIS MODULE DOES NOT DECIDE
    It reads nothing and posts nothing. Whether the period is open, which
    accounts to use and what a journal looks like are the service's; whether
    the credit survives Rule 36(4) is `gstr3b_computer`'s.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: The GSTR-2B section a Bill of Entry belongs to. The portal file keeps the two
#: apart (`data.docdata.impg` and `data.docdata.impgsez`), so a reconciliation
#: that collapses them cannot match either.
SECTION_IMPG = "impg"
SECTION_IMPGSEZ = "impgsez"

#: GSTR-3B Table 4(A)(1). Named here so a caller cannot spell it.
TABLE_4A_ROW = "4(A)(1)"

#: What the credit rests on, cited wherever this is reported.
CREDIT_AUTHORITY = "CGST Act s.2(62)(a) with Rule 36(1)(d)"

#: Why basic customs duty is not credit.
COST_AUTHORITY = "AS-2 paragraph 6"


@dataclass(frozen=True)
class Assessment:
    """The figures off one Bill of Entry, in paise.

    A separate type from `PurchaseTransaction` on purpose. A Bill of Entry has
    no `is_reverse_charge` and must never acquire one: reverse-charge tax is
    SELF-assessed by the recipient and creates a Table 3.1(d) liability, while
    this tax was assessed and collected by customs and creates none. A flag on
    the purchase dataclass would sit next to `is_import_of_services`, and the
    natural next step — setting `is_reverse_charge` as well, because every
    other import does — would declare a liability the client does not owe.

    Nor can it carry CGST or SGST. IGST Act s.7(2) makes the supply of goods
    imported into India an INTER-STATE supply until they cross the customs
    frontier, so the only heads an assessment can charge are integrated tax and
    cess.
    """
    igst_paise: int = 0
    cess_paise: int = 0
    basic_customs_duty_paise: int = 0
    social_welfare_surcharge_paise: int = 0
    other_duty_paise: int = 0
    #: The part of the tax CGST Act s.17(5) blocks. Still paid, still cost —
    #: simply not credit.
    ineligible_igst_paise: int = 0
    ineligible_cess_paise: int = 0

    @property
    def creditable_igst_paise(self) -> int:
        return max(self.igst_paise - self.ineligible_igst_paise, 0)

    @property
    def creditable_cess_paise(self) -> int:
        return max(self.cess_paise - self.ineligible_cess_paise, 0)

    @property
    def non_creditable_duty_paise(self) -> int:
        """What AS-2 paragraph 6 puts in the cost of purchase.

        The blocked part of the TAX is in here too: s.17(5) credit is
        recoverable from nobody, which is the same test paragraph 6 applies.
        """
        return (self.basic_customs_duty_paise
                + self.social_welfare_surcharge_paise
                + self.other_duty_paise
                + (self.igst_paise - self.creditable_igst_paise)
                + (self.cess_paise - self.creditable_cess_paise))

    @property
    def total_paise(self) -> int:
        """Everything paid to customs — what leaves the bank."""
        return (self.igst_paise + self.cess_paise
                + self.basic_customs_duty_paise
                + self.social_welfare_surcharge_paise
                + self.other_duty_paise)

    @property
    def is_empty(self) -> bool:
        return self.total_paise == 0


def assessment_of(row: dict[str, Any]) -> Assessment:
    """Read an assessment off a `bills_of_entry` row."""
    def _i(key: str) -> int:
        try:
            return int(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return Assessment(
        igst_paise=_i("igst_paise"),
        cess_paise=_i("cess_paise"),
        basic_customs_duty_paise=_i("basic_customs_duty_paise"),
        social_welfare_surcharge_paise=_i("social_welfare_surcharge_paise"),
        other_duty_paise=_i("other_duty_paise"),
        ineligible_igst_paise=_i("ineligible_igst_paise"),
        ineligible_cess_paise=_i("ineligible_cess_paise"),
    )


def section_for(row: dict[str, Any]) -> str:
    """Which GSTR-2B section this document would appear in."""
    return SECTION_IMPGSEZ if row.get("is_sez") else SECTION_IMPG


# ── Can it be posted? ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Readiness:
    """Whether this document can be posted, and what stands in the way.

    Two lists, and they are not the same thing. `refusals` mean the document
    cannot be posted as it stands; `caveats` are true and worth saying and stop
    nothing. A screen that renders them the same way turns a note into a block.
    """
    ok: bool
    refusals: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def readiness(row: dict[str, Any], assessment: Optional[Assessment] = None) -> Readiness:
    """Can this Bill of Entry be posted?"""
    a = assessment if assessment is not None else assessment_of(row)
    refusals: list[str] = []
    caveats: list[str] = []

    if a.is_empty:
        refusals.append(
            "This Bill of Entry carries no duty or tax at all, so there is "
            "nothing to post. Record what customs assessed.")
    if not row.get("payment_account_id"):
        refusals.append(
            "Say which account the duty was paid from. The whole assessment is "
            "paid to customs before the goods are cleared (Customs Act s.47), "
            "so a Bill of Entry with no payment account is not yet a document "
            "the books can carry.")
    if a.non_creditable_duty_paise and not row.get("duty_expense_account_id"):
        refusals.append(
            "Say which account the basic customs duty and surcharge belong to. "
            f"They are not input tax — {COST_AUTHORITY} puts a duty recoverable "
            "from nobody in the cost of purchase — so they cannot be guessed "
            "into an expense head by name.")

    if not (row.get("port_code") or "").strip():
        caveats.append(
            "No port code is recorded, so this document cannot be matched "
            "against the Bill of Entry in GSTR-2B — the portal keys it on the "
            "port and the number together.")
    if a.non_creditable_duty_paise:
        caveats.append(
            f"₹{a.non_creditable_duty_paise / 100:,.2f} of duty is not input "
            f"tax and is posted to the expense account named above. {COST_AUTHORITY} "
            "would put it in the cost of the goods themselves; it is NOT "
            "apportioned across the stock lines, because the basis for that "
            "(by value, by quantity, by weight) is a judgement nothing here "
            "holds.")
    if a.ineligible_igst_paise or a.ineligible_cess_paise:
        caveats.append(
            "Part of the tax is marked blocked under CGST Act s.17(5), so it "
            "is treated as cost rather than credit and does not reach GSTR-3B "
            f"Table {TABLE_4A_ROW}.")

    return Readiness(ok=not refusals, refusals=refusals, caveats=caveats)


# ── Deliberately not modelled, and named ─────────────────────────────────────

#: What this document cannot say, reported rather than silently assumed.
NOT_MODELLED = (
    "Deferred payment of duty (Customs Act s.47(2) proviso with Notification "
    "134/2016-Customs) is not modelled: the duty is recorded as paid from an "
    "account, not as owed to customs. An accredited importer paying on the "
    "prescribed date records the payment when it is made.",
    "A refund of duty under Customs Act s.27 is its own event, not a negative "
    "Bill of Entry, and is not modelled here.",
    "No line detail is held, so the duty is not apportioned into the cost of "
    "individual stock items (INV-05).",
)
