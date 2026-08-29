"""MCA annual-filing demo — AOC-4, MGT-7, MGT-7A and ADT-1 on the V3 portal.

THE REAL CHANNEL THIS MIMICS
    mca.gov.in (MCA V3) → MCA Services → e-Filing → the annual web form
    (since FY 2022-23 these are filled on the portal itself, not offline
    PDFs) → the eForm declaration signed by a DIRECTOR with a DIN-linked
    Class 3 DSC → for AOC-4 and MGT-7, the certification block signed by a
    PRACTISING PROFESSIONAL with their OWN DSC and membership number (for
    AOC-4 a CA / CS / cost accountant in whole-time practice; for MGT-7 a
    Company Secretary in whole-time practice specifically, §92(1)) → upload →
    pre-scrutiny → SRN → fee → challan/acknowledgement.

    The dual signature is the defining feature of the ROC annual forms and
    the thing this walk-through exists to teach: two different people affirm
    two different statements, and neither of them is the accounting firm as
    such. MGT-7A (One Person Companies and small companies, proviso to §92(1)
    of the Companies Act 2013 read with the Companies (Management and
    Administration) Rules 2014) drops the professional certification; ADT-1
    is the company's intimation of its auditor's appointment under §139(1)
    and is signed by a director alone.

    Software may not transmit this today: MCA V3 is a portal-login flow with
    no public filing API. The demo says so in real_channel.

ref: {"filing_id": <mca_filings.id>} — the not-yet-filed annual filing the
CA is walking through. Read-only: a handful of header rows, no writes of any
kind, and never per-transaction data.
"""
from __future__ import annotations

from datetime import date

from services import year_end_financial_service
from services.compliance_engine import MCA_AGM_OFFSET_DAYS, mca_due_date
from services.filing_demo import common

# Companies Act 2013 — the ROC ANNUAL forms, the only ones this demo covers:
#   AOC-4   §137 — financial statements, within 30 days of the AGM
#   MGT-7   §92  — annual return, within 60 days of the AGM
#   MGT-7A  §92(1) proviso — annual return for OPCs and small companies
#   ADT-1   §139(1) — intimation of auditor appointment, within 15 days
# services/compliance_engine.py::mca_due_date is the authority for the
# offsets; this module cites it rather than restating the numbers.
_ANNUAL_FORMS = ("AOC-4", "MGT-7", "MGT-7A", "ADT-1")

# The forms that carry the practising-professional certification block.
# MGT-7A and ADT-1 do not — see the module docstring.
_DUAL_SIGNATURE_FORMS = ("AOC-4", "MGT-7")

# The standard MCA eForm declaration, signed by the director. This is the
# form's own wording — a statutory declaration is never paraphrased. The
# resolution blanks are fields on the real form.
_DIRECTOR_DECLARATION = (
    "I am authorised by the Board of Directors of the Company vide "
    "resolution number ____ dated ____ to sign this form and declare that "
    "all the requirements of the Companies Act, 2013 and the rules made "
    "thereunder in respect of the subject matter of this form and matters "
    "incidental thereto have been complied with. I further declare that: "
    "1. Whatever is stated in this form and in the attachments thereto is "
    "true, correct and complete and no information material to the subject "
    "matter of this form has been suppressed or concealed and is as per the "
    "original records maintained by the company. 2. All the required "
    "attachments have been completely and legibly attached to this form."
)

# The certification block on AOC-4 and MGT-7, signed by the practising
# professional with their own DSC and membership number — for AOC-4 a
# CA / CS / cost accountant in whole-time practice, for MGT-7 a Company
# Secretary in whole-time practice specifically (§92(1); options are set
# per form where the stages are built). Again the form's own wording.
_PROFESSIONAL_CERTIFICATION = (
    "It is hereby certified that I have verified the above particulars "
    "(including attachment(s)) from the records of the Company and found "
    "them to be true, correct and complete and no information material to "
    "this form has been suppressed. I further certify that: 1. The said "
    "records have been properly prepared, signed by the required officers "
    "of the Company and maintained as per the relevant provisions of the "
    "Companies Act, 2013 and were found to be in order; 2. All the required "
    "attachments have been completely and legibly attached to this form."
)

