"""
`domain/demo/fixture` — the fictional practice, checked as if it were real.

WHY THESE ASSERTIONS AND NOT "IT BUILDS". A demo is where a CA copies an
example from, so a wrong identifier in it does more damage than one in a test:
this repository has already had to CORRECT three fixture GSTINs whose check
digits were invalid — `27AAAAA0000A1Z5` among them, used across 77 files
including two frontend placeholders that taught a CA an example their own
keystroke validator rejects. The fixture generates every identifier rather than
writing one down, and these pin that.

The second group is about the demo being WORTH anything: every client has to
make a different screen non-empty, and the year has to contain the cases the
engines branch on — an inter-state supply, a reverse-charge bill, an
unregistered party, an unclassified vendor, an employee either side of the ESI
ceiling. A fixture where everything is the ordinary case shows one thing eight
times.
"""
from __future__ import annotations

from datetime import date

import pytest

# ⚠️ TWO FUNCTIONS ARE CALLED `validate_pan` AND THEY RETURN OPPOSITE THINGS.
# `core.validators.validate_pan` answers None WHEN VALID and an error sentence
# when not — the `problem_with` convention this codebase uses everywhere else.
# `models.client.validate_pan` is a Pydantic field validator that RETURNS THE
# VALUE and raises. The first draft of this module asserted
# `validate_pan(x) == x` and failed on eight valid PANs. Same shape as the two
# `log_event`s CLAUDE.md warns about; `pan_problem` is named here so the
# convention is visible at the call site.
from core.validators import validate_pan as pan_problem
from domain.demo import fixture
from domain.gst import gstin as gstin_rule
from domain.gst.uqc import problem_with as uqc_problem
from domain.gst.hsn_digits import is_a_code

FIRM = fixture.build("2025-26")
ALL_PARTIES = [p for c in FIRM.clients for p in (*c.customers, *c.vendors)]


# ── It is the same practice twice ────────────────────────────────────────────

def test_the_fixture_is_deterministic():
    """One fixed seed. Two runs produce the same practice, which is what lets a
    test assert a figure and a demo be rehearsed — and what stops a
    walk-through showing different numbers than the rehearsal did."""
    again = fixture.build("2025-26")
    assert fixture.summary(FIRM) == fixture.summary(again)
    assert [c.name for c in FIRM.clients] == [c.name for c in again.clients]
    assert FIRM.clients[0].sales[0] == again.clients[0].sales[0]


def test_nothing_in_the_fixture_reads_the_clock():
    """A demo pinned to "now" is a different set of books every month, and a
    LOCKED PERIOD — half of what makes this product's accounting worth showing
    — cannot be demonstrated at all if every date is recent. The year is a
    parameter; asserted on the source so a later `ist_today()` fails here."""
    import pathlib
    src = pathlib.Path(fixture.__file__).read_text()
    for forbidden in ("ist_today", "datetime.now", "date.today", "time.time"):
        assert forbidden not in src, f"{forbidden} makes the demo move"


def test_a_different_year_moves_every_date_and_nothing_else():
    other = fixture.build("2024-25")
    assert fixture.summary(other)["sales_invoices"] == fixture.summary(FIRM)["sales_invoices"]
    assert other.clients[0].sales[0].doc_date.startswith("2024-")
    assert FIRM.clients[0].sales[0].doc_date.startswith("2025-")


# ── Every identifier is valid, because every one is generated ────────────────

def test_the_firms_own_gstin_is_valid():
    assert gstin_rule.problem_with(FIRM.gstin) is None
    assert gstin_rule.pan_of(FIRM.gstin) == FIRM.pan


@pytest.mark.parametrize("client", FIRM.clients, ids=lambda c: c.name)
def test_every_client_identifier_is_valid(client):
    assert pan_problem(client.pan) is None, client.pan
    if client.gstin is not None:
        assert gstin_rule.problem_with(client.gstin) is None, client.gstin
        assert gstin_rule.pan_of(client.gstin) == client.pan, (
            "a GSTIN carries its holder's PAN; a demo where they disagree "
            "teaches the opposite")


