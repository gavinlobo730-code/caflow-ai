"""
The employee master: a code the CA already uses, a date of birth §192 reads,
and ONE import that decides about the whole file.

WHAT WAS WRONG

1. THE OLD-REGIME NIL BAND WIDENS AT 60 AND PAYROLL NEVER KNEW.
   Part III of the First Schedule gives a resident individual "of the age of
   sixty years or more at any time during the previous year" a basic exemption
   of Rs 3,00,000, and Rs 5,00,000 at eighty.
   `domain/income_tax/itr_engine._slabs_for` has implemented all three ladders
   since the engine existed, reading `is_senior_citizen` and
   `is_very_senior_citizen` off its request — and
   `domain/payroll/declarations._build_request` set NEITHER, because the
   employee master held no date of birth.

   So an employee of 62 who intimated the old regime was withheld on the
   general ladder: a nil band Rs 50,000 too narrow, over-deducted every month
   and refunded a year later on assessment. §192(1) makes the employer
   answerable for a correct deduction.

   And the statutory test is "AT ANY TIME during the previous year", not an age
   on 1 April. Someone whose sixtieth birthday falls in March is senior for the
   WHOLE year — including the April payslip computed eleven months earlier.

2. THE BULK IMPORT ACCEPTED PART OF A FILE, AND COULD NOT BE RE-RUN.
   `buildEmployees` validated in the BROWSER and the screen POSTed one employee
   per row in a loop. Rows that validated were written; rows that did not were
   listed. A CA was left with thirty-one of fifty employees and no way to tell
   which nineteen were missing — and re-importing the corrected file made a
   SECOND copy of the thirty-one, because nothing identified an employee across
   two imports. A duplicated employee is paid twice, filed twice on the ECR
   under one UAN, and issued two Form 16s.

NEGATIVE CONTROLS
    Read the age on 1 April instead of during the year and
    test_a_march_birthday_is_senior_for_the_whole_year fails.
    Return only `senior` for an eighty-year-old and
    test_eighty_is_very_senior_not_merely_senior fails.
    Let validate() return the rows it liked and
    test_one_bad_row_refuses_the_whole_file fails.
    Drop the within-file duplicate check and
    test_a_file_that_repeats_a_code_is_refused fails.
"""
from __future__ import annotations

import pytest

from domain.payroll import age as age_domain
from domain.payroll import employee_import as importer


# ─── the age test the First Schedule actually states ────────────────────────

def test_a_march_birthday_is_senior_for_the_whole_year():
    """"At any time during the previous year" — the case a naive age-on-1-April
    gets wrong, in the direction that costs the employee."""
    # Turns 60 on 15 March 2027, which is inside FY 2026-27.
    assert age_domain.senior_status("1967-03-15", "2026-27") == (True, False)
    # On 1 April 2026 they were 58. An age-on-1-April reading says not senior.
    assert age_domain.age_reached_during_fy("1967-03-15", "2026-27") == 60


def test_turning_sixty_the_day_after_the_year_ends_is_not_this_year():
    """The boundary in the other direction: 1 April 2027 is FY 2027-28."""
    assert age_domain.senior_status("1967-04-01", "2026-27") == (False, False)
    assert age_domain.senior_status("1967-04-01", "2027-28") == (True, False)


def test_eighty_is_very_senior_not_merely_senior():
    """_slabs_for tests very_senior FIRST and falls through, so an 80-year-old
    marked only `senior` silently gets the 60-79 ladder."""
    senior, very = age_domain.senior_status("1946-06-01", "2026-27")
    assert senior and very


def test_an_unknown_date_of_birth_is_not_a_claim_that_they_are_young():
    """False/False reproduces the pre-existing behaviour, and `unknown` is what
    lets the caller say so rather than letting the silence stand."""
    assert age_domain.senior_status(None, "2026-27") == (False, False)
    assert age_domain.senior_status_unknown(None, "2026-27") is True
    assert age_domain.senior_status_unknown("1967-03-15", "2026-27") is False


def test_a_malformed_stored_date_does_not_stop_a_month_s_payroll():
    """This is read on the payslip path. A bad stored value becomes an unknown,
    which is reported — not an exception that fails the run."""
    assert age_domain.parse_dob("not-a-date") is None
    assert age_domain.senior_status("not-a-date", "2026-27") == (False, False)


