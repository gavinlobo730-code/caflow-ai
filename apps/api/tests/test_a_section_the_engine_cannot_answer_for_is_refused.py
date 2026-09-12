"""
A TDS section may be recorded against a vendor only if the engine can answer
for it on the bill path.

WHY THIS EXISTS
    The vendor master accepted any string. `VendorIn.tds_section` is a bare
    `Optional[str]`, and the only section check that ran was
    `section_refusal`, which asks whether the section fits a NON-RESIDENT
    payee. So s.194IA, s.194R, s.194T and s.194M all saved fine over the API,
    the bulk import, and any row predating the screen that stopped offering
    them — and then every bill for that vendor died on
    `ValueError: Unknown TDS section '194IA'`, an internal string reaching a CA
    weeks later with no statute, no alternative and no hint that the VENDOR
    RECORD is what is wrong.

    And s.192 did not even die. domain/tds/section_rates.py holds it as an
    explicit sentinel — `TDSSectionRule(0, 0, 0)`, present so a lookup
    succeeds, because salary is slab-based and lives in
    domain/income_tax/statutory_rates.py. So resolve_tds answered
    `applies=True, rate_bps=0, tds_paise=0`: the bill saved, the stored rate
    was 0, the explanation read "s.192 at 0%", and
    services/tds_register_service.py wrote NO register row and NO gap, because
    nothing had been deducted. A vendor bill is never salary, and s.192 was in
    the dropdown.

    That is the shape worth naming: a LOUD refusal was replaced, and a SILENT
    nil was left standing in the same list.

WHY IT REFUSES RATHER THAN ADDING THE MISSING SECTIONS
    Adding a `"194IA"` row to the registry would convert a visible 422 into an
    invisible wrong statutory return. `domain/tds/residency.return_type_for`
    picks the quarterly statement by RESIDENCY alone, and
    `tds_deductions.return_type` CHECKs ('24Q','26Q','27Q','27EQ') (migration
    014), so a computed property deduction would be stamped 26Q — reported on
    a statement it does not belong on, by a deductor who is not filing 26Q at
    all. The same call was already made one module over, on the same section:
    routers/tds_workspace.py refuses to name a form for 16B/16C because "a
    wrong form number is worse than an unchanged one".

THE RULE, NOT A LIST
    Every test below walks the registry rather than naming sections, so a
    section added later is covered without anyone remembering to add it here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from domain.tds.residency import (SECTION_192_SALARY, deduction_section_refusal,
                                  return_type_for)
from domain.tds.section_rates import tds_rates_for
from domain.tds.tds_computer import TDSComputer
from models.parties import VendorIn, VendorUpdateIn

# The statements tds_deductions.return_type will accept — migration 014's CHECK.
FILEABLE_STATEMENTS = {"24Q", "26Q", "27Q", "27EQ"}

# The registry keys a VENDOR may never carry. There were two reasons to be in
# this set and only one of them was known:
#
#   §192 is the SENTINEL the registry docstring names — present, rateable at
#   0%, and therefore silent rather than merely missing.
#
#   §206C is not a deduction at all. It is tax COLLECTED by a seller from a
#   buyer, reported on Form 27EQ, and its registry entry says in its own
#   comment that it is "reference data only". Nothing refused it until
#   12-09-2026, and the supplier screen's section dropdown is served straight
#   from the registry — so a vendor could be marked §206C and every bill from
#   them withheld 0.1% of the whole amount (the entry's threshold is ZERO) and
#   was stamped 26Q by return_type_for, which routes on residency and never
#   sees the section.
VENDOR_INELIGIBLE = {SECTION_192_SALARY, "206C"}

FYS = ("2025-26", "2026-27")


def _vendor_eligible(fy: str) -> set[str]:
    return set(tds_rates_for(fy).sections) - VENDOR_INELIGIBLE


# ── The registry answers, or the vendor master refuses ──────────────────────

@pytest.mark.parametrize("fy", FYS)
def test_every_registry_section_a_vendor_may_carry_is_accepted(fy):
    """The other half of the fix, and the half that gets forgotten: a rule that
    also blocks the sections a CA legitimately uses is a rule that gets
    reverted the same week."""
    for section in sorted(_vendor_eligible(fy)):
        assert deduction_section_refusal(section, fy) is None, (
            f"{section} is in the registry for {fy} and must not be refused")
        VendorIn(client_id="c", name="V", tds_applicable=True, tds_section=section)


#: Sections the Act charges that are NOT reported on a quarterly statement,
#: and the form each actually goes on. Rule 31A(4A): each is a
#: challan-cum-statement filed within thirty days of the month end, by a
#: deductor with no TAN.
#:
#: `return_type_for` routes on RESIDENCY and never sees the section, so a
#: registry row for any of these would be stamped 26Q — a value migration
#: 014's CHECK accepts and which is simply the wrong return. That is the one
#: failure a CHECK cannot catch, and it is why the refusal lives at the vendor
#: master instead.
NOT_A_QUARTERLY_STATEMENT = {
    "194IA": "26QB", "194-IA": "26QB",
    "194IB": "26QC", "194-IB": "26QC",
    "194M": "26QD",
}

#: And the one that is not a DEDUCTION at all. §206C is tax COLLECTED by a
#: seller from a buyer, reported on 27EQ. It sits in the registry as reference
#: data — its own comment says so — and a vendor may never carry it.
NOT_A_DEDUCTION = {"206C"}


@pytest.mark.parametrize("fy", FYS)
def test_every_registry_section_resolves_to_a_fileable_statement(fy):
    """A section the engine can rate but cannot FILE is the trap that adding
    s.194IA would spring.

    THIS TEST COULD NOT FAIL, AND THAT IS WHY IT IS REWRITTEN. It looped over
    the registry and then called `return_type_for(residency)` — whose signature
    is `return_type_for(residential_status)` and which never sees `section` at
    all. Every iteration asserted the same thing about the same two constants,
    so the property in the docstring was not being tested by the body: a
    §194-IA row WOULD have routed to "26Q", "26Q" IS in FILEABLE_STATEMENTS,
    and the test would have passed while reporting a property deduction on a
    statement it does not belong on. The trap was caught only incidentally, by
    the hardcoded list two tests below.

    The routing rule is still asserted — it is true and worth pinning — but it
    is stated as what it is, a fact about RESIDENCY, and the section-level trap
    is asked separately and directly below.
    """
    for residency in ("resident", "non_resident", None):
        statement = return_type_for(residency)
        assert statement in FILEABLE_STATEMENTS, (
            f"a {residency} payee routes to {statement!r}, which migration "
            f"014's CHECK does not accept")
    # And the routing genuinely ignores the section, which is the premise the
    # test below rests on. If this ever stops being true, that test is the one
    # to revisit rather than delete.
    import inspect
    assert "section" not in inspect.signature(return_type_for).parameters


@pytest.mark.parametrize("fy", FYS)
def test_no_registry_section_would_be_stamped_the_wrong_statement(fy):
    """The property the test above claimed to check, asked of the SECTION.

    `return_type_for` cannot tell a §194-IA row from a §194J one, so the only
    thing standing between a mis-routed return and a CA is that these sections
    are not in the registry a vendor picks from. Assert that directly.
    """
    registry = set(tds_rates_for(fy).sections)
    property_sections = registry & set(NOT_A_QUARTERLY_STATEMENT)
    assert not property_sections, (
        "these are in the registry and are NOT reported on a quarterly "
        "statement — Rule 31A(4A) puts each on its own challan-cum-statement, "
        "and return_type_for would stamp them 26Q, which the CHECK accepts: "
        + ", ".join(f"{s} belongs on {NOT_A_QUARTERLY_STATEMENT[s]}"
                    for s in sorted(property_sections)))


@pytest.mark.parametrize("fy", FYS)
def test_a_section_that_is_not_a_deduction_cannot_be_put_on_a_vendor(fy):
    """§206C, and the hole it was.

    TCS is COLLECTED by a seller from a buyer and reported on 27EQ. Its
    registry entry is reference data — the entry's own comment says "do not
    assume TCS is an implemented feature because a rate exists here" — but
    nothing refused it at the vendor master, and the supplier screen's section
    dropdown is served straight from the registry.

    So a CA could mark a vendor §206C, and then every bill from that vendor
    withheld 0.1% of the WHOLE amount — the entry's threshold is zero, so it
    fires on the first rupee — and the row was stamped 26Q. Three things wrong
    at once: nothing to collect on a bill you are paying, the wrong return, and
    no TCS path to compute it.
    """
    for section in sorted(NOT_A_DEDUCTION):
        if section not in tds_rates_for(fy).sections:
            continue                       # not held: nothing to refuse
        message = deduction_section_refusal(section, fy)
        assert message, (
            f"{section} is in the registry and a vendor can be marked with it. "
            "It is not a deduction — it is collected by a seller from a buyer "
            "and reported on 27EQ.")
        assert "27EQ" in message, "the CA must be told where TCS actually goes"
        with pytest.raises(Exception):
            VendorIn(client_id="c", name="V", tds_applicable=True,
                     tds_section=section)


@pytest.mark.parametrize("fy", FYS)
def test_the_section_list_a_screen_is_served_offers_only_what_the_save_accepts(fy):
    """A dropdown whose options the save refuses is a dead control, and
    §206C's was worse than dead — nothing refused it, so the option worked and
    produced a wrong deduction on the wrong return.

    Decided by the endpoint from `deduction_section_refusal`, so the screen
    cannot keep its own exclusion list and drift from it.
    """
    from routers.tds import list_tds_sections
    served = list_tds_sections(
        fy=fy, user={"id": "u", "firm_id": "F", "role": "Partner"})["data"]
    for row in served["sections"]:
        assert row["vendor_eligible"] == (
            deduction_section_refusal(row["section"], fy) is None), row["section"]
    offered = {r["section"] for r in served["sections"] if r["vendor_eligible"]}
    assert SECTION_192_SALARY not in offered
    assert NOT_A_DEDUCTION.isdisjoint(offered)
    assert "194J" in offered, "the ordinary sections must still be offered"


@pytest.mark.parametrize("fy", FYS)
def test_a_section_outside_the_registry_is_refused_with_a_usable_sentence(fy):
    """Named properties, not the literal wording — rewording the sentence must
    not break this, but dropping the section number or the alternatives must."""
    for section in ("194IA", "194R", "194T", "194M", "194ZZ"):
        message = deduction_section_refusal(section, fy)
        assert message, f"{section} is not in the registry and must be refused"
        assert section in message, "the CA must be told WHICH section"
        assert "194J" in message, "and which sections are available instead"
        assert SECTION_192_SALARY not in message.split("The sections it can compute are:")[1].split(".")[0], (
            "s.192 must not be offered as an alternative — it is refused two "
            "branches above, and suggesting it answers one refusal with another")


def test_a_property_section_says_it_cannot_be_FILED_not_merely_that_a_rate_is_missing():
    """s.194IA is the section a CA reaches for first, and a rate alone would
    not fix it. The refusal has to say why, or the obvious next step is to add
    a row to the registry — which is the dangerous change."""
    message = deduction_section_refusal("194IA")
    assert message
    assert "wrong return" in message or "no way to file" in message, (
        "the refusal must say the deduction cannot be FILED here, not only "
        "that a rate is missing")


# ── s.192, the silent nil ───────────────────────────────────────────────────

def test_the_registry_still_holds_192_as_a_sentinel_that_computes_nil():
    """The premise of the s.192 refusal, asserted rather than assumed. If this
    ever stops being true — if s.192 gains a real rate here — the refusal below
    needs rethinking rather than silently continuing to fire."""
    resolution = TDSComputer().resolve_tds(
        section=SECTION_192_SALARY, taxable_paise=10_00_000_00, fy="2025-26")
    assert resolution.applies is True and resolution.tds_paise == 0, (
        "s.192 in section_rates.py is a sentinel: it must still answer nil, "
        "which is exactly why a vendor may not carry it")


def test_a_vendor_cannot_carry_section_192():
    with pytest.raises(ValidationError) as err:
        VendorIn(client_id="c", name="V", tds_applicable=True,
                 tds_section=SECTION_192_SALARY)
    assert "Payroll" in str(err.value), (
        "the refusal must send the CA somewhere — s.192 is computed, just not "
        "here")


# ── Both models, and the PATCH hole the obvious gate would leave ────────────

def test_the_update_path_refuses_the_same_sections_as_the_create_path():
    """A create path that rejects and an update path that accepts would let the
    value in by one door. VendorUpdateIn is PATCH-shaped, so tds_applicable is
    None whenever the request does not mention it — a gate on tds_applicable
    would miss a PATCH that sets only the section."""
    with pytest.raises(ValidationError):
        VendorUpdateIn(tds_section="194IA")
    with pytest.raises(ValidationError):
        VendorUpdateIn(tds_section=SECTION_192_SALARY)
    VendorUpdateIn(tds_section="194C")           # still accepted
    VendorUpdateIn(name="X")                     # no section supplied, no opinion


def test_a_section_is_refused_even_with_tds_switched_off():
    """Not pedantry: a section recorded while TDS is off is a landmine that
    goes off at the first bill after somebody switches it on — which is the
    delayed failure this whole change moves earlier."""
    with pytest.raises(ValidationError):
        VendorIn(client_id="c", name="V", tds_applicable=False, tds_section="194IA")


def test_a_vendor_with_no_section_is_untouched():
    VendorIn(client_id="c", name="V", tds_applicable=False)
    VendorIn(client_id="c", name="V", tds_applicable=False, tds_section=None)


def test_section_195_is_not_refused_here():
    """s.195 has no registry row and must not be caught by the "not in the
    registry" branch: domain/tds/section_195.py rates it, and raises its own
    refusals about the PAYMENT rather than about the section."""
    assert deduction_section_refusal("195") is None
    VendorIn(client_id="c", name="V", tds_applicable=True, tds_section="195",
             residential_status="non_resident", country_of_residence="US")


# ── The frontend half: no screen may OFFER what the engine cannot answer for ─
#
# In Python rather than in apps/web's own suite, deliberately: the rule is
# "against the registry", and the registry is section_rates.py. A TypeScript
# test would have to restate the section list to check it, which is the third
# copy this phase exists to remove.

_WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_SKIP_DIRS = {"node_modules", ".next", "out", ".vercel"}
_SECTION_LITERAL = re.compile(r'"(19[0-9][A-Z]{0,4}(?:\([a-z]{1,2}\))?)"')

# Places a section literal may legitimately appear that is NOT an offer to
# record a deduction. Each needs its reason, and the list may only shrink.
_NOT_A_DEDUCTION_PICKER: dict[str, str] = {
    "app/tds/page.tsx":
        "SECTION_LABELS is a NAME lookup, and the challan modal legitimately "
        "offers s.192 — a salary TDS deposit is a real ITNS 281 payment that a "
        "CA records here. The DEDUCTION picker is seeded from "
        "DEDUCTIBLE_SECTIONS, which excludes it; that exclusion is asserted "
        "below rather than exempted.",
    "app/accounting/suppliers/page.tsx":
        "SECTION_LABELS is a NAME lookup only — the offered list is fetched "
        "from GET /api/tds/sections and rendered from the response, which is "
        "the shape every screen should use.",
}


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _strip_comments(src: str) -> str:
    """Comments blanked, line numbers preserved — the notes left where s.192
    used to be name s.192, so a scan that read comments would fail on the
    documentation of its own fix."""
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: _blank(m.group(0)), src)
    return re.sub(r'(^|[^:])//[^\n]*',
                  lambda m: m.group(1) + _blank(m.group(0)[len(m.group(1)):]), src)


def _web_section_literals() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not _WEB.exists():                                   # pragma: no cover
        pytest.skip("apps/web not present")
    for path in sorted(_WEB.rglob("*.ts*")):
        rel = path.relative_to(_WEB)
        if set(rel.parts) & _SKIP_DIRS or path.name.endswith(".test.ts"):
            continue
        found = set(_SECTION_LITERAL.findall(
            _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))))
        if found:
            out[str(rel)] = found
    return out


def test_no_screen_offers_a_section_the_engine_does_not_hold():
    """The rule, over the registry rather than over a list of screens.

    Before this, three files held three different section lists: the purchases
    dropdown (9), /tds's labels (14) and lib/imports/mappers.ts's importer (5).
    The importer's rejected EIGHT sections the engine does hold — a false
    refusal, the same divergence pointing the other way — and it is gone.
    """
    eligible = _vendor_eligible("2026-27") | _vendor_eligible("2025-26") | {"195"}
    offenders: list[str] = []
    for rel, sections in _web_section_literals().items():
        for section in sorted(sections - eligible):
            if rel in _NOT_A_DEDUCTION_PICKER and section == SECTION_192_SALARY:
                continue                                     # reasoned above
            offenders.append(f"{rel}: {section}")
    assert not offenders, (
        "these screens name a TDS section the engine cannot compute, so a CA "
        "can pick it and the bill will be refused — or, for s.192, saved with "
        "nil tax and no gap:\n  " + "\n  ".join(offenders)
        + "\n\nFetch the list from GET /api/tds/sections, or add the section to "
          "domain/tds/section_rates.py if the engine really can answer for it.")


def test_the_tds_deduction_picker_excludes_section_192_by_construction():
    """The one exemption above, asserted rather than trusted. s.192 may appear
    in that file — it is a valid CHALLAN section — but never in the list the
    deduction form offers."""
    page = (_WEB / "app" / "tds" / "page.tsx").read_text(encoding="utf-8")
    assert 'const DEDUCTIBLE_SECTIONS = Object.keys(SECTION_LABELS).filter(s => s !== "192")' in page, (
        "the deduction picker's fallback list must exclude s.192 by "
        "construction, not by someone remembering to leave it out")
    assert "useState<string[]>(DEDUCTIBLE_SECTIONS)" in page, (
        "and the deduction form must seed from it")


def test_the_vendor_importer_holds_no_section_list_of_its_own():
    """It held a five-section list that refused eight the engine supports. The
    server now refuses with a sentence naming the section and listing what is
    available, so a copy here can only be wrong in one of two directions."""
    mappers = (_WEB / "lib" / "imports" / "mappers.ts").read_text(encoding="utf-8")
    assert "const TDS_SECTIONS =" not in mappers, (
        "the importer must not re-state which sections are valid")
    # The CSV COLUMN, not the field name. BuiltVendor still carries
    # tds_rate_bps because VendorIn still accepts it — removing the API field
    # is TDS-13's remaining half and is not this change. What must not come
    # back is READING a rate out of the spreadsheet: the engine resolves the
    # rate from the section, the payee's PAN, the year's aggregate and s.206AA,
    # and in production every rate a CA typed was the s.194C COMPANY rate,
    # applied to individual contractors at double.
    code = _strip_comments(mappers)
    assert "r.tds_rate" not in code, (
        "the importer must not read a TDS rate from the spreadsheet")
    assert 'key: "tds_rate"' not in code, (
        "and must not offer a TDS Rate column for a CA to fill in")
