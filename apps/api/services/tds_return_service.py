"""
TDS return service — derives Form 26Q (vendor/non-salary TDS, IT Act §194
series) and Form 24Q (salary TDS, IT Act §192) ENTIRELY from posted
accounting data, and reconciles the computed TDS to the GL TDS Payable
control accounts.

Single source of truth (mirrors services/gst_return_service.py's audit-H8
pattern): returns are NEVER computed from frontend payloads. The flow is:

    posted purchase bills (26Q) / finalized payroll runs (24Q)
            │  →  domain.tds.TDSComputer  →  26Q / 24Q payload
            │
            └── the SAME documents posted the journal entries, so the
                return's total TDS deducted must equal the credit movement
                on "TDS Payable" (26Q) / "TDS Payable - Salary" (24Q).
                Reconciliation is done against the SPECIFIC journal entries
                those documents posted (via their own journal_entry_id), not
                a calendar date-range scan — a payroll run's accrual journal
                is dated the day it was FINALIZED, not the payroll period
                (services/phase2_journal_service.py::journal_for_payroll),
                so a date-range query would wrongly miss a late-finalized
                run's journal (or wrongly catch an unrelated one dated the
                same day).

26Q IS RESIDENTS ONLY. Rule 31A(4)(a) gives Form 26Q the non-salary payments
to residents and (b) gives Form 27Q the payments to non-residents, so a bill
whose vendor is recorded as a non-resident (migration 308) is excluded from
this return and REPORTED in `excluded_non_resident` rather than dropped. There
is no 27Q counterpart to build it into: s.195 is the charging section for a
non-resident and its rate — nature of income x treaty x surcharge — is not
modelled anywhere in this codebase. See domain/tds/residency.py.

Known simplification: purchase debit/credit notes never adjust tds_paise in
this codebase (confirmed — routers/debit_notes.py and
routers/purchase_credit_notes.py never touch it), so a purchase return after
TDS was already deducted and deposited is not modelled here either; this
mirrors the existing system's own scope, not a gap introduced by this file.

Integer paise throughout. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

from core.ist_clock import month_end_date
from domain.reporting.model import apportion
from domain.tds.tds_computer import TDSComputer, TDSDeducteeRecord
from domain.tds.section_rates import quarter_dates
from domain.tds.residency import is_non_resident

_computer = TDSComputer()

# Posted (on-books) statuses. Drafts are off-books — no TDS liability has
# actually posted to the GL yet (mirrors gst_return_service.py's
# _SALES_POSTED / _BILL_POSTED convention).
_BILL_POSTED = ("received", "partially_paid", "paid")
_PAYROLL_POSTED = ("finalized", "paid")


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging (same audit-C6
    class as domain/reporting/sources.py's _fetch_all / gst_return_service.py's
    _paginate_all) — an un-paged .execute() silently caps at PostgREST's
    ~1000-row limit, understating TDS deducted/deposited with no error."""
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        cursor = rows[-1][key]
    return out


def _find_account_by_exact_name(db, firm_id: str, client_id: str, account_name: str) -> str | None:
    """Resolve a chart_of_accounts id by EXACT name match (firm-wide or this
    client's own account), not the ILIKE-substring pattern
    phase2_journal_service._find_account uses elsewhere.

    "TDS Payable" and "TDS Payable - Salary" are two distinct real accounts
    in the seeded chart (confirmed in the live DB), and the latter's name
    contains the former's as a substring — an ILIKE '%TDS Payable%' lookup
    with no ORDER BY before its .limit(1) can non-deterministically resolve
    to either one. That ambiguity already exists in
    phase2_journal_service.journal_for_purchase_bill's own account lookup;
    not fixed here (out of scope, and a live posting-path change deserves its
    own dedicated verification), but this reconciliation must not repeat it —
    an exact match can never be ambiguous between the two.
    """
    resp = (
        db.table("chart_of_accounts").select("id")
        .eq("firm_id", firm_id)
        .or_(f"client_id.eq.{client_id},client_id.is.null")
        .eq("account_name", account_name)
        .eq("is_active", True)
        .limit(1).execute()
    )
    return resp.data[0]["id"] if resp.data else None


