"""
A non-resident vendor changes the charging SECTION, not just the return form.

The easy version of this feature writes '27Q' instead of '26Q' and stops. These
tests exist to hold the line that that is wrong: s.194C and its neighbours
charge, in their own words, sums paid "to a resident", so for a non-resident
payee they do not apply at all and s.195 does — at rates this codebase does not
compute and deliberately refuses to invent.

Mock-mode: pure functions plus the register service driven through a fake
Supabase client, so none of it needs a database.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.tds.residency import (
    FORM_26Q, FORM_27Q, GAP_27Q_IDENTIFIERS_MISSING,
    GAP_RESIDENCY_NOT_CLASSIFIED, NON_RESIDENT, RESIDENT,
    RESIDENT_ONLY_SECTIONS, SECTIONS_REACHING_NON_RESIDENTS,
    is_classified, is_non_resident, missing_27q_identifiers,
    return_type_for, section_refusal,
)


# ── The statute, transcribed ─────────────────────────────────────────────────

def test_every_section_the_registry_computes_is_classified_one_way_or_the_other():
    """A section nobody has read is the hole this whole module exists to close.

    If a new section lands in the rate registry and is in neither list, it
    silently inherits "no refusal" — i.e. it gets applied to a non-resident.
    That is the failure mode, so it fails here instead.
    """
    from domain.tds.section_rates import tds_rates_for
    computed = set(tds_rates_for("2025-26").sections)
    # 192 is salary (24Q, never a purchase bill) and 206C is TCS, which nothing
    # in this codebase computes — see section_rates.py's own comment.
    computed -= {"192", "206C"}
    unclassified = sorted(
        computed - set(RESIDENT_ONLY_SECTIONS) - set(SECTIONS_REACHING_NON_RESIDENTS))
    assert not unclassified, (
        f"these TDS sections are in the rate registry but nobody has recorded "
        f"whether they reach a non-resident payee: {unclassified}. Read the "
        f"section's charging words and add it to one list or the other — "
        f"defaulting is how a foreign remittance gets deducted under 194C.")


def test_the_resident_only_list_quotes_the_section_it_relies_on():
    """Each entry must carry its own citation, or the claim is unauditable."""
    for code, citation in RESIDENT_ONLY_SECTIONS.items():
        assert citation.startswith(f"s.{code}"), f"{code} does not cite itself"
        assert "resident" in citation.lower(), (
            f"{code}'s citation does not show the resident limitation it is "
            f"listed for: {citation!r}")


def test_194b_is_not_treated_as_resident_only():
    """s.194B charges 'to any person' — the one registry section that reaches a
    non-resident. Lumping it in with 194C would refuse a lawful deduction."""
    assert "194B" not in RESIDENT_ONLY_SECTIONS
    assert section_refusal("194B", NON_RESIDENT) is None


# ── Classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "  ", "unknown", "Resident", "resident"])
def test_only_an_explicit_non_resident_is_a_non_resident(value):
    assert is_non_resident(value) is False


@pytest.mark.parametrize("value", ["non_resident", "NON_RESIDENT", " Non_Resident "])
def test_the_flag_is_read_case_and_whitespace_insensitively(value):
    assert is_non_resident(value) is True


def test_unclassified_is_a_third_state_and_not_a_synonym_for_resident():
    """NULL behaves as resident for COMPUTATION and is still not the same fact
    — which is the whole reason the gap gets reported."""
    assert is_non_resident(None) is False          # computes as resident
    assert is_classified(None) is False            # but nobody has said so
    assert is_classified(RESIDENT) is True
    assert is_classified(NON_RESIDENT) is True


def test_the_return_form_follows_rule_31a4():
    assert return_type_for(NON_RESIDENT) == FORM_27Q
    assert return_type_for(RESIDENT) == FORM_26Q
    assert return_type_for(None) == FORM_26Q


# ── Refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section", sorted(RESIDENT_ONLY_SECTIONS))
def test_a_resident_only_section_is_refused_for_a_non_resident(section):
    refusal = section_refusal(section, NON_RESIDENT)
    assert refusal, f"{section} was allowed against a non-resident payee"
    assert "195" in refusal, "the refusal must name the section that DOES apply"


@pytest.mark.parametrize("section", sorted(RESIDENT_ONLY_SECTIONS))
def test_the_same_section_is_allowed_for_a_resident_and_for_the_unclassified(section):
    assert section_refusal(section, RESIDENT) is None
    assert section_refusal(section, None) is None


def test_section_195_is_no_longer_refused_here():
    """It was, while nothing could rate it. domain/tds/section_195.py now does,
    and raises its OWN refusals — no nature recorded, no no-PE declaration
    behind a nil, a TRC with no treaty rate — which are about the payment
    rather than the section. Refusing here as well would stop a CA setting a
    vendor up correctly."""
    for status in (NON_RESIDENT, RESIDENT, None):
        assert section_refusal("195", status) is None


def test_the_resident_only_refusal_still_points_at_195():
    """The one refusal left. It has to name the section that DOES apply, or a
    CA is told what not to do and not what to do."""
    refusal = section_refusal("194J", NON_RESIDENT)
    assert refusal and "195" in refusal


def test_no_section_at_all_is_not_a_refusal():
    """An empty section is a different error, raised by the caller with its own
    message; swallowing it here would replace a clear message with a vague one."""
    assert section_refusal(None, NON_RESIDENT) is None
    assert section_refusal("", NON_RESIDENT) is None


def test_a_section_this_module_has_not_read_is_not_refused():
    """Deliberate. Refusing a section nobody has classified would be guessing in
    the other direction; test_every_section_the_registry_computes... is what
    stops one going unclassified."""
    assert section_refusal("194ZZZ", NON_RESIDENT) is None


# ── 27Q identifiers ──────────────────────────────────────────────────────────

def test_a_vendor_with_a_pan_still_needs_its_country():
    assert missing_27q_identifiers({"pan": "AAAAA1111A"}) == ["country_of_residence"]


def test_the_tin_is_only_demanded_when_there_is_no_pan():
    """Rule 37BC's relief from the s.206AA floor is the no-PAN case."""
    with_pan = {"pan": "AAAAA1111A", "country_of_residence": "AE"}
    assert missing_27q_identifiers(with_pan) == []
    without_pan = {"country_of_residence": "AE"}
    assert missing_27q_identifiers(without_pan) == ["tax_identification_number"]


