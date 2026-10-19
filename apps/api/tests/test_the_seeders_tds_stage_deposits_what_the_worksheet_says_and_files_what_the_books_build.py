"""The seeder's TDS stage deposits what the worksheet says is owed and files what the books build (found by seeding the firm's TDS data).

WHAT IT IS FOR
    The challan, return and filing screens rendered nothing on a seeded firm, and the deposit worksheet charged interest on
    every month because nothing recorded the deposit. `seed_demo_firm._tds` records the challans a practice pays in and the
    quarterly statements it has filed, through the doors a CA's screens use. Like the income-tax stage, the risk is a figure
    of its own: a rate, a threshold, an amount "that looks right". So the rule it is held to is that EVERY AMOUNT AND EVERY DATE
    comes back from a door (the worksheet's outstanding tax and due date, the payroll run's tax, the quarter's due date, the
    statement the server builds). What the stage states itself is the facts nobody else holds, which are a branch code and a
    serial that say they are a seed's and a receipt number that says so, and the labels of the doors it drives: the minor
    head 200 of a challan paid by the deductor, the section number 192 for the payroll leg and the forms 26Q and 24Q.

WHAT IS HELD
    * only a client that deducts tax is touched; the month left in draft is not paid; a deposit whose due date is still to
      come is skipped and counted, and so is the statement of a quarter holding one (a year in progress), which could only
      be refused for the deposit the seeder had decided not to make;
    * one challan per section with tax outstanding, for exactly the outstanding amount, on the worksheet's due date, and the
      salary tax of a finalized or paid payroll run under section 192 on the same month's due date;
    * the branch code is the all-zero code no bank holds and the serial starts SEED: neither can pass for a bank's;
    * a statement is built by the server, saved as the screen saves it, and taken prepared -> CA approved -> filed on the
      quarter's due date for every quarter that has ended before the draft month and whose due date has passed; the last
      quarter is prepared and left; a quarter with no deduction in it gets none; 24Q only for a client whose payroll runs
      withheld tax;
    * a statement the engine reports errors, a gap, a ledger difference or an omitted non-resident payment on is never
      saved or filed, and is a finding; so is a quarter with no deductee whose challans were just recorded, a worksheet or
      payroll list the server refuses (answered as success false or as a 4xx), and a quarter whose challan was not recorded;
    * the obligation each filing leaves open is named; a refusal that is a finding does not stop the next client, a dead run
      does; and the stage runs in a process that cannot import the API.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from domain.demo import fixture

_API_ROOT = Path(__file__).resolve().parents[1]


def _seeder():
    spec = importlib.util.spec_from_file_location("seed_demo_firm_tds", _API_ROOT / "scripts" / "seed_demo_firm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seeder = _seeder()

FY = "2025-26"
FIRM = fixture.build(FY)
CLIENT = {c.name: c for c in FIRM.clients}
ANAND, SUNRISE, PRIYA, MEHER = (CLIENT[n] for n in ("Anand Textiles", "Sunrise Foods", "Priya Sharma", "Meher Enterprises"))
LAST_MONTH = "2026-03"
TODAY = date(2026, 10, 19)
#: Quarter -> (end of the quarter, the statement's due date), as `quarter_dates` gives them.
QUARTERS = {"Q1": ("2025-06-30", "2025-07-31"), "Q2": ("2025-09-30", "2025-10-31"),
            "Q3": ("2025-12-31", "2026-01-31"), "Q4": ("2026-03-31", "2026-05-31")}


def _due(month: str) -> str:
    """Rule 30(2): the 7th of the next month, and 30 April for March. Stated here only to build the fake's answer."""
    y, m = (int(p) for p in month.split("-"))
    if m == 3:
        return f"{y}-04-30"
    return f"{y + (m == 12)}-{(m % 12) + 1:02d}-07"


