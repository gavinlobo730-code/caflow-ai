"""
The retention position — one law, one anchor, one date, per data category.

WHAT WAS WRONG

Every deletion guard in this codebase is REFERENTIAL: it refuses while another
row points at this one. That answers a different question from the one DPDP
s. 8(7) asks, and it fails in a way that only gets worse — A REFERENTIAL REFUSAL
NEVER LAPSES. `delete_employee` refused with "this employee has payroll history",
which names no statute, gives no date, and would refuse identically in 2050 when
every duty has long released the record. From 13 May 2027 that is a standing
failure to erase.

WHAT THESE TESTS PIN

Half of them are about the ANCHOR, because that is the part that reads as
interchangeable and is not. For one financial year the same books are held under
three duties that end on three different days, and reading them all as "N years
from the end of the FY" releases the GST record nine months early. A record
released early is destroyed.

The other half are about the direction of the refusal. Everywhere else in this
codebase an unmodelled statutory figure means "do not compute". Here it must mean
"do not delete", because the action being authorised is irreversible — so an
unknown category, an unestablished period and an unanswerable question all
REFUSE, and each is asserted separately.

NEGATIVE CONTROLS — each applied, then reverted:

    | control                                             | tests that fail |
    |-----------------------------------------------------|-----------------|
    | treat an unestablished period as no duty             | 6               |
    | take the shortest live duty instead of the longest   | 5               |
    | anchor GST to the FY end instead of the return due   | 3               |
    | report the gap and drop the live duty's date         | 3               |
    | let an unknown category fall through to erasable     | 1               |
    | prefix-parse the FY label instead of normalising     | 1               |
    | revert the delete endpoint to its old one-line message | 1             |

The last one is the reason the final test exists at all: every other test in this
file passed with the endpoint still refusing the old way, because they exercise
the helper rather than the wire.
"""
from __future__ import annotations

import pathlib
from datetime import date

import pytest
from fastapi import HTTPException

from domain.dpdp import retention as R


# ── the anchors, which are the point ─────────────────────────────────────────

def test_one_financial_year_three_duties_three_different_dates():
    """The worked example from the module docstring. If these ever collapse to
    one date, an anchor has been flattened."""
    assert R.RULES["companies_act_books"].retained_until(fy_label="2020-21") == date(2029, 3, 31)
    assert R.RULES["income_tax_books"].retained_until(fy_label="2020-21") == date(2028, 3, 31)
    assert R.RULES["gst_records"].retained_until(fy_label="2020-21") == date(2027, 12, 31)


def test_gst_runs_from_the_annual_return_due_date_not_the_financial_year_end():
    """s. 36 is 72 months from the GSTR-9 due date — 81 months from the FY end.
    Anchoring it to 31 March would release the record nine months early."""
    until = R.RULES["gst_records"].retained_until(fy_label="2020-21")
    assert (until.day, until.month) == (31, 12), "GST retention anchored to the FY end"
    assert until > date(2027, 3, 31)


def test_the_gst_anchor_asks_compliance_engine_rather_than_restating_december():
    """compliance_engine is the single source for every statutory date. If the
    annual-return due date is ever extended, this rule has to move with it —
    which it only does while it CALLS that function instead of copying it."""
    import domain.dpdp.retention as module

    original = module.gstr9_due_date
    try:
        module.gstr9_due_date = lambda year: date(year, 6, 30)
        moved = R.RULES["gst_records"].retained_until(fy_label="2020-21")
    finally:
        module.gstr9_due_date = original
    assert moved == date(2027, 6, 30), "the GST rule restates the due date instead of asking for it"


def test_the_assessment_year_is_one_year_past_the_financial_year():
    """Six years from the end of the AY is seven from the end of the FY. Reading
    r. 6F(5) as six from the FY end loses a year."""
    assert R.RULES["income_tax_books"].retained_until(fy_label="2020-21") == date(2028, 3, 31)
    assert R.RULES["income_tax_books"].retained_until(fy_label="2020-21") != date(2027, 3, 31)


def test_an_event_anchored_period_runs_from_the_event():
    assert R.RULES["pmla_kyc"].retained_until(event_date=date(2024, 7, 15)) == date(2029, 7, 15)


