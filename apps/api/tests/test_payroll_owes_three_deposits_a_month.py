"""
Payroll deadlines reach the calendar, and a service name stops conjuring ROC
filings out of the word "processing".

WHAT WAS MISSING
    services/compliance_engine.py has computed all three payroll deposit dates
    since the payroll module was built — epf_deposit_due_date,
    esi_deposit_due_date, tds_deposit_due_date, and payroll_deposit_due_dates
    over the top of them. NOTHING HAS EVER CALLED THEM. Grep found exactly one
    reference to payroll_deposit_due_dates: its own definition.

    Meanwhile compliance_obligation_service said, in its docstring, that
    "non-statutory services (accounting / bookkeeping / payroll) imply no filing
    obligations and return []". That is true of the RETURN and false of the
    DEPOSIT. Every month a payroll runs, three authorities are owed money:

      EPF   15th of the following month  — EPF Scheme 1952, para 38(1)
      ESI   15th of the following month  — ESI (General) Regs 1950, reg. 31
      TDS   7th, except March: 30 April  — IT Act s.192 with Rule 30(2)

    None of them appeared in the deadline view, on any screen, ever.

THE SECOND BUG, FOUND BY TESTING THE FIRST
    `if "roc" in s` decided whether a service implied ROC filings, and "roc"
    sits inside "p-ROC-essing". So "Payroll processing" — the most ordinary name
    a firm could give the service — generated AOC-4 and MGT-7 against a client
    that may not be a company at all. So did "Invoice processing".

NEGATIVE CONTROLS
    Remove the _payroll_obligations call and
    test_a_payroll_engagement_generates_the_month_s_deposits fails.
    Put `"roc" in s` back and
    test_processing_is_not_an_roc_engagement fails.
    Point the TDS deposit at the plain 7th and
    test_march_salary_tds_is_due_on_thirty_april fails.
"""
from __future__ import annotations

from datetime import date

import services.compliance_engine as ce
import services.compliance_obligation_service as ob

FY = "2026-27"


# ─── the three deposits, and the dates the statutes actually give ───────────

def test_a_payroll_engagement_generates_the_month_s_deposits():
    specs = ob.obligations_for_service("Payroll", FY)
    assert len(specs) == 36, "three deposits x twelve months"
    assert {s["compliance_type"] for s in specs} == {"Payroll"}


def test_epf_and_esi_are_both_the_fifteenth(): 
    """Fifteen days from the close of the month, for both — EPF Scheme 1952
    para 38(1) and ESI (General) Regulations 1950 reg. 31.

    ESI was the TWENTY-FIRST until the 2017 amendment, so a date taken from
    older material is a week late and draws 12% interest under reg. 31A.
    """
    assert ce.epf_deposit_due_date(2026, 8) == date(2026, 9, 15)
    assert ce.esi_deposit_due_date(2026, 8) == date(2026, 9, 15)


def test_march_salary_tds_is_due_on_thirty_april():
    """Rule 30(2)'s proviso, and the date most often missed.

    s.201(1A)(ii) charges 1.5% a month from the date of DEDUCTION rather than
    from the due date, so being three weeks late on March costs two months of
    interest, not one.
    """
    assert ce.tds_deposit_due_date(2027, 3) == date(2027, 4, 30)
    assert ce.tds_deposit_due_date(2026, 8) == date(2026, 9, 7)


def test_the_generated_specs_carry_those_same_dates():
    """One source, not two. The obligations are built by calling
    payroll_deposit_due_dates rather than by re-deriving the day numbers, so
    a CBDT or EPFO notification moves both at once."""
    specs = ob.obligations_for_service("Payroll", FY)

    def _due(kind, period_start):
        return next(s["due_date"] for s in specs
                    if s["obligation_type"] == kind and s["period_start"] == period_start)

    assert _due("EPF_DEPOSIT", "2026-08-01") == "2026-09-15"
    assert _due("ESI_DEPOSIT", "2026-08-01") == "2026-09-15"
    assert _due("TDS_SALARY_DEPOSIT", "2026-08-01") == "2026-09-07"
    assert _due("TDS_SALARY_DEPOSIT", "2027-03-01") == "2027-04-30"


