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

THE RETURN FILE, AND THE STAGE THAT EXISTS TO SHOW WHAT IS MISSING
    Most Indian CAs do not fill an ITR in the browser: their software emits
    the Department's JSON and they upload it. So the honest question this
    walk-through has to answer is "could PracticeSync hand me that file?",
    and the answer is a specific no with named parts — which is more useful
    to a CA evaluating the product than any amount of ceremony.

    The stage reads the answer out of domain/income_tax/itr_json.py rather
    than restating it, so it cannot go stale the way the old copy did. That
    copy said there was "no ITR JSON generator"; the Department's schemas for
    AY 2026-27 have since been downloaded by hand and committed, and every
    field path is verified against them by tests/test_itr_schema_paths.py. Two
    things are genuinely missing and both are named:

      SW########. Every schema requires CreationInfo.SWCreatedBy and
      CreationInfo.JSONCreatedBy to match a software-provider id the
      Department issues to registered providers, and REJECTS a file without
      one whatever else it contains. itr_json.software_provider_id() reads it
      from ITR_SOFTWARE_PROVIDER_ID and returns None until one is issued.
      This is the same shape as GSP for GST: a registration, not code.

      A WHOLE RETURN. ITRPayload carries the tax figures. A file the portal
      accepts also needs PersonalInfo, FilingStatus, Verification and bank
      details, and for ITR-3/5/6 the balance sheet and profit-and-loss
      schedules. Emitting the fragment would produce something that looks
      like a return and fails at upload.

