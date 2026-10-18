"""A fixed-asset disposal that declares GST is refused inside a period whose return has been filed (POST-A-089).

WHAT WAS MISSING
    `create_asset`, `correct_asset` and `delete_asset` all ask the client's period lock, because the acquisition journal
    feeds GSTR-3B Table 4(A). `dispose_asset` asked only the FIRM's financial-year lock (`validate_posting_date`), which
    takes no client and cannot see a filed return, although a disposal that states a GST rate is the other half of the same
    register: a supply (CGST Act s.18(6)), whose journal credits GST Output and which `gst_return_service` declares in
    GSTR-3B Table 3.1(a). So a CA could dispose of an asset dated inside June after June's return had gone to the portal,
    and the books would carry output tax the return never declared, with nothing recording why.

WHAT IS HELD
    * a disposal that states a GST rate, dated inside a filed period, is refused with the reason the CA needs (which
      return, when it was filed, what to do instead), and the asset is left exactly as it was: not claimed, no journal;
    * the same disposal dated in an open period goes through, so the guard is a rule and not an outage;
    * the lock is the CLIENT's: another client's filed return does not stop this one;
    * a disposal that states NO rate (a scrapping) posts no tax and is declared nowhere, so it is not refused;
    * the lock is the combined one, so a filed GSTR-1 alone refuses it even while GSTR-3B is still open. That window is a
      known cost (see the design record), pinned here so changing it is a decision and not an accident.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from models.accounting import DisposalIn
from tests.test_a_disposal_declares_its_output_tax import CALLER, CLIENT, FIRM, _asset, db  # noqa: F401

__all__ = ["db"]


def _file_gstr1(db, client=CLIENT, month="2025-06", filing_type="GSTR-1"):
    year, mm = month.split("-")
    db.seed("filings", {
        "firm_id": FIRM, "client_id": client, "filing_type": filing_type,
        "period_start": f"{month}-01", "period_end": f"{month}-30",
        "filed_date": f"{year}-{int(mm) + 1:02d}-11", "status": "filed", "deleted_at": None,
    })


def _dispose(db, asset, disposal_date):
    return fa.dispose_asset(
        asset["id"],
        DisposalIn(disposal_type="Sale", sale_proceeds_paise=5_90_000_00, disposal_date=disposal_date,
                   is_supply=True, gst_rate_bps=1800),
        CALLER)


def test_a_disposal_dated_inside_a_filed_period_is_refused_and_leaves_the_asset_alone(db):
    asset = _asset(db)
    _file_gstr1(db)

    with pytest.raises(HTTPException) as refused:
        _dispose(db, asset, "2025-06-20")

    assert refused.value.status_code == 422
    assert "GSTR-1" in refused.value.detail, "the CA needs to know WHICH return closed the period"
    assert "amendment" in refused.value.detail.lower(), "refusing must say what to do instead"
    row = db.rows("fixed_assets")[0]
    assert row["is_disposed"] is False, "a refused disposal must not claim the asset"
    assert db.rows("journal_entries") == [], "and must post nothing"


def test_the_same_disposal_in_an_open_period_goes_through(db):
    # depreciation is posted through June, so July's disposal is not held up by the unposted-month rule (FA-08)
    asset = _asset(db, depreciation_posted_through="2025-06-30")
    _file_gstr1(db)

    out = _dispose(db, asset, "2025-07-20")["data"]

    assert out["journal_entry_id"]
    assert db.rows("fixed_assets")[0]["is_disposed"] is True


def test_another_clients_filed_return_does_not_stop_this_one(db):
    asset = _asset(db)
    _file_gstr1(db, client="SOMEBODY-ELSE")

    out = _dispose(db, asset, "2025-06-20")["data"]

    assert out["journal_entry_id"]


def test_a_filed_gstr3b_refuses_it_too_and_names_the_return(db):
    asset = _asset(db)
    _file_gstr1(db, filing_type="GSTR-3B")

    with pytest.raises(HTTPException) as refused:
        _dispose(db, asset, "2025-06-20")

    assert refused.value.status_code == 422 and "GSTR-3B" in refused.value.detail
    assert db.rows("fixed_assets")[0]["is_disposed"] is False


def test_a_disposal_that_states_no_rate_declares_nothing_so_it_is_not_refused(db):
    asset = _asset(db)
    _file_gstr1(db, filing_type="GSTR-3B")

    out = fa.dispose_asset(
        asset["id"], DisposalIn(disposal_type="Scrapped", sale_proceeds_paise=0, disposal_date="2025-06-20"), CALLER)["data"]

    assert out["journal_entry_id"]
    assert db.rows("fixed_assets")[0]["is_disposed"] is True


def test_the_lock_is_the_combined_one_so_a_filed_gstr1_alone_refuses_while_the_3b_is_open(db):
    """Pinned as a KNOWN cost (design record, POST-A-089): the open GSTR-3B would still carry this disposal, but one
    definition of 'filed' serves every path, as it does for create_asset."""
    asset = _asset(db)
    _file_gstr1(db, filing_type="GSTR-1")          # no GSTR-3B filed for the month

    with pytest.raises(HTTPException) as refused:
        _dispose(db, asset, "2025-06-20")
    assert "GSTR-1" in refused.value.detail