def _statement(deductees=2, **over):
    return {"deductee_count": deductees, "deductees": [{"deductee_pan": "ABCDE1234F"}] * deductees,
            "total_tds_deducted_paise": 1000_00, "total_tds_deposited_paise": 1000_00, "validation_errors": [],
            "challan_gaps": [], "reconciliation": {"matched": True}, **over}


class FakeApi:
    def __init__(self, sheets=None, runs=None, statements=None, refuse=None, closure=None, due_dates=None,
                 unreadable=None, runs_answer=None):
        self.sheets = sheets if sheets is not None else {}
        self.runs, self.statements, self.refuse = runs or [], statements or {}, refuse or {}
        self.due_dates, self.unreadable, self.runs_answer = due_dates or {}, unreadable or {}, runs_answer
        self.closure = closure if closure is not None else {"state": "closed", "closed": True}
        self.calls, self.n = [], 0

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path.startswith("/api/payroll/runs"):
            if self.runs_answer is not None:
                return self.runs_answer() if callable(self.runs_answer) else self.runs_answer
            return {"data": self.runs}
        if path.startswith("/api/tds-workspace/deposit-due"):
            month = parse_qs(urlparse(path).query)["month"][0]
            if month in self.unreadable:
                answer = self.unreadable[month]
                return answer() if callable(answer) else answer
            return {"data": {"month": month, "due_date": self.due_dates.get(month, _due(month)),
                             "sections": self.sheets.get(month, [])}}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body):
        return self._write("POST", path, body)

    def patch(self, path, body):
        return self._write("PATCH", path, body)

    def _write(self, method, path, body):
        self.calls.append((method, path, body))
        self.n += 1
        for key, fn in self.refuse.items():
            if key in path:
                return fn(body)
        if path.startswith("/api/tds/") and path.endswith("/from-books"):
            kind = path.split("/")[3].upper()
            return {"data": self.statements.get((kind, body["quarter"]), _statement())}
        if path.endswith("/status") and body.get("status") == "filed":
            return {"data": {"status": "filed", "compliance_obligation": self.closure}}
        return {"data": {"id": f"id-{self.n}"}}

    def sent(self, method, prefix):
        return [b for m, p, b in self.calls if m == method and p.startswith(prefix)]

    def paths(self, method):
        return [p for m, p, _ in self.calls if m == method]


def _written():
    return {k: 0 for k in ("tds_challans", "tds_deposits_not_yet_due", "tds_statements_not_yet_due", "tds_statements_filed",
                           "tds_statements_prepared",
                           "tds_quarters_without_deductions", "obligations_closed")} | {
        "obligations_left_open": [], "returns_refused": []}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: TODAY)


def _run(api, client=ANAND, written=None, last_month=LAST_MONTH):
    written = written if written is not None else _written()
    seeder._tds(api, client, "cid", FY, last_month, written)
    return written


# ── who is touched, and which months ────────────────────────────────────────

@pytest.mark.parametrize("client", [PRIYA, MEHER], ids=lambda c: c.name)
def test_a_client_that_deducts_no_tax_is_left_alone(client):
    api = FakeApi()
    assert not client.deducts_tax
    _run(api, client)
    assert api.calls == []


def test_the_worksheet_is_asked_for_every_posted_month_and_never_for_the_month_left_in_draft():
    api = FakeApi()
    _run(api)
    months = [parse_qs(urlparse(p).query)["month"][0] for p in api.paths("GET") if "deposit-due" in p]
    assert months == ["2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
                      "2026-01", "2026-02"], "April to February, eleven months; March is still being entered"


# ── the challans ────────────────────────────────────────────────────────────

