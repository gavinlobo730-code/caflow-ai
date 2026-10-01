"""
Does the GSTR-3B this product built say what the filed GSTR-1 said? (GST-07)

WHAT WAS WRONG

    From the JULY 2025 tax period the outward tables of GSTR-3B — 3.1(a), (b),
    (c), (e) and 3.2 — are filled in BY THE PORTAL from the period's GSTR-1,
    GSTR-1A or IFF and cannot be edited (GSTN advisory 606 of 07-06-2025; the
    filing walk-through in `services/filing_demo/gstr1.py` carries the same
    citation). This product builds the same figures from the BOOKS. So an
    invoice raised after the GSTR-1 was filed makes the books-built 3B differ
    from the 3B the portal will show — and the CA finds that out while filing,
    when the only remaining routes are GSTR-1A (before the 3B is filed) or a
    later period's amendment tables.

    Nothing in the real path compared the two. `gst_exception_service` does,
    but it compares the books against the filed GSTR-1 DOCUMENT BY DOCUMENT and
    is reachable only from the Amendments tab — a CA preparing the 3B never
    opens it.

WHAT THIS DOES

    It reads the OUTWARD figures a filed GSTR-1 declared, reads the same
    figures off the GSTR-3B build, and reports each difference in integer paise
    with its CAUSE. It reports and changes nothing: neither return is adjusted,
    no amendment is drafted, nothing is filed. # CA REVIEW REQUIRED.

THE COMPARISON IS DELIBERATELY COARSER THAN THE PORTAL'S OWN ROW SPLIT

    It compares 3.1(a) and 3.1(b) TOGETHER — the taxable value and the four tax
    heads of every outward supply the return declares as taxable or
    zero-rated — plus 3.1(c) and 3.1(e) as values. Two things force that:

      * A credit or debit note carries no marker in the GSTR-1 payload of what
        its parent was. The 3B build inherits that from the parent invoice
        (CGST §34), so a note against an SEZ supply is 3.1(b) on one side and
        indistinguishable on the other.
      * Which of 3.1(a) and 3.1(b) a DEEMED EXPORT lands in on the portal could
        not be confirmed here (every `.gov.in` is refused at this
        environment's proxy), and this product's own classifier calls it
        zero-rated while `gstr9_builder` documents the same supply as part of
        3.1(a). The two rows together are right whichever it is, and a split
        that was wrong would put a false difference on the screen of every
        client with a deemed export.

    Output tax per head is the figure the CA PAYS, so it is the one that has to
    be right; the row split would add a rupee-for-rupee error source and no
    information.

WHAT IS HELD OUT, AND NAMED

      * OUTWARD SUPPLIES THE RECIPIENT PAYS TAX ON (`rchrg` = "Y"). The 3B
        build leaves them out of 3.1(a) (`compute_gstr3b` accumulates a taxable
        supply only where it is not reverse charge) and whether the portal does
        the same could not be confirmed. They are reported in `held_out`, never
        folded into either side, so a difference they cause is visible as such.
      * AMENDMENTS. A GSTR-1 saved with its amendment tables (9A, 9C, 10)
        carries corrections to EARLIER periods, which the portal nets into 3.1
        and the books-built 3B does not. The sections are NAMED where the filed
        payload holds any; their effect is not part of the comparison.
      * GSTR-1A AND IFF. Neither is held, and either could already have closed
        a difference on the portal. Said on every answer.

WHAT IS NOT IN GSTR-1 AT ALL

    Two kinds of outward supply reach the books-built 3B and can never reach a
    GSTR-1: a bank receipt the CA marked as carrying GST (BANK-24) and the sale
    of a fixed asset (FA-08b) — neither has a tax invoice behind it. They are
    subtracted before the remainder is attributed, so a client who uses either
    feature does not get a permanent "difference" that no filing can close.
    Which means the portal's 3.1(a) will NOT show them, and that is said too.

⚠️  GRADING. The July 2025 lock and the GSTR-1A mechanics are `[S]` — secondary
    sources and the repo's own filing walk-through, nothing read off the
    advisory itself — so `VERIFIED` is False and both are named constants, not
    inline literals. The comparison arithmetic is not `[S]`: it is a total of
    figures this product computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from domain.gst import amendments as _amendments
from domain.gst.gstr9_builder import paise_of

#: Everything below that reads as a statutory claim about the PORTAL is written
#: from secondary sources. The arithmetic is not.
VERIFIED = False

#: The first tax period whose GSTR-3B outward tables the portal fills in and
#: locks (GSTN advisory 606, 07-06-2025). `[S]`. A period before it keeps the
#: editable form, so a difference there is still a mismatch the department can
#: see but is not one the portal will overwrite.
OUTWARD_TABLES_LOCKED_FROM = "2025-07-01"

ADVISORY_606 = "GSTN advisory 606 of 07-06-2025"

#: The only route that changes what the portal puts in a locked 3.1 BEFORE the
#: 3B is filed. Optional (Notification 12/2024-Central Tax, 10-07-2024), opens
#: once the period's GSTR-1 is filed and closes when its GSTR-3B is. `[S]`,
#: from `services/filing_demo/gstr1.py`.
GSTR_1A_ROUTE = (
    "GSTR-1A for this period — the only route that changes what the portal "
    "puts in Table 3.1 before the GSTR-3B is filed. It opens once this "
    "period's GSTR-1 is filed and closes the moment its GSTR-3B is "
    "(Notification 12/2024-Central Tax; [S]-graded here)."
)
AMENDMENT_ROUTE = (
    "A later period's GSTR-1: an invoice the filed return never carried is "
    "declared in that return's ordinary tables, and a filed entry that has "
    "changed is corrected in its amendment tables (9A, 9C or 10) — CGST Act "
    "§37(3), inside the window `correction_window` reports."
)
NOT_EDITABLE = (
    "On the portal these rows are not editable, so the GSTR-3B cannot simply "
    "be typed to agree with this build."
)

#: What the comparison could not see, said on every answer rather than only
#: where it happened to matter.
NOT_HELD = (
    "A GSTR-1A or an IFF filed on the portal is not held here, and either "
    "could already have changed what the portal shows in Table 3.1 for this "
    "period."
)

NOT_FILED = (
    "This period's GSTR-1 has not been filed, so the portal has nothing to "
    "fill Table 3.1 from yet and there is nothing to compare this build "
    "against. That is not the same as the two agreeing."
)
PAYLOAD_MISSING = (
    "This period's GSTR-1 was marked filed before the submitted payload was "
    "recorded, so there is nothing to compare this build against. A "
    "difference between the two cannot be detected automatically for this "
    "period."
)

#: The figures every row carries. Value first, then the four tax heads.
FIGURE_KEYS = ("taxable_value_paise", "igst_paise", "cgst_paise", "sgst_paise",
               "cess_paise")
TAX_KEYS = ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise")

#: GSTR-1's own amendment sections. Read from `domain/gst/amendments` so a
#: section added there cannot be missed here.
AMENDMENT_SECTIONS = tuple(_amendments.SECTION_TABLE)
#: Table 11's amendment pair, which `amendments.SECTION_TABLE` does not carry.
_ADVANCE_AMENDMENT_SECTIONS = ("ata", "txpda")


def _blank() -> dict[str, int]:
    return {k: 0 for k in FIGURE_KEYS}


def _add(into: dict[str, int], other: dict[str, int], sign: int = 1) -> None:
    for k in FIGURE_KEYS:
        into[k] += sign * int(other.get(k, 0))


def _heads_of(det: Optional[dict]) -> dict[str, int]:
    """One GSTN item's five figures, rupees back to exact paise.

    `gstr9_builder.paise_of` — `Decimal(str(v))`, never `int(v * 100)`: in
    binary floating point 8.29 * 100 is 828.9999999999999, so the multiplication
    loses a paisa on some values only, and a comparison that is a paisa out on
    the figures it is built to compare is worse than none.
    """
    det = det or {}
    return {"taxable_value_paise": paise_of(det.get("txval")),
            "igst_paise": paise_of(det.get("iamt")),
            "cgst_paise": paise_of(det.get("camt")),
            "sgst_paise": paise_of(det.get("samt")),
            "cess_paise": paise_of(det.get("csamt"))}


def _items(itms: Optional[Iterable[dict]]) -> dict[str, int]:
    """A document's `itms` array (one `itm_det` per rate), summed."""
    out = _blank()
    for item in itms or []:
        _add(out, _heads_of((item or {}).get("itm_det")))
    return out


