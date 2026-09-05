"""TDS quarterly statement (Form 24Q / 26Q) filing demo.

THE REAL CHANNEL THIS MIMICS
    A TDS statement is NOT filed on TRACES — a misconception this product's
    own screens carried until this flow was built. The real sequence, under
    IT Act §200(3) read with Rule 31A:

    prepare the return file (RPU or software) → download the CSI file from
    e-Pay Tax → validate with the FVU (File Validation Utility), which
    cross-checks the statement's challans against the CSI → upload the .fvu
    file on incometax.gov.in, logged in with the DEDUCTOR's TAN → sign with
    DSC or EVC → the acknowledgement is a 15-digit Token number, also called
    the Provisional Receipt Number (PRN). The offline alternative is a
    TIN-FC counter with a signed Form 27A.

    TRACES is post-filing only: Form 16/16A downloads, defaults, and
    correction statements. There is no public filing API — the upload is
    manual on the portal — so real_channel.software_permitted is False.

ref: {"return_id": <tds_returns.id>} — the saved 24Q/26Q row the CA walks
through. It must be ca_approved: the demo starts where the real upload does.
Read-only end to end — this module performs no write of any kind.
"""
from __future__ import annotations

from domain.tds import vocabulary

from datetime import date

from services.filing_demo import common

# ₹200 per day of default — IT Act §234E, in integer paise.
_S234E_FEE_PER_DAY_PAISE = 200_00


