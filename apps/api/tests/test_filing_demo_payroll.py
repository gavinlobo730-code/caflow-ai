"""PF ECR and ESI filing demos — the payroll pair, held to the framework rules.

Both flows derive from the payroll RUN (there is no separate return record):
services/filing_demo/pf_ecr.py and services/filing_demo/esi.py, ref
{"run_id": ...}. What is specific to this pair and pinned here:

  - NO signature ceremony STAGE: nothing in EPFO's manual walk of the return or
    the payment, and nothing in ESIC's, asks for a declaration, a signature or
    an OTP in the product, and a stage that took one would teach a ceremony
    that is not ours to hold. What the PF flow does NOT claim (POST-A-518) is
    that the portal asks for none: the manual's home page carries notices that
    the OTP-based second step on the employer login "has been temporarily
    relaxed" and that "the existing digital signature process has been
    changed", and the manual does not say whether either touches the return.
  - The PF flow walks EPFO's User Manual (v3.0) in ITS order: the upload page,
    the checks, the Return File ID and return statement, the employer's
    approval (irreversible), the Due Deposit Balance Summary, the challan and
    only then the TRRN (15 digits), then the payment. The return and the
    payment are two acts, and the Scheme says so (paras 24(2)(ix) and 28(3)).
  - The stored run totals are employee + employer COMBINED, so the split
    tables carry indicative rate TEXT and the combined paise figure once —
    never a fabricated per-head split.
  - The missing-identifier warnings (UAN for PF, IP/ESI number for ESI) name
    exactly the employees whose slip actually carries that contribution in
    THIS run — not the whole roster.

The framework rules (writes-nothing scan, honest envelope, labelled
specimens) apply automatically via tests/test_filing_demo_framework.py.
"""
from __future__ import annotations

import importlib
import re

import pytest

from services.filing_demo import esi, pf_ecr
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"


def _db(run_overrides: dict | None = None,
        employee_overrides: dict[str, dict] | None = None) -> FakeDB:
    """One June-2026 finalized run, three employees:
      E1 — PF and ESI both deducted, both identifiers on record;
      E2 — PF only (over the ESI wage ceiling), UAN missing;
      E3 — PF and ESI both deducted, ESI number missing.
    Totals are the run's stored figures (EE+ER combined), deliberately NOT
    the sum of the slips — the demos must present the run's stored totals.
    """
    db = FakeDB()
    run = {
        "id": "RUN1", "firm_id": FIRM, "client_id": CLIENT,
        "month": "2026-06", "status": "finalized", "headcount": 3,
        "total_gross_paise": 9_00_000_00, "total_net_paise": 7_80_000_00,
        "total_pf_paise": 43_200_00, "total_esi_paise": 8_400_00,
    }
    run.update(run_overrides or {})
    db.seed("payroll_runs", run)

    slips = [
        {"id": "S1", "run_id": "RUN1", "employee_id": "E1",
         "pf_employee_paise": 1_800_00, "pf_employer_paise": 1_800_00,
         "esi_employee_paise": 150_00, "esi_employer_paise": 650_00},
        {"id": "S2", "run_id": "RUN1", "employee_id": "E2",
         "pf_employee_paise": 1_800_00, "pf_employer_paise": 1_800_00,
         "esi_employee_paise": 0, "esi_employer_paise": 0},
        {"id": "S3", "run_id": "RUN1", "employee_id": "E3",
         "pf_employee_paise": 1_440_00, "pf_employer_paise": 1_440_00,
         "esi_employee_paise": 90_00, "esi_employer_paise": 390_00},
    ]
    for s in slips:
        db.seed("payroll_slips", s)

    employees = {
        "E1": {"id": "E1", "firm_id": FIRM, "client_id": CLIENT,
               "name": "Asha Rao", "uan": "100123456789",
               "esi_number": "3100123456"},
        "E2": {"id": "E2", "firm_id": FIRM, "client_id": CLIENT,
               "name": "Bharat Iyer", "uan": None,
               "esi_number": None},
        "E3": {"id": "E3", "firm_id": FIRM, "client_id": CLIENT,
               "name": "Chitra Nair", "uan": "100987654321",
               "esi_number": None},
    }
    for emp_id, override in (employee_overrides or {}).items():
        employees[emp_id].update(override)
    for e in employees.values():
        db.seed("payroll_employees", e)
    return db


