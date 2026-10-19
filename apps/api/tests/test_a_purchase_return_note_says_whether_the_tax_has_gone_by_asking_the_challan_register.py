"""A note on a purchase return says whether the tax has gone by asking the challan register (POST-A-271).

WHAT WAS WRONG
    When a purchase return or a supplier's undercharge note stands against a bill the tax was already withheld on, the
    quarter's statement carries one sentence naming which of two lawful answers applies: the tax has not gone, so the
    deduction may still be recomputed, or it has, so the deduction stands and the deductor carries an excess. The 26Q and
    27Q builders handed the sentence writer no deposit fact at all, and an absent fact resolved to "not yet deposited", so
    every note in a quarter whose tax HAD been deposited was told it had not. (The register's own copy of the sentence read
    two columns of `tds_deductions` that nothing writes, and was thrown away: only a gap code left that function.)

WHAT IS HELD
    * `position` is a REQUIRED argument of the sentence writer, and the 26Q and 27Q builders hand it each bill's position
      from the challan match the statement has already made, so the sentence is built from the same match as the deductee
      row beside it. They differ in one case, deliberately: a challan dated before the deduction is counted as deposit by
      the row and not by the sentence, which says so;
    * a deduction wholly matched to challans dated on or after it is "deposited" and the sentence names the last date; one
      partly matched says how much has gone and how much has not and decides nothing; one the register matched to a challan
      dated before the tax was deducted, and not fully paid by others, "cannot be told"; one nothing was matched to says the
      books record no challan, and that a payment made outside the product would change it;
    * a note that RAISES what stands credited says the deduction may be SHORT, whether or not the tax went;
    * the rule that dates a part is `challan_mapping.dated_parts`, the one the deposit worksheet uses for interest.
"""
from __future__ import annotations

from datetime import date

import pytest

import domain.tds.purchase_return as pr
from domain.tds import challan_mapping
from domain.tds.challan_mapping import Assignment

from tests.test_a_purchase_return_after_the_tax_was_withheld import VENDOR, _BooksDB, _bill


TAX = 50_000_00
PAID_IN_FULL = pr.deposit_position(TAX, [(TAX, date(2025, 11, 7))])
NOTHING_PAID = pr.deposit_position(TAX, [])
A_CHALLAN_BEFORE_THE_BILL = pr.deposit_position(TAX, [], True)


def _challan(no="C1", paid="2025-11-07", tds=50_000_00, section="194J", surcharge=0, ident=None):
    return {"id": ident or f"id-{no}", "challan_no": no, "payment_date": paid, "tds_paise": tds, "surcharge_paise": surcharge,
            "section": section, "financial_year": "2025-26", "quarter": "Q3", "bsr_code": "0000000"}


# ── the position of one deduction ───────────────────────────────────────────

def test_a_position_counts_what_the_challans_paid_and_the_latest_date_and_never_more_than_the_tax():
    p = pr.deposit_position(50_000_00, [(30_000_00, date(2025, 11, 7)), (30_000_00, date(2025, 12, 7))])
    assert (p.tax_paise, p.deposited_paise, p.last_paid_on, p.refused_before_deduction) == (
        50_000_00, 50_000_00, date(2025, 12, 7), False), "capped at the tax: a challan cannot pay more than was withheld"
    none = pr.deposit_position(50_000_00, [], True)
    assert (none.deposited_paise, none.last_paid_on, none.refused_before_deduction) == (0, None, True)


@pytest.mark.parametrize("deposited, expect", [(50_000_00, pr.DEPOSIT_MADE), (30_000_00, pr.DEPOSIT_PARTLY),
                                               (0, pr.DEPOSIT_NOT_MADE)])
def test_the_registers_position_decides_the_state(deposited, expect):
    parts = [(deposited, date(2025, 11, 7))] if deposited else []
    assert pr.deposit_state(position=pr.deposit_position(50_000_00, parts)) == expect