ref: {"filing_id": <itr_filings.id>} — the prepared filing the CA is walking
through. The demo is gated on status == 'ready_for_filing', the last stop
before 'filed' in domain/income_tax/itr_workflow.py's state machine: a draft
has not finished review, and a filed return has nothing left to walk through.
"""
from __future__ import annotations

from domain.income_tax import itr_json

from services import compliance_engine
from services.filing_demo import common


def _return_file_stage(itr_form: str, assessment_year: str) -> dict:
    """What PracticeSync could hand a CA to upload, and what is missing.

    Every row is READ from domain/income_tax/itr_json.py — the schema mapping
    it holds and the provider id it looks for — rather than restated here.
    That module is the authority on what would be refused and why; a
    walk-through that copies its answer goes stale the moment the answer
    changes, which is exactly what happened to the sentence this replaces.
    """
    mapping = itr_json.FIELD_MAPPINGS.get(itr_form)
    provider = itr_json.software_provider_id()

    if mapping is not None and mapping.verified and mapping.paths:
        schema_file = mapping.schema_file or "the committed schema"
        schema_state = (
            f"Held and verified — {schema_file}, {len(mapping.paths)} field "
            "paths resolved against it and re-checked by "
            "tests/test_itr_schema_paths.py on every run.")
    else:
        schema_state = (
            "Not held for this form. The Department publishes a new JSON "
            "schema per form per assessment year; it is downloaded by hand, "
            "not generated.")

    if provider:
        # Reachable only where a real id has been issued and configured. Say
        # it is present, never print it — it identifies the provider.
        provider_state = ("Configured. This is the one thing that used to "
                          "stop a file being produced.")
    else:
        provider_state = (
            "NOT HELD. The Department issues this to registered software "
            "providers; a file whose CreationInfo does not carry one is "
            "rejected at upload whatever else it contains. It comes with "
            "e-Return Intermediary registration — a commercial and "
            "compliance step, not a coding one.")

    return common.table_stage(
        "The return file — what is ready, and what is not",
        "Most CAs file an ITR by uploading the Department's JSON rather than "
        "typing the return into the browser, so this is the honest state of "
        "that file for "
        f"{itr_form}, AY {assessment_year or 'this year'}. It is read out of "
        "domain/income_tax/itr_json.py, which refuses to write a file rather "
        "than write a plausible one — the figures below are correct and "
        "correctly placed, and that is not the same as a return.",
        ["What the portal needs", "State in PracticeSync today"],
        [
            [{"text": f"The Department's JSON schema for {itr_form}"},
             {"text": schema_state}],
            [{"text": "CreationInfo.SWCreatedBy and JSONCreatedBy "
                      "(a SW######## software-provider id)"},
             {"text": provider_state}],
            [{"text": "PersonalInfo, FilingStatus, Verification, bank details"},
             {"text": "Not in the computed payload. These are the taxpayer's "
                      "own particulars and belong to the return, not to the "
                      "computation."}],
            [{"text": "Balance sheet and profit-and-loss schedules "
                      "(ITR-3, ITR-5, ITR-6)"},
             {"text": "Not in the computed payload. The books hold them; "
                      "assembling them into the form's schedules is not "
                      "built."}],
        ],
        footer=[{"text": "So: the figures are ready to key into the "
                         "Department's own offline utility, and PracticeSync "
                         "will not emit a .json that looks like a return and "
                         "fails at upload."},
                {"text": ""}],
        cta="Proceed to verification",
    )


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

    # IT Act §140A: where tax is still payable after TDS and advance tax, the
    # assessee pays it — with §234A/B/C interest — BEFORE furnishing the
    # return, by challan on e-Pay Tax. There is no payment stage in this
    # walk-through because there is none in the filing flow either: the
    # challan is a separate act on the portal and the return simply will not
    # validate until it is done. Said on the screen rather than left to be
    # discovered, and only where the return actually shows tax payable —
    # telling a refund case to pay something would be worse than silence.
    headline = figures[0] if figures else {}
    if headline.get("label") == "Net tax payable" and int(
            headline.get("paise") or 0) > 0:
        summary_note += (
            " This return still shows tax payable, so the self-assessment "
            "tax under IT Act §140A — with any interest under §234A, §234B "
            "and §234C — is paid by challan on e-Pay Tax BEFORE the return "
            "is furnished. That is a separate act on the portal, which is "
            "why there is no payment step in this sequence.")

    stages = [
        common.summary_stage(
            f"{itr_form} · AY {ay}",
            summary_note,
            figures,
            cta="Proceed",
        ),
        # The return FILE, and what is missing from it. Placed here because
        # this is where it sits in the real journey — the software's output
        # is what the CA carries to the portal — and because a CA evaluating
        # PracticeSync is entitled to the answer before the ceremony, not
        # buried in a transmit step nobody reads.
        _return_file_stage(itr_form, str(ay)),
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
            "The code is entered on incometax.gov.in, never here. PracticeSync"
            " has no field that takes an OTP and will not have one when"
            " filing is real — a box in your practice software that"
            " accepts a portal credential is a credential-capture"
            " surface whatever it is labelled.",
        ),
        common.transmit_stage([
            # Honest about the missing artefact, and specific about WHY —
            # the schemas are held and the paths verified; what is missing is
            # the SW######## provider id and the non-computed half of the
            # return. The "return file" stage above carries the detail; this
            # step must not quietly claim the file exists.
            {"key": "assemble",
             "label": "Return file — NOT produced by PracticeSync "
                      "(no SW######## provider id); on a real filing this is "
                      "the JSON you upload"},
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
        # What changes when this is real. ITR is the flow where the answer is
        # longest, because it is the only one where software is genuinely
        # permitted — so the gate is worth naming precisely rather than as
        # "registration". The four serial requirements below are recorded
        # against the compliance marker in domain/income_tax/itr_json.py.
        "Two registrations, and one of them has a deployment cost. A "
        "Type-2 e-Return Intermediary registration with the Income Tax "
        "Department is what lets software file at all, and it carries the "
        "SW######## software-provider id that every ITR JSON must name in "
        "CreationInfo — without it a file is rejected at upload however "
        "correct the figures are. ERI registration runs through four serial "
        "gates: a net worth of ₹1 crore or an application through a CA firm, "
        "an ISA/CISA due-diligence certificate, certification on the "
        "Department's UAT environment, and production access limited to four "
        "whitelisted INDIAN static IPs — the last is a hosting problem, not "
        "a coding one, since this API runs in Singapore. On the day it is "
        "done, PracticeSync produces the return file and transmits it, and "
        "the CA stops re-keying the computation into an offline utility. "
        "What does NOT change: verification stays the taxpayer's under §140, "
        "and the 30-day clock still runs from transmission.",
        stages,
    )