REF = {"run_id": "RUN1"}


# ── The envelope is honest, for both flows ──────────────────────────────────

def test_pf_envelope_is_honest():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["flow"] == "pf"
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-PF-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False, (
        "EPFO has no public API for ECR upload; claiming software may "
        "transmit it would teach a CA something false"
    )


def test_esi_envelope_is_honest():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["flow"] == "esi"
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-ESI-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False


# ── The sequence is the real portal's: no DSC, no OTP, no declaration ───────

def test_pf_follows_the_portal_sequence():
    """summary → the upload page → the ECR file and its checks → the
    sequential-filing warning → the approval warning → the Due Deposit Balance
    Summary → account-head table → missing-UAN warning (E2 has none) →
    transmit → result.

    The order is EPFO's own User Manual (v3.0, POST-A-518): the file and its
    checks come first, then the Return File ID and the employer's approval,
    then the summary of what is due, and the challan (with its TRRN) only
    after that — so the account-head table, which describes the challan, comes
    after the summary and not before the upload. There is no signature
    ceremony stage."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "table", "warning", "warning",
                     "table", "table", "warning", "transmit", "result"]
    titles = [s.get("title") for s in out["stages"] if s["kind"] == "table"]
    assert titles == ["The upload page",
                      "The ECR file, and what the portal checks",
                      "The Due Deposit Balance Summary",
                      "Challan account heads"]
    assert not any(k in kinds for k in ("declaration", "signature", "otp")), (
        "no stage takes a declaration, a signature or an OTP: whether the "
        "portal asks for one is not settled by the manual, and an OTP is "
        "typed on the portal, never here"
    )


def test_esi_follows_the_portal_sequence():
    """summary → EE/ER split table → the coverage table (who is on this
    filing, and until when) → missing-ESI-number warning (E3 has none) →
    transmit → result. Same shape as PF: no signature ceremony."""
    out = esi.build(_db(), FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "table", "warning", "transmit",
                     "result"]
    assert not any(k in kinds for k in ("declaration", "signature", "otp"))


def test_pf_warning_absent_when_every_member_has_a_uan():
    db = _db(employee_overrides={"E2": {"uan": "100555666777"}})
    out = pf_ecr.build(db, FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "table", "warning", "warning",
                     "table", "table", "transmit", "result"], (
        "with no missing UANs there is nothing to warn about — an empty "
        "warning stage is noise. The sequential-filing warning and the "
        "approval warning stay: both are unconditional, because the order and "
        "the irreversibility apply to every month"
    )
    assert "wage-month ORDER" in out["stages"][3]["text"]


def test_esi_warning_absent_when_every_covered_ip_has_a_number():
    db = _db(employee_overrides={"E3": {"esi_number": "3100999888"}})
    out = esi.build(db, FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "table", "transmit", "result"]


# ── The warnings name exactly the blocked members of THIS run ───────────────

def test_pf_warning_names_only_run_members_whose_slip_carries_pf():
    """E2 (PF in this run, no UAN) is named. A rostered employee outside the
    run with no UAN is not; nor is E3, whose UAN is on record."""
    db = _db()
    db.seed("payroll_employees", {
        "id": "E9", "firm_id": FIRM, "client_id": CLIENT,
        "name": "Zara Outside", "uan": None, "esi_number": None})
    out = pf_ecr.build(db, FIRM, CLIENT, REF)
    warning = next(s for s in out["stages"]
                   if s["kind"] == "warning" and "UAN" in s["text"])
    assert "Bharat Iyer" in warning["text"]
    assert "Zara Outside" not in warning["text"]
    assert "Chitra Nair" not in warning["text"]
    assert "UAN" in warning["text"]


def test_esi_warning_names_only_run_members_whose_slip_carries_esi():
    """E3 (ESI deducted, no number) is named. E2 has no ESI number either,
    but no ESI is deducted on E2's slip — over the ₹21,000 ceiling, E2 is
    simply not in this filing and must not be flagged."""
    out = esi.build(_db(), FIRM, CLIENT, REF)
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
    assert "Chitra Nair" in warning["text"]
    assert "Bharat Iyer" not in warning["text"]
    assert "ESI number" in warning["text"]


# ── The figures are the run's stored totals, paise-exact ────────────────────

def test_pf_figures_are_the_runs_stored_total():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    summary = out["stages"][0]
    by_label = {f["label"]: f for f in summary["figures"]}
    assert by_label["PF payable (employee + employer)"]["paise"] == 43_200_00
    assert by_label["Wage month"]["text"] == "2026-06"
    assert by_label["Employees in this run"]["text"] == "3"
    table = next(s for s in out["stages"]
                 if s.get("title") == "Challan account heads")
    assert table["footer"][-1]["paise"] == 43_200_00


def test_esi_figures_are_the_runs_stored_total():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    summary = out["stages"][0]
    by_label = {f["label"]: f for f in summary["figures"]}
    assert by_label["ESI payable (employee + employer)"]["paise"] == 8_400_00
    table = next(s for s in out["stages"]
                 if s.get("title") == "Contribution split")
    assert table["footer"][-1]["paise"] == 8_400_00


def test_the_split_tables_never_fabricate_per_head_amounts():
    """The run stores EE+ER combined; the account-head/rate rows are
    indicative TEXT, and the only paise figure is the combined total in the
    footer."""
    for build, title in ((pf_ecr.build, "Challan account heads"),
                         (esi.build, "Contribution split")):
        out = build(_db(), FIRM, CLIENT, REF)
        table = next(s for s in out["stages"] if s.get("title") == title)
        for row in table["rows"]:
            assert all("paise" not in cell for cell in row), (
                "a paise amount on a split row would be a fabricated split "
                "the stored data does not contain"
            )


# ── Statutory specifics ─────────────────────────────────────────────────────

def test_pf_challan_teaches_the_epfo_account_heads():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    table = next(s for s in out["stages"]
                 if s.get("title") == "Challan account heads")
    text = str(table)
    for head in ("A/c 1", "A/c 2", "A/c 10", "A/c 21", "A/c 22"):
        assert head in text, f"challan account head {head} missing"
    # Employees' Pension Scheme, 2026 para 4(1): 8.33% diverted from the
    # employer's 12%, on wages up to the wage ceiling the Government
    # notifies. The ceiling is ₹15,000 for a wage month before 17-09-2026
    # and ₹25,000 from it (S.O. 5109(E)), so a challan table that printed
    # either figure as the limit would be wrong for the other months: it
    # names the notified ceiling and leaves the amount to the run (POST-A-516).
    assert "8.33%" in text and "notified wage ceiling" in text
    assert "₹15,000" not in text and "₹25,000" not in text, (
        "the challan table must not hard-code a wage ceiling that moved on "
        "17-09-2026")
    assert "3.67%" in text  # employer balance after the EPS diversion
    assert "Nil at present" in text  # A/c 22 EDLI admin — waived


def test_esi_table_teaches_the_rule_51_rates_and_the_ceiling():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    table = next(s for s in out["stages"]
                 if s.get("title") == "Contribution split")
    text = str(table)
    # Rule 51, ESI (Central) Rules 1950, w.e.f. 01-07-2019.
    assert "0.75%" in text and "3.25%" in text
    # Rule 50: coverage wage ceiling.
    assert "₹21,000" in text and "₹25,000" in text


def test_the_ecr_stage_carries_the_four_checks_that_reject_the_file():
    """The ECR is a text file the portal parses, and an upload that fails on
    one member line fails as a whole. These are the four validations the
    revamped ECR applies (docs/audits/2026-09-07-market-research/
    payroll-primary.md §4), and the format itself — .txt, #~# separated,
    eleven fields per member, keyed by UAN, unchanged by the 2025 revamp."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    stage = next(s for s in out["stages"]
                 if s.get("title") == "The ECR file, and what the portal checks")
    checks = [r[0]["text"] for r in stage["rows"]]
    assert checks == [
        "EPF wages ≤ gross wages",
        "EPS wages ≤ EPF wages",
        "EDLI wages = EPF wages, capped at the notified wage ceiling",
        "Every member line carries a UAN",
    ]
    assert "#~#" in stage["note"] and "eleven fields" in stage["note"]
    assert all("paise" not in c for row in stage["rows"] for c in row), (
        "the checks are rules, not amounts — a paise figure here would be a "
        "per-member split the run does not store")