# ─── the withholding it changes ─────────────────────────────────────────────

def test_a_senior_citizen_on_the_old_regime_is_withheld_less():
    """The whole point. Same salary, same declaration, different ladder."""
    from domain.payroll import declarations as decl_domain

    decl = decl_domain.Declaration(employee_id="E1", fy="2026-27",
                                   regime=decl_domain.REGIME_OLD,
                                   status=decl_domain.STATUS_VERIFIED)
    kwargs = dict(decl=decl, projected_annual_salary_paise=9_00_000 * 100,
                  fy="2026-27", verified_only=False)

    young = decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1990-01-01")
    senior = decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1960-01-01")
    unknown = decl_domain.withholding_tax_paise(**kwargs)

    assert young > 0, "the fixture must produce tax or the comparison is vacuous"
    assert senior < young, "the wider nil band must reduce the withholding"
    # Unknown behaves as it did before this existed — it is not a guess.
    assert unknown == young


def test_age_changes_nothing_under_the_new_regime():
    """§115BAC(1A) has ONE ladder for every individual — Finance Act 2023
    onwards it does not distinguish age at all. Payroll withholds on the new
    regime by default, so a senior citizen must see no change there."""
    from domain.payroll import declarations as decl_domain

    kwargs = dict(decl=None, projected_annual_salary_paise=15_00_000 * 100,
                  fy="2026-27", verified_only=False)
    assert (decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1960-01-01")
            == decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1990-01-01"))


def test_a_senior_citizen_s_interest_claim_becomes_80ttb_not_80tta():
    """A side effect of the same change, and the right one. §80TTA(2) expressly
    excludes a senior citizen; §80TTB gives them Rs 50,000 on ALL interest
    rather than Rs 10,000 on savings interest. The engine has always switched
    between the two on `is_senior_citizen` — and nothing was setting it, so a
    senior citizen's declared interest was capped at the §80TTA figure."""
    from domain.payroll import declarations as decl_domain

    decl = decl_domain.Declaration(employee_id="E1", fy="2026-27",
                                   regime=decl_domain.REGIME_OLD,
                                   status=decl_domain.STATUS_VERIFIED)
    decl.items.append(decl_domain.DeclarationItem(
        section=decl_domain.SECTION_80TTA, label="FD interest",
        amount_declared_paise=50_000 * 100,
        amount_verified_paise=50_000 * 100,
        status=decl_domain.ITEM_VERIFIED))
    kwargs = dict(decl=decl, projected_annual_salary_paise=12_00_000 * 100,
                  fy="2026-27", verified_only=True)

    young = decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1990-01-01")
    senior = decl_domain.withholding_tax_paise(**kwargs, date_of_birth="1960-01-01")
    # Two reasons senior is lower here — the wider nil band and the bigger
    # interest deduction — and both follow from the same date of birth.
    assert senior < young


# ─── the import: whole file, one decision ───────────────────────────────────

def _row(**kw) -> dict:
    base = {"name": "Asha Rao", "basic": "30000"}
    base.update(kw)
    return base


def test_one_bad_row_refuses_the_whole_file():
    """A partial import of a payroll master is never what anybody wanted. The
    good row is still PREPARED — a dry run has to be able to show it — but
    `ok` is what the endpoint gates the write on."""
    result = importer.validate(
        [_row(name="Asha Rao"), _row(name="", basic="1000")],
        existing_by_code={})
    assert not result.ok
    assert any("Row 2" in p and "name is required" in p for p in result.problems)


def test_every_problem_comes_back_at_once():
    """A file fixed one error at a time is a file uploaded nineteen times."""
    result = importer.validate(
        [_row(pan="NOTAPAN"), _row(uan="123"), _row(bank_ifsc="NOPE")],
        existing_by_code={})
    assert len(result.problems) == 3
    assert [p.split(":")[0] for p in result.problems] == ["Row 1", "Row 2", "Row 3"]


def test_a_file_that_repeats_a_code_is_refused():
    """Two rows for one person, and nothing here can know which is meant. The
    codes differ only in case, which is how a spreadsheet actually produces
    this."""
    result = importer.validate(
        [_row(employee_code="EMP001"), _row(employee_code="emp001")],
        existing_by_code={})
    assert not result.ok
    assert any("also on row 1" in p for p in result.problems)


def test_a_known_code_updates_and_an_unknown_one_creates():
    """What makes re-importing a corrected file safe rather than duplicating."""
    result = importer.validate(
        [_row(employee_code="EMP001", name="Asha Rao"),
         _row(employee_code="EMP002", name="Ravi Kumar")],
        existing_by_code={"emp001": "EMPLOYEE-UUID-1"})
    assert result.ok
    assert len(result.to_update) == 1 and result.to_update[0][0] == "EMPLOYEE-UUID-1"
    assert len(result.to_create) == 1
    assert result.to_create[0]["name"] == "Ravi Kumar"


def test_a_row_with_no_code_always_creates():
    """Nullable by design — employees added by hand before migration 333 have
    none, and the partial unique index lets NULLs coexist."""
    result = importer.validate([_row(), _row(name="Ravi Kumar")],
                               existing_by_code={"emp001": "X"})
    assert result.ok and len(result.to_create) == 2 and not result.to_update


# ─── what the file's cells are allowed to mean ──────────────────────────────

def test_an_indian_grouped_amount_is_read_as_written():
    """parseFloat("1,25,000") is 1 — the bug apps/web/lib/money/rupeeInput.ts
    exists for, and a spreadsheet exports grouped amounts."""
    result = importer.validate([_row(basic="1,25,000")], existing_by_code={})
    assert result.ok and result.to_create[0]["basic_paise"] == 1_25_000 * 100


def test_paise_are_concatenated_not_multiplied():
    """float("1145.30") * 100 is 114529.99999999999."""
    result = importer.validate([_row(basic="1145.30")], existing_by_code={})
    assert result.to_create[0]["basic_paise"] == 114_530


def test_a_basic_that_is_not_an_amount_is_refused_not_coerced():
    for bad in ("12abc", "1e3", "", "-500"):
        result = importer.validate([_row(basic=bad)], existing_by_code={})
        assert not result.ok, f"{bad!r} was accepted"


def test_a_date_is_read_day_first():
    """A spreadsheet in India writes 03/04/1985 for 3 April. Month-first moves
    a date of birth by a month — which, in March, decides whether the employee
    was sixty during the year."""
    result = importer.validate([_row(date_of_birth="03/04/1985")],
                               existing_by_code={})
    assert result.to_create[0]["date_of_birth"] == "1985-04-03"


def test_iso_is_accepted_unambiguously():
    result = importer.validate([_row(date_of_birth="1985-04-03")],
                               existing_by_code={})
    assert result.to_create[0]["date_of_birth"] == "1985-04-03"


def test_a_date_of_birth_in_the_future_is_a_miskeyed_year():
    """'2062-05-01' for '1962-05-01' would make a 62-year-old a minor."""
    result = importer.validate([_row(date_of_birth="2062-05-01")],
                               existing_by_code={})
    assert not result.ok
    assert any("not in the past" in p for p in result.problems)


def test_only_the_last_four_digits_of_aadhaar_survive():
    """UIDAI: the full number never reaches storage. models/payroll.py enforces
    the same thing on the single-employee path."""
    result = importer.validate([_row(aadhaar="1234 5678 9012")],
                               existing_by_code={})
    assert result.ok
    payload = result.to_create[0]
    assert payload["aadhaar_last4"] == "9012"
    assert "123456789012" not in str(payload)


def test_a_uan_that_is_not_twelve_digits_is_refused_here_not_at_the_epfo():
    """The ECR rejects it AFTER upload, by which time the round trip is lost."""
    assert not importer.validate([_row(uan="12345")], existing_by_code={}).ok
    assert importer.validate([_row(uan="100200300400")], existing_by_code={}).ok


def test_the_ifsc_shape_is_the_rbi_one():
    assert importer.validate([_row(bank_ifsc="HDFC0001234")], existing_by_code={}).ok
    assert not importer.validate([_row(bank_ifsc="HDFC1001234")], existing_by_code={}).ok


def test_a_blank_flag_takes_the_statutory_default_and_a_word_is_read():
    result = importer.validate([_row(), _row(pf_applicable="no", pt_applicable="Yes")],
                               existing_by_code={})
    assert result.ok
    assert result.to_create[0]["pf_applicable"] is True
    assert result.to_create[0]["pt_applicable"] is False
    assert result.to_create[1]["pf_applicable"] is False
    assert result.to_create[1]["pt_applicable"] is True


def test_a_flag_that_is_neither_is_refused_rather_than_read_as_false():
    """"maybe" silently becoming "not PF applicable" is an employee left out of
    the ECR."""
    result = importer.validate([_row(esi_applicable="maybe")], existing_by_code={})
    assert not result.ok


def test_an_empty_file_is_a_problem_not_a_success():
    result = importer.validate([], existing_by_code={})
    assert not result.ok and "no rows" in result.problems[0]


def test_the_template_is_a_header_and_nothing_else():
    """A template with example rows gets uploaded WITH the examples still in,
    and "Ravi Kumar, 50000" becomes an employee."""
    csv = importer.template_csv()
    assert csv.count("\n") == 1
    assert csv.startswith("employee_code,name,pan,date_of_birth")


# ─── the endpoint, on the real path ─────────────────────────────────────────

import routers.payroll as payroll_mod  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-IMPORT"
USER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "client_name": "Acme Pvt Ltd",
                       "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {
        "id": "CPS-1", "firm_id": FIRM, "client_id": "CLI",
        "payroll_enabled": True, "inputs_due_day": 5})
    return d


