"""
The firm's own reading of the treaty, keyed by country and nature.

WHY THIS SHAPE
    Migration 309 put treaty_rate_bps on the VENDOR, which reads naturally and
    is wrong in a way that shows up on the second vendor. A DTAA rate is a fact
    about a country and an article: royalty to Switzerland is the same rate
    whichever Swiss company is paid, and the same agreement commonly gives
    royalty, FTS, interest and dividends four different rates. Five Swiss
    vendors meant entering one rate five times, no way to say that royalty and
    interest differ, and five rows to find when a protocol changed.

WHAT IS NOT HERE
    Any rates. The table ships empty and is never seeded — that is the whole
    position on treaties, unchanged.
"""
from __future__ import annotations

import pytest

from domain.tds.section_195 import (
    REFUSED_NO_PE_DECLARATION, REFUSED_TREATY_RATE_UNKNOWN, resolve_section_195,
)
from services.treaty_rate_service import treaty_position

TEN_LAKH = 10_00_000_00


class _DB:
    """Rows keyed the way the table is: (firm, country, nature)."""

    def __init__(self, rows=()):
        self._rows = list(rows)
        self._f: dict = {}

    def table(self, name):
        assert name == "dtaa_treaty_rates", name
        self._f = {}
        return self

    def select(self, *a):
        return self

    def eq(self, col, val):
        self._f[col] = val
        return self

    def limit(self, *a):
        return self

    def execute(self):
        out = [r for r in self._rows
               if all(r.get(k) == v for k, v in self._f.items())]
        return type("R", (), {"data": out})()


class _BoomDB(_DB):
    def execute(self):
        raise RuntimeError("dtaa_treaty_rates unreachable")


CH_ROYALTY = {"firm_id": "f1", "country_code": "CH", "nature": "royalty",
              "rate_bps": 1000, "no_article": False, "article_ref": "Article 12(2)"}
AE_FTS = {"firm_id": "f1", "country_code": "AE",
          "nature": "fees_for_technical_services",
          "rate_bps": None, "no_article": True, "article_ref": "no FTS article"}

NR = {"country_of_residence": "CH"}


# ── The lookup ───────────────────────────────────────────────────────────────

def test_the_firm_s_country_row_answers_for_every_vendor_in_that_country():
    """The point of the table: one reading, many vendors."""
    db = _DB([CH_ROYALTY])
    for name in ("Helvetica AG", "Zurich Systems", "Basel Labs"):
        pos = treaty_position(db, "f1", {**NR, "name": name}, "royalty")
        assert pos.found and pos.rate_bps == 1000 and pos.source == "firm_table"


def test_the_same_country_can_hold_a_different_rate_per_nature():
    """The same agreement commonly gives royalty and interest different rates,
    which a single number on the vendor could not express."""
    db = _DB([CH_ROYALTY,
              {**CH_ROYALTY, "nature": "interest", "rate_bps": 1500}])
    assert treaty_position(db, "f1", NR, "royalty").rate_bps == 1000
    assert treaty_position(db, "f1", NR, "interest").rate_bps == 1500


def test_another_country_s_row_does_not_answer():
    db = _DB([CH_ROYALTY])
    pos = treaty_position(db, "f1", {"country_of_residence": "SG"}, "royalty")
    assert not pos.found


def test_another_firm_s_reading_does_not_answer():
    """Firm-scoped on purpose: an MFN position one firm takes must not silently
    become another's."""
    db = _DB([CH_ROYALTY])
    assert not treaty_position(db, "OTHER", NR, "royalty").found


def test_a_vendor_override_beats_the_country_table():
    """For the rare payee whose position genuinely differs — an advance ruling,
    or a failed beneficial-ownership condition the country row assumes."""
    db = _DB([CH_ROYALTY])
    pos = treaty_position(db, "f1", {**NR, "treaty_rate_bps": 500}, "royalty")
    assert pos.rate_bps == 500 and pos.source == "vendor_override"


def test_an_override_of_zero_is_an_override_not_an_absence():
    db = _DB([CH_ROYALTY])
    pos = treaty_position(db, "f1", {**NR, "treaty_rate_bps": 0}, "royalty")
    assert pos.found and pos.rate_bps == 0 and pos.source == "vendor_override"


def test_nothing_recorded_is_not_found():
    assert not treaty_position(_DB([]), "f1", NR, "royalty").found


def test_a_vendor_with_no_country_cannot_be_looked_up():
    assert not treaty_position(_DB([CH_ROYALTY]), "f1", {}, "royalty").found


def test_a_failed_read_reports_not_found_rather_than_raising():
    """A treaty lookup that fails must not take a bill with it — and not-found
    makes the engine REFUSE, which is the safe direction, since the Act rate
    over-deducts exactly where a treaty has been established."""
    assert not treaty_position(_BoomDB([CH_ROYALTY]), "f1", NR, "royalty").found


