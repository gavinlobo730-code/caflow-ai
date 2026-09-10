"""IT-18 (part 2) — the AIS reconciliation is kept, and states no tax figure.

WHAT WAS WRONG
    apps/web/app/income-tax/ais/page.tsx was 805 lines holding a JSON parser,
    a transaction table and a books-comparison grid, entirely in React state.
    A grep of it for `api.`, `apiFetch`, `supabase.from`, `fetch(` and
    `localStorage` returned NOTHING: the reconciliation was gone on refresh.
    Backend-side there was no AIS table, no AIS endpoint and no AIS service.

    Its own footer said the data was "stored locally in your browser only",
    which was not true either. It was not stored at all.

    IT Act §285BB is the department's statement of what OTHERS reported about
    the taxpayer, and a CA's working against it is what a §143(1)(a)
    adjustment is answered from. A working paper that cannot be re-read
    tomorrow is not a working paper.

TWO THINGS THE OLD SCREEN ASSERTED THAT NOTHING KNEW
    1. "Est. Tax Impact (30%)" — the difference times 30%, in an orange box,
       in rupees. Nothing on that screen knew the client's regime, entity type
       or slab, or whether the receipt was income at all.
    2. A BLANK books box meant "Not in Books", which fed "Est. Undeclared
       Amount" and lit a red "Discrepancies Found" banner. So an uploaded and
       not-yet-reviewed statement reported every line as undeclared income.

WHAT THIS PINS
    That the statement, its lines and each line's working are persisted and
    read back; that an unreviewed line is counted apart from a finding; that
    the four self-contradicting conclusions are refused; that a published line
    cannot be deleted; that a re-upload of the same bytes is idempotent; that
    a half-done working carries onto a fresh statement ONLY where the line is
    identical; and that no tax figure is computed anywhere in the module.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from services import ais_service
from domain.income_tax import ais as ais_domain

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
AY = "2026-27"

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"


@pytest.fixture(autouse=True)
def _clean():
    ais_service._reset_mock_state()
    yield
    ais_service._reset_mock_state()


def _statement(*lines) -> str:
    """An AIS JSON in the portal's own envelope."""
    cats = []
    for source, nature, payer, amount, tds in lines:
        cats.append({
            "informationSource": source,
            "informationDescription": [
                {"label": "Nature of transaction", "value": nature},
                {"label": "Deductor", "value": payer},
            ],
            "amount": amount,
            "tdsAmount": tds,
        })
    return json.dumps({"AnnualInformationStatement": {
        "taxpayerInfo": {"pan": "ABCPK1234F", "name": "Kaveri Traders"},
        "aisInformation": {"aisSubInformationCategory": cats},
    }})


THREE_LINES = _statement(
    ("HDFC Bank Ltd", "Interest from savings bank", "HDFC Bank Ltd", "45000", "0"),
    ("Zenith Systems Pvt Ltd", "TDS on salary", "Zenith Systems Pvt Ltd", "1250000", "125000"),
    ("NSE Clearing", "Sale of securities", "Kotak Securities", "820000", "0"),
)


def _upload(raw=THREE_LINES, ay=AY):
    return ais_service.upload_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=ay,
        raw=raw, file_name="AIS_2026-27.json", uploaded_by=USER)


# ── It is kept ─────────────────────────────────────────────────────────────

def test_the_statement_is_read_back_after_the_upload_call_returns():
    _upload()
    # A separate read, exactly as a page load after a refresh does it.
    got = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)
    assert got["upload"]["pan"] == "ABCPK1234F"
    assert got["upload"]["taxpayer_name"] == "Kaveri Traders"
    assert len(got["records"]) == 3
    assert got["summary"]["total_amount_paise"] == (45000 + 1250000 + 820000) * 100
    assert got["summary"]["total_tds_paise"] == 125000 * 100


def test_the_portals_own_wording_is_kept_beside_the_bucket():
    """A bucket is a lossy reading; the wording is what a CA searches for."""
    got = _upload()
    interest = next(r for r in got["records"]
                    if r["transaction_type"] == "Interest")
    assert interest["information_label"] == "Interest from savings bank"
    assert interest["information_source"] == "HDFC Bank Ltd"


def test_the_working_is_read_back_too():
    got = _upload()
    salary = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    ais_service.save_working(firm_id=FIRM, record_id=salary["id"],
                             books_amount_paise=1250000 * 100, reviewed_by=USER)
    again = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)
    line = next(r for r in again["records"] if r["id"] == salary["id"])
    assert line["status"] == "matched"
    assert line["books_amount_paise"] == 1250000 * 100
    assert line["reviewed_at"]