def test_a_leap_day_event_clamps_rather_than_raising():
    assert R.RULES["pmla_kyc"].retained_until(event_date=date(2024, 2, 29)) == date(2029, 2, 28)


# ── longest duty wins ────────────────────────────────────────────────────────

def test_the_category_is_held_until_the_last_duty_lapses():
    """Books are released by GST in 2027 and by income tax in 2028, and still
    held by the Companies Act until 2029. Taking any but the maximum would
    authorise destruction while another duty runs."""
    assert R.retained_until("books_of_account", fy_label="2020-21") == date(2029, 3, 31)


def test_refused_on_the_last_day_of_the_duty_and_released_the_next():
    kw = dict(category_key="books_of_account", fy_label="2020-21")
    assert R.erasure_decision(**kw, today=date(2029, 3, 31)).erasable is False
    assert R.erasure_decision(**kw, today=date(2029, 4, 1)).erasable is True


def test_a_refusal_lapses_which_is_the_whole_difference_from_the_old_guard():
    """The referential guard it replaces refused for ever. This one stops."""
    old = R.erasure_decision("books_of_account", fy_label="2000-01", today=date(2026, 9, 5))
    assert old.erasable is True


# ── the refusal says which law and until when ────────────────────────────────

def test_the_refusal_names_the_statute_the_provision_and_the_date():
    d = R.erasure_decision("books_of_account", fy_label="2020-21", today=date(2026, 9, 5))
    assert d.erasable is False
    assert "Companies Act 2013" in d.reason
    assert "s. 128(5)" in d.reason
    assert "31 March 2029" in d.reason
    assert d.retained_until == date(2029, 3, 31)


def test_the_refusal_says_whose_duty_it_is():
    """An employee told "we won't delete this" is owed the truthful version:
    their employer must keep it."""
    d = R.erasure_decision("books_of_account", fy_label="2020-21", today=date(2026, 9, 5))
    assert "the client to keep" in d.reason


def test_the_refusal_cites_the_provision_that_makes_retention_win():
    d = R.erasure_decision("books_of_account", fy_label="2020-21", today=date(2026, 9, 5))
    assert "8(7)" in d.reason


# ── every uncertain answer refuses ───────────────────────────────────────────

def test_an_unclassified_category_refuses_rather_than_falling_through():
    """The registry is closed. Destruction is not reversible, so "nobody has
    classified this" cannot mean "go ahead"."""
    d = R.erasure_decision("something_nobody_wrote_down", today=date(2026, 9, 5))
    assert d.erasable is False
    assert "No retention position is written" in d.reason


def test_an_unestablished_period_refuses_and_names_itself_a_gap():
    d = R.erasure_decision("payroll", fy_label="2025-26", today=date(2026, 9, 5))
    assert d.erasable is False
    assert d.is_gap
    assert "epf_records" in d.gap_rules


def test_an_unestablished_period_is_not_treated_as_the_absence_of_a_duty():
    """The failure this guards: reading years=None as "no rule" and releasing
    the record. EPF and ESI both sit in that state."""
    payroll = R.erasure_decision("payroll", fy_label="1990-91", today=date(2026, 9, 5))
    assert payroll.erasable is False, "an unread period released the record"


def test_a_category_with_no_duty_at_all_is_erasable():
    """Different from an unread one, and only this one releases. Somebody looked
    and found nothing."""
    d = R.erasure_decision("support_correspondence", today=date(2026, 9, 5))
    assert d.erasable is True
    assert "No statutory retention duty was identified" in d.reason


def test_a_live_duty_and_a_gap_are_both_reported_with_the_date_first():
    """Reporting only the gap buries the one actionable fact — a date. Reporting
    only the date implies the record is free then, when an unread duty may still
    be running."""
    d = R.erasure_decision("payroll", fy_label="2025-26", today=date(2026, 9, 5))
    assert "Companies Act 2013" in d.reason
    assert "31 March 2034" in d.reason
    assert "NOT established" in d.reason
    assert d.reason.index("Companies Act 2013") < d.reason.index("NOT established")


def test_no_release_date_is_published_while_a_duty_is_unread():
    """`retained_until` beside an unknown duty would read as "free on this
    date". It is not, so it is withheld."""
    d = R.erasure_decision("payroll", fy_label="2025-26", today=date(2026, 9, 5))
    assert d.gap_rules
    assert d.retained_until is None


