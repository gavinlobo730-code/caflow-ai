"""IT-24: the 26AS parser dropped what it could not read, and said nothing.

Two paths in `parse_26as_text` discarded a line — a split that yielded fewer
than five columns (a bare `continue`) and a row whose date or amount would not
parse (a DEBUG log) — and the router then answered `{"records_parsed": N}` with
no denominator. So an upload that read three rows out of forty was reported
exactly like one that read forty out of forty.

That is not cosmetic. Every dropped line is a tax credit the client is entitled
to under IT Act s.199, and the reconciliation that runs next reports the
deductor as "missing in 26AS" — sending the CA to chase a deductor who filed
correctly, while the return claims less credit than the portal shows.

`read_26as_text` returns a Reading26AS carrying BOTH sides, and there is
deliberately no wrapper handing back only the records.
"""
import pytest

from domain.income_tax.form26as_service import Reading26AS, read_26as_text

HEADER = "PART A\nSr.\tName of Deductor\tTAN\tDate\tAmount Paid\tTDS\tStatus\n"
GOOD = "1\tAcme Pvt Ltd\tMUMA12345B\t10/06/2025\t100000.00\t10000.00\tF\n"


def test_a_good_file_reads_clean():
    r = read_26as_text(HEADER + GOOD)
    assert len(r.records) == 1
    assert r.skipped == []
    assert r.data_lines_seen == 1
    assert not r.looks_unrecognised


def test_a_short_row_is_named_with_its_line_number():
    r = read_26as_text(HEADER + GOOD + "2\tBeta LLP\tDELB98765C\n")
    assert len(r.records) == 1
    assert len(r.skipped) == 1
    assert r.skipped[0].line_no == 4, "1-based, the way a text editor counts"
    assert "Beta LLP" in r.skipped[0].text
    assert "column" in r.skipped[0].reason


def test_a_row_whose_amount_will_not_parse_is_named_not_logged():
    """The old code caught this at DEBUG. A tax credit dropped at DEBUG level
    is a tax credit dropped.

    The amount has to be one _parse_amount actually REFUSES. It returns 0 for
    text with no digits in it ("see annexure"), which is its own decision and
    not this branch — a first version of this test used exactly that and
    passed with the branch deleted.
    """
    r = read_26as_text(HEADER + GOOD +
                       "2\tBeta LLP\tDELB98765C\t12/09/2025\t1.2.3\t5000.00\tU\n")
    assert len(r.records) == 1
    assert len(r.skipped) == 1
    assert r.skipped[0].line_no == 4
    assert "amount could not be read" in r.skipped[0].reason


def test_every_data_line_lands_on_one_side_of_the_reading():
    """The invariant behind both branches: records + skipped == data lines.
    A line that is neither is a line that vanished."""
    text = (HEADER + GOOD
            + "2\tBeta LLP\tDELB98765C\n"                                  # too short
            + "3\tGamma\tCHEG11111Z\t01/01/2026\t1..5\t2000.00\tF\n"      # bad amount
            + "4\tDelta\tKOLD22222Y\t02/02/2026\t3000.00\t300.00\tF\n")   # good
    r = read_26as_text(text)
    assert r.data_lines_seen == 4
    assert len(r.records) + len(r.skipped) == r.data_lines_seen


def test_a_space_separated_paste_is_refused_rather_than_read_as_empty():
    """The commonest real failure: a CA copies 26AS out of a PDF viewer.

    Every line then has one column, nothing parses, and the old parser
    returned [] — indistinguishable from a year in which no tax was deducted.
    """
    pasted = ("PART A\n"
              "1 Acme Pvt Ltd MUMA12345B 10/06/2025 100000.00 10000.00 F\n"
              "2 Beta Services LLP DELB98765C 12/09/2025 50000.00 5000.00 U\n")
    r = read_26as_text(pasted)
    assert r.records == []
    assert r.data_lines_seen == 2
    assert r.looks_unrecognised is True
    assert all("space-separated" in s.reason for s in r.skipped)


def test_an_empty_file_is_not_called_unrecognised():
    """An empty 26AS and an unreadable one are opposite facts."""
    r = read_26as_text("PART A\nSr.\tName of Deductor\tTAN\tDate\tAmount\tTDS\n")
    assert r.records == [] and r.data_lines_seen == 0
    assert r.looks_unrecognised is False


def test_headers_and_part_markers_are_not_counted_as_data():
    r = read_26as_text(HEADER + GOOD + "PART B\n" + GOOD)
    assert r.data_lines_seen == 2 and len(r.records) == 2
    assert [x["part"] for x in r.records] == ["A", "B"]


def test_there_is_no_lossy_view_of_the_reading():
    """A convenience wrapper returning only the records is how the silent
    drop comes back — and is exactly what the old name did."""
    import domain.income_tax.form26as_service as svc
    assert not hasattr(svc, "parse_26as_text"), (
        "parse_26as_text returned the records alone; that IS the defect")


def test_the_router_reports_the_skipped_lines_and_refuses_a_blank_read():
    import inspect
    from routers import form_26as as r
    src = inspect.getsource(r.parse_upload)
    assert "lines_skipped" in src and '"skipped"' in src, (
        "records_parsed with no denominator reads as a complete read")
    assert "looks_unrecognised" in src and "422" in src, (
        "a file that parsed nothing must not be saved as an empty year")


def test_the_reading_is_a_frozen_value():
    r = read_26as_text(HEADER + GOOD)
    assert isinstance(r, Reading26AS)
    with pytest.raises(Exception):
        r.records = []          # type: ignore[misc]