def test_the_same_file_uploaded_twice_is_one_statement():
    first = _upload()
    second = _upload()
    assert first["upload"]["id"] == second["upload"]["id"]
    assert len(second["uploads"]) == 1


# ── An unreviewed line is not a finding ────────────────────────────────────

def test_an_unreviewed_line_is_counted_apart_and_is_in_no_open_figure():
    got = _upload()
    s = got["summary"]
    assert s["not_reviewed_count"] == 3
    # The old screen put all three into "Est. Undeclared Amount" here.
    assert s["not_in_books_paise"] == 0
    assert s["shortfall_paise"] == 0
    assert s["open_paise"] == 0


def test_a_null_books_figure_is_not_a_nil_one():
    got = _upload()
    line = got["records"][0]
    saved = ais_service.save_working(
        firm_id=FIRM, record_id=line["id"], books_amount_paise=None)
    assert saved["status"] == "not_reviewed"
    assert saved["books_amount_paise"] is None

    nil = ais_service.save_working(
        firm_id=FIRM, record_id=line["id"], books_amount_paise=None,
        status="not_in_books", reviewed_by=USER)
    assert nil["status"] == "not_in_books"
    assert nil["books_amount_paise"] == 0


def test_a_line_the_books_do_not_carry_is_an_open_figure():
    got = _upload()
    stock = next(r for r in got["records"]
                 if r["transaction_type"] == "Stock Sale")
    ais_service.save_working(firm_id=FIRM, record_id=stock["id"],
                             books_amount_paise=None, status="not_in_books",
                             reviewed_by=USER)
    s = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)["summary"]
    assert s["not_in_books_paise"] == 820000 * 100
    assert s["not_reviewed_count"] == 2


def test_a_shortfall_is_the_difference_and_an_overstatement_is_not_negative():
    got = _upload()
    interest = next(r for r in got["records"]
                    if r["transaction_type"] == "Interest")
    salary = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    # Books carry LESS than AIS: a shortfall of ₹5,000.
    ais_service.save_working(firm_id=FIRM, record_id=interest["id"],
                             books_amount_paise=40000 * 100, reviewed_by=USER)
    # Books carry MORE than AIS. That is still a question, but it is not
    # undeclared income and must not net off the shortfall above.
    ais_service.save_working(firm_id=FIRM, record_id=salary["id"],
                             books_amount_paise=1300000 * 100, reviewed_by=USER)
    s = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)["summary"]
    assert s["shortfall_paise"] == 5000 * 100
    assert s["by_status"]["amount_mismatch"] == 2


# ── No tax figure, anywhere ────────────────────────────────────────────────

def test_the_summary_states_no_tax_and_says_why():
    got = _upload()
    line = got["records"][0]
    ais_service.save_working(firm_id=FIRM, record_id=line["id"],
                             books_amount_paise=None, status="not_in_books",
                             reviewed_by=USER)
    s = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)["summary"]
    assert "tax_impact_paise" not in s
    assert "estimated_tax_paise" not in s
    assert "regime" in s["tax_impact_refused"]


def test_no_module_in_the_ais_path_applies_a_rate_to_a_difference():
    """The old screen's `undeclaredPaise * 30 / 100`, stated as a rule.

    Read with `ast`, not grep, so it is the CODE that is checked and not the
    prose about it — the docstrings on this path discuss the 30% precisely
    because it was removed, and a text search cannot tell the two apart. What
    the rule forbids is a multiplication or division by anything that could be
    a tax rate: no AIS module knows the client's regime, entity type or slab,
    so any such constant here is a figure nobody supplied.
    """
    import ast as _ast
    api = pathlib.Path(__file__).resolve().parents[1]
    # 100 is the paise/rupee conversion and is the only ratio allowed.
    allowed = {100, 1}
    for path in (api / "services" / "ais_service.py",
                 api / "domain" / "income_tax" / "ais.py",
                 api / "routers" / "ais.py"):
        tree = _ast.parse(path.read_text())
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.BinOp):
                continue
            if not isinstance(node.op, (_ast.Mult, _ast.Div, _ast.FloorDiv)):
                continue
            for side in (node.left, node.right):
                if isinstance(side, _ast.Constant) and isinstance(
                        side.value, (int, float)) and not isinstance(
                        side.value, bool):
                    assert side.value in allowed, (
                        f"{path.name}:{node.lineno} scales a figure by "
                        f"{side.value}")