def _gl_movement_for_entries(db, firm_id: str, client_id: str, account_id: str | None, journal_entry_ids: list[str]) -> int:
    """Net CREDIT movement (credit - debit) on one account, restricted to a
    specific set of journal entries — see module docstring for why this is a
    journal_entry_id lookup rather than a calendar date-range scan."""
    if not account_id or not journal_entry_ids:
        return 0
    total = 0
    ids = list(dict.fromkeys(journal_entry_ids))  # de-dupe, preserve order
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        # journal_lines rows carry no firm_id of their own (confirmed against
        # services/phase2_journal_service.py's insert payload and mirrored by
        # gst_return_service.py's identical GL query) — the firm scope comes
        # entirely from journal_entry_ids already being firm-scoped documents'
        # own journal_entry_id references.
        rows = _paginate_all(lambda chunk=chunk: db.table("journal_lines")
            .select("id, journal_entry_id, account_id, debit_paise, credit_paise")
            .eq("account_id", account_id)
            .in_("journal_entry_id", chunk))
        for r in rows:
            total += int(r.get("credit_paise") or 0) - int(r.get("debit_paise") or 0)
    return total


def _posted_vendor_tds_bills(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    return _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .gt("tds_paise", 0)
            .gte("bill_date", start).lte("bill_date", end))


def _vendors_by_id(db, firm_id: str, vendor_ids: set[str]) -> dict[str, dict]:
    if not vendor_ids:
        return {}
    # residential_status decides whether a deduction belongs in 26Q at all —
    # Rule 31A(4), migration 308.
    rows = (db.table("vendors").select("id, name, pan, residential_status")
            .eq("firm_id", firm_id).in_("id", list(vendor_ids)).execute().data) or []
    return {v["id"]: v for v in rows}


def _deposited_challans(db, firm_id: str, client_id: str, fy: str, quarter: str) -> list[dict]:
    return _paginate_all(lambda: db.table("tds_challans").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("financial_year", fy).eq("quarter", quarter))


