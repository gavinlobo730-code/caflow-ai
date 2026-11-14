"""Late interest on a customer's invoice is charged on the balance owed on each late day, not today's balance (POST-A-101).

WHAT WAS WRONG
    `domain/sales/late_interest` applied each invoice's balance AS IT STANDS TODAY to every day of the late period. Where a
    part-payment came in during that period, today's balance is lower than what was owed before it, so the figure UNDERSTATED the
    interest the client's own terms allow; the caveat on every answer said the opposite ("OVERSTATES"). Only a debit note that raised
    the balance during the period made it overstate.

WHAT IS HELD
    * the arithmetic: a payment reduces the balance from its own date and the day it arrives is still a late day on what it pays; a
      payment before the period, on the as-at day or after it; a debit note raising the balance; nothing below nil; one rounding;
    * the service reads each open invoice's receipts, credit notes and debit notes with their dates, uses them only when they account
      for exactly what the invoice shows as settled, and otherwise falls back to today's balance and SAYS so, the right way round;
    * a voided allocation, a reversed receipt and a draft credit note are not payments;
    * the prepared draft's line says "the balance outstanding on each of those days" when that is what it was computed on.

The worked example, used throughout: an invoice of 1,00,000.00 due on 1 September, 50,000.00 received on 21 September, looked at on
11 October, at 18% a year. Days 2 to 21 September (20) are on 1,00,000.00 and 22 September to 11 October (20) on 50,000.00:
3,00,00,00,000 paise-days x 1800 / (10,000 x 365) = 1,47,945.2, so 1,479.45. Today's balance over all 40 days gave 986.30.
"""
from __future__ import annotations

from datetime import date

from domain.sales import late_interest as L

DUE, AS_OF = "2026-09-01", date(2026, 10, 11)
LAKH = 10_000_000                                                    # 1,00,000.00 in paise


def _interest(outstanding, history, as_of=AS_OF, rate=1800, **kw):
    return L.document_interest(outstanding_paise=outstanding, invoice_date="2026-08-01", due_date=DUE,
                               terms=L.Terms(rate), as_of=as_of, history=history, **kw)