# MCA V3 signs with DSC only — there is no EVC/OTP route for ROC forms, so
# every signature method here has otp False and the flow contains no otp
# stage at all (the wizard skips one that a chosen method does not need, but
# a flow that never needs one simply does not carry one).
def _dsc_only(note: str) -> list:
    return [{"key": "dsc", "label": "Sign with DSC", "otp": False, "note": note}]


def _fy_bounds(financial_year: str):
    """"2024-25" → ("2024-04-01", "2025-03-31"). Indian financial year runs
    1 April to 31 March. None when the stored value is not in that shape —
    the caller then says so honestly instead of guessing a year."""
    fy = str(financial_year or "").strip()
    # mca_filings.financial_year is sometimes blank with period carrying
    # "FY 2025-26" (the format migration 038's own comment documents) —
    # accept the prefixed form rather than telling the CA no year exists.
    if fy.upper().startswith("FY"):
        fy = fy[2:].lstrip()
    if len(fy) == 7 and fy[:4].isdigit() and fy[4] == "-" and fy[5:].isdigit():
        start_year = int(fy[:4])
        return f"{start_year}-04-01", f"{start_year + 1}-03-31"
    return None


def _aoc4_figures(db, firm_id: str, client_id: str, financial_year: str):
    """Schedule III headline figures for the AOC-4 summary.

    Preference order: a validated XBRL package's stored figures (AOC-4 XBRL
    applies to listed and specified large companies, Companies (Filing of
    Documents and Forms in XBRL) Rules 2015 under §137), else the year-end
    Schedule III engine. Either way a handful of header totals — never
    transaction rows fetched by this module. Returns (figures, notes).
    """
    figures: list = []
    notes: list = []

    bounds = _fy_bounds(financial_year)
    if bounds is None:
        notes.append(
            "The financial year on this filing is not in a recognisable "
            "form, so Schedule III figures are not shown here."
        )
        return figures, notes

    # One header row: the validated XBRL package for this FY, if any.
    pkgs = (db.table("xbrl_packages")
            .select("id, status, taxonomy_version, balance_sheet_json, pnl_json")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("financial_year", str(financial_year))
            .in_("status", ["validated", "reviewed"])
            .limit(1).execute().data) or []
    if pkgs:
        pkg = pkgs[0]
        bs = pkg.get("balance_sheet_json") or {}
        pnl = pkg.get("pnl_json") or {}
        # Keys are the package's Schedule III schedule_line tags
        # (domain/income_tax/xbrl_service.DEFAULT_MAPPINGS), integer paise.
        for label, value in (
            ("Revenue from operations",
             pnl.get("ProfitAndLoss.Revenue.RevenueFromOperations")),
            ("Share capital", bs.get("BalanceSheet.Equity.ShareCapital")),
        ):
            if isinstance(value, int) and not isinstance(value, bool):
                figures.append({"label": label, "paise": value})
        # Say what the row's status actually is: review_package can mark a
        # package 'reviewed' without validation ever having run, so claiming
        # "validated" for both statuses would over-state the evidence.
        status_word = ("validated" if pkg.get("status") == "validated"
                       else "CA-reviewed")
        notes.append(
            f"A {status_word} XBRL package (taxonomy "
            f"{pkg.get('taxonomy_version') or 'MCA'}) exists for FY "
            f"{financial_year} and stands as evidence — AOC-4 XBRL applies "
            "to listed and specified large companies."
        )
        return figures, notes

    fy_start, fy_end = bounds
    try:
        fs = year_end_financial_service.generate_financial_statements(
            db, client_id, firm_id, fy_start, fy_end)
    except ValueError as ve:
        # An unbalanced balance sheet (or any other refusal from the
        # Schedule III engine) is an honest note on the summary, not a 500
        # and not a reason to withhold the walk-through.
        notes.append(
            f"Schedule III figures could not be produced: {ve} "
            "The walk-through continues without them."
        )
        return figures, notes

    balance_sheet = fs.get("balance_sheet") or {}
    profit_loss = fs.get("profit_loss") or {}
    for label, value in (
        ("Total assets (Schedule III)",
         balance_sheet.get("total_assets_paise")),
        ("Revenue from operations",
         (profit_loss.get("income") or {}).get("revenue_from_operations")),
        ("Profit after tax", profit_loss.get("profit_after_tax_paise")),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            figures.append({"label": label, "paise": value})
    return figures, notes


def _overdue_warning(form_type: str, agm_date_iso: str):
    """The late-filing warning, only where the AGM date lets it be computed
    honestly; None otherwise. Due dates come from compliance_engine
    (§137 / §92 / §139(1) offsets from the AGM) — cited, not restated."""
    if not agm_date_iso:
        return None
    try:
        agm = date.fromisoformat(str(agm_date_iso))
    except ValueError:
        return None  # an unparseable AGM date is a reason to omit, not guess

    # MGT-7A shares MGT-7's window: both are the §92 annual return, due 60
    # days from the AGM; compliance_engine keys the offset by "MGT-7".
    offset_form = "MGT-7" if form_type == "MGT-7A" else form_type
    if offset_form not in MCA_AGM_OFFSET_DAYS:
        return None
    due = mca_due_date(agm, offset_form)
    if date.today() <= due:
        return None

    if form_type == "ADT-1":
        # ADT-1's additional fee is the slab of multiples under the
        # Companies (Registration Offices and Fees) Rules 2014 — NOT the
        # per-day fee, which the Rules reserve for §92/§137 forms.
        return common.warning_stage(
            f"This ADT-1 is past its window: the AGM was held on "
            f"{agm.isoformat()} and §139(1) requires the intimation within "
            f"15 days (due {due.isoformat()}). Filing now attracts "
            "additional fees on the slab in the Companies (Registration "
            "Offices and Fees) Rules, 2014.",
            cta="Proceed anyway",
        )
    # AOC-4 / MGT-7 / MGT-7A: ₹100 for every day of delay, with no upper
    # cap — Companies (Registration Offices and Fees) Rules, 2014, read
    # with §137(3) and §92(5) of the Companies Act 2013.
    return common.warning_stage(
        f"This {form_type} is past its window: the AGM was held on "
        f"{agm.isoformat()} and the form was due by {due.isoformat()}. "
        "Filing now attracts an additional fee of ₹100 for every day "
        "of delay, with no upper cap (Companies (Registration Offices and "
        "Fees) Rules, 2014, read with §137(3) / §92(5)). The "
        "portal computes the fee at upload; paying it does not condone the "
        "default.",
        cta="Proceed anyway",
    )


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"filing_id": <mca_filings.id>}. Read-only: the filing header,
    its company row, the director list and (for AOC-4) one figures source."""
    filing_id = str(ref.get("filing_id") or "")
    if not filing_id:
        raise ValueError("mca demo needs ref.filing_id")

    rows = (db.table("mca_filings").select("*")
            .eq("id", filing_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("MCA filing not found")
    rec = rows[0]

    form_type = str(rec.get("form_type") or "").strip().upper()
    if form_type not in _ANNUAL_FORMS:
        raise ValueError(
            f"No walk-through exists for {form_type or 'this form'} — only "
            "the annual forms (AOC-4, MGT-7, MGT-7A, ADT-1) have filing "
            "demos.")
    if rec.get("status") == "filed":
        srn = rec.get("srn")
        raise ValueError(
            f"This {form_type} is already marked filed"
            + (f" (SRN {srn})" if srn else "")
            + " — the walk-through shows a filing that has not happened yet.")

    # ── The company row, for CIN, capital and the AGM date ──────────────────
    company = None
    company_id = rec.get("company_id")
    cin_on_filing = rec.get("company_cin") or rec.get("cin")
    if company_id:
        found = (db.table("mca_companies").select("*")
                 .eq("id", str(company_id)).eq("firm_id", firm_id)
                 .eq("client_id", client_id).limit(1).execute().data) or []
        company = found[0] if found else None
    elif cin_on_filing:
        found = (db.table("mca_companies").select("*")
                 .eq("cin", str(cin_on_filing)).eq("firm_id", firm_id)
                 .eq("client_id", client_id).limit(1).execute().data) or []
        company = found[0] if found else None

    cin = str(cin_on_filing or (company or {}).get("cin") or "")
    agm_date_iso = str(rec.get("agm_date")
                       or (company or {}).get("last_agm_date") or "")
    financial_year = str(rec.get("financial_year") or rec.get("period") or "")

    # ── Directors — the signatory options for the DIRECTOR's DSC ────────────
    # A handful of rows; ceased or deactivated directors cannot sign.
    directors = (db.table("mca_directors")
                 .select("director_name, din, is_active, date_of_cessation")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .limit(50).execute().data) or []
    director_options = sorted(
        f"{d.get('director_name')} (DIN {d.get('din')})"
        for d in directors
        if d.get("is_active") is not False and not d.get("date_of_cessation"))
    if not director_options:
        raise ValueError(
            "No active directors are on record for this client. AOC-4, "
            "MGT-7 and ADT-1 are signed by a director with their DIN and "
            "Class 3 DSC — add the directors in the MCA workspace first.")

    # ── Summary figures ─────────────────────────────────────────────────────
    figures: list = [
        {"label": "Form", "text": form_type},
        {"label": "CIN", "text": cin or "—"},
        {"label": "Financial year", "text": financial_year or "—"},
        {"label": "AGM date", "text": agm_date_iso or "—"},
    ]
    if company is not None:
        auth_cap = company.get("authorized_capital_paise")
        paid_cap = company.get("paid_up_capital_paise")
        if isinstance(auth_cap, int) and not isinstance(auth_cap, bool):
            figures.append({"label": "Authorised capital", "paise": auth_cap})
        if isinstance(paid_cap, int) and not isinstance(paid_cap, bool):
            figures.append({"label": "Paid-up capital", "paise": paid_cap})
    if form_type == "ADT-1" and rec.get("auditor_name"):
        figures.append({"label": "Auditor appointed",
                        "text": str(rec["auditor_name"])})

    notes: list = []
    if form_type == "AOC-4":
        aoc4_figures, aoc4_notes = _aoc4_figures(
            db, firm_id, client_id, financial_year)
        figures += aoc4_figures
        notes += aoc4_notes

    form_purpose = {
        # Comments alone don't reach the screen — the note carries the
        # section so the walk-through teaches which provision drives which
        # form (Companies Act 2013: §137, §92, §92(1) proviso, §139(1)).
        "AOC-4": "financial statements laid before the AGM (§137)",
        "MGT-7": "the annual return (§92)",
        "MGT-7A": "the annual return for OPCs and small companies "
                  "(proviso to §92(1))",
        "ADT-1": "intimation of the auditor's appointment (§139(1))",
    }[form_type]
    summary_note = (
        f"On MCA V3 this is the {form_type} web form — {form_purpose} — "
        "filled on the portal after signing in with the company's "
        "credentials." + ("" if not notes else " " + " ".join(notes)))

    stages = [
        common.summary_stage(
            f"{form_type} · FY {financial_year or '—'}",
            summary_note,
            figures,
            cta="Proceed to sign",
        ),
    ]

    overdue = _overdue_warning(form_type, agm_date_iso)
    if overdue is not None:
        stages.append(overdue)

    # ── Signature ceremony ──────────────────────────────────────────────────
    # Pair one, on every annual form: the DIRECTOR. DIN plus the director's
    # own Class 3 DSC registered against that DIN on MCA V3. DSC only — no
    # OTP route exists for ROC forms, so this flow has no otp stage.
    stages += [
        common.declaration_stage(
            _DIRECTOR_DECLARATION,
            "Director (signs with DIN and their own Class 3 DSC)",
            director_options,
            "This is a DIRECTOR's signature — the DIN holder's own Class 3 "
            "DSC as registered on MCA V3, never the accounting firm's. "
            "PracticeSync prepares the form; the company's director signs it.",
        ),
        common.signature_stage(_dsc_only(
            "Class 3 DSC associated with the director's DIN on MCA V3; "
            "no OTP alternative exists for ROC forms")),
    ]

    if form_type in _DUAL_SIGNATURE_FORMS:
        # Pair two, AOC-4 and MGT-7 only: the practising professional's
        # certification. A second person, a second statement, a second DSC —
        # the wizard resets the declaration tick between pairs so each
        # signatory affirms their own words. MGT-7A and ADT-1 skip this pair.
        if form_type == "MGT-7":
            # Companies Act §92(1) proviso and Form MGT-7's own certification
            # block: the annual return's professional certification is a
            # COMPANY SECRETARY in whole-time practice specifically — a CA or
            # cost accountant cannot certify MGT-7, unlike AOC-4.
            certifier_options = ["Company Secretary (in whole-time practice)"]
            certifier_note = (
                "This is the PRACTISING PROFESSIONAL's certification — for "
                "MGT-7 that professional is a Company Secretary in whole-time "
                "practice (Companies Act §92(1)), signing with their OWN DSC; "
                "membership number and certificate of practice are entered on "
                "the form and the certification is the professional's "
                "personal responsibility.")
        else:
            # AOC-4 (§137, Form AOC-4 certification block): CA, CS or cost
            # accountant in whole-time practice.
            certifier_options = [
                "Chartered Accountant (in whole-time practice)",
                "Company Secretary (in whole-time practice)",
                "Cost Accountant (in whole-time practice)",
            ]
            certifier_note = (
                "This is the PRACTISING PROFESSIONAL's certification — a "
                "CA, CS or cost accountant in whole-time practice signing "
                "with their OWN DSC; membership number and certificate of "
                "practice are entered on the form and the certification is "
                "the professional's personal responsibility.")
        stages += [
            common.declaration_stage(
                _PROFESSIONAL_CERTIFICATION,
                "Certifying professional (in whole-time practice)",
                certifier_options,
                certifier_note,
            ),
            common.signature_stage(_dsc_only(
                "The professional's own Class 3 DSC, with membership number")),
        ]

    stages += [
        common.transmit_stage([
            {"key": "upload", "label": "Uploading signed form to MCA V3"},
            {"key": "prescrutiny", "label": "Pre-scrutiny checks"},
            {"key": "srn", "label": "SRN generated"},
            {"key": "fee", "label": "Fee payment recorded"},
        ]),
        common.result_stage(
            "MCA",
            "Service Request Number (SRN)",
            common.specimen_mca_srn(filing_id),
            f"{form_type} for FY {financial_year or '—'} — on the real "
            "portal the SRN would now appear under My Applications, with "
            "the challan and acknowledgement to download.",
            [
                "Nothing was filed.",
                "To file for real: sign in to mca.gov.in (V3), fill and "
                "sign the web form with the DSCs shown here, pay the fee, "
                "then record the SRN in PracticeSync with Mark Filed (CA).",
            ],
        ),
    ]

    return common.envelope(
        "mca",
        f"File {form_type}",
        f"{cin or '—'} · FY {financial_year or '—'}",
        filing_id,
        {
            "how": "Filed on mca.gov.in (MCA V3) as a web form: the "
                   "director signs with a DIN-linked Class 3 DSC, a "
                   "practising professional certifies AOC-4 and MGT-7 with "
                   "their own DSC and membership number, and the portal "
                   "runs pre-scrutiny, issues the SRN and collects the fee.",
            "software_permitted": False,
            "note": "MCA V3 is a portal-login flow with no public filing "
                    "API — PracticeSync prepares the figures and evidence; "
                    "the signatories file on the portal.",
        },
        stages,
    )