def test_a_fully_identified_non_resident_is_missing_nothing():
    assert missing_27q_identifiers({
        "country_of_residence": "SG", "tax_identification_number": "T12345"}) == []


def test_whitespace_is_not_an_identifier():
    assert set(missing_27q_identifiers({"country_of_residence": "   ", "pan": "  "})) == {
        "country_of_residence", "tax_identification_number"}


# ── What the API accepts on a vendor ─────────────────────────────────────────

def _vendor(**over):
    from models.parties import VendorIn
    return VendorIn(client_id="c1", name="Helvetica Design AG", **over)


def test_the_status_and_country_are_canonicalised_on_the_way_in():
    """Stored has to match validated — the same rule GSTIN and PAN follow here,
    and the DB CHECK is ^[A-Z]{2}$."""
    v = _vendor(residential_status=" Non_Resident ", country_of_residence=" ch ")
    assert v.residential_status == "non_resident"
    assert v.country_of_residence == "CH"


def test_a_misspelt_status_is_refused_rather_than_stored_as_unclassified():
    """'nonresident' silently becoming NULL would file a foreign remittance in
    26Q while the CA believed they had classified the vendor."""
    with pytest.raises(ValueError, match="resident' or 'non_resident'"):
        _vendor(residential_status="nonresident")


def test_a_country_name_is_refused_where_a_code_is_required():
    """27Q takes the ISO code. Free text here is an FVU rejection discovered at
    filing, months after the deduction."""
    with pytest.raises(ValueError, match="ISO 3166-1"):
        _vendor(country_of_residence="United Arab Emirates")


def test_marking_a_vendor_non_resident_requires_its_country():
    with pytest.raises(ValueError, match="country_of_residence"):
        _vendor(residential_status="non_resident")


def test_a_resident_vendor_needs_no_country():
    assert _vendor(residential_status="resident").country_of_residence is None


def test_leaving_residency_unset_is_still_allowed():
    """Every vendor that existed before migration 308 is in this state; a
    required field here would have made the whole master unsaveable."""
    v = _vendor()
    assert v.residential_status is None


def test_a_tin_of_only_whitespace_is_not_a_tin():
    v = _vendor(residential_status="non_resident", country_of_residence="CH",
                tax_identification_number="   ")
    assert v.tax_identification_number is None


