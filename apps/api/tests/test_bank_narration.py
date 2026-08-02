"""
Indian bank narration parsing (Tier 6.2).

An Indian narration is a delimited record, not free text — the channel, UTR,
counterparty and VPA are already in it. These tests use real-shaped narrations
from the major banks, because the whole value of the module is that it copes
with formats nobody standardised.

The parser deliberately classifies tokens BY SHAPE rather than enumerating
per-bank layouts: there are hundreds and they change without notice. So the
tests are organised by bank to prove the shape-based approach actually covers
them, not because the code knows which bank it is looking at.
"""
import pytest

from domain.banking.narration import (
    parse_narration, party_matches, normalise_party_name, describe,
)


# ══════════════════════════════════════════════════════════════════════════════
# Per-bank formats
# ══════════════════════════════════════════════════════════════════════════════

def test_sbi_upi_debit():
    p = parse_narration("TO TRANSFER-UPI/DR/412345678901/RAMESH KUMAR/HDFC/ramesh@okhdfc/PAYMENT--")
    assert p.channel == "UPI"
    assert p.utr == "412345678901"
    assert p.vpa == "ramesh@okhdfc"
    assert p.counterparty == "RAMESH KUMAR"
    assert p.direction == "debit"


def test_sbi_upi_credit():
    p = parse_narration("BY TRANSFER-UPI/CR/998877665544/ACME PVT LTD/ICIC/acme@okicici/--")
    assert p.channel == "UPI"
    assert p.utr == "998877665544"
    assert p.counterparty == "ACME PVT LTD"
    assert p.direction == "credit"


def test_hdfc_upi():
    p = parse_narration("UPI-RAMESH KUMAR-RAMESH@OKAXIS-HDFC0000123-412345678901-PAYMENT")
    assert p.channel == "UPI"
    assert p.utr == "412345678901"
    assert p.vpa == "RAMESH@OKAXIS"
    assert p.ifsc == "HDFC0000123"
    assert p.counterparty == "RAMESH KUMAR"


def test_hdfc_neft():
    p = parse_narration("NEFT DR-SBIN0001234-ACME PVT LTD-N123456789012345")
    assert p.channel == "NEFT"
    assert p.counterparty == "ACME PVT LTD"
    assert p.ifsc == "SBIN0001234"
    assert p.utr == "N123456789012345"
    assert p.direction == "debit"


def test_icici_upi():
    p = parse_narration("UPI/412345678901/Payment from/ramesh@okicici/HDFC BANK")
    assert p.channel == "UPI"
    assert p.utr == "412345678901"
    assert p.vpa == "ramesh@okicici"


def test_icici_imps():
    p = parse_narration("MMT/IMPS/412512345678/Payment/RAMESH KUMAR/HDFC")
    assert p.channel == "IMPS"
    assert p.utr == "412512345678"
    assert p.counterparty == "RAMESH KUMAR"


def test_axis_upi():
    p = parse_narration("UPI/P2A/412345678901/RAMESH KUMAR/HDFC")
    assert p.channel == "UPI"
    assert p.utr == "412345678901"
    assert p.counterparty == "RAMESH KUMAR"


def test_axis_neft():
    p = parse_narration("NEFT/AXISP00123456/ACME ENTERPRISES/HDFC0000123")
    assert p.channel == "NEFT"
    assert p.counterparty == "ACME ENTERPRISES"
    assert p.ifsc == "HDFC0000123"


def test_kotak_upi():
    p = parse_narration("UPI-412345678901-RAMESH KUMAR-KKBK")
    assert p.channel == "UPI" and p.utr == "412345678901"
    assert p.counterparty == "RAMESH KUMAR"


def test_rtgs():
    p = parse_narration("RTGS-HDFCR52024061012345678-ACME PVT LTD")
    assert p.channel == "RTGS"
    assert p.counterparty == "ACME PVT LTD"


# ══════════════════════════════════════════════════════════════════════════════
# Non-transfer narrations
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,channel", [
    ("ATW-412345XXXXXX1234-HDFC ATM MUMBAI", "ATM"),
    ("POS 1234XXXXXXXX5678 AMAZON RETAIL", "POS"),
    ("CHQ PAID-123456", "CHEQUE"),
    ("ACH D- INDIAN CLEARING CORP-MANDATE", "NACH"),
    ("AMB CHRG INCL GST FOR MAR2026", "CHARGES"),
    ("CREDIT INTEREST CAPITALISED", "INTEREST"),
    ("CASH DEP MUMBAI BRANCH", "CASH"),
])
def test_channel_detection(text, channel):
    assert parse_narration(text).channel == channel