def _advance_items(rows: Optional[Iterable[dict]]) -> dict[str, int]:
    """Table 11's rows — a DIFFERENT shape from every other table.

    `at` / `txpd` carry `itms` of `{rt, ad_amt, iamt, camt, samt, csamt}` with
    NO `itm_det` wrapper and the taxable value under `ad_amt`
    (`gst_advance_service._table_11_rows`). Reading them with `_items` returns
    a confident nil.
    """
    out = _blank()
    for row in rows or []:
        row = row or {}
        for it in row.get("itms") or []:
            it = it or {}
            out["taxable_value_paise"] += paise_of(it.get("ad_amt") or row.get("ad_amt"))
            out["igst_paise"] += paise_of(it.get("iamt"))
            out["cgst_paise"] += paise_of(it.get("camt"))
            out["sgst_paise"] += paise_of(it.get("samt"))
            out["cess_paise"] += paise_of(it.get("csamt"))
    return out


@dataclass
class Gstr1Outward:
    """What a GSTR-1 payload declared on the outward side, in paise."""
    #: 3.1(a) + 3.1(b): every taxable and zero-rated outward supply, notes
    #: netted, Table 11 advances applied.
    taxable_and_zero_rated: dict = field(default_factory=_blank)
    #: 3.1(c) — Table 8's nil-rated and exempted.
    nil_rated_and_exempt_paise: int = 0
    #: 3.1(e) — Table 8's non-GST.
    non_gst_paise: int = 0
    #: Outward supplies on which the RECIPIENT pays tax (`rchrg` = "Y"), kept
    #: OUT of the combined row — see the module header.
    held_out_reverse_charge: dict = field(default_factory=_blank)
    #: Amendment sections the payload carries, which are not in the comparison.
    amendment_sections: list = field(default_factory=list)