def test_one_challan_per_section_with_tax_outstanding_for_exactly_that_amount_on_the_worksheets_due_date():
    api = FakeApi(sheets={"2025-07": [{"section": "194C", "outstanding_paise": 6_027_66},
                                      {"section": "194J", "outstanding_paise": 14_852_50},
                                      {"section": "194I", "outstanding_paise": 0}]})
    w = _run(api)
    challans = api.sent("POST", "/api/tds-workspace/challans")
    assert [(b["section"], b["amount_paise"], b["challan_date"]) for b in challans] == [
        ("194C", 6_027_66, "2025-08-07"), ("194J", 14_852_50, "2025-08-07")], "nothing for a section with nothing owed"
    assert w["tds_challans"] == 2
    assert all(b["client_id"] == "cid" and b["financial_year"] == FY and b["quarter"] == "Q2" and b["minor_head"] == "200"
               for b in challans), "the quarter is the DEDUCTION month's"


def test_april_is_deposited_on_the_seventh_of_may():
    api = FakeApi(sheets={"2025-04": [{"section": "194C", "outstanding_paise": 1_00}]})
    _run(api)
    assert api.sent("POST", "/api/tds-workspace/challans")[0]["challan_date"] == "2025-05-07"


def test_every_challan_date_is_the_one_the_worksheet_gave_and_not_the_seventh_of_the_next_month():
    """A seeder that worked the date out itself would agree with Rule 30(2) on every month the other tests use, so this
    one makes the server's answer differ from it: the practice deposits on the day the worksheet says, salary included."""
    api = FakeApi(sheets={"2025-07": [{"section": "194C", "outstanding_paise": 100}]},
                  runs=[{"month": "2025-07", "status": "paid", "total_tds_paise": 200}],
                  due_dates={"2025-07": "2025-08-09"})
    _run(api, SUNRISE)
    assert [(b["section"], b["challan_date"]) for b in api.sent("POST", "/api/tds-workspace/challans")] == [
        ("194C", "2025-08-09"), ("192", "2025-08-09")]


def test_the_branch_code_and_the_serial_say_they_are_a_seeds():
    api = FakeApi(sheets={"2025-07": [{"section": "194C", "outstanding_paise": 100}]})
    _run(api)
    body = api.sent("POST", "/api/tds-workspace/challans")[0]
    assert body["bsr_code"] == "0000000", "the all-zero branch code: no bank holds it"
    assert body["challan_no"].startswith("SEED-") and not body["challan_no"].isdigit()


def test_a_due_date_still_to_come_is_not_paid_and_is_counted(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2025, 8, 1))
    api = FakeApi(sheets={"2025-07": [{"section": "194C", "outstanding_paise": 100}]})
    w = _run(api, last_month="2025-08")
    assert not api.sent("POST", "/api/tds-workspace/challans")
    assert w["tds_deposits_not_yet_due"] == 1 and w["tds_challans"] == 0


def test_salary_tax_is_deposited_from_the_payroll_run_under_section_192_on_that_months_due_date():
    runs = [{"month": "2025-05", "status": "paid", "total_tds_paise": 15_010_66},
            {"month": "2025-06", "status": "finalized", "total_tds_paise": 15_010_66},
            {"month": "2026-03", "status": "draft", "total_tds_paise": 15_010_67},
            {"month": "2025-08", "status": "review", "total_tds_paise": 15_010_68},
            {"month": "2025-07", "status": "paid", "total_tds_paise": 0}]
    api = FakeApi(runs=runs)
    _run(api, SUNRISE)
    challans = [(b["section"], b["amount_paise"], b["challan_date"], b["quarter"])
                for b in api.sent("POST", "/api/tds-workspace/challans")]
    assert challans == [("192", 15_010_66, "2025-06-07", "Q1"), ("192", 15_010_66, "2025-07-07", "Q1")], (
        "a draft run and a run under review withheld nothing yet, and a run with no tax needs no challan")


@pytest.mark.parametrize("status", ["draft", "review"])
def test_a_run_that_is_not_released_has_withheld_nothing_and_needs_neither_a_challan_nor_a_24q(status):
    api = FakeApi(runs=[{"month": "2025-08", "status": status, "total_tds_paise": 15_010_66}])
    _run(api, SUNRISE)
    assert not api.sent("POST", "/api/tds-workspace/challans")
    assert not [p for p in api.paths("POST") if "24q" in p]


