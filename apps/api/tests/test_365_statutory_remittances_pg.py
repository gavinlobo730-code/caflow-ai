"""Migration 365 — ESIC and professional tax remittances, at the database.

WHAT THIS TABLE IS FOR

Of the monthly statutory remittances this product prepares, EPF got a record in
migration 335. ESI and professional tax had none: the CA uploaded the file, paid
the challan, and the product forgot it happened — no number, no amount, no date,
and no way to answer "is October's ESI paid" except by logging in to the portal.
An obligation that cannot be closed is one that gets paid twice or not at all.

WHY THESE ASSERTIONS ARE AT THE DATABASE AND NOT IN A SERVICE

The frontend reaches ~83 tables directly over PostgREST, where no `rbac()` runs
and the only check is RLS. A rule enforced in Python is a rule the second write
path does not have. Every constraint below is therefore stated in SQL, and this
file is what proves the SQL says what the migration's comments claim.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG", "")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql",
)

FIRM = "f0000000-0000-0000-0000-000000000365"
CLIENT = "c0000000-0000-0000-0000-000000000365"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m365_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "365_esic_and_professional_tax_remittances_are_recorded.sql" not in \
            pg_template.failed, (
            "migration 365 did not apply — everything below would pass vacuously")
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F365', 'f365@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C365', 'Private Limited');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:60]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(**cols) -> str:
    cols.setdefault("submitted_on", "2026-10-15")
    keys = ", ".join(cols)
    vals = ", ".join("NULL" if v is None else f"'{v}'" for v in cols.values())
    return (f"INSERT INTO statutory_remittances (firm_id, client_id, {keys}) "
            f"VALUES ('{FIRM}', '{CLIENT}', {vals});")


def _accepted(dsn: str, sql: str) -> bool:
    return _psql(dsn, sql).returncode == 0


def _refused(dsn: str, sql: str, constraint: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode != 0, f"accepted, and should not have been: {sql[:90]}"
    assert constraint in r.stderr, (
        f"refused by the wrong rule — wanted {constraint}, got:\n{r.stderr.strip()[:300]}")


# ── the scheme decides which columns are allowed ─────────────────────────────

def test_an_esi_remittance_carries_a_contribution_period_and_no_state(db):
    assert _accepted(db, _insert(scheme="esic", wage_month="2026-09",
                                 contribution_period="2026-H1"))


def test_a_pt_remittance_carries_a_state(db):
    assert _accepted(db, _insert(scheme="professional_tax", wage_month="2026-09",
                                 state="Maharashtra"))


def test_esi_with_a_state_is_refused(db):
    """ESI is a central levy. A state on it is a row somebody filled in from the
    PT screen, and it would slip past the uniqueness rule below."""
    _refused(db, _insert(scheme="esic", wage_month="2026-09", state="Maharashtra"),
             "statutory_remittance_state_belongs_to_pt")


def test_pt_without_a_state_is_refused(db):
    """PT is levied per STATE. Without one the row cannot say which authority was
    paid, and two of them for one month would be indistinguishable."""
    _refused(db, _insert(scheme="professional_tax", wage_month="2026-09"),
             "statutory_remittance_state_belongs_to_pt")


def test_pt_with_a_contribution_period_is_refused(db):
    """The contribution period is ESI's half-year. PT has none."""
    _refused(db, _insert(scheme="professional_tax", wage_month="2026-09",
                         state="Maharashtra", contribution_period="2026-H1"),
             "statutory_remittance_contribution_period_belongs_to_esi")


# ── one live remittance per client, scheme, month and state ──────────────────

def test_a_second_live_esi_row_for_the_same_month_is_refused(db):
    """THE DOUBLE PAYMENT THIS TABLE EXISTS TO PREVENT."""
    assert _accepted(db, _insert(scheme="esic", wage_month="2026-09",
                                 contribution_period="2026-H1"))
    _refused(db, _insert(scheme="esic", wage_month="2026-09",
                         contribution_period="2026-H1", challan_number="X"),
             "uq_statutory_remittance_live")