# ── A conclusion cannot contradict its own working ─────────────────────────

def test_matched_cannot_be_asserted_over_two_different_figures():
    got = _upload()
    line = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.save_working(firm_id=FIRM, record_id=line["id"],
                                 books_amount_paise=1200000 * 100,
                                 status="matched", reviewed_by=USER)
    assert "not the same" in str(e.value)


def test_amount_mismatch_cannot_be_asserted_over_two_equal_figures():
    got = _upload()
    line = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    with pytest.raises(ais_service.AISRefused):
        ais_service.save_working(firm_id=FIRM, record_id=line["id"],
                                 books_amount_paise=1250000 * 100,
                                 status="amount_mismatch", reviewed_by=USER)


def test_not_in_books_cannot_be_asserted_over_a_books_figure():
    got = _upload()
    line = got["records"][0]
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.save_working(firm_id=FIRM, record_id=line["id"],
                                 books_amount_paise=45000 * 100,
                                 status="not_in_books", reviewed_by=USER)
    assert "carry nothing" in str(e.value)


def test_explained_needs_the_explanation():
    got = _upload()
    line = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.save_working(firm_id=FIRM, record_id=line["id"],
                                 books_amount_paise=1200000 * 100,
                                 status="explained", reviewed_by=USER)
    assert "143(1)(a)" in str(e.value)

    ok = ais_service.save_working(
        firm_id=FIRM, record_id=line["id"], books_amount_paise=1200000 * 100,
        status="explained", note="₹50,000 is the March salary credited on "
                                 "2 April and taxable in the next year.",
        reviewed_by=USER)
    assert ok["status"] == "explained"
    s = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)["summary"]
    # Explained is settled, so it is in no open figure.
    assert s["shortfall_paise"] == 0


def test_a_negative_books_figure_is_refused():
    got = _upload()
    with pytest.raises(ais_service.AISRefused):
        ais_service.save_working(firm_id=FIRM, record_id=got["records"][0]["id"],
                                 books_amount_paise=-1, reviewed_by=USER)


# ── The published statement is not editable here ───────────────────────────

def test_a_published_line_cannot_be_deleted_and_the_refusal_says_where_to_go():
    got = _upload()
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.delete_record(firm_id=FIRM, record_id=got["records"][0]["id"])
    assert "incometax.gov.in" in str(e.value)


def test_a_line_the_firm_added_is_labelled_apart_and_can_be_removed():
    got = _upload()
    added = ais_service.add_manual_record(
        firm_id=FIRM, client_id=CLIENT, upload_id=got["upload"]["id"],
        transaction_type="Rent Received", payer="Sundar Estates",
        amount_paise=240000 * 100)
    assert added["source"] == "manual"
    after = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)
    assert after["upload"]["record_count"] == 4
    assert after["upload"]["total_amount_paise"] == (
        45000 + 1250000 + 820000 + 240000) * 100

    ais_service.delete_record(firm_id=FIRM, record_id=added["id"])
    back = ais_service.get_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY)
    assert back["upload"]["record_count"] == 3
    assert back["upload"]["total_amount_paise"] == (45000 + 1250000 + 820000) * 100


def test_a_manual_line_needs_a_type_the_product_holds():
    got = _upload()
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.add_manual_record(
            firm_id=FIRM, client_id=CLIENT, upload_id=got["upload"]["id"],
            transaction_type="Crypto", payer="X", amount_paise=1)
    assert "Rent Received" in str(e.value)


# ── A fresh statement mid-review ───────────────────────────────────────────

def test_an_identical_line_carries_its_working_onto_the_new_statement():
    got = _upload()
    salary = next(r for r in got["records"] if r["transaction_type"] == "Salary")
    ais_service.save_working(firm_id=FIRM, record_id=salary["id"],
                             books_amount_paise=1250000 * 100, reviewed_by=USER)

    # The department publishes a revised AIS: the STOCK line moved, the
    # salary line did not.
    revised = _statement(
        ("HDFC Bank Ltd", "Interest from savings bank", "HDFC Bank Ltd", "45000", "0"),
        ("Zenith Systems Pvt Ltd", "TDS on salary", "Zenith Systems Pvt Ltd", "1250000", "125000"),
        ("NSE Clearing", "Sale of securities", "Kotak Securities", "910000", "0"),
    )
    after = _upload(raw=revised)
    assert after["upload"]["id"] != got["upload"]["id"]
    new_salary = next(r for r in after["records"]
                      if r["transaction_type"] == "Salary")
    assert new_salary["status"] == "matched"
    assert new_salary["books_amount_paise"] == 1250000 * 100