def test_a_section_192_row_on_the_worksheet_is_not_deposited_a_second_time_beside_the_payroll_leg():
    api = FakeApi(sheets={"2025-07": [{"section": "192", "outstanding_paise": 999}, {"section": "194C", "outstanding_paise": 100}]},
                  runs=[{"month": "2025-07", "status": "paid", "total_tds_paise": 200}])
    _run(api, SUNRISE)
    assert [(b["section"], b["amount_paise"]) for b in api.sent("POST", "/api/tds-workspace/challans")] == [
        ("194C", 100), ("192", 200)], "the payroll run states what was withheld under 192; the worksheet does not own it"


def test_a_refused_challan_is_a_finding_and_the_next_month_is_still_paid():
    def refuse(body):
        raise seeder.ApiRefusal("\nPOST challans -> HTTP 422\nperiod locked\nNothing further", 422)
    api = FakeApi(sheets={"2025-04": [{"section": "194C", "outstanding_paise": 100}],
                          "2025-05": [{"section": "194C", "outstanding_paise": 200}]},
                  refuse={"/api/tds-workspace/challans": refuse})
    w = _run(api)
    findings = w["returns_refused"]
    assert [m for m in findings if "TDS challan" in m].__len__() == 2 and w["tds_challans"] == 0
    assert len(findings) == 3 and "TDS 26Q Q1: not built" in findings[2], (
        "the quarter whose challans were refused names itself as not built instead of being blamed on the challans")
    assert len(api.sent("POST", "/api/tds-workspace/challans")) == 2, "the second month was still tried"


# ── the statements ──────────────────────────────────────────────────────────

def test_a_quarter_that_has_ended_is_saved_prepared_approved_and_filed_on_its_due_date_in_that_order():
    api = FakeApi()
    w = _run(api, ANAND)
    saved = api.sent("POST", "/api/tds-workspace/returns")
    assert [(b["return_type"], b["quarter"]) for b in saved] == [("26Q", q) for q in ("Q1", "Q2", "Q3", "Q4")]
    assert all(b["financial_year"] == FY and b["client_id"] == "cid" for b in saved)
    steps = [(p.split("/")[-2], b["status"], b.get("filing_date")) for m, p, b in api.calls
             if m == "PATCH" and p.endswith("/status")]
    walk = []
    for quarter in ("Q1", "Q2", "Q3"):
        walk += [("prepared", None), ("ca_approved", None), ("filed", QUARTERS[quarter][1])]
    walk += [("prepared", None)]
    assert [(s, d) for _, s, d in steps] == walk
    assert w["tds_statements_filed"] == 3 and w["tds_statements_prepared"] == 1


def test_the_receipt_number_says_it_is_a_seeds_and_approval_is_explicit():
    api = FakeApi()
    _run(api, ANAND)
    filed = [b for m, p, b in api.calls if m == "PATCH" and b.get("status") == "filed"]
    assert filed and all(b["prn"].startswith("SEED-PRN-") and b["ca_approved"] is True for b in filed)
    approvals = [b for m, p, b in api.calls if m == "PATCH" and b.get("status") == "ca_approved"]
    assert approvals and all(b["ca_approved"] is True for b in approvals)


def test_the_statement_is_saved_with_what_the_server_built_and_nothing_of_its_own():
    api = FakeApi(statements={("26Q", "Q1"): _statement(deductees=3, total_tds_deducted_paise=42_00,
                                                       total_tds_deposited_paise=41_00)})
    _run(api, ANAND)
    first = api.sent("POST", "/api/tds-workspace/returns")[0]
    assert first["deductee_count"] == 3 and first["total_deductions_paise"] == 42_00 and first["total_deposits_paise"] == 41_00, (
        "deducted and deposited are different figures and each is saved under its own name")
    assert first["deductee_details"] == [{"deductee_pan": "ABCDE1234F"}] * 3 and first["validation_errors"] == []


