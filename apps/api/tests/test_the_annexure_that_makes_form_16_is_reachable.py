"""PAY-11 — the year-end deliverable now has a screen and a file.

WHAT WAS WRONG
    GET /api/payroll/24q-annexure-ii has been finished since the payroll module
    was built and NO SCREEN CALLED IT. A grep of apps/web/{app,components,lib}
    for "annexure" returned nothing.

    Annexure II is not one report among several. CBDT Notification 09/2019
    makes Form 16 Part B a TRACES download — an employer who prints their own
    has issued nothing — and TRACES builds Part B from exactly ONE input: this
    annexure, filed with Q4. So it is the thing a whole year of payroll exists
    to produce, and a CA closing a client's year had to produce it elsewhere.

WHAT THIS PINS
    That the annexure is assembled ONCE and rendered twice. The screen reads
    the JSON, the CA downloads the CSV, and both come from
    _assemble_annexure_ii — so the figures a CA approved on screen are the
    figures that leave in the file.

    A CSV built in the browser from the JSON would be a second answer to "what
    is income under the head Salaries", and §16(iii) alone is enough to make
    the two disagree: §115BAC(2)(i) computes total income without any deduction
    under section 16 SAVE clause (ia), so professional tax is allowable only
    under the old regime — and payroll withholds on the new regime by default.
"""
from __future__ import annotations

import csv
import io

import pytest

from domain.payroll.annexure2 import (
    ANNEXURE_II_COLUMNS, AnnexureII, AnnexureIIRow, to_csv,
)
import routers.payroll as pay


def _rows(blob: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(blob.decode("utf-8-sig"))))


def _annexure(**over) -> AnnexureII:
    row = AnnexureIIRow(
        employee_id="E1", name="Asha Kumar", pan="ABCPK1234F", months_paid=12,
        salary_17_1_paise=6_00_000_00,
        standard_deduction_16_ia_paise=75_000_00,
        professional_tax_16_iii_paise=2_500_00,
        chapter_vi_a_paise=0, tds_deducted_paise=15_000_00,
        **over)
    return AnnexureII(rows=[row])


# ───────── the §16 treatment the two renderings must not disagree on ─────────

def test_professional_tax_is_not_allowed_under_the_new_regime():
    """§115BAC(2)(i). The column is the ALLOWABLE figure, not the deducted one,
    so a screen and a spreadsheet cannot arrive at different taxable salary."""
    new = _annexure(uses_new_regime=True).rows[0]
    old = _annexure(uses_new_regime=False).rows[0]
    assert new.allowable_professional_tax_paise == 0
    assert old.allowable_professional_tax_paise == 2_500_00
    # …and it moves income under the head by exactly that much.
    assert new.income_under_salaries_paise \
        - old.income_under_salaries_paise == 2_500_00


def test_the_file_carries_the_allowable_figure_and_not_the_deducted_one():
    body = _rows(to_csv(_annexure(uses_new_regime=True), financial_year="2026-27"))
    header = [h for h, _k in ANNEXURE_II_COLUMNS]
    data = body[body.index(header) + 1]
    pt = data[header.index("Professional Tax u/s 16(iii)")]
    assert pt == "0.00", "the new regime allows §16(ia) and nothing else"
    assert data[header.index("Income under the head Salaries")] == "525000.00"
    assert data[header.index("Regime")] == "115BAC (new)"


# ─────────────── the reasons travel with the file, not with a toast ──────────

def test_the_gaps_and_problems_are_in_the_file():
    """A CSV of names and taxable salary that does not say what is missing gets
    forwarded, filed and turned into a certificate. The banner on the screen
    that produced it does not travel with it."""
    ann = _annexure()
    ann.gaps.append("No Chapter VI-A declared for Asha Kumar.")
    ann.problems.append("PAN missing for one employee.")
    text = to_csv(ann, financial_year="2026-27").decode("utf-8-sig")
    assert "# MISSING: No Chapter VI-A declared for Asha Kumar." in text
    assert "# NOT READY: PAN missing for one employee." in text
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in text
    assert "TRACES" in text, "the file must say where Form 16 actually comes from"


