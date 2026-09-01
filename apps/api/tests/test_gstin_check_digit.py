"""
The GSTIN check digit — CGST Act 2017 s.25, and the GSTN's registration format.

WHY IT MATTERS ENOUGH TO TEST PROPERLY

    Six places in this codebase already test a GSTIN against its shape, and the
    shape passes every transposition inside the PAN. A sales invoice carrying a
    well-formed GSTIN that is not the recipient's puts the supply into somebody
    else's GSTR-2B; the recipient never gets the credit, and the fix is an
    amendment under s.37(3) inside a window that closes on 30 November following
    the FY or the date GSTR-9 was furnished, whichever is EARLIER.

    So the interesting cases here are not "is 15 characters" — they are the
    typos that survive the regex.
"""
import pytest

from domain.gst.gstin import (
    ALPHABET, checksum_char, is_valid, pan_of, problem_with, state_code,
)

# Real, published GSTINs. Three independent numbers agreeing with a mod-36
# checksum is not a coincidence — this is what pins the algorithm rather than
# my reading of it.
REAL = ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4", "24AAACC1206D1ZM"]

# The cases shared with the browser mirror. apps/web/lib/gst/gstin.test.ts reads
# the SAME file, so the two implementations are exercised on the same numbers
# and one cannot be changed without the other failing.
import json
from pathlib import Path as _Path

SHARED = json.loads((_Path(__file__).parent / "fixtures" / "gstin.json").read_text())


@pytest.mark.parametrize("gstin", SHARED["valid"])
def test_shared_fixture_valid_cases(gstin):
    assert is_valid(gstin), problem_with(gstin)


@pytest.mark.parametrize("case", SHARED["invalid"], ids=[c["gstin"] for c in SHARED["invalid"]])
def test_shared_fixture_invalid_cases(case):
    problem = problem_with(case["gstin"])
    assert problem is not None
    assert case["fragment"] in problem, problem


def test_the_state_code_fixtures_isolate_the_state_rule():
    """Each carries its OWN correct check digit, so the state code is the only
    thing wrong with it. Without that they would pass on the check-digit branch
    and prove nothing about state codes."""
    for case in SHARED["invalid"]:
        if "state code" in case["fragment"]:
            g = case["gstin"]
            assert checksum_char(g[:14]) == g[14], g


@pytest.mark.parametrize("gstin", REAL)
def test_a_real_gstin_passes(gstin):
    assert is_valid(gstin), problem_with(gstin)


@pytest.mark.parametrize("gstin", REAL)
def test_the_computed_check_digit_is_the_one_printed(gstin):
    assert checksum_char(gstin[:14]) == gstin[14]


# ── The typos the shape regex cannot see ─────────────────────────────────────

@pytest.mark.parametrize("gstin", REAL)
def test_transposing_two_characters_is_caught(gstin):
    """The failure mode this exists for. Swapping two characters of the PAN
    leaves a perfectly well-formed GSTIN."""
    from models.client import GSTIN_REGEX
    swapped = gstin[:7] + gstin[8] + gstin[7] + gstin[9:]
    assert swapped != gstin
    assert GSTIN_REGEX.match(swapped), "the shape regex still accepts it — that is the point"
    assert not is_valid(swapped)
    assert "check digit does not match" in problem_with(swapped)


def test_a_single_wrong_character_is_caught():
    bad = "27AAPFU0939F1ZW"          # last character off by one
    assert not is_valid(bad)
    assert "check digit" in problem_with(bad)


def test_the_message_names_the_expected_character():
    """A CA reads this beside the field. "Invalid GSTIN" does not tell them
    which character to look at."""
    msg = problem_with("27AAPFU0939F1ZW")
    assert "ends in W" in msg and "compute to V" in msg


# ── Shape and state code ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad,fragment", [
    ("27AAPFU0939F1Z", "15 characters"),
    ("27AAPFU0939F1ZVV", "15 characters"),
    ("27AAPFU0939F1AV", "Not a GSTIN pattern"),      # 'Z' is not where it must be
    ("2AAAPFU0939F1ZV", "Not a GSTIN pattern"),
    ("27AAPFU0939F0ZV", "Not a GSTIN pattern"),      # entity number is never 0
])
def test_malformed_gstins_say_what_is_wrong(bad, fragment):
    assert not is_valid(bad)
    assert fragment in problem_with(bad)


@pytest.mark.parametrize("code", ["00", "39", "51", "98"])
def test_an_impossible_state_code_is_refused(code):
    """State codes run 01-38 plus 97 and 99. A leading 00 or 51 is a keying
    error, and it decides place of supply — so it decides whether the invoice
    charges IGST or CGST+SGST."""
    # Built with its OWN correct check digit, so the only thing wrong with it is
    # the state code — otherwise this would pass for the wrong reason.
    body = code + "AAPFU0939F1Z"
    gstin = body + checksum_char(body)
    assert not is_valid(gstin)
    assert "not a GST state code" in problem_with(gstin)