def test_a_quarter_with_no_deduction_in_it_gets_no_statement_and_is_counted():
    api = FakeApi(statements={("26Q", "Q1"): _statement(deductees=0)})
    w = _run(api, ANAND)
    assert [b["quarter"] for b in api.sent("POST", "/api/tds-workspace/returns")] == ["Q2", "Q3", "Q4"]
    assert w["tds_quarters_without_deductions"] == 1 and w["tds_statements_filed"] == 2


@pytest.mark.parametrize("override, said", [
    ({"validation_errors": ["TDS deducted exceeds deposited"]}, "validation errors"),
    ({"challan_gaps": [{"code": "deductions_not_deposited"}]}, "do not cover the deductions"),
    ({"reconciliation": {"matched": False, "difference_paise": 5}}, "does not tie to the ledger"),
])
def test_a_statement_the_engine_reports_a_problem_with_is_a_finding_and_is_never_saved_or_filed(override, said):
    api = FakeApi(statements={("26Q", "Q2"): _statement(**override)})
    w = _run(api, ANAND)
    assert len(w["returns_refused"]) == 1 and said in w["returns_refused"][0] and "Q2" in w["returns_refused"][0]
    assert [b["quarter"] for b in api.sent("POST", "/api/tds-workspace/returns")] == ["Q1", "Q3", "Q4"]
    assert w["tds_statements_filed"] == 2 and w["tds_statements_prepared"] == 1


def test_a_statement_still_to_be_filed_is_left_prepared_and_not_filed(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2025, 10, 1))
    api = FakeApi()
    w = _run(api, ANAND, last_month="2025-10")
    filed = [b for m, p, b in api.calls if m == "PATCH" and b.get("status") == "filed"]
    assert [b["filing_date"] for b in filed] == ["2025-07-31"], "Q2's due date, 31 October, is still to come"
    assert w["tds_statements_prepared"] == 1


def test_form_24q_is_built_only_for_a_client_whose_payroll_withheld_tax():
    with_salary = FakeApi(runs=[{"month": "2025-05", "status": "paid", "total_tds_paise": 100}])
    _run(with_salary, SUNRISE)
    built = [p for p in with_salary.paths("POST") if p.endswith("/from-books")]
    assert built.count("/api/tds/24q/from-books") == 4 and built.count("/api/tds/26q/from-books") == 4
    assert {b["return_type"] for b in with_salary.sent("POST", "/api/tds-workspace/returns")} == {"24Q", "26Q"}
    none = FakeApi(runs=[{"month": "2025-05", "status": "paid", "total_tds_paise": 0}])
    _run(none, SUNRISE)
    assert not [p for p in none.paths("POST") if "24q" in p]
    no_payroll = FakeApi()
    _run(no_payroll, ANAND)
    assert not [p for p in no_payroll.paths("POST") if "24q" in p]


def test_the_requests_for_a_statement_carry_the_client_year_and_quarter_and_nothing_else():
    api = FakeApi()
    _run(api, ANAND)
    assert api.sent("POST", "/api/tds/26q/from-books")[0] == {"client_id": "cid", "financial_year": FY, "quarter": "Q1"}


# ── a year in progress, and what the stage will not take for an answer ─────

def _every_month_owes(section="194C", paise=500):
    months = [f"2025-{m:02d}" for m in range(4, 13)] + ["2026-01", "2026-02"]
    return {m: [{"section": section, "outstanding_paise": paise}] for m in months}


