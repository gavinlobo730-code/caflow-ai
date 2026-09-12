"""TDS-19: every part of Form 26AS was counted as TDS deducted from the client.

`_infer_record_type` mapped B to "tds_other", C to "advance_tax", D to
"self_assessment" and F to "tds_other" — and NOTHING read the answer. Every row
of every part was turned into a Form26ASEntry and summed into
`total_26as_paise`, then matched against the client's book TDS register.

Three of those parts are not TDS deducted from the client:

  * PART C is tax the client PAID THEMSELVES — advance and self-assessment.
    Real and claimable, and not a TDS credit. So a client who paid any advance
    tax showed a 26AS-versus-books variance of exactly that amount, every
    year, and the CA had to work out each time that the difference was not a
    missing certificate.
  * PART D is a REFUND already received. Not a credit in any direction.
  * PART F is s.194-IA tax the client deducted as BUYER of property — money
    they paid over, not money withheld from them.

Part B is TCS collected FROM the client (s.206C(4)) — a genuine credit, and
its own kind rather than "tds_other".

⚠️ THE ONE THING THIS DELIBERATELY DOES NOT DO. The audit finding's own
suggested fix was to treat "A2/F" as one thing and filter both out. A2 is TDS
on the client's SALE of immovable property — a credit they are owed — and F is
the same section from the other side. Lumping them drops a real credit. They
are kept apart. What no code here can settle is whether the parser tells A2
from A at all: `re.match(r"PART\\s+([A-Z])")` keeps one letter, so it does not
— which is safe only because A, A1 and A2 are all credits.
"""
import pytest

from domain.income_tax.form26as_service import (
    CREDIT_RECORD_TYPES,
    _infer_record_type,
    read_26as_text,
    split_by_credit,
)


@pytest.mark.parametrize("part,expected,is_credit", [
    ("A", "tds_salary", True),
    ("B", "tcs_collected", True),
    ("C", "tax_paid_by_client", False),
    ("D", "refund_received", False),
    ("F", "tds_deducted_by_client_194ia", False),
])
def test_each_part_is_named_and_classified(part, expected, is_credit):
    got = _infer_record_type(part)
    assert got == expected
    assert (got in CREDIT_RECORD_TYPES) is is_credit


def test_tcs_is_a_credit_and_is_not_called_tds():
    """s.206C(4) gives the collectee credit for TCS, so it counts — but
    calling it 'tds_other' loses the fact that it is a different statement
    (Form 27D) and a different section."""
    assert _infer_record_type("B") == "tcs_collected"
    assert "tcs_collected" in CREDIT_RECORD_TYPES


def test_an_unknown_part_is_treated_as_a_credit():
    """The residual has to fall on the side that does not silently drop money.
    An unrecognised part reported by TRACES is more likely a credit the CA
    should see than a refund, and being shown one too many is recoverable
    where being shown one too few is not."""
    assert _infer_record_type("Z") in CREDIT_RECORD_TYPES
    assert _infer_record_type(None) in CREDIT_RECORD_TYPES


def _row(part, amount):
    return {"part": part, "record_type": _infer_record_type(part),
            "tds_deposited_paise": amount, "deductor_name": "X"}


def test_the_split_keeps_credits_and_sets_the_rest_aside():
    keep, aside = split_by_credit([
        _row("A", 10_000), _row("B", 2_000),
        _row("C", 50_000), _row("D", 7_000), _row("F", 1_000),
    ])
    assert [r["part"] for r in keep] == ["A", "B"]
    assert [r["part"] for r in aside] == ["C", "D", "F"]


def test_nothing_is_discarded_by_the_split():
    rows = [_row(p, 1_000) for p in ("A", "B", "C", "D", "F")]
    keep, aside = split_by_credit(rows)
    assert len(keep) + len(aside) == len(rows), (
        "a row that lands on neither side has vanished, which is the defect "
        "one level up")


def test_a_row_with_no_record_type_is_kept():
    """Rows written before this classification existed have no record_type.
    Reading absence as 'not a credit' would drop every historic row."""
    keep, aside = split_by_credit([{"part": "A", "tds_deposited_paise": 5}])
    assert len(keep) == 1 and aside == []


def test_the_parser_stamps_the_part_it_read():
    r = read_26as_text(
        "PART A\nSr.\tDeductor\tTAN\tDate\tAmount\tTDS\n"
        "1\tAcme\tMUMA12345B\t10/06/2025\t100000.00\t10000.00\tF\n"
        "PART C\n"
        "1\tSelf\t\t15/06/2025\t50000.00\t50000.00\t\n")
    assert [x["part"] for x in r.records] == ["A", "C"]
    assert [x["record_type"] for x in r.records] == ["tds_salary", "tax_paid_by_client"]


def test_the_reconciliation_reports_what_it_set_aside_rather_than_dropping_it():
    """A Part C advance-tax payment is a real fact about the client's year.
    Excluding it from the TDS comparison must not make it invisible."""
    import inspect
    from domain.income_tax import form26as_service as svc
    src = inspect.getsource(svc.run_reconciliation)
    assert "split_by_credit(" in src
    assert "not_a_tds_credit" in src


def test_the_aside_never_reaches_the_reconciliation_insert():
    """`summary` is spread straight into the form_26as_reconciliations INSERT,
    so a key that is not a column of that table fails on the live database and
    passes in mock mode — the exact shape migration 291 was written to repair
    on this same table."""
    import inspect
    from domain.income_tax import form26as_service as svc
    src = inspect.getsource(svc.run_reconciliation)
    before_insert = src[:src.index("recon_row = {")].replace("'", '"')
    assert 'summary["not_a_tds_credit' not in before_insert, (
        "the extras must be a separate dict merged into the RETURN, never "
        "into the row that is inserted")
    # Quotes normalised above on purpose: the first version of this assertion
    # matched double quotes only and passed against a single-quoted mutation.
