"""
Regression tests for the platform accounting audit fixes (July 2026).

Covers, end-to-end through the real routers + posting kernel:
1. RCM (CGST Act §9(3)/(4)) — vendor payable excludes self-assessed GST and
   the journal posts the RCM output liability (previously an RCM bill was
   booked identically to a normal bill: AP overstated by GST the vendor
   never charged, no output liability anywhere in the GL, while GSTR-3B
   reported one).
2. Journal reference uniqueness — two DIFFERENT vendors' bills with the
   same vendor-assigned bill_no on the same date must post two separate
   journals (the old bill_no-based reference silently deduped the second
   bill onto the first bill's journal), and cancelling each must reverse
   its OWN journal (REV- references now derive from the unique entry id).
3. The intrastate GST split in purchase bills / credit notes / debit notes —
   full-tax-then-split, matching the sales-side implementation (the old
   floor-each-half split lost paise and mis-computed odd-bps rates).
"""
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from services.phase2_journal_service import purchase_bill_journal_ref
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id

FIRM = "FIRM-AUDIT"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "id": "u1", "email": "ca@firm.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.purchase_bills as pb
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND-A", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Vendor A", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": False})
    db.seed("vendors", {"id": "VEND-B", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Vendor B", "state_code": "27", "gstin": "27LMNOP3456Q1Z2",
                        "pan": "LMNOP3456Q", "is_active": True, "tds_applicable": False})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Legal Services", "kind": "service"})
    return pb, db


def _bill_in(vendor_id="VEND-A", bill_no="INV-101", rate_paise=10_000_000, gst=18.0, rcm=False):
    return PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date="2026-04-05", bill_no=bill_no,
        is_reverse_charge=rcm,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Services", hsn_sac="9982",
                                  quantity=1, rate_paise=rate_paise, gst_rate_percent=gst)],
    )


# ── 1. Reverse charge (CGST Act §9(3)/(4)) ───────────────────────────────────

def test_rcm_bill_vendor_payable_excludes_self_assessed_gst(monkeypatch):
    pb, db = _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill_in(rcm=True), CALLER)["data"]
    # GST is computed (drives 3B/ITC) but the vendor is owed the taxable only.
    assert bill["taxable_amount_paise"] == 10_000_000
    assert bill["cgst_paise"] == 900_000 and bill["sgst_paise"] == 900_000
    assert bill["total_paise"] == 10_000_000          # NOT 11,800,000
    assert bill["net_payable_paise"] == 10_000_000
    assert bill["lines"][0]["line_total_paise"] == 10_000_000


def test_rcm_receive_posts_output_liability_and_balances(monkeypatch):
    pb, db = _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill_in(rcm=True), CALLER)["data"]
    resp = pb.receive_purchase_bill(bill["id"], CALLER)
    assert resp["success"] is True, resp

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 11_800_000
    # Dr Expense 1,00,000 + Dr GST Input 18,000
    assert account_balance(db, coa_id(db, FIRM, "gst_input")) == 1_800_000
    # Cr AP = taxable only (vendor never charged the GST)
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -10_000_000
    # Cr RCM output liability on the per-head GST output accounts
    rcm_out = (account_balance(db, coa_id(db, FIRM, "gst_cgst"))
               + account_balance(db, coa_id(db, FIRM, "gst_sgst")))
    assert rcm_out == -1_800_000


def test_normal_bill_unchanged_by_rcm_support(monkeypatch):
    pb, db = _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill_in(rcm=False), CALLER)["data"]
    assert bill["total_paise"] == 11_800_000
    assert bill["net_payable_paise"] == 11_800_000
    pb.receive_purchase_bill(bill["id"], CALLER)
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -11_800_000
    assert account_balance(db, coa_id(db, FIRM, "gst_cgst")) == 0  # no RCM lines


# ── 2. Journal reference uniqueness across documents ─────────────────────────