def test_a_line_whose_amount_moved_does_not_carry_its_working():
    got = _upload()
    stock = next(r for r in got["records"]
                 if r["transaction_type"] == "Stock Sale")
    ais_service.save_working(firm_id=FIRM, record_id=stock["id"],
                             books_amount_paise=820000 * 100, reviewed_by=USER)
    revised = _statement(
        ("NSE Clearing", "Sale of securities", "Kotak Securities", "910000", "0"),
    )
    after = _upload(raw=revised)
    line = after["records"][0]
    # Agreeing ₹8,20,000 to the books is not agreeing ₹9,10,000 to them.
    assert line["status"] == "not_reviewed"
    assert line["books_amount_paise"] is None


# ── The parser refuses rather than guessing ────────────────────────────────

def test_a_file_that_is_not_an_ais_is_refused_and_nothing_is_stored():
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.upload_statement(
            firm_id=FIRM, client_id=CLIENT, assessment_year=AY,
            raw='{"hello": "world"}', uploaded_by=USER)
    assert "AnnualInformationStatement" in str(e.value)
    assert ais_service.list_uploads(FIRM, CLIENT) == []


def test_a_pdf_is_refused_with_the_thing_to_do_instead():
    with pytest.raises(ais_service.AISRefused) as e:
        ais_service.upload_statement(
            firm_id=FIRM, client_id=CLIENT, assessment_year=AY,
            raw="%PDF-1.7 ...", uploaded_by=USER)
    assert "JSON" in str(e.value)


def test_a_row_whose_amount_cannot_be_read_is_kept_as_a_problem_not_a_zero():
    raw = json.dumps({"AnnualInformationStatement": {
        "taxpayerInfo": {"pan": "ABCPK1234F"},
        "aisInformation": {"aisSubInformationCategory": [
            {"informationSource": "HDFC Bank Ltd", "amount": "45000", "tdsAmount": "0"},
            {"informationSource": "Axis Bank Ltd", "amount": "not stated", "tdsAmount": "0"},
        ]}}})
    got = ais_service.upload_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY, raw=raw,
        uploaded_by=USER)
    assert len(got["records"]) == 1
    assert got["upload"]["problems"]
    assert "Axis Bank Ltd" in got["upload"]["problems"][0]
    # NOT ₹0 — a zero here says the payer reported nothing.
    assert got["summary"]["total_amount_paise"] == 45000 * 100


def test_a_pan_that_is_not_a_pan_is_reported_rather_than_stored():
    raw = json.dumps({"AnnualInformationStatement": {
        "taxpayerInfo": {"pan": "ABCP1234F"},
        "aisInformation": {"aisSubInformationCategory": [
            {"informationSource": "HDFC Bank Ltd", "amount": "45000", "tdsAmount": "0"},
        ]}}})
    got = ais_service.upload_statement(
        firm_id=FIRM, client_id=CLIENT, assessment_year=AY, raw=raw,
        uploaded_by=USER)
    assert got["upload"]["pan"] is None
    assert any("is not a PAN" in p for p in got["upload"]["problems"])


def test_an_amount_is_read_through_decimal_and_never_a_float():
    # 12345.67 through float * 100 is 1234566.9999999998.
    assert ais_domain.rupees_to_paise("12345.67") == 1234567
    assert ais_domain.rupees_to_paise("1,25,000") == 12500000
    assert ais_domain.rupees_to_paise("abc") is None
    assert ais_domain.rupees_to_paise("1e3") is None


# ── One firm cannot read another's statement ───────────────────────────────

def test_another_firms_statement_is_not_visible():
    _upload()
    other = "44444444-4444-4444-4444-444444444444"
    assert ais_service.list_uploads(other, CLIENT) == []
    assert ais_service.get_statement(
        firm_id=other, client_id=CLIENT, assessment_year=AY)["upload"] is None


def test_another_firms_record_cannot_be_worked_on():
    got = _upload()
    other = "44444444-4444-4444-4444-444444444444"
    with pytest.raises(ais_service.AISRefused):
        ais_service.save_working(firm_id=other,
                                 record_id=got["records"][0]["id"],
                                 books_amount_paise=1)


# ── The screen calls it ────────────────────────────────────────────────────

