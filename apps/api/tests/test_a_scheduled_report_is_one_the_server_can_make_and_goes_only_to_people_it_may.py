"""A scheduled report is one the server can make, and it goes only to people it may (PRE-B-002 part 1).

WHAT WAS WRONG
    The Scheduled Reports screen offered five report types, none of which the server makes a document of under those
    names, an "All clients" option that would have mailed one client's books to addresses typed for another, and a
    free-text recipient box written straight into a table nothing validated. `domain/reporting/report_schedule.py`
    is the rule the later chunks (the run table, the service, the send door, the screen) ask; this module holds it.

THE RULES UNDER TEST (the owner's decisions of 9 October 2026)
    * A report can be scheduled only if `report_export_service` makes a PDF of it. The kinds and the export service's
      `REPORTS` agree in both directions, so a report added to one is a decision made about the other.
    * The period a schedule hands the export is the period the export reads: the dates arrive in the parameters the
      service takes (driven through its own `_document`, not asserted from a copy of its parameter names).
    * There is no "All clients": a row with no client is refused, with its reason.
    * A recipient is the firm's ACTIVE staff, the client's ACTIVE portal contacts or the client's own email, and
      nothing else; the list is judged again at send because a stored array nothing validates is the whole trust the
      mail rests on.
    * The practice's own record, a deleted client and an archived one are never run, and "not read" is not "ordinary".
    * Nothing here promises future work: its sentences say what is.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.reporting import report_schedule as R
from services import report_export_service as exports
from services.email_outbox_service import RECIPIENT_KINDS
from tests._property import kernel

API = Path(__file__).resolve().parents[1]
MODULE = API / "domain" / "reporting" / "report_schedule.py"
MIGRATION_031 = API / "migrations" / "031_employee_portal.sql"

D = date.fromisoformat


# ═══ The report kinds ═══════════════════════════════════════════════════════════════════════════════════════════

def test_a_report_can_be_scheduled_exactly_when_the_server_makes_a_document_of_it():
    """The two directions: every export the server makes is either a kind or named as one a schedule cannot hold,
    and every kind that names an export names one that exists."""
    named = {k.export_id for k in R.REPORT_KINDS if k.export_id is not None}
    assert named <= set(exports.REPORTS), f"a kind names an export that does not exist: {named - set(exports.REPORTS)}"
    assert set(exports.REPORTS) == named | set(R.NOT_SCHEDULABLE_EXPORTS)
    assert not named & set(R.NOT_SCHEDULABLE_EXPORTS)
    for k in R.REPORT_KINDS:
        assert k.available == (k.export_id is not None), k.id
        if k.available:
            assert k.reason is None
            assert R.ATTACHMENT_FORMAT in exports.REPORTS[k.export_id], f"{k.id} is not offered as a {R.ATTACHMENT_FORMAT}"
        else:
            assert k.reason and k.reason.endswith(".")


def test_the_ids_are_unique_and_include_every_value_the_table_can_hold_today():
    """A row written by the old screen holds one of the CHECK's five values; each must still be a kind, or the list
    could not say why that row does nothing."""
    ids = [k.id for k in R.REPORT_KINDS]
    assert len(ids) == len(set(ids))
    check = re.search(r"report_type\s+TEXT NOT NULL CHECK \(report_type IN \(([^)]*)\)\)", MIGRATION_031.read_text())
    stored = set(re.findall(r"'([a-z_]+)'", check.group(1)))
    assert stored == {"pl", "balance_sheet", "gst_summary", "tds_summary", "payroll_summary"}
    assert stored <= set(ids)
    assert not {k.id for k in R.REPORT_KINDS if k.available} & stored, (
        "an available kind is a NEW value for the CHECK; the run-table migration widens it")


@pytest.mark.parametrize("report_type", ["pl", "balance_sheet", "gst_summary", "tds_summary", "payroll_summary"])
def test_a_report_the_server_makes_no_document_of_is_refused_with_why(report_type):
    problem = R.kind_problem(report_type)
    assert problem.code == "report_unavailable"
    assert "cannot be scheduled" in problem.sentence and "no " in problem.sentence and "document" in problem.sentence
    with pytest.raises(ValueError):
        R.export_params(report_type, R._month_period(2026, 9))


def test_the_ledger_is_named_as_unschedulable_for_the_reason_it_needs_an_account():
    problem = R.kind_problem("ledger")
    assert problem.code == "report_not_schedulable" and "account" in problem.sentence


@pytest.mark.parametrize("junk", [None, "", "mystery", "trial-balance", 7, ["trial_balance"], "Trial_Balance"])
def test_an_unknown_report_is_not_one_a_schedule_can_run(junk):
    assert R.kind_problem(junk).code == "unknown_report"
    assert R.kind_of(junk) is None


def test_an_available_report_has_no_problem_and_a_picker_can_list_them_all():
    available = [k for k in R.REPORT_KINDS if k.available]
    assert [R.kind_problem(k.id) for k in available] == [None] * len(available)
    assert len(available) >= 4
    for k in R.REPORT_KINDS:
        assert set(k.as_dict()) == {"id", "label", "shape", "available", "reason"}


def test_the_shape_of_a_report_is_the_dates_the_schedule_hands_it():
    """Both ends is a stretch, the end alone is a position, and no date at all is a report that is read on the day it
    is prepared. The shape cannot say more than the parameters do."""
    for k in R.REPORT_KINDS:
        if k.available:
            params = R._EXPORT_DATE_PARAMS[k.export_id]
            wanted = (R.PERIOD if "start" in params.values()
                      else R.AS_AT if "end" in params.values() else R.LIVE)
            assert wanted == k.shape, k.id
    assert {k.id for k in R.REPORT_KINDS if k.shape == R.LIVE} == {"ar_ageing", "ap_ageing"}


# ═══ The period reaches the export where the export reads it ════════════════════════════════════════════════════

class _Reached(Exception):
    """Raised by a spy once it has recorded what the export asked for, so no document has to be built."""


class _SpySvc:
    """Stands in for the reporting engine: records the dates the export passes it."""

    def __init__(self):
        self.seen = {}

    def trial_balance(self, firm_id, client_id, as_of_date, basis="accrual", start_date=None):
        self.seen = {"as_of_date": as_of_date, "start_date": start_date}
        raise _Reached

    def cash_flow_statement(self, firm_id, client_id, start_date, end_date, basis="accrual"):
        self.seen = {"start_date": start_date, "end_date": end_date}
        raise _Reached


PERIODS = [R._month_period(2026, 9), R._month_period(2028, 2), R._quarter_periods("2026-27")[1],
           R._quarter_periods("2026-27")[3], R._year_period("2026-27")]


@pytest.mark.parametrize("period", PERIODS, ids=lambda p: p.key)
@pytest.mark.parametrize("kind", [k for k in R.REPORT_KINDS if k.available], ids=lambda k: k.id)
def test_the_dates_a_schedule_hands_the_export_are_the_dates_the_export_reads(kind, period, monkeypatch):
    spy, ageing = _SpySvc(), {}

    def record(name):
        def fn(db, firm_id, client_id, as_of=None):
            ageing["as_of"] = as_of
            raise _Reached
        return fn

    from services.customer_statement_service import customer_statement_service as ar
    from services.vendor_statement_service import vendor_statement_service as ap
    monkeypatch.setattr(ar, "ar_aging", record("ar"))
    monkeypatch.setattr(ap, "ap_aging", record("ap"))
    params = R.export_params(kind.id, period)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in params.values())   # vacuous for an ageing: it has none
    with pytest.raises(_Reached):
        exports._document(kind.export_id, R.ATTACHMENT_FORMAT, svc=spy, db=None, firm_id="f", client_id="c", p=params)
    start, end = period.start.isoformat(), period.end.isoformat()
    if kind.id == "trial_balance":
        assert spy.seen == {"as_of_date": end, "start_date": None}
    elif kind.id == "cash_flow":
        assert spy.seen == {"start_date": start, "end_date": end}
    else:
        # No date: the ageing is read on the day it is prepared (see `test_a_scheduled_ageing_is_as_at_the_day_...`).
        assert params == {} and ageing == {"as_of": None}


# ═══ A position is claimed only by a report that rebuilds it ═══════════════════════════════════════════════════
#
# The first draft of this module called the two ageing reports a "position as at the period end" and handed them the
# period's end as `as_of`. They read each document's CURRENT outstanding balance and use the date only to age it, so a
# September report prepared on 5 October omitted the invoice that was open on 30 September and paid on 2 October, and
# listed the one raised on 3 October. These tests drive the REAL reports over a book where something happened after the
# period ended, and hold each kind's shape to what its report does.

PERIOD_ENDS = D("2026-09-30")
PREPARED_ON = D("2026-10-05")

# (id, raised_on, total_paise, settled_on). The books store only TODAY's state (a settlement overwrites paid_paise), so
# the truth about 30 September is held here, beside the facts that make it true, and never read from the report.
DOCUMENTS = [
    ("A", "2026-09-20", 100_000, "2026-10-02"),    # open on 30 Sep, paid after: IN the September position
    ("B", "2026-10-03", 50_000, None),             # did not exist on 30 Sep: NOT in it
    ("C", "2026-08-10", 30_000, "2026-09-12"),     # settled before the end: not in it
    ("D", "2026-08-15", 20_000, None),             # open throughout: in it
]
OPEN_AT_PERIOD_END = {i for i, raised, _, settled in DOCUMENTS
                      if D(raised) <= PERIOD_ENDS and (settled is None or D(settled) > PERIOD_ENDS)}
OPEN_ON_PREPARED_DAY = {i for i, raised, _, settled in DOCUMENTS
                        if D(raised) <= PREPARED_ON and (settled is None or D(settled) > PREPARED_ON)}


def _books_as_stored_on_the_prepared_day():
    from tests.e2e_harness import FakeDB
    db = FakeDB()
    db.seed("customers", {"id": "CU", "firm_id": "F", "client_id": "C", "name": "Customer"})
    db.seed("vendors", {"id": "VE", "firm_id": "F", "client_id": "C", "name": "Supplier"})
    for i, raised, total, settled in DOCUMENTS:
        db.seed("client_sales_invoices", {
            "id": i, "firm_id": "F", "client_id": "C", "customer_id": "CU", "invoice_no": f"INV-{i}",
            "invoice_date": raised, "due_date": raised, "total_paise": total,
            "paid_paise": total if settled else 0, "status": "issued", "deleted_at": None})
        db.seed("purchase_bills", {
            "id": i, "firm_id": "F", "client_id": "C", "vendor_id": "VE", "bill_no": f"BILL-{i}",
            "bill_date": raised, "due_date": raised, "net_payable_paise": total,
            "paid_paise": total if settled else 0, "status": "received", "deleted_at": None})
    return db


def _pin_the_prepared_day(monkeypatch):
    import services.customer_statement_service as cs
    import services.vendor_statement_service as vs
    monkeypatch.setattr(cs, "ist_today", lambda: PREPARED_ON)
    monkeypatch.setattr(vs, "ist_today", lambda: PREPARED_ON)


def _run_a_scheduled_ageing(kind_id, monkeypatch, *, handed=None):
    """The real ageing report, made the way a schedule would make it for September. Returns (data, document)."""
    from services import customer_statement_service as cs, vendor_statement_service as vs
    _pin_the_prepared_day(monkeypatch)
    seen = {}
    for service, name in ((cs.customer_statement_service, "ar_aging"), (vs.vendor_statement_service, "ap_aging")):
        original = getattr(service, name)

        def wrapper(*a, _original=original, **k):
            seen["data"] = _original(*a, **k)
            return seen["data"]
        monkeypatch.setattr(service, name, wrapper)
    kind = R.kind_of(kind_id)
    params = R.export_params(kind_id, R._month_period(2026, 9)) if handed is None else handed
    doc = exports._document(kind.export_id, R.ATTACHMENT_FORMAT, svc=None, db=_books_as_stored_on_the_prepared_day(),
                            firm_id="F", client_id="C", p=params)
    return seen["data"], doc


def _listed_ids(kind_id, data):
    return {r["invoice_id" if kind_id == "ar_ageing" else "bill_id"] for r in data["invoices" if kind_id == "ar_ageing" else "bills"]}


def _trial_balance_total_debit(monkeypatch):
    """The real trial balance, made the way a schedule would make it for September, over a ledger that also holds an
    entry dated 3 October. Returns (what the report totals, what the ledger held on 30 September)."""
    from domain.reporting import Account, InMemoryLedgerSource, JournalEntry, JournalLine, ReportingService
    accounts = [Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", system_key="ar"),
                Account("rev", "4000", "Sales", "Revenue")]
    entries = []
    for i, (_, raised, total, _s) in enumerate(DOCUMENTS):
        entries.append(JournalEntry(
            id=f"e{i}", entry_date=raised, client_id="C", firm_id="F", entry_type="x",
            lines=(JournalLine("ar", total, 0), JournalLine("rev", 0, total)), created_at=f"{raised}T00:00:00",
            reference_no=f"INV/{i}", narration="Sale"))
    svc = ReportingService(InMemoryLedgerSource(accounts=accounts, entries=entries))
    seen = {}
    original = svc.trial_balance

    def recording(*a, **k):
        seen["tb"] = original(*a, **k)
        return seen["tb"]
    svc.trial_balance = recording
    params = R.export_params("trial_balance", R._month_period(2026, 9))
    exports._document("trial-balance", R.ATTACHMENT_FORMAT, svc=svc, db=None, firm_id="F", client_id="C", p=params)
    held_on_the_last_day = sum(total for _, raised, total, _s in DOCUMENTS if D(raised) <= PERIOD_ENDS)
    return seen["tb"]["total_debit_paise"], held_on_the_last_day


def _the_report_rebuilds_the_position(kind_id, monkeypatch) -> bool:
    if kind_id == "trial_balance":
        reported, held = _trial_balance_total_debit(monkeypatch)
        return reported == held
    # A report that becomes schedulable and is not a stretch needs a driver here before it can claim a shape; failing
    # by name is better than failing inside the ageing driver.
    assert kind_id in ("ar_ageing", "ap_ageing"), (
        f"no driver for {kind_id!r}: add one that makes it over a book with later activity")
    data, _ = _run_a_scheduled_ageing(kind_id, monkeypatch)
    return _listed_ids(kind_id, data) == OPEN_AT_PERIOD_END


@pytest.mark.parametrize("kind", [k for k in R.REPORT_KINDS if k.available and k.shape != R.PERIOD],
                         ids=lambda k: k.id)
def test_a_kind_claims_a_position_exactly_when_its_report_rebuilds_one(kind, monkeypatch):
    """THE RULE. A report is `AS_AT` only if, made for September over a book where documents were raised and settled
    after 30 September, it still gives September's position. A kind that claims more than its report does is the
    defect this guard exists for; a kind that claims less (a report that learns to look back and is still `LIVE`) is
    caught the same way, so the day an ageing is made to reconstruct, this fails and says to flip its shape."""
    assert _the_report_rebuilds_the_position(kind.id, monkeypatch) == (kind.shape == R.AS_AT), kind.id


def test_the_scenario_is_not_vacuous_the_position_on_the_last_day_differs_from_the_one_on_the_prepared_day():
    """If the open sets were equal, no report could be told from one that looks back."""
    assert OPEN_AT_PERIOD_END == {"A", "D"} and OPEN_ON_PREPARED_DAY == {"B", "D"}


@pytest.mark.parametrize("kind_id", ["ar_ageing", "ap_ageing"])
def test_an_ageing_given_a_past_date_re_ages_todays_open_documents_and_does_not_look_back(kind_id, monkeypatch):
    """The premise the LIVE shape rests on, driven through the real report with the date the first draft handed it.
    The document settled after 30 September is missing, the one raised after it is listed, and the date only moved
    the ages. If this starts failing because an ageing now reconstructs, the kind may become AS_AT."""
    data, _ = _run_a_scheduled_ageing(kind_id, monkeypatch, handed={"as_of": PERIOD_ENDS.isoformat()})
    assert _listed_ids(kind_id, data) == OPEN_ON_PREPARED_DAY
    assert _listed_ids(kind_id, data) != OPEN_AT_PERIOD_END
    assert "A" not in _listed_ids(kind_id, data) and "B" in _listed_ids(kind_id, data)
    assert data["total_outstanding_paise"] == 50_000 + 20_000          # not the 1,20,000 that was open on 30 Sep


@pytest.mark.parametrize("kind_id", ["ar_ageing", "ap_ageing"])
def test_a_scheduled_ageing_is_as_at_the_day_it_is_prepared_and_says_so(kind_id, monkeypatch):
    """What the LIVE sentence promises is what the schedule produces: the open documents of the day it is made, aged
    from that day, under a header that names that day and not the period's end."""
    data, doc = _run_a_scheduled_ageing(kind_id, monkeypatch)
    assert _listed_ids(kind_id, data) == OPEN_ON_PREPARED_DAY
    assert data["as_of"] == PREPARED_ON.isoformat()
    assert doc.period == f"As at {PREPARED_ON.isoformat()}"
    assert PERIOD_ENDS.isoformat() not in doc.period and PERIOD_ENDS.isoformat() not in doc.file_stem


