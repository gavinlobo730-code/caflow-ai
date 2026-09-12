"""Rule 31A puts four dates a year on Form 24Q, and the calendar had none.

WHAT WAS WRONG (TDS-12)

    `_tds_obligations` emitted `TDS26Q` for every TDS engagement and `TDS27Q`
    where the client pays a non-resident. It never emitted the SALARY
    statement. And `_payroll_obligations` declined to emit it too, in a
    docstring that said:

        THE 24Q RETURN IS NOT HERE EITHER — it is already emitted by
        _tds_obligations, quarterly, for a TDS engagement.

    That was load-bearing misinformation: it is the sentence a reader checking
    "where is 24Q?" would have stopped at. So the quarterly salary statement —
    the one §234E charges Rs 200 a day for filing late, capped at the tax
    deductible — appeared on no calendar at all.

    The MONTHLY §192 deposit was there all along (`TDS_SALARY_DEPOSIT`, Rule
    30). A deposit and a statement are different obligations with different
    dates and different penalties, and having one is not having the other.

    Both screens were already waiting for it: `app/deadlines/page.tsx` and
    `app/risks/page.tsx` list "TDS24Q" among the types a CA can filter to, and
    `lib/types/index.ts`'s `ComplianceType` union has carried it for as long as
    either. A filter that can never match a row.

WHY UNCONDITIONAL, LIKE 26Q RATHER THAN LIKE 27Q

    26Q is emitted for every TDS engagement without first asking whether the
    client has any resident deduction to report — the engagement IS the
    statement of that. 24Q is the same shape: a business with employees is the
    ordinary case, not the rare one 27Q's condition exists for.

    Gating it on `payroll_employees` would also be the wrong FACT. A firm can
    file 24Q for a client whose payroll it does not run, and then the row a CA
    needs most is the one that would be missing.

WHY A NEW TYPE AND NOT A SECOND 26Q ROW

    The generator dedups on `(obligation_type, period_start)`, and 24Q shares
    its period_start with 26Q. A second row under `TDS26Q` would be silently
    swallowed. The string is `TDS24Q` and is stable from this commit: renaming
    it later would orphan every row already generated.
"""
from __future__ import annotations

import re
from pathlib import Path

import services.compliance_obligation_service as ob

FY = "2025-26"
FY_2025_ACT = "2026-27"


def _types(specs):
    return sorted(s["obligation_type"] for s in specs)


# ── the statement is generated ───────────────────────────────────────────────

def test_a_tds_engagement_owes_four_salary_statements():
    specs = ob._tds_obligations(FY)
    assert _types(specs).count("TDS24Q") == 4


def test_it_is_its_own_obligation_type():
    """The dedup key is (obligation_type, period_start) and 24Q shares its
    period_start with 26Q, so a second row under TDS26Q would be swallowed."""
    specs = ob._tds_obligations(FY)
    by_period: dict[str, set] = {}
    for s in [x for x in specs if x["obligation_type"].startswith("TDS2")]:
        by_period.setdefault(s["period_start"], set()).add(s["obligation_type"])
    assert len(by_period) == 4
    for period, kinds in by_period.items():
        assert "TDS24Q" in kinds and "TDS26Q" in kinds, (period, kinds)


def test_it_is_not_conditional():
    """27Q is the conditional one, for a reason written into its own comment.
    24Q must not inherit that: nothing here reads a payroll fact."""
    assert ob._tds_obligations(FY, has_non_resident_vendors=False) \
        != []
    assert _types(ob._tds_obligations(FY, has_non_resident_vendors=False)).count("TDS24Q") == 4
    assert _types(ob._tds_obligations(FY, has_non_resident_vendors=True)).count("TDS24Q") == 4


def test_it_shares_the_quarter_s_one_due_date():
    """Rule 31A(2) sets one date per quarter regardless of form. Two date
    computations would eventually drift."""
    # The STATEMENTS only. The monthly Rule 30(2) deposits ride in the same
    # function and have their own twelve periods on twelve different dates —
    # which is what makes them a separate obligation rather than a fifth
    # statement (TDS-12).
    specs = [x for x in ob._tds_obligations(FY, has_non_resident_vendors=True)
             if x["obligation_type"].startswith("TDS2")]
    for period in {s["period_start"] for s in specs}:
        dues = {s["due_date"] for s in specs if s["period_start"] == period}
        assert len(dues) == 1, (period, dues)


