"""The ECR is downloaded under a name of letters and digits only, with a lower-case .txt (POST-A-519).

WHAT WAS WRONG
    The product named the file `ECR_202609.txt`. EPFO's notice on its upload page (User Manual for the Re-engineered ECR, v3.0,
    page 7, read at full size on 19-11-2026) says "Please only use alphabets and numbers in file names. Remove special characters
    and spaces from file names", and that the extension "should be in small case". Whether the portal really refuses an underscore
    is not known from the manual; its words are reason enough to take it out, at no cost. (EPFO's own "File Naming Convention" PDF
    is the rule for the scanned Form 9 upload and says nothing of the return file, so it settles nothing here.)

WHAT THE FIX DOES
    One function, `domain/payroll/ecr.ecr_file_name`, makes the name, and the ECR response and the hand-off panel both call it, so
    the screen and the download cannot name two different files.

NEGATIVE CONTROLS (each mutant was run and these fail)
    * put the underscore back in `ecr_file_name`        — the shape and the route tests fail
    * make the hand-off build its own name again        — the hand-off test fails
"""
from __future__ import annotations

import re

import pytest

import routers.payroll as pr
from domain.payroll.ecr import ecr_file_name
from tests.e2e_harness import FakeDB, wire_e2e

LETTERS_AND_DIGITS_WITH_A_SMALL_CASE_TXT = re.compile(r"^[A-Za-z0-9]+\.txt$")

FIRM = "FIRM-ECR519"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.mark.parametrize("month, name", [
    ("2026-09", "ECR202609.txt"),
    ("2026-10", "ECR202610.txt"),
    ("2027-03", "ECR202703.txt"),
])
def test_the_name_is_letters_and_digits_only(month, name):
    assert ecr_file_name(month) == name
    assert LETTERS_AND_DIGITS_WITH_A_SMALL_CASE_TXT.match(ecr_file_name(month))


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                       "payroll_enabled": True})
    d.seed("payroll_employees", {
        "id": "e-01", "firm_id": FIRM, "client_id": "CLI", "name": "Asha Kumar",
        "uan": "100200300401", "basic_paise": 15_000_00, "hra_percent": 0.0,
        "da_percent": 0.0, "other_allowances_paise": 0, "lta_paise": 0,
        "medical_paise": 0, "special_allowance_paise": 0, "pf_applicable": True,
        "eps_eligible": True, "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active"})
    return d


def _finalised_run(db) -> str:
    out = pr.create_run(pr.PayrollRunIn(client_id="CLI", month="2026-08"), CALLER)
    assert out["success"] is True
    run_id = out["data"]["id"]
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = "finalized"
    return run_id


def test_the_ecr_response_carries_that_name(db):
    resp = pr.run_ecr(run_id=_finalised_run(db), current_user=CALLER)
    assert resp["success"] is True
    assert resp["data"]["filename"] == "ECR202608.txt"
    assert LETTERS_AND_DIGITS_WITH_A_SMALL_CASE_TXT.match(resp["data"]["filename"])


def test_the_handoff_panel_offers_the_same_file_under_the_same_name(db):
    run_id = _finalised_run(db)
    ecr_name = pr.run_ecr(run_id=run_id, current_user=CALLER)["data"]["filename"]
    handoff = pr.run_handoff(run_id=run_id, current_user=CALLER)
    assert handoff["success"] is True
    epf = next(o for o in handoff["data"]["obligations"] if o["key"] == "epf")
    assert epf["artefact"]["filename"] == ecr_name == "ECR202608.txt"
