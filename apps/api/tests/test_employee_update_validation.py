"""
EmployeeUpdateIn.status validator — the deactivate flow (PATCH status=
resigned/terminated) and any future reactivate (status=active) go through this
model. It must accept exactly the payroll_employees.status CHECK set and reject
anything else up front, so a bad value never reaches the DB as an opaque 500.

Pure Pydantic validation — no database needed.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.payroll import EmployeeUpdateIn


def test_status_accepts_the_check_set_and_normalizes_case():
    assert EmployeeUpdateIn(status="active").status == "active"
    assert EmployeeUpdateIn(status="resigned").status == "resigned"
    assert EmployeeUpdateIn(status="terminated").status == "terminated"
    # case-insensitive + trimmed
    assert EmployeeUpdateIn(status="ACTIVE").status == "active"
    assert EmployeeUpdateIn(status="  Resigned  ").status == "resigned"


def test_status_rejects_values_outside_the_check():
    for bad in ("deleted", "inactive", "fired", "paid", "left", ""):
        with pytest.raises(ValidationError):
            EmployeeUpdateIn(status=bad)


def test_status_optional_stays_none():
    # A partial update that doesn't touch status must not force one.
    assert EmployeeUpdateIn().status is None
    assert EmployeeUpdateIn(name="Ramesh Kumar").status is None
