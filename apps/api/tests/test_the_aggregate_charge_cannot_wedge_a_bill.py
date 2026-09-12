"""The FY-aggregate charge, at its edges.

Moving the TDS charge onto the financial-year aggregate was right — s.194C(5)
and its neighbours charge on "the aggregate of the amounts" — and it introduced
three edges the marginal-bill version never had. All three are here because all
three reached `main` before anyone noticed.
"""
from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

import routers.purchase_bills as pb
from domain.tds.residency import GAP_TDS_IS_A_FY_CATCH_UP
from domain.tds.section_rates import tds_rates_for
from domain.tds.tds_computer import TDSComputer
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"


@pytest.fixture()
def books():
    mp = MonkeyPatch()
    db = FakeDB()
    wire_e2e(mp, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "V", "firm_id": FIRM, "client_id": "CLI", "name": "Pro",
                        "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": True,
                        "tds_section": "194J", "tds_rate_bps": 1000})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "S1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Audit", "kind": "service"})
    try:
        yield db
    finally:
        mp.undo()


class _Payload:
    def __init__(self, bills):
        self.bills = bills


def _bill(no: str, rate_paise: int) -> dict:
    return PurchaseBillIn(
        client_id="CLI", vendor_id="V", bill_date="2026-04-05", bill_no=no,
        lines=[PurchaseBillLineIn(description="Audit", hsn_sac="9982", quantity=1,
                                  rate_paise=rate_paise, gst_rate_percent=18.0,
                                  service_catalogue_id="S1")],
    ).model_dump()


# ── the wedge ────────────────────────────────────────────────────────────────

def test_the_crossing_bill_never_produces_a_negative_payable(books):
    """A deduction is made FROM a payment and cannot exceed it.

    That was academic while the charge fell on the marginal bill (tds was at
    most 20% of the taxable value) and became real when it moved to the
    aggregate. A §194J vendor billing ₹49,000 then ₹2,000 owes ₹5,100 on the
    ₹51,000 aggregate against a ₹2,360 bill, and `net_payable_paise` went to
    -₹3,100. The kernel credits Trade Payables with exactly that figure, against
    `journal_lines CHECK (credit_paise >= 0)` — the entry still BALANCES, so the
    assertion inside _create_journal passed and mock mode wrote it happily,
    while production answered 23514 and left the bill a draft for ever.
    """
    resp = pb.bulk_create_purchase_bills(
        _Payload([_bill("A", 49_000_00), _bill("B", 2_000_00)]), CALLER)

    created = resp["data"]["created"]
    assert [b["net_payable_paise"] for b in created] == [57_820_00, 0]
    assert created[1]["tds_paise"] == 2_360_00, "capped at the bill, not ₹5,100"
    for b in created:
        assert b["net_payable_paise"] >= 0
        assert b["tds_paise"] <= b["total_paise"]


def test_the_shortfall_is_recovered_from_the_next_bill(books):
    """Capping must not FORGIVE the balance.

    Nothing records the shortfall, and nothing needs to: fy_prior_tds_paise
    sums what earlier bills ACTUALLY withheld, so the next bill re-charges the
    difference by the same §200 credit that stops the aggregate being taxed
    twice. The year comes out exact.
    """
    resp = pb.bulk_create_purchase_bills(
        _Payload([_bill("A", 49_000_00), _bill("B", 2_000_00), _bill("C", 50_000_00)]),
        CALLER)

    created = resp["data"]["created"]
    aggregate = 49_000_00 + 2_000_00 + 50_000_00
    assert sum(b["tds_paise"] for b in created) == aggregate * 1000 // 10000
    assert [b["tds_paise"] for b in created] == [0, 2_360_00, 7_740_00]


# ── the draft question, settled the other way ────────────────────────────────