def test_a_year_in_progress_builds_no_statement_for_a_quarter_whose_deposit_is_still_to_come_and_reports_no_finding(monkeypatch):
    """`seed()` always passes the year's last month, so the reachable combination is last_month=March with today part way
    through the year (a `--financial-year` still running). Quarters whose deposits are all due are filed; the others are
    left alone and counted, and nothing is called a finding, because the seeder itself decided not to make those deposits."""
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2025, 10, 1))
    api = FakeApi(sheets=_every_month_owes())
    w = _run(api, ANAND, last_month="2026-03")
    assert w["returns_refused"] == []
    assert [b["quarter"] for b in api.sent("POST", "/api/tds-workspace/returns")] == ["Q1"], (
        "Q2's September deposit is due on 7 October, which is still to come")
    assert w["tds_statements_filed"] == 1 and w["tds_statements_not_yet_due"] == 3
    # the deposits that were due were recorded: April to August (September's falls due on 7 October)
    assert [b["challan_date"] for b in api.sent("POST", "/api/tds-workspace/challans")] == [
        "2025-05-07", "2025-06-07", "2025-07-07", "2025-08-07", "2025-09-07"]
    assert w["tds_deposits_not_yet_due"] == 6


def test_a_quarter_whose_deposits_are_all_due_is_still_built_when_another_quarter_is_not(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2026, 2, 10))
    api = FakeApi(sheets=_every_month_owes())
    w = _run(api, ANAND, last_month="2026-03")
    assert [b["quarter"] for b in api.sent("POST", "/api/tds-workspace/returns")] == ["Q1", "Q2", "Q3"], (
        "February's deposit falls due on 7 March, so only the last quarter waits")
    assert w["tds_statements_filed"] == 3 and w["tds_statements_prepared"] == 0 and w["tds_statements_not_yet_due"] == 1
    assert w["returns_refused"] == []


def test_a_salary_deposit_still_to_come_holds_back_the_24q_and_not_the_26q_of_that_quarter(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2025, 10, 1))
    sheets = {m: v for m, v in _every_month_owes().items() if m <= "2025-08"}
    api = FakeApi(sheets=sheets, runs=[{"month": "2025-09", "status": "paid", "total_tds_paise": 700}])
    w = _run(api, SUNRISE, last_month="2026-03")
    saved = [(b["return_type"], b["quarter"]) for b in api.sent("POST", "/api/tds-workspace/returns")]
    assert ("26Q", "Q2") in saved and ("24Q", "Q2") not in saved, (
        "September's salary deposit falls due on 7 October: the salary statement waits, the resident one does not")
    assert w["returns_refused"] == [] and w["tds_statements_not_yet_due"] >= 1


def test_a_deposit_the_worksheet_gives_no_due_date_for_is_a_finding_and_is_not_posted_with_a_date_of_the_seeds_own():
    api = FakeApi(sheets={"2025-07": [{"section": "194C", "outstanding_paise": 100}]}, due_dates={"2025-07": ""})
    w = _run(api, ANAND)
    assert not api.sent("POST", "/api/tds-workspace/challans")
    assert any("TDS challan 2025-07 194C" in m and "gave no due date" in m for m in w["returns_refused"])
    assert any("TDS 26Q Q2: not built" in m for m in w["returns_refused"])


def test_a_worksheet_the_server_refuses_as_success_false_is_a_finding_and_not_an_empty_month():
    """`Api.get` does not check the envelope and the TDS workspace answers a failure as HTTP 200 with success false, so a
    stage reading `data or {}` recorded nothing and said nothing."""
    api = FakeApi(sheets=_every_month_owes(),
                  unreadable={"2025-07": {"success": False, "data": None, "error": "Could not work out the deposit."}})
    w = _run(api, ANAND)
    refused = " | ".join(w["returns_refused"])
    assert "TDS deposit worksheet 2025-07" in refused and "Could not work out the deposit" in refused
    months = [b["challan_no"] for b in api.sent("POST", "/api/tds-workspace/challans")]
    assert "SEED-202507-194C" not in months and "SEED-202508-194C" in months, "the other months were still paid"
    assert not [b for b in api.sent("POST", "/api/tds-workspace/returns") if b["quarter"] == "Q2"], (
        "Q2 holds July, so its statement is not built, and says why instead of blaming the challans")
    assert "not built" in refused and "2025-07 deposit worksheet could not be read" in refused