def C(day, amount):
    return L.BalanceChange(date.fromisoformat(day), amount)


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_the_worked_example_charges_the_balance_owed_on_each_day():
    got = _interest(LAKH // 2, (C("2026-09-21", LAKH // 2),))
    assert (got.status, got.interest_paise, got.days_charged, got.balance_basis) == (L.CHARGE, 147_945, 40, "history")
    today = _interest(LAKH // 2, None)
    assert (today.interest_paise, today.balance_basis) == (98_630, "today"), "the old figure, which understated"


def test_no_change_is_the_same_as_todays_balance():
    assert _interest(LAKH, ()).interest_paise == _interest(LAKH, None).interest_paise == L.interest_paise(LAKH, 1800, 40)


def test_a_payment_before_the_late_period_lowers_every_late_day():
    assert _interest(LAKH // 2, (C("2026-08-20", LAKH // 2),)).interest_paise == L.interest_paise(LAKH // 2, 1800, 40)


def test_a_payment_on_the_as_at_day_leaves_that_day_owed():
    assert _interest(LAKH // 2, (C("2026-10-11", LAKH // 2),)).interest_paise == L.interest_paise(LAKH, 1800, 40)


def test_a_payment_after_the_as_at_date_had_not_happened_yet():
    """An as-at date earlier than today uses the balance as it was then."""
    assert _interest(LAKH // 2, (C("2026-10-30", LAKH // 2),)).interest_paise == L.interest_paise(LAKH, 1800, 40)


def test_the_day_after_a_payment_is_the_first_day_at_the_lower_balance():
    assert L.balance_paise_days(0, (C("2026-09-02", 100),), date(2026, 9, 1), date(2026, 9, 3)) == 100
    assert L.balance_paise_days(0, (C("2026-09-03", 100),), date(2026, 9, 1), date(2026, 9, 3)) == 200


def test_a_debit_note_raises_the_balance_from_its_date():
    # 50,000 owed until 21 September, then a debit note of 50,000: today's balance is 1,00,000 and over all 40 days overstated.
    got = _interest(LAKH, (C("2026-09-21", -(LAKH // 2)),))
    assert got.interest_paise == 147_945 and _interest(LAKH, None).interest_paise == L.interest_paise(LAKH, 1800, 40)


def test_several_changes_on_one_day_and_the_balance_never_below_nil():
    changes = (C("2026-09-10", 3), C("2026-09-10", 2), C("2026-09-20", 99))
    # 2 Sep to 10 Sep (9 days) at 0 + 3 + 2 + 99 = 104; 11 to 20 Sep (10 days) at 99; after, at 0.
    assert L.balance_paise_days(0, changes, date(2026, 9, 1), date(2026, 10, 11)) == 9 * 104 + 10 * 99
    assert L.balance_paise_days(-500, (C("2026-09-10", 100),), date(2026, 9, 1), date(2026, 9, 30)) == 0


def test_a_period_already_charged_counts_only_the_days_after_it():
    got = _interest(LAKH // 2, (C("2026-09-21", LAKH // 2),), charged_through=date(2026, 9, 21))
    assert got.days_charged == 20 and got.interest_paise == L.interest_paise(LAKH // 2, 1800, 20)


def test_the_sentinel_dates_are_before_and_after_every_late_day():
    assert L.balance_paise_days(LAKH, (C("2026-09-21", 0), L.BalanceChange(L.FROM_THE_START, LAKH)), date(2026, 9, 1),
                                date(2026, 9, 3)) == 2 * LAKH, "a change from the start has happened on both days (2 and 3 September)"
    assert L.balance_paise_days(LAKH, (L.BalanceChange(L.OUTSIDE_THE_WINDOW, -(LAKH // 2)),), date(2026, 9, 1),
                                date(2026, 9, 3)) == 2 * (LAKH // 2), "a change outside the window never happens inside it"


def test_a_document_already_covered_still_says_the_base_it_would_be_on():
    got = _interest(LAKH // 2, (C("2026-09-21", LAKH // 2),), charged_through=AS_OF)
    assert (got.status, got.balance_basis) == (L.COVERED, "history")
    assert _interest(LAKH // 2, None, charged_through=AS_OF).balance_basis == "today"


def test_a_history_ties_only_when_it_accounts_for_everything_settled():
    assert L.history_ties(total_paise=LAKH, outstanding_paise=LAKH // 2, changes=(C("2026-09-21", LAKH // 2),))
    assert not L.history_ties(total_paise=LAKH, outstanding_paise=LAKH // 2, changes=(C("2026-09-21", LAKH // 4),))


def test_the_draft_line_says_what_the_base_was():
    common = dict(invoice_id="i", invoice_no="INV/1", customer_id="c", interest_paise=147_945, period_from="2026-09-01",
                  period_to="2026-10-11", days=40, outstanding_paise=LAKH // 2, interest_rate_bps=1800)
    assert "on the balance outstanding on each of those days" in L.line_description(L.ChargeableDoc(balance_basis="history", **common))
    assert "on the balance of Rs.50,000.00" in L.line_description(L.ChargeableDoc(balance_basis="today", **common))


# ── the service, on the in-memory database ───────────────────────────────────

from services import late_interest_service as svc   # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e       # noqa: E402

FIRM, CLIENT, CUST = "FIRM-LI", "CLI-LI", "CUST-LI"


def _book(monkeypatch) -> FakeDB:
    import routers.sales_invoices as si
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    db.seed("customers", {"id": CUST, "firm_id": FIRM, "client_id": CLIENT, "name": "Beta Ltd", "is_active": True,
                          "late_interest_rate_bps": 1800, "late_interest_grace_days": 0, "late_interest_from": "due_date"})
    return db


def _invoice(db, *, paid=0, credited=0, debited=0, no="INV/1"):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "invoice_no": no, "invoice_date": "2026-08-01",
        "due_date": DUE, "status": "partially_paid", "total_paise": LAKH, "paid_paise": paid, "credited_paise": credited,
        "debit_note_paise": debited, "invoice_type": "Regular"})


def _receipt(db, invoice, day, amount, *, voided=False, reversed_=False):
    r = db.seed("receipts", {"firm_id": FIRM, "client_id": CLIENT, "customer_id": CUST, "receipt_date": day,
                             "amount_paise": amount, "is_reversed": reversed_})
    db.seed("receipt_allocations", {"receipt_id": r["id"], "sales_invoice_id": invoice["id"], "allocated_paise": amount,
                                    "is_voided": voided})


def _doc(db):
    out = svc.preview(db, FIRM, CLIENT, AS_OF)
    return out, out["parties"][0]["documents"][0]


def test_a_part_payment_received_during_the_late_period_is_followed_by_its_date(monkeypatch):
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    _receipt(db, inv, "2026-09-21", LAKH // 2)
    out, doc = _doc(db)
    assert (doc["interest_paise"], doc["balance_basis"], doc["balance_note"]) == (147_945, "history", None)
    assert L.CAVEAT_BALANCE_FOLLOWED in out["caveats"] and not any("UNDERSTATES" in c for c in out["caveats"])


def test_a_voided_allocation_and_a_reversed_receipt_are_not_payments(monkeypatch):
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    _receipt(db, inv, "2026-09-21", LAKH // 2)
    _receipt(db, inv, "2026-09-05", LAKH // 4, voided=True)
    _receipt(db, inv, "2026-09-06", LAKH // 4, reversed_=True)
    assert _doc(db)[1]["interest_paise"] == 147_945


def test_an_issued_credit_note_counts_from_the_start_and_a_draft_one_does_not(monkeypatch):
    """Whether the note corrected the price or recorded a later return is not recorded, so its amount is treated as never owed:
    the reading that cannot overstate. A note issued on 21 September leaves 50,000.00 owed on every late day."""
    db = _book(monkeypatch)
    inv = _invoice(db, credited=LAKH // 2)
    for status, day in (("issued", "2026-09-21"), ("draft", "2026-09-05")):
        note = db.seed("credit_notes", {"firm_id": FIRM, "client_id": CLIENT, "credit_note_date": day, "status": status})
        db.seed("credit_note_allocations", {"firm_id": FIRM, "credit_note_id": note["id"], "sales_invoice_id": inv["id"],
                                            "allocated_paise": LAKH // 2})
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (L.interest_paise(LAKH // 2, 1800, 40), "history")


def test_what_an_issued_debit_note_adds_bears_no_interest_here(monkeypatch):
    """A debit note is a separate demand on its own terms: the amount it adds is never part of this invoice's late balance, so an
    invoice paid in full before the period and then raised by a debit note owes no interest here."""
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH, debited=LAKH // 2)
    _receipt(db, inv, "2026-08-25", LAKH)
    db.seed("sales_debit_notes", {"firm_id": FIRM, "client_id": CLIENT, "sales_invoice_id": inv["id"],
                                  "debit_note_date": "2026-09-21", "applied_paise": LAKH // 2, "status": "issued"})
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (0, "history")
    # With part of the invoice still unpaid, the base is that part alone, on every late day.
    db2 = _book(monkeypatch)
    inv2 = _invoice(db2, paid=LAKH // 2, debited=LAKH // 4)
    _receipt(db2, inv2, "2026-08-25", LAKH // 2)
    db2.seed("sales_debit_notes", {"firm_id": FIRM, "client_id": CLIENT, "sales_invoice_id": inv2["id"],
                                   "debit_note_date": "2026-08-10", "applied_paise": LAKH // 4, "status": "issued"})
    assert _doc(db2)[1]["interest_paise"] == L.interest_paise(LAKH // 2, 1800, 40)


def _bank_line(db, invoice, day, amount, *, status="posted", category="Customer Payment"):
    return db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": CLIENT, "transaction_date": day, "credit_paise": amount, "debit_paise": 0,
        "category": category, "matched_entity_type": "sales_invoice", "matched_entity_id": invoice["id"], "match_status": status})


def test_a_posted_bank_line_settling_the_invoice_reduces_the_balance_from_its_date(monkeypatch):
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    _bank_line(db, inv, "2026-09-21", LAKH // 2)
    _bank_line(db, inv, "2026-09-05", LAKH // 2, status="matched")          # not posted: settled nothing
    _bank_line(db, inv, "2026-09-06", LAKH // 2, category="Bank Charges")   # a category that does not settle an invoice
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (147_945, "history")


def test_the_bank_lines_are_read_with_the_servers_access_and_not_the_callers(monkeypatch):
    """The late-interest routes ask the accounting tier, not banking, and migration 524 hides a person's bank lines as ZERO ROWS
    under a sign-in that lacks Banking: so the bank lines (and the overpayment credits beside them) are read through
    `privileged_for`, after the route's access check. Here the caller's client holds none; the server's holds the line."""
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    server = FakeDB()
    server.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": CLIENT, "transaction_date": "2026-09-21", "credit_paise": LAKH // 2, "debit_paise": 0,
        "category": "Customer Payment", "matched_entity_type": "sales_invoice", "matched_entity_id": inv["id"],
        "match_status": "posted"})
    monkeypatch.setattr(svc, "privileged_for", lambda _db: server)
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (147_945, "history")


def test_what_a_bank_line_overpaid_went_to_the_customers_credit_and_not_to_the_invoice(monkeypatch):
    """A line of 60,000.00 against 50,000.00 open: the posting put 10,000.00 on the customer's credit. Granted, undone and granted
    again (a correction loop) nets to that one 10,000.00."""
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    line = _bank_line(db, inv, "2026-09-21", 6_000_000)
    for amount, kind in ((1_000_000, "grant"), (-1_000_000, "revocation"), (1_000_000, "grant")):
        db.seed("party_credit_ledger", {"firm_id": FIRM, "client_id": CLIENT, "party_type": "customer", "party_id": CUST,
                                        "source_type": "bank_overpayment", "source_id": line["id"], "amount_paise": amount,
                                        "kind": kind})
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (147_945, "history")


def test_a_credit_applied_from_the_customers_balance_counts_from_the_start(monkeypatch):
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    db.seed("party_credit_ledger", {"firm_id": FIRM, "client_id": CLIENT, "party_type": "customer", "party_id": CUST,
                                    "kind": "application", "applied_to_type": "sales_invoice", "applied_to_id": inv["id"],
                                    "amount_paise": -(LAKH // 2)})
    doc = _doc(db)[1]
    assert (doc["interest_paise"], doc["balance_basis"]) == (L.interest_paise(LAKH // 2, 1800, 40), "history")


def test_a_history_that_does_not_account_for_the_settlement_falls_back_and_says_which_way_it_errs(monkeypatch):
    db = _book(monkeypatch)
    _invoice(db, paid=LAKH // 2)                              # paid recorded, no receipt behind it
    out, doc = _doc(db)
    assert doc["balance_basis"] == "today" and doc["interest_paise"] == 98_630
    assert "account for ₹0.00 of the ₹50,000.00 it shows as settled" in doc["balance_note"]
    assert "UNDERSTATES the interest where a payment arrived" in doc["balance_note"]
    assert any(c.startswith("For 1 invoice(s)") and "UNDERSTATES" in c for c in out["caveats"])


def test_a_history_that_cannot_be_read_falls_back_on_every_invoice_and_says_so(monkeypatch):
    db = _book(monkeypatch)
    inv = _invoice(db, paid=LAKH // 2)
    _receipt(db, inv, "2026-09-21", LAKH // 2)
    real_table = db.table

    def refuses_allocations(name):
        if name == "receipt_allocations":
            raise RuntimeError("outage")
        return real_table(name)

    monkeypatch.setattr(db, "table", refuses_allocations)
    _invoice(db, no="INV/2")                                  # nothing settled: today's balance is every day's, read or not
    out = svc.preview(db, FIRM, CLIENT, AS_OF)
    docs = {d["invoice_no"]: d for d in out["parties"][0]["documents"]}
    assert docs["INV/1"]["balance_basis"] == "today" and docs["INV/1"]["balance_note"] == svc.HISTORY_UNREAD
    assert (docs["INV/2"]["balance_basis"], docs["INV/2"]["balance_note"]) == ("history", None)
    assert L.caveat_balance_is_todays(unread=1) in out["caveats"]
    assert "for 1 invoice(s) the receipts, bank lines, credits and notes against it could not be read" in \
        L.caveat_balance_is_todays(unread=1).lower()


def test_the_prepared_draft_says_the_base_it_was_computed_on(monkeypatch):
    """Through the real sales engine: the service hands the row's basis to the draft, so the words on the line the customer will
    read are true. The invoice of the worked example, with its 50,000.00 received on 21 September."""
    from tests.test_interest_on_an_overdue_customer_balance import CALLER, CLIENT as C1, CUST as U1, FIRM as F1, _book as book
    from tests.test_interest_on_an_overdue_customer_balance import _overdue
    db = book(monkeypatch)
    inv = _overdue(db, 1, due=DUE, paid_paise=LAKH // 2, credited_paise=0, debit_note_paise=0)
    r = db.seed("receipts", {"firm_id": F1, "client_id": C1, "customer_id": U1, "receipt_date": "2026-09-21",
                             "amount_paise": LAKH // 2, "is_reversed": False})
    db.seed("receipt_allocations", {"receipt_id": r["id"], "sales_invoice_id": inv["id"], "allocated_paise": LAKH // 2,
                                    "is_voided": False})
    out = svc.prepare_drafts(db, F1, C1, U1, AS_OF, CALLER)
    draft_id = out["drafts"][0]["invoice_id"]
    lines = [ln for ln in db.rows("client_sales_invoice_lines") if ln["sales_invoice_id"] == draft_id]
    assert len(lines) == 1 and "on the balance outstanding on each of those days" in lines[0]["description"]
    assert int(lines[0]["rate_paise"]) == 147_945
