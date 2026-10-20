"""The two doors outside Banking that read a client's bank lines read them with the server's access (POST-A-005, migration 524).

THE FAULT THIS ANSWERS
    Migration 524 makes the database ask `banking:read` when a signed-in person reads `bank_transactions`, and a read
    their tier hides comes back as ZERO ROWS, not as an error. Two places outside the banking module read that table
    under the caller's own sign-in for people who need not hold Banking:

      * the client's health score (anyone who reaches it: the calculate route asks `client:write`, the reads `client:read`): "is there an unreconciled bank line older
        than N days" feeds `accounting_quality` and the six-month hard override. Zero rows read as a clean bank, so the
        score came out false-healthy for a client whose bank has not been reconciled in a year — the answer a FAILED
        read is refused for (POST-A-282) arrived here as a successful empty one;
      * the GST return build (a person holding `gst:compute`): a bank charge on which the CA declared GST is a
        DOCUMENT of the return (BANK-24). Zero rows left its input credit and a bank receipt's output tax out of the
        return, which was wrong and said nothing.

    Both now read through the service client. Each route that reaches them asks `assert_client_access` first. What comes
    out of the health read is a count-like fact (an id and a date). What comes out of the GST read is the declared tax of
    a POSTED line and, with it, the line's description, which the GSTR-3B drill-down names the line by: that text is
    already in the narration of the line's posted journal entry, which migration 524 leaves alone (readable to every
    assigned staff role straight from the database, and over the API under `accounting:read`), and the unposted lines (the ones carrying narrations nobody has matched to a party) are
    not in this read.

THE RULE, NOT THE TWO SPELLINGS
    `test_every_read_of_the_bank_lines_in_the_health_router_goes_through_the_one_chooser` reads the router's own source
    and fails a fifth `.table("bank_transactions")` that does not go through `_bank_db`. The behavioural cases drive the
    real functions over a request client that holds NO rows (what row security leaves a blocked person) beside a service
    client that holds the line.
"""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

import routers.health as health
import services.gst_return_service as grs
from core.ist_clock import ist_today
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "FIRM-A", "CLI"
API = Path(__file__).resolve().parents[1]


def _old_unreconciled_line(db: FakeDB, days: int) -> None:
    db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": CLIENT, "reconciled": False,
        "transaction_date": (ist_today() - timedelta(days=days)).isoformat(),
        "description": "x", "debit_paise": 100, "credit_paise": 0,
    })


# ── the health score ─────────────────────────────────────────────────────────

@pytest.fixture
def blocked_person_and_the_server(monkeypatch):
    """(what the blocked person's sign-in sees: nothing, what the server sees: a line 100 days old and unreconciled)."""
    request_db, service_db = FakeDB(), FakeDB()
    _old_unreconciled_line(service_db, 100)
    monkeypatch.setattr(health, "_service_db", lambda: service_db)
    return request_db, service_db


def test_a_line_the_callers_tier_hides_still_counts_toward_the_accounting_quality_dimension(blocked_person_and_the_server):
    request_db, _ = blocked_person_and_the_server
    # 100 - 50 for a line older than 90 days; before this change the request client's empty answer scored 100
    assert health._dim_accounting_quality_db(request_db, CLIENT, FIRM) == 50


def test_a_line_the_callers_tier_hides_still_forces_the_six_month_override(monkeypatch):
    request_db, service_db = FakeDB(), FakeDB()
    _old_unreconciled_line(service_db, 200)
    monkeypatch.setattr(health, "_service_db", lambda: service_db)
    assert health._detect_hard_override_db(request_db, CLIENT, FIRM) == "bank_recon_6months"


def test_the_dimension_detail_names_the_factor_the_score_counted(blocked_person_and_the_server):
    request_db, _ = blocked_person_and_the_server
    factors = health._dimension_detail_db(request_db, CLIENT, FIRM, "accounting_quality")
    assert any("Unreconciled bank transactions" in f["label"] for f in factors), (
        "the score counts the line and the detail that explains the score does not name it")


def test_a_client_with_no_old_line_still_scores_clean_and_the_chooser_falls_back_to_the_callers_client(monkeypatch):
    """The control: nothing to find is still nothing found, and with no service client configured (mock mode, the
    in-memory doubles) the read goes to the client it was handed, as it did before."""
    monkeypatch.setattr(health, "_service_db", lambda: None)
    empty = FakeDB()
    assert health._dim_accounting_quality_db(empty, CLIENT, FIRM) == 100
    assert health._detect_hard_override_db(empty, CLIENT, FIRM) is None
    holds_it = FakeDB()
    _old_unreconciled_line(holds_it, 100)
    assert health._dim_accounting_quality_db(holds_it, CLIENT, FIRM) == 50
    assert health._bank_db(holds_it) is holds_it