def test_a_bank_charge_has_no_counterparty_utr_or_vpa():
    p = parse_narration("AMB CHRG INCL GST FOR MAR2026")
    assert p.channel == "CHARGES"
    assert p.utr is None and p.vpa is None


# ══════════════════════════════════════════════════════════════════════════════
# What must NOT be mistaken for something else
# ══════════════════════════════════════════════════════════════════════════════

def test_an_ifsc_is_not_read_as_a_neft_reference():
    """Both are 4 letters then alphanumerics. Confusing them would put a routing
    code in the UTR field, where a CA would then try to trace it."""
    p = parse_narration("NEFT-HDFC0000123-ACME PVT LTD")
    assert p.ifsc == "HDFC0000123"
    assert p.utr != "HDFC0000123"


def test_a_masked_account_number_is_not_a_counterparty():
    p = parse_narration("IMPS-412512345678-XXXXXXXX1234-HDFC")
    assert p.counterparty != "XXXXXXXX1234"


def test_a_bare_bank_code_is_not_a_counterparty():
    p = parse_narration("UPI/DR/412345678901/HDFC/PAYMENT")
    assert p.counterparty not in ("HDFC", "PAYMENT")


def test_routing_words_are_not_counterparties():
    p = parse_narration("TO TRANSFER-UPI/DR/412345678901/PAYMENT")
    assert p.counterparty is None


def test_a_thirteen_digit_number_is_not_a_utr():
    """Exactly twelve digits, or it is an account number or an amount."""
    assert parse_narration("UPI/DR/4123456789012/RAMESH").utr is None


def test_direction_ignores_the_words_credit_card():
    """'CREDIT CARD' is a product name. The debit/credit columns are the
    authority anyway — this field is only ever corroboration."""
    p = parse_narration("POS/CREDIT CARD PAYMENT/AMAZON")
    assert p.direction is None


# ══════════════════════════════════════════════════════════════════════════════
# Degenerate input
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text", [None, "", "   ", "///", "----"])
def test_degenerate_input_never_raises(text):
    p = parse_narration(text)
    assert p.is_empty


def test_an_unrecognised_narration_yields_no_guesses():
    p = parse_narration("MISC ENTRY 998877")
    assert p.channel is None and p.utr is None and p.vpa is None


def test_the_vpa_handle_is_the_last_resort_counterparty():
    """`ramesh@okhdfc` still tells a CA more than nothing."""
    p = parse_narration("UPI/DR/412345678901/ramesh@okhdfc")
    assert p.counterparty == "ramesh"


# ══════════════════════════════════════════════════════════════════════════════
# Party matching — the point of the whole module
# ══════════════════════════════════════════════════════════════════════════════

def test_normalise_strips_entity_suffixes_and_punctuation():
    assert normalise_party_name("Acme Pvt. Ltd.") == "ACME"
    assert normalise_party_name("ACME PRIVATE LIMITED") == "ACME"
    assert normalise_party_name("Acme Enterprises") == "ACME"
    assert normalise_party_name(None) == ""


def test_the_case_the_old_substring_test_missed():
    """'Acme Pvt Ltd' stored, 'ACME PRIVATE LIMITED' printed by the bank. The
    matcher's `party_name.lower() in narration` was False here, so a perfectly
    good match never surfaced."""
    p = parse_narration("BY TRANSFER-UPI/CR/998877665544/ACME PRIVATE LIMITED/ICIC/--")
    assert p.counterparty == "ACME PRIVATE LIMITED"
    assert party_matches("Acme Pvt Ltd", p) is True


def test_the_old_substring_behaviour_still_works():
    """Nothing that matched before may stop matching."""
    p = parse_narration("NEFT payment from Acme Pvt Ltd for invoices")
    assert party_matches("Acme Pvt Ltd", p) is True


def test_a_multi_word_name_matches_inside_a_longer_one():
    p = parse_narration("UPI/CR/412345678901/ACME TRADING MUMBAI/HDFC")
    assert party_matches("Acme Trading", p) is True