def _import(rows, **kw):
    from models.payroll import EmployeeImportIn
    return payroll_mod.import_employees(
        EmployeeImportIn(client_id="CLI", rows=rows, **kw), current_user=USER)


def test_a_clean_file_is_one_insert_for_every_row(db):
    out = _import([{"name": "Asha Rao", "basic": "30000", "employee_code": "EMP001"},
                   {"name": "Ravi Kumar", "basic": "45000", "employee_code": "EMP002"}])["data"]
    assert out["created"] == 2 and out["updated"] == 0
    assert len(db.rows("payroll_employees")) == 2
    stored = {r["employee_code"]: r for r in db.rows("payroll_employees")}
    assert stored["EMP001"]["basic_paise"] == 30_000 * 100
    assert stored["EMP001"]["firm_id"] == FIRM
    assert stored["EMP001"]["client_id"] == "CLI"


def test_re_importing_a_corrected_file_does_not_duplicate_anybody(db):
    """The whole reason employee_code exists. Before it, this produced a second
    Asha Rao — paid twice, filed twice on the ECR under one UAN, and issued two
    Form 16s."""
    _import([{"name": "Asha Rao", "basic": "30000", "employee_code": "EMP001"}])
    _import([{"name": "Asha Rao", "basic": "32000", "employee_code": "EMP001"}])
    rows = db.rows("payroll_employees")
    assert len(rows) == 1, "a second row is the duplicate this prevents"
    assert rows[0]["basic_paise"] == 32_000 * 100, "the correction must land"