def test_the_export_params_name_only_dates_the_export_reads():
    """Every parameter name is one `_document` reads from its `p` argument, so none is silently ignored."""
    source = (API / "services" / "report_export_service.py").read_text()
    read = set(re.findall(r'p\.get\("([a-z_]+)"\)|p\["([a-z_]+)"\]', source))
    read = {a or b for a, b in read}
    used = {name for params in R._EXPORT_DATE_PARAMS.values() for name in params}
    assert used <= read, f"export_params names parameters the export never reads: {used - read}"
    assert set(R._EXPORT_DATE_PARAMS) == {k.export_id for k in R.REPORT_KINDS if k.available}


# ═══ The row: no "All clients", no defaulted day, no unreadable switch ══════════════════════════════════════════

def test_a_schedule_with_no_client_is_refused_because_it_would_mail_one_clients_books_to_anothers_addresses():
    problem = R.schedule_problem({"report_type": "trial_balance", "frequency": "monthly", "day_of_month": 5,
                                  "client_id": None, "is_active": True})
    assert problem.code == "no_client"
    assert "all clients" in problem.sentence and "another" in problem.sentence


# ═══ Who may receive it ═════════════════════════════════════════════════════════════════════════════════════════

def staff(email, *, id_="u-1", name="Asha", active=True, status="active", deleted=None):
    return {"id": id_, "full_name": name, "email": email, "is_active": active, "status": status,
            "deleted_at": deleted}