def read_gstr1_outward(payload: Optional[dict]) -> Gstr1Outward:
    """The outward figures a GSTR-1 payload declared.

    Used on BOTH the filed payload and the one rebuilt from the books, so a
    quirk of the reading applies to each side alike and cannot show up as a
    difference.
    """
    payload = payload or {}
    out = Gstr1Outward()

    def bucket(is_reverse_charge: bool) -> dict:
        return out.held_out_reverse_charge if is_reverse_charge else out.taxable_and_zero_rated

    # Tables 4A / 4B / 6B / 6C — all inside `b2b`, told apart by `inv_typ`.
    for grp in payload.get("b2b") or []:
        for inv in (grp or {}).get("inv") or []:
            _add(bucket(str((inv or {}).get("rchrg") or "N").upper() == "Y"),
                 _items((inv or {}).get("itms")))
    # Table 5 and Table 7 — B2C. `b2cs` rows carry the figures flat.
    for grp in payload.get("b2cl") or []:
        for inv in (grp or {}).get("inv") or []:
            _add(out.taxable_and_zero_rated, _items((inv or {}).get("itms")))
    for row in payload.get("b2cs") or []:
        _add(out.taxable_and_zero_rated, _heads_of(row))
    # Table 6A — exports.
    for grp in payload.get("exp") or []:
        for inv in (grp or {}).get("inv") or []:
            _add(out.taxable_and_zero_rated, _items((inv or {}).get("itms")))
    # Table 9B — a credit note SUBTRACTS and a debit note adds (CGST §34).
    for grp in payload.get("cdnr") or []:
        for nt in (grp or {}).get("nt") or []:
            sign = -1 if str((nt or {}).get("ntty") or "").upper() == "C" else 1
            _add(bucket(str((nt or {}).get("rchrg") or "N").upper() == "Y"),
                 _items((nt or {}).get("itms")), sign)
    for nt in payload.get("cdnur") or []:
        sign = -1 if str((nt or {}).get("ntty") or "").upper() == "C" else 1
        _add(out.taxable_and_zero_rated, _items((nt or {}).get("itms")), sign)
    # Table 11 — advances received less advances adjusted (CGST §13(2)). Both
    # halves, or an invoice that consumes an earlier advance is charged twice.
    _add(out.taxable_and_zero_rated, _advance_items(payload.get("at")))
    _add(out.taxable_and_zero_rated, _advance_items(payload.get("txpd")), -1)

    # Table 8.
    nil = payload.get("nil") or {}
    for row in (nil.get("inv") if isinstance(nil, dict) else nil) or []:
        row = row or {}
        out.nil_rated_and_exempt_paise += (paise_of(row.get("nil_amt"))
                                           + paise_of(row.get("expt_amt")))
        out.non_gst_paise += paise_of(row.get("ngsup_amt"))

    out.amendment_sections = sorted(
        s for s in (*AMENDMENT_SECTIONS, *_ADVANCE_AMENDMENT_SECTIONS)
        if payload.get(s))
    return out


# ── The GSTR-3B side ─────────────────────────────────────────────────────────

@dataclass
class Gstr3bOutward:
    """The books-built 3B's outward figures, in paise — taken off the
    `GSTR3BResult` the build already computed, never re-derived."""
    taxable_and_zero_rated: dict = field(default_factory=_blank)
    nil_rated_and_exempt_paise: int = 0
    non_gst_paise: int = 0