def test_all_three_kinds_of_refusal_are_reported_not_just_the_first():
    """The bug this caught: returning on the first reason found. A payslip whose
    month could not be read said "tell me the period" and never mentioned that
    EPF and ESI hold the record under periods nobody has established — and those
    two do not depend on the period at all. Naming one of three reasons invites
    the reader to fix that one and expect the record to be released."""
    d = R.erasure_decision("payroll", today=date(2026, 9, 5))   # no fy_label
    assert d.erasable is False
    assert "did not say which" in d.reason, "the answerable question went unasked"
    assert "NOT established" in d.reason, "the unread duties were hidden"
    assert d.gap_rules == ("epf_records", "esi_records")


def test_a_period_anchored_question_asked_without_a_period_refuses():
    d = R.erasure_decision("books_of_account", today=date(2026, 9, 5))
    assert d.erasable is False
    assert "did not say which" in d.reason


def test_a_label_that_is_not_a_financial_year_refuses_rather_than_meaning_another_year():
    """'2020-99' prefix-parses to 2020-21 and would compute a lapse date for a
    year nobody asked about. fy_bounds is lenient by design; a date that
    authorises deletion cannot be."""
    with pytest.raises(ValueError):
        R.erasure_decision("books_of_account", fy_label="2020-99", today=date(2026, 9, 5))


# ── the position holds together ──────────────────────────────────────────────

def test_every_category_points_at_a_rule_that_exists():
    for category in R.CATEGORIES.values():
        for key in category.rules:
            assert key in R.RULES, f"{category.key} names an unknown rule {key!r}"


def test_an_unestablished_period_and_its_confidence_grade_agree():
    """Two ways of saying the same thing, so they cannot drift apart and leave a
    rule that computes a date while claiming not to."""
    for rule in R.RULES.values():
        assert rule.period_established is (rule.confidence != R.NOT_ESTABLISHED), rule.key


def test_the_published_position_covers_every_category():
    published = R.position()
    assert {row["category"] for row in published} == set(R.CATEGORIES)
    for row in published:
        for entry in row["rules"]:
            assert entry["statute"] and entry["provision"] and entry["duty_holder"]


def test_no_rule_claims_a_primary_source():
    """docs/compliance/00-how-to-read-this.md: nothing here was read from a
    primary source — every legal host is blocked from this environment. A rule
    graded higher than the evidence is the failure this catches."""
    assert {r.confidence for r in R.RULES.values()} <= {
        R.CORROBORATED, R.SECONDARY, R.NOT_ESTABLISHED}


# ── the payroll delete refusal, end to end ───────────────────────────────────

class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows): self._rows = rows
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def in_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def maybe_single(self): return _Single(self._rows)
    def execute(self): return _Result(self._rows)


class _Single:
    def __init__(self, rows): self._rows = rows
    def execute(self): return _Result(self._rows[0] if self._rows else None)


class _DB:
    def __init__(self, tables): self._tables = tables
    def table(self, name): return _Query(self._tables.get(name, []))


def _refusal(slips, runs):
    from routers.payroll import _payroll_retention_refusal
    return _payroll_retention_refusal(
        _DB({"payroll_runs": runs}), "firm-1", slips)


def test_the_employee_refusal_names_a_statute_and_a_date():
    """The old message was "this employee has payroll history" — no statute, no
    date, and it never lapsed."""
    text = _refusal([{"run_id": "r1"}], [{"month": "2025-06"}])
    assert "Companies Act 2013" in text
    assert "31 March 2034" in text
    assert "payroll history and cannot be deleted" not in text


def test_the_latest_month_drives_the_date_not_the_first():
    """Retention runs from the year the record belongs to, so the most recent
    payslip is the one whose duty expires last."""
    early = _refusal([{"run_id": "r1"}], [{"month": "2019-06"}])
    late = _refusal([{"run_id": "r1"}, {"run_id": "r2"}],
                    [{"month": "2019-06"}, {"month": "2025-06"}])
    assert "31 March 2028" in early
    assert "31 March 2034" in late


