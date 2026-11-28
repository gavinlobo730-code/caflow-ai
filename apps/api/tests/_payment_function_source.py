"""What the function that records a supplier payment stores of the payment row (migration 784, POST-A-575).

`settle_payment_atomic` builds its INSERT from the payload's OWN keys: a column the caller names is stored, a column it leaves out
takes the table's default, and a key that is no column fails the whole call. The in-memory double (`tests/e2e_harness.py`) has no
catalogue to ask, so it asks this list, and the list is held to the real table by
`tests/test_784_a_supplier_payment_is_recorded_in_one_transaction_pg.py::test_the_doubles_list_of_payment_columns_is_the_tables`:
a migration that adds a column to `purchase_payments` fails there until the column is added here.
"""
from __future__ import annotations

#: every column of public.purchase_payments
PURCHASE_PAYMENT_COLUMNS = frozenset({
    "id", "firm_id", "client_id", "vendor_id", "purchase_bill_id", "payment_no", "payment_date", "amount_paise", "payment_mode",
    "reference_no", "notes", "journal_entry_id", "created_at", "updated_at",
    "txn_currency", "exchange_rate", "txn_amount", "rate_source", "rate_type", "rate_date", "rate_selected_by", "rate_overridden",
    "is_reversed", "unallocated_paise", "bank_account_id",
    "tds_paise", "tds_base_paise", "tds_section", "tds_rate_bps", "tds_surcharge_paise", "tds_cess_paise", "tds_nature_of_income",
    "tds_basis", "tds_certificate_no",
})

#: the one key of the payment payload that is not the row's: the record of the realised exchange difference
NOT_THE_ROWS = frozenset({"fx_adjustment"})

#: what the table gives a column the payload leaves out, for the columns a reader of the stored row relies on
COLUMN_DEFAULTS = {
    "amount_paise": 0, "payment_mode": "bank", "txn_currency": "INR", "exchange_rate": 1, "rate_type": "booking",
    "rate_overridden": False, "is_reversed": False, "unallocated_paise": 0, "tds_paise": 0, "tds_base_paise": 0,
    "tds_surcharge_paise": 0, "tds_cess_paise": 0,
}
