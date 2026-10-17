"""A compliance record created without a status gets one the database accepts (ledger POST-A-209).

`ComplianceRecordIn.status` defaulted to `"pending"`, which is outside `compliance_records_status_check` (migration 108)
and outside `VALID_TRANSITIONS`; the in-memory suite accepted it, the real table would have refused the insert. No screen
creates a record through this route today, so it was latent; the default is now the first state of the lifecycle.

The rule is asserted against the CHECK constraint's own text rather than a copy of its list, so a state added to the
constraint or the lifecycle later cannot leave the default stranded.

THE SAME ROUTE HAD TWO MORE WAYS TO FAIL AGAINST A REAL DATABASE, found by the independent review of the status fix:
`due_date` and `period_label` are NOT NULL with no default, the request model carries both as Optional, and the service
read them with `data["due_date"]` / `data.get("period_label", "")`, both of which return the PRESENT key's None. So an
omitted due date came back as a 500 (23502) and not as a refusal in words. The payload a manual create sends is now held
against the production schema's own NOT NULL, no-default columns.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.exceptions import ValidationError
from domain.compliance_record_service import VALID_TRANSITIONS, compliance_record_service
from routers.compliance_records import ComplianceRecordIn

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _statuses_the_database_accepts() -> set[str]:
    """The LAST migration that defines the constraint, found by number."""
    defining = sorted(p for p in _MIGRATIONS.glob("[0-9]*.sql")
                      if "compliance_records_status_check" in p.read_text(encoding="utf-8")
                      and "ADD CONSTRAINT compliance_records_status_check" in p.read_text(encoding="utf-8")
                      and not p.name.endswith("_rollback.sql"))
    text = defining[-1].read_text(encoding="utf-8")
    block = text.split("ADD CONSTRAINT compliance_records_status_check", 1)[1].split(";", 1)[0]
    return set(re.findall(r"'([^']+)'", block))


def test_the_default_status_is_one_the_database_accepts_and_the_lifecycle_starts_at():
    accepted = _statuses_the_database_accepts()
    assert len(accepted) >= 8, accepted
    default = ComplianceRecordIn(client_id="c", compliance_type="GSTR-3B").status
    assert default in accepted, f"{default!r} is not in the status CHECK {sorted(accepted)}"
    assert default in VALID_TRANSITIONS, f"{default!r} is not a state of the lifecycle"
    assert default == "Not Started"


def test_the_lifecycle_and_the_constraint_name_the_same_states():
    assert set(VALID_TRANSITIONS) == _statuses_the_database_accepts()


# ── a manual create sends a value for every column the table needs ───────────────────────────────────────────────────

_SCHEMA = Path(__file__).resolve().parent / "fixtures" / "production_schema_2026-09-03.json"


def _columns_the_insert_must_supply() -> set[str]:
    """NOT NULL, no default, in production's own `compliance_records` (a snapshot, refreshed by hand)."""
    table = json.loads(_SCHEMA.read_text(encoding="utf-8"))["compliance_records"]
    return {name for name, col in table.items() if col["nullable"] == "NO" and not col["default"]}


def _captured_create(monkeypatch, **body):
    from domain import compliance_record_service as module

    sent = []
    monkeypatch.setattr(module.compliance_records_repo, "find_all", lambda **k: [])
    monkeypatch.setattr(module.compliance_records_repo, "create", lambda payload: sent.append(payload) or {
        **payload, "id": "r1", "created_at": "2026-10-17T00:00:00+00:00", "updated_at": "2026-10-17T00:00:00+00:00"})
    request = {"client_id": "c1", "compliance_type": "GSTR-3B", "period_start": "2026-04-01",
               "period_end": "2026-04-30", "due_date": "2026-05-20", **body}
    compliance_record_service.create_record(request, firm_id="f1")
    return sent[0]


def test_a_manual_create_supplies_every_not_null_column_that_has_no_default(monkeypatch):
    needed = _columns_the_insert_must_supply()
    assert {"client_id", "compliance_type", "due_date", "firm_id", "period_end", "period_label", "period_start"} <= needed
    # the request model's own shape: every optional field present with None, as `model_dump()` sends it
    payload = _captured_create(monkeypatch, financial_year=None, period_label=None, notes=None)
    missing = {c for c in needed if payload.get(c) in (None,)}
    assert not missing, f"the insert would be refused for NULL in: {sorted(missing)}"
    assert payload["period_label"] == ""


@pytest.mark.parametrize("due", [None, ""])
def test_a_manual_create_without_a_due_date_is_refused_in_words_not_by_the_database(monkeypatch, due):
    with pytest.raises(ValidationError) as e:
        _captured_create(monkeypatch, due_date=due)
    assert "due_date" in str(e.value)
