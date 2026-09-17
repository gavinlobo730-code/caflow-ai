"""CGST Rule 48(4) — which supplies must be prepared by obtaining an IRN.

SALES-18. `apps/web/lib/invoices/compliance.irnEligibility` was the only
implementation of this rule in the repository; `domain/gst/irn_scope.py` is the
authority now and the browser copy is a pinned mirror.

WHAT THIS MODULE IS FOR, beyond the parity vectors in `test_irn_parity.py`:

  * ⚠️ EVERY THRESHOLD AND EVERY EFFECTIVE DATE IS [S]-GRADED. Direct egress is
    refused at this environment's proxy — `.gov.in` included — so all twelve
    figures were written from knowledge rather than read off the notifications.
    Each is pinned EXACTLY below, so a later correction against the real
    notification is a deliberate edit to a test that says what it is, not a
    drift nobody notices. `VERIFIED` is False in the module for the same reason.

  * THE TWO LIMBS ARE TESTED SEPARATELY, because the module's own header says
    they are facts about different things — one about the client for the year,
    one about this document. A test that only ever exercised them together
    would pass on an implementation that ANDed the wrong pair.
"""
from __future__ import annotations

import inspect

import pytest

from domain.gst import irn_scope
from domain.gst import treatment as gst_treatment


# ── ⚠️ [S]-graded: the notified thresholds, pinned exactly ───────────────────
#
# Written from knowledge. The six steps of Rule 48(4)'s notified class, oldest
# first: (in force from, threshold in paise, notification). If a real reading of
# the notifications disagrees with any row, CHANGE THIS TABLE deliberately —
# it is the record of what was believed, not a restatement of the module.
EXPECTED_THRESHOLDS = [
    ("2020-10-01", 500_00_00_000_00, "Notification 61/2020-Central Tax"),
    ("2021-01-01", 100_00_00_000_00, "Notification 88/2020-Central Tax"),
    ("2021-04-01",  50_00_00_000_00, "Notification 05/2021-Central Tax"),
    ("2022-04-01",  20_00_00_000_00, "Notification 01/2022-Central Tax"),
    ("2022-10-01",  10_00_00_000_00, "Notification 17/2022-Central Tax"),
    ("2023-08-01",   5_00_00_000_00, "Notification 10/2023-Central Tax"),
]


def test_the_six_notified_thresholds_are_exactly_these():
    assert list(irn_scope.THRESHOLDS) == [tuple(r) for r in EXPECTED_THRESHOLDS]


@pytest.mark.parametrize("date,paise,citation", EXPECTED_THRESHOLDS)
def test_each_step_is_in_force_from_its_own_date(date, paise, citation):
    got = irn_scope.threshold_for(date)
    assert got.paise == paise
    assert got.citation == citation


def test_the_thresholds_only_ever_fall():
    """Every step of Rule 48(4)'s class has been downward. A row that raised the
    threshold would take a client OUT of e-invoicing mid-history, which no
    notification has done — so an upward step is far likelier a typo."""
    paise = [p for _, p, _ in irn_scope.THRESHOLDS]
    assert paise == sorted(paise, reverse=True)
    dates = [d for d, _, _ in irn_scope.THRESHOLDS]
    assert dates == sorted(dates)


def test_rupee_figures_are_the_crore_amounts_they_claim_to_be():
    """The paise literals above are easy to get wrong by a factor of ten, and a
    threshold off by 10x is silently wrong in one direction for every client.
    ₹1 crore is 1e7 rupees is 1e9 paise."""
    crore_paise = 1_00_00_000 * 100
    assert irn_scope.threshold_for("2023-08-01").paise == 5 * crore_paise
    assert irn_scope.threshold_for("2022-10-01").paise == 10 * crore_paise
    assert irn_scope.threshold_for("2022-04-01").paise == 20 * crore_paise
    assert irn_scope.threshold_for("2021-04-01").paise == 50 * crore_paise
    assert irn_scope.threshold_for("2021-01-01").paise == 100 * crore_paise
    assert irn_scope.threshold_for("2020-10-01").paise == 500 * crore_paise


