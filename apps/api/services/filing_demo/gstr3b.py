"""GSTR-3B filing demo — the summary return, and the only one that PAYS.

THE REAL CHANNEL THIS MIMICS
    gst.gov.in → Returns Dashboard → GSTR-3B → Prepare Online → SAVE →
    PREVIEW DRAFT → the form's tables in its own order (3.1 outward supplies,
    4 eligible ITC, 5.1 interest and late fee) → PROCEED TO PAYMENT, which is
    Table 6.1: set the liability off against the electronic credit ledger and
    pay whatever is left in cash → PROCEED TO FILE → the declaration and the
    authorised signatory → FILE WITH DSC / FILE WITH EVC → emSigner or an OTP
    to the signatory's registered mobile and email → ARN.

    THE PAYMENT STEP IS WHY THIS FLOW EXISTS. GSTR-1 declares outward supplies
    and pays nothing; GSTR-3B is where the liability is discharged (CGST Act
    §39 with §49), and Table 6.1 is the screen the CA actually makes a decision
    on — how much of the liability the credit ledger covers, and how much has
    to be found in cash by challan (PMT-06) before the return can be filed at
    all. Flattening that into a single "net tax" figure hides the decision,
    which is exactly what a CA comes to this walk-through to see.

    Software may not transmit this today: GSTN's filing APIs are reachable only
    through a GST Suvidha Provider (a commercial registration, not a coding
    step). The demo says so in real_channel.

TABLE 4, AS THE PORTAL HAS LAID IT OUT SINCE 01-09-2022
    Notification 14/2022-Central Tax read with Circular 170/02/2022-GST:

      4(A)     GROSS. It is auto-populated from GSTR-2B, so blocked credit
               stays IN it — netting §17(5) out of 4(A) breaks the tie-up with
               the portal's own 2B figure, which is the mismatch that draws a
               notice.
      4(B)(1)  reversals "absolute in nature and not reclaimable" — CGST Rules
               38/42/43 and CGST Act §17(5).
      4(B)(2)  the reclaimable ones — Rule 37/37A, §16(2)(b) and (c).
      4(C)   = 4(A) − 4(B). §17(5) sits in 4(B)(1) and is NOT repeated in 4(D).

    domain/gst/gstr3b_computer.py carries the circular's wording and is the
    authority. This module computes nothing: it displays what the saved return
    already worked out.

TABLE 6 SETS OFF 4(C), NEVER 4(A)
    CGST Act §49(4) permits payment only out of credit available in the
    electronic credit ledger, and credit reversed in this very return is not
    available. Offering 4(A) as the credit that pays the tax is the classic
    error: it understates the cash the client has to find by the whole of the
    reversal, and the shortfall is discovered as interest under §50.

ref: {"return_id": <gstr3b_returns.id>} — the saved return the CA is walking
through. It must be ca_approved: the walk-through starts where filing does.
Read-only end to end — this module performs no write of any kind.
"""
from __future__ import annotations

from services.filing_demo import common

# The three tax heads, in the form's own order. Cess has no line in the saved
# working's Table 4 or Table 6 views, so it is not invented here.
_HEADS = (("IGST", "igst"), ("CGST", "cgst"), ("SGST", "sgst"))


def _p(d, key: str) -> int:
    """One paise figure out of a saved working sub-dict. Integer paise only —
    a missing key is 0, never None and never a float."""
    return int((d or {}).get(key) or 0)


def _due_date(client_id: str, firm_id: str, period: str) -> str:
    """GSTR-3B's due date for this period, from the single authority.

    services/compliance_engine.py::gstr3b_due_date is the only place any GST
    due date is stated in this codebase, and it is not restated here: the 20th
    is a MONTHLY filer's date, and a QRMP filer (Rule 61A) is due the 22nd or
    24th of the month following the QUARTER depending on their state. Quoting
    the wrong one is not a display bug — §47 charges ₹50 a day.

    Returns "" rather than raising: a malformed period costs the walk-through
    its due-date line, not the walk-through.
    """
    try:
        from services.compliance_engine import gstr3b_due_date
        from services.compliance_obligation_service import gst_profile_for
        frequency, state_code = gst_profile_for(client_id, firm_id)
        return gstr3b_due_date(int(period[2:]), int(period[:2]),
                               frequency, state_code).isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


