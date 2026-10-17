"""The staff "Client Portal Preview" lists a client's open fee invoices in the shape the server sends them (POST-A-160).

THE DEFECT, FOUND BY TRIAGING THE STATUS-VOCABULARY RATCHET
    `app/client-portal/page.tsx` declared each due as `{party_name, transaction_date, reference_no, total_paise, status}`,
    the shape of the retired `transactions` feed. Phase 4.5.2 moved `GET /api/portal/dues` onto the canonical receivable,
    which sends `portal_data_service.safe_invoice` (`invoice_no`, `invoice_date`, `due_date`, `total_paise`, `paid_paise`,
    `outstanding_paise`, `status`, `is_overdue`, `days_overdue`), so every row printed a blank name and a blank date and
    showed the invoice's face value rather than what is owed. Three more things were wrong beside it:
      * the badge compared `due.status === "overdue"`, but the status column never holds "overdue" (the server derives it
        into `is_overdue`), so the overdue colour never appeared;
      * whenever the server's answer was EMPTY the panel fell back to the client's whole transaction feed, filtered with
        `status !== "posted"` (a value no transaction carries), so a client who owed nothing was shown every paid sale and
        purchase as "outstanding";
      * that fallback made the screen's emptiness untruthful in the other direction too: "No outstanding dues" could
        never be shown for a client who had any transaction at all.

WHAT IS HELD
    * every field the screen's `ApiDue` declares is a key `safe_invoice` sends, and the ones it needs to say what is owed
      and whether it is late are declared;
    * the page does not load the transaction feed or filter it on a status nobody sets, and no panel falls back to it.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from services.portal_data_service import safe_invoice

PAGE = Path(__file__).resolve().parents[3] / "apps" / "web" / "app" / "client-portal" / "page.tsx"


def _declared_fields(source: str, interface: str = "ApiDue") -> list[str]:
    body = re.search(r"interface\s+" + interface + r"\s*\{(.*?)\n\}", source, re.S)
    assert body, f"interface {interface} not found"
    text = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.S)
    text = re.sub(r"//.*", "", text)
    return re.findall(r"^\s*(\w+)\??\s*:", text, re.M)


def _served_keys() -> set[str]:
    sample = {"id": "i-1", "invoice_no": "FEE/1", "invoice_date": "2026-04-01", "due_date": "2026-04-30",
              "total_paise": 118000, "paid_paise": 0, "status": "issued"}
    return set(safe_invoice(sample, today=date(2026, 6, 1)))


def test_every_field_the_screen_declares_is_one_the_server_sends():
    declared = _declared_fields(PAGE.read_text(encoding="utf-8"))
    assert declared, "the scan found no ApiDue fields"
    missing = [f for f in declared if f not in _served_keys()]
    assert not missing, f"ApiDue declares fields the dues endpoint does not send: {missing}"


def test_it_declares_what_is_needed_to_say_what_is_owed_and_whether_it_is_late():
    declared = set(_declared_fields(PAGE.read_text(encoding="utf-8")))
    assert {"outstanding_paise", "is_overdue", "days_overdue", "invoice_no", "due_date"} <= declared


def test_the_panel_no_longer_falls_back_to_the_transaction_feed():
    source = PAGE.read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))
    assert "getTransactions" not in code and "lib/data/transactions" not in code
    assert "unpaidInvoices" not in code
    assert '!== "posted"' not in code and "=== \"posted\"" not in code
    assert 'due.status === "overdue"' not in code, "the status column never says overdue; the server derives is_overdue"


def test_negative_control_the_old_shape_is_caught():
    stale = "interface ApiDue {\n  id: string;\n  party_name: string;\n  transaction_date: string;\n}\n"
    assert [f for f in _declared_fields(stale) if f not in _served_keys()] == ["party_name", "transaction_date"]