def test_the_lookup_reads_one_row_not_a_country_s_worth():
    import inspect
    from services import treaty_rate_service as m
    assert ".limit(1)" in inspect.getsource(m.treaty_position)


# ── "No article" is an answer, not a missing rate ───────────────────────────

def test_a_treaty_with_no_article_for_this_nature_withholds_nil():
    """The UAE and Singapore have no fees-for-technical-services article, so
    what the Act would tax as FTS is Article 7 business profits and not taxable
    in India without a permanent establishment."""
    pos = treaty_position(_DB([AE_FTS]), "f1", {"country_of_residence": "AE"},
                          "fees_for_technical_services")
    assert pos.found and pos.no_article and pos.rate_bps is None

    r = resolve_section_195(
        amount_paise=TEN_LAKH, nature="fees_for_technical_services",
        is_company=True, trc_on_file=True, treaty_has_no_article=True,
        no_pe_declaration_on_file=True)
    assert r.applies and r.tds_paise == 0 and r.basis == "not_chargeable"


def test_no_article_still_needs_the_no_pe_declaration():
    """It is the SAME question chargeability asks, arriving by a different
    route, so it needs the same evidence rather than being waved through as a
    zero rate."""
    r = resolve_section_195(
        amount_paise=TEN_LAKH, nature="fees_for_technical_services",
        is_company=True, trc_on_file=True, treaty_has_no_article=True)
    assert not r.applies and r.refusal == REFUSED_NO_PE_DECLARATION


def test_no_article_is_not_the_same_as_no_row():
    """Having READ the agreement and found no article is an answer; nobody
    having read it is a refusal. Collapsing the two would withhold nil on a
    treaty nobody has opened."""
    read_it = resolve_section_195(
        amount_paise=TEN_LAKH, nature="royalty", trc_on_file=True,
        treaty_has_no_article=True, no_pe_declaration_on_file=True)
    never_read = resolve_section_195(
        amount_paise=TEN_LAKH, nature="royalty", trc_on_file=True,
        no_pe_declaration_on_file=True)
    assert read_it.applies and read_it.tds_paise == 0
    assert not never_read.applies and never_read.refusal == REFUSED_TREATY_RATE_UNKNOWN


def test_no_article_without_a_trc_does_not_reach_the_treaty_branch_at_all():
    """s.90(4): no TRC, no treaty relief. The Act rate applies and the
    no-article flag is irrelevant."""
    r = resolve_section_195(amount_paise=TEN_LAKH, nature="royalty",
                            is_company=True, treaty_has_no_article=True)
    assert r.applies and r.rate_bps == 2000 and r.basis == "act"


# ── The API a CA populates it through ───────────────────────────────────────

def _upsert(**over):
    from fastapi import HTTPException
    from routers.tds import TreatyRateIn, upsert_treaty_rate
    body = {"country_code": "CH", "nature": "royalty", "rate_bps": 1000}
    body.update(over)
    return upsert_treaty_rate(TreatyRateIn(**body), user={"firm_id": "f1", "id": "u1"})


@pytest.mark.parametrize("bad,fragment", [
    ({"country_code": "Switzerland"}, "ISO 3166-1"),
    ({"country_code": "CHE"}, "ISO 3166-1"),
    ({"nature": "consultancy"}, "nature must be one of"),
    ({"no_article": True}, "one thing or the other"),
    ({"rate_bps": None}, "no article"),
    ({"rate_bps": 99999}, "basis points"),
    ({"rate_bps": -1}, "basis points"),
])
def test_the_api_refuses_a_row_it_could_not_withhold_on(bad, fragment):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _upsert(**bad)
    assert e.value.status_code == 422
    assert fragment in e.value.detail


def test_no_article_with_no_rate_is_accepted():
    """The one shape where a missing rate is the answer rather than an
    omission. It reaches the database, so this only proves validation passed."""
    from fastapi import HTTPException
    try:
        _upsert(nature="fees_for_technical_services", rate_bps=None, no_article=True)
    except HTTPException as e:
        assert e.status_code != 422, f"validation rejected a valid no-article row: {e.detail}"


def test_the_write_endpoint_is_manager_tier_like_the_table_s_rls():
    """The app-layer check is the primary control and RLS is defence in depth
    (CLAUDE.md). If they disagreed, one of them would be decorative — and
    migration 310's RESTRICTIVE policies are Manager."""
    from core.permissions import PERMISSIONS
    assert "write" in PERMISSIONS["tds"]
    assert "Executive" not in PERMISSIONS["tds"]["write"]
    assert "Manager" in PERMISSIONS["tds"]["write"]
    assert "Partner" in PERMISSIONS["tds"]["write"]


def test_the_delete_is_firm_scoped():
    """dtaa_treaty_rates is addressed by id here, so without the firm filter one
    firm could remove another's reading by guessing a uuid."""
    import inspect
    from routers.tds import delete_treaty_rate
    src = inspect.getsource(delete_treaty_rate)
    assert '.eq("firm_id", user["firm_id"])' in src