def read_gstr3b_outward(result: Any) -> Gstr3bOutward:
    """3.1(a)+(b), (c) and (e) off a `GSTR3BResult`.

    Zero-rated IGST is the tax on a supply made ON PAYMENT of tax (IGST Act
    §16(3)(b)); an LUT or bond supply carries none. Cess is accumulated on the
    taxable line only, which is how the build declares it.
    """
    return Gstr3bOutward(
        taxable_and_zero_rated={
            "taxable_value_paise": (int(result.outward_taxable_value)
                                    + int(result.outward_zero_rated)),
            "igst_paise": (int(result.outward_taxable_igst)
                           + int(result.outward_zero_rated_igst)),
            "cgst_paise": int(result.outward_taxable_cgst),
            "sgst_paise": int(result.outward_taxable_sgst),
            "cess_paise": int(result.outward_taxable_cess),
        },
        nil_rated_and_exempt_paise=int(result.outward_nil_exempt),
        non_gst_paise=int(result.outward_non_gst),
    )


def books_only_figures(sales: Iterable[Any]) -> dict[str, int]:
    """The outward supplies the 3B build declares that no GSTR-1 can carry.

    A bank receipt marked as carrying GST (BANK-24) and an asset disposal
    (FA-08b): both are real output tax in the ledger and on the return, and
    neither has a tax invoice behind it (CGST Rule 46), so neither is in any
    GSTR-1. Filtered on the transaction's own type — the same field
    `compute_gstr3b` reads — rather than recomputed from the bank and asset
    tables, so what is named here is exactly what the build counted.
    """
    out = _blank()
    for s in sales:
        if getattr(s, "transaction_type", "") not in ("bank_receipt", "asset_disposal"):
            continue
        if getattr(s, "supply_type", "taxable") != "taxable" or getattr(s, "is_reverse_charge", False):
            continue
        out["taxable_value_paise"] += int(s.taxable_amount_paise)
        out["igst_paise"] += int(s.igst_paise)
        out["cgst_paise"] += int(s.cgst_paise)
        out["sgst_paise"] += int(s.sgst_paise)
        out["cess_paise"] += int(s.cess_paise)
    return out


# ── The comparison ───────────────────────────────────────────────────────────

MATCHED = "matched"
DIFFERS = "differs"


def _row(code: str, label: str, filed: dict, books: dict, keys: tuple) -> dict:
    figures = {}
    for k in keys:
        f, b = int(filed.get(k, 0)), int(books.get(k, 0))
        figures[k] = {"gstr1_filed": f, "books_3b": b, "difference": b - f}
    return {
        "code": code,
        "label": label,
        "figures": figures,
        "state": (MATCHED if all(v["difference"] == 0 for v in figures.values())
                  else DIFFERS),
    }


def compare(filed: Gstr1Outward, books: Gstr3bOutward) -> dict:
    """books minus filed, row by row. Positive: the books-built 3B declares MORE
    than the filed GSTR-1 did."""
    rows = [
        _row("3.1(a)+(b)",
             "Outward taxable and zero-rated supplies (3.1(a) and 3.1(b) together)",
             filed.taxable_and_zero_rated, books.taxable_and_zero_rated,
             FIGURE_KEYS),
        _row("3.1(c)", "Nil-rated and exempted outward supplies",
             {"value_paise": filed.nil_rated_and_exempt_paise},
             {"value_paise": books.nil_rated_and_exempt_paise}, ("value_paise",)),
        _row("3.1(e)", "Non-GST outward supplies",
             {"value_paise": filed.non_gst_paise},
             {"value_paise": books.non_gst_paise}, ("value_paise",)),
    ]
    return {"rows": rows,
            "tied": all(r["state"] == MATCHED for r in rows)}


def tax_difference(rows: list[dict]) -> dict[str, int]:
    """The four tax heads' difference on the combined row, signed."""
    combined = rows[0]["figures"]
    return {k: int(combined[k]["difference"]) for k in TAX_KEYS}


# ── Attributing a difference ─────────────────────────────────────────────────

def _delta(a: dict, b: dict) -> dict[str, int]:
    return {k: int(a.get(k, 0)) - int(b.get(k, 0)) for k in FIGURE_KEYS}