def test_a_draft_counts_in_BOTH_limbs_because_it_counts_in_the_charge_base():
    """It was argued that §200 credits only tax "deducted and paid", so a draft
    — which has no journal, challan or register row — should be left out of
    fy_prior_tds_paise. Read alone that is right about §200 and wrong about this
    code, because the CHARGE BASE counts drafts too.

    Bill A received (₹1,00,000, ₹10,000 withheld), bill B a live draft
    (₹1,00,000), bill C now created (₹1,00,000). Crediting A and B withholds
    ₹10,000 on C, so the ledger holds ₹20,000 against the ₹2,00,000 actually
    credited. Crediting A alone withholds ₹20,000 and the ledger holds ₹30,000
    against the same ₹2,00,000 — an OVER-deduction recoverable only by a refund
    claim. The draft appears on both sides and cancels; excluding it from one
    side is what breaks it.
    """
    lakh = 1_00_000_00
    both = TDSComputer().resolve_tds("194J", lakh, fy_prior_taxable_paise=2 * lakh,
                                     fy_prior_tds_paise=2 * 10_000_00, fy=FY)
    received_only = TDSComputer().resolve_tds("194J", lakh, fy_prior_taxable_paise=2 * lakh,
                                              fy_prior_tds_paise=10_000_00, fy=FY)

    due_on_what_was_actually_credited = 2 * lakh * 1000 // 10000
    assert 10_000_00 + both.tds_paise == due_on_what_was_actually_credited
    assert 10_000_00 + received_only.tds_paise > due_on_what_was_actually_credited


# ── the four sections left behind ────────────────────────────────────────────

@pytest.mark.parametrize("section, limit, each", [
    ("193", 10_000_00, 4_000_00),      # interest on securities
    ("194", 10_000_00, 4_000_00),      # dividends
    ("194K", 10_000_00, 4_000_00),     # mutual-fund income
    ("194LA", 5_00_000_00, 2_00_000_00),  # compulsory acquisition compensation
])
def test_the_four_remaining_aggregate_sections_charge_on_the_year(section, limit, each):
    """Each of these carries "or, as the case may be, the aggregate of the
    amounts" in its own proviso, and each was left without the limb when
    §§194A/194D/194G/194H/194J got one — while the module docstring said only
    two sections deliberately had none. Undecided documented as deliberate is
    the worse half of that.
    """
    c = TDSComputer()
    prior_taxable = prior_tds = 0
    for _ in range(4):
        r = c.resolve_tds(section, each, fy_prior_taxable_paise=prior_taxable,
                          fy_prior_tds_paise=prior_tds, fy=FY)
        prior_taxable += each
        prior_tds += r.tds_paise

    assert prior_taxable > limit, "the scenario must actually cross the limit"
    assert prior_tds == prior_taxable * 1000 // 10000


def test_only_these_sections_have_no_aggregate_and_each_has_a_reason():
    """§194I's limit is per month or part of a month, FA 2025 made §194B's per
    single transaction, §192 is a sentinel (salary is slab-based) and §206C is
    reference data no computation reads. An FY aggregate on 194I or 194B would
    deduct where the statute does not charge.

    §194I's two CLAUSES inherit its answer — the per-month limit is the
    section's, not the clause's — while §194J's carry their parent's ₹50,000
    aggregate. That asymmetry is the point of listing them: a limb added with
    the wrong one silently changes when the charge starts.
    """
    rules = tds_rates_for(FY).sections
    assert sorted(k for k, v in rules.items()
                  if v.aggregate_threshold_paise is None) == [
        "192", "194B", "194I", "194I(A)", "194I(B)", "206C"]
    for limb in ("194J(A)", "194J(B)"):
        assert rules[limb].aggregate_threshold_paise == rules["194J"].aggregate_threshold_paise


# ── the 26Q row that does not multiply out ───────────────────────────────────

def test_the_catch_up_row_says_its_columns_do_not_multiply_out():
    """Form 26Q's deductee annexure asks for the amount paid on this date, the
    rate deducted under, and the tax deducted. On the crossing bill those are
    ₹2,000, 10% and ₹5,100 — each individually right, and they do not close.

    Restating any one of them to make the arithmetic work would put a figure in
    the return that is not what happened, so the row keeps all three and names
    the gap instead.
    """
    import inspect

    from domain.tds.residency import GAP_MESSAGES
    from services import tds_register_service as reg

    # Every gap code must carry a sentence a CA can act on — residency.py's own
    # test enforces that, and this one checks the sentence says the right thing.
    assert GAP_TDS_IS_A_FY_CATCH_UP in GAP_MESSAGES
    msg = GAP_MESSAGES[GAP_TDS_IS_A_FY_CATCH_UP]
    assert "aggregate" in msg and "will NOT equal" in msg

    # And that the register actually raises it, rather than the code existing
    # unused — which is how a gap vocabulary rots.
    src = inspect.getsource(reg)
    assert "gaps.append(GAP_TDS_IS_A_FY_CATCH_UP)" in src