def contact(email, *, status="active", name="Ravi"):
    return {"id": "pc-1", "name": name, "email": email, "status": status}


STAFF = [staff("asha@firm.in", id_="u-asha", name="Asha"), staff("bala@firm.in", id_="u-bala", name="Bala")]
CONTACTS = [contact("ravi@client.in")]
CLIENT_EMAIL = "accounts@client.in"


def resolve(requested, *, st_=None, ct=None, ce=CLIENT_EMAIL):
    return R.resolve_recipients(requested, staff=STAFF if st_ is None else st_,
                                contacts=CONTACTS if ct is None else ct, client_email=ce)


def test_the_three_sources_are_accepted_and_each_is_labelled_with_where_it_came_from():
    res = resolve(["asha@firm.in", "ravi@client.in", "accounts@client.in"])
    assert res.ok and res.problems == ()
    assert [(r.address, r.source, r.kind) for r in res.accepted] == [
        ("asha@firm.in", "staff", "staff"),
        ("ravi@client.in", "portal_contact", "client_contact"),
        ("accounts@client.in", "client_email", "client_contact")]
    assert res.accepted[0].user_id == "u-asha" and res.accepted[0].name == "Asha"
    assert res.accepted[1].user_id is None
    assert {r.kind for r in res.accepted} <= set(RECIPIENT_KINDS)