def test_an_unpadded_month_does_not_order_as_text():
    """A text sort puts '2026-3' after '2026-11', because '3' > '1'.

    The pair has to STRADDLE 1 APRIL for the mistake to show: within one
    financial year both orderings give the same answer, which is why the first
    version of this test passed against the bug it was written for. March 2026
    is FY 2025-26 and November 2026 is FY 2026-27, so picking the wrong one
    understates the retention by a whole year."""
    text = _refusal([{"run_id": "r1"}, {"run_id": "r2"}],
                    [{"month": "2026-11"}, {"month": "2026-3"}])
    assert "31 March 2035" in text, "the later month lost to a text sort"
    assert "31 March 2034" not in text


def test_an_unreadable_month_still_refuses_and_still_names_the_statutes():
    """A month that cannot be parsed is skipped, never guessed. The refusal
    falls back to the category sentence rather than to silence."""
    text = _refusal([{"run_id": "r1"}], [{"month": "not-a-month"}])
    assert "Erasure refused" in text
    assert "EPF" in text


def test_the_refusal_still_tells_the_ca_what_to_do_instead():
    text = _refusal([{"run_id": "r1"}], [{"month": "2025-06"}])
    assert "deactivate" in text.lower()


def test_the_delete_endpoint_actually_calls_the_refusal(monkeypatch):
    """The helper being right is not the same as the endpoint using it.

    Reverting the call site to the old one-line message left every other test in
    this file passing — the same unwired failure mode as an unreferenced
    redactor. This one holds the wire, not the calculation.
    """
    import routers.payroll as payroll

    db = _DB({
        "payroll_employees": [{"id": "e1", "name": "Asha Rao", "client_id": "c1"}],
        "payroll_slips": [{"run_id": "r1"}],
        "payroll_runs": [{"month": "2025-06"}],
    })
    monkeypatch.setattr(payroll, "_db", lambda: db)
    monkeypatch.setattr(payroll, "_assert_employee_scope", lambda *a, **k: "c1")

    with pytest.raises(HTTPException) as raised:
        payroll.delete_employee("e1", current_user={"firm_id": "f1"})

    assert raised.value.status_code == 409
    assert "Companies Act 2013" in raised.value.detail
    assert "31 March 2034" in raised.value.detail


# ── the doc and the code say the same thing ──────────────────────────────────

_DOC = (pathlib.Path(__file__).resolve().parents[3]
        / "docs" / "compliance" / "06-data-protection-dpdp.md")


def test_the_published_table_names_every_category_the_code_holds():
    """§5b is the readable form of `position()`. A table maintained by hand
    drifts from the code that actually refuses, and the drift is invisible —
    both halves look fine on their own."""
    text = _DOC.read_text()
    section = text[text.index("## 5b."):text.index("## 6.")]
    for key in R.CATEGORIES:
        assert f"**{key}**" in section, f"{key} is in the code and not in §5b"


def test_the_published_table_does_not_invent_a_category():
    text = _DOC.read_text()
    section = text[text.index("## 5b."):text.index("## 6.")]
    import re
    # Anchored to the ROW START: "| **firm** |" and "| **platform** |" appear
    # mid-row in the whose-duty column and are duty holders, not categories.
    named = set(re.findall(r"^\| \*\*([a-z_]+)\*\* \|", section, re.MULTILINE))
    assert named, "the category table stopped being parseable — this test would pass vacuously"
    assert named <= set(R.CATEGORIES), f"§5b names categories the code does not hold: {named - set(R.CATEGORIES)}"


def test_the_worked_example_in_the_doc_matches_what_the_code_computes():
    """The three dates in §5b's anchor table are the whole argument for anchors
    mattering. If the code moves and the doc does not, the argument is stale."""
    text = _DOC.read_text()
    section = text[text.index("## 5b."):text.index("## 6.")]
    for expected in ("31-03-2029", "31-03-2028", "31-12-2027"):
        assert expected in section
    assert R.RULES["companies_act_books"].retained_until(fy_label="2020-21") == date(2029, 3, 31)
    assert R.RULES["income_tax_books"].retained_until(fy_label="2020-21") == date(2028, 3, 31)
    assert R.RULES["gst_records"].retained_until(fy_label="2020-21") == date(2027, 12, 31)
