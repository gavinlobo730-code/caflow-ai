"""Form 140 does not have a section 194J.

WHAT WAS WRONG (TDS-17)

    `tds_return_service` resolved the FORM number through
    `domain/tds/vocabulary.py` — `"form": statement_form(RESIDENT_NON_SALARY,
    fy_label=fy)` — and left every deductee line's `section` exactly as it came
    out of `tds_deductions.tds_section`. So a FY 2026-27 quarter came back as:

        {"form": "140", "act": "Income-tax Act, 2025",
         "deductees": [{"section": "194J", ...}]}

    Form 140 is the Income-tax Act 2025's statement, and that Act does not
    contain a section 194J: CBDT Notification 22/2026 collapsed the whole
    §194 series into §393(1), §192 into §392 and §195 into §393(2). A statement
    naming a section its own Act does not have is a correction statement
    waiting to happen, and `vocabulary.py`'s own docstring says the module
    exists to prevent exactly this.

    All three from-books builders had it: 26Q, 27Q and 24Q.

WHAT IS TRANSLATED, AND WHAT IS NOT

    THE EMISSION DICT ONLY. `d.section` is a ROUTING key everywhere else — it
    came off `tds_deductions.tds_section`, it groups the challan match
    (`challan_mapping.parent_of`), and `section_rates` is keyed on it. CLAUDE.md
    is explicit: translate at the boundary, never rekey a store. Rekeying the
    challan match would break it outright, because a challan records what
    somebody typed and says "194J" in every period.

    So the label goes out as `section` and the stored code travels beside it as
    `section_1961`. That second field is load-bearing rather than decorative:
    §393(1) HAS NO REVERSE — nine sections collapse into it — so a reader given
    only the label cannot recover the section that produced it, and
    `lib/data/tds.ts` writes the whole payload into `tds_returns.fvu_json`.

WHAT IS NOT CLAIMED

    That the line is complete. The 2025-Act statement also wants a numeric
    payment code 1001-1067, which `vocabulary.py` deliberately does not hold;
    `gaps()` already says so and every one of these returns already surfaces it
    in `statutory_gaps`.
"""
from __future__ import annotations

import pytest

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import services.tds_return_service as trs
from domain.tds import vocabulary as v
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
TAN = "MUMF12345G"

OLD_FY, OLD_Q, OLD_DATE = "2025-26", "Q1", "2025-05-12"
NEW_FY, NEW_Q, NEW_DATE = "2026-27", "Q1", "2026-05-12"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pb, pp])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    d.seed("vendors", {
        "id": "RES", "firm_id": FIRM, "client_id": "CLI", "name": "Sharma & Co",
        "state_code": "27", "pan": "AAACB1234C", "is_active": True,
        "tds_applicable": True, "tds_section": "194J",
        "residential_status": "resident"})
    seed_standard_coa(d, FIRM, "CLI")
    d.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                 "name": "Professional fees", "kind": "service"})
    return d


def _bill(db, no, on, taxable=5_00_000_00):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="RES", bill_date=on, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Advice",
                                  hsn_sac="9982", quantity=1, rate_paise=taxable,
                                  gst_rate_percent=0.0)],
    ), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]


def _26q(db, fy, q):
    return trs.tds_26q_from_books(db, FIRM, "CLI", fy, q, TAN,
                                  "Apex", "AAACA1234B", "Mumbai")


# ── the fixture has to produce a deductee at all ─────────────────────────────

def test_the_fixture_really_files_a_194j_deduction(db):
    """Guard. With no deductee row every assertion below is vacuous — which is
    how this survived a suite that already tested the vocabulary thoroughly,
    one layer away from the return that emits it."""
    _bill(db, "P-1", OLD_DATE)
    out = _26q(db, OLD_FY, OLD_Q)
    assert out["deductees"], "no deductee — the rest of this file proves nothing"
    assert out["deductees"][0]["tds_deducted_paise"] > 0


# ── the two Acts ─────────────────────────────────────────────────────────────

def test_a_1961_act_quarter_is_unchanged(db):
    """The 2025 Act governs from 01-04-2026 and not one day earlier. A belated
    or revised FY 2025-26 statement filed today is still 26Q citing 194J, for
    ever."""
    _bill(db, "P-1", OLD_DATE)
    out = _26q(db, OLD_FY, OLD_Q)
    assert out["form"] == "26Q"
    assert out["deductees"][0]["section"] == "194J"
    assert out["deductees"][0]["section_1961"] == "194J"


