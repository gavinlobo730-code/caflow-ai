"""A create that returns an EXISTING supplier or customer says so, in words
(sweep-client-purchases-04).

WHAT WAS WRONG

`POST /api/vendors/` with a GSTIN an active vendor already holds returns THAT
vendor with `duplicate: True` — no insert, nothing typed saved — which is the
right answer (a GSTIN identifies one registration; see
`domain/party_duplicates`). The Vendors tab ignored the flag and showed
"Vendor added.", so a CA believed they had added a vendor when they had
changed nothing; the customer dialog did the same. Only one of four screens
read the flag, and each that did had to compose its own explanation.

The server now sends the sentence beside the flag — which identifier matched,
which party, and that nothing was created or changed — and every screen renders
it. These tests CALL the create paths.
"""
from __future__ import annotations

import pathlib

import routers.customers as cust
import routers.vendors as vend
from domain.party_duplicates import same_party_sentence
from models.parties import CustomerIn, VendorIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-DUP"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firm.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z2"
PAN = "ZZZZZ9999Z"
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _db(monkeypatch, modules):
    db = FakeDB()
    wire_e2e(monkeypatch, db, modules)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN})
    return db


def test_a_vendor_matched_on_gstin_is_named_and_nothing_is_created(monkeypatch):
    db = _db(monkeypatch, [vend])
    first = vend.create_vendor(VendorIn(client_id="CLI", name="Sunrise Fabrics Suppliers",
                                        gstin=GSTIN, state_code="27"), CALLER)
    assert first["success"] and not first["data"].get("duplicate")
    assert "duplicate_reason" not in first["data"]

    again = vend.create_vendor(VendorIn(client_id="CLI", name="A Different Name",
                                        gstin=GSTIN, state_code="27"), CALLER)

    assert again["success"] and again["data"]["duplicate"] is True
    reason = again["data"]["duplicate_reason"]
    assert reason.startswith("Not added")
    assert f"GSTIN {GSTIN}" in reason
    assert "Sunrise Fabrics Suppliers" in reason          # WHICH vendor it matched
    assert "A Different Name" not in reason               # not the name that was typed
    assert "Nothing new was created" in reason
    assert len(db.rows("vendors")) == 1


def test_a_customer_matched_on_pan_says_it_was_the_pan(monkeypatch):
    db = _db(monkeypatch, [cust])
    cust.create_customer(CustomerIn(client_id="CLI", name="Acme Traders", pan=PAN), CALLER)

    again = cust.create_customer(CustomerIn(client_id="CLI", name="Acme", pan=PAN), CALLER)

    assert again["data"]["duplicate"] is True
    reason = again["data"]["duplicate_reason"]
    assert f"PAN {PAN}" in reason and "GSTIN" not in reason
    assert "customer" in reason and "Acme Traders" in reason
    assert len(db.rows("customers")) == 1


def test_the_sentence_names_the_identifier_the_guard_actually_matched():
    """GSTIN first, PAN only where no GSTIN was given — the guard's own order."""
    row = {"name": "X Ltd"}
    assert "GSTIN 27AAAAA0000A1Z2" in same_party_sentence("vendor", row, "27AAAAA0000A1Z2", "ZZZZZ9999Z")
    assert "PAN ZZZZZ9999Z" in same_party_sentence("vendor", row, "", "ZZZZZ9999Z")
    # A matched row with no name still produces a sentence, never "None".
    assert "None" not in same_party_sentence("vendor", {}, "", "ZZZZZ9999Z")


def test_every_screen_that_creates_a_party_reads_the_flag():
    """The screen half. Each door that POSTs a new vendor or customer must look
    at `duplicate` before saying it was added."""
    for rel in ("app/clients/[id]/purchases/page.tsx",
                "components/customers/CustomerFormModal.tsx",
                "app/accounting/suppliers/page.tsx"):
        src = (WEB / rel).read_text(encoding="utf-8")
        assert "duplicate_reason" in src, f"{rel} does not render the server's sentence"
