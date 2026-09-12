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
from typing import Optional, Sequence

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
    # Table 3.2 needs to know, of the supplies in 3.1(a), which were made
    # INTER-STATE and to whom. Defaulted so existing callers are unaffected;
    # a supply left at the defaults simply never reaches 3.2.
    is_interstate: bool = False
    place_of_supply: str = ""     # 2-digit state code
    # registered | unregistered | composition | uin. Only the last three are
    # reported in 3.2 — a supply to an ordinary registered person is not.
    recipient_type: str = "registered"


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
    for (Notification 14/2022-Central Tax, Circular 170/02/2022-GST, live on
    the portal from 01-09-2022 and so for periods from August 2022).

    THE CIRCULAR'S OWN TEST, which is what to reason from when a new kind of
    reversal appears and none of the named rules fits it:

      4(B)(1)  "reversal of ITC that are absolute in nature and not
               reclaimable ... such as those on account of rule 38 (reversal of
               credit by a banking company or a financial institution), rule 42
               (reversal on input and input services on account of supply of
               exempted goods or services), rule 43 (reversal on capital goods
               on account of supply of exempted goods or services) of the CGST
               Rules and for reporting ineligible ITC under section 17(5) of
               the CGST Act."

      4(B)(2)  "ITC that is to be reclaimed or may be reclaimed on a future
               date should be reported in Table 4(B)(2)" — headed "ITC
               reversed - Others" — and "at the time of reclaim, ITC can be
               reclaimed through Table 4A(5) with additional disclosure in
               Table 4D(1)."

    Note "such as": the 4(B)(1) list is illustrative, not exhaustive. The test
    is ABSOLUTE AND NOT RECLAIMABLE, so a reversal that meets it belongs there
    whether or not the circular names it. Rule 37 / 37A (supplier unpaid past
    180 days) and §16(2)(b) and (c) are the everyday 4(B)(2) cases: the credit
    comes back when the supplier is paid.

    So:
      False -> 4(B)(1). Rules 38/42/43, §17(5), and anything else that is gone
               for good — a purchase cancelled after its credit was taken,
               stock written off.
      True  -> 4(B)(2). Comes back later through 4(A)(5), reported in 4(D)(1).

    Getting the side wrong is not a rounding matter: 4(B)(2) tells the portal a
    credit is coming back, and the electronic credit reversal and re-claimed
    statement reconciles against it. A permanent reversal declared there leaves
    a balance in that statement which never clears.

    PROVENANCE: the wording above is quoted from secondary sources reproducing
    the circular (GSTN's 02-09-2022 Table 4 advisory, Taxguru, ClearTax, VJM
    Global). cbic-gst.gov.in and taxinformation.cbic.gov.in are unreachable
    from this repo's build environment, so the text has not been diffed against
    the CBIC PDF itself. Anyone who can reach it should do that once.
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
    # Table 3.1(b) has TWO figures, not one. IGST Act §16(3) gives a zero-rated
    # supplier a choice: supply under a bond or LUT with no tax and claim a
    # refund of the unutilised credit (§16(3)(a)), or supply ON PAYMENT of
    # integrated tax and claim a refund of the tax paid (§16(3)(b), with CGST
    # Act §54). The second route is only worth taking because the tax is
    # declared and paid — so 3.1(b) carries the integrated tax as well as the
    # turnover, and a return that files the turnover with a nil tax has
    # declared an export under LUT that was not one, and claims no refund.
    #
    # This is whatever IGST the transaction actually carries. An LUT/bond
    # export has none and this stays zero, which is the correct declaration
    # for it; nothing is invented for a supply that bore no tax.
    outward_zero_rated_igst: int = 0
    outward_nil_exempt: int = 0      # nil-rated + exempt taxable value

    # Table 3.1(e) — NON-GST outward supplies. A separate line from 3.1(c),
    # and a different thing: 3.1(c) is a supply GST reaches and charges at nil
    # or exempts (§11), 3.1(e) is a supply GST does not reach at all —
    # petroleum products and alcoholic liquor for human consumption, excluded
    # by §9(1) and §9(2), and anything in Schedule III.
    #
    # This used to be a literal 0 in the payload while the accumulation loop
    # had no branch for `non_gst` at all, so such a supply fell off the end
    # silently (GST-06). The same invoice IS declared by GSTR-1, which maps
    # `non_gst` to `ngsup_amt` (gstr1_builder.py), so one document produced two
    # returns that disagreed about whether it existed. 3.1(e) carries no tax by
    # definition, so nothing was underpaid — what was wrong is the disclosure,
    # and the mismatch is the kind a portal comparison surfaces months later.
    outward_non_gst: int = 0         # non-GST outward supply value

    # Table 3.2 of the FORM (not of this dataclass's old numbering): of the
    # supplies declared in 3.1(a), the inter-state ones made to unregistered
    # persons, composition taxable persons and UIN holders, per place of
    # supply. Keyed by 2-digit state code -> {"txval": paise, "iamt": paise}.
    inter_sup_unreg: dict = field(default_factory=dict)
    inter_sup_comp: dict = field(default_factory=dict)
    inter_sup_uin: dict = field(default_factory=dict)

    # Reverse-charge INWARD supplies (CGST Act Section 9(3), 9(4))
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
    # Table 4(D)(1) — credit reversed under 4(B)(2) in an EARLIER period and
    # reclaimed now. A separate declaration from 4(B): it does not reduce this
    # period's 4(C), because the credit comes back through 4(A)(5) instead.
    itc_reclaimed_igst: int = 0
    itc_reclaimed_cgst: int = 0
    itc_reclaimed_sgst: int = 0
    itc_reclaimed_cess: int = 0

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
    #: The part of the book figure that is SELF-ASSESSED reverse-charge tax —
    #: §9(3)/(4), on the recipient's own §31(3)(f) invoice. Rule 36(4) does not
    #: reach it (it reaches only what a supplier furnishes under §37(1)), so it
    #: sits outside the cap. Reported because a CA who sees book ₹68,000
    #: against a 2A of ₹18,000 and NO cap applied needs to be able to see why
    #: without re-deriving it: the difference is tax they paid in cash.
    itc_self_assessed_igst: int = 0
    itc_self_assessed_cgst: int = 0
    itc_self_assessed_sgst: int = 0
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

    def itc_avl_rows(self) -> list[tuple[str, int, int, int, int]]:
        """Table 4(A), one tuple per row: (ty, igst, cgst, sgst, cess).

        The form has never had a single 4(A) line. It has five, and the GSTN
        offline utility (GSTR3B_Excel_Utility V5.8, sheet rows 31-35) writes one
        JSON object for each, unconditionally, in this order:

            4(A)(1) Import of goods                            IMPG
            4(A)(2) Import of services                         IMPS
            4(A)(3) Inward supplies liable to reverse charge   ISRC
            4(A)(4) Inward supplies from ISD                   ISD
            4(A)(5) All other ITC                              OTH

        This used to emit ONE object typed "ISRC" carrying the whole credit, so
        every rupee of a client's ITC was declared on the reverse-charge line
        of a filed return. "ISRC" is Inward Supplies Reverse Charge; the
        general bucket is "OTH".

        IMPG, IMPS and ISD are zero because nothing upstream distinguishes an
        import or an ISD distribution from any other purchase yet. They are
        still emitted: the utility always writes all five, and a row that is
        absent is not the same as a row that is nil.

        ISRC is capped at the credit available so the five rows sum to exactly
        4(A). Without the cap, a period where the Rule 36(4) cap trimmed credit
        below the reverse-charge tax would file a 4(A) that does not reconcile
        with its own 4(C).
        """
        isrc_i = min(self.rcm_igst, self.itc_avail_igst)
        isrc_c = min(self.rcm_cgst, self.itc_avail_cgst)
        isrc_s = min(self.rcm_sgst, self.itc_avail_sgst)
        return [
            ("IMPG", 0, 0, 0, 0),
            ("IMPS", 0, 0, 0, 0),
            # Reverse-charge tax is self-assessed by the recipient and taken as
            # credit in the same return (CGST Act §9(3)/(4) with §16).
            ("ISRC", isrc_i, isrc_c, isrc_s, 0),
            ("ISD", 0, 0, 0, 0),
            ("OTH",
             self.itc_avail_igst - isrc_i,
             self.itc_avail_cgst - isrc_c,
             self.itc_avail_sgst - isrc_s,
             self.itc_avail_cess),
        ]

    # Table 6: tax on OUTWARD supplies still payable after the §49 set-off.
    # This is not the whole of what the return pays — see the reverse-charge
    # block below, which never touches these figures.
    net_igst: int = 0
    net_cgst: int = 0
    net_sgst: int = 0
    net_cess: int = 0

    # ── The liability the set-off is run against ─────────────────────────────
    # Derived, so Table 6 and the credit-utilisation figures below can never be
    # run against two different liabilities.
    #
    # Each head floors at zero. A period's credit notes can exceed its invoices
    # (CGST Act §34), and a negative liability is not a set-off against which
    # credit can be spent — it reduces the next period's outward tax, not this
    # one's credit ledger.

    @property
    def liability_igst(self) -> int:
        """Table 6.1 integrated tax: 3.1(a) plus the 3.1(b) zero-rated supplies
        made WITH payment of integrated tax (IGST Act §16(3)(b)). An export on
        payment of tax is a real IGST liability, discharged here and refunded
        under CGST Act §54; an LUT/bond export contributes nothing because it
        carries no tax."""
        return max(self.outward_taxable_igst + self.outward_zero_rated_igst, 0)

    @property
    def liability_cgst(self) -> int:
        return max(self.outward_taxable_cgst, 0)

    @property
    def liability_sgst(self) -> int:
        return max(self.outward_taxable_sgst, 0)

    @property
    def liability_cess(self) -> int:
        return max(self.outward_taxable_cess, 0)

    # ── Reverse charge is paid in CASH and never out of credit ───────────────
    #
    # CGST Act §49(4): the electronic credit ledger "may be used for making any
    # payment towards OUTPUT TAX". Output tax is defined by §2(82) as the tax
    # chargeable on a taxable supply made by the person or by his agent "but
    # EXCLUDES tax payable by him on reverse charge basis". So the §9(3)/(4)
    # liability declared in Table 3.1(d) is discharged out of the electronic
    # CASH ledger, in full, every time — and only then does the corresponding
    # credit become available (§16 with §49(2)), which is why it is claimed on
    # the 4(A)(3) ISRC row of the same return.
    #
    # That is why these are separate from net_igst/cgst/sgst rather than added
    # into them: adding the reverse-charge tax to the net figures would let the
    # set-off above discharge it out of credit, which §49(4) forbids. It used
    # to be omitted from the payable side altogether while its credit was still
    # deducted, so a return with reverse-charge purchases understated the tax
    # by twice the reverse-charge amount — once for the liability that was
    # never added, once for the credit that reduced everything else.

    @property
    def rcm_cash_paise(self) -> int:
        """Table 3.1(d) tax — payable in cash, no set-off available."""
        return self.rcm_igst + self.rcm_cgst + self.rcm_sgst

    @property
    def cash_payable_igst(self) -> int:
        """Everything this return pays in cash under the integrated head: what
        the set-off could not cover, plus the reverse-charge tax it could never
        have covered."""
        return self.net_igst + self.rcm_igst

    @property
    def cash_payable_cgst(self) -> int:
        return self.net_cgst + self.rcm_cgst

    @property
    def cash_payable_sgst(self) -> int:
        return self.net_sgst + self.rcm_sgst

    @property
    def cash_payable_cess(self) -> int:
        """No reverse-charge cess is modelled, so this is the set-off residue."""
        return self.net_cess

    @property
    def cash_payable_paise(self) -> int:
        """Total cash outgo for the period across every head."""
        return (self.cash_payable_igst + self.cash_payable_cgst
                + self.cash_payable_sgst + self.cash_payable_cess)

    # ── What is LEFT of the credit once Table 6 has set off what it can ──────
    #
    # WHY THIS EXISTS
    #   Net tax of zero has two entirely different meanings and the return
    #   cannot tell them apart on its own:
    #
    #       liability and credit cancelled out, nothing carries forward
    #       credit exceeded liability, and the excess sits in the ledger
    #
    #   Apex, April 2026: liability Rs 17,77,664.34, credit Rs 54,32,625.99,
    #   net tax Rs 0 — and Rs 36,54,961.65 of that credit carrying into May with
    #   nothing on screen saying so. Both readings of that zero are consistent
    #   with the figures shown, and the difference is a third of a crore.
    #
    #   The set-off itself is unchanged. §49(4) allows payment only out of
    #   credit available in the electronic credit ledger, and net tax already
    #   floors at zero because there is no such thing as negative tax payable.
    #   What was missing was the residual, not a correction.
    #
    # WHY IT IS DERIVED FROM net_* RATHER THAN RECOMPUTED
    #   Credit consumed is (what was owed) minus (what is still payable). Taking
    #   the residual from the same net_* figures the screen displays means the
    #   balance cannot drift from them — a second set-off calculation, run
    #   beside the first and printed next to it, is exactly the kind of pair
    #   that disagrees six months later.
    #
    # NOT the electronic credit ledger balance. That is a portal figure and
    # carries every earlier period's closing balance; this is the credit this
    # ONE return leaves behind.

    @property
    def itc_consumed_paise(self) -> int:
        """Credit actually used to discharge this period's liability.

        The reverse-charge tax is deliberately NOT in `owed`: §49(4) with
        §2(82) keeps it out of the credit ledger's reach, so no credit is
        consumed by it and none of it may be netted here."""
        owed = (self.liability_igst + self.liability_cgst
                + self.liability_sgst + self.liability_cess)
        still_payable = self.net_igst + self.net_cgst + self.net_sgst + self.net_cess
        return max(owed - still_payable, 0)

    @property
    def itc_available_paise(self) -> int:
        """Table 4(C) across all heads — credit this return may actually spend."""
        return (self.itc_net_igst + self.itc_net_cgst
                + self.itc_net_sgst + self.itc_net_cess)

    @property
    def itc_carried_forward_paise(self) -> int:
        """4(C) less what Table 6 spent. Floors at zero: the set-off can never
        spend credit that is not there, and a negative here would be a bug
        reported as a refund."""
        return max(self.itc_available_paise - self.itc_consumed_paise, 0)

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
        # Table 3.1.1 — supplies notified under CGST Act §9(5), where an
        # electronic commerce operator is liable for the tax instead of the
        # supplier. The GSTN utility gates this block on the return period and
        # writes it for every period from July 2022; before that the row did
        # not exist on the form. Zero here: nothing marks a supply as made
        # through an ECO, and neither side of §9(5) is modelled.
        eco_zero = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
        eco_dtls = (
            {"eco_dtls": {"eco_sup": dict(eco_zero),          # ECO pays the tax
                          "eco_reg_sup": dict(eco_zero)}}     # supplier through an ECO
            if _period_at_or_after(period, 7, 2022) else {}
        )
        return {
            "gstin": gstin,
            "ret_period": period,
            # Section 5 of the form — values of EXEMPT, NIL-RATED and NON-GST
            # INWARD supplies, split inter-state / intra-state. Not reverse
            # charge: this block previously carried the RCM figures under an
            # invented {"ty": "RCM", "inter", "intra_cgst", "intra_sgst"}, none
            # of which the schema has. The reverse-charge liability belongs in
            # sup_details.isup_rev (Table 3.1(d)) and is already there.
            #
            # Zero because purchases are not yet classified as exempt or
            # non-GST on the inward side. Both rows are emitted regardless: the
            # utility defaults the cells to 0 and always writes GST and NONGST.
            "inward_sup": {
                "isup_details": [
                    {"ty": "GST", "inter": 0, "intra": 0},
                    {"ty": "NONGST", "inter": 0, "intra": 0},
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
                # Table 3.1(b) — zero-rated. "iamt" used to be hardcoded 0,
                # which files every export as though it were made under a bond
                # or LUT. IGST Act §16(3)(b) lets a supplier export ON PAYMENT
                # of integrated tax and claim that tax back under CGST Act §54;
                # the refund is processed against what 3.1(b) declares, so a
                # nil there forfeits it. camt/samt/csamt stay nil: a zero-rated
                # supply is inter-state by IGST Act §7(5), so it can bear no
                # central or state tax.
                "osup_zero": {
                    "txval": r(self.outward_zero_rated),
                    "iamt": r(self.outward_zero_rated_igst),
                    "camt": 0, "samt": 0, "csamt": 0,
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
                # 3.1(e). Value only — a supply outside the levy bears no tax,
                # so the form has no tax columns here.
                "osup_nongst": {"txval": r(self.outward_non_gst)},
            },
            # Table 3.2 — of the supplies in 3.1(a), the inter-state ones made
            # to unregistered persons, composition taxable persons and UIN
            # holders, per place of supply. Read from the GSTN GSTR-3B utility
            # V5.8 (sheet rows 87-125): three arrays of {pos, txval, iamt}.
            #
            # comp_details and uin_details are always empty. A composition
            # dealer and a UIN holder both HOLD a registration number, so on
            # this platform's data they are indistinguishable from any other
            # registered recipient — nothing records that a customer is one.
            # Emitting an empty array says "none to report", which is the
            # accurate statement; inventing a split would not be.
            "inter_sup": {
                "unreg_details": _inter_sup_rows(self.inter_sup_unreg, r),
                "comp_details": _inter_sup_rows(self.inter_sup_comp, r),
                "uin_details": _inter_sup_rows(self.inter_sup_uin, r),
            },
            **eco_dtls,
            # ── Table 4, in the shape the portal has used since 01-09-2022 ──
            # Notification 14/2022-Central Tax and Circular 170/02/2022-GST:
            #
            #   4(A)    ALL ITC availed, including credit that is then reversed.
            #           "Table 4(A) now gets auto-populated with the total
            #           figure from the GSTR-2B, including ineligible ITC" — so
            #           a 4(A) that omits blocked credit cannot tie to 2B, and
            #           the taxpayer is asked to explain a difference that is
            #           only a difference of definition.
            #   4(B)(1) reversals "absolute in nature and not reclaimable ...
            #           such as those on account of rule 38 ... rule 42 ...
            #           rule 43 ... and for reporting ineligible ITC under
            #           section 17(5)". "Such as" — the list illustrates the
            #           test, it does not exhaust it. See ITCReversal.
            #   4(B)(2) "ITC that is to be reclaimed or may be reclaimed on a
            #           future date" — Rule 37/37A, §16(2)(b)/(c).
            #   4(C)    net ITC available = 4(A) - 4(B). "Table 4A captures
            #           gross ITC, Table 4B shows reversals, and Table 4C is
            #           the net ITC flowing to the credit ledger."
            #   4(D)(1) reclaims of amounts reversed earlier under 4(B)(2).
            #   4(D)(2) ineligible under §16(4) and the place-of-supply rules.
            #
            # This used to file 4(A) NET of §17(5), an empty 4(B), and §17(5)
            # under 4(D) — the pre-August-2022 layout. The tax payable came out
            # the same, but the face of the return was wrong in two ways: 4(A)
            # understated against 2B, and 4(B) said no credit had been reversed
            # in a period when the books had reversed some.
            "itc_elg": {
                # Five rows, always, in form order. See itc_avl_rows().
                "itc_avl": [
                    {"ty": ty, "iamt": r(i), "camt": r(c), "samt": r(sg),
                     "csamt": r(cs)}
                    for ty, i, c, sg, cs in self.itc_avl_rows()
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
                # Zero because neither is tracked yet. §17(5) is NOT reported
                # here any more; it moved to 4(B)(1) above, and the circular
                # leaves no room: "The reversal of ITC of ineligible credit
                # under section 17(5) or any other provisions is required to be
                # made under Table 4(B) and not under Table 4(D) of FORM
                # GSTR-3B." Reporting it in both overstates the ineligible
                # credit the portal shows against the taxpayer.
                "itc_inelg": [
                    # 4(D)(1) — credit reversed under 4(B)(2) in an EARLIER
                    # period and reclaimed now, from the ITC reversal register.
                    # It does NOT reduce this period's 4(C): the credit comes
                    # back through 4(A)(5), and 4(D)(1) is the disclosure that
                    # says where it came from.
                    {"ty": "RUL",
                     "iamt": r(self.itc_reclaimed_igst),
                     "camt": r(self.itc_reclaimed_cgst),
                     "samt": r(self.itc_reclaimed_sgst),
                     "csamt": r(self.itc_reclaimed_cess)},
                    # 4(D)(2) — §16(4) time-bar and place-of-supply
                    # ineligibility. Neither is tracked. §17(5) is NOT here; it
                    # is declared in 4(B)(1) above.
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


def _apply_rule_36_4_cap(book: int, gstr2a: int,
                        have_2b: bool = False) -> tuple[int, bool]:
    """Return (capped_itc, was_capped) using integer paise arithmetic.

    CGST Rule 36(4) (as amended w.e.f. 1 Jan 2022): ITC cannot exceed 100% of
    eligible GSTR-2A/2B credit — no provisional buffer.

    ZERO MEANS TWO DIFFERENT THINGS, and `have_2b` is what tells them apart.
    Until the 2B reconciliation was built nothing ever wrote `gstr2a_records`,
    so a zero could only mean "nobody uploaded anything" and leaving book ITC
    alone was the only honest answer. Now a 2B CAN be on file and show no
    eligible credit under this head — every document blocked by `itcavl`, or
    simply no IGST in the month — and for that the cap is genuinely NIL. Reading
    it as "no data" would let the return claim credit the portal has refused,
    which is the direction §16(2)(aa) exists to stop.

    Defaulted to False so every existing caller keeps the old behaviour: a
    caller that does not know whether a 2B is on file must not be treated as
    knowing there is none.
    """
    if gstr2a == 0 and not have_2b:
        # No GSTR-2A data — use book ITC; warn CA to upload GSTR-2A
        return book, False
    cap = (gstr2a * _RULE_36_4_NUMERATOR) // _RULE_36_4_DENOMINATOR
    if book > cap:
        return cap, True
    return book, False


def _inter_sup_rows(by_pos: dict, r) -> list[dict]:
    """Table 3.2 rows for one recipient class, sorted by place of supply.

    A place of supply that nets to nothing after credit notes is dropped: the
    utility writes a row only where the worksheet has a value, and declaring a
    nil inter-state supply to a state the client did not supply is noise on the
    face of the return.
    """
    return [
        {"pos": pos, "txval": r(v["txval"]), "iamt": r(v["iamt"])}
        for pos, v in sorted(by_pos.items())
        if v["txval"] or v["iamt"]
    ]


def _period_at_or_after(period: str, month: int, year: int) -> bool:
    """Is this MMYYYY return period on or after the given month and year?

    A string compare is wrong here — "012026" sorts below "122025" — so the
    period is split and compared as (year, month).

    An unparseable period is treated as being in range. The form has carried
    Table 3.1.1 since July 2022 and every period this product files is later
    than that, so including the block is the safe direction; omitting it on a
    malformed input would silently drop a section of a live return.
    """
    p = (period or "").strip()
    if len(p) != 6 or not p.isdigit():
        return True
    return (int(p[2:]), int(p[:2])) >= (year, month)


def compute_gstr3b(
    sales: Sequence[SalesTransaction],
    purchases: Sequence[PurchaseTransaction],
    gstr2a_records: Sequence[GSTR2ARecord],
    reversals: Sequence[ITCReversal] = (),
    reclaims: Sequence[ITCReversal] = (),
    have_2b: Optional[bool] = None,
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
        elif s.supply_type == "non_gst":
            # 3.1(e), NOT 3.1(c). Outside the levy rather than relieved of it —
            # see the field's comment. Falling off the end of this chain is
            # what GST-06 was.
            result.outward_non_gst += sign * s.taxable_amount_paise
        elif s.supply_type == "zero_rated":
            result.outward_zero_rated += sign * s.taxable_amount_paise
            # IGST Act §16(3)(b): an export or SEZ supply made ON PAYMENT of
            # integrated tax carries real IGST, refundable under CGST Act §54.
            # Only the taxable value used to be accumulated, so the tax on
            # every such supply vanished out of the return. Whatever the
            # transaction actually carries is carried here — an LUT/bond export
            # (§16(3)(a)) has none, and correctly contributes nothing.
            result.outward_zero_rated_igst += sign * s.igst_paise
        elif s.supply_type == "taxable":
            if not s.is_reverse_charge:
                result.outward_taxable_value += sign * s.taxable_amount_paise
                result.outward_taxable_igst += sign * s.igst_paise
                result.outward_taxable_cgst += sign * s.cgst_paise
                result.outward_taxable_sgst += sign * s.sgst_paise
                result.outward_taxable_cess += sign * s.cess_paise

                # Table 3.2 — "of the supplies shown in 3.1(a)". It is a
                # BREAKDOWN of what was just added above, never an addition to
                # it, so it is accumulated here and under the same sign: a
                # credit note reduces the 3.2 line it relates to as well.
                bucket = {
                    "unregistered": result.inter_sup_unreg,
                    "composition": result.inter_sup_comp,
                    "uin": result.inter_sup_uin,
                }.get(s.recipient_type)
                if s.is_interstate and bucket is not None and s.place_of_supply:
                    row = bucket.setdefault(s.place_of_supply,
                                            {"txval": 0, "iamt": 0})
                    row["txval"] += sign * s.taxable_amount_paise
                    row["iamt"] += sign * s.igst_paise

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

    # RULE 36(4) REACHES ONLY WHAT A SUPPLIER FURNISHES UNDER §37, AND
    # REVERSE-CHARGE TAX IS NOT THAT.
    #
    # Rule 36(4) opens: "Input tax credit to be availed by a registered person
    # in respect of invoices or debit notes, THE DETAILS OF WHICH ARE REQUIRED
    # TO BE FURNISHED BY THE SUPPLIER UNDER SUB-SECTION (1) OF SECTION 37".
    # On a §9(3)/(4) supply the supplier charges no tax and furnishes none: the
    # recipient issues a self-invoice under §31(3)(f) and pays the tax in cash,
    # and Rule 36(1)(b) makes THAT the document the credit rests on, "subject
    # to the payment of tax". A document the recipient issued to itself has no
    # supplier to have furnished it, so the sub-rule cannot reach it.
    #
    # WHAT THIS WAS DOING. `book_*` above sums every purchase, reverse-charge
    # included, and GSTR-2B can only ever carry what suppliers filed — so the
    # cap compared a book figure that includes self-assessed tax against a
    # portal figure that structurally cannot. Measured at HEAD before this
    # change: one ordinary ₹1,00,000 bill with ₹18,000 IGST matched in 2B, plus
    # one RCM supply carrying ₹50,000 of self-assessed IGST, gave book ₹68,000
    # capped to ₹18,000 — ₹50,000 of credit withheld on tax the client had
    # already paid in cash.
    #
    # It has been latent since the cap was written and is LIVE now: the 2B
    # reconciliation writes `gstr2a_records` and `gst_return_service` feeds
    # them in with `have_2b` from the reconciliation header, so the cap fires
    # on the return of any client whose CA has run a reconciliation.
    #
    # An IMPORT is deliberately NOT carved out with it. IGST on a bill of entry
    # IS communicated — GSTR-2B carries it in `impg`/`impgsez`, which
    # domain/gst/gstr2b.py parses — so it belongs inside the cap like any
    # other matched credit.
    rcm_book_igst = sum(p.igst_paise - p.ineligible_igst_paise
                        for p in purchases if p.is_reverse_charge)
    rcm_book_cgst = sum(p.cgst_paise - p.ineligible_cgst_paise
                        for p in purchases if p.is_reverse_charge)
    rcm_book_sgst = sum(p.sgst_paise - p.ineligible_sgst_paise
                        for p in purchases if p.is_reverse_charge)

    result.itc_ineligible_igst = sum(p.ineligible_igst_paise for p in purchases)
    result.itc_ineligible_cgst = sum(p.ineligible_cgst_paise for p in purchases)
    result.itc_ineligible_sgst = sum(p.ineligible_sgst_paise for p in purchases)
    result.itc_ineligible_cess = sum(p.ineligible_cess_paise for p in purchases)

    gstr2a_igst = sum(r.igst_paise for r in gstr2a_records)
    gstr2a_cgst = sum(r.cgst_paise for r in gstr2a_records)
    gstr2a_sgst = sum(r.sgst_paise for r in gstr2a_records)

    # WHETHER A 2B IS ON FILE AT ALL — a different fact from its total being
    # zero, and one this function cannot work out for itself.
    #
    # Deriving it from `len(gstr2a_records)`, which is what the caller-less
    # default below does, is WRONG whenever a 2B exists and yields no rows: the
    # supplier filed nothing, or every document is itcavl = "N" and the caller
    # filtered them out. Both mean the cap is NIL, and both look identical to
    # "no 2B uploaded" from in here. A caller that knows — gst_return_service
    # asks the reconciliation header, migration 341 — passes it explicitly.
    #
    # The fallback is kept, and kept as a fallback rather than a required
    # argument, because the direct-compute path and the mock-mode callers have
    # no header table to ask and their old behaviour is the safe one for them:
    # it never caps where it should not, it only fails to cap where it should.
    if have_2b is None:
        have_2b = len(gstr2a_records) > 0
    # Cap the §37 credit only, then add the self-assessed credit back whole.
    # Written as cap-then-add rather than by passing an inflated numerator,
    # because the cap must not be able to LEND the reverse-charge figure to the
    # matched credit either: a month with ₹50,000 of RCM and an unfiled ₹18,000
    # b2b bill owes exactly ₹50,000 of credit, not ₹68,000.
    itc_igst, capped_i = _apply_rule_36_4_cap(
        book_igst - rcm_book_igst, gstr2a_igst, have_2b)
    itc_cgst, capped_c = _apply_rule_36_4_cap(
        book_cgst - rcm_book_cgst, gstr2a_cgst, have_2b)
    itc_sgst, capped_s = _apply_rule_36_4_cap(
        book_sgst - rcm_book_sgst, gstr2a_sgst, have_2b)
    itc_igst += rcm_book_igst
    itc_cgst += rcm_book_cgst
    itc_sgst += rcm_book_sgst

    result.itc_book_igst = book_igst
    result.itc_book_cgst = book_cgst
    result.itc_book_sgst = book_sgst
    result.itc_self_assessed_igst = rcm_book_igst
    result.itc_self_assessed_cgst = rcm_book_cgst
    result.itc_self_assessed_sgst = rcm_book_sgst
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

    # ── Table 4(D)(1): credit reversed earlier and taken back now ────────────
    # Reported, never netted here. The credit itself re-enters through 4(A)(5)
    # — it is part of the period's availed ITC — and 4(D)(1) only discloses
    # that this much of it is a reclaim rather than a fresh purchase.
    for rc in reclaims:
        result.itc_reclaimed_igst += rc.igst_paise
        result.itc_reclaimed_cgst += rc.cgst_paise
        result.itc_reclaimed_sgst += rc.sgst_paise
        result.itc_reclaimed_cess += rc.cess_paise

    # ── Table 6: Net tax payable ─────────────────────────────────────────────
    #
    # WHAT IS SET OFF. The credit spent here is Table 4(C) — what is left AFTER
    # the 4(B) reversals — not 4(A). CGST Act §49(4) permits payment only out
    # of credit "available in the electronic credit ledger", and credit
    # reversed in this very return is not available: reversing it and then
    # paying tax with it would use the same rupee twice. Before reversals
    # existed as an input this distinction could not arise and the set-off read
    # the gross figure; with a cancellation in the period, that understates the
    # tax payable by the whole reversed amount, and the taxpayer underpays.
    #
    # WHAT IS NOT SET OFF. The reverse-charge liability in Table 3.1(d). §49(4)
    # reaches "output tax", which §2(82) defines to EXCLUDE tax payable on
    # reverse charge basis, so §9(3)/(4) tax is paid in cash and never out of
    # credit. It is deliberately absent from every line below and surfaces
    # through rcm_cash_paise / cash_payable_* instead.
    #
    # THE ORDER OF UTILISATION — CGST Act §49(5) read with §49A, §49B and
    # Rule 88A. Each is a separate rule and the whole answer needs all of them:
    #
    #   §49A + Rule 88A   IGST credit is exhausted FIRST — against IGST, then
    #                     towards CGST or SGST "in any order and in any
    #                     proportion" — before CGST or SGST credit may be used
    #                     towards any liability at all.
    #   §49(5)(b)         CGST credit: first towards CGST, THEN towards IGST.
    #   §49(5)(c)         SGST credit: first towards SGST, THEN towards IGST.
    #                     The proviso allows the second limb only "where the
    #                     balance of the input tax credit on account of central
    #                     tax is not available for payment of integrated tax",
    #                     so CGST credit reaches IGST before SGST credit does —
    #                     which is why step 3 runs before step 4.
    #   §49(5)(e)/(f)     CGST credit is NEVER usable towards SGST, nor SGST
    #                     credit towards CGST. There is no step doing either.
    #
    # The SECOND LIMBS of (b) and (c) were missing. IGST credit was carried
    # across to CGST and SGST, but CGST and SGST credit never went the other
    # way, so an exporter or any inter-state seller with local purchases was
    # shown the whole IGST liability as payable in cash while lakhs of central
    # and state credit sat unusable in the ledger. Nothing about it looked
    # wrong: the liability was right, the credit was right, only the bridge
    # between them was absent.
    avail_igst, avail_cgst, avail_sgst = (
        result.itc_net_igst, result.itc_net_cgst, result.itc_net_sgst)
    liab_igst = result.liability_igst
    liab_cgst = result.liability_cgst
    liab_sgst = result.liability_sgst

    # 1. IGST credit -> IGST liability. §49(5)(a), first limb.
    used = min(avail_igst, liab_igst)
    liab_igst -= used
    avail_igst -= used

    # 2. IGST credit -> CGST and SGST liability. §49(5)(a) second limb with
    #    Rule 88A ("in any order and in any proportion"). Split as evenly as
    #    the two remaining liabilities allow — the long-standing behaviour —
    #    and then let whatever one head cannot absorb fall to the other. A
    #    half that exceeds one head's liability is not a reason to leave IGST
    #    credit idle while the other head is still payable, and §49A requires
    #    this credit to be exhausted before any CGST or SGST credit is touched.
    #
    #    The halving is pinned from outside this module:
    #    tests/test_filing_demo_gstr3b.py reads this source for
    #    "half_excess = excess_igst_itc // 2", because the Table 6.1 note in
    #    services/filing_demo/gstr3b.py tells a CA the split is whatever the
    #    saved working computed rather than a rule the demo re-derives. Change
    #    the apportionment and that note has to be revisited.
    excess_igst_itc = avail_igst
    half_excess = excess_igst_itc // 2
    from_igst_c = min(liab_cgst, half_excess)
    from_igst_s = min(liab_sgst, excess_igst_itc - half_excess)
    liab_cgst -= from_igst_c
    liab_sgst -= from_igst_s
    avail_igst -= from_igst_c + from_igst_s
    mop_c = min(liab_cgst, avail_igst)
    liab_cgst -= mop_c
    avail_igst -= mop_c
    mop_s = min(liab_sgst, avail_igst)
    liab_sgst -= mop_s
    avail_igst -= mop_s

    # 3. CGST credit -> CGST liability, then IGST liability. §49(5)(b).
    #    Never towards SGST — §49(5)(e).
    used = min(avail_cgst, liab_cgst)
    liab_cgst -= used
    avail_cgst -= used
    used = min(avail_cgst, liab_igst)
    liab_igst -= used
    avail_cgst -= used

    # 4. SGST credit -> SGST liability, then IGST liability. §49(5)(c), after
    #    step 3 because of its proviso. Never towards CGST — §49(5)(f).
    used = min(avail_sgst, liab_sgst)
    liab_sgst -= used
    avail_sgst -= used
    used = min(avail_sgst, liab_igst)
    liab_igst -= used
    avail_sgst -= used

    result.net_igst = liab_igst
    result.net_cgst = liab_cgst
    result.net_sgst = liab_sgst

    # Compensation cess credit is usable only against compensation cess —
    # GST (Compensation to States) Act §11(2), which applies §49 to the cess
    # "as if it were tax", head for head. No cross-utilisation either way.
    result.net_cess = max(0, result.liability_cess - result.itc_net_cess)

    return result