def test_the_pf_sequence_warning_is_unconditional_and_names_the_no_active_members_route():
    """Sequential filing is what actually stops a bureau: since the
    re-engineered ECR (wage month September 2025) a later month cannot be
    uploaded while an earlier one is pending, so one skipped month blocks
    every month after it. A month with no active members is NOT a NIL return
    (POST-A-518): the portal's FAQ, question 21, has its administrative and
    inspection charges paid through Direct Challan Entry, which is enabled only
    when there are no active members. It is not conditional on anything in the
    run, so it renders every time."""
    out = pf_ecr.build(_db(employee_overrides={"E2": {"uan": "100555666777"}}),
                       FIRM, CLIENT, REF)
    warning = next(s for s in out["stages"]
                   if s["kind"] == "warning" and "ORDER" in s["text"])
    assert "September 2025" in warning["text"]
    assert "Direct Challan Entry" in warning["text"]
    assert "NIL return" not in warning["text"], (
        "the FAQ does not say a month with no active members needs a NIL "
        "return; it says the charges are paid through Direct Challan Entry"
    )
    assert "two separate acts" in warning["text"], (
        "filing the return and paying the challan are two acts; approving the "
        "return is not a payment and the TRRN is not the return's reference"
    )


def test_the_pf_approval_warning_says_an_approval_cannot_be_undone_and_names_the_route():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    warning = next(s for s in out["stages"]
                   if s["kind"] == "warning" and "approves or rejects" in s["text"])
    assert "cannot be modified" in warning["text"]
    assert "Revised return" in warning["text"], (
        "an irreversible step names the lawful correction route rather than "
        "reading as a dead end"
    )