def attribute(*, filed: Gstr1Outward, books_3b: Gstr3bOutward,
              books_only: dict, books_now: Optional[Gstr1Outward],
              exception_report: Optional[dict],
              books_gstr1_gaps: Optional[list] = None) -> dict:
    """Split the combined row's difference into what explains it.

    The books-built 3B equals, by construction,

        GSTR-1 as the books would build it NOW
        + supplies no GSTR-1 can carry          (bank receipts, disposals)
        + whatever the two builders disagree on (the REMAINDER)

    and the GSTR-1 as the books would build it now differs from the one filed by
    DRIFT — documents raised, edited or cancelled since. So

        books_3b - filed  =  drift  +  books_only  +  remainder.

    Three figures, each in the four tax heads and the value, signed; the last is
    NOT assumed to be zero, because the two builders classify a few documents
    differently (an intra-state note to an unregistered person has no row in
    GSTR-1 Table 9B and the 3B nets it; see `payload_gaps`) and an attribution
    that forced the remainder into one of the other two would be a guess.
    """
    total = _delta(books_3b.taxable_and_zero_rated, filed.taxable_and_zero_rated)
    if books_now is None:
        # The rebuild failed or was not asked for. Nothing can be said about
        # drift, and saying the whole of it is "unexplained" is true.
        drift = _blank()
    else:
        drift = _delta(books_now.taxable_and_zero_rated,
                       filed.taxable_and_zero_rated)
    only = {k: int(books_only.get(k, 0)) for k in FIGURE_KEYS}
    remainder = {k: total[k] - drift[k] - only[k] for k in FIGURE_KEYS}

    report = exception_report or {}
    docs = report.get("documents") or {}
    drift_documents = {
        "missing_from_return": list(docs.get("missing_from_return") or []),
        "missing_from_books": list(docs.get("missing_from_books") or []),
        "amount_changed": list(docs.get("amount_changed") or []),
        "reclassified": list(docs.get("reclassified") or []),
        "b2cs_changed": list((report.get("b2cs") or {}).get("changed") or []),
    }
    held_out_of_gstr1 = [
        {"kind": g.get("kind"), "reference_no": g.get("reference_no"),
         "reason": g.get("reason")}
        for g in (books_gstr1_gaps or []) if g.get("withheld", False)
    ]
    return {
        "total": total,
        "drift": drift,
        "books_only": only,
        "remainder": remainder,
        "drift_documents": drift_documents,
        "held_out_of_gstr1": held_out_of_gstr1,
    }


def routes_for(*, portal_locks_outward: bool, gstr3b_filed: Optional[bool],
               drift_documents: dict) -> list[str]:
    """What a CA can DO about a difference, in the order the portal allows.

    The route depends on two facts and neither is a guess: whether the portal
    locks this period's outward tables, and whether the period's GSTR-3B is
    already filed (GSTR-1A closes the moment it is). An unknown 3B state shows
    BOTH routes rather than choosing — the `itc_04_period` posture.
    """
    steps: list[str] = []
    if portal_locks_outward:
        steps.append(NOT_EDITABLE)
        if gstr3b_filed is True:
            steps.append("This period's GSTR-3B is recorded as filed, so "
                         "GSTR-1A has closed. " + AMENDMENT_ROUTE)
        elif gstr3b_filed is False:
            steps.append(GSTR_1A_ROUTE + " " + AMENDMENT_ROUTE
                         + " (the second only if GSTR-1A is not used)")
        else:
            steps.append(GSTR_1A_ROUTE + " Whether this period's GSTR-3B has "
                         "been filed is not recorded here — if it has, "
                         "GSTR-1A has closed. " + AMENDMENT_ROUTE)
    else:
        steps.append(
            "This period precedes the July 2025 lock, so its GSTR-3B outward "
            "tables are editable on the portal. The difference is still one "
            "the department can see against the GSTR-1, so decide which return "
            "is right first. If it is the GSTR-3B, " + AMENDMENT_ROUTE)
    if drift_documents.get("missing_from_return"):
        steps.append("Invoices in the books and not in the filed GSTR-1 are "
                     "declared in the ORDINARY tables of the return that "
                     "carries them — there is no filed entry to amend.")
    if any(drift_documents.get(k) for k in
           ("amount_changed", "reclassified", "missing_from_books", "b2cs_changed")):
        steps.append("A filed entry that has changed, or that is no longer in "
                     "the books, is corrected in the amendment tables — each "
                     "document below names the one (9A, 9C or 10).")
    return steps


def locks_outward(period_start: str) -> bool:
    """Is the period on or after the portal's July 2025 lock? `[S]`."""
    return (period_start or "")[:10] >= OUTWARD_TABLES_LOCKED_FROM