@pytest.mark.parametrize("status", [404, 409, 422])
def test_a_read_the_server_refuses_with_a_4xx_is_a_finding_and_does_not_kill_the_run(status):
    def refuse():
        raise seeder.ApiRefusal(f"\nGET deposit-due -> HTTP {status}\nnot here\n", status)
    api = FakeApi(sheets=_every_month_owes(), unreadable={"2025-07": refuse})
    w = _run(api, ANAND)
    assert any("TDS deposit worksheet 2025-07" in m for m in w["returns_refused"])
    assert w["tds_challans"] == 10, "the other ten posted months were still deposited"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_a_read_that_means_every_later_call_fails_stops_the_run(status):
    def die():
        raise seeder.ApiRefusal(f"\nGET -> HTTP {status}\n", status)
    with pytest.raises(seeder.ApiRefusal):
        _run(FakeApi(unreadable={"2025-07": die}))
    with pytest.raises(seeder.ApiRefusal):
        _run(FakeApi(runs_answer=die))


def test_a_payroll_list_the_server_refuses_is_a_finding_and_the_stage_goes_no_further_for_that_client():
    api = FakeApi(sheets=_every_month_owes(), runs_answer={"success": False, "data": None, "error": "Payroll is switched off."})
    w = _run(api, SUNRISE)
    assert len(w["returns_refused"]) == 1 and "Payroll is switched off" in w["returns_refused"][0]
    assert not api.sent("POST", "/api/tds-workspace/challans") and not [p for p in api.paths("GET") if "deposit-due" in p], (
        "without knowing what payroll withheld, nothing is deposited and no statement is built")


def test_a_refused_challan_keeps_its_quarters_statement_from_being_blamed_on_the_challans():
    def refuse(body):
        if body["challan_no"] == "SEED-202507-194C":
            raise seeder.ApiRefusal("\nPOST challans -> HTTP 422\nperiod locked\nNothing", 422)
        return {"data": {"id": "ok"}}
    api = FakeApi(sheets=_every_month_owes(), refuse={"/api/tds-workspace/challans": refuse})
    w = _run(api, ANAND)
    assert any("the 2025-07 194C challan was not recorded" in m for m in w["returns_refused"])
    assert not [b for b in api.sent("POST", "/api/tds-workspace/returns") if b["quarter"] == "Q2"]


def test_an_empty_statement_beside_challans_just_recorded_is_a_finding_and_not_a_quarter_with_nothing_to_report():
    """The worksheet reads the deduction register and the statement reads the posted bills: when the first says tax was
    owed and the second finds no deductee, one of them is wrong, and counting the quarter as empty would hide it."""
    api = FakeApi(sheets=_every_month_owes(), statements={("26Q", "Q2"): _statement(deductees=0)})
    w = _run(api, ANAND)
    assert w["tds_quarters_without_deductions"] == 0
    assert any("Q2" in m and "3 challan(s) were recorded" in m and "no deductee" in m for m in w["returns_refused"])
    assert not [b for b in api.sent("POST", "/api/tds-workspace/returns") if b["quarter"] == "Q2"]


def test_a_statement_that_leaves_out_a_payment_to_a_non_resident_is_not_filed_as_the_quarters_tds():
    api = FakeApi(statements={("26Q", "Q3"): _statement(excluded_non_resident={"bill_count": 2, "tds_paise": 5000})})
    w = _run(api, ANAND)
    assert len(w["returns_refused"]) == 1 and "leaves out 2 payment(s) to a non-resident" in w["returns_refused"][0]
    assert [b["quarter"] for b in api.sent("POST", "/api/tds-workspace/returns")] == ["Q1", "Q2", "Q4"]
    clean = FakeApi(statements={("26Q", "Q3"): _statement(excluded_non_resident={"bill_count": 0, "tds_paise": 0})})
    assert _run(clean, ANAND)["returns_refused"] == []