def test_commencement_is_the_first_notified_date_and_nothing_applies_before_it():
    """⚠️ [S]. Rule 48(4) was inserted by Notification 68/2019-CT and notified
    its first class from 01-10-2020, so an invoice before that owes no IRN at
    any turnover. `None` means there was no threshold, not that none was
    found — a caller must not read it as zero."""
    assert irn_scope.COMMENCEMENT == "2020-10-01"
    assert irn_scope.THRESHOLDS[0][0] == irn_scope.COMMENCEMENT
    before = irn_scope.threshold_for("2020-09-30")
    assert before.paise is None
    assert "2020-10-01" in before.citation


def test_notification_70_2019s_superseded_hundred_crore_is_not_in_the_table():
    """Notification 70/2019-CT set ₹100 crore from 01-04-2020 and was
    superseded by 13/2020-CT before it ever took effect. No invoice was
    governed by it, so a row for it would govern 2020 invoices by a threshold
    that never applied to them."""
    assert all(d != "2020-04-01" for d, _, _ in irn_scope.THRESHOLDS)
    assert irn_scope.threshold_for("2020-05-01").paise is None


def test_the_module_says_its_figures_are_unverified():
    assert irn_scope.VERIFIED is False


def test_an_absent_date_is_not_a_pre_commencement_date():
    """The two would share a branch if nobody thought about it, and both would
    answer "no threshold" — so an invoice whose date nobody recorded would be
    reported as owing no IRN, which Rule 48(5) makes the expensive direction.
    An absent date takes the STRICTEST (most recent, lowest) threshold instead
    and flags itself."""
    missing = irn_scope.threshold_for("")
    assert missing.date_missing is True
    assert missing.paise == irn_scope.THRESHOLDS[-1][1]

    before = irn_scope.threshold_for("2020-09-30")
    assert before.date_missing is False
    assert before.paise is None

    # And the whole answer goes the safe way, with the gap naming it.
    out = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="", highest_aato_paise=10_00_00_000_00)
    assert out.verdict == "required"
    assert irn_scope.INVOICE_DATE_NOT_RECORDED in out.gaps


def test_an_undated_b2c_invoice_still_reports_nothing():
    """The missing date is named only after the supply limb passes — on a B2C
    invoice the threshold decides nothing, so a missing date decides nothing."""
    out = irn_scope.assess(treatment="regular", recipient_gstin=None,
                           invoice_date="", highest_aato_paise=None)
    assert out.verdict == "not_required"
    assert out.gaps == []


# ── The PERSON limb, on its own ───────────────────────────────────────────────

def test_the_turnover_limb_is_exceeds_not_reaches():
    """The notification's word is "exceeds". A client exactly ON the threshold
    is not above it, and `>=` brings them into e-invoicing a rupee early."""
    at = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                          invoice_date="2026-06-01",
                          highest_aato_paise=5_00_00_000_00)
    over = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                            invoice_date="2026-06-01",
                            highest_aato_paise=5_00_00_000_00 + 1)
    assert at.turnover_exceeds is False and at.verdict == "not_required"
    assert over.turnover_exceeds is True and over.verdict == "required"


def test_an_unrecorded_turnover_is_not_zero_and_the_two_answer_differently():
    """`None` is a third state. 0 is a client who turned over nothing; None is
    nobody having said. GST-17 closed exactly this bug on the HSN side, where a
    defaulted 0 silently told every client HSN was optional."""
    unknown = irn_scope.assess(treatment="regular",
                               recipient_gstin="27AAAAA0000A1Z5",
                               invoice_date="2026-06-01",
                               highest_aato_paise=None)
    nil = irn_scope.assess(treatment="regular",
                           recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="2026-06-01", highest_aato_paise=0)
    assert unknown.verdict == "required" and unknown.turnover_unknown is True
    assert unknown.turnover_exceeds is None
    assert nil.verdict == "not_required" and nil.turnover_unknown is False
    assert nil.turnover_exceeds is False


def test_an_unrecorded_turnover_names_the_gap_rather_than_stating_a_figure():
    out = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="2026-06-01", highest_aato_paise=None)
    assert any(g == irn_scope.TURNOVER_NOT_RECORDED for g in out.gaps)
    assert "2(6)" in irn_scope.TURNOVER_NOT_RECORDED


