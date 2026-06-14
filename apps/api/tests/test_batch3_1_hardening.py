"""
Batch 3.1 hardening — firm CoA seeding, atomic invoice issue, and issued-but-
unposted detection/remediation (mock mode, no DB).
"""
import re
import pytest
from fastapi import HTTPException

from services.coa_seed_service import STANDARD_COA
import services.internal_client_service as ics
from services.phase2_journal_service import phase2_journal_service
from routers.sales_invoices import (
    MOCK_SALES_INVOICES, issue_invoice, list_unposted, repost_journal,
)

PARTNER = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p", "email": "p@f"}
STAFF = {"firm_id": "F1", "role": "Executive", "auth_user_id": "s", "email": "s@f"}

# Account-name patterns the posting engine (phase2_journal_service) resolves.
REQUIRED_PATTERNS = [
    "%Trade Receivable%", "%Sales%", "%GST Output%", "%Bank%", "%Purchase%",
    "%Expense%", "%GST Input%", "%Trade Payable%", "%TDS Payable%",
    "%TDS Payable - Salary%", "%Salaries Expense%", "%Net Salary Payable%",
    "%PF Payable%", "%ESI Payable%", "%PT Payable%", "%Plant & Machinery%",
    "%Furniture & Fixtures%", "%Computers & Software%", "%Vehicles%",
    "%Land & Building%", "%Intangible Assets%", "%Accumulated Depreciation%",
    "%Depreciation Expense%", "%Profit on Asset Disposal%", "%Loss on Asset Disposal%",
]


@pytest.fixture(autouse=True)
def _clear():
    MOCK_SALES_INVOICES.clear()
    yield
    MOCK_SALES_INVOICES.clear()


def _ilike(pattern: str, name: str) -> bool:
    return re.fullmatch(pattern.replace("%", ".*"), name, re.IGNORECASE) is not None


def test_seed_covers_all_posting_account_patterns():
    names = [name for (_code, name, _t, _s) in STANDARD_COA]
    for pat in REQUIRED_PATTERNS:
        assert any(_ilike(pat, n) for n in names), f"STANDARD_COA missing an account matching {pat}"


def _draft(invoice_id="inv1", client_id="C1"):
    inv = {
        "id": invoice_id, "firm_id": "F1", "client_id": client_id,
        "invoice_no": "SINV-2526-0001", "invoice_date": "2026-06-10",
        "taxable_amount_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000,
        "igst_paise": 0, "total_paise": 118000, "paid_paise": 0, "status": "draft",
    }
    MOCK_SALES_INVOICES.append(inv)
    return inv


def test_atomic_issue_succeeds_and_links_journal():
    _draft()
    resp = issue_invoice("inv1", PARTNER)
    assert resp["success"] is True
    assert resp["data"]["status"] == "issued"
    assert resp["data"]["journal_entry_id"]  # journal linked


def test_missing_coa_leaves_invoice_retryable_draft(monkeypatch):
    _draft()

    def _raise(*a, **k):
        raise ValueError("Required account not found: %Trade Receivable%.")
    monkeypatch.setattr(phase2_journal_service, "journal_for_sales_invoice", _raise)

    resp = issue_invoice("inv1", PARTNER)
    assert resp["success"] is False
    inv = next(i for i in MOCK_SALES_INVOICES if i["id"] == "inv1")
    assert inv["status"] == "draft", "posting failure must leave the invoice a DRAFT"
    assert not inv.get("journal_entry_id"), "no journal link on failed issue"

    # After CoA is fixed (monkeypatch removed), the same invoice issues cleanly.
    monkeypatch.undo()
    resp2 = issue_invoice("inv1", PARTNER)
    assert resp2["success"] is True and resp2["data"]["status"] == "issued"


def test_detect_and_remediate_issued_but_unposted():
    # Simulate a legacy issued-but-unposted invoice.
    MOCK_SALES_INVOICES.append({
        "id": "legacy1", "firm_id": "F1", "client_id": "C1", "invoice_no": "SINV-1",
        "invoice_date": "2026-05-01", "taxable_amount_paise": 100000, "cgst_paise": 9000,
        "sgst_paise": 9000, "igst_paise": 0, "total_paise": 118000, "paid_paise": 0,
        "status": "issued", "journal_entry_id": None,
    })
    found = list_unposted(client_id=None, current_user=PARTNER)["data"]
    assert found["count"] == 1 and found["unposted"][0]["id"] == "legacy1"

    rep = repost_journal("legacy1", PARTNER)
    assert rep["success"] is True and rep["data"]["journal_entry_id"]

    after = list_unposted(client_id=None, current_user=PARTNER)["data"]
    assert after["count"] == 0, "remediated invoice no longer unposted"


def test_repost_idempotent():
    MOCK_SALES_INVOICES.append({
        "id": "inv2", "firm_id": "F1", "client_id": "C1", "invoice_no": "SINV-2",
        "invoice_date": "2026-05-01", "total_paise": 118000, "status": "issued",
        "journal_entry_id": "JE-EXISTING",
    })
    rep = repost_journal("inv2", PARTNER)
    assert rep["data"]["already_posted"] is True
    assert rep["data"]["journal_entry_id"] == "JE-EXISTING"


def test_repost_internal_client_partner_only(monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: "INT")
    MOCK_SALES_INVOICES.append({
        "id": "inv3", "firm_id": "F1", "client_id": "INT", "invoice_no": "SINV-3",
        "invoice_date": "2026-05-01", "total_paise": 118000, "status": "issued",
        "journal_entry_id": None,
    })
    # Staff cannot remediate the internal client's invoice (G1 -> 404).
    with pytest.raises(HTTPException) as ei:
        repost_journal("inv3", STAFF)
    assert ei.value.status_code == 404
    # Partner can.
    assert repost_journal("inv3", PARTNER)["success"] is True