def test_two_vendors_same_bill_no_same_date_post_two_separate_journals(monkeypatch):
    pb, db = _setup(monkeypatch)
    bill_a = pb.create_purchase_bill(_bill_in(vendor_id="VEND-A", bill_no="INV-101", rate_paise=5_000_000), CALLER)["data"]
    bill_b = pb.create_purchase_bill(_bill_in(vendor_id="VEND-B", bill_no="INV-101", rate_paise=10_000_000), CALLER)["data"]
    pb.receive_purchase_bill(bill_a["id"], CALLER)
    pb.receive_purchase_bill(bill_b["id"], CALLER)

    purchase_journals = [e for e in db.rows("journal_entries") if e.get("entry_type") == "Purchase"]
    assert len(purchase_journals) == 2, "second bill must not dedup onto the first bill's journal"
    refs = {e["reference_no"] for e in purchase_journals}
    assert refs == {purchase_bill_journal_ref(bill_a["id"]), purchase_bill_journal_ref(bill_b["id"])}
    # Both bills' full value reached the GL.
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 5_900_000 + 11_800_000

    # Each bill carries ITS OWN journal id (the old collision stamped bill A's
    # journal onto bill B, so cancelling B reversed A's journal).
    a_row = db.table("purchase_bills").select("*").eq("id", bill_a["id"]).execute().data[0]
    b_row = db.table("purchase_bills").select("*").eq("id", bill_b["id"]).execute().data[0]
    assert a_row["journal_entry_id"] != b_row["journal_entry_id"]


def test_cancelling_same_numbered_bills_same_day_reverses_each_own_journal(monkeypatch):
    pb, db = _setup(monkeypatch)
    bill_a = pb.create_purchase_bill(_bill_in(vendor_id="VEND-A", bill_no="INV-101", rate_paise=5_000_000), CALLER)["data"]
    bill_b = pb.create_purchase_bill(_bill_in(vendor_id="VEND-B", bill_no="INV-101", rate_paise=10_000_000), CALLER)["data"]
    pb.receive_purchase_bill(bill_a["id"], CALLER)
    pb.receive_purchase_bill(bill_b["id"], CALLER)

    assert pb.cancel_purchase_bill(bill_a["id"], CALLER)["success"] is True
    assert pb.cancel_purchase_bill(bill_b["id"], CALLER)["success"] is True

    # BOTH originals are reversed — the old REV-{reference} key deduped the
    # second same-day reversal onto the first, leaving bill B cancelled with
    # its journal still live.
    reversals = [e for e in db.rows("journal_entries") if e.get("reversal_of")]
    assert len(reversals) == 2
    assert {e["reversal_of"] for e in reversals} == {
        db.table("purchase_bills").select("*").eq("id", bill_a["id"]).execute().data[0]["journal_entry_id"],
        db.table("purchase_bills").select("*").eq("id", bill_b["id"]).execute().data[0]["journal_entry_id"],
    }
    # Net GL effect of two receive+cancel cycles is zero.
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0


# ── 3. Intrastate GST split parity with the sales side ───────────────────────

def test_intrastate_split_matches_sales_side_for_odd_amounts_and_rates():
    from routers.sales_invoices import _compute_line_gst as sales_gst
    from routers.purchase_bills import _compute_line_gst as pb_gst
    from routers.credit_notes import _compute_line_gst as cn_gst
    from routers.debit_notes import _compute_line_gst as dn_gst

    cases = [
        (9_999, 1800),      # odd full tax: 1799p — old split gave 899+899=1798
        (1_000_000, 25),    # 0.25% odd-bps rate: 2500p — old split gave 2400
        (1_000_000, 10),    # 0.10%: 1000p — old split gave 0+0... (half=5bps floor)
        (12_345, 1800),
    ]
    for taxable, bps in cases:
        expected = sales_gst(taxable, bps, False)
        assert pb_gst(taxable, bps, False) == expected, (taxable, bps)
        assert cn_gst(taxable, bps, False) == expected, (taxable, bps)
        assert dn_gst(taxable, bps, False) == expected, (taxable, bps)
        cgst, sgst, _ = expected
        assert cgst + sgst == (taxable * bps) // 10000  # sum equals IGST-equivalent
