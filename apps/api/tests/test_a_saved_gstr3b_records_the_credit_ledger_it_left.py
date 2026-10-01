"""Every door that SAVES a GSTR-3B records the credit ledger it left (gst-06).

THE CHAIN ONLY WORKS IF EVERY WRITER FEEDS IT. The next return opens with this
return's closing balance, found by `credit_closing_as_of`, so a saved return that
did not record one is a hole the chain cannot cross — and the GSTR-3B is saved by
FOUR different doors that no one of them sees the others of:

    * `POST /api/gst-workspace/gstr3b`          — the client workspace's save
    * `POST /api/gst-workspace/gstr3b/{id}/recompute?dry_run=false`
    * `lib/data/gst.ts::saveGSTR3BReturn`       — the firm-level screen, straight
                                                  over PostgREST (so `rbac()` and
                                                  the API never run)
    * the client page's `saveComputed`          — sends the block to the first

The first two are exercised; the last two are the browser's and are held by a
source scan from this side, because a guard written in `apps/web` would assert
the browser against a copy of itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
from domain.gst import credit_ledger as cl
from domain.gst.credit_ledger import CreditBalance
from tests.e2e_harness import FakeDB, wire_e2e

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
FIRM = "firm-1"
CLIENT = "client-1"
GSTIN = "27AAPFU0939F1ZV"          # checksum-valid (tests/fixtures/gstin.json)
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}

TEN_COLUMNS = (
    "credit_opening_igst_paise", "credit_opening_cgst_paise",
    "credit_opening_sgst_paise", "credit_opening_cess_paise",
    "credit_closing_igst_paise", "credit_closing_cgst_paise",
    "credit_closing_sgst_paise", "credit_closing_cess_paise",
    "credit_closing_as_of", "credit_opening_source",
)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    d.seed("clients", {
        "id": CLIENT, "firm_id": FIRM, "client_name": "Acme Industries",
        "legal_name": "Acme Industries Private Limited", "gstin": GSTIN,
        "state_code": "27", "gst_filing_frequency": "monthly",
        "gst_registration_date": None, "gst_registration_type": None,
        "composition_category": None,
    })
    return d


def _block(period_end="2026-06-30", closing=CreditBalance(igst_paise=365396165),
           opening=CreditBalance(igst_paise=365496165), source=cl.SOURCE_RECORDED):
    o = cl.OpeningCredit(balance=opening, source=source, window_start="2026-06-01")
    return cl.ledger_block(o, closing=closing, window_end=period_end)


def _save(period="062026", credit_ledger=None, **over):
    body = {"client_id": CLIENT, "period": period, "gstin": GSTIN,
            "payload_json": {}, "summary_json": {},
            "tax_liability_paise": 100000, "itc_claimed_paise": 0,
            "net_tax_paise": 0}
    if credit_ledger is not None:
        body["credit_ledger"] = credit_ledger
    body.update(over)
    return gw.save_gstr3b(gw.SaveGSTR3BRequest(**body), current_user=USER)


def test_a_save_records_the_ten_columns_the_chain_reads(db):
    res = _save(credit_ledger=_block())
    assert res["success"] is True
    row = db.rows("gstr3b_returns")[0]
    for col in TEN_COLUMNS:
        assert col in row, col
    assert row["credit_closing_igst_paise"] == 365396165
    assert row["credit_opening_igst_paise"] == 365496165
    assert row["credit_closing_as_of"] == "2026-06-30"
    assert row["credit_opening_source"] == "recorded"


def test_what_a_save_records_is_what_the_next_return_chains_from(db):
    """The two halves wired end to end: the columns a save writes are exactly
    the ones the chain reader selects."""
    import services.gst_credit_ledger_service as svc
    _save(credit_ledger=_block())
    prior = svc.previous_closing(db, FIRM, CLIENT, GSTIN, "2026-07-01")
    assert prior is not None
    assert prior.balance.igst_paise == 365396165 and prior.period == "062026"


def test_a_save_that_states_no_ledger_leaves_what_the_row_already_records(db):
    _save(credit_ledger=_block())
    _save()                                           # a re-save with no statement
    row = db.rows("gstr3b_returns")[0]
    assert row["credit_closing_igst_paise"] == 365396165, (
        "None is 'not stated'; it must never be written as a nil ledger")
    assert len(db.rows("gstr3b_returns")) == 1


def test_a_re_save_replaces_the_statement_with_the_new_one(db):
    _save(credit_ledger=_block())
    _save(credit_ledger=_block(closing=CreditBalance(igst_paise=7)))
    assert db.rows("gstr3b_returns")[0]["credit_closing_igst_paise"] == 7


def test_a_statement_that_is_not_whole_is_refused_and_nothing_is_saved(db):
    bad = _block()
    bad["closing"] = {"igst_paise": 1}
    with pytest.raises(HTTPException) as e:
        _save(credit_ledger=bad)
    assert e.value.status_code == 422
    assert not db.rows("gstr3b_returns")


def test_a_statement_dated_for_another_window_is_refused(db):
    """The chain finds the previous return by the EXACT day before the new window,
    so a wrong date would orphan or mis-chain every return after it."""
    with pytest.raises(HTTPException) as e:
        _save(credit_ledger=_block(period_end="2026-05-31"))
    assert e.value.status_code == 422
    assert "2026-06-30" in e.value.detail
    assert not db.rows("gstr3b_returns")


def test_a_quarterly_registrations_return_is_dated_at_the_quarters_end(db):
    db.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": "29AAGCB7383J1Z4",
        "state_code": "29", "registration_type": "regular",
        "filing_frequency": "quarterly", "trade_name": "depot", "effective_from": None,
        "effective_to": None, "notes": None, "created_at": None, "deleted_at": None,
        "composition_category": None})
    body = {"client_id": CLIENT, "period": "042026", "gstin": "29AAGCB7383J1Z4",
            "payload_json": {}, "summary_json": {}, "tax_liability_paise": 0,
            "itc_claimed_paise": 0, "net_tax_paise": 0}
    with pytest.raises(HTTPException):                # a monthly end for a quarter
        gw.save_gstr3b(gw.SaveGSTR3BRequest(
            **body, credit_ledger=_block(period_end="2026-04-30")), current_user=USER)
    ok = gw.save_gstr3b(gw.SaveGSTR3BRequest(
        **body, credit_ledger=_block(period_end="2026-06-30")), current_user=USER)
    assert ok["success"] is True


# ── The recompute door ──────────────────────────────────────────────────────

def test_recompute_rewrites_all_ten_columns_so_a_stale_closing_is_never_chained():
    """Source scan: `recompute_gstr3b`'s update is an inline literal (the column
    parser reads only literals) and has to carry every credit column, or a
    recomputed draft would chain the balance it had BEFORE it was recomputed."""
    src = (REPO / "apps/api/routers/gst_workspace.py").read_text(encoding="utf-8")
    body = src[src.index("def recompute_gstr3b"):]
    update = body[body.index('.table("gstr3b_returns").update({'):]
    update = update[:update.index("}).eq(")]
    for col in TEN_COLUMNS:
        assert f'"{col}"' in update, f"recompute no longer rewrites {col}"


# ── The two browser doors ───────────────────────────────────────────────────

def test_the_firm_level_save_writes_the_ten_columns_from_the_servers_block():
    """`saveGSTR3BReturn` writes straight over PostgREST, so nothing server-side
    can add the credit columns to it — it has to name them."""
    src = (WEB / "lib" / "data" / "gst.ts").read_text(encoding="utf-8")
    fn = src[src.index("export async function saveGSTR3BReturn"):]
    upsert = fn[fn.index(".upsert({"):fn.index("}, {")] if "}, {" in fn else fn
    for col in TEN_COLUMNS:
        assert re.search(rf"\b{col}:\s*result\.credit_ledger\?\.", upsert), (
            f"the firm-level GSTR-3B save no longer writes {col} from the server's block")


def test_the_firm_level_save_never_computes_a_ledger_figure():
    """Every figure is the server's: no arithmetic between the block and the column."""
    src = (WEB / "lib" / "data" / "gst.ts").read_text(encoding="utf-8")
    for line in src.splitlines():
        if re.match(r"\s*credit_(opening|closing)_", line):
            assert not re.search(r"[-+*/]\s*\w|Number\(|parseFloat|parseInt|\|\|\s*0", line.split(":", 1)[1]), line


def test_the_client_workspace_save_sends_the_block_it_was_served():
    src = (WEB / "app" / "clients" / "[id]" / "compliance" / "gst" / "page.tsx").read_text(encoding="utf-8")
    # The page holds a saveComputed for GSTR-1 and one for GSTR-3B; the 3B one is
    # the one that sends `rcm_cash_paise`.
    fns = [part[:part.index("setSavingComputed(false)")]
           for part in src.split("async function saveComputed")[1:]
           if "setSavingComputed(false)" in part]
    fn = next(f for f in fns if "rcm_cash_paise" in f)
    assert "credit_ledger: d.credit_ledger" in fn, (
        "the save would drop the block and Pydantic would not say so")
