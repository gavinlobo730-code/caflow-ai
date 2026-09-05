"""
Form 24Q's working paper, built by the server.

WHAT WAS WRONG

`generateTds24QData` in apps/web/app/payroll/page.tsx assembled a STATUTORY
RETURN in the browser, from whatever payslips that screen happened to have
loaded. domain/payroll/form24q.py had existed for some time and did the job
properly; the browser copy was never retired, and the two disagreed on the thing
that matters most.

  1. THE BROWSER WROTE "PAN NOT AVAILABLE" AND CARRIED ON.
     §206AA requires tax at the HIGHER of the specified rate or 20% where PAN is
     not furnished. A row declaring tax deducted at slab rates against no PAN
     therefore declares a SHORT deduction — and §201(1) puts that on the
     employer, not the employee. The domain refuses the row instead.

  2. IT NEVER LOOKED FOR A §192 CHALLAN, so it would produce a quarter's return
     with nothing showing the tax was deposited. TDS deducted is a trust; a
     return saying it was deducted and nothing saying it was paid over invites
     exactly the demand the return is meant to prevent.

  3. IT NEVER CHECKED THE RUNS WERE FINALISED, so a draft month's figures could
     be filed and then move.

  4. It divided paise by 100 in floating point.

Same fix as the salary register and the employee import: a statutory document is
not a thing the browser assembles. And the ASSEMBLY is shared — one helper feeds
both the JSON source a screen reads and the CSV a CA keeps — because two
assemblies would drift and both would look like a perfectly reasonable 24Q.

NEGATIVE CONTROLS
    Write paise instead of rupees and
    test_the_file_is_in_rupees_at_the_document_boundary fails.
    Drop the not-ready banner and
    test_a_quarter_that_is_not_ready_says_so_in_the_file fails.
    Let a deductee through without a PAN and
    test_a_row_with_no_valid_pan_is_not_in_the_file fails.
"""
from __future__ import annotations

import csv
import io

from domain.payroll import form24q as f24


class _Row:
    """The fields to_csv reads off a TDSDeducteeRecord."""
    def __init__(self, **kw):
        self.deductee_name = kw.get("name", "Asha Rao")
        self.deductee_pan = kw.get("pan", "ABCPA1234A")
        self.section = "192"
        self.payment_date = "2026-06-30"
        self.payment_amount_paise = kw.get("gross", 3_000_000)
        self.tds_deducted_paise = kw.get("tds", 250_000)
        self.tds_deposited_paise = kw.get("tds", 250_000)
        self.challan_no = "00123"
        self.bsr_code = "0510308"
        self.challan_date = "2026-07-05"


def _src(**kw) -> f24.Form24QSource:
    s = f24.Form24QSource()
    s.deductees = kw.get("deductees", [_Row()])
    s.challans = kw.get("challans", [{"tds_paise": 250_000}])
    s.problems = kw.get("problems", [])
    s.employees_with_nil_tds = kw.get("nil", 0)
    return s


def _lines(blob: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(blob.decode("utf-8-sig"))))


def _body(blob: bytes) -> list[list[str]]:
    """The rows under the header, ignoring the banner comments."""
    rows = _lines(blob)
    start = next(i for i, r in enumerate(rows) if r and r[0] == "Employee Name")
    return rows[start:]


def test_the_file_is_in_rupees_at_the_document_boundary():
    """Money is integer paise everywhere and becomes rupees only where a
    document is produced — the rule domain/gst/money.py follows for the
    statutory payloads and register.py for the salary register."""
    rows = _body(f24.to_csv(_src(), financial_year="2026-27", quarter="Q1"))
    header, first = rows[0], rows[1]
    assert first[header.index("Gross Salary")] == "30000.00"
    assert first[header.index("TDS Deducted")] == "2500.00"


def test_no_thousands_separator():
    """This file is read by a program as often as by a person, and
    parseFloat("1,25,000") is 1."""
    rows = _body(f24.to_csv(_src(deductees=[_Row(gross=12_500_000)]),
                            financial_year="2026-27", quarter="Q1"))
    assert "," not in rows[1][rows[0].index("Gross Salary")]


