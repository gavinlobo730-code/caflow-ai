"""
The revamped ECR: month sequence, return type, and the arithmetic we refuse.

WHAT THESE ARE FOR

The ECR file format did not change when EPFO revamped the return on 26 September
2025 — same .txt, same eleven fields, same `#~#`. Everything AROUND it did, and
the product knew none of it: it built a correct October file for a client whose
September was outstanding and called that done.

So the weight of this module is deliberately on the cases where the answer is
"you cannot file this yet" and on the cases where nothing should change at all.
A test suite that only proved the happy path would pass just as well against a
version that always says "Regular, nothing blocking".

THE ONE THAT IS NOT ABOUT SEQUENCE

test_nothing_in_payroll_computes_7q_or_14b tokenises the payroll modules and
fails if either section number appears anywhere but a string or a comment. EPFO
computes interest under s.7Q and damages under s.14B itself and shows them at
challan generation; a second implementation would hand the CA two numbers with
no way to tell which the portal will accept. It is an inverted assertion — its
subject is code that must never exist — which is why it scans rather than calls.
"""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

from domain.payroll import ecr_sequence as seq
from domain.payroll.ecr_sequence import (
    APPROVED, REGULAR, REVISED, SUBMITTED, SUPPLEMENTARY,
    FiledMember, RecordedFiling, decide_returns, outstanding_months, sequence_for,
)

API = Path(__file__).resolve().parents[1]


def member(uan: str, wages: int = 15000, epf: int = 1800, eps: int = 1250):
    return FiledMember(uan=uan, epf_wages=wages,
                       epf_contribution=epf, eps_contribution=eps)


def regular(month: str, *members, status: str = APPROVED):
    return RecordedFiling(wage_month=month, return_type=REGULAR,
                          status=status, members=tuple(members))


# ── The month sequence ────────────────────────────────────────────────────────

def test_a_month_with_no_approved_regular_is_outstanding():
    assert outstanding_months(finalised_months=["2026-04", "2026-05"],
                              filings=[]) == ("2026-04", "2026-05")


def test_an_approved_regular_clears_its_month():
    assert outstanding_months(
        finalised_months=["2026-04", "2026-05"],
        filings=[regular("2026-04", member("111111111111"))]) == ("2026-05",)


def test_a_submitted_regular_does_not_clear_its_month():
    """The portal blocks a later month unless the earlier one is filed AND
    validated, and the challan cannot be generated until the return is approved.
    Treating a submission as clearance is the mistake that hands a CA the next
    month's file while the previous return is still in flight."""
    assert outstanding_months(
        finalised_months=["2026-04"],
        filings=[regular("2026-04", member("111111111111"),
                         status=SUBMITTED)]) == ("2026-04",)


def test_a_supplementary_alone_does_not_clear_a_month():
    """A Supplementary presupposes the month's Regular; it is not that Regular.
    A month cleared by one would be a month whose main return was never filed."""
    supp = RecordedFiling(wage_month="2026-04", return_type=SUPPLEMENTARY,
                          status=APPROVED, members=(member("111111111111"),))
    assert outstanding_months(finalised_months=["2026-04"],
                              filings=[supp]) == ("2026-04",)


def test_only_earlier_outstanding_months_block():
    s = sequence_for("2026-06",
                     finalised_months=["2026-04", "2026-05", "2026-06", "2026-07"],
                     filings=[])
    assert s.blocking == ("2026-04", "2026-05")
    assert s.is_blocked
    assert "2026-07" not in s.blocking          # a LATER month blocks nothing


def test_every_earlier_outstanding_month_is_named_not_a_four_month_window():
    """The launch relaxation let a month through if the data four months prior
    was complete. It has expired. Encoding a window that has already moved once
    would err in the only direction that matters — telling a CA a month is clear
    when the portal will refuse it."""
    months = [f"2025-{m:02d}" for m in (9, 10, 11, 12)] + ["2026-01", "2026-02"]
    s = sequence_for("2026-02", finalised_months=months, filings=[])
    assert s.blocking == ("2025-09", "2025-10", "2025-11", "2025-12", "2026-01")


def test_a_clear_month_is_not_blocked_and_says_what_it_did_not_check():
    s = sequence_for("2026-05",
                     finalised_months=["2026-04", "2026-05"],
                     filings=[regular("2026-04", member("111111111111"))])
    assert s.blocking == ()
    assert not s.is_blocked
    # The honest limit, stated in the note the CA reads.
    assert "not visible here" in s.note
    assert s.months_known_from == "2026-04"