def test_an_address_nobody_named_is_refused_by_name():
    res = resolve(["asha@firm.in", "stranger@elsewhere.com"])
    assert not res.ok
    assert [r.address for r in res.accepted] == ["asha@firm.in"]
    (problem,) = res.problems
    assert problem.code == "not_allowed" and problem.subject == "stranger@elsewhere.com"
    assert "active staff" in problem.sentence and "portal contacts" in problem.sentence


def test_a_customers_or_a_suppliers_address_is_not_a_recipient_even_if_it_looks_like_a_normal_one():
    """AR and AP ageing name that client's customers and suppliers: those people must not receive the books."""
    assert resolve(["customer@buyer.in"]).problems[0].code == "not_allowed"


@pytest.mark.parametrize("who, code", [
    (staff("gone@firm.in", active=False), "staff_inactive"),
    (staff("gone@firm.in", status="invited"), "staff_inactive"),
    (staff("gone@firm.in", deleted="2026-09-01T00:00:00+00:00"), "staff_inactive"),
    ({**staff("gone@firm.in"), "is_active": None}, "staff_inactive"),
    ({k: v for k, v in staff("gone@firm.in").items() if k != "status"}, "staff_inactive"),
    ({k: v for k, v in staff("gone@firm.in").items() if k != "deleted_at"}, "staff_inactive"),
    ({k: v for k, v in staff("gone@firm.in").items() if k != "is_active"}, "staff_inactive"),
])
def test_a_staff_member_who_is_not_active_is_not_a_recipient_and_a_narrow_read_does_not_make_them_one(who, code):
    res = resolve(["gone@firm.in"], st_=[who])
    assert res.accepted == () and [p.code for p in res.problems] == [code]
    assert res.problems[0].subject == "gone@firm.in"