# ── The PERSON limb RATCHETS: "any preceding financial year from 2017-18" ────

def test_the_qualifying_years_start_at_gsts_own_first_year():
    years = irn_scope.qualifying_financial_years("2026-06-01")
    assert years[0] == irn_scope.FIRST_QUALIFYING_FY == "2017-18"


def test_the_qualifying_years_stop_at_the_PRECEDING_year_never_the_current_one():
    """"any PRECEDING financial year". A client crossing the threshold this
    year comes within the rule next year, so the current FY is not in the set."""
    years = irn_scope.qualifying_financial_years("2026-06-01")   # FY 2026-27
    assert years[-1] == "2025-26"
    assert "2026-27" not in years


def test_a_january_invoice_belongs_to_the_financial_year_that_started_in_april():
    """India's FY runs 1 April to 31 March, so January 2027 is FY 2026-27 and
    its preceding year is still 2025-26 — the same set as June 2026."""
    assert (irn_scope.qualifying_financial_years("2027-01-15")
            == irn_scope.qualifying_financial_years("2026-06-01"))


def test_an_invoice_inside_2017_18_has_no_preceding_year_the_rule_can_reach():
    assert irn_scope.qualifying_financial_years("2017-06-01") == []


def test_the_rule_latches_so_a_client_who_shrank_is_still_within_it():
    """THE DIFFERENCE FROM `hsn_digits`, which reads on the PRECEDING year
    alone. Rule 48(4) reads on ANY preceding year from 2017-18, so a client who
    crossed ₹20 crore once and has turned over ₹4 crore ever since is still
    inside it. The caller passes the HIGHEST recorded figure for exactly this,
    and a caller passing the LATEST would let them out."""
    highest = irn_scope.assess(treatment="regular",
                               recipient_gstin="27AAAAA0000A1Z5",
                               invoice_date="2026-06-01",
                               highest_aato_paise=20_00_00_000_00)
    assert highest.verdict == "required"