def test_q4_is_31_may_for_the_salary_statement_too():
    """The exception worth pinning: Q4 is NOT the end of the month following
    quarter end. compliance_engine.tds_return_due_date is the authority."""
    q4 = [s for s in ob._tds_obligations(FY)
          if s["obligation_type"] == "TDS24Q" and s["period_start"] == "2026-01-01"]
    assert [s["due_date"] for s in q4] == ["2026-05-31"]


def test_it_reaches_the_calendar_through_a_tds_engagement():
    specs = ob.obligations_for_service("TDS Compliance", FY)
    assert _types(specs).count("TDS24Q") == 4


def test_a_gst_engagement_owes_no_salary_statement():
    assert "TDS24Q" not in _types(ob.obligations_for_service("GST Compliance", FY))


# ── the label is the PERIOD's form number ────────────────────────────────────

def test_the_label_names_the_form_and_the_quarter():
    labels = {s["period_label"] for s in ob._tds_obligations(FY)}
    assert "TDS 24Q Q3 FY 2025-26" in labels


def test_from_fy_2026_27_the_label_is_form_138():
    """CBDT Notification 22/2026 renumbered 24Q to 138. The kind code stays
    TDS24Q — it is an internal key existing rows carry — and only what the CA
    READS moves, exactly as 26Q and 27Q already do."""
    specs = ob._tds_obligations(FY_2025_ACT)
    labels = {s["period_label"] for s in specs}
    assert "TDS 138 Q1 FY 2026-27" in labels
    assert not any("24Q Q" in l for l in labels)
    assert _types(specs).count("TDS24Q") == 4, "the ROUTING key must not move"


# ── the docstring that was the reason nobody looked ─────────────────────────

def test_the_payroll_docstring_is_true_now():
    """It said 24Q was "already emitted by _tds_obligations" while it was not.
    A comment asserting a thing exists is how it goes on not existing."""
    import inspect
    src = inspect.getsource(ob._payroll_obligations)
    assert "24Q" in src, "the payroll side must still say where 24Q lives"
    assert "already emitted" not in src, (
        "the claim that made this invisible is back, word for word")
    # And the claim it makes is checkable from here.
    assert "TDS24Q" in _types(ob._tds_obligations(FY))


def test_the_monthly_deposit_is_still_a_different_obligation():
    """Rule 30's monthly §192 DEPOSIT and Rule 31A's quarterly STATEMENT are
    two obligations. Adding one must not have replaced the other."""
    pay = ob.obligations_for_service("Payroll", FY)
    kinds = {s["obligation_type"] for s in pay}
    assert "TDS_SALARY_DEPOSIT" in kinds
    assert "TDS24Q" not in kinds, (
        "the payroll side is emitting it too — the calendar now shows the same "
        "deadline twice for a firm that holds both engagements, and the dedup "
        "key (obligation_type, period_start) does not catch it")


# ── the screens were already waiting for it ──────────────────────────────────

_WEB = Path(__file__).resolve().parents[2] / "web"


def test_the_deadline_list_could_already_filter_to_a_type_nothing_generated():
    """Both screens list TDS24Q among the types. Recorded as a test rather than
    a note because it is the measure of the gap: the filter existed, the rows
    did not."""
    for rel in ("app/deadlines/page.tsx", "app/risks/page.tsx"):
        f = _WEB / rel
        if not f.is_file():
            continue
        code = re.sub(r"/\*.*?\*/", "", f.read_text(), flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        assert '"TDS24Q"' in code, f"{rel} no longer offers the filter"


def test_marking_it_filed_says_what_it_does_not_lock():
    """`_NO_FILING_ROW_REASON` exists to answer PER TYPE why a tick closes no
    GST period. It named 26Q and not the other two."""
    from routers.compliance import _NO_FILING_ROW_REASON
    for t in ("TDS24Q", "TDS26Q", "TDS27Q"):
        assert t in _NO_FILING_ROW_REASON, t
        assert "GST period lock does not apply" in _NO_FILING_ROW_REASON[t]
