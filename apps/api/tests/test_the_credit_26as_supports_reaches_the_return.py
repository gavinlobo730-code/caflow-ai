"""IT-31 — the 26AS reconciliation never fed the computation.

The reconciliation produced matched / mismatch / missing counts and an
`unsupported_credit_paise` figure, and nothing wrote a total back:
`ITRComputeRequest.tds_deducted_paise` is a plain input and the computation
screen collected it from a free-text box. A CA who had just run the
reconciliation — and therefore knew exactly which credits were supported —
then retyped the total into a different tab by hand, with no check that the
two agreed.

What these pin is the STATUTE, not the plumbing: Rule 37BA(1) gives credit "on
the basis of information relating to deduction of tax furnished by the
deductor", so the claim is the 26AS figure; TCS is a different schedule; Part C
is the client's own tax and Part D is not a credit at all; and a row that is
not booked FINAL at TRACES has not reached the government.
"""
import pytest

from domain.income_tax.claimable_credit import (
    FINAL_BOOKING_STATUS, RULE_37BA, claimable_from_records,
)


def _r(**kw):
    base = dict(record_type="tds_other", tds_deposited_paise=50_000_00,
                booking_status="F", deductor_name="Acme Ltd", deductor_tan="MUMA12345B")
    base.update(kw)
    return base


# ── what is claimable ────────────────────────────────────────────────────────

def test_a_final_tds_row_is_claimable():
    c = claimable_from_records([_r()])
    assert c.tds_claimable_paise == 50_000_00
    assert c.provisional_paise == 0
    assert c.caveats == []


def test_the_basis_is_rule_37ba_and_it_is_stated():
    assert "37BA(1)" in RULE_37BA
    assert claimable_from_records([_r()]).as_dict()["basis"] == RULE_37BA


@pytest.mark.parametrize("status", ["U", "P", "O", "u", " p ", "", None, "X"])
def test_a_row_that_is_not_booked_final_is_not_claimable(status):
    """'F' means the deductor's statement was matched to a challan actually
    paid. Everything else — including a BLANK, which is missing information
    rather than a settled credit — is reported and excluded. Claiming an
    unmatched credit is what produces a §143(1) intimation with a demand."""
    c = claimable_from_records([_r(booking_status=status)])
    assert c.tds_claimable_paise == 0
    assert c.provisional_paise == 50_000_00
    assert any("not booked final" in g for g in c.caveats)


def test_a_blank_status_says_so_in_its_own_sentence():
    c = claimable_from_records([_r(booking_status="")])
    assert any("no TRACES booking status" in g for g in c.caveats)
    assert any("optimistic reading is" in g for g in c.caveats)


def test_final_is_exactly_f():
    assert FINAL_BOOKING_STATUS == "F"


# ── the four lines of the return ─────────────────────────────────────────────

def test_tcs_is_its_own_figure_and_not_folded_into_tds():
    """§206C(4) credit goes on Schedule TCS. Summing it into the TDS figure
    would put it on the wrong schedule, and the two reconcile against
    different statements at the department's end."""
    c = claimable_from_records([_r(), _r(record_type="tcs_collected",
                                        tds_deposited_paise=2_000_00)])
    assert c.tds_claimable_paise == 50_000_00
    assert c.tcs_claimable_paise == 2_000_00
    assert any("Schedule" in g and "206C" in g for g in c.caveats)


def test_tax_the_client_paid_itself_is_its_own_line():
    """26AS Part C is advance tax and self-assessment. It reduces the same
    liability and belongs on `advance_tax_paid_paise`, not in the TDS claim."""
    c = claimable_from_records([_r(record_type="tax_paid_by_client",
                                   tds_deposited_paise=90_000_00,
                                   booking_status=None)])
    assert c.tds_claimable_paise == 0
    assert c.tax_paid_by_client_paise == 90_000_00
    # And no booking status is required of it — the client holds the challan.
    assert c.provisional_paise == 0


def test_a_refund_already_received_is_not_a_credit():
    c = claimable_from_records([_r(record_type="refund_received",
                                   tds_deposited_paise=5_000_00)])
    assert c.tds_claimable_paise == 0
    assert c.refund_already_received_paise == 5_000_00
    assert c.provisional_paise == 0


def test_salary_tds_is_claimable_even_though_the_books_cannot_see_it():
    """`_load_book_credits` reads `receipts` — tax a CUSTOMER withheld — so a
    salaried client's §192 credit has no books counterpart and the
    reconciliation reports it 'missing in books' for ever. The claim is read
    off 26AS, where the credit actually is."""
    c = claimable_from_records([_r(record_type="tds_salary",
                                   tds_deposited_paise=1_20_000_00)])
    assert c.tds_claimable_paise == 1_20_000_00


def test_an_unclassified_part_is_named_and_never_claimed():
    c = claimable_from_records([_r(record_type="something_new",
                                   tds_deposited_paise=7_000_00)])
    assert c.tds_claimable_paise == 0
    assert any("could not classify" in g for g in c.caveats)


# ── the per-deductor schedule ────────────────────────────────────────────────

def test_the_schedule_is_per_deductor_and_carries_the_tan():
    c = claimable_from_records([
        _r(deductor_name="Acme Ltd", deductor_tan="MUMA12345B", tds_deposited_paise=50_000_00),
        _r(deductor_name="Acme Ltd", deductor_tan="MUMA12345B", tds_deposited_paise=10_000_00,
           booking_status="U"),
        _r(deductor_name="Beta LLP", deductor_tan="DELB99999C", tds_deposited_paise=80_000_00),
    ])
    by_name = {d.deductor_name: d for d in c.by_deductor}
    assert by_name["Acme Ltd"].claimable_paise == 50_000_00
    assert by_name["Acme Ltd"].provisional_paise == 10_000_00
    assert by_name["Acme Ltd"].entry_count == 2
    assert by_name["Acme Ltd"].deductor_tan == "MUMA12345B"
    # Largest claim first — Schedule TDS-2 is worked from the top.
    assert c.by_deductor[0].deductor_name == "Beta LLP"