def test_the_service_reads_the_max_across_the_qualifying_years_not_the_latest():
    """The other half of the ratchet, at the fetch. A stub `db` returning three
    years with the biggest in the middle: taking the newest row would answer
    ₹4 crore and let the client out of e-invoicing."""
    from services import client_gst_turnover_service as svc

    class _Result:
        def __init__(self, data): self.data = data

    class _Q:
        def __init__(self, rows): self._rows = rows
        def select(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def in_(self, _col, _vals): return self
        def order(self, *_a, **_k): return self
        def execute(self): return _Result(self._rows)

    class _DB:
        def __init__(self, rows): self._rows = rows
        def table(self, name):
            assert name == "client_gst_turnover"
            return _Q(self._rows)

    db = _DB([
        {"financial_year": "2024-25", "aggregate_turnover_paise": 4_00_00_000_00},
        {"financial_year": "2022-23", "aggregate_turnover_paise": 20_00_00_000_00},
        {"financial_year": "2021-22", "aggregate_turnover_paise": 3_00_00_000_00},
    ])
    got = svc.highest_turnover_within_rule_48_4(db, "firm", "client", "2026-06-01")
    assert got == 20_00_00_000_00

    # No row in any qualifying year is None, never 0 — the caller has to be
    # able to tell "nobody said" from "turned over nothing".
    assert svc.highest_turnover_within_rule_48_4(
        _DB([]), "firm", "client", "2026-06-01") is None


# ── The SUPPLY limb, on its own ──────────────────────────────────────────────

@pytest.mark.parametrize("treatment", sorted(gst_treatment.TREATMENTS - {"regular"}))
def test_every_export_sez_and_deemed_export_is_in_scope_with_no_recipient_gstin(treatment):
    """"to a registered person, OR for export". A foreign buyer holds no GSTIN
    and the rule still reaches the invoice, so the treatment is asked BEFORE
    the recipient's registration — collapsing the limb into one GSTIN test
    would take every export out of scope."""
    in_scope, why, gaps = irn_scope.supply_scope(
        treatment=treatment, recipient_gstin=None)
    assert in_scope is True, why
    assert gaps == []


def test_a_regular_supply_to_a_registered_person_is_in_scope():
    in_scope, _, gaps = irn_scope.supply_scope(
        treatment="regular", recipient_gstin="27AAAAA0000A1Z5")
    assert in_scope is True and gaps == []


def test_a_regular_supply_to_an_unregistered_recipient_is_b2c_and_out_of_scope():
    in_scope, why, gaps = irn_scope.supply_scope(
        treatment="regular", recipient_gstin=None)
    assert in_scope is False
    assert "B2C" in why and gaps == []


def test_the_in_scope_treatments_are_derived_from_the_treatment_vocabulary():
    """DERIVED, not listed. A treatment added to `domain/gst/treatment` must
    not quietly default to B2C — the same reason `gstr1_builder` derives its
    B2B set from the classifier rather than spelling it."""
    assert (irn_scope.SUPPLY_IN_SCOPE_TREATMENTS
            == gst_treatment.TREATMENTS - {gst_treatment.REGULAR})
    assert gst_treatment.REGULAR not in irn_scope.SUPPLY_IN_SCOPE_TREATMENTS


def test_the_treatment_is_taken_never_re_derived():
    """`domain/gst/treatment` is the one authority for what kind of supply an
    invoice is (SALES-19). A second derivation here would be exactly the
    disagreement that finding exists to prevent, so this module must not read
    `supply_type` or `invoice_type` at all."""
    src = inspect.getsource(irn_scope)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "supply_type" not in body
    assert "invoice_type" not in body


# ── Registration has three states and the third is named, not guessed ────────

@pytest.mark.parametrize("gstin,state", [
    ("27AAAAA0000A1Z5", "registered"),
    ("27AABCU9603R1ZX", "registered"),
    ("  27aaaaa0000a1z5  ", "registered"),   # trimmed and upper-cased
    (None, "unregistered"),
    ("", "unregistered"),
    ("   ", "unregistered"),
    ("27AAAAA", "malformed"),
    ("not a gstin at all", "malformed"),
    ("27AAAAA0000A1Z5X", "malformed"),       # sixteen characters
])
def test_registration_state_has_exactly_three_answers(gstin, state):
    assert irn_scope.registration_state(gstin) == state


def test_a_malformed_gstin_is_read_as_b2b_and_reported():
    """Reading a mistyped GSTIN as "unregistered" takes the invoice out of the
    supply limb, and Rule 48(5) then voids a document that needed an IRN.
    Fifteen wrong characters are far likelier a real registered customer than a
    walk-in, so it goes the safe way AND says so."""
    in_scope, _, gaps = irn_scope.supply_scope(
        treatment="regular", recipient_gstin="27AAAAA")
    assert in_scope is True
    assert gaps == [irn_scope.GSTIN_MALFORMED]


def test_the_gstin_test_is_shape_only_so_the_browser_mirror_can_agree():
    """This decides B2B-vs-B2C; it is not a human typing a GSTIN into a form,
    which is where the CHECK DIGIT is enforced. A checksum here would put the
    Python and browser copies in disagreement on a transposed digit, which says
    nothing about who the customer is."""
    from domain.gst.gstin import GSTIN_SHAPE, problem_with

    # Well-shaped, wrong check digit: `problem_with` refuses it and the scope
    # test does not, and that difference is deliberate.
    bad_check = "27AAAAA0000A1Z9"
    assert GSTIN_SHAPE.match(bad_check)
    assert problem_with(bad_check) is not None
    assert irn_scope.registration_state(bad_check) == "registered"


# ── The gaps are named where they can change something, and nowhere else ─────

def test_the_exempted_classes_are_named_on_a_required_answer():
    out = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="2026-06-01",
                           highest_aato_paise=10_00_00_000_00)
    assert out.verdict == "required"
    joined = " ".join(out.gaps)
    assert "48(4)" in joined
    for clause in irn_scope.EXEMPTED_CLASSES:
        assert clause in joined