def test_a_2025_act_quarter_cites_the_section_that_act_has(db):
    """The whole finding, stated: Form 140 with a 194J line on it."""
    _bill(db, "P-1", NEW_DATE)
    out = _26q(db, NEW_FY, NEW_Q)
    assert out["form"] == "140"
    assert out["act"] == v.vocabulary_for(NEW_FY).act_name
    d = out["deductees"][0]
    assert d["section"] == "393(1)", (
        "the form was translated and the section was not — a statement citing "
        "a section its own Act does not contain")
    assert d["section_1961"] == "194J"


def test_the_stored_routing_key_travels_with_the_label(db):
    """§393(1) has no reverse — nine sections collapse into it — so a reader
    given only the label cannot get back to the section that produced it, and
    the challan match, the rate lookup and `tds_deductions` all key on the
    1961 code."""
    _bill(db, "P-1", NEW_DATE)
    d = _26q(db, NEW_FY, NEW_Q)["deductees"][0]
    assert d["section"] != d["section_1961"]
    assert d["section_1961"] == "194J"
    with pytest.raises(v.VocabularyError):
        v.section_1961_for("393(1)")        # the reverse really is refused


def test_the_challan_match_still_sees_the_1961_code(db):
    """`challan_mapping.parent_of` groups on the stored section, and a challan
    records what somebody typed: it says 194J in every period. Translating the
    routing key would break the match outright."""
    _bill(db, "P-1", NEW_DATE)
    db.seed("tds_challans", {
        "firm_id": FIRM, "client_id": "CLI", "financial_year": NEW_FY,
        "quarter": NEW_Q, "section": "194J", "challan_no": "00021",
        "bsr_code": "0004329", "payment_date": "2026-06-07",
        "tds_paise": 50_000, "total_paise": 50_000, "status": "deposited"})
    out = _26q(db, NEW_FY, NEW_Q)
    assert out["deductees"][0]["challan_no"] == "00021", (
        "the challan stored as 194J no longer matches a line labelled 393(1)")


def test_a_salary_statement_translates_too(db):
    """24Q's every line is §192, which becomes §392. `domain/payroll/form24q.py`
    already resolved it; the statement builder did not."""
    assert v.vocabulary_for(NEW_FY).section("192") == "392"
    assert v.vocabulary_for(OLD_FY).section("192") == "192"


def test_the_payment_code_gap_still_rides_on_the_return(db):
    """Translating the section must not read as "the line is now complete".
    The 2025-Act statement also wants a numeric payment code 1001-1067 and
    nothing in this repository holds the table."""
    _bill(db, "P-1", NEW_DATE)
    gaps = " ".join(_26q(db, NEW_FY, NEW_Q)["statutory_gaps"])
    assert "1001" in gaps


# ── the helper, and its refusal ──────────────────────────────────────────────

def test_a_section_with_no_2025_code_is_kept_and_named():
    """`vocabulary.section` RAISES on a code it has no mapping for, and a
    return build must not die on one deductee row. The stored code is kept —
    never guessed — and the omission is named beside the payment-code gap."""
    # §192A — TDS on a premature PF withdrawal. A real section, storable in
    # `tds_deductions.tds_section`, and one `_SECTION_2025_ONE_TO_ONE` does not
    # carry: it is not "192" exactly and it does not start with "194".
    labels, gaps = trs._section_labels(NEW_FY, ["194J", "192A"])
    assert labels["194J"] == "393(1)"
    assert labels["192A"] == "192A", "an unmapped section must not be invented"
    assert any("192A" in g for g in gaps)
    assert any("1961" in g for g in gaps)


def test_the_helper_is_silent_for_a_1961_period():
    labels, gaps = trs._section_labels(OLD_FY, ["194J", "194C", "192"])
    assert labels == {"194J": "194J", "194C": "194C", "192": "192"}
    assert gaps == []


def test_the_helper_ignores_blanks():
    labels, gaps = trs._section_labels(NEW_FY, ["", None, "  "])
    assert labels == {} and gaps == []


# ── nothing downstream was rekeyed ───────────────────────────────────────────

def test_the_register_and_the_rate_table_stay_on_1961_keys():
    """CLAUDE.md: translate at the boundary, never rekey a store. `section_rates`
    holds right numbers under 1961-Act keys and stays that way."""
    from domain.tds.section_rates import tds_rates_for
    assert "194J" in tds_rates_for(NEW_FY).sections
    assert "393(1)" not in tds_rates_for(NEW_FY).sections


def test_only_the_statement_dicts_translate():
    """`routers/tds.py` emits `section` twice — the rate preview and the
    section list — and both are the RATE LOOKUP's key, not a statement line.
    Translating either would break the lookup they feed."""
    import inspect
    from routers import tds as m
    src = inspect.getsource(m)
    assert "_section_labels" not in src, (
        "the rate preview and the section list are keyed on the 1961 code; "
        "translating them breaks section_rates")