def test_a_challan_dated_before_the_deduction_is_not_proof_and_says_it_cannot_be_told():
    position = pr.deposit_position(50_000_00, [], refused=True)
    assert pr.deposit_state(position=position) == pr.DEPOSIT_UNRECORDED
    m = pr.credit_moved_after_deduction(bill_no="BILL-7", section="194J", credited_paise=5_00_000_00, tds_paise=50_000_00,
                                        returned_taxable_paise=2_00_000_00, position=position)
    assert "dated before the tax was deducted" in m.sentence and "cannot be told from the books" in m.sentence
    assert "has not been paid over" not in m.sentence


def test_the_state_follows_what_the_register_matched_and_an_unknown_is_never_unpaid():
    full = pr.deposit_position(TAX, [(TAX, date(2025, 11, 7))])
    part = pr.deposit_position(TAX, [(30_000_00, date(2025, 11, 7))])
    assert pr.deposit_state(full) == pr.DEPOSIT_MADE
    assert pr.deposit_state(part) == pr.DEPOSIT_PARTLY
    assert pr.deposit_state(pr.deposit_position(TAX, [])) == pr.DEPOSIT_NOT_MADE
    assert pr.deposit_state(None) == pr.DEPOSIT_UNRECORDED, "no position could be made: an unknown, not 'unpaid'"
    # a challan dated before the deduction: not proof of anything, whether or not another challan paid part
    assert pr.deposit_state(pr.deposit_position(TAX, [], True)) == pr.DEPOSIT_UNRECORDED
    assert pr.deposit_state(pr.deposit_position(TAX, [(20_000_00, date(2025, 11, 7))], True)) == pr.DEPOSIT_UNRECORDED, (
        "₹30,000 was matched to a challan that cannot be right: the other ₹20,000 paid is known, the rest is UNKNOWN and "
        "must not read 'has not been paid over'")
    # but when valid challans paid all of it, a refused one beside them changes nothing
    assert pr.deposit_state(pr.deposit_position(TAX, [(TAX, date(2025, 11, 7))], True)) == pr.DEPOSIT_MADE


def _sentence(position):
    return pr.credit_moved_after_deduction(bill_no="BILL-7", section="194J", credited_paise=5_00_000_00, tds_paise=50_000_00,
                                           returned_taxable_paise=2_00_000_00, position=position)


def test_a_wholly_deposited_deduction_says_it_stands_and_names_the_last_challan_date():
    m = _sentence(pr.deposit_position(50_000_00, [(20_000_00, date(2025, 11, 7)), (30_000_00, date(2025, 12, 9))]))
    assert m.deposit_state == pr.DEPOSIT_MADE
    assert "paid over on 2025-12-09" in m.sentence and "The deduction STANDS" in m.sentence
    assert "RECOMPUTED" not in m.sentence


def test_a_part_deposited_deduction_says_how_much_has_gone_and_how_much_has_not_and_decides_nothing():
    m = _sentence(pr.deposit_position(50_000_00, [(30_000_00, date(2025, 11, 7))]))
    assert m.deposit_state == pr.DEPOSIT_PARTLY
    assert "₹30,000 of the ₹50,000 withheld went by 2025-11-07" in m.sentence and "₹20,000 has not" in m.sentence
    # it names the two answers and says the deduction is part of each; it does NOT say which part gets which
    assert "excess deposit" in m.sentence and "recomputed on ₹3,00,000" in m.sentence and "part of each" in m.sentence
    assert "is a CA's decision and is not settled by the books" in m.sentence
    assert "Nothing here adjusts the register" in m.sentence
    assert "has not been paid over" not in m.sentence
    assert "For the part paid over" not in m.sentence, "an unconfirmed legal reading must not be stated as fact (POST-C-206)"


def test_a_deduction_with_a_challan_that_cannot_be_right_beside_a_valid_one_does_not_say_the_rest_has_not_gone():
    """₹30,000 matched to a challan dated before the deduction, ₹20,000 to a valid one. The sentence used to read '₹20,000 of
    the ₹50,000 went ... ₹30,000 has not'; the ₹30,000 is unknown, not unpaid."""
    m = _sentence(pr.deposit_position(50_000_00, [(20_000_00, date(2025, 11, 7))], True))
    assert m.deposit_state == pr.DEPOSIT_UNRECORDED
    assert "cannot be told from the books" in m.sentence and "dated before the tax was deducted" in m.sentence
    assert "has not" not in m.sentence.split("cannot be told")[1].split("Record")[0].replace("it is not counted", "")