@pytest.mark.parametrize("code", ["01", "27", "38", "97", "99"])
def test_the_real_state_codes_are_accepted(code):
    body = code + "AAPFU0939F1Z"
    gstin = body + checksum_char(body)
    assert is_valid(gstin), problem_with(gstin)


# ── Blank ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_is_not_wrong(blank):
    """A person who is not registered has no GSTIN. That is different from
    having a wrong one, and a composition or unregistered supplier must not be
    unsaveable."""
    assert is_valid(blank)
    assert problem_with(blank) is None


def test_case_and_whitespace_are_forgiven():
    assert is_valid("  27aapfu0939f1zv  ")


# ── The two things the GSTIN carries ─────────────────────────────────────────

def test_the_state_code_and_pan_can_be_read_off():
    assert state_code("27AAPFU0939F1ZV") == "27"
    assert pan_of("27AAPFU0939F1ZV") == "AAPFU0939F"


def test_nothing_is_read_off_an_invalid_gstin():
    """Place of supply follows the state code (IGST Act s.7/s.8). Reading one
    out of a number that failed its own check digit would silently decide
    whether IGST or CGST+SGST is charged."""
    assert state_code("27AAPFU0939F1ZW") is None
    assert pan_of("27AAPFU0939F1ZW") is None


# ── The algorithm itself ─────────────────────────────────────────────────────

def test_the_alphabet_is_the_36_symbol_one_positionally():
    assert len(ALPHABET) == 36
    assert ALPHABET[0] == "0" and ALPHABET[9] == "9"
    assert ALPHABET[10] == "A" and ALPHABET[35] == "Z"


def test_the_checksum_needs_exactly_fourteen_characters():
    with pytest.raises(ValueError, match="14 characters"):
        checksum_char("27AAPFU0939F1")


def test_a_character_outside_the_alphabet_is_refused():
    with pytest.raises(ValueError, match="not a GSTIN character"):
        checksum_char("27AAPFU0939F1-")


def test_every_check_digit_the_algorithm_produces_validates():
    """Round trip over the whole symbol space at one position, so a weight or a
    modulus that is off shows up rather than happening to work for the three
    real numbers above."""
    for ch in ALPHABET[10:]:            # entity number position takes A-Z
        body = "27AAPFU0939F" + ch + "Z"
        assert is_valid(body + checksum_char(body)), body


# ── Where it is actually enforced ────────────────────────────────────────────
# The check digit is deliberately NOT in models.client.validate_gstin — see the
# module docstring. These pin the three places a human types one, so a later
# refactor cannot quietly drop the check back to a shape test.

import pytest as _pytest
from fastapi import HTTPException

CLIENT = "11111111-1111-1111-1111-111111111111"
FIRM = "22222222-2222-2222-2222-222222222222"
GOOD = "27AAPFU0939F1ZV"
TRANSPOSED = "27AAPFU0399F1ZV"          # well-formed, wrong check digit


@_pytest.fixture()
def _scoped(monkeypatch):
    """Past the tenancy guard, so what is being tested is the GSTIN check and
    not the client-assignment check that runs before it."""
    from routers import customers as c
    from routers import vendors as v
    monkeypatch.setattr(c, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(v, "assert_client_access", lambda *a, **k: None)


def test_a_customer_with_a_transposed_gstin_is_refused(_scoped):
    from routers.customers import create_customer
    from models.parties import CustomerIn
    with _pytest.raises(HTTPException) as e:
        create_customer(CustomerIn(client_id=CLIENT, name="Acme", gstin=TRANSPOSED),
                        {"firm_id": FIRM, "role": "Partner"})
    assert e.value.status_code == 422
    assert "check digit" in str(e.value.detail)


def test_a_customer_with_a_real_gstin_gets_past_the_check(_scoped):
    """The guard must not be a blanket refusal — a correct GSTIN reaches the
    code after it (which, with no database configured, is where it stops)."""
    from routers.customers import create_customer
    from models.parties import CustomerIn
    out = create_customer(CustomerIn(client_id=CLIENT, name="Acme", gstin=GOOD),
                          {"firm_id": FIRM, "role": "Partner"})
    assert "check digit" not in str(out)


def test_a_vendor_with_a_transposed_gstin_is_refused(_scoped):
    from routers.vendors import create_vendor
    from models.parties import VendorIn
    with _pytest.raises(HTTPException) as e:
        create_vendor(VendorIn(client_id=CLIENT, name="Supplier", gstin=TRANSPOSED),
                      {"firm_id": FIRM, "role": "Partner"})
    assert e.value.status_code == 422
    assert "check digit" in str(e.value.detail)


def test_the_shape_validator_is_deliberately_left_alone():
    """models.client.validate_gstin guards a Pydantic field that 512 invented
    fixture GSTINs flow through. Tightening it would fail them all and prove
    nothing — the typo this catches happens at a keyboard, not in a fixture."""
    from models.client import validate_gstin
    assert validate_gstin(TRANSPOSED) == TRANSPOSED
