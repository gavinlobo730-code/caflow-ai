"""CGST Rule 37A — the supplier did not file their GSTR-3B (GST-28, second half).

WHAT WAS MISSING
    `itc_reversal_register` has accepted a `rule_37a` ground since migration
    362 and GSTR-3B Table 4(B)(2) has a box for it, and NOTHING produced a
    figure. Rule 37 — the recipient's own 180-day default — had a report;
    Rule 37A had a reason code and no way to reach it.

    The two are unrelated and share only that box. Rule 37 is about what the
    RECIPIENT did (the supplier went unpaid); Rule 37A is about what the
    SUPPLIER did (they declared the invoice in GSTR-1 and never filed the
    GSTR-3B). One the client can fix by paying, the other only the supplier
    can fix.

THE ONE FACT THE PRODUCT CANNOT HOLD
    Whether the supplier furnished their GSTR-3B. GSTR-2B is generated FROM
    filed GSTR-1s, so a document appearing in it proves the GSTR-1 and says
    nothing about the 3B. Every answer names that and no credit is reported as
    reversible on a supplier nobody has checked — guessing "filed" leaves a
    reversal undone with §50 interest running, and guessing "not filed"
    reverses credit the client is entitled to.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import date

import pytest

from domain.gst import rule_37a as rule

API = pathlib.Path(__file__).resolve().parent.parent


# ── the two dates ────────────────────────────────────────────────────────────

def test_both_deadlines_hang_off_the_END_of_the_availment_year():
    """The FY in which the credit was AVAILED ends on 31 March, and both dates
    follow that end — not the FY's own September and November, which would be
    a year early, and not sixty days after the supplier's date, which would be
    two months late."""
    assert rule.supplier_deadline("2025-26") == date(2026, 9, 30)
    assert rule.recipient_deadline("2025-26") == date(2026, 11, 30)
    assert rule.supplier_deadline("2023-24") == date(2024, 9, 30)
    assert rule.recipient_deadline("2023-24") == date(2024, 11, 30)


def test_the_dates_are_pinned_so_a_change_is_deliberate():
    """Notification 26/2022-CT. [S]-graded — this environment's proxy refuses
    every .gov.in — so the constants are pinned rather than trusted."""
    assert rule.SUPPLIER_DEADLINE_MONTH_DAY == (9, 30)
    assert rule.RECIPIENT_DEADLINE_MONTH_DAY == (11, 30)
    assert "26/2022" in rule.RULE


def test_a_malformed_financial_year_raises_rather_than_guessing():
    for bad in ("2025", "", "not-a-year", None):
        with pytest.raises(ValueError):
            rule.supplier_deadline(bad)


# ── what the report says ─────────────────────────────────────────────────────

def _report(**kw):
    base = dict(
        financial_year="2025-26", as_of=date(2026, 10, 15),
        matched_bills=[
            {"vendor_id": "V1", "igst_paise": 100000},
            {"vendor_id": "V1", "cgst_paise": 5000, "sgst_paise": 5000},
            {"vendor_id": "V2", "igst_paise": 20000, "cess_paise": 1000},
        ],
        vendors={"V1": {"name": "Acme Tools", "gstin": "27AAPFU0939F1ZV"},
                 "V2": {"name": "Beta Traders", "gstin": "29AAPFU0939F1ZR"}})
    base.update(kw)
    return rule.build(**base).as_dict()


def test_the_exposure_is_grouped_per_supplier_and_totalled():
    r = _report()
    assert r["totals"]["supplier_count"] == 2
    assert r["totals"]["bill_count"] == 3
    assert r["totals"]["total_paise"] == 100000 + 10000 + 21000
    acme = r["suppliers"][0]
    assert acme["vendor_name"] == "Acme Tools"
    assert acme["total_paise"] == 110000
    assert acme["bill_count"] == 2


def test_the_largest_exposure_comes_first():
    """That is the supplier worth checking without scrolling."""
    r = _report()
    assert [s["vendor_name"] for s in r["suppliers"]] \
        == ["Acme Tools", "Beta Traders"]


def test_NO_supplier_is_ever_reported_as_having_filed_or_not():
    """The one fact this product cannot hold. Guessing 'filed' leaves a
    reversal undone with §50 interest running; guessing 'not filed' reverses
    credit the client is entitled to."""
    r = _report()
    assert all(s["supplier_filed_gstr3b"] is None for s in r["suppliers"])
    assert rule.SUPPLIER_FILING_NOT_HELD in r["caveats"]
    assert "GSTR-2B is generated FROM filed GSTR-1s" in rule.SUPPLIER_FILING_NOT_HELD
    assert "Search Taxpayer" in rule.SUPPLIER_FILING_NOT_HELD


def test_the_two_deadlines_are_reported_as_passed_or_not():
    before = _report(as_of=date(2026, 9, 1))
    between = _report(as_of=date(2026, 10, 15))
    after = _report(as_of=date(2026, 12, 1))
    assert (before["supplier_deadline_passed"],
            before["recipient_deadline_passed"]) == (False, False)
    assert (between["supplier_deadline_passed"],
            between["recipient_deadline_passed"]) == (True, False)
    assert (after["supplier_deadline_passed"],
            after["recipient_deadline_passed"]) == (True, True)


def test_the_deadline_day_itself_has_not_passed():
    """'by the 30th of September' includes the 30th."""
    on_the_day = _report(as_of=date(2026, 9, 30))
    assert on_the_day["supplier_deadline_passed"] is False
    assert _report(as_of=date(2026, 10, 1))["supplier_deadline_passed"] is True


def test_a_supplier_with_no_GSTIN_is_a_named_gap():
    """Their return filing cannot be looked up on the portal without one."""
    r = _report(vendors={"V1": {"name": "Acme Tools"},
                         "V2": {"name": "Beta", "gstin": "29AAPFU0939F1ZR"}})
    assert any("no GSTIN recorded" in g for g in r["gaps"])


def test_nothing_matched_is_a_named_gap_and_not_a_clean_bill_of_health():
    """A nil here would read as 'no exposure'. It means the reconciliation has
    not been run — and Rule 37A reaches a supply whose invoice the supplier DID
    declare in GSTR-1, which is exactly what a 2B match proves."""
    r = _report(matched_bills=[])
    assert r["totals"]["total_paise"] == 0
    assert any("Run the GSTR-2B reconciliation first" in g for g in r["gaps"])


def test_the_re_availment_limb_is_stated_because_it_decides_the_BOX():
    """Where the supplier later files, the credit may be re-availed — which is
    why this reversal is RECLAIMABLE (Table 4(B)(2), released into 4(D)(1))
    rather than absolute under 4(B)(1)."""
    r = _report()
    assert rule.RE_AVAILMENT in r["caveats"]
    assert "4(B)(2)" in rule.RE_AVAILMENT
    assert "4(B)(1)" in rule.RE_AVAILMENT


def test_the_interest_is_NOT_computed_and_says_why():
    """Rule 37A makes the unreversed credit payable 'along with interest
    payable under section 50', and §50(1)'s 18% is settled — but the date it
    runs FROM is not stated, and `domain/gst/late_filing.py` already records
    that the same silence in Rule 37 is why that report shows two readings.
    A single figure here would be a third answer to an open question."""
    r = _report()
    assert rule.NOT_COMPUTED in r["caveats"]
    assert not any("interest_paise" in s for s in r["suppliers"])
    assert "interest_paise" not in r["totals"]


def test_nothing_is_posted_and_the_report_says_so():
    r = _report()
    assert r["ca_review_required"] is True
    assert rule.POSTS_NOTHING in r["caveats"]
    assert "rule_37a" in rule.POSTS_NOTHING


def test_the_module_reaches_no_database_and_raises_no_http():
    """`domain/gst/rule_37a.py` is the RULE. It takes rows and returns an
    answer — the fetch is the service's job, and a db handle here would make
    the rule untestable without one."""
    src = (API / "domain" / "gst" / "rule_37a.py").read_text(encoding="utf-8")
    for forbidden in ("get_supabase", ".table(", "HTTPException", "requests.",
                      "httpx."):
        assert forbidden not in src, forbidden
    assert "db" not in inspect.signature(rule.build).parameters


# ── the service ──────────────────────────────────────────────────────────────

class _Q:
    def __init__(self, store, table):
        self.store = store
        self.table_name = table
        self._rows = list(store.get(table, []))

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": [dict(r) for r in self._rows]})()


class _FakeDB:
    def __init__(self, **tables):
        self.store = {k: list(v) for k, v in tables.items()}

    def table(self, name):
        return _Q(self.store, name)


def _rec(rid, **kw):
    base = {"id": rid, "firm_id": "F1", "client_id": "C1",
            "supplier_gstin": "27AAPFU0939F1ZV", "supplier_name": "Acme Tools",
            "return_period": "062025", "match_status": "matched",
            "igst_paise": 10000, "itc_available": True}
    base.update(kw)
    return base


def test_the_service_reads_only_MATCHED_documents():
    """Rule 37A reaches a supply whose invoice the supplier DID declare in
    GSTR-1 — that is its opening words. A bill missing from 2B is a
    §16(2)(aa) problem and belongs in the reconciliation, and reporting it
    here would send the CA to chase the wrong thing."""
    from services import rule_37a_service as svc
    db = _FakeDB(gstr2a_records=[
        _rec("r1"),
        _rec("r2", match_status="missing_in_2b", igst_paise=99999),
        _rec("r3", match_status="amount_mismatch", igst_paise=88888),
    ])
    out = svc.build(db, "F1", "C1", financial_year="2025-26")
    assert out["totals"]["total_paise"] == 10000


def test_the_service_reads_only_THIS_financial_years_periods():
    """MMYYYY does not sort — '042025' is greater than '032026' — so the month
    and the year are split and tested. A string range would drop the first
    nine months of every year and keep three belonging to the next."""
    from services import rule_37a_service as svc
    db = _FakeDB(gstr2a_records=[
        _rec("in-apr", return_period="042025", igst_paise=100),
        _rec("in-dec", return_period="122025", igst_paise=200),
        _rec("in-mar", return_period="032026", igst_paise=400),
        _rec("before", return_period="032025", igst_paise=9999),
        _rec("after", return_period="042026", igst_paise=8888),
    ])
    out = svc.build(db, "F1", "C1", financial_year="2025-26")
    assert out["totals"]["total_paise"] == 700


def test_a_document_the_PORTAL_says_carries_no_credit_is_left_out():
    """`itc_available` is 2B's own `itcavl`. A document the portal has already
    marked unavailable never gave the client anything to reverse."""
    from services import rule_37a_service as svc
    db = _FakeDB(gstr2a_records=[
        _rec("r1", igst_paise=10000),
        _rec("r2", igst_paise=50000, itc_available=False),
    ])
    out = svc.build(db, "F1", "C1", financial_year="2025-26")
    assert out["totals"]["total_paise"] == 10000


def test_another_firms_or_clients_records_never_reach_the_answer():
    """The service-role key bypasses RLS, so `.eq("firm_id", …)` is the
    primary isolation control rather than a narrowing convenience."""
    from services import rule_37a_service as svc
    db = _FakeDB(gstr2a_records=[
        _rec("mine", igst_paise=10000),
        _rec("zz-other-firm", firm_id="F2", igst_paise=70000),
        _rec("zz-other-client", client_id="C2", igst_paise=80000),
    ])
    out = svc.build(db, "F1", "C1", financial_year="2025-26")
    assert out["totals"]["total_paise"] == 10000


def test_the_service_never_reads_supplier_filed_on_as_the_answer():
    """That column records when the GSTR-1 was filed, which is what 2B
    communicates. Rule 37A turns on the GSTR-3B, which 2B does not carry at
    all — reading it would report every supplier as compliant."""
    from services import rule_37a_service as svc
    db = _FakeDB(gstr2a_records=[
        _rec("r1", supplier_filed_on="2025-07-11"),
    ])
    out = svc.build(db, "F1", "C1", financial_year="2025-26")
    assert all(s["supplier_filed_gstr3b"] is None for s in out["suppliers"])
    tree = ast.parse((API / "services" / "rule_37a_service.py")
                     .read_text(encoding="utf-8"))
    # It may be NAMED in prose — the docstring calls it the trap — but it must
    # not be read in code. Docstrings are stripped before the walk.
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body.pop(0)
    names = {n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("supplier_filed_on" in n for n in names), (
        "supplier_filed_on reached the code — it is the GSTR-1's date, not the "
        "GSTR-3B's")


def test_a_malformed_financial_year_is_a_422_not_a_500():
    from fastapi import HTTPException
    from services import rule_37a_service as svc
    with pytest.raises(HTTPException) as e:
        svc.build(_FakeDB(gstr2a_records=[]), "F1", "C1",
                  financial_year="not-a-year")
    assert e.value.status_code == 422


def test_the_service_posts_nothing():
    names_src = (API / "services" / "rule_37a_service.py").read_text(
        encoding="utf-8")
    for forbidden in ("_create_journal", "journal_entries", ".insert(",
                      ".update(", ".delete("):
        assert forbidden not in names_src, forbidden


def test_the_endpoint_is_mounted_and_typed():
    """`fy: FYLabel = Query(...)` validates NOTHING — FastAPI builds the field
    from `Query()` in the default position and discards the Annotated
    metadata. CLAUDE.md records it; this endpoint uses the Annotated form."""
    import main
    paths = [r.path for r in main.app.routes if getattr(r, "path", "")]
    assert "/api/gst-workspace/itc/rule37a" in paths
    src = (API / "routers" / "gst_workspace.py").read_text(encoding="utf-8")
    block = src[src.index("def rule37a_supplier_not_filed"):]
    block = block[:block.index("@router")]
    assert "Annotated[FYLabel, Query(" in block
    assert "CA REVIEW REQUIRED" in block
