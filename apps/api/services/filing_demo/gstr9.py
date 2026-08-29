"""GSTR-9 annual return filing demo — the year-end walk-through.

THE REAL CHANNEL THIS MIMICS
    gst.gov.in → Returns Dashboard → Annual Return → select FY → FORM GSTR-9
    (CGST Act §44 with Rule 80(1)) → tables auto-populated from the year's
    filed GSTR-1 and GSTR-3B → Compute Liabilities → preview → the
    verification declaration and the authorised signatory → FILE WITH DSC /
    FILE WITH EVC → emSigner or an OTP to the signatory's registered mobile
    and email → ARN. The portal opens GSTR-9 only after EVERY GSTR-1 and
    GSTR-3B of the FY is filed, and once filed GSTR-9 cannot be revised.

    The moment this demo exists to teach: furnishing the annual return CLOSES
    the §37(3)/§39(9)/§16(4) correction window for that FY EARLY. The window
    ends at the EARLIER of 30 November following the FY or the date GSTR-9 is
    furnished — services/compliance_engine.py::correction_window_closes is
    the authority. A CA who files GSTR-9 in July has shut the door on the
    year's corrections four months ahead of the statutory outer limit, so the
    warning stage runs every time, not only when something is missing.

    Software may not transmit this today: GSTN's filing APIs are reachable
    only through a GST Suvidha Provider (a commercial registration, not a
    coding step). The demo says so in real_channel.

ref: {"return_id": <gstr1_returns.id of the GSTR-9 draft>}. GSTR-9 drafts
live in the gstr1_returns store with return_type='gstr9' and
period='FY<financial_year>' (migration 053). They only ever hold status
'draft' — there is no GSTR-9 status endpoint — so the demo is gated on the
row existing, not on a status.
"""
from __future__ import annotations