def test_the_banner_says_it_is_not_a_return():
    """A CSV of names, PANs and tax deducted that does not say what it is and is
    not gets forwarded, and the next person to open it cannot tell it was never
    filed."""
    text = f24.to_csv(_src(), financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in text
    assert "not filed" in text
    assert "2026-27 Q1" in text


def test_a_quarter_that_is_not_ready_says_so_in_the_file():
    """The problems go IN the file, not only on the screen that produced it. A
    file downloaded while the quarter was incomplete outlives the toast."""
    blob = f24.to_csv(_src(problems=["Payroll for 2026-05 is not finalised."]),
                      financial_year="2026-27", quarter="Q1")
    text = blob.decode("utf-8-sig")
    assert "NOT READY" in text and "2026-05" in text


def test_a_ready_quarter_carries_no_not_ready_line():
    text = f24.to_csv(_src(), financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "NOT READY" not in text


def test_the_nil_tax_employees_are_counted_not_hidden():
    """Annexure I is a break-up of TDS DEDUCTED, so an employee with no tax is
    not a deductee row — but the decision is stated rather than silently made."""
    text = f24.to_csv(_src(nil=3), financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "3 employee(s)" in text and "NIL tax" in text


def test_the_file_states_both_sides_of_the_reconciliation():
    """Tax deducted against tax deposited is the check a CA is actually doing.
    Stating only the first invites the return to be filed without the second."""
    text = f24.to_csv(_src(deductees=[_Row(tds=250_000), _Row(tds=150_000)],
                           challans=[{"tds_paise": 300_000}]),
                      financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "TDS deducted   4000.00" in text
    assert "Challans on file 3000.00" in text


def test_it_totals_itself():
    rows = _body(f24.to_csv(_src(deductees=[_Row(gross=3_000_000, tds=250_000),
                                            _Row(gross=1_000_000, tds=50_000)]),
                            financial_year="2026-27", quarter="Q1"))
    header = rows[0]
    total = next(r for r in rows if r and r[0] == "TOTAL")
    assert total[header.index("Gross Salary")] == "40000.00"
    assert total[header.index("TDS Deducted")] == "3000.00"


def test_an_empty_quarter_is_a_header_and_no_total():
    """A TOTAL of zero under no rows reads as a quarter that ran and deducted
    nothing."""
    rows = _body(f24.to_csv(_src(deductees=[]), financial_year="2026-27", quarter="Q1"))
    assert len(rows) == 1


def test_the_file_carries_a_bom_but_the_portal_files_do_not():
    """This is a WORKING PAPER opened in a spreadsheet, so Excel must read it as
    UTF-8. The ECR and the ESIC return deliberately carry no BOM, because those
    are uploaded to a portal where extra bytes break parsing."""
    assert f24.to_csv(_src(), financial_year="2026-27", quarter="Q1").startswith(b"\xef\xbb\xbf")


# ─── the refusal the browser did not make ───────────────────────────────────

def test_a_row_with_no_valid_pan_is_not_in_the_file():
    """§206AA: tax at the HIGHER of the specified rate or 20% where PAN is not
    furnished. Filing tax deducted at slab rates against "PANNOTAVBL" declares a
    SHORT deduction, and §201(1) puts it on the employer.

    The browser wrote "PAN NOT AVAILABLE" into the column and carried on. This
    asserts the DOMAIN refuses the row, which is what the file inherits."""
    src = f24.build_24q_from_payroll(
        slips_by_month={"2026-04": [{"employee_id": "E1", "gross_paise": 3_000_000,
                                     "tds_paise": 250_000}]},
        employees_by_id={"E1": {"id": "E1", "name": "Asha Rao", "pan": ""}},
        challans=[{"section": "192", "tds_paise": 250_000,
                   "challan_no": "1", "bsr_code": "0510308",
                   "payment_date": "2026-05-05"}],
        record_cls=_Row,
        financial_year="2026-27",
    )
    assert src.deductees == []
    assert any("PAN" in p for p in src.problems)
    text = f24.to_csv(src, financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "PANNOTAVBL" not in text and "PAN NOT AVAILABLE" not in text
    assert "NOT READY" in text


def test_the_column_order_is_pinned():
    """A working paper whose columns move between quarters cannot be diffed
    against the last one, and diffing is most of what a CA does with it."""
    names = [h for h, _k in f24.CSV_COLUMNS]
    assert names[0] == "Employee Name" and names[1] == "PAN"
    assert names.index("Gross Salary") < names.index("TDS Deducted")
    assert names.index("TDS Deducted") < names.index("Challan No")