def _every_string(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _every_string(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _every_string(v)


def test_the_pf_walk_through_never_says_no_otp_and_never_says_nil_return():
    """POST-A-518, points 3 and 4. EPFO's manual carries two notices about the
    OTP-based second step and the digital signature process and does not say
    whether either touches the return, so a sentence saying there is none
    cannot stand; and the FAQ has no 'NIL return' for a month with no active
    members."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    text = " ".join(_every_string(out))
    for banned in ("no DSC and no OTP", "No DSC and no OTP", "no OTP", "NIL return",
                   "nil-ECR", "NIL ECR"):
        assert banned not in text, banned
    assert "does not say whether" in out["real_channel"]["how"]


def test_the_trrn_is_issued_at_the_challan_and_not_at_the_upload():
    """POST-A-518, point 1: the walk-through put the TRRN at the upload and
    generated the challan when the file was verified. In EPFO's manual the file
    gives a Return File ID, the employer approves, the summary follows, and the
    TRRN is issued only when the challan is finalised."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    transmit = next(s for s in out["stages"] if s["kind"] == "transmit")
    keys = [step["key"] for step in transmit["steps"]]
    assert keys == ["prepare", "upload", "validate", "approve", "summary",
                    "challan", "payment"]
    with_trrn = [step["key"] for step in transmit["steps"] if "TRRN" in step["label"]]
    assert with_trrn == ["challan"]
    validate = next(step for step in transmit["steps"] if step["key"] == "validate")
    assert "Return File ID" in validate["label"]


def test_the_upload_page_table_names_the_file_the_way_the_download_does():
    """The name EPFO's notice asks for (letters and digits only, a small-case
    extension) is the name the product gives the download, from one function."""
    from domain.payroll.ecr import ecr_file_name
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    table = next(s for s in out["stages"] if s.get("title") == "The upload page")
    text = " ".join(_every_string(table))
    assert ecr_file_name("2026-09") in text
    assert "12% or 10%" in text


def test_the_esi_coverage_stage_teaches_the_contribution_period():
    """The rule payroll gets backwards most often: an employee whose wages
    cross ₹21,000 mid-period stays covered and contributory to the END of
    that contribution period. Dropping them in the month of the rise
    under-remits for every month left in the period — and it decides who is
    on THIS filing, which is what the walk-through is about."""
    out = esi.build(_db(), FIRM, CLIENT, REF)
    stage = next(s for s in out["stages"]
                 if s.get("title") == "Who is covered, and until when")
    rows = {r[0]["text"]: r[1]["text"] for r in stage["rows"]}
    period_row = next(k for k in rows if "Contribution periods" in k)
    assert "1 April to 30 September" in rows[period_row]
    assert "1 October to 31 March" in rows[period_row]
    crossing = next(k for k in rows if "cross the ceiling" in k)
    assert "STAYS covered" in rows[crossing]
    assert "under-remits" in rows[crossing]
    # The research grades the mechanics [S] but the "Rule 50 / Rule 51, ESI
    # (Central) Rules 1950" citation [U] — possibly superseded by rules under
    # the Code on Social Security. A wrong citation beside a right fact is
    # worse than the fact alone, so this stage carries no rule number.
    assert "Rule" not in str(stage["rows"]), (
        "the contribution-period rule number is unverified; state the "
        "mechanics, not a citation nobody has confirmed")


def test_both_flows_say_what_changes_when_filing_is_real():
    """And both have to give the SAME uncomfortable answer: there is no
    registration to wait for. EPFO and ESIC publish no API, and the door is
    the CLIENT's own establishment login — which the firm should not hold.
    A roadmap note implying a coming integration would be selling something
    that does not exist."""
    for build, portal in ((pf_ecr.build, "epfindia.gov.in"),
                          (esi.build, "esic.gov.in")):
        note = build(_db(), FIRM, CLIENT, REF)["when_this_is_real"]
        assert "no registration to wait for" in note
        assert portal in note
        assert "belongs to the client" in note


# What each walk-through's "what changes when this is real" may say about the FILE.
#
# The two texts used to say "What PracticeSync will do is produce the ECR .txt"
# and "...produce the contribution file": the future tense, for a file that
# domain/payroll/ecr.build_ecr and domain/payroll/esic.build_esic_return have
# produced from a finalised run, and routers/payroll has served, for a long
# time. A CA shown the walk-through was told a shipped feature was future work
# (COMING-016, COMING-017). The rule is not a spelling: where the product
# already builds the file the walk-through says so in the present tense, and the
# premise test below is what would make the future tense true again.

#: flow -> (module, the builder that produces the file, the route that serves
#: it, the walk-through module)
_FILE_BUILT_TODAY = {
    "pf": ("domain.payroll.ecr", "build_ecr", "/runs/{run_id}/ecr", pf_ecr),
    "esi": ("domain.payroll.esic", "build_esic_return", "/runs/{run_id}/esic", esi),
}

#: The product speaking about its own future work: "PracticeSync will ...",
#: "it will ...". A sentence about somebody else's future ("the portal will
#: reject") is not this rule's business.
_PRODUCT_FUTURE = re.compile(
    r"\b(?:PracticeSync|it|this app|this product|the product)\s+will\b", re.I)


@pytest.mark.parametrize("flow", sorted(_FILE_BUILT_TODAY))
def test_the_premise_the_file_is_built_and_served_today(flow):
    """The reason the present tense is the true one. If a builder or its route
    is removed this fails first, and the walk-through's wording is then a
    decision, not a leftover."""
    from routers import payroll as payroll_router

    module_name, builder, route_suffix, _ = _FILE_BUILT_TODAY[flow]
    assert callable(getattr(importlib.import_module(module_name), builder, None)), (
        f"{module_name}.{builder} is gone: the {flow} walk-through may speak of "
        "the file as future work again, but say so deliberately")
    assert any(getattr(r, "path", "").endswith(route_suffix)
               for r in payroll_router.router.routes), (
        f"no payroll route ends in {route_suffix}: the file is no longer served")


@pytest.mark.parametrize("flow", sorted(_FILE_BUILT_TODAY))
def test_a_file_the_product_already_produces_is_not_future_work(flow):
    walkthrough = _FILE_BUILT_TODAY[flow][3]
    note = walkthrough.build(_db(), FIRM, CLIENT, REF)["when_this_is_real"]
    future = _PRODUCT_FUTURE.findall(note)
    assert not future, (
        f"the {flow} walk-through speaks of what PracticeSync {future!r} do, but "
        f"{_FILE_BUILT_TODAY[flow][1]} already builds the file. Say it in the "
        "present tense: what is built, and what stays with the portal login")
    assert re.search(r"\bproduces\b", note), (
        f"the {flow} walk-through never says PracticeSync produces the file")


def test_the_future_tense_rule_fires_on_the_old_wording():
    """Verify clause: the rule above is shown to fail on the sentences it was
    written for, so it is not vacuous."""
    old_pf = ("What PracticeSync will do is produce the ECR .txt itself, member "
              "by member with each UAN.")
    old_esi = "...and it will flag the coverage the table above describes"
    assert _PRODUCT_FUTURE.search(old_pf)
    assert _PRODUCT_FUTURE.search(old_esi)
    assert not _PRODUCT_FUTURE.search("EPFO will reject a file with no UAN.")


def test_both_due_dates_are_the_15th_of_the_following_month():
    """Para 38(1) EPF Scheme 1952 / Regulation 31 ESI (General) Regulations
    1950 — and the December→January rollover crosses the year."""
    for build in (pf_ecr.build, esi.build):
        out = build(_db(), FIRM, CLIENT, REF)
        due = next(f for f in out["stages"][0]["figures"]
                   if f["label"] == "Due date")
        assert "15-07-2026" in due["text"]
        out = build(_db(run_overrides={"month": "2026-12"}), FIRM, CLIENT, REF)
        due = next(f for f in out["stages"][0]["figures"]
                   if f["label"] == "Due date")
        assert "15-01-2027" in due["text"]


# ── Realism is labelled ─────────────────────────────────────────────────────

def test_pf_specimen_is_a_fifteen_digit_trrn_with_its_note():
    """15 digits, in the shape of the manual's own example (250113000000438);
    it was 10 until POST-A-518."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert len(result["specimen"]) == 15 and result["specimen"].isdigit()
    assert result["reference_label"] == "Challan reference (TRRN)"
    assert "Return File ID" in result["filed_line"], (
        "the return has its own reference; the result says the TRRN is not it")
    assert "SPECIMEN" in result["specimen_note"]
    assert "EPFO" in result["specimen_note"]
    assert any("Nothing was uploaded and nothing was paid" in t
               for t in result["truth"]), (
        "the ECR ends in a net-banking payment — the demo must say no money "
        "moved, not just that no return was filed"
    )


def test_esi_specimen_is_a_nineteen_digit_challan_with_its_note():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert len(result["specimen"]) == 19 and result["specimen"].isdigit()
    assert result["reference_label"] == "Challan number"
    assert "SPECIMEN" in result["specimen_note"]
    assert "ESIC" in result["specimen_note"]
    assert any("Nothing was submitted and nothing was paid" in t
               for t in result["truth"])


# ── Refusals: every one a plain sentence, never a 500 ───────────────────────

def test_both_flows_need_a_run_id():
    with pytest.raises(ValueError, match="run_id"):
        pf_ecr.build(_db(), FIRM, CLIENT, {})
    with pytest.raises(ValueError, match="run_id"):
        esi.build(_db(), FIRM, CLIENT, {})


def test_a_missing_run_is_an_answer_not_an_incident():
    with pytest.raises(ValueError, match="not found"):
        pf_ecr.build(_db(), FIRM, CLIENT, {"run_id": "NOPE"})
    with pytest.raises(ValueError, match="not found"):
        esi.build(_db(), FIRM, CLIENT, {"run_id": "NOPE"})


def test_another_firms_run_is_not_found_here():
    """Tenancy: the run select carries firm and client filters, so another
    firm's run id answers 'not found' rather than leaking figures."""
    with pytest.raises(ValueError, match="not found"):
        pf_ecr.build(_db(), "FIRM-B", CLIENT, REF)
    with pytest.raises(ValueError, match="not found"):
        esi.build(_db(), "FIRM-B", CLIENT, REF)


@pytest.mark.parametrize("status", ["draft", "review"])
def test_an_unsettled_run_is_refused(status):
    db = _db(run_overrides={"status": status})
    with pytest.raises(ValueError, match="finalize"):
        pf_ecr.build(db, FIRM, CLIENT, REF)
    with pytest.raises(ValueError, match="finalize"):
        esi.build(db, FIRM, CLIENT, REF)


def test_a_paid_run_still_qualifies():
    """'paid' (migration 225) is downstream of finalized — the contribution
    filing is still due, so the walk-through must not vanish at disbursement."""
    db = _db(run_overrides={"status": "paid"})
    assert pf_ecr.build(db, FIRM, CLIENT, REF)["flow"] == "pf"
    assert esi.build(db, FIRM, CLIENT, REF)["flow"] == "esi"


def test_a_run_with_nothing_to_deposit_is_refused():
    with pytest.raises(ValueError, match="no PF contribution"):
        pf_ecr.build(_db(run_overrides={"total_pf_paise": 0}), FIRM, CLIENT, REF)
    with pytest.raises(ValueError, match="no ESI contribution"):
        esi.build(_db(run_overrides={"total_esi_paise": 0}), FIRM, CLIENT, REF)
