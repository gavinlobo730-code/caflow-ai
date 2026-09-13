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

26Q IS RESIDENTS ONLY, AND 27Q IS WHERE THE REST GO. Rule 31A(4)(a) gives Form
26Q the non-salary payments to residents and (b) gives Form 27Q the payments to
non-residents, so a document whose vendor is recorded as a non-resident
(migration 308) is excluded from 26Q and REPORTED in `excluded_non_resident`
rather than dropped.

    This paragraph used to end "There is no 27Q counterpart to build it into:
    s.195 ... is not modelled anywhere in this codebase". Both halves stopped
    being true — domain/tds/section_195.py rates the remittance, and
    tds_27q_from_books below files it (TDS-09). Residency routes a row, not the
    section number: §194E, §194LB/§194LC and §196D all charge non-residents and
    all report on 27Q too. See domain/tds/residency.py.

BOTH VENDOR RETURNS READ TWO KINDS OF DOCUMENT. §194 and §195 charge at the
time of credit "or at the time of payment thereof, whichever is EARLIER", so a
vendor ADVANCE is a charging event in its own right (migration 358) and its
deduction posts to the same control account with the same challan obligation.
Reading only `purchase_bills` left a real deduction in the ledger and in the
register but off the statement — and then the reconciliation failed, because
the GL movement included it.

A PURCHASE RETURN AFTER THE TAX WAS WITHHELD IS REPORTED, NOT ADJUSTED. The
FIGURES still do not move — a note changes neither `payment_amount_paise` nor
`tds_paise` — because §194's charge on "the aggregate of the sums credited or
paid" and §199's credit to the deductee for tax already paid over point in
opposite directions, and which applies turns on when the challan went, which
the books do not record. What changed (PUR-23 ≡ TDS-32) is that it is no
longer SILENT: `_credit_moved_gaps` names every bill in the quarter whose
credit a note has moved since the deduction, in `statutory_gaps`, so the CA
assembling the return sees it before the vendor's 26AS shows income they did
not earn. `domain/tds/purchase_return.py` is the rule; both note routers now
resync the register on issue, which its own docstring always claimed happened
"on every transition".

Integer paise throughout. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

import logging

from domain.tds import vocabulary as _vocabulary

from core.ist_clock import month_end_date
from domain.tds import challan_mapping
from domain.tds.tds_computer import (
    TDSComputer, TDSDeducteeRecord, TDS27QDeducteeRecord,
)
from domain.tds.section_rates import quarter_dates
from domain.tds.residency import is_non_resident
from domain.tds.purchase_return import credit_moved_after_deduction

_logger = logging.getLogger("caflow.tds_return")

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


def _posted_vendor_tds_bills_including_nil_195(
        db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """26Q's bill source PLUS the §195 remittances that withheld nothing.

    Two narrow queries rather than one wide one. A quarter's purchase bills are
    proportional to transaction volume, so fetching them all and filtering in
    Python would break CLAUDE.md's reporting rule; `.gt("tds_paise", 0)` and
    `.eq("tds_section", "195")` each stay selective, and the ids are merged.
    """
    withheld = _posted_vendor_tds_bills(db, firm_id, client_id, start, end)
    nil_195 = _paginate_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .eq("tds_section", "195")
            .gte("bill_date", start).lte("bill_date", end))
    by_id = {r["id"]: r for r in withheld}
    for r in nil_195:
        by_id.setdefault(r["id"], r)
    return list(by_id.values())