def _correction_window(period: str) -> str:
    """When this period stops being correctable at all, per
    compliance_engine.correction_window_closes (CGST §37(3)/§39(9)/§16(4)).

    Never november_30_cutoff: that is only the statutory outer limit, and on
    its own it tells a CA a correction is available when the client's early
    GSTR-9 has already shut the window. The prose beside this date carries the
    "whichever is EARLIER" half, which is the part that bites.
    """
    try:
        from services.compliance_engine import correction_window_closes
        month, year = int(period[:2]), int(period[2:])
        # Financial year is April to March, so a period in Jan–Mar belongs to
        # the FY that ENDS in its own calendar year.
        fy_end = year + 1 if month >= 4 else year
        return correction_window_closes(fy_end).isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"return_id": <gstr3b_returns.id>} — see the module docstring.

    Read-only: one select, no writes of any kind. Every figure below is an
    integer paise value read straight off the saved return.
    """
    return_id = str(ref.get("return_id") or "")
    if not return_id:
        raise ValueError("gstr3b demo needs ref.return_id")

    rows = (db.table("gstr3b_returns").select("*")
            .eq("id", return_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("GSTR-3B return not found")
    rec = rows[0]

    # The same gate the screen applies, and for the same reason: filing starts
    # from an approved return. A submitted one already carries its real ARN and
    # the filing record the period lock reads, so walking it through a
    # ceremony that ends in a specimen ARN would be actively confusing.
    status = str(rec.get("status") or "")
    if status == "submitted":
        raise ValueError(
            "This GSTR-3B is already recorded as filed, with its real ARN — "
            "there is nothing left to walk through.")
    if status != "ca_approved":
        raise ValueError(
            f"This GSTR-3B is still '{status or 'unsaved'}'. The walk-through "
            "starts where filing does — from a CA-approved return.")

    period = str(rec.get("period") or "")
    gstin = str(rec.get("gstin") or "")

    # summary_json is what gst_return_service.gstr3b_from_books called
    # `working`: the return's table-by-table figures in paise. A return created
    # by hand from the + New GSTR-3B form has none, which costs the tables
    # their per-head detail and nothing else.
    working = rec.get("summary_json") or {}
    outward = working.get("outward") or {}
    rcm = working.get("rcm_inward") or {}
    itc = working.get("itc") or {}
    reversal = working.get("itc_reversal") or {}
    permanent = reversal.get("permanent_paise") or {}
    reclaimable = reversal.get("reclaimable_paise") or {}
    net_payable = working.get("net_payable") or {}
    utilisation = working.get("itc_utilisation") or {}

    liability = int(rec.get("tax_liability_paise") or 0)
    itc_claimed = int(rec.get("itc_claimed_paise") or 0)
    net_tax = int(rec.get("net_tax_paise") or 0)
    carried_forward = _p(utilisation, "carried_forward_paise")

    due = _due_date(client_id, firm_id, period)
    window_closes = _correction_window(period)

    # ── Stage 1: the saved return, as the portal shows it ────────────────────
    note = ("On the portal this is the saved return, after Prepare Online and "
            "Save, with a Preview Draft PDF beside it.")
    if not working:
        note += (" This return was saved without its table-by-table working, "
                 "so the per-head tables that follow are nil — the header "
                 "figures above are all it carries, and nothing is invented "
                 "to fill the gap.")

    figures = [
        {"label": "Tax liability (Table 3.1)", "paise": liability},
        # 4(C), not 4(A) — see the module docstring. This is what the return
        # claims, and what Table 6.1 below is allowed to spend.
        {"label": "ITC claimed (Table 4(C))", "paise": itc_claimed},
        {"label": "Net tax payable in cash (Table 6)", "paise": net_tax},
        {"label": "Credit carried forward", "paise": carried_forward},
    ]
    if due:
        figures.append({"label": "Due date (CGST Act §39)", "text": due})

    stages = [
        common.summary_stage(
            f"GSTR-3B · {period}", note, figures, cta="Proceed"),
    ]

    # ── Stage 2: Table 3.1 ───────────────────────────────────────────────────
    # Rows (a)–(d) of the form. (e) non-GST outward supplies is not tracked
    # upstream, so it is absent rather than shown as a nil the books did not
    # actually assert. A dash means "this line carries no figure of that kind"
    # — zero-rated and exempt supplies bear no output tax, and the taxable
    # value behind reverse-charge inward supplies is not part of this working.
    dash = {"text": "—"}
    stages.append(common.table_stage(
        "Table 3.1 — Outward supplies and inward supplies liable to reverse charge",
        "Declared under CGST Act §39. 3.1(d) is tax the RECIPIENT self-assesses "
        "under §9(3)/(4) and pays in cash — §49(4) does not let the credit "
        "ledger discharge it — and the credit for it comes back in Table "
        "4(A)(3).",
        ["", "Taxable value", "IGST", "CGST", "SGST"],
        [
            [{"text": "(a) Outward taxable supplies (other than zero rated, "
                      "nil rated and exempted)"},
             {"paise": _p(outward, "taxable_value_paise")},
             {"paise": _p(outward, "taxable_igst_paise")},
             {"paise": _p(outward, "taxable_cgst_paise")},
             {"paise": _p(outward, "taxable_sgst_paise")}],
            [{"text": "(b) Outward taxable supplies (zero rated)"},
             {"paise": _p(outward, "zero_rated_paise")}, dash, dash, dash],
            [{"text": "(c) Other outward supplies (nil rated, exempted)"},
             {"paise": _p(outward, "nil_exempt_paise")}, dash, dash, dash],
            [{"text": "(d) Inward supplies (liable to reverse charge)"},
             dash,
             {"paise": _p(rcm, "igst_paise")},
             {"paise": _p(rcm, "cgst_paise")},
             {"paise": _p(rcm, "sgst_paise")}],
        ],
    ))

    # ── Stage 3: Table 4 ─────────────────────────────────────────────────────
    # The layout Notification 14/2022 with Circular 170/02/2022-GST put on the
    # portal from 01-09-2022. 4(C) is the FOOTER because it is the total line
    # the rows above add up to, and because it is the only figure Table 6.1 is
    # allowed to spend.
    stages.append(common.table_stage(
        "Table 4 — Eligible ITC",
        "Notification 14/2022-Central Tax with Circular 170/02/2022-GST, live "
        "on the portal from 01-09-2022. 4(A) is GROSS — the portal "
        "auto-populates it from GSTR-2B, so blocked credit stays in it and "
        "netting §17(5) out would break the tie-up. §17(5) is declared in "
        "4(B)(1) and is NOT repeated in 4(D).",
        ["", "IGST", "CGST", "SGST"],
        [
            [{"text": "4(A) ITC available (gross, as auto-populated from GSTR-2B)"},
             {"paise": _p(itc, "avail_igst_paise")},
             {"paise": _p(itc, "avail_cgst_paise")},
             {"paise": _p(itc, "avail_sgst_paise")}],
            [{"text": "4(B)(1) ITC reversed — absolute, not reclaimable "
                      "(Rules 38/42/43, §17(5))"},
             {"paise": _p(permanent, "igst_paise")},
             {"paise": _p(permanent, "cgst_paise")},
             {"paise": _p(permanent, "sgst_paise")}],
            [{"text": "4(B)(2) ITC reversed — reclaimable "
                      "(Rule 37/37A, §16(2)(b)/(c))"},
             {"paise": _p(reclaimable, "igst_paise")},
             {"paise": _p(reclaimable, "cgst_paise")},
             {"paise": _p(reclaimable, "sgst_paise")}],
        ],
        footer=[{"text": "4(C) Net ITC available (4A − 4B)"},
                {"paise": _p(itc, "net_igst_paise")},
                {"paise": _p(itc, "net_cgst_paise")},
                {"paise": _p(itc, "net_sgst_paise")}],
    ))

    # ── Stage 4: Table 5.1 ───────────────────────────────────────────────────
    # Nil in the prepared return, and said so plainly. PracticeSync does not
    # compute §50 interest or §47 late fee, and showing a figure it did not
    # compute would be worse than showing the nil with an explanation.
    interest_note = ("PracticeSync does not compute §50 interest or §47 late "
                     "fee, so both are nil in the prepared return and the "
                     "portal's own figures govern. Both are payable in CASH: "
                     "§49(4) lets the credit ledger pay output tax only, and "
                     "interest and fee are neither.")
    if due:
        interest_note += f" Late fee runs from this return's due date, {due}."
    stages.append(common.table_stage(
        "Table 5.1 — Interest and late fee",
        interest_note,
        ["", "In this return", "Who fills it on the portal"],
        [
            [{"text": "Interest (CGST Act §50)"}, {"paise": 0},
             {"text": "Declared by the taxpayer; the portal offers a "
                      "system-computed figure alongside"}],
            [{"text": "Late fee (CGST Act §47)"}, {"paise": 0},
             {"text": "Computed by the portal itself from the due date and "
                      "not editable"}],
        ],
    ))

    # ── Stage 5: Table 6.1 — THE PAYMENT STAGE ───────────────────────────────
    # The reason GSTR-3B has a step GSTR-1 does not, and the one screen this
    # whole walk-through exists to put in front of a CA.
    #
    # THE CREDIT COLUMN IS 4(C) AND ONLY 4(C). CGST Act §49(4) permits payment
    # out of credit "available in the electronic credit ledger", and credit
    # reversed in this same return is not available — spending it here would
    # use the same rupee twice. domain/gst/gstr3b_computer.py performs the
    # §49(5) set-off on itc_net_* for exactly this reason; nothing is
    # re-computed here, the saved net_payable IS that set-off's answer.
    pay_rows = []
    total_liability = total_credit = total_itc_paid = total_cash = 0
    for label, head in _HEADS:
        head_liability = _p(outward, f"taxable_{head}_paise")
        credit_available = _p(itc, f"net_{head}_paise")   # 4(C) — never 4(A)
        cash = _p(net_payable, f"{head}_paise")
        # What the credit actually discharged, as the difference between the
        # liability and what Table 6 leaves payable. Floored at zero so a
        # liability smaller than the residual — which would be a bug upstream
        # — can never render as a negative contribution from the ledger.
        paid_by_itc = max(head_liability - cash, 0)
        pay_rows.append([
            {"text": label},
            {"paise": head_liability},
            {"paise": credit_available},
            {"paise": paid_by_itc},
            {"paise": cash},
        ])
        total_liability += head_liability
        total_credit += credit_available
        total_itc_paid += paid_by_itc
        total_cash += cash

    payment_note = (
        "The portal's PROCEED TO PAYMENT screen. The credit set off here is "
        "Table 4(C) — what is left AFTER the 4(B) reversals — and never 4(A): "
        "CGST Act §49(4) permits payment only out of credit available in the "
        "electronic credit ledger, and credit reversed in this same return is "
        "not available. Cross-utilisation: §49(5)(a) requires IGST credit to "
        "be used against IGST first, and Rule 88A (inserted by Notification "
        "16/2019-Central Tax under §49B, w.e.f. 29-03-2019) then allows the "
        "balance against CGST and SGST in ANY order and ANY proportion — "
        "which is why the portal offers a set-off preference on this screen. "
        "The split shown here is the one the saved working computed "
        "(domain/gst/gstr3b_computer.py), not a rule this walk-through "
        "re-derives; on the portal the taxpayer may choose a different "
        "permissible split and the cash column will change. Anything in the "
        "cash column is paid "
        "by challan (PMT-06) before the return can be filed, and the "
        "reverse-charge tax in 3.1(d) is paid in cash separately — it is not "
        "part of this set-off.")
    stages.append(common.table_stage(
        "Table 6.1 — Payment of tax",
        payment_note,
        ["Head", "Liability (3.1(a))", "Credit available (4C)",
         "Paid through ITC", "Paid in cash"],
        pay_rows,
        footer=[{"text": "Total"}, {"paise": total_liability},
                {"paise": total_credit}, {"paise": total_itc_paid},
                {"paise": total_cash}],
        cta="Proceed to file",
    ))

    # ── The moment of no return, then the ceremony ───────────────────────────
    freeze = ("Once filed, GSTR-3B for this period cannot be revised. A "
              "correction is declared in a later period's return (CGST Act "
              "§39(9))")
    if window_closes:
        freeze += (f", and only while the correction window is open — "
                   f"{window_closes}, or the date GSTR-9 for that year is "
                   "furnished, whichever is EARLIER. Filing the annual return "
                   "early shuts this window early.")
    else:
        freeze += ", and only while the correction window is open."

    stages += [
        common.warning_stage(freeze),
        common.declaration_stage(
            # FORM GSTR-3B's verification, verbatim — the wording the portal
            # puts beside the checkbox. Shown because it is the moment that
            # matters: the person ticking it is making a statement to the
            # department, and paraphrasing it would misrepresent what they
            # are affirming.
            "I/We hereby solemnly affirm and declare that the information "
            "given herein above is true and correct to the best of my/our "
            "knowledge and belief and nothing has been concealed therefrom.",
            "Authorised signatory",
            ["Authorised signatory on the GST registration"],
            "This is the taxpayer's signatory, not the firm's. PracticeSync "
            "prepares the return; the taxpayer signs it — and it is the "
            "taxpayer's own cash and credit ledgers that discharge the "
            "liability, which is why filing can never be a single button on "
            "this side.",
        ),
        common.signature_stage([
            {"key": "evc", "label": "File with EVC", "otp": True,
             "note": "OTP to the authorised signatory's registered mobile and email"},
            {"key": "dsc", "label": "File with DSC", "otp": False,
             "note": "Class 3 digital signature via emSigner; mandatory for "
                     "companies and LLPs"},
        ]),
        common.otp_stage(
            "An OTP would now be sent to the authorised signatory's mobile "
            "and email as registered on the GST portal.",
            "Any six digits will do here — there is no OTP to be right about.",
        ),
        common.transmit_stage([
            {"key": "validate", "label": "Validating return against the GSTN schema"},
            {"key": "authenticate", "label": "Authenticating with the GST portal"},
            {"key": "upload", "label": "Uploading return payload"},
            {"key": "process", "label": "Awaiting GSTN processing"},
            {"key": "acknowledge", "label": "Receiving acknowledgement"},
        ]),
        common.result_stage(
            "GSTN",
            "Acknowledgement Reference Number (ARN)",
            common.specimen_gstn_arn(gstin, period, return_id),
            f"GSTR-3B for {period} — on the real portal, the return status "
            "would now read Filed, this ARN would arrive by SMS and email, "
            "and the electronic cash and credit ledgers would be debited.",
            [
                "Nothing was filed. No tax was paid and no ledger moved.",
                "To file for real: pay any cash balance by challan (PMT-06), "
                "then file and sign GSTR-3B on gst.gov.in, and record the real "
                "ARN against this return here — that is what writes the filing "
                "record the period lock reads.",
            ],
        ),
    ]

    return common.envelope(
        "gstr3b",
        "File GSTR-3B",
        f"{gstin} · {period}",
        return_id,
        {
            "how": "Filed on gst.gov.in with the taxpayer's DSC or EVC, after "
                   "the cash portion of the liability is paid by challan "
                   "(PMT-06). GSTN's filing APIs are reachable only through a "
                   "GST Suvidha Provider (GSP).",
            "software_permitted": False,
            "note": "Software filing needs GSP registration — a commercial "
                    "and compliance step, not a coding one. Until then, "
                    "PracticeSync prepares and the CA files.",
        },
        stages,
    )