def test_a_file_with_one_bad_row_writes_nothing_at_all(db):
    """Not "writes the good ones and reports the rest" — that is the shape that
    left a CA with thirty-one of fifty employees and no list of the nineteen."""
    with pytest.raises(HTTPException) as e:
        _import([{"name": "Asha Rao", "basic": "30000"},
                 {"name": "Ravi Kumar", "basic": "not-a-number"}])
    assert e.value.status_code == 422
    assert db.rows("payroll_employees") == []
    assert any("Row 2" in p for p in e.value.detail["problems"])


def test_a_dry_run_says_what_would_happen_and_writes_nothing(db):
    _import([{"name": "Asha Rao", "basic": "30000", "employee_code": "EMP001"}])
    out = _import([{"name": "Asha Rao", "basic": "31000", "employee_code": "EMP001"},
                   {"name": "New Person", "basic": "20000", "employee_code": "EMP009"}],
                  dry_run=True)["data"]
    assert out["would_update"] == 1 and out["would_create"] == 1
    assert db.rows("payroll_employees")[0]["basic_paise"] == 30_000 * 100


def test_a_client_payroll_is_not_switched_on_for_cannot_be_imported_into(db):
    """Migration 332's gate. The import is a WRITE like any other."""
    for row in db.rows("client_payroll_settings"):
        row["payroll_enabled"] = False
    with pytest.raises(HTTPException) as e:
        _import([{"name": "Asha Rao", "basic": "30000"}])
    assert e.value.status_code == 403
    assert db.rows("payroll_employees") == []


