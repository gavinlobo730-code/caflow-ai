"""GSTR-1 filing demo — the exemplar flow every other module follows.

THE REAL CHANNEL THIS MIMICS
    gst.gov.in → Returns Dashboard → GSTR-1 → the saved statement's summary →
    an acknowledgement that filing freezes the statement → the Rule 59
    declaration and the authorised signatory → FILE WITH DSC / FILE WITH EVC →
    emSigner or an OTP to the signatory's registered mobile and email → ARN.

    There is no payment step: GSTR-1 declares outward supplies; the tax is
    paid with GSTR-3B. That asymmetry is itself worth showing — a CA coming
    from VAT-style regimes expects payment with every return.

    Software may not transmit this today: GSTN's filing APIs are reachable
    only through a GST Suvidha Provider (a commercial registration, not a
    coding step). The demo says so in real_channel.
"""
from __future__ import annotations

from services.filing_demo import common


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"return_id": <gstr1_returns.id>} — the saved return the CA is
    walking through. Read-only: one select, no writes of any kind."""
    return_id = str(ref.get("return_id") or "")
    if not return_id:
        raise ValueError("gstr1 demo needs ref.return_id")

    rows = (db.table("gstr1_returns").select("*")
            .eq("id", return_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("GSTR-1 return not found")
    rec = rows[0]

    period = rec.get("period") or ""
    gstin = rec.get("gstin") or ""
    taxable = int(rec.get("total_taxable_paise") or 0)
    igst = int(rec.get("total_igst_paise") or 0)
    cgst = int(rec.get("total_cgst_paise") or 0)
    sgst = int(rec.get("total_sgst_paise") or 0)
    cess = int(rec.get("total_cess_paise") or 0)

    # Document counts, where the saved summary carries them. Resilient to an
    # older record without summary_json: the figures above always exist.
    counts = ((rec.get("summary_json") or {}).get("counts") or {})
    count_rows = [
        [{"text": label}, {"text": str(counts[key])}]
        for key, label in (("b2b", "B2B invoices"),
                           ("b2cs_rate_groups", "B2CS rate groups"),
                           ("b2cl", "B2CL invoices"),
                           ("cdnr", "Credit/debit notes (registered)"),
                           ("hsn", "HSN summary lines"))
        if counts.get(key) is not None
    ]

    stages = [
        common.summary_stage(
            f"GSTR-1 · {period}",
            "On the portal this is the saved statement, after Prepare "
            "Online or a JSON upload, with Generate Summary run.",
            [
                {"label": "Taxable value", "paise": taxable},
                {"label": "IGST", "paise": igst},
                {"label": "CGST", "paise": cgst},
                {"label": "SGST", "paise": sgst},
                {"label": "Cess", "paise": cess},
            ],
            cta="Proceed to file",
        ),
    ]
    if count_rows:
        stages.append(common.table_stage(
            "Documents in this statement",
            "The section-wise counts the portal shows on the summary page.",
            ["Section", "Count"], count_rows,
        ))
    stages += [
        # No payment stage — see the module docstring. The freeze warning is
        # GSTR-1's equivalent moment of no return.
        common.warning_stage(
            "Once filed, GSTR-1 for this period cannot be revised. A "
            "correction is declared in a later period's amendment tables "
            "(CGST Act §37(3)), subject to the correction window."
        ),
        common.declaration_stage(
            # Rule 59 — the form's own wording, verbatim.
            "I/We hereby solemnly affirm and declare that the information "
            "given herein above is true and correct to the best of my/our "
            "knowledge and belief and nothing has been concealed therefrom.",
            "Authorised signatory",
            ["Authorised signatory on the GST registration"],
            "This is the taxpayer's signatory, not the firm's. PracticeSync "
            "prepares the statement; the taxpayer signs it — which is why "
            "filing can never be a single button on this side.",
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
            {"key": "validate", "label": "Validating statement summary"},
            {"key": "authenticate", "label": "Authenticating with the GST portal"},
            {"key": "file", "label": "Filing statement"},
            {"key": "acknowledge", "label": "Receiving acknowledgement"},
        ]),
        common.result_stage(
            "GSTN",
            "Acknowledgement Reference Number (ARN)",
            common.specimen_gstn_arn(gstin, period, return_id),
            f"GSTR-1 for {period} — on the real portal, the statement status "
            "would now read Filed and this ARN would arrive by SMS and email.",
            [
                "Nothing was filed.",
                "To file for real: download the GSTN JSON, upload and sign it "
                "on gst.gov.in, then record the ARN here with Mark Filed.",
            ],
        ),
    ]

    return common.envelope(
        "gstr1",
        "File GSTR-1",
        f"{gstin} · {period}",
        return_id,
        {
            "how": "Filed on gst.gov.in with the taxpayer's DSC or EVC. "
                   "GSTN's filing APIs are reachable only through a GST "
                   "Suvidha Provider (GSP).",
            "software_permitted": False,
            "note": "Software filing needs GSP registration — a commercial "
                    "and compliance step, not a coding one. Until then, "
                    "PracticeSync prepares and the CA uploads.",
        },
        stages,
    )