def test_a_note_that_raises_the_credit_says_the_deduction_may_be_short_in_every_state():
    """An increase gives no excess deposit: it can only leave the deduction short, whatever the challans paid."""
    for position in (NOTHING_PAID, PAID_IN_FULL, pr.deposit_position(TAX, [(30_000_00, date(2025, 11, 7))]),
                     A_CHALLAN_BEFORE_THE_BILL, None):
        m = pr.credit_moved_after_deduction(bill_no="BILL-7", section="194J", credited_paise=5_00_000_00, tds_paise=TAX,
                                            increased_taxable_paise=1_00_000_00, position=position)
        assert "SHORT" in m.sentence and "201(1A)" in m.sentence and "₹6,00,000" in m.sentence
        assert "excess deposit" not in m.sentence and "RECOMPUTED" not in m.sentence
    # a return that outweighs an undercharge note still gets the two answers
    both = pr.credit_moved_after_deduction(bill_no="B", section="194J", credited_paise=5_00_000_00, tds_paise=TAX,
                                           returned_taxable_paise=2_00_000_00, increased_taxable_paise=50_000_00,
                                           position=PAID_IN_FULL)
    assert "STANDS" in both.sentence and "SHORT" not in both.sentence


def test_tax_is_stated_to_the_paisa_so_the_two_parts_of_a_part_paid_deduction_add_up():
    """₹72.80 withheld read "₹72" (whole rupees, truncated), and a challan of ₹28.50 beside it left ₹44 unaccounted for."""
    m = pr.credit_moved_after_deduction(bill_no="RAV/0014", section="194C", credited_paise=3_640_00, tds_paise=72_80,
                                        returned_taxable_paise=1_000_00,
                                        position=pr.deposit_position(72_80, [(28_50, date(2025, 10, 7))]))
    assert "₹72.80 withheld" in m.sentence and "₹28.50 of the ₹72.80 withheld" in m.sentence
    assert "₹44.30 has not" in m.sentence
    whole = pr.credit_moved_after_deduction(bill_no="B", section="194C", credited_paise=3_640_00, tds_paise=72_00,
                                            returned_taxable_paise=1_000_00, position=NOTHING_PAID)
    assert "₹72 withheld" in whole.sentence and "₹72.00" not in whole.sentence, "a whole figure stays whole"


def test_a_deduction_with_nothing_deposited_still_says_it_may_be_recomputed():
    m = _sentence(pr.deposit_position(50_000_00, []))
    assert m.deposit_state == pr.DEPOSIT_NOT_MADE and "has not been paid over" in m.sentence
    assert "as far as they show" in m.sentence and "outside this product" in m.sentence


# ── the one rule that dates a part ──────────────────────────────────────────

def test_the_rule_that_dates_a_part_is_shared_and_refuses_what_cannot_be_right():
    a = Assignment(challan=_challan(), deposited_paise=50_000_00, parts=(
        (_challan("A", "2025-11-07", ident="a"), 10_000_00),      # counted
        (_challan("B", "2025-10-01", ident="b"), 10_000_00),      # dated before the deduction: refused
        ({**_challan("C", None, ident="c")}, 10_000_00),          # no date: nothing to say when
        (_challan("D", "2025-12-01T10:30:00+00:00", ident="d"), 20_000_00)))
    parts, refused = challan_mapping.dated_parts(a, date(2025, 10, 25))
    assert parts == [(10_000_00, date(2025, 11, 7)), (20_000_00, date(2025, 12, 1))] and refused is True
    assert challan_mapping.dated_parts(Assignment(), date(2025, 10, 25)) == ([], False)
    assert challan_mapping.dated_parts(a, date(2025, 11, 7))[0][0] == (10_000_00, date(2025, 11, 7)), "the same day counts"


