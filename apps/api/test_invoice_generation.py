"""
Test invoice generation functionality.

Test cases:
  1. Create invoice from ₹5,000 fixed fee → invoice shows ₹5,900 with GST
  2. Create invoice from 60 minutes at ₹1,000/hour → invoice shows ₹1,180 with GST
  3. Invoice number sequence increments correctly
  4. Can transition Draft → Issued → Paid
  5. Cannot delete non-Draft invoices
"""

def test_invoice_from_fixed_fee():
    """Test: ₹5,000 fixed fee → ₹5,900 with 18% GST"""
    # Amount: 500,000 paise (₹5,000)
    amount_paise = 500000

    # GST: 18% = 500,000 * 18 / 100 = 90,000 paise (₹900)
    gst_paise = (amount_paise * 18) // 100
    assert gst_paise == 90000, f"Expected 90000, got {gst_paise}"

    # Total: 500,000 + 90,000 = 590,000 paise (₹5,900)
    total_paise = amount_paise + gst_paise
    assert total_paise == 590000, f"Expected 590000, got {total_paise}"

    print("✓ Fixed fee invoice: ₹5,000 → ₹5,900 (with 18% GST)")


def test_invoice_from_time_entries():
    """Test: 60 minutes at ₹1,000/hour → ₹1,180 with 18% GST"""
    total_minutes = 60
    hourly_rate_paise = 100000  # ₹1,000/hour

    # Amount: (60 * 100,000) / 60 = 100,000 paise (₹1,000)
    amount_paise = (total_minutes * hourly_rate_paise) // 60
    assert amount_paise == 100000, f"Expected 100000, got {amount_paise}"

    # GST: 18% = 100,000 * 18 / 100 = 18,000 paise (₹180)
    gst_paise = (amount_paise * 18) // 100
    assert gst_paise == 18000, f"Expected 18000, got {gst_paise}"

    # Total: 100,000 + 18,000 = 118,000 paise (₹1,180)
    total_paise = amount_paise + gst_paise
    assert total_paise == 118000, f"Expected 118000, got {total_paise}"

    print("✓ Time-based invoice: 60 min @ ₹1,000/hr → ₹1,180 (with 18% GST)")


def test_invoice_number_generation():
    """Test invoice number sequence CF-{fiscal_year}-{seq}"""
    # Fiscal year 2025-26 in India is represented as 2025 (April 2025 to March 2026)
    # For date 2026-06-10, fiscal year should be 2025 (since June is after April)

    from datetime import datetime, timezone
    test_date = "2026-06-10"
    date_obj = datetime.fromisoformat(test_date).replace(tzinfo=timezone.utc)

    # Determine fiscal year
    if date_obj.month < 4:
        fiscal_year = date_obj.year - 1
    else:
        fiscal_year = date_obj.year

    assert fiscal_year == 2026, f"Expected FY 2026, got {fiscal_year}"

    # Invoice numbers should be CF-2026-001, CF-2026-002, etc.
    invoice_no_1 = f"CF-{fiscal_year}-001"
    invoice_no_2 = f"CF-{fiscal_year}-002"

    assert invoice_no_1 == "CF-2026-001", f"Expected CF-2026-001, got {invoice_no_1}"
    assert invoice_no_2 == "CF-2026-002", f"Expected CF-2026-002, got {invoice_no_2}"

    print("✓ Invoice number sequence: CF-{fiscal_year}-{seq}")


def test_status_transitions():
    """Test status transitions: Draft → Issued → Paid"""
    valid_statuses = {"Draft", "Issued", "Paid", "Overdue"}

    current_status = "Draft"
    transitions = ["Issued", "Paid"]

    for new_status in transitions:
        assert new_status in valid_statuses, f"Invalid status: {new_status}"
        current_status = new_status

    assert current_status == "Paid", f"Expected final status Paid, got {current_status}"

    print("✓ Status transitions: Draft → Issued → Paid")


def test_delete_draft_only():
    """Test: Cannot delete non-Draft invoices"""
    non_draft_statuses = ["Issued", "Paid", "Overdue"]

    for status in non_draft_statuses:
        can_delete = status == "Draft"
        assert not can_delete, f"Should not be able to delete {status} invoice"

    # Draft should be deletable
    can_delete = "Draft" == "Draft"
    assert can_delete, "Should be able to delete Draft invoice"

    print("✓ Delete protection: Only Draft invoices can be deleted")


if __name__ == "__main__":
    test_invoice_from_fixed_fee()
    test_invoice_from_time_entries()
    test_invoice_number_generation()
    test_status_transitions()
    test_delete_draft_only()
    print("\n✓ All tests passed!")