@pytest.mark.parametrize("status", ["invited", "inactive", "revoked", None, ""])
def test_a_portal_contact_whose_access_is_not_active_is_not_a_recipient(status):
    res = resolve(["ex@client.in"], ct=[contact("ex@client.in", status=status)])
    assert res.accepted == () and [p.code for p in res.problems] == ["contact_inactive"]


def test_the_three_reasons_an_address_is_refused_are_three_different_sentences():
    res = resolve(["gone@firm.in", "ex@client.in", "nobody@x.com"],
                  st_=[staff("gone@firm.in", active=False)], ct=[contact("ex@client.in", status="inactive")])
    assert [p.code for p in res.problems] == ["staff_inactive", "contact_inactive", "not_allowed"]
    assert len({p.sentence for p in res.problems}) == 3


@pytest.mark.parametrize("bad", [
    "plain", "a@b", "a b@c.in", "a@b .in", "x,y@z.in", "x@y.in,z@w.in", "x@y.in;z@w.in", "<x@y.in>",
    '"x"@y.in', "x@y.in>", "(x)@y.in", "x@y@z.in", "@y.in", "x@.in" + "a" * 300, "a" * 250 + "@y.in",
])
def test_something_that_is_not_one_address_is_refused_as_not_an_address(bad):
    res = resolve([bad])
    assert res.accepted == () and [p.code for p in res.problems] == ["bad_address"]