def test_professional_tax_is_deliberately_absent():
    """Its due date is fixed by each state and there is no single rule —
    Maharashtra differs from Karnataka differs from West Bengal. A missing date
    is a gap somebody notices; a wrong one is trusted. The same refusal
    payroll_deposit_due_dates already makes in its own docstring."""
    specs = ob.obligations_for_service("Payroll", FY)
    assert not [s for s in specs
                if "professional" in (s["period_label"] or "").lower()
                or s["obligation_type"].startswith("PT")]


def test_the_24q_return_is_not_emitted_twice():
    """It is already generated, quarterly, by _tds_obligations for a TDS
    engagement. Emitting it from the payroll side too would put the same
    deadline in the calendar twice for a firm that runs both — and the
    generator dedups on (obligation_type, period_start), which would not
    catch a quarterly row beside a monthly one."""
    payroll = ob.obligations_for_service("Payroll", FY)
    assert not [s for s in payroll if s["obligation_type"].startswith("TDS24Q")]


def test_a_deposit_period_is_the_wage_month_not_the_payment_month():
    """The period is the month the wages relate to; the due date falls in the
    next one. Getting that backwards would file August's challan under
    September and make the year's twelve rows read as eleven and a stray."""
    specs = ob.obligations_for_service("Payroll", FY)
    aug = [s for s in specs if s["period_start"] == "2026-08-01"]
    assert len(aug) == 3
    assert all(s["period_end"] == "2026-08-31" for s in aug)
    assert all(s["due_date"] > s["period_end"] for s in aug)


# ─── the substring bug ──────────────────────────────────────────────────────

def test_processing_is_not_an_roc_engagement():
    """"roc" sits inside "p-ROC-essing"."""
    for name in ("Invoice processing", "Bookkeeping and processing",
                 "Document processing"):
        assert ob.obligations_for_service(name, FY) == [], name


def test_payroll_processing_generates_payroll_and_nothing_else():
    specs = ob.obligations_for_service("Payroll processing", FY)
    assert {s["compliance_type"] for s in specs} == {"Payroll"}
    assert not [s for s in specs if s["obligation_type"].startswith("MCA")]


def test_the_real_abbreviations_still_match():
    """Anchored at the start of a word and NOT at the end, so "gstr-1 filing"
    keeps matching "gst"."""
    assert ob.obligations_for_service("GSTR-1 filing", FY)
    assert {s["obligation_type"] for s in ob.obligations_for_service("ROC Compliance", FY)} \
        == {"MCA_AOC4", "MCA_MGT7"}
    assert ob.obligations_for_service("MCA annual filing", FY)
    assert ob.obligations_for_service("TDS Compliance", FY)
    assert ob.obligations_for_service("ITR filing", FY)


def test_accounting_still_implies_nothing():
    """The half of the original sentence that was right."""
    assert ob.obligations_for_service("Accounting Outsourcing", FY) == []
    assert ob.obligations_for_service("Bookkeeping", FY) == []


# ═════════════════════════════════════════════════════════════════════════════
#  The firm grain — where a payroll month is FOUND
# ═════════════════════════════════════════════════════════════════════════════

import pytest  # noqa: E402
import routers.payroll as payroll_mod  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-STATES"
PARTNER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
           "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    for cid, cname in (("CLI-ON", "Acme Pvt Ltd"), ("CLI-OFF", "Beta LLP"),
                       ("CLI-RUN", "Gamma Industries")):
        d.seed("clients", {"id": cid, "firm_id": FIRM, "client_name": cname,
                           "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "s-1", "firm_id": FIRM,
                                       "client_id": "CLI-ON",
                                       "payroll_enabled": True, "inputs_due_day": 5})
    d.seed("client_payroll_settings", {"id": "s-2", "firm_id": FIRM,
                                       "client_id": "CLI-OFF",
                                       "payroll_enabled": False})
    d.seed("client_payroll_settings", {"id": "s-3", "firm_id": FIRM,
                                       "client_id": "CLI-RUN",
                                       "payroll_enabled": True})
    d.seed("payroll_runs", {"id": "r-1", "firm_id": FIRM, "client_id": "CLI-RUN",
                            "month": "2026-08", "status": "finalized",
                            "headcount": 4, "total_net_paise": 12_000_000})
    return d