def test_tds_and_tcs_from_one_party_are_separate_lines():
    c = claimable_from_records([
        _r(deductor_name="Trader", tds_deposited_paise=10_000_00),
        _r(deductor_name="Trader", record_type="tcs_collected", tds_deposited_paise=3_000_00),
    ])
    kinds = sorted(d.kind for d in c.by_deductor)
    assert kinds == ["tcs", "tds"]


def test_a_deductor_with_no_name_is_labelled_not_left_blank():
    c = claimable_from_records([_r(deductor_name="", deductor_tan=None)])
    assert c.by_deductor[0].deductor_name == "(deductor not named)"


def test_the_figures_in_the_caveats_are_indian_grouped():
    c = claimable_from_records([_r(tds_deposited_paise=12_34_567_00, booking_status="U")])
    assert "₹12,34,567" in c.caveats[0]
    assert "1,234,567" not in c.caveats[0]


def test_no_records_is_a_clean_nil_and_not_a_crash():
    c = claimable_from_records([])
    assert c.tds_claimable_paise == 0 and c.by_deductor == [] and c.caveats == []


# ── the service and the endpoint ─────────────────────────────────────────────

def test_a_year_with_no_parsed_26as_refuses_rather_than_answering_zero(monkeypatch):
    """Nobody having uploaded the statement and the client having no credit are
    OPPOSITE facts. A prefilled 0 would quietly become a filed 0."""
    from domain.income_tax import form26as_service as svc
    monkeypatch.setattr(svc, "list_uploads", lambda *a, **k: [])
    out = svc.claimable_credit("f1", "c1", "2025-26")
    assert out["available"] is False
    assert "TRACES" in out["reason"] and "2025-26" in out["reason"]
    assert "tds_claimable_paise" not in out


def test_an_unparsed_upload_does_not_count(monkeypatch):
    from domain.income_tax import form26as_service as svc
    monkeypatch.setattr(svc, "list_uploads",
                        lambda *a, **k: [{"id": "u1", "parse_status": "pending"}])
    assert svc.claimable_credit("f1", "c1", "2025-26")["available"] is False


def test_the_claim_names_which_statement_it_came_off(monkeypatch):
    """A prefilled number whose provenance is invisible is one a reviewer
    cannot check."""
    from domain.income_tax import form26as_service as svc
    monkeypatch.setattr(svc, "list_uploads", lambda *a, **k: [
        {"id": "u1", "parse_status": "parsed", "created_at": "2026-07-01T00:00:00Z"}])
    monkeypatch.setattr(svc, "_load_records", lambda f, u: [_r()])
    out = svc.claimable_credit("f1", "c1", "2025-26")
    assert out["available"] is True
    assert out["upload_id"] == "u1"
    assert out["uploaded_at"] == "2026-07-01T00:00:00Z"
    assert out["record_count"] == 1
    assert out["tds_claimable_paise"] == 50_000_00


def test_the_reconciliation_response_carries_the_same_claim(monkeypatch):
    """One derivation, two places. A second computation of the claim is how
    the panel and the working paper come to disagree."""
    from domain.income_tax import form26as_service as svc
    monkeypatch.setattr(svc, "_load_records", lambda f, u: [
        _r(id="r1"),
        _r(id="r2", record_type="tax_paid_by_client", tds_deposited_paise=90_000_00,
           booking_status=None)])
    monkeypatch.setattr(svc, "_load_book_credits", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_gl_control_paise", lambda *a, **k: 0)
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    out = svc.run_reconciliation("f1", "c1", "u1", "2025-26", "me")
    assert out["claimable"]["tds_claimable_paise"] == 50_000_00
    assert out["claimable"]["tax_paid_by_client_paise"] == 90_000_00


def test_the_claim_is_reported_beside_the_summary_never_inside_it(monkeypatch):
    """`summary` is spread straight into the form_26as_reconciliations INSERT,
    so a key that is not a column of that table fails the whole reconciliation
    on the live database while passing in mock mode — the exact shape migration
    291 was written to repair on this same table.

    Asserted against the STORED ROW, not against `summarise`'s return. A first
    draft checked `summarise([], [], 0)` and passed happily with the claim
    added to `summary` one line later in `run_reconciliation`, which is where
    it would actually reach the INSERT.
    """
    from domain.income_tax import form26as_service as svc
    monkeypatch.setattr(svc, "_load_records", lambda f, u: [_r(id="r1")])
    monkeypatch.setattr(svc, "_load_book_credits", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_gl_control_paise", lambda *a, **k: 0)
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    svc._MOCK_RECONS.clear()
    out = svc.run_reconciliation("f1", "c1", "u1", "2025-26", "me")

    stored = list(svc._MOCK_RECONS.values())[-1]
    for key in ("claimable", "not_a_tds_credit", "not_a_tds_credit_paise"):
        assert key not in stored, (
            f"{key} would be sent as a column of form_26as_reconciliations")
    # And it IS on the response, which is the whole point of the aside.
    assert "claimable" in out and "not_a_tds_credit" in out

    _result, summary = svc.summarise([], [], 0)
    assert "claimable" not in summary
