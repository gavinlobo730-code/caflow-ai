"""GSTR-3B computation engine.

CGST Act Section 39 — furnishing of returns.
CGST Rule 36(4) — ITC restricted to eligible credit reflected in GSTR-2A/2B.
Notification 40/2021-Central Tax (w.e.f. 1 Jan 2022) removed the prior 105%
provisional buffer; ITC is now capped strictly at 100% (Section 16(2)(aa)).
CGST Act Section 49 — payment of tax, interest, penalty and fee.

All amounts are integer paise. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# GSTR-3B is declared and paid in WHOLE rupees (CGST Act §170) — not the 2-decimal
# rupees GSTR-1 uses. Conversion lives in the shared GST money module.
from domain.gst.money import paise_to_rupees_whole


@dataclass(frozen=True)
class SalesTransaction:
    """Posted sales invoice or credit/debit note fields for GSTR-3B."""
    transaction_type: str
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    supply_type: str       # taxable | zero_rated | nil_rated | exempt | non_gst
    is_reverse_charge: bool


@dataclass(frozen=True)
class PurchaseTransaction:
    """Posted purchase invoice fields for ITC computation."""
    taxable_amount_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    is_reverse_charge: bool
    # CGST Act §17(5): the portion of cgst/sgst/igst/cess_paise above that is
    # BLOCKED input tax credit (CA-flagged at the purchase-bill-line level —
    # see routers/purchase_bills.py._compute_bill_lines_and_totals). Always
    # <= the corresponding *_paise field. Defaulted so existing call sites
    # (no §17(5) lines) are unaffected.
    ineligible_igst_paise: int = 0
    ineligible_cgst_paise: int = 0
    ineligible_sgst_paise: int = 0
    ineligible_cess_paise: int = 0


@dataclass(frozen=True)
class GSTR2ARecord:
    """Supplier-filed invoice from GSTR-2A."""
    cgst_paise: int
    sgst_paise: int
    igst_paise: int


@dataclass
class ITCReversal:
    """Credit already taken that is being given back in this period.

    `reclaimable` is the whole classification, and it is the one GSTR-3B asks
    for (Notification 14/2022, Circular 170/02/2022-GST, live on the portal for
    periods from August 2022):

      False -> Table 4(B)(1), permanent. Rules 38, 42 and 43, CGST Act §17(5),
               and any other reversal that will never come back — a purchase
               cancelled after its credit was taken, stock written off.
      True  -> Table 4(B)(2), "Others". Reversals that MAY be reclaimed later:
               Rule 37 / 37A (supplier unpaid past 180 days), §16(2)(b) and
               §16(2)(c). When the condition is met the credit is taken again
               through Table 4(A)(5), and 4(D)(1) reports the reclaim.

    Getting the side wrong is not a rounding matter: 4(B)(2) tells the portal a
    credit is coming back, and the electronic credit reversal and re-claimed
    statement reconciles against it.
    """
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    reclaimable: bool = False
    reason: str = ""


@dataclass
class GSTR3BResult:
    """Computed GSTR-3B values — all amounts in paise."""

    # Table 3.1: Outward supplies (CGST Act Section 37)
    outward_taxable_value: int = 0   # taxable VALUE of taxable outward supplies (not the tax)
    outward_taxable_igst: int = 0
    outward_taxable_cgst: int = 0
    outward_taxable_sgst: int = 0
    outward_taxable_cess: int = 0
    outward_zero_rated: int = 0      # zero-rated (export) taxable value
    outward_nil_exempt: int = 0      # nil-rated + exempt taxable value

    # Table 3.2: Inward supplies on reverse charge (CGST Act Section 9(3), 9(4))
    rcm_igst: int = 0
    rcm_cgst: int = 0
    rcm_sgst: int = 0

    # Table 4: ITC available
    itc_igst: int = 0
    itc_cgst: int = 0
    itc_sgst: int = 0
    itc_cess: int = 0

    # CGST Act §17(5) blocked credit. Excluded from itc_igst/cgst/sgst/cess
    # above and from the Rule 36(4) cap (ineligibility is a hard bar, applied
    # before matching against 2A/2B).
    #
    # WHERE IT IS REPORTED CHANGED. Until August 2022 this was Table 4(D)(1).
    # Notification 14/2022 moved it into Table 4(B)(1) — it is a REVERSAL, and
    # 4(A) now carries all ITC including it, so that 4(A) ties to the
    # auto-populated GSTR-2B and 4(C) = 4(A) - 4(B) nets it back out. Reporting
    # it in 4(D) understates 4(A) against the portal's own figure, which is
    # precisely the mismatch that draws a notice.
    itc_ineligible_igst: int = 0
    itc_ineligible_cgst: int = 0
    itc_ineligible_sgst: int = 0
    itc_ineligible_cess: int = 0

    # Table 4(B)(1) — permanent reversals OTHER than §17(5) (which is added to
    # this line in the payload): Rules 38/42/43, a cancelled purchase, stock
    # written off.
    itc_rev_perm_igst: int = 0
    itc_rev_perm_cgst: int = 0
    itc_rev_perm_sgst: int = 0
    itc_rev_perm_cess: int = 0

    # Table 4(B)(2) — reclaimable reversals: Rule 37/37A, §16(2)(b)/(c).
    itc_rev_temp_igst: int = 0
    itc_rev_temp_cgst: int = 0
    itc_rev_temp_sgst: int = 0
    itc_rev_temp_cess: int = 0

    # ITC working — raw figures before Rule 36(4) cap
    itc_book_igst: int = 0
    itc_book_cgst: int = 0
    itc_book_sgst: int = 0
    itc_2a_igst: int = 0
    itc_2a_cgst: int = 0
    itc_2a_sgst: int = 0
    itc_capped_by_2a: bool = False   # True if Rule 36(4) cap was applied

    # ── Table 4 derived views ────────────────────────────────────────────
    # Kept as properties rather than stored fields so they can never drift from
    # the parts they are made of.

    @property
    def itc_avail_igst(self) -> int:
        """4(A): ALL credit availed, blocked credit included."""
        return self.itc_igst + self.itc_ineligible_igst

    @property
    def itc_avail_cgst(self) -> int:
        return self.itc_cgst + self.itc_ineligible_cgst

    @property
    def itc_avail_sgst(self) -> int:
        return self.itc_sgst + self.itc_ineligible_sgst

    @property
    def itc_avail_cess(self) -> int:
        return self.itc_cess + self.itc_ineligible_cess

    @property
    def itc_rev_total_igst(self) -> int:
        """4(B) = 4(B)(1) + 4(B)(2), §17(5) included in the permanent half."""
        return self.itc_ineligible_igst + self.itc_rev_perm_igst + self.itc_rev_temp_igst

    @property
    def itc_rev_total_cgst(self) -> int:
        return self.itc_ineligible_cgst + self.itc_rev_perm_cgst + self.itc_rev_temp_cgst

    @property
    def itc_rev_total_sgst(self) -> int:
        return self.itc_ineligible_sgst + self.itc_rev_perm_sgst + self.itc_rev_temp_sgst

    @property
    def itc_rev_total_cess(self) -> int:
        return self.itc_ineligible_cess + self.itc_rev_perm_cess + self.itc_rev_temp_cess

    @property
    def itc_net_igst(self) -> int:
        """4(C) = 4(A) - 4(B). Never negative: a reversal cannot exceed the
        credit there was to reverse, and if the data says otherwise the return
        must not carry a negative into the electronic credit ledger."""
        return max(self.itc_avail_igst - self.itc_rev_total_igst, 0)

    @property
    def itc_net_cgst(self) -> int:
        return max(self.itc_avail_cgst - self.itc_rev_total_cgst, 0)

    @property
    def itc_net_sgst(self) -> int:
        return max(self.itc_avail_sgst - self.itc_rev_total_sgst, 0)

    @property
    def itc_net_cess(self) -> int:
        return max(self.itc_avail_cess - self.itc_rev_total_cess, 0)

    # Table 6: Net tax payable
    net_igst: int = 0
    net_cgst: int = 0
    net_sgst: int = 0
    net_cess: int = 0

    def as_gstn_payload(self, gstin: str, period: str) -> dict:
        """Return GSTN-compatible GSTR-3B JSON.

        Format follows GSTN API specification v1.3. Every monetary field is in
        WHOLE RUPEES — internal computation is integer paise, but GSTR-3B is
        declared and paid in whole rupees (CGST Act §170, round half up). Finding
        F16: the earlier version emitted raw paise, making every amount 100x too
        large.
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        """
        r = paise_to_rupees_whole
        return {
            "gstin": gstin,
            "ret_period": period,
            "inward_sup": {
                "isup_details": [
                    {
                        "ty": "RCM",
                        "inter": r(self.rcm_igst),
                        "intra_cgst": r(self.rcm_cgst),
                        "intra_sgst": r(self.rcm_sgst),
                    }
                ]
            },
            "sup_details": {
                "osup_det": {
                    "txval": r(self.outward_taxable_value),
                    "iamt": r(self.outward_taxable_igst),
                    "camt": r(self.outward_taxable_cgst),
                    "samt": r(self.outward_taxable_sgst),
                    "csamt": r(self.outward_taxable_cess),
                },
                "osup_zero": {
                    "txval": r(self.outward_zero_rated),
                    "iamt": 0, "camt": 0, "samt": 0, "csamt": 0,
                },
                "osup_nil_exmp": {
                    "txval": r(self.outward_nil_exempt),
                },
                "isup_rev": {
                    "txval": 0,
                    "iamt": r(self.rcm_igst),
                    "camt": r(self.rcm_cgst),
                    "samt": r(self.rcm_sgst),
                    "csamt": 0,
                },
                "osup_nongst": {"txval": 0},
            },
            # ── Table 4, in the shape the portal has used since 01-09-2022 ──
            # Notification 14/2022-Central Tax and Circular 170/02/2022-GST:
            #
            #   4(A)    ALL ITC availed, including credit that is then reversed.
            #           Auto-populated from GSTR-2B on the portal, so a figure
            #           that omits blocked credit does not tie to 2B.
            #   4(B)(1) permanent reversals — Rules 38/42/43 and §17(5).
            #   4(B)(2) reclaimable reversals — Rule 37/37A, §16(2)(b)/(c).
            #   4(C)    net ITC available = 4(A) - 4(B).
            #   4(D)(1) reclaims of amounts reversed earlier under 4(B)(2).
            #   4(D)(2) ineligible under §16(4) and the place-of-supply rules.
            #
            # This used to file 4(A) NET of §17(5), an empty 4(B), and §17(5)
            # under 4(D) — the pre-August-2022 layout. The tax payable came out
            # the same, but the face of the return was wrong in two ways: 4(A)
            # understated against 2B, and 4(B) said no credit had been reversed
            # in a period when the books had reversed some.
            "itc_elg": {
                "itc_avl": [
                    {
                        "ty": "ISRC",       # inputs, inputs services, capital goods combined
                        "iamt": r(self.itc_avail_igst),
                        "camt": r(self.itc_avail_cgst),
                        "samt": r(self.itc_avail_sgst),
                        "csamt": r(self.itc_avail_cess),
                    }
                ],
                "itc_rev": [
                    # "RUL" is the GSTN type code for a reversal under the rules
                    # — 4(B)(1). §17(5) rides here with them.
                    {
                        "ty": "RUL",
                        "iamt": r(self.itc_ineligible_igst + self.itc_rev_perm_igst),
                        "camt": r(self.itc_ineligible_cgst + self.itc_rev_perm_cgst),
                        "samt": r(self.itc_ineligible_sgst + self.itc_rev_perm_sgst),
                        "csamt": r(self.itc_ineligible_cess + self.itc_rev_perm_cess),
                    },
                    # "OTH" — 4(B)(2), the reclaimable ones.
                    {
                        "ty": "OTH",
                        "iamt": r(self.itc_rev_temp_igst),
                        "camt": r(self.itc_rev_temp_cgst),
                        "samt": r(self.itc_rev_temp_sgst),
                        "csamt": r(self.itc_rev_temp_cess),
                    },
                ],
                "itc_net": {
                    "iamt": r(self.itc_net_igst),
                    "camt": r(self.itc_net_cgst),
                    "samt": r(self.itc_net_sgst),
                    "csamt": r(self.itc_net_cess),
                },
                # Table 4(D)(2) — ineligible under §16(4) and the PoS rules.
                # Zero because neither is tracked yet; §17(5) is NOT reported
                # here any more (it moved to 4(B)(1) above), and the circular is
                # explicit that once §17(5) is shown in 4(B) it is not to be
                # repeated in 4(D).
                "itc_inelg": [
                    {"ty": "OTH", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
                ],
            },
            "intr_ltfee": {
                "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
                "fee_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            },
        }


# CGST Rule 36(4): eligible ITC capped at 100% of GSTR-2A/2B credit.
# Notification 40/2021-Central Tax (w.e.f. 1 Jan 2022) withdrew the prior 105%
# provisional buffer — ITC is now strictly matched, no additional grace.
_RULE_36_4_NUMERATOR = 100
_RULE_36_4_DENOMINATOR = 100


def _apply_rule_36_4_cap(book: int, gstr2a: int) -> tuple[int, bool]:
    """Return (capped_itc, was_capped) using integer paise arithmetic.

    CGST Rule 36(4) (as amended w.e.f. 1 Jan 2022): ITC cannot exceed 100% of
    eligible GSTR-2A/2B credit — no provisional buffer. If GSTR-2A is zero
    (no records uploaded), book ITC is used as-is.
    """
    if gstr2a == 0:
        # No GSTR-2A data — use book ITC; warn CA to upload GSTR-2A
        return book, False
    cap = (gstr2a * _RULE_36_4_NUMERATOR) // _RULE_36_4_DENOMINATOR
    if book > cap:
        return cap, True
    return book, False


def compute_gstr3b(
    sales: Sequence[SalesTransaction],
    purchases: Sequence[PurchaseTransaction],
    gstr2a_records: Sequence[GSTR2ARecord],
    reversals: Sequence[ITCReversal] = (),
) -> GSTR3BResult:
    """Compute GSTR-3B figures from transaction data.

    Args:
        sales: Posted sales invoices and credit/debit notes for the period.
        purchases: Posted purchase invoices for the period.
        gstr2a_records: Supplier-filed records from GSTR-2A for the period.

    Returns:
        GSTR3BResult with all table values computed in paise.
    """
    result = GSTR3BResult()

    # ── Table 3.1: Outward supplies ──────────────────────────────────────────
    # GSTR-3B instructions: report NET values — credit notes reduce output tax.
    # txval is the taxable VALUE (H7 fix — previously the payload summed tax heads).
    for s in sales:
        sign = -1 if s.transaction_type == "credit_note" else 1
        if s.supply_type in ("nil_rated", "exempt"):
            result.outward_nil_exempt += sign * s.taxable_amount_paise
        elif s.supply_type == "zero_rated":
            result.outward_zero_rated += sign * s.taxable_amount_paise
        elif s.supply_type == "taxable":
            if not s.is_reverse_charge:
                result.outward_taxable_value += sign * s.taxable_amount_paise
                result.outward_taxable_igst += sign * s.igst_paise
                result.outward_taxable_cgst += sign * s.cgst_paise
                result.outward_taxable_sgst += sign * s.sgst_paise
                result.outward_taxable_cess += sign * s.cess_paise

    # ── Table 3.2: Reverse charge INWARD supplies ────────────────────────────
    # C5 fix: RCM liability arises on INWARD supplies (purchases), not on sales.
    # The recipient self-assesses and pays this tax; the supplier never does.
    for p in purchases:
        if p.is_reverse_charge:
            result.rcm_igst += p.igst_paise
            result.rcm_cgst += p.cgst_paise
            result.rcm_sgst += p.sgst_paise

    # ── Table 4: ITC available ───────────────────────────────────────────────
    # C4 fix: each purchase's tax is counted ONCE. RCM ITC is already included in
    # the sum over all purchases (the recipient books the self-assessed tax as
    # input tax) — CGST Act Section 9(3)/(4) allows ITC on RCM paid, so it must NOT
    # be added a second time (the previous code double-counted every RCM purchase).
    #
    # CGST Act §17(5): blocked-credit lines are excluded from book ITC HERE —
    # before the Rule 36(4) 2A/2B cap below — because ineligibility is a hard
    # statutory bar, not a matching restriction; it must never be "restored"
    # by capping logic that only compares against supplier-filed records.
    book_igst = sum(p.igst_paise - p.ineligible_igst_paise for p in purchases)
    book_cgst = sum(p.cgst_paise - p.ineligible_cgst_paise for p in purchases)
    book_sgst = sum(p.sgst_paise - p.ineligible_sgst_paise for p in purchases)
    book_cess = sum(p.cess_paise - p.ineligible_cess_paise for p in purchases)

    result.itc_ineligible_igst = sum(p.ineligible_igst_paise for p in purchases)
    result.itc_ineligible_cgst = sum(p.ineligible_cgst_paise for p in purchases)
    result.itc_ineligible_sgst = sum(p.ineligible_sgst_paise for p in purchases)
    result.itc_ineligible_cess = sum(p.ineligible_cess_paise for p in purchases)

    gstr2a_igst = sum(r.igst_paise for r in gstr2a_records)
    gstr2a_cgst = sum(r.cgst_paise for r in gstr2a_records)
    gstr2a_sgst = sum(r.sgst_paise for r in gstr2a_records)

    itc_igst, capped_i = _apply_rule_36_4_cap(book_igst, gstr2a_igst)
    itc_cgst, capped_c = _apply_rule_36_4_cap(book_cgst, gstr2a_cgst)
    itc_sgst, capped_s = _apply_rule_36_4_cap(book_sgst, gstr2a_sgst)

    result.itc_book_igst = book_igst
    result.itc_book_cgst = book_cgst
    result.itc_book_sgst = book_sgst
    result.itc_2a_igst = gstr2a_igst
    result.itc_2a_cgst = gstr2a_cgst
    result.itc_2a_sgst = gstr2a_sgst
    result.itc_igst = itc_igst
    result.itc_cgst = itc_cgst
    result.itc_sgst = itc_sgst
    result.itc_cess = book_cess
    result.itc_capped_by_2a = capped_i or capped_c or capped_s

    # ── Table 4(B): credit given back this period ────────────────────────────
    # Split by whether it can ever come back, which is the only question the
    # return asks: 4(B)(1) permanent, 4(B)(2) reclaimable. See ITCReversal.
    for rv in reversals:
        if rv.reclaimable:
            result.itc_rev_temp_igst += rv.igst_paise
            result.itc_rev_temp_cgst += rv.cgst_paise
            result.itc_rev_temp_sgst += rv.sgst_paise
            result.itc_rev_temp_cess += rv.cess_paise
        else:
            result.itc_rev_perm_igst += rv.igst_paise
            result.itc_rev_perm_cgst += rv.cgst_paise
            result.itc_rev_perm_sgst += rv.sgst_paise
            result.itc_rev_perm_cess += rv.cess_paise

    # ── Table 6: Net tax payable ─────────────────────────────────────────────
    # CGST Act Section 49: IGST credit first against IGST, then CGST, then SGST.
    #
    # The credit set off here is Table 4(C) — what is left AFTER the 4(B)
    # reversals — not 4(A). Section 49(4) permits payment only out of credit
    # "available in the electronic credit ledger", and credit reversed in this
    # very return is not available: reversing it and then paying tax with it
    # would use the same rupee twice. Before reversals existed as an input this
    # distinction could not arise and the set-off read the gross figure; with a
    # cancellation in the period, that understates the tax payable by the whole
    # reversed amount, and the taxpayer underpays.
    avail_igst, avail_cgst, avail_sgst = (
        result.itc_net_igst, result.itc_net_cgst, result.itc_net_sgst)
    igst_after_itc = result.outward_taxable_igst - avail_igst

    if igst_after_itc <= 0:
        # Excess IGST ITC — offset against CGST and SGST (Section 49(5))
        excess_igst_itc = abs(igst_after_itc)
        half_excess = excess_igst_itc // 2
        result.net_igst = 0
        result.net_cgst = max(0, result.outward_taxable_cgst - avail_cgst - half_excess)
        result.net_sgst = max(0, result.outward_taxable_sgst - avail_sgst - (excess_igst_itc - half_excess))
    else:
        result.net_igst = igst_after_itc
        result.net_cgst = max(0, result.outward_taxable_cgst - avail_cgst)
        result.net_sgst = max(0, result.outward_taxable_sgst - avail_sgst)

    result.net_cess = max(0, result.outward_taxable_cess - result.itc_net_cess)

    return result