def test_an_sez_unit_as_SUPPLIER_and_a_supply_TO_an_sez_point_opposite_ways():
    """The trap in the exempted-classes list. An SEZ unit is exempt as the
    SUPPLIER; a supply MADE TO an SEZ unit or developer is squarely in scope.
    One is about who issues the invoice and the other about who receives it,
    and reading either for the other inverts the answer."""
    to_an_sez = irn_scope.assess(treatment="sez_with_payment",
                                 recipient_gstin=None,
                                 invoice_date="2026-06-01",
                                 highest_aato_paise=10_00_00_000_00)
    assert to_an_sez.verdict == "required"
    supplier_clause = next(c for c in irn_scope.EXEMPTED_CLASSES if "SEZ" in c.upper())
    assert "supplier" in supplier_clause
    assert "MADE TO" in supplier_clause


def test_an_exemption_is_never_named_on_an_answer_it_could_not_change():
    """An exemption can only REMOVE a requirement, so naming it beside a
    "not required" would send a CA to check a proviso that cannot move the
    answer — and train them to skip it on the case that matters."""
    for kwargs in (
        # B2C: the supply limb fails.
        dict(treatment="regular", recipient_gstin=None,
             highest_aato_paise=1000_00_00_000_00),
        # Below the threshold: the person limb fails.
        dict(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
             highest_aato_paise=1_00_00_000_00),
        # Turned over nothing.
        dict(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
             highest_aato_paise=0),
    ):
        out = irn_scope.assess(invoice_date="2026-06-01", **kwargs)
        assert out.verdict == "not_required"
        assert out.gaps == [], out.gaps


def test_a_b2c_supply_never_reports_on_a_turnover_it_did_not_reach():
    """The supply limb short-circuits. An unrecorded turnover on every B2C
    invoice would bury the clients where it actually decides something."""
    out = irn_scope.assess(treatment="regular", recipient_gstin=None,
                           invoice_date="2026-06-01", highest_aato_paise=None)
    assert out.verdict == "not_required"
    assert out.turnover_unknown is False
    assert out.gaps == []


# ── Shape ────────────────────────────────────────────────────────────────────

def test_the_verdict_vocabulary_has_exactly_two_values_and_both_are_reachable():
    """There is deliberately no "undetermined" here, unlike `eway.assess`:
    every unknown resolves to the strict reading and is flagged instead,
    because Rule 48(5) makes the two errors wildly unequal. A declared value
    nothing can produce invites a caller to handle a case that cannot occur."""
    seen = set()
    for aato in (None, 0, 10_00_00_000_00):
        for gstin in (None, "27AAAAA0000A1Z5"):
            seen.add(irn_scope.assess(treatment="regular", recipient_gstin=gstin,
                                      invoice_date="2026-06-01",
                                      highest_aato_paise=aato).verdict)
    assert seen == {"required", "not_required"}


def test_as_dict_carries_every_field_the_browser_mirror_reads():
    out = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="2026-06-01",
                           highest_aato_paise=10_00_00_000_00).as_dict()
    assert set(out) == {
        "verdict", "supply_in_scope", "supply_reason", "threshold_paise",
        "threshold_citation", "turnover_paise", "turnover_exceeds",
        "turnover_unknown", "reason", "gaps",
    }


def test_it_decides_eligibility_and_reaches_no_portal():
    """PREPARE-ONLY. An IRN comes from the Invoice Registration Portal and is
    recorded here afterwards by a human; nothing in this module may transmit,
    mint an IRN or write anything."""
    src = inspect.getsource(irn_scope)
    for forbidden in ("requests", "httpx", "urlopen", "einvoice1.gst.gov.in",
                      "post(", "supabase", "db.table"):
        assert forbidden not in src, forbidden


def test_the_reason_names_the_rule_and_what_being_wrong_costs():
    """The sentence is half the fix — a CA told "required" with no reason
    cannot tell a rule that was applied from one applied wrongly."""
    out = irn_scope.assess(treatment="regular", recipient_gstin="27AAAAA0000A1Z5",
                           invoice_date="2026-06-01",
                           highest_aato_paise=10_00_00_000_00)
    assert "48(5)" in out.reason
    assert "Notification" in out.reason
    assert "₹" in out.reason