def test_the_ais_screen_calls_the_api_and_holds_no_parser_of_its_own():
    """The rule, not a spelling of it.

    The old page held `parseAISJSON`, `guessTransactionType` and a
    `rupeesToPaise` — three copies of logic that now lives in
    domain/income_tax/ais.py. A second implementation in the browser is the
    thing deleted twice before (the browser 24Q assembler, the browser GST
    reconciliation), and for the same reason: two implementations drift and
    only one of them is tested.
    """
    page = (WEB / "app" / "income-tax" / "ais" / "page.tsx").read_text()
    client = (WEB / "lib" / "api" / "index.ts").read_text()
    assert "api.ais." in page, "the AIS screen does not call the AIS API"
    assert "/api/ais/statement" in client and "/api/ais/uploads" in client, (
        "the API client has no AIS routes to call")
    for gone in ("parseAISJSON", "guessTransactionType",
                 "AnnualInformationStatement", "aisSubInformationCategory",
                 "informationDescription"):
        assert gone not in page, f"{gone} is still parsed in the browser"


def _without_comments(text: str) -> str:
    """The code the browser runs, without the prose about it.

    This file's own header explains at length what was removed and why, so a
    plain text search finds "undeclared" and "30%" in the explanation. The
    comments are not what ships to a CA's screen.
    """
    import re
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.strip().startswith("//"))


def test_the_screen_claims_no_tax_impact_and_no_browser_only_storage():
    raw = (WEB / "app" / "income-tax" / "ais" / "page.tsx").read_text()
    page = _without_comments(raw)
    # The orange box, and the arithmetic behind it.
    assert "Tax Impact" not in page
    assert "estimatedTaxPaise" not in page
    assert "30%" not in page
    assert "undeclared" not in page.lower()
    # The footer that said the working was kept in the browser, when it was
    # kept nowhere.
    assert "stored locally in your browser only" not in raw
    # And what stands where the figure was: the server's own sentence, so the
    # refusal reads the same wherever the figure is asked for.
    assert "tax_impact_refused" in page


# ── Through the router ─────────────────────────────────────────────────────

def _app_client(role="Executive"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.ais as ais_router

    app = FastAPI()
    app.include_router(ais_router.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": USER, "firm_id": FIRM, "role": role, "email": "e@f.test"}
    return TestClient(app, raise_server_exceptions=False)


def test_the_endpoints_answer_and_a_refusal_is_a_400_the_ca_can_read():
    tc = _app_client()
    res = tc.post("/api/ais/uploads", json={
        "client_id": CLIENT, "assessment_year": "2026-27", "raw": THREE_LINES,
        "file_name": "AIS.json"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    record = next(r for r in body["data"]["records"]
                  if r["transaction_type"] == "Salary")

    # A conclusion that contradicts its own working comes back as a sentence,
    # not a 500 and not a silent success.
    bad = tc.put(f"/api/ais/records/{record['id']}/working", json={
        "client_id": CLIENT, "books_amount_paise": 1, "status": "matched"})
    assert bad.status_code == 400
    assert "not the same" in bad.json()["detail"]

    good = tc.put(f"/api/ais/records/{record['id']}/working", json={
        "client_id": CLIENT, "books_amount_paise": 1250000 * 100})
    assert good.status_code == 200
    assert good.json()["data"]["status"] == "matched"

    again = tc.get("/api/ais/statement",
                   params={"client_id": CLIENT, "assessment_year": "2026-27"})
    line = next(r for r in again.json()["data"]["records"]
                if r["id"] == record["id"])
    assert line["status"] == "matched"


def test_an_assessment_year_whose_halves_disagree_is_refused():
    """'2026-28' passes ^\\d{4}-\\d{2}$ and then means 2026-27.

    An AIS filed under the wrong year is reconciled against the wrong return,
    and nothing about the request looks wrong. AYLabel is the same validator
    FYLabel uses, under a name that says which year it is.
    """
    tc = _app_client()
    res = tc.post("/api/ais/uploads", json={
        "client_id": CLIENT, "assessment_year": "2026-28", "raw": THREE_LINES})
    assert res.status_code == 422


def test_a_reviewer_cannot_write_a_working():
    """rbac('income_tax', 'compute') is Executive and above."""
    tc = _app_client(role="Reviewer")
    res = tc.post("/api/ais/uploads", json={
        "client_id": CLIENT, "assessment_year": "2026-27", "raw": THREE_LINES})
    assert res.status_code == 403