def test_an_entry_that_is_not_text_is_a_bad_address_and_blank_entries_are_ignored():
    res = resolve([None, 12, "", "   ", "asha@firm.in"])
    assert [r.address for r in res.accepted] == ["asha@firm.in"]
    assert [p.code for p in res.problems] == ["bad_address", "bad_address"]


def test_addresses_are_trimmed_lower_cased_and_folded_so_one_inbox_is_one_recipient():
    res = resolve(["  Asha@Firm.IN ", "asha@firm.in", "ASHA@FIRM.IN"])
    assert res.ok and [r.address for r in res.accepted] == ["asha@firm.in"]


def test_a_requested_address_is_matched_whatever_case_the_source_row_holds():
    res = resolve(["asha@firm.in", "ravi@client.in", "accounts@client.in"],
                  st_=[staff("Asha@Firm.in")], ct=[contact(" RAVI@client.in ")], ce="Accounts@Client.in")
    assert res.ok and len(res.accepted) == 3


def test_an_address_held_by_staff_and_by_a_contact_is_the_staff_member_so_their_own_opt_out_applies():
    res = resolve(["asha@firm.in"], ct=[contact("asha@firm.in")])
    assert res.accepted[0].source == "staff" and res.accepted[0].kind == "staff"
    # An inactive staff row does not hide an active contact who shares the address.
    res = resolve(["asha@firm.in"], st_=[staff("asha@firm.in", active=False)], ct=[contact("asha@firm.in")])
    assert res.accepted[0].source == "portal_contact" and res.problems == ()
    # And the client's own email is last.
    res = resolve(["ravi@client.in"], ct=[contact("ravi@client.in")], ce="ravi@client.in")
    assert res.accepted[0].source == "portal_contact"