def _withholding_advances(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """Vendor payments that withheld — the OTHER half of the charging event.

    §194 and §195 charge at credit or payment, whichever is EARLIER, and
    migration 358 made an advance withhold. Those deductions post to the same
    TDS Payable control account and carry the same challan obligation, so a
    return that read only `purchase_bills` would leave a real deduction off the
    statement it belongs on while the GL and the register both hold it.

    `tds_base_paise` rather than `tds_paise` is the filter, because a §195
    remittance that withheld NIL is still reported on 27Q with a reason —
    26Q's own resident filter is applied by the caller.
    """
    rows = _paginate_all(lambda: db.table("purchase_payments").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .gt("tds_base_paise", 0)
            .gte("payment_date", start).lte("payment_date", end))
    return [r for r in rows if not r.get("is_reversed")]


def _as_deduction_event(row: dict, *, kind: str) -> dict:
    """One shape for a bill and for an advance, so the return builders branch once.

    A bill's base is its taxable value excluding GST (CBDT Circular 23/2017);
    an advance's is `tds_base_paise`, the unallocated part alone — the allocated
    part settled bills that were charged when they were credited.
    """
    if kind == "bill":
        return {
            "id": row["id"], "kind": "bill", "vendor_id": row.get("vendor_id"),
            "section": row.get("tds_section") or "",
            "on_date": str(row.get("bill_date") or ""),
            "doc_no": row.get("bill_no") or row["id"],
            "narration": f"Vendor payment — Bill {row.get('bill_no') or row['id']}",
            "base_paise": int(row.get("taxable_amount_paise") or 0),
            "tds_paise": int(row.get("tds_paise") or 0),
            "rate_bps": int(row.get("tds_rate_bps") or 0),
            "surcharge_paise": int(row.get("tds_surcharge_paise") or 0),
            "cess_paise": int(row.get("tds_cess_paise") or 0),
            "nature": row.get("tds_nature_of_income"),
            "basis": row.get("tds_basis"),
            "form_15ca_ack_no": row.get("form_15ca_ack_no"),
            "journal_entry_id": row.get("journal_entry_id"),
        }
    return {
        "id": row["id"], "kind": "advance", "vendor_id": row.get("vendor_id"),
        "section": row.get("tds_section") or "",
        "on_date": str(row.get("payment_date") or ""),
        "doc_no": row.get("payment_no") or row["id"],
        "narration": f"Advance to vendor — Payment {row.get('payment_no') or row['id']}",
        "base_paise": int(row.get("tds_base_paise") or 0),
        "tds_paise": int(row.get("tds_paise") or 0),
        "rate_bps": int(row.get("tds_rate_bps") or 0),
        "surcharge_paise": int(row.get("tds_surcharge_paise") or 0),
        "cess_paise": int(row.get("tds_cess_paise") or 0),
        "nature": row.get("tds_nature_of_income"),
        "basis": row.get("tds_basis"),
        "form_15ca_ack_no": None,
        "journal_entry_id": row.get("journal_entry_id"),
    }


def _vendors_by_id(db, firm_id: str, vendor_ids: set[str]) -> dict[str, dict]:
    if not vendor_ids:
        return {}
    # residential_status decides whether a deduction belongs in 26Q at all —
    # Rule 31A(4), migration 308.
    # country_of_residence and tax_identification_number are 27Q's own
    # identifiers for a payee with no Indian PAN (migration 308) — read here
    # rather than joined at filing time, so one query serves both returns.
    rows = (db.table("vendors")
            .select("id, name, pan, residential_status, country_of_residence, "
                    "tax_identification_number")
            .eq("firm_id", firm_id).in_("id", list(vendor_ids)).execute().data) or []
    return {v["id"]: v for v in rows}


def _deposited_challans(db, firm_id: str, client_id: str, fy: str, quarter: str) -> list[dict]:
    return _paginate_all(lambda: db.table("tds_challans").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("financial_year", fy).eq("quarter", quarter))


def _section_labels(fy: str, sections) -> tuple[dict[str, str], list[str]]:
    """{stored 1961 code -> the code the PERIOD's own Act names}, and the gaps.

    THE FORM NUMBER WAS TRANSLATED AND THE SECTIONS WERE NOT (TDS-17). A FY
    2026-27 26Q came back as `"form": "140"` — right, because the Income-tax
    Act 2025 renumbered the statements — with every deductee line still citing
    `194J`, which that Act does not contain. `domain/tds/vocabulary.py:312`
    says in as many words that it exists to prevent exactly this.

    TRANSLATED AT THE EMISSION DICT, NOWHERE ELSE. `d.section` is the stored
    ROUTING key: it came off `tds_deductions.tds_section`, it groups the
    challan match (`challan_mapping.parent_of`), and it is what
    `section_rates` is keyed on. Rekeying any of those is the thing CLAUDE.md
    forbids — and it would break the challan match outright, because a challan
    records what somebody typed and says "194J" in every period.

    The 1961 code travels WITH the label as `section_1961` on each deductee,
    because §393(1) has no reverse: the whole 194-series collapses into it, so
    a reader given only the label cannot get back to the section that produced
    it. Anything reading the payload back to route or reconcile must use that
    field. (`lib/data/tds.ts` writes the payload into `tds_returns.fvu_json`,
    so both land in a JSONB snapshot; the routing keys beside the labels are
    what keep it usable.)

    A section the 2025 Act has no recorded code for is NOT guessed: the stored
    code is kept and the omission is named in `statutory_gaps`, beside the
    payment-code gap the vocabulary already reports.
    """
    vocab = _vocabulary.vocabulary_for(fy)
    labels: dict[str, str] = {}
    gaps: list[str] = []
    seen = {str(c or "").strip() for c in sections}
    for code in sorted(c for c in seen if c):
        try:
            labels[code] = vocab.section(code)
        except _vocabulary.VocabularyError:
            labels[code] = code
            gaps.append(
                f"No {vocab.act_name} section code is recorded for {code}. The "
                f"line is shown under its Income-tax Act 1961 section; check it "
                f"against the notified correspondence before filing.")
    return labels, gaps


def _accumulate_note_totals(rows, bucket: dict) -> None:
    """Sum the ISSUED, undeleted notes' taxable value per bill.

    The one place the "which notes count" rule lives for both note kinds — a
    draft note has reversed nothing and a soft-deleted one was a mistake, and
    spelling that twice is how the two sides come to disagree about a draft.
    """
    for r in rows:
        if (r.get("status") or "") != "issued" or r.get("deleted_at"):
            continue
        k = r.get("purchase_bill_id")
        bucket[k] = bucket.get(k, 0) + int(r.get("taxable_amount_paise") or 0)


def _credit_moved_gaps(db, firm_id: str, events: list[dict]) -> list[str]:
    """A purchase return, or a §34(3) undercharge note, against a bill in this
    quarter that already withheld (PUR-23 ≡ TDS-32).

    The module docstring used to end "purchase debit/credit notes never adjust
    tds_paise in this codebase ... so a purchase return after TDS was already
    deducted and deposited is not modelled here either". That is still true of
    the FIGURES and deliberately so — domain/tds/purchase_return sets out why
    the statute leaves two lawful answers and the books hold neither of the
    facts that pick between them. What was not acceptable is that it was also
    SILENT: the deductee row reported a credit that had been partly reversed,
    the vendor's 26AS showed income they did not earn, and the CA assembling
    the quarter had no way to know.

    Read by BILL ID rather than by date. The note that matters most is the one
    raised in a LATER quarter against this quarter's bill, and a date-ranged
    query is exactly the one that misses it. What crosses the wire is
    proportional to the notes, not to the ledger.

    An advance carries no notes — a note is raised against a BILL — so only
    bill events are asked about.
    """
    bills = {e["id"]: e for e in events
             if e.get("kind") == "bill" and int(e.get("tds_paise") or 0) > 0}
    if not bills:
        return []
    ids = list(bills)
    returned: dict[str, int] = {}
    increased: dict[str, int] = {}
    # THE TABLE NAME IS A LITERAL AT EACH READ, and that is not style.
    # `tests/test_backend_columns_exist_pg.py` can only check a column against
    # the real schema when it can READ the table name — `db.table(table)` with
    # a variable is invisible to it, and the first draft of this function put
    # both reads inside one `for table, bucket in (...)` loop, which took ten
    # column references out of that check's coverage and tripped its
    # unreadable-reference budget. Two spellings of the same three lines is the
    # price of keeping the coverage; the SHAPE is shared in `_note_totals`
    # below, so the rule itself still exists once.
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        try:
            rows = _paginate_all(lambda chunk=chunk: db.table("debit_notes")
                    .select("id, purchase_bill_id, taxable_amount_paise, status, deleted_at")
                    .eq("firm_id", firm_id).in_("purchase_bill_id", chunk))
        except Exception as e:                                  # noqa: BLE001
            # A gap that cannot be measured is reported as absent rather than
            # failing the whole return build. The quarter still assembles; what
            # is lost is one warning, and the log says so.
            _logger.error("could not read debit_notes against this quarter's bills: %s", e)
            rows = []
        _accumulate_note_totals(rows, returned)

        try:
            rows = _paginate_all(lambda chunk=chunk: db.table("purchase_credit_notes")
                    .select("id, purchase_bill_id, taxable_amount_paise, status, deleted_at")
                    .eq("firm_id", firm_id).in_("purchase_bill_id", chunk))
        except Exception as e:                                  # noqa: BLE001
            _logger.error("could not read purchase_credit_notes against this "
                          "quarter's bills: %s", e)
            rows = []
        _accumulate_note_totals(rows, increased)

    out: list[str] = []
    for bill_id, e in bills.items():
        moved = credit_moved_after_deduction(
            bill_no=e.get("doc_no"), section=e.get("section"),
            credited_paise=int(e.get("base_paise") or 0),
            tds_paise=int(e.get("tds_paise") or 0),
            returned_taxable_paise=returned.get(bill_id, 0),
            increased_taxable_paise=increased.get(bill_id, 0))
        if moved:
            out.append(moved.sentence)
    return sorted(out)


def tds_26q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 26Q (non-salary TDS) from posted books, and reconcile the
    total TDS deducted to the "TDS Payable" GL account.

    TWO KINDS OF POSTED DOCUMENT WITHHOLD, not one. §194 charges at the time of
    credit "or at the time of payment thereof, whichever is EARLIER", so a
    vendor ADVANCE is a charging event in its own right (migration 358) and its
    deduction posts to the same control account and carries the same challan
    obligation. Reading only `purchase_bills` left a real deduction off the
    statement it belongs on while the GL and the register both held it — and
    then the reconciliation failed, because the GL movement included it.
    """
    start, end, due_date = quarter_dates(fy, quarter)

    events = (
        [_as_deduction_event(b, kind="bill")
         for b in _posted_vendor_tds_bills(db, firm_id, client_id, start, end)]
        + [_as_deduction_event(p, kind="advance")
           for p in _withholding_advances(db, firm_id, client_id, start, end)
           # 26Q reports DEDUCTIONS. An advance below its section's threshold
           # counts toward the year's aggregate and is not one — the same
           # asymmetry the register applies (services/tds_register_service.py).
           if int(p.get("tds_paise") or 0) > 0]
    )
    vendors = _vendors_by_id(db, firm_id, {e["vendor_id"] for e in events if e.get("vendor_id")})

    # A NON-RESIDENT PAYEE IS NOT A 26Q DEDUCTEE. Rule 31A(4)(a) gives 26Q the
    # non-salary payments to residents; (b) gives 27Q the payments to
    # non-residents. Before migration 308 nothing recorded the difference, so
    # every deduction swept into 26Q — including a foreign remittance, which is
    # a wrong return rather than a missing one.
    #
    # Excluded BEFORE the challan mapping and the journal-id list, not filtered
    # out of the deductees afterwards, so the mapping, the books total and the
    # GL movement are all computed over the same set of bills and the
    # reconciliation still means what it says.
    #
    # Reported, never silent: a total that quietly drops between one quarter
    # and the next is exactly the kind of thing nobody notices until a notice
    # arrives.
    excluded_non_resident = [
        e for e in events
        if is_non_resident((vendors.get(e.get("vendor_id")) or {}).get("residential_status"))
    ]
    if excluded_non_resident:
        excluded_ids = {e["id"] for e in excluded_non_resident}
        events = [e for e in events if e["id"] not in excluded_ids]

    # Non-salary challans only — a firm's TDS Payable challan for section 192
    # (salary) belongs to 24Q, not 26Q; excluded by section, defensively, even
    # though no current UI path creates a 192 challan via this table's normal
    # 26Q-facing flow.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") != "192"]

    # WHICH CHALLAN PAID WHICH DEDUCTION — domain/tds/challan_mapping.py, which
    # carries the reasoning and the citations.
    #
    # This used to be two separate wrong answers. The CIN on a deductee row was
    # `next(c for c in challans if section matches)` — the FIRST challan for the
    # section, in an id order arbitrary with respect to time — and Rule 30(2)
    # gives a quarter THREE monthly deposits all under the same section, so
    # every June deductee carried April's BSR code and serial. And the deposited
    # column was the section's whole quarterly deposit apportioned across the
    # section's bills by weight, so a bill fully deposited on 7 May read as
    # partly deposited whenever the QUARTER was short. A proportion is not an
    # answer to "has this vendor's tax been paid".
    #
    # It is filled FIFO by date, and grouped by PARENT section because a challan
    # records what somebody typed and a CA types "194J" whichever limb the bill
    # was under — the rule CLAUDE.md states for the 2025-Act fork, applied to a
    # clause key.
    mapping = challan_mapping.assign(events, challans, fy=fy)

    deductees: list[TDSDeducteeRecord] = []
    for e in events:
        vendor = vendors.get(e.get("vendor_id"), {})
        assigned = mapping.for_deduction(e["id"])
        matching_challan = assigned.challan
        deductees.append(TDSDeducteeRecord(
            deductee_name=vendor.get("name") or "Unknown Vendor",
            deductee_pan=(vendor.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section=e["section"],
            nature_of_payment=e["narration"],
            payment_date=e["on_date"],
            payment_amount_paise=e["base_paise"],
            tds_rate_pct=e["rate_bps"] / 100,
            tds_deducted_paise=e["tds_paise"],
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
        ))

    payload = _computer.compute_26q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees])

    tds_payable_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable")
    journal_ids = [e["journal_entry_id"] for e in events if e.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_payable_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    matched = tds_payable_id is not None and books_paise == gl_paise

    return {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # Form 140 from FY 2026-27, still 26Q for earlier periods — including a
        # belated or revised one filed today. See domain/tds/vocabulary.py.
        "form": _vocabulary.statement_form(_vocabulary.RESIDENT_NON_SALARY, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           + _sec_gaps + _credit_moved_gaps(db, firm_id, events)),
        "source": "posted_purchase_bills_and_advances",
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
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
            }
            for d in payload.deductees
        ],
        "challans": payload.challans,
        # WHAT THE CHALLAN MAPPING COULD NOT SETTLE. Not a validation error —
        # the return is assembled and the figures are right — but a deductee
        # left without a challan is a 26AS entry that will read 'U' (unmatched)
        # and a §201(1A) exposure the CA has to see BEFORE filing, not after a
        # notice. domain/tds/challan_mapping.py words them.
        "challan_gaps": mapping.gaps,
        # What was deliberately left out of this return, and where it went.
        # This used to end "…this codebase does not compute the s.195 rate they
        # would need", which stopped being true when domain/tds/section_195.py
        # was written and stopped being an excuse when tds_27q_from_books was
        # (TDS-09). The exclusion is still reported: a total that quietly drops
        # between one quarter and the next is what nobody notices until a
        # notice arrives.
        "excluded_non_resident": {
            "bill_count": len(excluded_non_resident),
            "tds_paise": sum(int(e.get("tds_paise") or 0) for e in excluded_non_resident),
            "reason": "Payments to a non-resident are reported on Form 27Q "
                      "under Rule 31A(4)(b), not on 26Q. Build 27Q for the same "
                      "quarter to file them.",
            "bills": [
                {"id": e.get("id"), "bill_no": e.get("doc_no"), "kind": e.get("kind"),
                 "vendor_name": (vendors.get(e.get("vendor_id")) or {}).get("name"),
                 "section": e.get("section"),
                 "tds_paise": int(e.get("tds_paise") or 0)}
                for e in excluded_non_resident
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


def tds_27q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 27Q — payments to NON-RESIDENTS, Rule 31A(4)(b).

    WHY THIS EXISTS (TDS-09)

    §195 deductions were computed by domain/tds/section_195.py, registered in
    full — country, TIN, surcharge, cess, non-deduction reason — excluded from
    26Q BY NAME with a reason, and given a deadline on the compliance calendar.
    There was nothing to file them on. A client pays a Singapore consultant,
    the platform gets every part of it right, and then the CA rebuilds the
    statement by hand from the deduction list.

    THE SAME BOOKS AS 26Q, SPLIT ON RESIDENCY AND NOT ON SECTION. Rule 31A(4)
    routes by who the payee is, not by which provision charges: §195 is the
    ordinary case, but §194E (non-resident sportsmen), §194LB/§194LC (interest)
    and §196D (FII income) also charge non-residents and also report here.
    Reading the same posted documents 26Q reads — bills AND advances, since
    §195 charges at credit or payment whichever is earlier — is what keeps the
    two returns from disagreeing about a quarter.

    A NIL REMITTANCE IS A ROW, which is the shape difference from 26Q. An
    ordinary import from a supplier with no permanent establishment is business
    profits and not chargeable under §195 at all (*GE India Technology Centre
    (P) Ltd v. CIT* (2010) 327 ITR 456), so the right withholding is nil — and
    the remittance is still reported, with the basis the engine resolved on.
    `_withholding_advances` filters on `tds_base_paise` rather than `tds_paise`
    precisely so a nil advance survives to here.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    start, end, due_date = quarter_dates(fy, quarter)

    events = (
        [_as_deduction_event(b, kind="bill")
         for b in _posted_vendor_tds_bills_including_nil_195(db, firm_id, client_id, start, end)]
        + [_as_deduction_event(p, kind="advance")
           for p in _withholding_advances(db, firm_id, client_id, start, end)]
    )
    vendors = _vendors_by_id(db, firm_id, {e["vendor_id"] for e in events if e.get("vendor_id")})
    events = [
        e for e in events
        if is_non_resident((vendors.get(e.get("vendor_id")) or {}).get("residential_status"))
    ]

    # §192 is salary and belongs on 24Q whoever the employee is; everything else
    # recorded for this quarter is available to this return. Excluded by section
    # defensively, exactly as 26Q does.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter)
                if (c.get("section") or "") != "192"]

    mapping = challan_mapping.assign(events, challans, fy=fy)

    deductees: list[TDS27QDeducteeRecord] = []
    for e in events:
        vendor = vendors.get(e.get("vendor_id"), {})
        assigned = mapping.for_deduction(e["id"])
        c = assigned.challan or {}
        # Why nothing was withheld, where nothing was — the engine's own
        # sentence. `tds_basis` is what section_195.py resolved on
        # (not_chargeable / treaty / act / 206aa_floor), persisted on the
        # document precisely so a NIL can be told apart from an absence months
        # later. Worded the same way services/tds_register_service.py words it,
        # because two places describing one fact is how they start to differ.
        reason = None
        if e["tds_paise"] == 0:
            reason = (f"Nil withheld under section {e['section'] or '195'} — basis "
                      f"'{e.get('basis') or 'not recorded'}'.")
        deductees.append(TDS27QDeducteeRecord(
            deductee_name=vendor.get("name") or "Unknown Vendor",
            deductee_pan=(vendor.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section=e["section"],
            # The NATURE of the income, which is what §115A and Part II rate on
            # — not the kind of work, which is what the resident series asks.
            nature_of_payment=e.get("nature") or e["narration"],
            payment_date=e["on_date"],
            payment_amount_paise=e["base_paise"],
            tds_rate_pct=e["rate_bps"] / 100,
            tds_deducted_paise=e["tds_paise"],
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=c.get("challan_no") or "",
            bsr_code=c.get("bsr_code") or "",
            challan_date=str(c.get("payment_date") or ""),
            country_of_residence=vendor.get("country_of_residence") or None,
            deductee_tin=vendor.get("tax_identification_number") or None,
            surcharge_paise=e["surcharge_paise"],
            cess_paise=e["cess_paise"],
            non_deduction_reason=reason,
        ))

    payload = _computer.compute_27q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees])

    # THE SAME CONTROL ACCOUNT AS 26Q, and that is not an oversight. §195 tax
    # credits "TDS Payable" like every §194-series deduction — one liability,
    # one challan series (ITNS 281), two statements. So the reconciliation is
    # over THIS return's own documents' journals, which is what makes it mean
    # something when both returns exist for one quarter.
    tds_payable_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable")
    journal_ids = [e["journal_entry_id"] for e in events if e.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_payable_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    # A NIL REMITTANCE MOVES NO LEDGER, so a quarter of nothing but nils
    # reconciles at zero against zero and that is correct, not a coincidence.
    matched = tds_payable_id is not None and books_paise == gl_paise

    return {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # Form 144 from FY 2026-27, still 27Q for earlier periods — including a
        # belated or revised one filed today. See domain/tds/vocabulary.py.
        "form": _vocabulary.statement_form(_vocabulary.NON_RESIDENT, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           + _sec_gaps + _credit_moved_gaps(db, firm_id, events)),
        "source": "posted_purchase_bills_and_advances",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_payment_paise": payload.total_payment_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "total_surcharge_paise": payload.total_surcharge_paise,
        "total_cess_paise": payload.total_cess_paise,
        "nil_deduction_count": payload.nil_deduction_count,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
                "country_of_residence": d.country_of_residence,
                "deductee_tin": d.deductee_tin,
                "surcharge_paise": d.surcharge_paise, "cess_paise": d.cess_paise,
                "non_deduction_reason": d.non_deduction_reason,
            }
            for d in payload.deductees
        ],
        "challans": payload.challans,
        "challan_gaps": mapping.gaps,
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "account_found": tds_payable_id is not None,
            "matched": matched,
            "journal_entry_count": len(set(journal_ids)),
        },
    }


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

    # Section 192 challans for the quarter (deposited salary TDS).
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") == "192"]

    # THE SAME DEFECT AS 26Q, IN ITS SALARY MIRROR, AND FIXED THE SAME WAY.
    # `matching_challan = challans[0]` stamped every slip in the quarter with
    # whichever §192 challan came back first, and the deposited column was the
    # quarter's whole deposit apportioned by weight — so April's fully-paid
    # employees read as partly paid whenever June was short. A quarter carries
    # three monthly deposits under Rule 30(2); the payroll MONTH is what says
    # which one paid a slip. See domain/tds/challan_mapping.py.
    slip_months = {}
    for s in slips:
        run = runs_by_id.get(s.get("run_id"), {})
        month = str(run.get("month") or "")
        # Representative payment date — last day of the payroll month; the run
        # header carries no per-slip payment date, and this is descriptive
        # only (the FY/quarter driving the return is the caller's own input).
        month_end = month or ""
        try:
            month_end = month_end_date(month)
        except (ValueError, IndexError):
            pass
        slip_months[s["id"]] = (month, month_end)

    mapping = challan_mapping.assign(
        [{"id": s["id"], "section": "192",
          "on_date": slip_months[s["id"]][1],
          "doc_no": str(s.get("employee_id") or ""),
          "tds_paise": int(s.get("tds_paise") or 0)}
         for s in slips],
        challans, fy=fy)

    deductees: list[TDSDeducteeRecord] = []
    for s in slips:
        emp = employees.get(s.get("employee_id"), {})
        month, month_end = slip_months[s["id"]]
        gross = int(s.get("gross_paise") or 0)
        tds = int(s.get("tds_paise") or 0)
        assigned = mapping.for_deduction(s["id"])
        matching_challan = assigned.challan
        deductees.append(TDSDeducteeRecord(
            deductee_name=emp.get("name") or "Unknown Employee",
            deductee_pan=(emp.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section="192",
            nature_of_payment=f"Salary — {month}",
            payment_date=month_end,
            payment_amount_paise=gross,
            tds_rate_pct=round(tds * 100 / gross, 4) if gross > 0 else 0.0,
            tds_deducted_paise=tds,
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
        ))

    payload = _computer.compute_24q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees])

    tds_salary_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable - Salary")
    journal_ids = [r["journal_entry_id"] for r in runs if r.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_salary_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    matched = tds_salary_id is not None and books_paise == gl_paise

    return {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # The PERIOD names the form, not a literal. FY 2026-27 onward this is
        # Form 138 under the Income-tax Act 2025; a belated FY 2025-26 return is
        # still 24Q, for ever. domain/tds/vocabulary.py carries both.
        "form": _vocabulary.statement_form(_vocabulary.SALARY, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        # As on 26Q — see its own comment. A §192 deposit short by one month
        # leaves the employees of that month showing 'U' in their 26AS, and
        # they are the people most likely to ask about it.
        "challan_gaps": mapping.gaps,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           # NOT _credit_moved_gaps: 24Q is SALARY (§192), built
                           # from payroll runs. A purchase note cannot reach it,
                           # and this builder has no bill events to ask about.
                           + _sec_gaps),
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
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                "nature_of_payment": d.nature_of_payment,
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
