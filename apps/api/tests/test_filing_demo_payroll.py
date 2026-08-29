"""PF ECR and ESI filing demos — the payroll pair, held to the framework rules.

Both flows derive from the payroll RUN (there is no separate return record):
services/filing_demo/pf_ecr.py and services/filing_demo/esi.py, ref
{"run_id": ...}. What is specific to this pair and pinned here:

  - NO signature ceremony: the monthly EPFO ECR and ESIC contribution flows
    are password logins with net-banking/online payment — no DSC, no OTP, no
    statutory declaration text. A declaration, signature or otp stage in
    either flow would teach a CA a ceremony that does not exist.
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
    """summary → account-head table → missing-UAN warning (E2 has none) →
    transmit → result. The monthly ECR has no signature ceremony at all."""
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "transmit", "result"]
    assert not any(k in kinds for k in ("declaration", "signature", "otp")), (
        "the monthly ECR flow is a password login — a signature or OTP stage "
        "teaches a ceremony that does not exist"
    )


def test_esi_follows_the_portal_sequence():
    """summary → EE/ER split table → missing-ESI-number warning (E3 has
    none) → transmit → result. Same shape as PF: no signature ceremony."""
    out = esi.build(_db(), FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "transmit", "result"]
    assert not any(k in kinds for k in ("declaration", "signature", "otp"))


def test_pf_warning_absent_when_every_member_has_a_uan():
    db = _db(employee_overrides={"E2": {"uan": "100555666777"}})
    out = pf_ecr.build(db, FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "transmit", "result"], (
        "with no missing UANs there is nothing to warn about — an empty "
        "warning stage is noise"
    )


def test_esi_warning_absent_when_every_covered_ip_has_a_number():
    db = _db(employee_overrides={"E3": {"esi_number": "3100999888"}})
    out = esi.build(db, FIRM, CLIENT, REF)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "transmit", "result"]


# ── The warnings name exactly the blocked members of THIS run ───────────────

def test_pf_warning_names_only_run_members_whose_slip_carries_pf():
    """E2 (PF in this run, no UAN) is named. A rostered employee outside the
    run with no UAN is not; nor is E3, whose UAN is on record."""
    db = _db()
    db.seed("payroll_employees", {
        "id": "E9", "firm_id": FIRM, "client_id": CLIENT,
        "name": "Zara Outside", "uan": None, "esi_number": None})
    out = pf_ecr.build(db, FIRM, CLIENT, REF)
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
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
    table = out["stages"][1]
    assert table["footer"][-1]["paise"] == 43_200_00


def test_esi_figures_are_the_runs_stored_total():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    summary = out["stages"][0]
    by_label = {f["label"]: f for f in summary["figures"]}
    assert by_label["ESI payable (employee + employer)"]["paise"] == 8_400_00
    table = out["stages"][1]
    assert table["footer"][-1]["paise"] == 8_400_00


def test_the_split_tables_never_fabricate_per_head_amounts():
    """The run stores EE+ER combined; the account-head/rate rows are
    indicative TEXT, and the only paise figure is the combined total in the
    footer."""
    for build in (pf_ecr.build, esi.build):
        out = build(_db(), FIRM, CLIENT, REF)
        table = next(s for s in out["stages"] if s["kind"] == "table")
        for row in table["rows"]:
            assert all("paise" not in cell for cell in row), (
                "a paise amount on a split row would be a fabricated split "
                "the stored data does not contain"
            )


# ── Statutory specifics ─────────────────────────────────────────────────────

def test_pf_challan_teaches_the_epfo_account_heads():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    table = next(s for s in out["stages"] if s["kind"] == "table")
    text = str(table)
    for head in ("A/c 1", "A/c 2", "A/c 10", "A/c 21", "A/c 22"):
        assert head in text, f"challan account head {head} missing"
    # EPS-95 para 3: 8.33% diverted from the employer's 12%, wages capped
    # at ₹15,000/month.
    assert "8.33%" in text and "₹15,000" in text
    assert "3.67%" in text  # employer balance after the EPS diversion
    assert "Nil at present" in text  # A/c 22 EDLI admin — waived


def test_esi_table_teaches_the_rule_51_rates_and_the_ceiling():
    out = esi.build(_db(), FIRM, CLIENT, REF)
    table = next(s for s in out["stages"] if s["kind"] == "table")
    text = str(table)
    # Rule 51, ESI (Central) Rules 1950, w.e.f. 01-07-2019.
    assert "0.75%" in text and "3.25%" in text
    # Rule 50: coverage wage ceiling.
    assert "₹21,000" in text and "₹25,000" in text


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

def test_pf_specimen_is_a_ten_digit_trrn_with_its_note():
    out = pf_ecr.build(_db(), FIRM, CLIENT, REF)
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert len(result["specimen"]) == 10 and result["specimen"].isdigit()
    assert result["reference_label"] == "Temporary Return Reference Number (TRRN)"
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