def test_the_clients_own_email_counts_only_if_it_is_an_address():
    assert resolve(["accounts@client.in"], ce=None).problems[0].code == "not_allowed"
    assert resolve(["accounts@client.in"], ce="").problems[0].code == "not_allowed"
    assert resolve(["n/a"], ce="n/a").problems[0].code == "bad_address"


def test_no_recipient_is_a_problem_of_its_own():
    for empty in (None, [], ["", "  "], ()):
        res = resolve(empty)
        assert not res.ok and res.accepted == () and [p.code for p in res.problems] == ["no_recipient"]


def test_a_schedule_takes_at_most_five_recipients_because_the_send_is_synchronous():
    many_staff = [staff(f"s{i}@firm.in", id_=f"u{i}") for i in range(7)]
    five = resolve([f"s{i}@firm.in" for i in range(R.MAX_RECIPIENTS)], st_=many_staff)
    assert five.ok and len(five.accepted) == R.MAX_RECIPIENTS == 5
    six = resolve([f"s{i}@firm.in" for i in range(R.MAX_RECIPIENTS + 1)], st_=many_staff)
    assert not six.ok and [p.code for p in six.problems] == ["too_many_recipients"]
    assert len(six.accepted) == 6                       # the list is still separated; the door decides what to do


def test_the_pickers_list_is_everyone_allowed_once_sorted_and_nobody_else():
    people = R.allowed_recipients(
        staff=[*STAFF, staff("gone@firm.in", active=False), staff("ASHA@firm.in", id_="dup")],
        contacts=[*CONTACTS, contact("off@client.in", status="inactive")], client_email="Accounts@client.in")
    assert [p.address for p in people] == ["accounts@client.in", "asha@firm.in", "bala@firm.in", "ravi@client.in"]
    assert people[1].user_id == "u-asha"               # the first staff row for an address wins


def test_a_problem_never_echoes_an_unbounded_string():
    res = resolve(["a" * 5000 + " b"])
    assert len(res.problems[0].sentence) < 200


def test_every_recipient_problem_names_its_address_where_it_has_one_and_is_a_sentence():
    res = resolve(["gone@firm.in", "ex@client.in", "nobody@x.com", "bad"],
                  st_=[staff("gone@firm.in", active=False)], ct=[contact("ex@client.in", status="inactive")])
    for p in res.problems:
        assert p.sentence.endswith(".") and p.subject
        assert p.as_dict() == {"code": p.code, "sentence": p.sentence, "subject": p.subject}


ADDRESSES = st.sampled_from(
    ["asha@firm.in", "bala@firm.in", "gone@firm.in", "ravi@client.in", "ex@client.in", "accounts@client.in",
     "ASHA@FIRM.IN", " bala@firm.in ", "nobody@elsewhere.com", "x@y", "", "  ", "a,b@c.in"])


@kernel()
@given(requested=st.lists(ADDRESSES, max_size=12))
def test_nothing_is_ever_accepted_that_is_not_an_active_member_contact_or_client_address(requested):
    res = R.resolve_recipients(
        requested,
        staff=[*STAFF, staff("gone@firm.in", active=False)],
        contacts=[*CONTACTS, contact("ex@client.in", status="inactive")], client_email=CLIENT_EMAIL)
    allowed = {"asha@firm.in", "bala@firm.in", "ravi@client.in", "accounts@client.in"}
    folded = [a.strip().lower() for a in requested if a.strip()]
    accepted = [r.address for r in res.accepted]
    assert set(accepted) <= allowed
    assert len(accepted) == len(set(accepted))
    # every requested address is either accepted or named in a problem: none vanishes
    named = {p.subject for p in res.problems if p.subject}
    assert set(folded) <= set(accepted) | named
    assert set(accepted) == {a for a in folded if a in allowed}
    assert not set(accepted) & named


