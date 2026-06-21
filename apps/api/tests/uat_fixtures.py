"""
Phase 5.2 WS-2 — repeatable demo-data fixtures.

A single, deterministic builder that provisions the UAT demo dataset (two firms,
four staff roles, clients, customers, vendors, a standard COA, fee invoices,
bills and a compliance obligation) into the in-memory harness DB. It is the
canonical, executable definition of the demo data referenced by
docs/PHASE_5_2_WS2_UAT_PLAN.md — repeatable (same ids every run) and verified by
tests/test_uat_fixtures.py. For staging it is the contract a seed script mirrors.

Integer paise only. No business logic — pure data provisioning.
"""
from __future__ import annotations

from tests.e2e_harness import FakeDB, seed_standard_coa


def build_demo_dataset(db: FakeDB) -> dict:
    """Provision the UAT demo dataset. Deterministic ids; returns the id map."""
    A, B = "FIRM-A", "FIRM-B"
    ids: dict = {"firm_a": A, "firm_b": B}

    # ── Firm A: staff (the four UAT personas) ────────────────────────────────
    db.seed("firms", {"id": A, "name": "Sharma & Associates"})
    db.seed("users", {"id": "u-priya",  "firm_id": A, "name": "Priya",  "role": "Partner",   "email": "priya@firma.test"})
    db.seed("users", {"id": "u-manish", "firm_id": A, "name": "Manish", "role": "Manager",   "email": "manish@firma.test"})
    db.seed("users", {"id": "u-arjun",  "firm_id": A, "name": "Arjun",  "role": "Executive", "email": "arjun@firma.test"})
    db.seed("users", {"id": "u-reena",  "firm_id": A, "name": "Reena",  "role": "Reviewer",  "email": "reena@firma.test"})

    # ── Firm A: clients + assignment scope (Manager/Exec → C1; Reviewer → C2) ─
    db.seed("clients", {"id": "C1", "firm_id": A, "client_name": "Acme Pvt Ltd",   "gstin": "27ABCDE1234F1Z5", "status": "active"})
    db.seed("clients", {"id": "C2", "firm_id": A, "client_name": "Bharat Traders", "gstin": "29PQRST5678K1Z2", "status": "active"})
    for uid, cid in (("u-manish", "C1"), ("u-arjun", "C1"), ("u-reena", "C2")):
        db.seed("user_client_assignments", {"user_id": uid, "client_id": cid})
    seed_standard_coa(db, A, "C1")
    seed_standard_coa(db, A, "C2")

    # ── Firm A / C1: customers + vendors ─────────────────────────────────────
    db.seed("customers", {"id": "CU-NW", "firm_id": A, "client_id": "C1", "name": "Northwind",
                          "state_code": "27", "email": "ar@northwind.test", "is_active": True})
    db.seed("customers", {"id": "CU-SR", "firm_id": A, "client_id": "C1", "name": "Sunrise Exports",
                          "state_code": "29", "email": "ar@sunrise.test", "is_active": True})
    db.seed("vendors", {"id": "VD-OS", "firm_id": A, "client_id": "C1", "name": "OfficeSpace LLP",
                        "state_code": "27", "is_active": True, "tds_applicable": True,
                        "tds_section": "194I", "tds_rate_bps": 1000})
    db.seed("vendors", {"id": "VD-CV", "firm_id": A, "client_id": "C1", "name": "CloudVendor",
                        "state_code": "27", "is_active": True, "tds_applicable": False})

    # ── Firm A / C1: a couple of documents (issued invoice, received bill) ────
    db.seed("client_sales_invoices", {"id": "INV-1", "firm_id": A, "client_id": "C1", "customer_id": "CU-NW",
                                      "invoice_no": "SINV-2526-0001", "invoice_date": "2026-04-10",
                                      "due_date": "2026-04-25", "total_paise": 118_000, "paid_paise": 0,
                                      "status": "issued", "deleted_at": None})
    db.seed("purchase_bills", {"id": "BILL-1", "firm_id": A, "client_id": "C1", "vendor_id": "VD-OS",
                               "bill_no": "OS-2026-04", "bill_date": "2026-04-05", "total_paise": 11_800_000,
                               "tds_paise": 1_000_000, "net_payable_paise": 10_800_000, "status": "received"})

    # ── Firm A / C1: a compliance obligation ─────────────────────────────────
    db.seed("compliance_records", {"id": "OBL-1", "firm_id": A, "client_id": "C1", "compliance_type": "GST",
                                   "obligation_type": "GSTR3B", "period_label": "GSTR-3B Apr 2026",
                                   "due_date": "2026-05-20", "status": "Not Started",
                                   "created_at": "2026-04-01T00:00:00Z"})

    # ── Firm B: isolation foil (its own partner + client + invoice) ──────────
    db.seed("firms", {"id": B, "name": "Verma & Co"})
    db.seed("users", {"id": "u-raj", "firm_id": B, "name": "Raj", "role": "Partner", "email": "raj@firmb.test"})
    db.seed("clients", {"id": "C9", "firm_id": B, "client_name": "Zephyr Ltd", "gstin": "07ZEPHY9999Z1Z0", "status": "active"})
    db.seed("customers", {"id": "CU-Z", "firm_id": B, "client_id": "C9", "name": "Zephyr Customer", "is_active": True})
    db.seed("client_sales_invoices", {"id": "INV-9", "firm_id": B, "client_id": "C9", "customer_id": "CU-Z",
                                      "invoice_no": "SINV-2526-9001", "invoice_date": "2026-04-10",
                                      "total_paise": 59_000, "paid_paise": 0, "status": "issued", "deleted_at": None})

    ids.update({
        "users": {"partner": "u-priya", "manager": "u-manish", "executive": "u-arjun", "reviewer": "u-reena"},
        "clients": ["C1", "C2"], "customers": ["CU-NW", "CU-SR"], "vendors": ["VD-OS", "VD-CV"],
        "invoice_c1": "INV-1", "bill_c1": "BILL-1", "obligation_c1": "OBL-1",
        "firm_b_client": "C9", "firm_b_invoice": "INV-9",
    })
    return ids


def demo_callers() -> dict:
    """The four Firm-A personas + Firm-B partner as current_user dicts."""
    A = "FIRM-A"
    return {
        "partner":   {"firm_id": A, "auth_user_id": "u-priya",  "email": "priya@firma.test",  "role": "Partner"},
        "manager":   {"firm_id": A, "auth_user_id": "u-manish", "email": "manish@firma.test", "role": "Manager"},
        "executive": {"firm_id": A, "auth_user_id": "u-arjun",  "email": "arjun@firma.test",  "role": "Executive"},
        "reviewer":  {"firm_id": A, "auth_user_id": "u-reena",  "email": "reena@firma.test",  "role": "Reviewer"},
        "firm_b_partner": {"firm_id": "FIRM-B", "auth_user_id": "u-raj", "email": "raj@firmb.test", "role": "Partner"},
    }