def test_the_blocked_note_names_the_month_to_file_first():
    note = sequence_for("2026-06", finalised_months=["2026-03", "2026-06"],
                        filings=[]).note
    assert "File 2026-03 first" in note


def test_months_known_from_is_none_when_nothing_has_been_run():
    s = sequence_for("2026-06", finalised_months=[], filings=[])
    assert s.months_known_from is None and s.outstanding == ()


def test_a_malformed_month_is_dropped_rather_than_breaking_the_sequence():
    s = sequence_for("2026-06", finalised_months=["2026-04", "not-a-month", ""],
                     filings=[])
    assert s.outstanding == ("2026-04",)


# ── Which return type a month needs ──────────────────────────────────────────

def test_no_approved_regular_means_this_file_is_the_regular():
    d = decide_returns("2026-06", members=[member("111111111111")], filings=[])
    assert d.required_returns == (REGULAR,)


def test_an_unapproved_regular_does_not_make_the_next_file_a_supplementary():
    """A Regular still in flight has not covered anybody. Reading it as coverage
    would recommend a Supplementary for a month whose Regular is not accepted
    yet — a return EPFO has nothing to attach to."""
    d = decide_returns("2026-06", members=[member("111111111111")],
                       filings=[regular("2026-06", member("111111111111"),
                                        status=SUBMITTED)])
    assert d.required_returns == (REGULAR,)


def test_a_new_joiner_after_an_approved_regular_is_a_supplementary():
    d = decide_returns(
        "2026-06",
        members=[member("111111111111"), member("222222222222")],
        filings=[regular("2026-06", member("111111111111"))])
    assert d.required_returns == (SUPPLEMENTARY,)
    assert d.new_members == ("222222222222",)
    assert d.changed_members == ()


def test_a_changed_figure_after_an_approved_regular_is_a_revised():
    d = decide_returns(
        "2026-06",
        members=[member("111111111111", wages=14000, epf=1680, eps=1166)],
        filings=[regular("2026-06", member("111111111111"))])
    assert d.required_returns == (REVISED,)
    assert d.changed_members == ("111111111111",)


def test_a_month_can_need_both_and_neither_is_dropped():
    """The case picking one silently gets wrong. A new joiner AND a corrected
    wage in the same month are two returns, not a choice between them."""
    d = decide_returns(
        "2026-06",
        members=[member("111111111111", wages=14000, epf=1680, eps=1166),
                 member("222222222222")],
        filings=[regular("2026-06", member("111111111111"))])
    assert d.required_returns == (SUPPLEMENTARY, REVISED)
    assert d.new_members == ("222222222222",)
    assert d.changed_members == ("111111111111",)
    assert "does not know which order" in d.reason


def test_nothing_further_to_file_when_the_books_still_match_the_return():
    d = decide_returns("2026-06", members=[member("111111111111")],
                       filings=[regular("2026-06", member("111111111111"))])
    assert d.required_returns == () and d.nothing_to_file


def test_a_revised_already_filed_is_not_flagged_again():
    """The correction has been accepted. Comparing against the Regular alone
    would re-recommend a Revised for a member whose revision is already in."""
    corrected = member("111111111111", wages=14000, epf=1680, eps=1166)
    filings = [regular("2026-06", member("111111111111")),
               RecordedFiling(wage_month="2026-06", return_type=REVISED,
                              status=APPROVED, members=(corrected,))]
    d = decide_returns("2026-06", members=[corrected], filings=filings)
    assert d.required_returns == ()


def test_a_member_who_has_gone_is_reported_and_drives_no_return_type():
    """The file format has no way to say "remove this member". A member wrongly
    included is corrected by revising their line, which shows as a figure change
    while they are still in the run. A member who has simply vanished from the
    run is a question about the run, and guessing "Revised" would file a return
    that says nothing about them."""
    d = decide_returns("2026-06", members=[member("111111111111")],
                       filings=[regular("2026-06", member("111111111111"),
                                        member("999999999999"))])
    assert d.required_returns == ()
    assert d.withdrawn_members == ("999999999999",)
    assert "no longer in this run" in d.reason