# ── the calendar, refusals and a dead run ───────────────────────────────────

def test_each_filing_that_closes_its_obligation_is_counted_and_one_that_does_not_is_named():
    w = _run(FakeApi(), ANAND)
    assert w["obligations_closed"] == 3 and w["obligations_left_open"] == []
    api = FakeApi(closure={"state": "not_on_the_calendar", "closed": False, "message": "No TDS 26Q Q1 obligation is on the calendar."})
    w = _run(api, ANAND)
    assert len(w["obligations_left_open"]) == 3 and "Anand Textiles 26Q Q1" in w["obligations_left_open"][0]
    api = FakeApi(closure={"state": "already_filed", "closed": False})
    w = _run(api, ANAND)
    assert w["obligations_left_open"] == [] and w["obligations_closed"] == 0, "already filed is what was wanted"


def test_a_refusal_that_is_a_finding_does_not_stop_the_next_quarter():
    def refuse(body):
        if body.get("quarter") == "Q1":
            raise seeder.ApiRefusal("\nPOST returns -> HTTP 422\nbad PAN\nNothing", 422)
        return {"data": {"id": "ok"}}
    api = FakeApi(refuse={"/api/tds-workspace/returns": refuse})
    w = _run(api, ANAND)
    assert len(w["returns_refused"]) == 1 and w["tds_statements_filed"] == 2


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_a_dead_run_stops_instead_of_being_listed_one_by_one(status):
    def die(body):
        raise seeder.ApiRefusal(f"\nPOST -> HTTP {status}\n", status)
    api = FakeApi(sheets={"2025-04": [{"section": "194C", "outstanding_paise": 100}]},
                  refuse={"/api/tds-workspace/challans": die})
    with pytest.raises(seeder.ApiRefusal):
        _run(api)


def test_a_call_with_no_answer_is_reported_as_such():
    def silence(body):
        raise urllib.error.URLError("timed out")
    api = FakeApi(refuse={"/api/tds/26q/from-books": silence})
    w = _run(api, ANAND)
    assert len(w["returns_refused"]) == 4 and "no answer" in w["returns_refused"][0]


def test_the_stage_runs_after_income_tax_and_only_with_the_books_in_place():
    import inspect
    src = inspect.getsource(seeder.seed)
    assert src.index("_income_tax(api, c, client_id") < src.index("_tds(api, c, client_id"), (
        "the stage reads posted bills and finalized payroll runs, which are written before any return")
    assert src.index("_gst_returns(api, c, client_id") < src.index("_tds(api, c, client_id")


def test_the_stage_runs_in_a_process_that_cannot_import_the_api():
    """The seeder is a script an owner runs with a bare python3: a helper imported from a module that pulls in fastapi
    would die at the first statement."""
    import subprocess
    import sys
    code = r"""
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("fastapi", "starlette", "pydantic", "supabase", "httpx", "services"):
            raise ImportError(name + " is blocked: the seeder is a standalone script")
sys.meta_path.insert(0, Block())
sys.path.insert(0, %r)
from tests import test_the_seeders_tds_stage_deposits_what_the_worksheet_says_and_files_what_the_books_build as t
import core.ist_clock
core.ist_clock.ist_today = lambda: t.TODAY
w = t._written()
t.seeder._tds(t.FakeApi(), t.ANAND, "cid", t.FY, t.LAST_MONTH, w)
assert w["tds_statements_filed"] == 3 and not w["returns_refused"], w
print("ok")
""" % str(_API_ROOT)
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=str(_API_ROOT))
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-600:] or out.stdout
