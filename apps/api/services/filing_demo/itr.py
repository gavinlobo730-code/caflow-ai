"""ITR filing demo — the e-filing portal walk-through.

THE REAL CHANNEL THIS MIMICS
    incometax.gov.in → e-File → Income Tax Returns → File Income Tax Return →
    the prepared return's computation summary → the §140 verification
    declaration and the signatory's capacity → e-Verify with Aadhaar OTP or
    EVC, or sign with DSC → transmission → the 15-digit e-filing
    acknowledgement number and the ITR-V.

    ITR is the ONE filing in this package that software genuinely CAN
    transmit in India today: an e-Return Intermediary (ERI) registered with
    the Income Tax Department files on the taxpayer's behalf through the
    department's ERI APIs. real_channel says so — software_permitted is True
    here and nowhere else. PracticeSync is not yet a registered ERI, which is
    exactly why this is a demo.

    Verification (IT Act §140): the return is verified by the taxpayer —
    self, karta for an HUF, managing director for a company, partner for a
    firm, or an authorised signatory — never by the CA's firm. E-verification
    must happen within 30 days of transmission or the return is treated as
    never having been filed (CBDT Notification 05/2022, in force 01-08-2022);
    the warning stage carries that clock.

    PracticeSync has no ITR JSON generator yet, and the transmit stage says
    so in as many words rather than pretending the artefact exists.

ref: {"filing_id": <itr_filings.id>} — the prepared filing the CA is walking
through. The demo is gated on status == 'ready_for_filing', the last stop
before 'filed' in domain/income_tax/itr_workflow.py's state machine: a draft
has not finished review, and a filed return has nothing left to walk through.
"""
from __future__ import annotations

from services import compliance_engine
from services.filing_demo import common


def _figures_from_snapshot(db, firm_id: str, client_id: str, filing: dict):
    """The computation the return is filed on, via the fallback chain:
    the filing's pinned snapshot → the latest snapshot for this client and
    financial year → zeros with an explicit note. Read-only, and each step is
    a single-row select — never per-line transaction data.

    The by-year query mirrors domain/income_tax/computation_workspace.py::
    list_snapshots (same table, same scope, version DESC) with LIMIT 1 —
    that helper cannot be called directly because it resolves its own
    Supabase client instead of taking this builder's read-only handle.
    """
    snap = None
    source_note = None

    snap_id = filing.get("computation_snapshot_id")
    if snap_id:
        rows = (db.table("tax_computation_snapshots").select("*")
                .eq("id", str(snap_id)).eq("firm_id", firm_id)
                .eq("client_id", client_id).limit(1).execute().data) or []
        if rows:
            snap = rows[0]
            source_note = ("Figures from the computation snapshot this "
                           f"filing pins (v{snap.get('version') or 1}).")

    if snap is None:
        rows = (db.table("tax_computation_snapshots").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("financial_year", filing.get("financial_year") or "")
                .order("version", desc=True).limit(1).execute().data) or []
        if rows:
            snap = rows[0]
            source_note = ("Figures from the latest computation snapshot for "
                           f"this year (v{snap.get('version') or 1}) — the "
                           "filing does not pin one.")

    if snap is None:
        snap = {}
        source_note = ("No computation snapshot yet — figures show as zero. "
                       "Compute the tax in the workspace first for a demo "
                       "with this client's real numbers.")

    def paise(col: str) -> int:
        return int(snap.get(col) or 0)

    # net_payable_paise is negative for a refund (domain/income_tax/
    # itr_engine.py: "negative = refund"; is_refund mirrors that sign). The
    # refund-or-payable line leads because it is the number the client asks
    # about; the magnitude is shown and the label carries the direction.
    net = paise("net_payable_paise")
    is_refund = bool(snap.get("is_refund"))
    headline = {"label": "Refund due" if is_refund else "Net tax payable",
                "paise": abs(net) if is_refund else net}

    figures = [
        headline,
        {"label": "Taxable income", "paise": paise("taxable_income_paise")},
        {"label": "Tax liability", "paise": paise("tax_liability_paise")},
        {"label": "TDS deducted", "paise": paise("tds_deducted_paise")},
        {"label": "Advance tax paid", "paise": paise("advance_tax_paid_paise")},
    ]
    return figures, source_note