def test_one_client_may_file_pt_in_two_states_for_one_month(db):
    """Staff in Maharashtra and Karnataka is two authorities, two due dates and
    two challans for a single wage month — and must not be mistaken for a
    duplicate."""
    assert _accepted(db, _insert(scheme="professional_tax", wage_month="2026-09",
                                 state="Maharashtra"))
    assert _accepted(db, _insert(scheme="professional_tax", wage_month="2026-09",
                                 state="Karnataka"))


def test_two_pt_rows_for_the_SAME_state_and_month_are_refused(db):
    assert _accepted(db, _insert(scheme="professional_tax", wage_month="2026-09",
                                 state="Maharashtra"))
    _refused(db, _insert(scheme="professional_tax", wage_month="2026-09",
                         state="Maharashtra"),
             "uq_statutory_remittance_live")


def test_a_retracted_row_does_not_block_its_replacement(db):
    """The CA types this off the portal and can type it wrong. A correction must
    be possible, which is why the unique index is partial on deleted_at."""
    assert _accepted(db, _insert(scheme="esic", wage_month="2026-09",
                                 contribution_period="2026-H1"))
    assert _accepted(db, "UPDATE statutory_remittances SET deleted_at = now() "
                         "WHERE scheme = 'esic' AND wage_month = '2026-09';")
    assert _accepted(db, _insert(scheme="esic", wage_month="2026-09",
                                 contribution_period="2026-H1",
                                 challan_number="COR-1"))


# ── the state machine ────────────────────────────────────────────────────────

def test_paid_without_a_date_is_refused(db):
    """A row could otherwise claim the settled state with no evidence of when."""
    _refused(db, _insert(scheme="esic", wage_month="2026-09",
                         contribution_period="2026-H1", status="paid"),
             "statutory_remittance_paid_needs_a_date")


def test_paid_before_submitted_is_refused(db):
    _refused(db, _insert(scheme="esic", wage_month="2026-09",
                         contribution_period="2026-H1", status="paid",
                         paid_on="2026-10-01", submitted_on="2026-10-15"),
             "statutory_remittance_paid_not_before_submitted")


def test_submitted_and_paid_on_the_same_day_is_allowed(db):
    """ESIC generates the challan right after the contribution is submitted, so
    the common case is one sitting."""
    assert _accepted(db, _insert(scheme="esic", wage_month="2026-09",
                                 contribution_period="2026-H1", status="paid",
                                 submitted_on="2026-10-15", paid_on="2026-10-15"))


# ── the shapes that sort or total wrongly if they are let in ─────────────────

@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "26-09", "2026-9", "September"])
def test_a_malformed_wage_month_is_refused(db, bad):
    """Anything that sorts these as text sorts a malformed one into the wrong
    place silently — which is how a month gets skipped."""
    _refused(db, _insert(scheme="esic", wage_month=bad, contribution_period="2026-H1"),
             "wage_month")


@pytest.mark.parametrize("bad", ["2026-H3", "2026H1", "H1"])
def test_a_malformed_contribution_period_is_refused(db, bad):
    _refused(db, _insert(scheme="esic", wage_month="2026-09", contribution_period=bad),
             "contribution_period")


def test_a_negative_amount_is_refused(db):
    """A remittance is money that left the bank. There is no negative one."""
    _refused(db, _insert(scheme="esic", wage_month="2026-09",
                         contribution_period="2026-H1", amount_paise="-1"),
             "amount_paise")


def test_an_unknown_scheme_is_refused(db):
    """EPF has its own table (335) with its own return-type sequence; putting it
    here would give it two records that disagree.

    No constraint NAME is asserted, deliberately. Two rules reject this — the
    scheme CHECK and the state rule, whose branches both name a known scheme —
    and which one Postgres reports first is its business, not a contract. The
    guarantee is that the row does not get in.
    """
    r = _psql(db, _insert(scheme="epf", wage_month="2026-09"))
    assert r.returncode != 0, "an unknown scheme was accepted"
    assert "violates check constraint" in r.stderr