# ─── the run says when it did not know ──────────────────────────────────────

def test_an_old_regime_employee_with_no_date_of_birth_is_reported():
    """not-senior for an unknown date is the right DEFAULT and might be the
    wrong ANSWER. The run says so, rather than letting the zero speak."""
    from domain.payroll import declarations as decl_domain

    old = decl_domain.Declaration(employee_id="E1", fy="2026-27",
                                  regime=decl_domain.REGIME_OLD)
    gaps = payroll_mod._age_gap({"name": "Asha Rao"}, old, "2026-27")
    assert len(gaps) == 1 and "no date of birth" in gaps[0]
    assert "over-deducts" in gaps[0], "the gap must say which way it is wrong"


def test_a_recorded_date_of_birth_is_not_a_gap():
    from domain.payroll import declarations as decl_domain

    old = decl_domain.Declaration(employee_id="E1", fy="2026-27",
                                  regime=decl_domain.REGIME_OLD)
    assert payroll_mod._age_gap({"name": "Asha", "date_of_birth": "1967-03-15"},
                                old, "2026-27") == []


def test_the_new_regime_is_silent_about_age():
    """§115BAC(1A) has ONE ladder for every individual. Payroll withholds on the
    new regime by DEFAULT, so reporting this for every employee would put a line
    on every run that changes nothing — and a gap list nobody can act on is a
    gap list nobody reads."""
    from domain.payroll import declarations as decl_domain

    new = decl_domain.Declaration(employee_id="E1", fy="2026-27",
                                  regime=decl_domain.REGIME_NEW)
    assert payroll_mod._age_gap({"name": "Asha"}, new, "2026-27") == []
    # And an employee who has declared nothing at all is on the new regime.
    assert payroll_mod._age_gap({"name": "Asha"}, None, "2026-27") == []


# ─── the two column lists are one list ──────────────────────────────────────

def test_the_browser_s_column_list_mirrors_the_server_s():
    """`EMPLOYEE_IMPORT_COLUMNS` in apps/web is what a CA is shown to map their
    spreadsheet onto; `COLUMNS` here is what the import actually reads. If the
    browser offers a column the server ignores, the CA fills it in and it
    silently does nothing — which is worse than not offering it, because the
    file LOOKS complete.

    Asserted here rather than in the node suite because the server is the
    authority: a column added here and missing there is a column a CA cannot
    supply, and a column added there and missing here is a column that lies.
    """
    import re
    from pathlib import Path

    web = (Path(__file__).resolve().parents[3] / "apps" / "web"
           / "lib" / "imports" / "mappers.ts")
    if not web.exists():
        pytest.skip("apps/web not present in this checkout")

    text = web.read_text()
    block = text[text.index("export const EMPLOYEE_IMPORT_COLUMNS"):]
    block = block[:block.index("];")]
    browser = re.findall(r'\{\s*key:\s*"([^"]+)"', block)

    server = [name for name, _required in importer.COLUMNS]
    assert browser == server, (
        "the import template and the importer disagree about the columns:\n"
        f"  only in the browser: {sorted(set(browser) - set(server))}\n"
        f"  only on the server:  {sorted(set(server) - set(browser))}\n"
        "(order matters too — the header a CA is given is the header they map)"
    )


def test_the_required_columns_agree():
    """A column the server insists on but the browser marks optional produces a
    422 for a file the CA was told was complete."""
    import re
    from pathlib import Path

    web = (Path(__file__).resolve().parents[3] / "apps" / "web"
           / "lib" / "imports" / "mappers.ts")
    if not web.exists():
        pytest.skip("apps/web not present in this checkout")

    text = web.read_text()
    block = text[text.index("export const EMPLOYEE_IMPORT_COLUMNS"):]
    block = block[:block.index("];")]
    browser_required = {
        key for key, req in re.findall(
            r'\{\s*key:\s*"([^"]+)".*?required:\s*(true|false)', block)
        if req == "true"}

    assert browser_required == set(importer.REQUIRED)