def _inr(paise: int) -> str:
    """Integer paise → a rupee string for PROSE only (warning sentences).
    Tabular and figure money stays raw paise for the frontend to format —
    this exists because a warning stage carries text, not cells. Integer
    arithmetic throughout; no float ever touches the amount."""
    rupees_part, paise_part = divmod(abs(int(paise)), 100)
    body = f"{rupees_part:,}" if paise_part == 0 else f"{rupees_part:,}.{paise_part:02d}"
    return f"{'-' if paise < 0 else ''}₹{body}"


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """ref: {"return_id": <tds_returns.id>} — see the module docstring."""
    return_id = str(ref.get("return_id") or "")
    if not return_id:
        raise ValueError("tds demo needs ref.return_id")

    rows = (db.table("tds_returns").select("*")
            .eq("id", return_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("TDS return not found")
    rec = rows[0]

    form = str(rec.get("return_type") or "")
    # Migration 037 also allows 27Q (non-resident) and 27EQ (TCS); this
    # walk-through covers the two forms the product computes from books.
    if form not in ("24Q", "26Q"):
        raise ValueError(
            f"This walk-through covers Form 24Q and 26Q; Form {form or '?'} "
            "is not demoed yet.")

    status = str(rec.get("status") or "")
    if status == "filed":
        raise ValueError(
            "This TDS return is already recorded as filed — there is nothing "
            "left to walk through.")
    if status != "ca_approved":
        raise ValueError(
            f"This TDS return is still '{status or 'pending'}'. The "
            "walk-through starts where the real upload does — from a "
            "CA-approved statement.")

    fy = str(rec.get("financial_year") or "")
    quarter = str(rec.get("quarter") or "")

    # THE STORED return_type IS AN INTERNAL KEY; WHAT THE CA READS IS THE
    # PERIOD'S OWN FORM NUMBER. tds_returns.return_type holds "24Q"/"26Q" (and
    # migration 037's CHECK constrains it to those), so the row stays keyed that
    # way — rekeying would orphan every saved return. But this walk-through is
    # meant to be portal-faithful, and from FY 2026-27 the portal shows Form 138
    # and Form 140 under the Income-tax Act 2025. A demo that rehearses a form
    # number the portal no longer accepts teaches the wrong step.
    _kind = (vocabulary.SALARY if form == "24Q"
             else vocabulary.RESIDENT_NON_SALARY)
    _vocab = vocabulary.vocabulary_for(fy) if fy else None
    form_no = _vocab.statement(_kind) if _vocab else form

    # Figures come from the saved row. A quick-created row often carries
    # zeros; the honest fallback is the same from-books computation the
    # Compute screen uses, and if even that fails the demo shows zeros WITH
    # a note — it never invents a number. (The from-books path reads the
    # quarter's posted documents, which is heavier than this module's usual
    # header-row diet; it runs only for a row saved without figures, and the
    # alternative — displaying invented money — is worse than the read.)
    deducted = int(rec.get("total_deductions_paise") or 0)
    deposited = int(rec.get("total_deposits_paise") or 0)
    deductee_count = int(rec.get("deductee_count") or 0)
    figures_note = ""
    if deducted == 0 and deposited == 0:
        from services import tds_return_service
        compute = (tds_return_service.tds_24q_from_books if form == "24Q"
                   else tds_return_service.tds_26q_from_books)
        try:
            # Deductor identity fields are display-only in the computed
            # payload and unknown here; blanks change no total.
            books = compute(db, firm_id, client_id, fy, quarter, "", "", "", "")
            deducted = int(books.get("total_tds_deducted_paise") or 0)
            deposited = int(books.get("total_tds_deposited_paise") or 0)
            deductee_count = int(books.get("deductee_count") or 0)
            figures_note = (
                " This return was saved without computed figures, so these "
                "were computed from the posted books just now."
                if deducted or deposited or deductee_count else
                " This return was saved without computed figures and the "
                "books show no TDS for this quarter — the zeros are real, "
                "not placeholders.")
        except Exception:
            figures_note = (
                " This return was saved without computed figures and they "
                "could not be computed from the books, so zeros are shown "
                "rather than invented numbers.")

    # Due date from the single authority — services/compliance_engine.py::
    # tds_return_due_date (Rule 31A). Never restated as literals here.
    from services.compliance_engine import tds_return_due_date
    due = None
    try:
        # financial_year is "2025-26"; the authority wants the calendar year
        # Mar 31 falls in (FY start year + 1).
        due = tds_return_due_date(quarter, int(fy[:4]) + 1)
    except (ValueError, KeyError, IndexError):
        due = None  # a malformed FY/quarter loses the due-date extras only

    figures = [
        {"label": "Form", "text": form},
        {"label": "TDS deducted", "paise": deducted},
        {"label": "TDS deposited", "paise": deposited},
        {"label": "Deductees", "text": str(deductee_count)},
    ]
    if due is not None:
        figures.append({"label": "Due date (Rule 31A)", "text": due.isoformat()})

    stages = [
        common.summary_stage(
            f"Form {form_no} · {quarter} {fy}",
            "On the e-filing portal this statement travels as an .fvu file, "
            "uploaded under the deductor's TAN login. These are the figures "
            "the FVU-validated file would carry." + figures_note,
            figures,
            cta="Proceed to file",
        ),
    ]

    # The quarter's ITNS 281 challans, deposited through e-Pay Tax. Split by
    # section the way services/tds_return_service.py splits when computing:
    # §192 (salary) challans belong to 24Q, everything else to 26Q.
    challans = (db.table("tds_challans").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("financial_year", fy).eq("quarter", quarter)
                .execute().data) or []
    # Both section vocabularies, always. A 2026-27 deposit may sit in the table
    # as "192" (this codebase's internal key) or as "392" (copied off the
    # challan the CA paid), and splitting on one name would move a salary
    # challan into the non-salary statement — where it reconciles against
    # nothing.
    _salary_sections = {"192", "392"}
    if form == "24Q":
        challans = [c for c in challans
                    if (c.get("section") or "") in _salary_sections]
    else:
        challans = [c for c in challans
                    if (c.get("section") or "") not in _salary_sections]
    if challans:
        challan_rows = [
            [{"text": str(c.get("challan_no") or "")},
             {"text": str(c.get("bsr_code") or "")},
             {"text": str(c.get("payment_date") or "")},
             {"text": str(c.get("minor_head") or "")},
             {"paise": int(c.get("total_paise") or 0)}]
            for c in challans
        ]
        stages.append(common.table_stage(
            "Challans in this statement",
            "Deposited through e-Pay Tax on incometax.gov.in (challan "
            "ITNS 281). The FVU cross-checks every challan against the CSI "
            "file before the portal will accept the statement.",
            ["Challan no", "BSR code", "Deposit date", "Minor head", "Amount"],
            challan_rows,
            footer=[{"text": "Total"}, {"text": ""}, {"text": ""}, {"text": ""},
                    {"paise": sum(int(c.get("total_paise") or 0) for c in challans)}],
        ))

    # IT Act §234E: ₹200 for every day the statement is late, capped at the
    # TDS amount. Shown only when both the lateness and the cap can be
    # computed honestly from the record — a demo that guesses a fee teaches
    # a wrong number. (§271H's ₹10,000–₹1,00,000 penalty for late/incorrect
    # statements is discretionary and not computable from a row, so the
    # walk-through does not state a figure for it.)
    warning = (
        "Once uploaded and accepted, a TDS statement cannot be withdrawn or "
        "revised. An error in a filed statement is fixed by filing a "
        "correction statement (tracked on TRACES) — the original filing "
        "stands.")
    if due is not None and deducted > 0:
        days_late = (date.today() - due).days
        if days_late > 0:
            fee = min(days_late * _S234E_FEE_PER_DAY_PAISE, deducted)
            warning += (
                f" This statement is past its Rule 31A due date "
                f"({due.isoformat()}): the late-filing fee under IT Act "
                f"§234E is ₹200 per day — {_inr(fee)} here, capped at the "
                "TDS amount — payable before the statement is filed.")

    stages += [
        common.warning_stage(warning),
        common.declaration_stage(
            # Form 27A's certification — the form's own wording, verbatim.
            "I/We hereby certify that all the particulars furnished above "
            "are correct and complete.",
            "Person responsible for paying (IT Act §204)",
            ["Person responsible for paying / principal officer"],
            "This certification is the DEDUCTOR's — made by the person "
            "responsible for paying under IT Act §204 — never the CA "
            "firm's. PracticeSync prepares the statement; the deductor's "
            "own signatory authorises the upload.",
        ),
        common.signature_stage([
            {"key": "dsc", "label": "Upload with DSC", "otp": False,
             "note": "Digital signature registered against the TAN on the "
                     "e-filing portal"},
            {"key": "evc", "label": "Upload with EVC", "otp": True,
             "note": "Electronic verification code to the mobile and email "
                     "registered on the e-filing portal"},
        ]),
        common.otp_stage(
            "An EVC would now be sent to the mobile number and email "
            "registered for the deductor on the e-filing portal.",
            "Any six digits will do here — there is no OTP to be right about.",
        ),
        common.transmit_stage([
            {"key": "generate", "label": "Return file generated"},
            {"key": "csi", "label": "CSI file downloaded from e-Pay Tax"},
            {"key": "fvu", "label": "FVU validation passed — challans "
                                    "matched against CSI"},
            {"key": "upload", "label": "Uploaded to the e-filing portal "
                                       "(TAN login)"},
            {"key": "accept", "label": "Portal accepted the statement"},
        ]),
        common.result_stage(
            "Income Tax Department",
            "Token number / Provisional Receipt Number (PRN)",
            common.specimen_tds_prn(return_id),
            f"Form {form_no} for {quarter} {fy} — on the real portal this Token "
            "would appear under e-File → View Filed Forms, and TRACES would "
            "pick the statement up for Form 16/16A once processed.",
            [
                "Nothing was filed.",
                "To file for real: generate the return file, validate it "
                "with the FVU using the CSI from e-Pay Tax, upload the .fvu "
                "on incometax.gov.in under the deductor's TAN login, then "
                "record the Token/PRN here with Mark as Filed.",
            ],
        ),
    ]

    return common.envelope(
        "tds",
        f"File Form {form_no} (TDS)",
        f"{fy} · {quarter}",
        return_id,
        {
            "how": "Prepared as a return file, validated with the FVU "
                   "against the CSI from e-Pay Tax, and uploaded on "
                   "incometax.gov.in under the deductor's TAN login, signed "
                   "with DSC or EVC. TRACES is post-filing only — Form "
                   "16/16A, defaults and correction statements.",
            "software_permitted": False,
            "note": "There is no public filing API for TDS statements — the "
                    ".fvu upload is manual on the e-filing portal (or a "
                    "TIN-FC counter with a signed Form 27A).",
        },
        stages,
    )