def _due_date_line(financial_year: str) -> str | None:
    """§139(1) due dates via services/compliance_engine.py::itr_due_date —
    the single source for every statutory date. The filing row does not say
    whether audit applies, so both dates are stated rather than guessed."""
    try:
        # financial_year is stored as e.g. "2025-26"; the FY ends 31 March
        # of the starting year + 1.
        fy_end = int(str(financial_year)[:4]) + 1
    except (TypeError, ValueError):
        return None
    non_audit = compliance_engine.itr_due_date(fy_end, is_audit=False)
    audit = compliance_engine.itr_due_date(fy_end, is_audit=True)
    return (f"Due date under §139(1): {non_audit.strftime('%d %b %Y')}, or "
            f"{audit.strftime('%d %b %Y')} where audit applies.")


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"filing_id": <itr_filings.id>}. Read-only: a filing header row
    and at most one snapshot row — no writes of any kind."""
    filing_id = str(ref.get("filing_id") or "")
    if not filing_id:
        raise ValueError("itr demo needs ref.filing_id")

    rows = (db.table("itr_filings").select("*")
            .eq("id", filing_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("ITR filing not found")
    filing = rows[0]

    status = filing.get("status") or ""
    if status == "filed":
        raise ValueError(
            "This return is already recorded as filed — there is nothing "
            "left to walk through.")
    if status != "ready_for_filing":
        raise ValueError(
            f"This ITR is not ready for filing yet — its status is "
            f"'{status}'. Complete review and partner review to reach "
            "'ready_for_filing' first.")

    itr_form = filing.get("itr_form") or "ITR"
    ay = filing.get("assessment_year") or ""
    fy = filing.get("financial_year") or ""

    figures, source_note = _figures_from_snapshot(db, firm_id, client_id, filing)
    due_line = _due_date_line(fy)

    summary_note = ("On the portal this is the computation summary shown "
                    "before verification. " + source_note
                    + (f" {due_line}" if due_line else ""))

    stages = [
        common.summary_stage(
            f"{itr_form} · AY {ay}",
            summary_note,
            figures,
            cta="Proceed to verification",
        ),
        # IT Act §140 read with CBDT Notification 05/2022 (from 01-08-2022):
        # e-verification, or the signed ITR-V reaching CPC Bengaluru, within
        # 30 days of transmission — or the return is treated as never filed.
        common.warning_stage(
            "After transmission, the return must be e-verified within 30 "
            "days — Aadhaar OTP, EVC, DSC, or the signed ITR-V reaching CPC "
            "Bengaluru by post. A return not verified in time is treated as "
            "never having been filed (CBDT Notification 05/2022), and a "
            "fresh return would then attract late-filing consequences."
        ),
        common.declaration_stage(
            # The ITR verification block's own wording, verbatim (the name
            # and father's-name blanks are the portal's to fill; the
            # capacity blank is the dropdown below, as on the form).
            "I solemnly declare that to the best of my knowledge and "
            "belief, the information given in the return and the schedules "
            "thereto is correct and complete and is in accordance with the "
            "provisions of the Income-tax Act, 1961. I further declare that "
            "I am making this return in my capacity as indicated below and "
            "I am also competent to make this return and verify it.",
            "Capacity of the person verifying (IT Act §140)",
            # §140: who may verify, by constitution of the taxpayer.
            ["Self (the taxpayer)",
             "Karta (Hindu Undivided Family)",
             "Managing director (company)",
             "Partner (firm / LLP)",
             "Authorised signatory"],
            "This is the taxpayer's verification, not the firm's. "
            "PracticeSync prepares the return; the taxpayer (or the §140 "
            "signatory) verifies it — which is why filing can never be a "
            "single button on this side.",
        ),
        common.signature_stage([
            {"key": "aadhaar_otp", "label": "e-Verify with Aadhaar OTP",
             "otp": True,
             "note": "OTP to the mobile number linked with the signatory's "
                     "Aadhaar"},
            {"key": "evc", "label": "e-Verify with EVC", "otp": True,
             "note": "Electronic Verification Code via net banking, a "
                     "pre-validated bank account, or a demat account"},
            {"key": "dsc", "label": "Verify with DSC", "otp": False,
             "note": "Digital signature via emBridge; mandatory for "
                     "companies and audit cases (Rule 12, IT Rules 1962)"},
        ]),
        common.otp_stage(
            "An OTP would now be sent to the signatory's registered mobile "
            "for e-verification.",
            "Any six digits will do here — there is no OTP to be right "
            "about.",
        ),
        common.transmit_stage([
            # Honest about the missing artefact: there is no ITR JSON
            # generator in PracticeSync yet, and this step says so instead
            # of pretending one ran.
            {"key": "assemble",
             "label": "ITR JSON assembled — generator not yet built in "
                      "PracticeSync; specimen step"},
            {"key": "authenticate",
             "label": "Authenticating with the e-filing portal "
                      "(incometax.gov.in)"},
            {"key": "upload", "label": "Uploading return"},
            {"key": "verify", "label": "Registering e-verification"},
            {"key": "acknowledge",
             "label": "Receiving acknowledgement (ITR-V)"},
        ]),
        common.result_stage(
            "Income Tax Department",
            "e-Filing Acknowledgement Number",
            common.specimen_itr_ack(filing_id),
            f"{itr_form} for AY {ay} — on the real portal, this 15-digit "
            "acknowledgement number would arrive with the ITR-V, and "
            "e-verification would close out the 30-day clock.",
            [
                "Nothing was filed.",
                "On a real filing, the ITR-V acknowledgement is generated "
                "at transmission and e-verification must follow within 30 "
                "days, or the return is treated as never filed.",
                "To file for real: prepare and upload the return on "
                "incometax.gov.in, e-verify it, then enter the "
                "acknowledgement number here with Record Acknowledgement.",
            ],
        ),
    ]

    return common.envelope(
        "itr",
        f"File {itr_form}",
        f"AY {ay} · FY {fy}",
        filing_id,
        {
            "how": "Filed on incometax.gov.in and verified per IT Act §140 "
                   "with Aadhaar OTP, EVC or DSC. Software CAN transmit an "
                   "ITR today: a registered e-Return Intermediary (ERI) "
                   "files through the department's ERI APIs.",
            "software_permitted": True,
            "note": "PracticeSync is not yet a registered ERI — which is "
                    "exactly why this is a demo. Until registration, the CA "
                    "files on the portal and records the acknowledgement "
                    "number here.",
        },
        stages,
    )