def test_every_read_of_the_bank_lines_in_the_health_router_goes_through_the_one_chooser():
    tree = ast.parse((API / "routers" / "health.py").read_text())
    reads, through_the_chooser = 0, 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "bank_transactions"):
            continue
        reads += 1
        receiver = node.func.value
        if (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "_bank_db"):
            through_the_chooser += 1
    assert reads >= 4, "the scan found almost no read of the bank lines in the health router: it is reading nothing"
    assert reads == through_the_chooser, (
        f"{reads - through_the_chooser} read(s) of bank_transactions in routers/health.py do not go through _bank_db, "
        "so a person whose Banking is blocked would read zero rows and the score would count them as a clean bank")


# ── the GST return build ─────────────────────────────────────────────────────

def _posted_bank_line_declaring_gst(db: FakeDB) -> None:
    db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": CLIENT, "transaction_date": "2025-06-14", "description": "MONTHLY CHARGES",
        "debit_paise": 59_000, "credit_paise": 0, "category": "Expense", "match_status": "posted",
        "gst_rate_bps": 1800, "gst_is_interstate": False, "posted_journal_id": "J-1",
    })


def test_a_bank_line_the_callers_tier_hides_is_still_on_the_return(monkeypatch):
    request_db, service_db = FakeDB(), FakeDB()
    _posted_bank_line_declaring_gst(service_db)
    monkeypatch.setattr(grs, "_service_db", lambda: service_db)
    rows = grs._bank_lines_declaring_gst(request_db, FIRM, CLIENT, "2025-06-01", "2025-06-30")
    assert [r["description"] for r in rows] == ["MONTHLY CHARGES"], (
        "a person holding gst:compute and no Banking built a return without the bank charge their client declared GST on")


def test_the_return_reads_the_client_it_was_handed_when_there_is_no_service_client(monkeypatch):
    monkeypatch.setattr(grs, "_service_db", lambda: None)
    holds_it = FakeDB()
    _posted_bank_line_declaring_gst(holds_it)
    rows = grs._bank_lines_declaring_gst(holds_it, FIRM, CLIENT, "2025-06-01", "2025-06-30")
    assert len(rows) == 1


def test_the_service_read_is_still_scoped_to_the_firm_and_the_client(monkeypatch):
    """Reading with the server's access removes the database's second lock, so the filters the function writes are the
    only ones: another client's line, and another firm's, must not come back."""
    service_db = FakeDB()
    _posted_bank_line_declaring_gst(service_db)
    service_db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": "OTHER", "transaction_date": "2025-06-14", "description": "OTHER CLIENT",
        "debit_paise": 1, "credit_paise": 0, "gst_rate_bps": 1800, "posted_journal_id": "J-2"})
    service_db.seed("bank_transactions", {
        "firm_id": "FIRM-B", "client_id": CLIENT, "transaction_date": "2025-06-14", "description": "OTHER FIRM",
        "debit_paise": 1, "credit_paise": 0, "gst_rate_bps": 1800, "posted_journal_id": "J-3"})
    monkeypatch.setattr(grs, "_service_db", lambda: service_db)
    rows = grs._bank_lines_declaring_gst(FakeDB(), FIRM, CLIENT, "2025-06-01", "2025-06-30")
    assert [r["description"] for r in rows] == ["MONTHLY CHARGES"]


def test_the_return_builders_choose_the_service_client_before_the_fetch():
    """The rule on the function itself: it rebinds `db` to the service client (falling back to the one it was handed)
    before its first read of the table."""
    tree = ast.parse((API / "services" / "gst_return_service.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_bank_lines_declaring_gst")
    rebinding = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db" for t in n.targets)
                 and isinstance(n.value, ast.BoolOp) and isinstance(n.value.op, ast.Or)
                 and isinstance(n.value.values[0], ast.Call) and isinstance(n.value.values[0].func, ast.Name)
                 and n.value.values[0].func.id == "_service_db"
                 and isinstance(n.value.values[1], ast.Name) and n.value.values[1].id == "db"]
    assert rebinding, "_bank_lines_declaring_gst no longer reads through the service client"
    first_read = min(n.lineno for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table")
    assert rebinding[0].lineno < first_read, "the service client is chosen after the table is already read"