def tds_26q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 26Q (non-salary TDS) from posted purchase bills, and
    reconcile the total TDS deducted to the "TDS Payable" GL account."""
    start, end, due_date = quarter_dates(fy, quarter)

    bills = _posted_vendor_tds_bills(db, firm_id, client_id, start, end)
    vendors = _vendors_by_id(db, firm_id, {b["vendor_id"] for b in bills if b.get("vendor_id")})

    # A NON-RESIDENT PAYEE IS NOT A 26Q DEDUCTEE. Rule 31A(4)(a) gives 26Q the
    # non-salary payments to residents; (b) gives 27Q the payments to
    # non-residents. Before migration 308 nothing recorded the difference, so
    # every deduction swept into 26Q — including a foreign remittance, which is
    # a wrong return rather than a missing one.
    #
    # Excluded BEFORE the apportionment and the journal-id list, not filtered
    # out of the deductees afterwards, so the challan apportionment, the books
    # total and the GL movement are all computed over the same set of bills and
    # the reconciliation still means what it says.
    #
    # Reported, never silent: a total that quietly drops between one quarter
    # and the next is exactly the kind of thing nobody notices until a notice
    # arrives.
    excluded_non_resident = [
        b for b in bills
        if is_non_resident((vendors.get(b.get("vendor_id")) or {}).get("residential_status"))
    ]
    if excluded_non_resident:
        excluded_ids = {b["id"] for b in excluded_non_resident}
        bills = [b for b in bills if b["id"] not in excluded_ids]

    # Non-salary challans only — a firm's TDS Payable challan for section 192
    # (salary) belongs to 24Q, not 26Q; excluded by section, defensively, even
    # though no current UI path creates a 192 challan via this table's normal
    # 26Q-facing flow.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") != "192"]

    # Apportion each section's deposited challan total across that section's
    # deducted bills (largest-remainder — domain/reporting/model.py::apportion),
    # so the sum of deductee-level tds_deposited_paise always equals the real
    # total deposited, capped at what was actually deducted (never assume more
    # was deposited than was withheld).
    by_section: dict[str, list[dict]] = {}
    for b in bills:
        by_section.setdefault(b.get("tds_section") or "", []).append(b)
    deposited_by_bill_id: dict[str, int] = {}
    for section, section_bills in by_section.items():
        deposited_total = sum(int(c.get("tds_paise") or 0) for c in challans if (c.get("section") or "") == section)
        weights = [int(b.get("tds_paise") or 0) for b in section_bills]
        shares = apportion(min(deposited_total, sum(weights)), weights)
        for b, share in zip(section_bills, shares):
            deposited_by_bill_id[b["id"]] = share

    deductees: list[TDSDeducteeRecord] = []
    for b in bills:
        vendor = vendors.get(b.get("vendor_id"), {})
        section = b.get("tds_section") or ""
        matching_challan = next((c for c in challans if (c.get("section") or "") == section), None)
        deductees.append(TDSDeducteeRecord(
            deductee_name=vendor.get("name") or "Unknown Vendor",
            deductee_pan=(vendor.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section=section,
            nature_of_payment=f"Vendor payment — Bill {b.get('bill_no') or b['id']}",
            payment_date=str(b.get("bill_date") or ""),
            payment_amount_paise=int(b.get("taxable_amount_paise") or 0),
            tds_rate_pct=int(b.get("tds_rate_bps") or 0) / 100,
            tds_deducted_paise=int(b.get("tds_paise") or 0),
            tds_deposited_paise=deposited_by_bill_id.get(b["id"], 0),
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
        ))

    payload = _computer.compute_26q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )

    tds_payable_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable")
    journal_ids = [b["journal_entry_id"] for b in bills if b.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_payable_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    matched = tds_payable_id is not None and books_paise == gl_paise

    return {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        "form": "26Q",
        "source": "posted_purchase_bills",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_payment_paise": payload.total_payment_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                "section": d.section, "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
            }
            for d in payload.deductees
        ],
        "challans": payload.challans,
        # What was deliberately left out of this return, and why. 27Q is where
        # these belong; this codebase does not compute the s.195 rate they
        # would need, so they are named here rather than silently dropped.
        "excluded_non_resident": {
            "bill_count": len(excluded_non_resident),
            "tds_paise": sum(int(b.get("tds_paise") or 0) for b in excluded_non_resident),
            "reason": "Payments to a non-resident are reported on Form 27Q "
                      "under Rule 31A(4)(b), not on 26Q.",
            "bills": [
                {"id": b.get("id"), "bill_no": b.get("bill_no"),
                 "vendor_name": (vendors.get(b.get("vendor_id")) or {}).get("name"),
                 "section": b.get("tds_section"),
                 "tds_paise": int(b.get("tds_paise") or 0)}
                for b in excluded_non_resident
            ],
        },
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "matched": matched,
            "account_found": tds_payable_id is not None,
        },
        "ca_review_required": True,
    }


def _finalized_payroll_runs(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    # month is stored "YYYY-MM"; a quarter never spans a partial month, so a
    # plain string range on "YYYY-MM" (lexicographically monotonic) is exact.
    return _paginate_all(lambda: db.table("payroll_runs").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_PAYROLL_POSTED))
            .gte("month", start[:7]).lte("month", end[:7]))


def _payroll_slips_for_runs(db, firm_id: str, run_ids: list[str]) -> list[dict]:
    if not run_ids:
        return []
    out: list[dict] = []
    for i in range(0, len(run_ids), 200):
        chunk = run_ids[i:i + 200]
        out.extend(_paginate_all(lambda chunk=chunk: db.table("payroll_slips").select("*")
            .in_("run_id", chunk)))
    return out


def _employees_by_id(db, firm_id: str, employee_ids: set[str]) -> dict[str, dict]:
    if not employee_ids:
        return {}
    rows = (db.table("payroll_employees").select("id, name, pan")
            .eq("firm_id", firm_id).in_("id", list(employee_ids)).execute().data) or []
    return {e["id"]: e for e in rows}


def tds_24q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 24Q (salary TDS) from finalized payroll runs, and reconcile
    the total TDS deducted to the "TDS Payable - Salary" GL account."""
    start, end, due_date = quarter_dates(fy, quarter)

    runs = _finalized_payroll_runs(db, firm_id, client_id, start, end)
    run_ids = [r["id"] for r in runs]
    runs_by_id = {r["id"]: r for r in runs}
    slips = [s for s in _payroll_slips_for_runs(db, firm_id, run_ids) if int(s.get("tds_paise") or 0) > 0]
    employees = _employees_by_id(db, firm_id, {s["employee_id"] for s in slips if s.get("employee_id")})

    deductees: list[TDSDeducteeRecord] = []
    for s in slips:
        emp = employees.get(s.get("employee_id"), {})
        run = runs_by_id.get(s.get("run_id"), {})
        month = str(run.get("month") or "")
        # Representative payment date — last day of the payroll month; the run
        # header carries no per-slip payment date, and this is descriptive
        # only (the FY/quarter driving the return is the caller's own input).
        month_end = f"{month}-28" if not month else month
        try:
            month_end = month_end_date(month)
        except (ValueError, IndexError):
            pass
        gross = int(s.get("gross_paise") or 0)
        tds = int(s.get("tds_paise") or 0)
        deductees.append(TDSDeducteeRecord(
            deductee_name=emp.get("name") or "Unknown Employee",
            deductee_pan=(emp.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section="192",
            nature_of_payment=f"Salary — {month}",
            payment_date=month_end,
            payment_amount_paise=gross,
            tds_rate_pct=round(tds * 100 / gross, 4) if gross > 0 else 0.0,
            tds_deducted_paise=tds,
            tds_deposited_paise=0,  # apportioned below
            challan_no="", bsr_code="", challan_date="",
        ))

    # Section 192 challans for the quarter (deposited salary TDS), apportioned
    # across slips the same way 26Q apportions across bills.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") == "192"]
    deposited_total = sum(int(c.get("tds_paise") or 0) for c in challans)
    weights = [d.tds_deducted_paise for d in deductees]
    shares = apportion(min(deposited_total, sum(weights)), weights) if deductees else []
    matching_challan = challans[0] if challans else None
    deductees = [
        TDSDeducteeRecord(
            deductee_name=d.deductee_name, deductee_pan=d.deductee_pan, section=d.section,
            nature_of_payment=d.nature_of_payment, payment_date=d.payment_date,
            payment_amount_paise=d.payment_amount_paise, tds_rate_pct=d.tds_rate_pct,
            tds_deducted_paise=d.tds_deducted_paise, tds_deposited_paise=share,
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
        )
        for d, share in zip(deductees, shares)
    ]

    payload = _computer.compute_24q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )

    tds_salary_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable - Salary")
    journal_ids = [r["journal_entry_id"] for r in runs if r.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_salary_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    matched = tds_salary_id is not None and books_paise == gl_paise

    return {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        "form": "24Q",
        "source": "finalized_payroll_runs",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_salary_paise": payload.total_salary_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                "section": d.section, "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
            }
            for d in payload.deductees
        ],
        "challans": payload.challans,
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "matched": matched,
            "account_found": tds_salary_id is not None,
        },
        "ca_review_required": True,
    }