def test_every_party_gstin_is_valid():
    bad = [p.name for p in ALL_PARTIES
           if p.gstin and gstin_rule.problem_with(p.gstin)]
    assert bad == []


def test_every_employee_pan_is_valid():
    for c in FIRM.clients:
        for e in c.employees:
            assert pan_problem(e.pan) is None, e.pan


def test_the_checksum_is_computed_and_not_written_down():
    """The load-bearing one. `checksum_char` is called; a GSTIN literal in the
    module would be one somebody typed, which is exactly how the three bad
    fixtures got in."""
    import pathlib
    import re
    src = pathlib.Path(fixture.__file__).read_text()
    assert "checksum_char" in src
    literals = re.findall(r'"\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\w"', src)
    assert literals == [], f"a hand-written GSTIN: {literals}"


# ── Every amount is integer paise ────────────────────────────────────────────

def test_every_rate_is_integer_paise():
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            for ln in d.lines:
                assert isinstance(ln.rate_paise, int)
                assert ln.rate_paise > 0


def test_every_salary_component_is_integer_paise():
    for c in FIRM.clients:
        for e in c.employees:
            for amount in (e.basic_paise, e.hra_paise, e.special_paise):
                assert isinstance(amount, int) and amount > 0


def test_no_float_amount_appears_in_the_module():
    """A rupee figure written as a float is the one thing this schema does not
    allow, and a fixture is where it would look harmless."""
    import pathlib
    import re
    src = pathlib.Path(fixture.__file__).read_text()
    # A decimal literal next to a paise-ish name. Quantities are STRINGS
    # (NUMERIC(10,3)) and are not matched.
    assert not re.search(r"_paise[^)\n]*=\s*\d+\.\d", src)


# ── The documents are documents this product would accept ────────────────────

def test_every_date_falls_inside_the_financial_year():
    lo, hi = date(2025, 4, 1), date(2026, 3, 31)
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            assert lo <= date.fromisoformat(d.doc_date) <= hi, d.doc_date


def test_no_document_lands_on_a_date_that_does_not_exist():
    """Days 0-27 only, so February needs no special case — asserted rather than
    trusted, because a fixture that raises on 29 February in a leap year would
    do it once every four years."""
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            assert int(d.doc_date[8:10]) <= 28


def test_every_hsn_code_is_a_code_and_six_digits():
    """Notification 78/2020 wants six digits above ₹5 crore and four on B2B
    below it, so six satisfies both and the demo never shows a shortfall it did
    not mean to. `is_a_code` is the module's own rule, not `str.isdigit` —
    Python calls a fullwidth digit a digit and the IRP does not."""
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            for ln in d.lines:
                assert is_a_code(ln.hsn_sac_code), ln.hsn_sac_code
                assert len(ln.hsn_sac_code) == 6, ln.hsn_sac_code


def test_every_unit_is_a_real_uqc():
    """Table 12 files the unit as recorded, so a fixture unit that is not a CBIC
    code would demonstrate a gap the demo did not intend."""
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            for ln in d.lines:
                assert uqc_problem(ln.unit) is None, ln.unit


def test_every_quantity_fits_the_column():
    """Three decimals — every quantity column here is NUMERIC(10,3) and
    `domain/quantity` refuses a fourth at six doors."""
    from domain.quantity import quantity_violation
    for c in FIRM.clients:
        for d in (*c.sales, *c.purchases):
            for ln in d.lines:
                assert quantity_violation(ln.quantity) is None, ln.quantity


def test_documents_are_in_date_order():
    """The invoice numbers the seeder assigns are sequential, and Rule 46(b)
    wants a CONSECUTIVE series — a fixture out of date order would produce a
    series that runs backwards through the year."""
    for c in FIRM.clients:
        for docs in (c.sales, c.purchases):
            dates = [d.doc_date for d in docs]
            assert dates == sorted(dates)