@pytest.mark.parametrize("challans, expect_state, expect_outstanding_paise", [
    ([("2025-11-07", 50_000_00)], pr.DEPOSIT_MADE, 0),
    ([("2025-11-07", 20_000_00), ("2025-12-09", 30_000_00)], pr.DEPOSIT_MADE, 0),
    ([("2025-11-07", 30_000_00)], pr.DEPOSIT_PARTLY, 20_000_00),
    ([], pr.DEPOSIT_NOT_MADE, 50_000_00),
    ([("2025-10-25", 50_000_00)], pr.DEPOSIT_MADE, 0),                       # the same day counts
    ([("2025-10-01", 50_000_00)], pr.DEPOSIT_UNRECORDED, 50_000_00),         # dated before the deduction
])
def test_the_worksheet_and_the_note_agree_about_one_deduction(challans, expect_state, expect_outstanding_paise):
    """The deposit worksheet states what is still outstanding (and charges interest on it) and the note says whether the
    tax has gone. Both go through `challan_mapping.dated_parts`, and this holds them to agreeing on the same deduction."""
    from domain.tds import deposit_due
    row = {"id": "d1", "section": "194J", "transaction_date": "2025-10-25", "tds_paise": TAX, "surcharge_paise": 0,
           "cess_paise": 0, "payment_amount_paise": 5_00_000_00, "deductee_name": "Pinnacle"}
    chl = [_challan(no=f"C{i}", paid=paid, tds=paise) for i, (paid, paise) in enumerate(challans)]
    mapping = deposit_due.mapping_from_register([row], chl, fy="2025-26")
    sheet = deposit_due.build([row], month="2025-10", due_date=date(2025, 11, 7), as_at=date(2026, 3, 1), deposits=mapping)
    parts, refused = challan_mapping.dated_parts(mapping.for_deduction("d1"), date(2025, 10, 25))
    state = pr.deposit_state(pr.deposit_position(TAX, parts, refused))
    assert (state, sheet.totals["outstanding_paise"]) == (expect_state, expect_outstanding_paise)


def test_a_challan_whose_payment_date_is_a_timestamp_is_dated_by_its_day_and_never_a_type_error():
    """`as_date` handed a datetime back unchanged and `dated_parts` then compared it with a date: a warning sentence
    aborted the whole statement build."""
    from datetime import datetime, timezone
    a = Assignment(parts=((_challan("A", None, ident="a") | {"payment_date": datetime(2025, 11, 7, 18, 30, tzinfo=timezone.utc)}, 10_00),))
    assert challan_mapping.dated_parts(a, date(2025, 10, 25)) == ([(10_00, date(2025, 11, 7))], False)
    assert challan_mapping.as_date(datetime(2025, 11, 7, 1, 0)) == date(2025, 11, 7)
    assert challan_mapping.as_date("2025-11-07T18:30:00+00:00") == date(2025, 11, 7) and challan_mapping.as_date("None") is None


# ── the quarter's statement asks the register ───────────────────────────────

class _RegisterBooksDB(_BooksDB):
    """The books double of the note's other tests, serving the quarter's challans as well."""

    def __init__(self, bills, vendors, debit_notes=(), challans=()):
        super().__init__(bills, vendors, debit_notes, ())
        self._challans = list(challans)

    def execute(self):
        if self._t == "tds_challans":
            return type("R", (), {"data": list(self._challans)})()
        return super().execute()


def _26q(bills, vendors, challans=(), notes=None):
    from services.tds_return_service import tds_26q_from_books
    notes = notes if notes is not None else [{"purchase_bill_id": b["id"], "taxable_amount_paise": 2_00_000_00,
                                              "status": "issued", "deleted_at": None} for b in bills]
    return tds_26q_from_books(_RegisterBooksDB(bills, vendors, notes, challans), "f1", "c1", "2025-26", "Q3",
                              "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")


def _named(out, bill_no="BILL-7"):
    found = [g for g in out["statutory_gaps"] if bill_no in g]
    assert len(found) == 1, found
    return found[0]