from services.compliance_engine import gstr9_due_date, november_30_cutoff
from services.filing_demo import common
from services.gst_return_service import (
    gstr9_fy_periods,
    gstr9_summary_from_returns,
)


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"return_id": <gstr1_returns.id>} — the saved GSTR-9 draft the CA
    is walking through. Read-only: three header selects (the draft plus at
    most 24 monthly return headers), no writes of any kind."""
    return_id = str(ref.get("return_id") or "")
    if not return_id:
        raise ValueError("gstr9 demo needs ref.return_id")

    rows = (db.table("gstr1_returns").select("*")
            .eq("id", return_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("GSTR-9 return not found")
    rec = rows[0]
    # The gstr1_returns store also holds monthly GSTR-1 rows (whose stored or
    # defaulted return_type is 'gstr1') — walking one of those through an
    # ANNUAL return ceremony would teach the wrong filing.
    if (rec.get("return_type") or "gstr1") != "gstr9":
        raise ValueError("That return is not a GSTR-9 annual return.")

    # save_gstr9 writes financial_year and period='FY<fy>' together; an older
    # row missing the column still names its FY in the period string.
    fy = str(rec.get("financial_year") or "").strip()
    period = str(rec.get("period") or "")
    if not fy and period.startswith("FY"):
        fy = period[2:]
    fy_periods = gstr9_fy_periods(fy)  # raises a plain sentence on a bad FY
    fy_end_year = int(fy.split("-")[0]) + 1  # FY 2025-26 ends 31 Mar 2026

    gstin = rec.get("gstin") or ""

    # The year's monthly return HEADERS — at most 12 + 12 rows, proportional
    # to the answer (a 12-row month table), never per-line transaction data.
    # The gstr9 draft row itself cannot collide with this select: its period
    # is 'FY2025-26', never one of the twelve MMYYYY strings.
    g1_rows = (db.table("gstr1_returns")
               .select("period,status,return_type,total_taxable_paise,"
                       "total_igst_paise,total_cgst_paise,total_sgst_paise,"
                       "total_cess_paise")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .in_("period", fy_periods).execute().data) or []
    g3b_rows = (db.table("gstr3b_returns").select("period,status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("period", fy_periods).execute().data) or []

    summary = gstr9_summary_from_returns(fy, g1_rows, g3b_rows)
    totals = summary["totals"]

    # CGST Act §44: annual return due 31 December following the FY —
    # services/compliance_engine.py::gstr9_due_date is the date authority.
    due = gstr9_due_date(fy_end_year)
    due_text = f"{due.day} {due.strftime('%B')} {due.year}"
    # §37(3)/§39(9)/§16(4) statutory outer limit — the demo quotes it from
    # compliance_engine.november_30_cutoff and states the earlier-of rule that
    # correction_window_closes() applies, rather than hardcoding a date.
    outer = november_30_cutoff(fy_end_year)
    outer_text = f"{outer.day} {outer.strftime('%B')} {outer.year}"

    def _status_text(status) -> str:
        if status == "submitted":
            return "Filed"
        return str(status) if status else "Not filed"

    month_rows = [
        [{"text": m["label"]},
         {"text": _status_text(m["gstr1_status"])},
         {"text": _status_text(m["gstr3b_status"])}]
        for m in summary["months"]
    ]

    stages = [
        common.summary_stage(
            f"GSTR-9 · FY {fy}",
            # CGST Act §44 (due date; gstr9_due_date above) and §47(2) (late
            # fee). The proviso to §44(1) lets the Commissioner exempt classes
            # of taxpayers by notification — exercised year after year for
            # turnover up to ₹2 crore, which is why the line stays general.
            f"Annual return under CGST Act §44, due {due_text}. Filing it "
            "is optional below the notified turnover threshold (₹2 crore, by "
            "notification under the proviso to §44(1)); filed late it "
            "attracts a late fee under §47(2). On the portal these figures "
            "are auto-populated from the year's FILED GSTR-1 returns.",
            [
                {"label": "Taxable value (filed GSTR-1)",
                 "paise": totals["taxable_paise"]},
                {"label": "IGST", "paise": totals["igst_paise"]},
                {"label": "CGST", "paise": totals["cgst_paise"]},
                {"label": "SGST", "paise": totals["sgst_paise"]},
                {"label": "Cess", "paise": totals["cess_paise"]},
                {"label": "GSTR-1 filed",
                 "text": f"{summary['gstr1_filed_months']} of 12 months"},
                {"label": "GSTR-3B filed",
                 "text": f"{summary['gstr3b_filed_months']} of 12 months"},
            ],
            cta="Proceed to file",
        ),
        common.table_stage(
            "Month-wise filing status",
            # Rule 80(1) CGST Rules with FORM GSTR-9's instructions: the
            # annual return can be filed only after all the FY's GSTR-1 and
            # GSTR-3B are filed. This table is the portal's checklist.
            "The portal opens GSTR-9 only after every GSTR-1 and GSTR-3B of "
            "the financial year is filed.",
            ["Month", "GSTR-1", "GSTR-3B"], month_rows,
        ),
    ]

    missing_g1 = summary["missing_gstr1"]
    missing_g3b = summary["missing_gstr3b"]
    if missing_g1 or missing_g3b:
        parts = []
        if missing_g1:
            parts.append("GSTR-1 for " + ", ".join(missing_g1))
        if missing_g3b:
            parts.append("GSTR-3B for " + ", ".join(missing_g3b))
        stages.append(common.warning_stage(
            # Rule 80(1) precondition again — shown, not refused: the demo
            # teaches what the portal would block, so it walks on where the
            # real portal would stop.
            f"The portal would not open GSTR-9 for FY {fy} yet — still to be "
            f"filed: {'; '.join(parts)}. The real portal stops here until "
            "every monthly return of the year is filed. This demo continues "
            "so the rest of the ceremony can be shown.",
        ))

    stages += [
        # THE warning. CGST Act §37(3), §39(9) and §16(4), each amended by
        # the Finance Act 2022 to "30 November following the end of the
        # financial year ... or the furnishing of the relevant annual return,
        # whichever is earlier". compliance_engine.correction_window_closes()
        # is the authority for the earlier-of rule; november_30_cutoff() above
        # supplies only the statutory outer limit quoted in the text.
        common.warning_stage(
            f"Filing GSTR-9 closes the books on FY {fy} early. Corrections "
            "to the year's GSTR-1 and GSTR-3B and any input tax credit still "
            f"to be taken (CGST Act §37(3), §39(9), §16(4)) are available "
            f"only until {outer_text} OR the date this annual return is "
            "furnished, whichever is EARLIER. File GSTR-9 in July and the "
            "correction window shuts in July — months ahead of the statutory "
            "outer limit. GSTR-9 itself, once filed, cannot be revised.",
        ),
        common.declaration_stage(
            # FORM GSTR-9's verification — the form's own wording, verbatim,
            # including its anti-profiteering rider (§171 is why it is there).
            "I hereby solemnly affirm and declare that the information given "
            "herein above is true and correct to the best of my knowledge "
            "and belief and nothing has been concealed there from and in "
            "case of any reduction in output tax liability the benefit "
            "thereof has been/will be passed on to the recipient of supply.",
            "Authorised signatory",
            ["Authorised signatory on the GST registration"],
            "This is the taxpayer's signatory, not the firm's. PracticeSync "
            "prepares the annual return; the taxpayer signs it — which is "
            "why filing can never be a single button on this side.",
        ),
        common.signature_stage([
            {"key": "evc", "label": "File with EVC", "otp": True,
             "note": "OTP to the authorised signatory's registered mobile "
                     "and email"},
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
            {"key": "compute", "label": "Computing liabilities"},
            {"key": "authenticate", "label": "Authenticating with the GST portal"},
            {"key": "file", "label": "Filing annual return"},
            {"key": "acknowledge", "label": "Receiving acknowledgement"},
        ]),
        common.result_stage(
            "GSTN",
            "Acknowledgement Reference Number (ARN)",
            common.specimen_gstn_arn(gstin, period, return_id),
            f"GSTR-9 for FY {fy} — on the real portal, the return status "
            "would now read Filed and this ARN would arrive by SMS and email.",
            [
                "Nothing was filed. The §37(3)/§39(9) correction window for "
                f"FY {fy} is untouched and still runs to its statutory limit.",
                "To file for real: the authorised signatory files FORM GSTR-9 "
                f"on gst.gov.in with DSC or EVC, by {due_text}.",
            ],
        ),
    ]

    return common.envelope(
        "gstr9",
        "File GSTR-9",
        f"{gstin} · FY {fy}",
        return_id,
        {
            "how": "Filed on gst.gov.in with the taxpayer's DSC or EVC. "
                   "GSTN's filing APIs are reachable only through a GST "
                   "Suvidha Provider (GSP).",
            "software_permitted": False,
            "note": "Software filing needs GSP registration — a commercial "
                    "and compliance step, not a coding one. Until then, "
                    "PracticeSync prepares and the CA files on the portal.",
        },
        stages,
    )