def _states(month="2026-08", user=PARTNER):
    return payroll_mod.payroll_client_states(month=month, current_user=user)["data"]


def test_every_row_carries_the_client_s_name(db):
    """A queue keyed by UUID is not a queue anybody can work, and the screen
    that reads this (the Month tab on /payroll) is the one a bureau opens
    first. The name is fetched in ONE query for the firm, not one per row."""
    by_id = {c["client_id"]: c for c in _states()["clients"]}
    assert by_id["CLI-ON"]["client_name"] == "Acme Pvt Ltd"
    assert by_id["CLI-RUN"]["client_name"] == "Gamma Industries"


def test_a_deleted_client_with_payroll_history_is_named_as_such(db):
    """A blank cell reads as a rendering fault. This row is a client that was
    removed while its payroll settings and runs survived — worth showing,
    because the history is still somebody's statutory record."""
    d = db
    d.seed("client_payroll_settings", {"id": "s-9", "firm_id": FIRM,
                                       "client_id": "CLI-GONE",
                                       "payroll_enabled": True})
    row = next(c for c in _states()["clients"] if c["client_id"] == "CLI-GONE")
    assert row["client_name"] == "(client no longer on file)"


def test_a_client_with_no_run_this_month_is_not_started(db):
    """Switched on and nothing done — the row that needs somebody."""
    row = next(c for c in _states()["clients"] if c["client_id"] == "CLI-ON")
    assert row["payroll_enabled"] is True
    assert row["run_status"] is None
    assert row["inputs_due_day"] == 5


def test_a_client_payroll_is_off_for_is_reported_not_omitted(db):
    """"We do not run payroll for them" and "we do and have not started" are
    different answers. A list showing only the second cannot say which."""
    row = next(c for c in _states()["clients"] if c["client_id"] == "CLI-OFF")
    assert row["payroll_enabled"] is False
    assert row["run_status"] is None


def test_a_finalised_run_is_reported_with_its_headcount(db):
    row = next(c for c in _states()["clients"] if c["client_id"] == "CLI-RUN")
    assert row["run_status"] == "finalized"
    assert row["headcount"] == 4


def test_another_month_shows_no_run(db):
    """The run read is keyed on the month asked for, not on whatever run
    happens to be latest."""
    row = next(c for c in _states("2026-09")["clients"] if c["client_id"] == "CLI-RUN")
    assert row["run_status"] is None


def test_it_answers_for_the_callers_clients_not_the_whole_firm(db, monkeypatch):
    """This is the one payroll endpoint that answers for MANY clients at once,
    so it is the one where firm scoping alone would be a leak: an Executive
    assigned to four clients would otherwise read the headcount and net pay of
    all forty.

    effective_client_ids is patched rather than a role being invented, because
    in mock mode it returns None — "all clients", permissive by design, since
    real assignment scoping needs the database (core/authz.py). Patching it is
    what makes the assertion about THIS endpoint applying filter_by_client
    rather than about how mock mode happens to answer.
    """
    import core.authz as authz
    monkeypatch.setattr(authz, "effective_client_ids", lambda u: {"CLI-ON"})
    seen = {c["client_id"] for c in _states()["clients"]}
    assert seen == {"CLI-ON"}, f"saw {seen}"

    # And with no restriction, the whole firm comes back — so the assertion
    # above is about the filter and not about an empty fixture.
    monkeypatch.setattr(authz, "effective_client_ids", lambda u: None)
    assert len({c["client_id"] for c in _states()["clients"]}) == 3