def test_the_update_model_validates_identically_to_the_create_model():
    """Two doors onto the same three columns. A value the create path refuses
    and the update path accepts is a value that gets in anyway."""
    from models.parties import VendorUpdateIn
    with pytest.raises(ValueError, match="resident' or 'non_resident'"):
        VendorUpdateIn(residential_status="nonresident")
    with pytest.raises(ValueError, match="ISO 3166-1"):
        VendorUpdateIn(country_of_residence="Switzerland")
    with pytest.raises(ValueError, match="country_of_residence"):
        VendorUpdateIn(residential_status="non_resident")


def test_an_unrelated_update_does_not_demand_a_country():
    """VendorUpdateIn is a partial payload — renaming a vendor must not trip a
    cross-field rule about fields the caller never sent."""
    from models.parties import VendorUpdateIn
    assert VendorUpdateIn(name="New Name").residential_status is None


# ── What the API accepts for a §195 withholding ──────────────────────────────

def test_the_nature_of_income_is_canonicalised_and_checked():
    v = _vendor(residential_status="non_resident", country_of_residence="CH",
                section_195_nature_of_income=" Royalty ")
    assert v.section_195_nature_of_income == "royalty"


def test_a_nature_the_rate_table_cannot_price_is_refused():
    """The DB CHECK is generated from the same list, so a value that got past
    here would be rejected by Postgres with no explanation a CA could act on."""
    with pytest.raises(ValueError, match="section_195_nature_of_income must be one of"):
        _vendor(section_195_nature_of_income="consultancy")


def test_a_nil_nature_needs_its_no_pe_declaration_at_the_point_it_is_chosen():
    """Not only when a bill is booked. s.195 reaches a sum 'chargeable under
    the Act', and business profits without a permanent establishment are not —
    so nil is an assertion about the payee's Indian presence, and this is where
    somebody makes it."""
    with pytest.raises(ValueError, match="no permanent establishment"):
        _vendor(residential_status="non_resident", country_of_residence="CH",
                section_195_nature_of_income="business_profits_no_pe")
    ok = _vendor(residential_status="non_resident", country_of_residence="CH",
                 section_195_nature_of_income="business_profits_no_pe",
                 no_pe_declaration_on_file=True)
    assert ok.no_pe_declaration_on_file is True


@pytest.mark.parametrize("bps", [-1, 10001])
def test_a_treaty_rate_outside_zero_to_one_hundred_percent_is_refused(bps):
    with pytest.raises(ValueError, match="basis points"):
        _vendor(treaty_rate_bps=bps)


@pytest.mark.parametrize("bps", [0, 1000, 10000])
def test_a_treaty_rate_inside_the_range_is_accepted(bps):
    """Zero is a real treaty rate — several agreements tax nothing without a
    permanent establishment — so it must not be read as 'unset'."""
    assert _vendor(treaty_rate_bps=bps).treaty_rate_bps == bps


def test_a_non_resident_may_not_also_carry_a_resident_only_tds_section():
    """The two facts contradict each other: s.194C charges sums paid 'to a
    resident'. Caught on the VENDOR now rather than when a bill is booked,
    because the bill routes by residency and would silently ignore the stale
    section rather than telling anyone the record is wrong."""
    with pytest.raises(ValueError, match="section 194C applies only to a resident"):
        _vendor(residential_status="non_resident", country_of_residence="CH",
                tds_applicable=True, tds_section="194C")


def test_a_non_resident_carrying_section_195_is_fine():
    v = _vendor(residential_status="non_resident", country_of_residence="CH",
                tds_applicable=True, tds_section="195",
                section_195_nature_of_income="royalty")
    assert v.tds_section == "195"


def test_a_resident_vendor_keeps_its_ordinary_section():
    """The negative control for the rule above: nothing changed for the
    domestic vendor this platform is built for."""
    v = _vendor(residential_status="resident", tds_applicable=True, tds_section="194C")
    assert v.tds_section == "194C"


def test_the_update_model_validates_the_195_fields_identically():
    from models.parties import VendorUpdateIn
    with pytest.raises(ValueError, match="section_195_nature_of_income must be one of"):
        VendorUpdateIn(section_195_nature_of_income="consultancy")
    with pytest.raises(ValueError, match="basis points"):
        VendorUpdateIn(treaty_rate_bps=99999)
    with pytest.raises(ValueError, match="no permanent establishment"):
        VendorUpdateIn(residential_status="non_resident", country_of_residence="CH",
                       section_195_nature_of_income="business_profits_no_pe")