def test_a_note_on_a_bill_whose_tax_a_challan_paid_is_told_the_deduction_stands():
    """The defect: this read "has not been paid over ... recomputed" with the tax already with the department."""
    sentence = _named(_26q([_bill()], [VENDOR], challans=[_challan()]))
    assert "paid over on 2025-11-07" in sentence
    assert "has not been paid over" not in sentence and "RECOMPUTED" not in sentence


def test_a_note_on_a_bill_with_no_challan_is_still_told_it_may_be_recomputed():
    sentence = _named(_26q([_bill()], [VENDOR]))
    assert "has not been paid over" in sentence and "RECOMPUTED" in sentence


def test_a_short_challan_leaves_the_bill_part_paid_and_the_sentence_says_so():
    sentence = _named(_26q([_bill()], [VENDOR], challans=[_challan(tds=30_000_00)]))
    assert "only partly paid over" in sentence and "₹30,000 of the ₹50,000" in sentence and "₹20,000 has not" in sentence


def test_a_challan_dated_before_the_bill_is_not_counted_and_the_sentence_says_it_cannot_be_told():
    sentence = _named(_26q([_bill()], [VENDOR], challans=[_challan(paid="2025-10-01")]))
    assert "dated before the tax was deducted" in sentence and "cannot be told" in sentence
    assert "has not been paid over" not in sentence


def test_two_bills_of_a_quarter_are_told_apart_first_in_first_out():
    """One challan pays the earlier bill; the later bill has nothing matched, exactly as the statement's own deductee rows."""
    earlier = _bill(id="b1", bill_no="BILL-1", bill_date="2025-10-05")
    later = _bill(id="b2", bill_no="BILL-2", bill_date="2025-10-25")
    out = _26q([earlier, later], [VENDOR], challans=[_challan(paid="2025-11-07", tds=50_000_00)])
    assert "paid over on 2025-11-07" in _named(out, "BILL-1")
    assert "has not been paid over" in _named(out, "BILL-2")


def test_a_challan_typed_under_the_other_limb_of_the_section_still_pays_the_bill():
    """A CA types 194J whichever limb the bill was under: the match groups by the parent section."""
    sentence = _named(_26q([_bill(tds_section="194J(B)")], [VENDOR], challans=[_challan(section="194J")]))
    assert "paid over on 2025-11-07" in sentence


def test_a_bill_with_no_date_to_compare_a_challan_with_is_told_it_cannot_be_told_and_not_that_it_is_unpaid():
    sentence = _named(_26q([_bill(bill_date=None)], [VENDOR], challans=[_challan()]))
    assert "cannot be told from the books" in sentence and "has not been paid over" not in sentence


def test_a_note_that_raises_the_credit_is_told_the_deduction_may_be_short_through_the_statement():
    notes = [{"purchase_bill_id": "b1", "taxable_amount_paise": 1_00_000_00, "status": "issued", "deleted_at": None}]
    from services.tds_return_service import tds_26q_from_books
    db = _RegisterBooksDB([_bill()], [VENDOR], [], [_challan()])
    db._cn = notes
    out = tds_26q_from_books(db, "f1", "c1", "2025-26", "Q3", "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")
    sentence = _named(out)
    assert "SHORT" in sentence and "excess deposit" not in sentence


def test_the_non_resident_statement_asks_the_register_too():
    from services.tds_return_service import tds_27q_from_books
    nri = {**VENDOR, "id": "v1", "residential_status": "non_resident", "country_of_residence": "SG",
           "tax_identification_number": "SG-1", "pan": None}
    bill = _bill(tds_section="195")
    notes = [{"purchase_bill_id": "b1", "taxable_amount_paise": 2_00_000_00, "status": "issued", "deleted_at": None}]
    paid = tds_27q_from_books(_RegisterBooksDB([bill], [nri], notes, [_challan(section="195")]), "f1", "c1", "2025-26",
                              "Q3", "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")
    unpaid = tds_27q_from_books(_RegisterBooksDB([bill], [nri], notes, []), "f1", "c1", "2025-26", "Q3", "MUMP12345A",
                                "Client Pvt Ltd", "AAACC1111C", "Mumbai")
    assert "paid over on 2025-11-07" in _named(paid)
    assert "has not been paid over" in _named(unpaid)