def test_one_shared_word_is_not_a_match():
    """'SHARMA' or 'INDIA' appearing in both is a coincidence, not a party."""
    p = parse_narration("UPI/DR/412345678901/RAJESH SHARMA TRADERS/HDFC")
    assert party_matches("Suresh Sharma Exports", p) is False


def test_a_single_word_party_needs_a_tight_counterparty():
    """One shared word between a one-word party and a long counterparty is too
    weak to call a match.

    Note the party name here is 'Acme Ltd', not 'Acme': the raw-substring test
    (kept so nothing that matched before stops matching) would fire on a bare
    'Acme' appearing anywhere in the narration. This exercises the normalised
    token path, which is the one that needs the guard.
    """
    p_tight = parse_narration("UPI/CR/412345678901/ACME/HDFC")
    assert party_matches("Acme Ltd", p_tight) is True
    p_loose = parse_narration("UPI/CR/412345678901/ACME TRADING COMPANY MUMBAI/HDFC")
    assert party_matches("Acme Ltd", p_loose) is False


def test_an_unrelated_party_does_not_match():
    p = parse_narration("UPI/DR/412345678901/RAMESH KUMAR/HDFC")
    assert party_matches("Global Exports", p) is False


def test_party_matching_handles_missing_input():
    p = parse_narration("UPI/DR/412345678901/RAMESH KUMAR/HDFC")
    assert party_matches(None, p) is False
    assert party_matches("", p) is False
    assert party_matches("Acme", parse_narration("")) is False


# ══════════════════════════════════════════════════════════════════════════════
# Display
# ══════════════════════════════════════════════════════════════════════════════

def test_describe_summarises_for_the_queue():
    p = parse_narration("TO TRANSFER-UPI/DR/412345678901/RAMESH KUMAR/HDFC/ramesh@okhdfc/--")
    assert describe(p) == "UPI · RAMESH KUMAR · UTR 412345678901 · ramesh@okhdfc"


def test_describe_of_an_unparsed_narration_is_empty():
    assert describe(parse_narration("MISC 9987")) == ""


# ══════════════════════════════════════════════════════════════════════════════
# Wiring — the parser only earns its place if the matcher and queue use it
# ══════════════════════════════════════════════════════════════════════════════

def test_the_matcher_now_recognises_a_suffix_variant_party():
    """The regression this module exists for, end to end through the ranker."""
    from domain.banking import Candidate, rank_suggestions
    narration = "BY TRANSFER-UPI/CR/998877665544/ACME PRIVATE LIMITED/ICIC/--"
    cand = Candidate(entity_type="sales_invoice", entity_id="i1", label="INV-1",
                     amount_paise=118000, entity_date="2026-04-10",
                     party_name="Acme Pvt Ltd")
    s = rank_suggestions(118000, "2026-04-10", narration, [cand])[0]
    assert "party in narration" in s.reasons


def test_the_matcher_does_not_invent_a_party_match():
    from domain.banking import Candidate, rank_suggestions
    narration = "BY TRANSFER-UPI/CR/998877665544/RAMESH KUMAR/HDFC/--"
    cand = Candidate(entity_type="sales_invoice", entity_id="i1", label="INV-1",
                     amount_paise=118000, entity_date="2026-04-10",
                     party_name="Global Exports")
    s = rank_suggestions(118000, "2026-04-10", narration, [cand])[0]
    assert "party in narration" not in s.reasons


def test_the_queue_surfaces_the_parsed_narration():
    from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn
    from services.bank_matching_service import bank_matching_service
    db = FakeDB()
    _seed_txn(db, id="u1",
              description="TO TRANSFER-UPI/DR/412345678901/RAMESH KUMAR/HDFC/ramesh@okhdfc/--")
    row = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]
    assert row["parsed"]["channel"] == "UPI"
    assert row["parsed"]["utr"] == "412345678901"
    assert row["parsed"]["counterparty"] == "RAMESH KUMAR"
    assert row["parsed"]["vpa"] == "ramesh@okhdfc"
    # The raw narration is untouched — it is the record of what arrived.
    assert row["description"].startswith("TO TRANSFER-UPI/DR/")


def test_the_queue_handles_an_unparseable_narration():
    from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn
    from services.bank_matching_service import bank_matching_service
    db = FakeDB()
    _seed_txn(db, id="u1", description="MISC 9987")
    row = bank_matching_service.queue(db, FIRM, CLIENT, "unmatched")[0]
    assert row["parsed"]["counterparty"] is None
    assert row["parsed"]["summary"] == ""