def test_another_months_filing_does_not_cover_this_month():
    d = decide_returns("2026-06", members=[member("111111111111")],
                       filings=[regular("2026-05", member("111111111111"))])
    assert d.required_returns == (REGULAR,)


def test_only_the_three_comparable_figures_decide_a_revision():
    """Name, NCP days and the refund of advances are not carried on a filing
    record. A Revised return corrects "wages or contribution details"; a
    respelled name is not a revision, and treating it as one would file a return
    against EPFO for nothing."""
    assert member("111111111111").figures == (15000, 1800, 1250)


# ── The arithmetic that must not exist ───────────────────────────────────────

def test_the_interest_note_names_epfo_as_the_computer():
    note = seq.INTEREST_AND_DAMAGES_NOTE
    assert "s.7Q" in note and "s.14B" in note
    assert "computed by EPFO" in note
    assert "does not compute" in note


PAYROLL_SOURCES = sorted((API / "domain" / "payroll").glob("*.py")) + [
    API / "routers" / "payroll.py",
    API / "services" / "epfo_ecr_filing_service.py",
]


def test_nothing_in_payroll_computes_7q_or_14b():
    """s.7Q interest and s.14B damages are EPFO's to compute.

    An inverted assertion: its subject is code that must never exist, so it
    scans rather than calls. Every occurrence of either section number must be
    inside a string or a comment — prose about why we do not compute them is
    exactly right, an identifier or a number keyed to them is not.
    """
    assert PAYROLL_SOURCES, "no payroll sources found — the glob is wrong"
    offenders = []
    for path in PAYROLL_SOURCES:
        src = path.read_text()
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                continue
            text = tok.string.lower().replace("_", "")
            if "7q" in text or "14b" in text:
                offenders.append(f"{path.name}:{tok.start[0]} {tok.string!r}")
    assert not offenders, (
        "s.7Q / s.14B appear outside a string or comment, which means something "
        "is computing them: " + "; ".join(offenders))


def test_the_scan_would_actually_catch_a_computation(tmp_path):
    """The negative control for the scan above. Without this, a broken glob or a
    tokeniser that silently yields nothing would make the guard pass forever."""
    bad = tmp_path / "damages.py"
    bad.write_text("def section_14b_damages(paise):\n    return paise * 25 // 100\n")
    found = [t.string for t in tokenize.generate_tokens(
        io.StringIO(bad.read_text()).readline)
        if t.type not in (tokenize.STRING, tokenize.COMMENT)
        and "14b" in t.string.lower().replace("_", "")]
    assert found == ["section_14b_damages"]


# ── The service's refusals ───────────────────────────────────────────────────

def test_the_service_refuses_a_month_that_is_not_a_wage_month():
    from services import epfo_ecr_filing_service as svc
    with pytest.raises(svc.ECRFilingError) as exc:
        svc.record_filing(None, firm_id="f", client_id="c", wage_month="June 2026",
                          return_type=REGULAR)
    assert "YYYY-MM" in str(exc.value)


def test_the_service_refuses_an_invented_return_type():
    from services import epfo_ecr_filing_service as svc
    with pytest.raises(svc.ECRFilingError) as exc:
        svc.record_filing(None, firm_id="f", client_id="c", wage_month="2026-06",
                          return_type="annual")
    for word in (REGULAR, SUPPLEMENTARY, REVISED):
        assert word in str(exc.value)


def test_the_service_refuses_an_approval_before_the_submission():
    from services import epfo_ecr_filing_service as svc
    with pytest.raises(svc.ECRFilingError):
        svc.record_filing(None, firm_id="f", client_id="c", wage_month="2026-06",
                          return_type=REGULAR, status=APPROVED,
                          submitted_on="2026-07-10", approved_on="2026-07-01")


def test_a_malformed_stored_member_reads_as_uncovered_not_as_a_crash():
    """Skipping rather than raising, and in the safe direction: a skipped member
    reads as "not on any approved return", which recommends a Supplementary.
    Filing a Supplementary for a member already on the Regular is visible at the
    portal; omitting one is not."""
    from services import epfo_ecr_filing_service as svc
    got = svc._members_from_row([{"uan": "111111111111", "epf_wages": 15000,
                                  "epf_contribution": 1800, "eps_contribution": 1250},
                                 {"uan": ""}, "not a dict",
                                 {"uan": "222222222222", "epf_wages": "oops"}])
    assert [m.uan for m in got] == ["111111111111"]