def test_a_not_ready_year_still_downloads():
    """Same rule as the 24Q working paper: this is what a CA checks BEFORE
    filing Q4, and refusing to produce it refuses to show them what is wrong."""
    ann = _annexure()
    ann.problems.append("Something is wrong.")
    assert ann.is_ready is False
    body = _rows(to_csv(ann, financial_year="2026-27"))
    assert any(r and r[0] == "Asha Kumar" for r in body)


def test_the_total_row_adds_the_columns_it_labels():
    ann = AnnexureII(rows=[
        _annexure().rows[0],
        AnnexureIIRow(employee_id="E2", name="Ravi", pan="ABCPR1234F",
                      months_paid=6, salary_17_1_paise=3_00_000_00,
                      standard_deduction_16_ia_paise=75_000_00,
                      tds_deducted_paise=1_000_00),
    ])
    header = [h for h, _k in ANNEXURE_II_COLUMNS]
    body = _rows(to_csv(ann, financial_year="2026-27"))
    total = next(r for r in body if r and r[0] == "TOTAL")
    assert total[header.index("Gross Salary")] == "900000.00"
    assert total[header.index("TDS Deducted")] == "16000.00"


def test_an_empty_year_has_a_header_and_no_total():
    body = _rows(to_csv(AnnexureII(), financial_year="2026-27"))
    assert [h for h, _k in ANNEXURE_II_COLUMNS] in body
    assert not any(r and r[0] == "TOTAL" for r in body)


# ─────────────────────── one assembly, two renderings ───────────────────────

def test_both_endpoints_read_the_same_assembler():
    """Not "they agree" — the same function. Two assemblies would be two
    answers, and this is the document Form 16 is built from."""
    import inspect
    for fn in (pay.form_24q_annexure_ii, pay.form_24q_annexure_ii_csv):
        assert "_assemble_annexure_ii(" in inspect.getsource(fn), fn.__name__


def test_the_csv_endpoint_is_mounted_and_scoped():
    paths = {r.path for r in pay.router.routes}
    assert "/api/payroll/24q-annexure-ii" in paths
    assert "/api/payroll/24q-annexure-ii.csv" in paths
    # The client is named and checked in the assembler, which is where both
    # endpoints reach the database from.
    import inspect
    src = inspect.getsource(pay._assemble_annexure_ii)
    assert "assert_client_access(current_user, client_id)" in src


def test_nothing_here_issues_a_form_16():
    """The refusal is the point. There is no Part B generator and there must
    not be one — CBDT Notification 09/2019."""
    src = open(pay.__file__).read()
    assert "build_form_16" not in src
    assert not hasattr(pay, "generate_form_16")


# ───────────────────────── through the endpoint ─────────────────────────

CALLER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


def test_the_json_endpoint_answers_in_the_house_envelope():
    res = pay.form_24q_annexure_ii(client_id="C1", financial_year="2026-27",
                                   current_user=CALLER)
    assert res["success"] is True
    for key in ("rows", "problems", "gaps", "totals", "ready",
                "form_16_note", "disclaimer"):
        assert key in res["data"], key
    assert "DO NOT AUTO-SUBMIT" in res["data"]["disclaimer"]


def test_the_csv_endpoint_returns_a_file_named_for_the_year():
    res = pay.form_24q_annexure_ii_csv(client_id="C1", financial_year="2026-27",
                                       current_user=CALLER)
    assert res.media_type == "text/csv"
    assert "24Q-AnnexureII-2026-27.csv" in res.headers["content-disposition"]


def test_a_malformed_financial_year_is_refused_not_reinterpreted():
    """FYLabel, not str. '2026-28' passes ^\\d{4}-\\d{2}$ and then MEANS
    2026-27, which is a wrong answer rather than a rejected request."""
    from models.fy import FYLabel
    from pydantic import TypeAdapter, ValidationError
    with pytest.raises(ValidationError):
        TypeAdapter(FYLabel).validate_python("2026-28")