# ═══ The client, and the file ═══════════════════════════════════════════════════════════════════════════════════

ORDINARY = {"is_internal": False, "is_deleted": False, "is_archived": False, "deleted_at": None, "archived_at": None}


def test_an_ordinary_client_is_run():
    assert R.client_problem(ORDINARY) is None


@pytest.mark.parametrize("change, code", [
    ({"is_internal": True}, "client_internal"),
    ({"is_deleted": True}, "client_deleted"),
    ({"deleted_at": "2026-09-01T00:00:00+00:00"}, "client_deleted"),
    ({"is_archived": True}, "client_archived"),
    ({"archived_at": "2026-09-01T00:00:00+00:00"}, "client_archived"),
])
def test_the_practices_own_record_a_deleted_client_and_an_archived_one_are_never_run(change, code):
    assert R.client_problem({**ORDINARY, **change}).code == code


@pytest.mark.parametrize("missing", ["is_internal", "is_deleted", "is_archived"])
def test_a_client_read_without_its_status_is_not_assumed_ordinary(missing):
    """The flags are NOT NULL in the schema, so anything but False means the read left them out: refused, not run."""
    row = {k: v for k, v in ORDINARY.items() if k != missing}
    assert R.client_problem(row).code == "client_unread"
    assert R.client_problem({**ORDINARY, missing: None}).code == "client_unread"


@pytest.mark.parametrize("nobody", [None, {}])
def test_no_client_record_is_a_problem(nobody):
    assert R.client_problem(nobody).code == "client_missing"


def test_the_columns_the_rules_read_are_listed_so_a_narrow_select_is_a_visible_decision():
    assert set(R.CLIENT_FIELDS) >= {"is_internal", "is_deleted", "is_archived"}
    assert set(R.STAFF_FIELDS) >= {"email", "is_active", "status", "deleted_at"}
    assert set(R.CONTACT_FIELDS) >= {"email", "status"}
    # each listed field is one the module actually reads outside the lists themselves (a field nothing reads is a
    # lie in the contract the service writes its select from)
    body = "\n".join(line for line in MODULE.read_text().splitlines()
                     if not line.startswith(("CLIENT_FIELDS", "STAFF_FIELDS", "CONTACT_FIELDS")))
    for name in (*R.CLIENT_FIELDS, *R.STAFF_FIELDS, *R.CONTACT_FIELDS):
        assert f'"{name}"' in body, f"{name} is listed as read and nothing reads it"


def test_a_file_over_the_limit_is_refused_in_words_and_one_at_the_limit_is_not():
    limit = R.MAX_ATTACHMENT_BYTES
    assert R.size_problem(0) is None and R.size_problem(limit) is None
    problem = R.size_problem(limit + 1)
    assert problem.code == "too_large" and "10.0 MB" in problem.sentence and "Nothing was sent" in problem.sentence
    assert "25.5 MB" in R.size_problem(int(25.5 * 1024 * 1024)).sentence


# ═══ The words promise nothing ══════════════════════════════════════════════════════════════════════════════════

#: Wording a screen reads as a promise or an owner's switch. The coming-soon register tracks every sentence that
#: says something is planned, coming or switched off; the sentences here say what IS, so they use none of it.
PROMISE_WORDS = re.compile(r"\b(not yet|coming soon|planned|switched off|in progress|will be|soon)\b", re.I)


def test_no_sentence_in_the_module_promises_future_work_or_names_an_off_switch():
    offenders = []
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # docstrings explain; the sentences a person is shown are the short literals and f-strings
            if len(node.value) < 400 and PROMISE_WORDS.search(node.value):
                offenders.append(node.value)
    assert not offenders, offenders


def test_the_unavailable_reasons_are_distinct_facts_not_one_sentence_repeated():
    reasons = [k.reason for k in R.REPORT_KINDS if not k.available]
    assert len(reasons) == len(set(reasons)) == 5
