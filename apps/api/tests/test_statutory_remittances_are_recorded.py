"""The ESI / professional-tax remittance record, above the database.

Migration 365 states every rule as a CHECK constraint, and
test_365_statutory_remittances_pg.py proves the SQL enforces them. This file is
about the layer above: that a CA gets a SENTENCE rather than a constraint name,
and that the two rules the service adds on top — the contribution period and
the update-in-place — behave.
"""
from __future__ import annotations

import pytest

from domain.payroll.statutory import esi_contribution_period
from services import statutory_remittance_service as svc

FIRM, CLIENT = "f1", "c1"


class _Table:
    """The smallest PostgREST stand-in these calls need."""

    def __init__(self, store: list[dict]):
        self.store, self._filters, self._payload, self._op = store, [], None, None

    def select(self, _cols):
        self._op = "select"
        return self

    def insert(self, row):
        self._op, self._payload = "insert", row
        return self

    def update(self, row):
        self._op, self._payload = "update", row
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def is_(self, col, _null):
        self._filters.append((col, None))
        return self

    def _matches(self, row) -> bool:
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"r{len(self.store) + 1}")
            row.setdefault("deleted_at", None)
            self.store.append(row)
            return type("R", (), {"data": [row]})
        if self._op == "update":
            hit = [r for r in self.store if self._matches(r)]
            for r in hit:
                r.update(self._payload)
            return type("R", (), {"data": hit})
        return type("R", (), {"data": [r for r in self.store if self._matches(r)]})


class _DB:
    def __init__(self):
        self.rows: list[dict] = []

    def table(self, name):
        assert name == "statutory_remittances", name
        return _Table(self.rows)


@pytest.fixture()
def db():
    return _DB()


def _record(db, **over):
    args = dict(firm_id=FIRM, client_id=CLIENT, scheme=svc.ESIC,
                wage_month="2026-09", submitted_on="2026-10-14")
    args.update(over)
    return svc.record(db, **args)


# ── the contribution period is derived, and derived from ONE place ───────────

@pytest.mark.parametrize("month", [f"{y}-{m:02d}" for y in (2025, 2026, 2027)
                                   for m in range(1, 13)])
def test_the_contribution_period_matches_the_domain_rule(month):
    """DELEGATION, asserted. The rule lives in domain/payroll/statutory and ESI
    Rule 50's ceiling continuation depends on it; a second copy here would be a
    second thing to get wrong about October-to-March spanning a year boundary."""
    assert svc.contribution_period_for(month) == esi_contribution_period(month)


def test_january_belongs_to_the_period_that_began_last_october():
    """The case a naive implementation gets wrong: H2 spans the year end, so a
    January wage month is filed under the PREVIOUS year's H2."""
    assert svc.contribution_period_for("2027-01") == "2026-H2"


def test_an_esi_remittance_carries_the_period_without_being_told(db):
    row = _record(db, wage_month="2027-01")
    assert row["contribution_period"] == "2026-H2"


def test_a_pt_remittance_carries_no_period(db):
    row = _record(db, scheme=svc.PROFESSIONAL_TAX, state="Maharashtra")
    assert "contribution_period" not in row


@pytest.mark.parametrize("bad", ["2026-13", "26-09", "September", ""])
def test_a_malformed_month_is_refused_with_a_sentence(bad):
    with pytest.raises(svc.RemittanceError) as e:
        svc.contribution_period_for(bad)
    assert "YYYY-MM" in str(e.value)


# ── the refusals a CA should be able to read ─────────────────────────────────

def test_pt_without_a_state_says_why(db):
    with pytest.raises(svc.RemittanceError) as e:
        _record(db, scheme=svc.PROFESSIONAL_TAX)
    assert "STATE" in str(e.value)


def test_esi_with_a_state_says_why(db):
    with pytest.raises(svc.RemittanceError) as e:
        _record(db, state="Maharashtra")
    assert "central levy" in str(e.value)


def test_epf_is_refused_and_points_at_its_own_record(db):
    with pytest.raises(svc.RemittanceError) as e:
        _record(db, scheme="epf")
    assert "335" in str(e.value)


def test_paid_before_filed_is_refused(db):
    with pytest.raises(svc.RemittanceError):
        _record(db, status=svc.PAID, submitted_on="2026-10-14", paid_on="2026-10-01")


def test_a_negative_amount_is_refused(db):
    with pytest.raises(svc.RemittanceError) as e:
        _record(db, amount_paise=-1)
    assert "left the bank" in str(e.value)


# ── filing then paying is ONE remittance, not two ────────────────────────────

def test_recording_the_payment_updates_the_filing_in_place(db):
    first = _record(db)
    second = _record(db, status=svc.PAID, paid_on="2026-10-20",
                     challan_number="CH-1", amount_paise=45_00_00)
    assert second["id"] == first["id"], (
        "filing the return and paying the challan are two entries about ONE "
        "remittance; a second row would hit the unique index")
    assert len(db.rows) == 1
    assert db.rows[0]["status"] == svc.PAID
    assert db.rows[0]["challan_number"] == "CH-1"


def test_two_states_in_one_month_are_two_remittances(db):
    a = _record(db, scheme=svc.PROFESSIONAL_TAX, state="Maharashtra")
    b = _record(db, scheme=svc.PROFESSIONAL_TAX, state="Karnataka")
    assert a["id"] != b["id"], (
        "two authorities, two due dates, two challans — not a duplicate")
    assert len(db.rows) == 2


def test_esi_and_pt_for_one_month_do_not_collide(db):
    _record(db)
    _record(db, scheme=svc.PROFESSIONAL_TAX, state="Maharashtra")
    assert len(db.rows) == 2


def test_paid_without_a_date_defaults_to_the_filing_date(db):
    """ESIC generates the challan straight after the contribution is submitted,
    so one sitting is the common case — and the CHECK would otherwise refuse the
    row with nothing useful to say."""
    row = _record(db, status=svc.PAID, submitted_on="2026-10-14")
    assert row["paid_on"] == "2026-10-14"


# ── the link, and the question it answers ────────────────────────────────────

def test_a_paid_remittance_with_no_entry_is_reported_as_unlinked(db):
    _record(db, status=svc.PAID, paid_on="2026-10-20")
    assert [r["wage_month"] for r in
            svc.unlinked(db, firm_id=FIRM, client_id=CLIENT)] == ["2026-09"]


def test_linking_the_payment_clears_it_from_that_list(db):
    row = _record(db, status=svc.PAID, paid_on="2026-10-20")
    assert svc.link_payment(db, firm_id=FIRM, remittance_id=row["id"],
                            journal_entry_id="je-1")
    assert svc.unlinked(db, firm_id=FIRM, client_id=CLIENT) == []


def test_a_remittance_only_filed_is_not_reported_as_unlinked(db):
    """Unlinked means PAID with no entry. A return that is merely filed has no
    payment to match yet, and reporting it would bury the real ones."""
    _record(db)
    assert svc.unlinked(db, firm_id=FIRM, client_id=CLIENT) == []


def test_retracting_is_a_soft_delete(db):
    row = _record(db)
    assert svc.retract(db, firm_id=FIRM, remittance_id=row["id"])
    assert db.rows, "the row must survive — the challan number is held nowhere else"
    assert db.rows[0]["deleted_at"]