def test_the_invoice_number_the_seeder_builds_satisfies_rule_46b():
    """Sixteen characters is the Act's limit and `INV/2025-26/0001` is exactly
    sixteen — asserted here rather than discovered when the seeder's 
    four-hundredth POST is refused."""
    from domain.gst.invoice_series import format_violation
    for n in (1, 315, 9999):
        number = f"INV/{FIRM.financial_year}/{n:04d}"
        assert len(number) <= 16
        assert format_violation(number) is None, number


# ── The demo is worth running ────────────────────────────────────────────────

def test_every_client_says_what_it_is_for():
    """A demo whose clients are interchangeable shows one thing eight times."""
    reasons = [c.demonstrates for c in FIRM.clients]
    assert len(set(reasons)) == len(reasons), "two clients demonstrate the same thing"
    assert all(len(r) >= 40 for r in reasons)


def test_the_year_contains_the_cases_the_engines_branch_on():
    s = fixture.summary(FIRM)
    assert s["inter_state_sales"] > 0, "IGST and Table 3.2 would be structurally nil"
    assert s["reverse_charge_bills"] > 0, "§9(3), Table 3.1(d) and the self-invoice"
    assert s["unregistered_parties"] > 0, "B2C, and §31(3)(f)'s own limb"
    assert s["employees"] > 0, "payroll, §192 and the Bonus Act register"


def test_some_vendors_are_deliberately_unclassified():
    """`rcm_documents` reads a NULL `msme_status` as *unrecorded* and NAMES it
    rather than assuming Others — §43B(h) changes taxable income on that
    distinction. A fixture where every vendor is classified cannot show it."""
    vendors = [p for c in FIRM.clients for p in c.vendors]
    assert any(p.msme_status is None for p in vendors)
    assert any(p.msme_status == "micro" for p in vendors)


def test_the_employees_straddle_the_statutory_ceilings():
    """ESI stops at ₹21,000 of gross and Bonus Act §2(13) at ₹21,000 of salary,
    so both engines need somebody they reach and somebody they do not."""
    employees = [e for c in FIRM.clients for e in c.employees]
    gross = [e.basic_paise + e.hra_paise + e.special_paise for e in employees]
    assert any(g <= 21_000_00 for g in gross), "nobody is inside the ESI ceiling"
    assert any(g > 21_000_00 for g in gross), "nobody is outside it"


def test_the_practice_is_large_enough_to_judge():
    """The live book is 7 clients and 2 bank accounts with most tables empty,
    which is why every screen renders its empty state. A demo has to be past
    the point where a report is a single row."""
    s = fixture.summary(FIRM)
    assert s["clients"] >= 6
    assert s["sales_invoices"] >= 200
    assert s["purchase_bills"] >= 100


# ── The fixture is a fixture ─────────────────────────────────────────────────

def test_it_holds_no_database_handle_and_makes_no_call():
    """`scripts/seed_demo_firm.py` writes; this describes. Asserted on the
    source, because the tempting shortcut when adding a client is to look one
    up."""
    import pathlib
    src = pathlib.Path(fixture.__file__).read_text()
    for forbidden in ("supabase", "get_supabase", "requests", "urllib",
                      "httpx", ".execute()", ".table("):
        assert forbidden not in src, f"the fixture must not {forbidden}"


def test_the_two_validate_pan_functions_still_disagree():
    """A premise, pinned. `core.validators.validate_pan` answers None WHEN
    VALID; `models.client.validate_pan` returns the value and raises. If one of
    them is ever made to match the other, the assertions above silently invert
    and pass over everything — so the disagreement is asserted rather than
    assumed, the way the two `log_event`s are."""
    from models.client import validate_pan as model_validator

    good = FIRM.clients[0].pan
    assert pan_problem(good) is None
    assert model_validator(good) == good

    with pytest.raises(Exception):
        model_validator("NOTAPAN")
    assert isinstance(pan_problem("NOTAPAN"), str)
