"""
Phase 5.2 final sprint — Portal Cycle (client-side access).

  Portal context → Invoice access → Statement access → Compliance access
  + the ownership gate (a portal client sees ONLY its own fee invoices)

Drives the real portal_data_service against the shared DB. The portal client is
scoped through the fee-relationship (firm's internal client + the linked
internal customer), so it can only ever see invoices issued to IT. The critical
isolation leg: a second portal client cannot see/access the first client's
invoice. (Portal login / context resolution is covered by test_m1_auth_portal /
test_portal*; here we validate the data surfaces + scoping.)
"""
import services.portal_data_service as pds
import services.internal_client_service as ics
import repositories.compliance_records_repository as crepo
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
INTERNAL = "INTERNAL-CLIENT"      # the firm's own books (where fee invoices live)


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [])
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: INTERNAL if firm_id == FIRM else None)
    monkeypatch.setattr(crepo, "_USE_MOCK", False)
    # Portal client CLI ↔ internal customer CUST (the fee-relationship link).
    db.seed("client_firm_customer_links", {"firm_id": FIRM, "client_id": "CLI", "internal_customer_id": "CUST"})
    # A second portal client CLI2 ↔ a DIFFERENT customer CUST2.
    db.seed("client_firm_customer_links", {"firm_id": FIRM, "client_id": "CLI2", "internal_customer_id": "CUST2"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": INTERNAL,
                          "name": "Acme Pvt Ltd", "opening_balance_paise": 0})
    # CLI's fee invoice (visible to CLI) and an unrelated one (CUST2 → must NOT leak to CLI).
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": INTERNAL, "customer_id": "CUST", "invoice_no": "FEE-1",
        "invoice_date": "2026-04-10", "due_date": "2026-04-25", "total_paise": 118_000,
        "paid_paise": 0, "status": "issued", "deleted_at": None})
    other = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": INTERNAL, "customer_id": "CUST2", "invoice_no": "FEE-2",
        "invoice_date": "2026-04-11", "total_paise": 50_000, "paid_paise": 0,
        "status": "issued", "deleted_at": None})
    # CLI's compliance obligation (with sensitive internal fields that must be stripped).
    db.seed("compliance_records", {
        "firm_id": FIRM, "client_id": "CLI", "compliance_type": "GST", "obligation_type": "GSTR3B",
        "period_label": "GSTR-3B Apr 2026", "due_date": "2026-05-20", "status": "Filed",
        "notes": "internal note", "preparer_id": "exec1", "priority": "high",
        "created_at": "2026-04-01T00:00:00Z", "updated_at": "2026-04-01T00:00:00Z"})
    return db, inv["id"], other["id"]


def test_portal_invoice_access(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    invs = pds.list_invoices(FIRM, "CLI", db=db)
    assert [i["invoice_no"] for i in invs] == ["FEE-1"]        # only CLI's fee invoice
    assert invs[0]["outstanding_paise"] == 118_000


def test_portal_statement_access(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    st = pds.statement(FIRM, "CLI", "2026-04-01", "2026-04-30", db=db)
    assert st["closing_balance_paise"] == 118_000           # the one issued fee invoice


def test_portal_compliance_access_is_client_safe(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    recs = pds.compliance(FIRM, "CLI", db=db)
    assert len(recs) == 1 and recs[0]["status"] == "Filed"
    # Client-safe projection: internal fields stripped.
    assert "notes" not in recs[0] and "preparer_id" not in recs[0]


def test_portal_ownership_gate(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    assert pds.invoice_in_scope(FIRM, "CLI", inv_id, db=db) is True
    assert pds.invoice_in_scope(FIRM, "CLI", other_id, db=db) is False   # not CLI's customer
    assert pds.invoice_in_scope(FIRM, "CLI", "does-not-exist", db=db) is False


# --------------------------------------------------------------------------- #
#  Cross-client isolation — the core portal guarantee
# --------------------------------------------------------------------------- #
def test_portal_other_client_cannot_see_or_access(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    # CLI2 (linked to CUST2) must not see CLI's invoice…
    cli2_invs = pds.list_invoices(FIRM, "CLI2", db=db)
    assert all(i["invoice_no"] != "FEE-1" for i in cli2_invs)
    # …and cannot pass the ownership gate for it.
    assert pds.invoice_in_scope(FIRM, "CLI2", inv_id, db=db) is False


def test_portal_unlinked_client_sees_nothing(monkeypatch):
    db, inv_id, other_id = _setup(monkeypatch)
    # A portal client with no fee-relationship link resolves no scope ⇒ empty.
    assert pds.list_invoices(FIRM, "CLI-UNLINKED", db=db) == []
    assert pds.invoice_in_scope(FIRM, "CLI-UNLINKED", inv_id, db=db) is False
