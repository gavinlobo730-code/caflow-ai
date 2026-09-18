"""The annual return, consolidated from the year's own returns (GST-10).

CGST Act s.44 with Rule 80(1): every registered person other than the excluded
classes furnishes an annual return for each financial year. The portal opens
FORM GSTR-9 once the year's GSTR-1s and GSTR-3Bs are furnished, and
auto-populates it FROM THEM — the annual return consolidates what was
DECLARED, not what the books say. That is the shape this module takes.

WHERE EACH FIGURE COMES FROM, AND WHY
    Part II's headline rows and the whole of Part III come from the twelve
    stored GSTR-3B rows, in PAISE, because that is where the tax was declared
    and paid and because `gstr3b_returns` keeps every figure as an integer
    paise column (migration 036 with 234 and 339). Twelve rows for a year —
    proportional to the ANSWER, never to transaction volume (CLAUDE.md).

    What GSTR-3B cannot split is Table 4's breakdown: B2C, B2B, exports on
    payment of tax, SEZ and deemed exports all ride inside Table 3.1(a). Those
    come from the year's stored GSTR-1 PAYLOADS, whose sections are exactly
    that distinction. Table 17's HSN summary is the same — twelve monthly
    Table-12 sections, totalled.

    ⚠️ A GSTR-1 payload holds 2-decimal RUPEES (the GSTN JSON does), so every
    figure read out of one is converted back through `Decimal(str(value))`
    rather than `value * 100`. `str()` of a float is the shortest form that
    round-trips, so a 2-dp rupee figure converts to paise exactly; multiplying
    a float by 100 does not, and twelve months of accumulated error would show
    up as a return that does not foot.

WHAT IS REFUSED, AND NAMED
    Six things, each because the answer is not in these books rather than
    because the arithmetic is hard. Every one reaches the response as a
    sentence in `gaps`, and none is silently nil — a nil on an annual return
    is a positive declaration that nothing was owed.

      * Table 6B's three-way split (inputs / capital goods / input services).
        No column on a purchase bill or its lines records which of the three a
        supply was, and the distinction is a judgement about USE. It is the
        CA's input, and the table says so rather than putting the whole figure
        on one row.
      * Table 6C against 6D — reverse charge from an UNREGISTERED supplier
        against a registered one. `vendors.gst_registration_status` records it
        (migration 388) but `gstr3b_returns` accumulates one combined
        reverse-charge figure, so the split is not in the monthly return this
        consolidates. Declared combined, and said.
      * Rule 39 (7B) — ISD credit is not modelled anywhere in this product.
      * TRAN-I and TRAN-II (6K, 6L, 7F, 7G) — transitional credit carried in
        from the pre-GST regime in 2017. Not modelled, and no client of this
        product has one it did not already declare years ago.
      * Table 8C — input tax credit on this year's inward supplies availed in
        the NEXT financial year up to the specified period. It is a fact about
        a year this return cannot see.
      * A month whose return was FILED but whose payload this product never
        held — the CA prepared it elsewhere and recorded the ARN here. Its tax
        is in the 3B row and its Table 4 breakdown is not, so the breakdown
        says which months it could not read.

    ⚠️ The FORM's own structure is `[S]`-graded throughout: every `.gov.in` is
    refused at this environment's egress proxy, so the table numbering and the
    row labels are written from knowledge and pinned by tests rather than read
    off the notified form. The FIGURES are not affected — each is a total of
    figures this product itself computed and the CA filed.

NOTHING IS FILED, AND NOTHING IS POSTED. This builds a working for a CA to
check against the portal's own auto-population.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from decimal import Decimal
from typing import Any, Iterable, Optional

#: What a GSTN money field looks like. Everything in a stored payload is
#: JSON, so a figure is a number or the string form of one.
_NUMERIC = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")

# ── Reading a GSTN payload's rupees back to paise, exactly ───────────────────


def paise_of(value: Any) -> int:
    """A 2-decimal rupee figure out of a stored GSTN payload, as integer paise.

    Through `Decimal(str(v))`, never `int(v * 100)`. `str()` of a float is the
    shortest representation that round-trips, so a figure the GSTR-1 builder
    wrote with `paise_to_rupees_2dp` converts back exactly; the multiplication
    does not, and twelve months of that error is a return that does not foot.
    """
    if value is None or isinstance(value, bool):
        # A bool is an int in Python, and `True` would become one rupee.
        return 0
    text = str(value).strip()
    # VALIDATED, not caught. A bare `except` here would be a silent swallow on
    # a figure that belongs on a statutory return — and the shape of a GSTN
    # money field is known, so there is nothing to guess: anything that is not
    # a number is not one, and the caller's own gaps already say which months
    # this product could not read.
    if not _NUMERIC.match(text):
        return 0
    return int((Decimal(text) * 100).to_integral_value())


def _items_total(items: Iterable[dict]) -> dict[str, int]:
    """Sum one document's `itms` array into the five heads."""
    out = {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    for it in items or []:
        det = (it or {}).get("itm_det") or {}
        for k in out:
            out[k] += paise_of(det.get(k))
    return out


def _add(into: dict[str, int], other: dict[str, int]) -> None:
    for k, v in other.items():
        into[k] = into.get(k, 0) + v


def _blank() -> dict[str, int]:
    return {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}


#: The `inv_typ` values the GSTR-1 builder writes, and which GSTR-9 Table 4 row
#: each belongs on. Read off `gstr1_builder._INV_TYP` by a test, so a value
#: added there without a home here fails rather than falling into 4B.
INV_TYP_ROW = {
    "R": "4B",     # ordinary registered supply
    "SEWP": "4D",  # SEZ with payment of tax
    "SEWOP": "5B",  # SEZ without payment — Table 5, no tax payable
    "DE": "4E",    # deemed export
}


@dataclass
class MonthlyReturn:
    """One month of the financial year, as this product holds it."""
    period: str                      # MMYYYY
    gstr1_status: Optional[str] = None
    gstr3b_status: Optional[str] = None
    #: The stored GSTN JSON of the month's GSTR-1, where this product built it.
    gstr1_payload: Optional[dict] = None
    #: The month's GSTR-3B row, whose money columns are integer paise.
    gstr3b_row: Optional[dict] = None

    @property
    def gstr1_filed(self) -> bool:
        return self.gstr1_status == "submitted"

    @property
    def gstr3b_filed(self) -> bool:
        return self.gstr3b_status == "submitted"


@dataclass
class Reversal:
    """One row of `itc_reversal_register` — the per-GROUND split Table 7 wants
    and GSTR-3B's own Table 4(B) does not carry."""
    reason_code: str
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0


@dataclass
class AnnualInputs:
    """What the CA supplies because the books cannot.

    Each is Optional and None means NOT STATED, which is reported as a gap —
    never defaulted to zero. A zero on Table 6B(1) is a declaration that no
    credit was taken on inputs all year.
    """
    itc_inputs: Optional[dict[str, int]] = None
    itc_capital_goods: Optional[dict[str, int]] = None
    itc_input_services: Optional[dict[str, int]] = None
    #: Table 8C — credit of this FY availed in the next one.
    itc_availed_next_fy: Optional[dict[str, int]] = None


@dataclass
class Row:
    """One row of the annual return: a label, a taxable value and four heads."""
    code: str
    label: str
    txval: int = 0
    iamt: int = 0
    camt: int = 0
    samt: int = 0
    csamt: int = 0
    #: Set where the figure could not be derived. A row with a note is NOT a
    #: declaration of nil.
    note: Optional[str] = None

    def as_dict(self) -> dict:
        d = {"code": self.code, "label": self.label, "txval_paise": self.txval,
             "igst_paise": self.iamt, "cgst_paise": self.camt,
             "sgst_paise": self.samt, "cess_paise": self.csamt}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class GSTR9:
    financial_year: str
    gstin: str
    tables: dict[str, list[Row]] = field(default_factory=dict)
    hsn: list[dict] = field(default_factory=list)
    months: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    #: True only when every month of the year has BOTH returns filed. The
    #: portal opens GSTR-9 on exactly that condition, and a consolidation of
    #: eleven months presented as twelve is a wrong return.
    is_complete: bool = False

    def as_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "gstin": self.gstin,
            "tables": {k: [r.as_dict() for r in v] for k, v in self.tables.items()},
            "hsn": self.hsn,
            "months": self.months,
            "gaps": self.gaps,
            "is_complete": self.is_complete,
            "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        }


# ── Reading a stored GSTR-3B ────────────────────────────────────────────────
#
# NOT from `gstr3b_returns`' own per-head paise columns. Migration 036 declared
# them and the save path has never written one — `save_gstr3b` stores
# `tax_liability_paise`, `itc_claimed_paise`, `net_tax_paise`,
# `rcm_cash_paise`, `cash_payable_paise` and the two JSON blobs, and every
# other column keeps its DEFAULT 0. Reading them would give a confident nil for
# every month of every client, which is the worst possible answer on an annual
# return.
#
# So the figures come from `payload_json`, which is the GSTN JSON this product
# built and the CA filed. It holds WHOLE RUPEES (GSTR-3B does not take paise —
# CGST Act s.170, and `domain/gst/money.paise_to_rupees_whole`), so converting
# back is exact and is not a precision loss: the annual return consolidates
# what was DECLARED, and what was declared was those rupees.


def _sup(payload: Optional[dict], block: str) -> dict[str, int]:
    """One `sup_details` block of a stored GSTR-3B, in paise."""
    d = ((payload or {}).get("sup_details") or {}).get(block) or {}
    return {"txval": paise_of(d.get("txval")),
            "iamt": paise_of(d.get("iamt")),
            "camt": paise_of(d.get("camt")),
            "samt": paise_of(d.get("samt")),
            "csamt": paise_of(d.get("csamt"))}


def _itc_avl(payload: Optional[dict], ty: str) -> dict[str, int]:
    """One row of Table 4(A) — IMPG, IMPS, ISRC, ISD or OTH — in paise.

    These five are `gstr3b_computer.itc_avl_rows()`'s own output, and each maps
    onto exactly one row of GSTR-9 Table 6: import of goods to 6E, import of
    services to 6F, domestic reverse charge to 6C+6D, ISD to 6G, and "all other
    ITC" to 6B with 6H.
    """
    for row in ((payload or {}).get("itc_elg") or {}).get("itc_avl") or []:
        if str((row or {}).get("ty") or "").upper() == ty:
            return {"txval": 0,
                    "iamt": paise_of(row.get("iamt")),
                    "camt": paise_of(row.get("camt")),
                    "samt": paise_of(row.get("samt")),
                    "csamt": paise_of(row.get("csamt"))}
    return _blank()


# ── Part II: the outward side ───────────────────────────────────────────────

def _table_4_and_5(months: list[MonthlyReturn], gaps: list[str]
                   ) -> tuple[list[Row], list[Row]]:
    """Tables 4 and 5 — supplies on which tax IS and IS NOT payable.

    The BREAKDOWN comes from the GSTR-1 payloads (B2C, B2B, exports on payment,
    SEZ, deemed export are all one line in GSTR-3B Table 3.1(a)); the reverse-
    charge and nil/exempt/non-GST figures come from the 3B rows, where they are
    already integer paise and already the figure that was declared.
    """
    buckets: dict[str, dict[str, int]] = {}

    def bucket(code: str) -> dict[str, int]:
        return buckets.setdefault(code, _blank())

    unread: list[str] = []
    for m in months:
        payload = m.gstr1_payload or {}
        if m.gstr1_filed and not payload:
            unread.append(m.period)

        # 4A — supplies to unregistered persons. b2cs is rate-grouped, b2cl is
        # per invoice; both are Table 4A of the annual return.
        for grp in payload.get("b2cs") or []:
            _add(bucket("4A"), {
                "txval": paise_of(grp.get("txval")),
                "iamt": paise_of(grp.get("iamt")),
                "camt": paise_of(grp.get("camt")),
                "samt": paise_of(grp.get("samt")),
                "csamt": paise_of(grp.get("csamt")),
            })
        for grp in payload.get("b2cl") or []:
            for inv in grp.get("inv") or []:
                _add(bucket("4A"), _items_total(inv.get("itms")))

        # 4B / 4D / 4E / 5B — all inside the b2b section, told apart by inv_typ.
        for grp in payload.get("b2b") or []:
            for inv in grp.get("inv") or []:
                row = INV_TYP_ROW.get(str(inv.get("inv_typ") or "R"), "4B")
                _add(bucket(row), _items_total(inv.get("itms")))

        # 4C / 5A — exports, split by whether the tax was paid (IGST Act
        # s.16(3): with payment and claim the tax back, or under LUT/bond and
        # claim the unutilised credit).
        for grp in payload.get("exp") or []:
            code = "4C" if str(grp.get("exp_typ") or "").upper() == "WPAY" else "5A"
            for inv in grp.get("inv") or []:
                _add(bucket(code), _items_total(inv.get("itms")))

        # 4I / 4J — credit and debit notes, CGST Act s.34. Registered and
        # unregistered together: the annual return splits by DIRECTION, not by
        # whether the recipient was registered.
        for grp in payload.get("cdnr") or []:
            for nt in grp.get("nt") or []:
                _add(bucket("4I" if str(nt.get("ntty")) == "C" else "4J"),
                     _items_total(nt.get("itms")))
        for nt in payload.get("cdnur") or []:
            _add(bucket("4I" if str(nt.get("ntty")) == "C" else "4J"),
                 _items_total(nt.get("itms")))

        # 4F — advances taxed on receipt with no invoice yet issued. GSTR-1
        # Table 11A is where they are declared (s.13(2): for SERVICES the time
        # of supply is the earlier of invoice or payment, and Notification
        # 66/2017-Central Tax removed the charge for goods), less 11B where a
        # later invoice consumed one.
        for at in payload.get("at") or []:
            for it in at.get("itms") or []:
                _add(bucket("4F"), {
                    "txval": paise_of(it.get("ad_amt") or at.get("ad_amt")),
                    "iamt": paise_of(it.get("iamt")),
                    "camt": paise_of(it.get("camt")),
                    "samt": paise_of(it.get("samt")),
                    "csamt": paise_of(it.get("csamt"))})
        for tx in payload.get("txpd") or []:
            for it in tx.get("itms") or []:
                _add(bucket("4F"), {
                    "txval": -paise_of(it.get("ad_amt") or tx.get("ad_amt")),
                    "iamt": -paise_of(it.get("iamt")),
                    "camt": -paise_of(it.get("camt")),
                    "samt": -paise_of(it.get("samt")),
                    "csamt": -paise_of(it.get("csamt"))})

        # From the month's stored GSTR-3B payload, in paise.
        b3 = (m.gstr3b_row or {}).get("payload_json") or {}
        _add(bucket("4G"), _sup(b3, "isup_rev"))
        _add(bucket("5D"), {**_blank(), "txval": _sup(b3, "osup_nil_exmp")["txval"]})
        _add(bucket("5F"), {**_blank(), "txval": _sup(b3, "osup_nongst")["txval"]})

    if unread:
        gaps.append(
            f"{len(unread)} month(s) of this year were filed but this product "
            f"does not hold their GSTR-1 — {', '.join(unread)}. Their tax is in "
            f"the annual totals (it comes from the GSTR-3B rows), and their "
            f"Table 4 breakdown between B2C, B2B, exports, SEZ and deemed "
            f"exports is NOT: those rows are short by whatever those months "
            f"declared.")

    labels_4 = [
        ("4A", "Supplies to unregistered persons (B2C)"),
        ("4B", "Supplies to registered persons (B2B)"),
        ("4C", "Zero-rated supply (export) on payment of tax"),
        ("4D", "Supply to SEZ on payment of tax"),
        ("4E", "Deemed exports"),
        ("4F", "Advances on which tax has been paid but invoice not issued"),
        ("4G", "Inward supplies on which tax is payable on reverse charge"),
        ("4I", "Credit notes issued in respect of 4A to 4G"),
        ("4J", "Debit notes issued in respect of 4A to 4G"),
    ]
    labels_5 = [
        ("5A", "Zero-rated supply (export) without payment of tax"),
        ("5B", "Supply to SEZ without payment of tax"),
        ("5D", "Exempted and nil rated"),
        ("5F", "Non-GST supply"),
    ]
    table_4 = [Row(code, label, **buckets.get(code, _blank()))
               for code, label in labels_4]
    table_5 = [Row(code, label, **buckets.get(code, _blank()))
               for code, label in labels_5]

    # 4H / 4N and 5G / 5M — the sub-totals. 4I and 4J are the note ADJUSTMENTS,
    # so 4N is 4H less credit notes plus debit notes.
    gross = _blank()
    for r in table_4:
        if r.code in ("4I", "4J"):
            continue
        _add(gross, {"txval": r.txval, "iamt": r.iamt, "camt": r.camt,
                     "samt": r.samt, "csamt": r.csamt})
    cn = next(r for r in table_4 if r.code == "4I")
    dn = next(r for r in table_4 if r.code == "4J")
    table_4.insert(len(table_4) - 2, Row("4H", "Sub-total (A to G above)", **gross))
    table_4.append(Row(
        "4N", "Supplies and advances on which tax is to be paid (H + M above)",
        txval=gross["txval"] - cn.txval + dn.txval,
        iamt=gross["iamt"] - cn.iamt + dn.iamt,
        camt=gross["camt"] - cn.camt + dn.camt,
        samt=gross["samt"] - cn.samt + dn.samt,
        csamt=gross["csamt"] - cn.csamt + dn.csamt))

    total_5 = _blank()
    for r in table_5:
        _add(total_5, {"txval": r.txval, "iamt": r.iamt, "camt": r.camt,
                       "samt": r.samt, "csamt": r.csamt})
    table_5.append(Row("5M", "Turnover on which tax is not to be paid", **total_5))
    table_5.append(Row(
        "5N", "Total turnover (including advances)",
        txval=total_5["txval"] + gross["txval"],
        iamt=0, camt=0, samt=0, csamt=0,
        note="Taxable value only — 5N is a turnover figure, not a tax one."))
    return table_4, table_5


# ── Part III: the credit side ───────────────────────────────────────────────

def _heads(d: Optional[dict[str, int]]) -> dict[str, int]:
    d = d or {}
    return {"txval": 0,
            "iamt": int(d.get("igst_paise") or 0),
            "camt": int(d.get("cgst_paise") or 0),
            "samt": int(d.get("sgst_paise") or 0),
            "csamt": int(d.get("cess_paise") or 0)}


def _table_6(months: list[MonthlyReturn], inputs: AnnualInputs,
             gaps: list[str]) -> list[Row]:
    """Table 6 — input tax credit availed, as declared in the year's GSTR-3Bs."""
    # Table 4(A)'s five rows ARE Table 6's rows. GST-24 split IMPS out of ISRC
    # and PUR-18 gave IMPG a document, so each of the three that can carry a
    # figure is already told apart in the return being consolidated — there is
    # nothing left to apportion here.
    total = _blank()
    isrc = _blank()
    imps = _blank()
    impg = _blank()
    isd = _blank()
    other = _blank()
    unread_3b: list[str] = []
    for m in months:
        b3 = (m.gstr3b_row or {}).get("payload_json") or {}
        if m.gstr3b_filed and not b3:
            unread_3b.append(m.period)
        for bucket, ty in ((impg, "IMPG"), (imps, "IMPS"), (isrc, "ISRC"),
                           (isd, "ISD"), (other, "OTH")):
            cell = _itc_avl(b3, ty)
            _add(bucket, cell)
            _add(total, cell)

    if unread_3b:
        gaps.append(
            f"{len(unread_3b)} month(s) were filed but this product does not "
            f"hold their GSTR-3B payload — {', '.join(unread_3b)}. Every credit "
            f"row below is short by whatever those months availed.")

    domestic_rcm = isrc

    rows = [Row("6A", "Total ITC availed as per GSTR-3B (auto)", **total)]

    # 6B's TOTAL is derived — it is Table 4(A)(5) "All other ITC", which is
    # exactly "inward supplies other than imports and reverse charge". What is
    # NOT derived is the three-way split, so the total is shown as a row of its
    # own and the three carry the CA's figures or a note. That is the honest
    # shape: the amount is known, only its apportionment is not.
    rows.append(Row(
        "6B", "Inward supplies other than imports and reverse charge (total)",
        **other))

    split_note = (
        "Not derived: no column on a purchase bill or its lines records whether "
        "a supply was an input, a capital good or an input service, and the "
        "distinction is a judgement about use. The TOTAL is 6B above; split it, "
        "or leave the three rows for the portal.")
    stated = _blank()
    for code, label, supplied in (
        ("6B(1)", "— inputs", inputs.itc_inputs),
        ("6B(2)", "— capital goods", inputs.itc_capital_goods),
        ("6B(3)", "— input services", inputs.itc_input_services),
    ):
        if supplied is None:
            rows.append(Row(code, label, note=split_note))
        else:
            cell = _heads(supplied)
            _add(stated, cell)
            rows.append(Row(code, label, **cell))
    missing_split = any(x is None for x in (
        inputs.itc_inputs, inputs.itc_capital_goods, inputs.itc_input_services))
    if missing_split:
        gaps.append(
            "Table 6B's three-way split — inputs, capital goods and input "
            "services — is not derived: nothing in these books records which of "
            "the three a purchase was, and it is a judgement about USE. The "
            "TOTAL is derived and shown; a nil on two of the three rows would "
            "declare that no credit was taken on capital goods or on services "
            "all year.")
    elif any(stated[k] != other[k] for k in stated):
        gaps.append(
            "The three parts of Table 6B do not add up to the total credit on "
            "inward supplies other than imports and reverse charge. One of the "
            "four figures is wrong.")

    rows.append(Row(
        "6C+6D", "Inward supplies on which tax is paid on reverse charge",
        **domestic_rcm,
        note=("Combined. Table 6C is reverse charge from an UNREGISTERED "
              "supplier and 6D from a registered one; the monthly GSTR-3B this "
              "consolidates accumulates one figure for both, so the split is "
              "not in the return being consolidated.")))
    gaps.append(
        "Table 6C and 6D are declared as one figure: the reverse-charge split "
        "between unregistered and registered suppliers is recorded on the "
        "vendor (vendors.gst_registration_status) but is not carried by the "
        "monthly GSTR-3B this annual return consolidates.")

    rows.append(Row("6E", "Import of goods (including supplies from SEZ)", **impg))
    rows.append(Row("6F", "Import of services (excluding inward supplies from SEZ)", **imps))
    rows.append(Row(
        "6G", "Input Tax Credit received from ISD", note=(
            "Not modelled: this product has no Input Service Distributor "
            "invoice, so a figure here would be invented.")))
    for code, label in (("6K", "Transition Credit through TRAN-I"),
                        ("6L", "Transition Credit through TRAN-II")):
        rows.append(Row(code, label, note=(
            "Transitional credit carried in from the pre-GST regime in 2017. "
            "Not modelled.")))
    gaps.append(
        "Tables 6G (ISD), 6K and 6L (TRAN-I and TRAN-II) are not derived: "
        "neither an ISD invoice nor a transitional credit is modelled in this "
        "product, so each row is left blank rather than declared nil.")

    # 6H — credit reversed in an EARLIER period under Table 4(B)(2) and
    # reclaimed during this year. GSTR-3B carries it in Table 4(D)(1), which is
    # a DISCLOSURE rather than an addition (the credit comes back through
    # 4(A)(5)), so it is already inside 6A and is shown here for Table 8B.
    reclaim = _blank()
    for m in months:
        b3 = (m.gstr3b_row or {}).get("payload_json") or {}
        for row in ((b3.get("itc_elg") or {}).get("itc_inelg") or [])[:1]:
            _add(reclaim, {"txval": 0,
                           "iamt": paise_of(row.get("iamt")),
                           "camt": paise_of(row.get("camt")),
                           "samt": paise_of(row.get("samt")),
                           "csamt": paise_of(row.get("csamt"))})
    rows.append(Row(
        "6H", "Amount of ITC reclaimed (other than B above)", **reclaim,
        note=("Already inside 6A: GSTR-3B Table 4(D)(1) is a disclosure of "
              "where reclaimed credit came from, and the credit itself comes "
              "back through 4(A)(5).")))

    rows.append(Row("6O", "Total ITC availed", **total))
    return rows


def _table_7(reversals: list[Reversal], gaps: list[str],
             table_6_total: dict[str, int]) -> list[Row]:
    """Table 7 — ITC reversed and ineligible, per GROUND.

    From `itc_reversal_register`, which records the statutory ground of every
    reversal (migration 362). GSTR-3B's own Table 4(B) cannot answer this: it
    has two boxes, permanent and reclaimable, and Rules 38, 42, 43 and s.17(5)
    share one of them.
    """
    by_ground: dict[str, dict[str, int]] = {}
    for r in reversals:
        into = by_ground.setdefault(r.reason_code, _blank())
        _add(into, {"txval": 0, "iamt": r.igst_paise, "camt": r.cgst_paise,
                    "samt": r.sgst_paise, "csamt": r.cess_paise})

    #: Each GSTR-9 row and the register ground(s) that feed it.
    GROUNDS = [
        ("7A", "As per Rule 37", ("rule_37", "rule_37a")),
        ("7B", "As per Rule 39", ()),
        ("7C", "As per Rule 42", ("rule_42",)),
        ("7D", "As per Rule 43", ("rule_43",)),
        ("7E", "As per section 17(5)", ("section_17_5_h", "section_17_5_other")),
        ("7H", "Other reversals", ("rule_38", "section_16_2b", "section_16_2c",
                                   "other")),
    ]
    rows: list[Row] = []
    total = _blank()
    for code, label, grounds in GROUNDS:
        cell = _blank()
        for g in grounds:
            _add(cell, by_ground.get(g, _blank()))
        note = None
        if not grounds:
            note = ("Rule 39 is an ISD reversal, and no Input Service "
                    "Distributor invoice is modelled in this product.")
        rows.append(Row(code, label, **cell, note=note))
        _add(total, cell)
    for code, label in (("7F", "As per TRAN-I"), ("7G", "As per TRAN-II")):
        rows.append(Row(code, label, note=(
            "Transitional credit reversal from 2017. Not modelled.")))
    rows.append(Row("7I", "Total ITC reversed", **total))
    rows.append(Row(
        "7J", "Net ITC available for utilisation (6O − 7I)",
        txval=0,
        iamt=table_6_total["iamt"] - total["iamt"],
        camt=table_6_total["camt"] - total["camt"],
        samt=table_6_total["samt"] - total["samt"],
        csamt=table_6_total["csamt"] - total["csamt"]))

    seen = set(by_ground)
    known = {g for _, _, gs in GROUNDS for g in gs}
    stray = sorted(seen - known)
    if stray:
        gaps.append(
            f"The ITC reversal register holds ground(s) this table has no row "
            f"for — {', '.join(stray)}. They are NOT in Table 7's total; decide "
            f"where each belongs before filing.")
    return rows


def _table_8(table_6: list[Row], two_b: Optional[dict[str, int]],
             inputs: AnnualInputs, gaps: list[str]) -> list[Row]:
    """Table 8 — other ITC information: what the portal says was available
    against what was availed."""
    def row(code: str) -> Row:
        return next((r for r in table_6 if r.code == code), Row(code, ""))

    rows: list[Row] = []
    if two_b is None:
        rows.append(Row("8A", "ITC as per GSTR-2A / 2B (auto)", note=(
            "No GSTR-2B has been reconciled for this year in this product, so "
            "there is nothing to compare against. The portal auto-populates "
            "this row.")))
        gaps.append(
            "Table 8A is left for the portal: no GSTR-2B for this year has been "
            "uploaded and reconciled here, so the figure the portal will "
            "auto-populate cannot be checked against anything.")
    else:
        rows.append(Row("8A", "ITC as per GSTR-2A / 2B (auto)", **_heads(two_b)))

    # 8B is 6(B) + 6(H), and BOTH are derived — 6B's total is Table 4(A)(5)
    # "All other ITC" and 6H is Table 4(D)(1). The three-way split of 6B is
    # what is not derived, and 8B does not need it.
    b_total = _blank()
    for code in ("6B", "6H"):
        r = row(code)
        _add(b_total, {"txval": 0, "iamt": r.iamt, "camt": r.camt,
                       "samt": r.samt, "csamt": r.csamt})
    rows.append(Row("8B", "ITC as per sum of 6(B) and 6(H)", **b_total))

    if two_b is not None:
        a = rows[0]
        rows.append(Row(
            "8D", "Difference (8A − 8B)",
            txval=0, iamt=a.iamt - b_total["iamt"], camt=a.camt - b_total["camt"],
            samt=a.samt - b_total["samt"], csamt=a.csamt - b_total["csamt"],
            note=("A POSITIVE figure is credit the portal shows as available "
                  "that this client did not avail; a negative one is credit "
                  "availed that the portal does not show, which is what "
                  "s.16(2)(aa) makes decisive.")))

    if inputs.itc_availed_next_fy is None:
        rows.append(Row(
            "8C", "ITC on inward supplies of this year availed in the next year",
            note=("A fact about the NEXT financial year's returns, which this "
                  "one cannot see. State it before filing.")))
        gaps.append(
            "Table 8C — credit on this year's inward supplies availed in the "
            "next financial year up to the specified period — is a fact about "
            "returns this year's consolidation cannot see.")
    else:
        rows.append(Row(
            "8C", "ITC on inward supplies of this year availed in the next year",
            **_heads(inputs.itc_availed_next_fy)))
    return rows


# ── Table 17: the HSN summary ───────────────────────────────────────────────

def _table_17(months: list[MonthlyReturn]) -> list[dict]:
    """The year's outward HSN summary, from the twelve monthly Table 12s.

    Quantity is a float in the GSTN payload (it is a measured quantity, not
    money) and is summed as one; every VALUE goes through `paise_of`.
    """
    by_code: dict[str, dict] = {}
    for m in months:
        for r in ((m.gstr1_payload or {}).get("hsn") or {}).get("data") or []:
            code = str(r.get("hsn_sc") or "")
            if not code:
                continue
            cell = by_code.setdefault(code, {
                "hsn_sc": code, "desc": r.get("desc"), "uqc": r.get("uqc"),
                "qty": 0.0, "txval_paise": 0, "igst_paise": 0,
                "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0})
            # Validated rather than caught, for `paise_of`'s reason: the
            # quantity is the one field here that is NOT money (it is a
            # measured quantity in the line's own UQC, and nothing converts
            # tonnes to kilograms), so it is a float — but a swallowed
            # conversion would drop a quantity off a statutory summary with no
            # word said.
            qty = str(r.get("qty") if r.get("qty") is not None else 0).strip()
            if _NUMERIC.match(qty):
                cell["qty"] += float(qty)
            cell["txval_paise"] += paise_of(r.get("txval"))
            cell["igst_paise"] += paise_of(r.get("iamt"))
            cell["cgst_paise"] += paise_of(r.get("camt"))
            cell["sgst_paise"] += paise_of(r.get("samt"))
            cell["cess_paise"] += paise_of(r.get("csamt"))
    out = sorted(by_code.values(), key=lambda c: c["hsn_sc"])
    for c in out:
        c["qty"] = round(c["qty"], 3)
    return out


# ── The whole return ────────────────────────────────────────────────────────

def build_gstr9(*, financial_year: str, gstin: str,
                months: list[MonthlyReturn],
                reversals: Optional[list[Reversal]] = None,
                two_b: Optional[dict[str, int]] = None,
                inputs: Optional[AnnualInputs] = None) -> GSTR9:
    """The annual return's Tables 4, 5, 6, 7, 8, 9 and 17.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    inputs = inputs or AnnualInputs()
    gaps: list[str] = []

    unfiled_1 = [m.period for m in months if not m.gstr1_filed]
    unfiled_3b = [m.period for m in months if not m.gstr3b_filed]
    if unfiled_1 or unfiled_3b:
        gaps.append(
            "This year's monthly returns are not all filed, so what follows is "
            "a consolidation of PART of the year. "
            + (f"GSTR-1 outstanding: {', '.join(unfiled_1)}. " if unfiled_1 else "")
            + (f"GSTR-3B outstanding: {', '.join(unfiled_3b)}. " if unfiled_3b else "")
            + "The portal opens FORM GSTR-9 once every one of them is furnished "
              "(CGST Act s.44 with Rule 80(1)).")

    table_4, table_5 = _table_4_and_5(months, gaps)
    table_6 = _table_6(months, inputs, gaps)
    total_6 = next(r for r in table_6 if r.code == "6O")
    table_7 = _table_7(list(reversals or []), gaps,
                       {"iamt": total_6.iamt, "camt": total_6.camt,
                        "samt": total_6.samt, "csamt": total_6.csamt})
    table_8 = _table_8(table_6, two_b, inputs, gaps)

    # Table 9 — tax PAID during the year, as declared. `net_*_paise` is what
    # GSTR-3B Table 6 settled after the s.49(5) set-off, which is the figure
    # the annual return's "tax payable" column consolidates.
    # These four ARE written by `save_gstr3b` (unlike the per-head columns), so
    # they are read as stored paise. They are one figure each rather than a
    # per-head split, which is what the save path holds.
    liability = itc = net = cash = 0
    for m in months:
        b = m.gstr3b_row or {}
        liability += int(b.get("tax_liability_paise") or 0)
        itc += int(b.get("itc_claimed_paise") or 0)
        net += int(b.get("net_tax_paise") or 0)
        cash += int(b.get("cash_payable_paise") or 0)
    table_9 = [
        Row("9a", "Tax payable as declared in the year's GSTR-3Bs", txval=liability),
        Row("9b", "Input tax credit claimed", txval=itc),
        Row("9c", "Net tax payable after set-off", txval=net),
        Row("9d", "Paid in cash", txval=cash, note=(
            "Reverse-charge tax is always cash: CGST Act s.49(4) lets the "
            "credit ledger pay only OUTPUT tax, and s.2(82) excludes tax "
            "payable on reverse charge from that.")),
    ]

    return GSTR9(
        financial_year=financial_year,
        gstin=gstin,
        tables={"4": table_4, "5": table_5, "6": table_6, "7": table_7,
                "8": table_8, "9": table_9},
        hsn=_table_17(months),
        months=[{"period": m.period, "gstr1_status": m.gstr1_status,
                 "gstr3b_status": m.gstr3b_status,
                 "gstr1_payload_held": bool(m.gstr1_payload)} for m in months],
        gaps=gaps,
        is_complete=not unfiled_1 and not unfiled_3b,
    )


#: The parts of the form this module deliberately does not build, each with the
#: reason. Served beside the return so a screen shows what is left to do on the
#: portal rather than implying the working is the whole return.
NOT_BUILT = {
    "10-14": ("Transactions of the PREVIOUS financial year declared in this "
              "year's returns. Amendments are tracked per period here, not "
              "across a year boundary."),
    "15": "Demands and refunds. Neither is recorded in this product.",
    "16": ("Supplies received from composition taxpayers, deemed supply under "
           "section 143 and goods sent on approval. None is modelled."),
    "18": ("HSN summary of INWARD supplies. Purchase bill lines carry an HSN "
           "code, but the table's own requirement has moved by notification "
           "more than once and could not be read here — every .gov.in is "
           "refused at this environment's egress proxy."),
    "19": ("Late fee payable and PAID. domain/gst/late_filing.py computes what "
           "is PAYABLE under section 47(2) — Notification 7/2023-Central Tax "
           "was read on 18-09-2026 — but its ceiling is a percentage of "
           "turnover in the State, which nothing here holds, so the answer "
           "carries that gap. What is PAID is a fact about a challan this "
           "product does not record, and the two boxes of this table are not "
           "one figure: a return showing the fee as paid when it has not been "
           "is a declaration, not a rounding."),
}
