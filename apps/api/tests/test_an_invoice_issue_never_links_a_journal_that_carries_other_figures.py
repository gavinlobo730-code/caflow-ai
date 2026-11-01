"""A draft invoice whose first issue did not finish is not linked to the entry that attempt left, when the draft has changed (ledger POST-A-092).

THE SEQUENCE THIS HOLDS
    Issuing posts the journal first, then marks the invoice issued and links the entry in a second statement. If the second statement
    fails the invoice stays a draft and a live entry is in the ledger under its number and date. The CA, told the issue failed, opens the
    draft, corrects it and issues again. The posting kernel is idempotent on (firm, client, number, date), so the retry used to find the
    old entry, link the invoice to it and report success: the invoice said one amount and the ledger, the output tax and the customer's
    balance said another, with nothing naming the difference.

WHAT IS ASKED NOW
    An entry already live under the number and date is reused only if it carries the very lines the issue would post (account, debit,
    credit; order and narration do not matter). A retry of an unchanged draft still finds the same lines and still links the same entry.
    A changed draft, or an entry that cannot be read to check, refuses in a sentence and writes nothing. The default of the kernel is
    untouched: only the sales invoice builder asks, so no other caller's retry behaves differently.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import services.phase2_journal_service as pjs
from domain.accounting import journal_figures as jf, journal_source as JS
from domain.sales import issue_readiness as ir
from models.invoices import InvoiceLineIn, SalesInvoiceIn, SalesInvoiceUpdateIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


# ── the pure comparison ──────────────────────────────────────────────────────────────────────────────────────────

def _l(account, debit=0, credit=0, narration=""):
    return {"account_id": account, "debit_paise": debit, "credit_paise": credit, "narration": narration}


def test_the_same_lines_in_another_order_with_another_narration_are_the_same_figures():
    held = [_l("AR", 118_000), _l("SALES", 0, 100_000, "Sales revenue"), _l("GST", 0, 18_000)]
    proposed = [_l("GST", 0, 18_000, "tax"), _l("AR", 118_000, 0, "x"), _l("SALES", 0, 100_000)]
    assert jf.difference(held, proposed, what="invoice A/1") is None


def test_a_line_with_nothing_on_either_side_is_not_a_line():
    assert jf.difference([_l("AR", 5), _l("S", 0, 5)], [_l("AR", 5), _l("S", 0, 5), _l("X", 0, 0)], what="invoice A/1") is None


def test_two_equal_lines_are_two_lines_and_not_one():
    twice = [_l("AR", 100), _l("S", 0, 50), _l("S", 0, 50)]
    once = [_l("AR", 100), _l("S", 0, 50)]
    assert jf.difference(twice, once, what="invoice A/1") is not None
    assert jf.difference(twice, [_l("S", 0, 50), _l("AR", 100), _l("S", 0, 50)], what="invoice A/1") is None


def test_the_same_accounts_with_the_sides_swapped_are_other_figures():
    """A debit where a credit was is not the same entry, whatever the amounts: the side is part of the figure."""
    assert jf.difference([_l("AR", 100), _l("S", 0, 100)], [_l("AR", 0, 100), _l("S", 100, 0)], what="invoice A/1") is not None


def test_one_paise_is_a_difference():
    """Nothing is rounded and nothing has a tolerance: a tolerance on a posted figure is a posted figure that is wrong by that much."""
    assert jf.difference([_l("AR", 11_800), _l("S", 0, 11_800)], [_l("AR", 11_801), _l("S", 0, 11_801)], what="invoice A/1") is not None


def test_a_different_total_is_worded_in_rupees_for_both_sides():
    said = jf.difference([_l("AR", 118_000), _l("S", 0, 118_000)], [_l("AR", 236_000), _l("S", 0, 236_000)], what="invoice A/1")
    assert said is not None
    assert "₹1,180.00" in said and "₹2,360.00" in said, said
    assert "paise" not in said, "a sentence for a person names rupees, not a count of paise"
    assert "invoice A/1" in said and "Nothing was changed" in said


def test_the_same_total_in_other_lines_is_worded_as_other_lines_and_not_as_other_accounts():
    """The same total can sit on other accounts or on the same accounts split differently (a rate corrected with the total held), so
    the sentence claims neither."""
    said = jf.difference([_l("AR", 100), _l("S", 0, 100)], [_l("AR", 100), _l("OTHER", 0, 100)], what="invoice A/1")
    assert said is not None and "not in the same lines" in said and "different accounts" not in said, said
    split = jf.difference([_l("AR", 100), _l("S", 0, 60), _l("G", 0, 40)], [_l("AR", 100), _l("S", 0, 70), _l("G", 0, 30)], what="invoice A/1")
    assert split is not None and "not in the same lines" in split, split


def test_the_advice_fits_a_draft_and_an_issued_invoice_and_says_who_can_reverse():
    for said in (jf.difference([_l("AR", 1)], [_l("AR", 2)], what="invoice A/1"),
                 jf.elsewhere(what="invoice A/1", number="A/0", date="2026-04-05"),
                 jf.unreadable(what="invoice A/1")):
        assert "issue the draft again" not in said and "the figures the draft has" not in said, said
    assert "A Partner can reverse that entry" in jf.difference([_l("AR", 1)], [_l("AR", 2)], what="invoice A/1")
    assert "if it is still a draft" in jf.elsewhere(what="invoice A/1", number="A/0", date="2026-04-05")


def test_an_entry_held_elsewhere_is_worded_with_its_number_and_date_and_says_it_would_count_twice():
    said = jf.elsewhere(what="invoice A/2", number="A/1", date="2026-04-05")
    assert "A/1" in said and "2026-04-05" in said and "twice" in said and "Nothing was changed" in said, said


def test_an_entry_that_could_not_be_read_has_a_sentence_that_says_so():
    said = jf.unreadable(what="invoice A/1")
    assert "could not be read" in said and "Nothing was changed" in said


def test_a_lookup_that_failed_does_not_say_an_entry_is_in_the_ledger():
    """Two different facts, two sentences: the lines of an entry that IS there could not be read, or the ledger could not be asked and
    nothing is known to be there. Only the first may say an entry exists."""
    known, unknown = jf.unreadable(what="invoice A/1"), jf.unreadable(what="invoice A/1", known_entry=False)
    assert "already in the ledger" in known
    assert "already in the ledger" not in unknown and "could not be checked" in unknown and "Nothing was changed" in unknown, unknown


def test_the_held_elsewhere_sentence_does_not_say_the_draft_when_the_invoice_is_issued():
    said = jf.elsewhere(what="invoice A/2", number="A/1", date="2026-04-05")
    assert "what the draft says now" not in said and "invoice A/2 has now" in said, said


def test_the_sentence_for_a_draft_that_cannot_be_deleted_names_the_entry_and_the_remedy():
    said = jf.kept_by_delete(what="invoice A/1", number="A/1", date="2026-04-05")
    assert said.startswith("Invoice A/1 cannot be deleted") and "A/1" in said and "2026-04-05" in said, said
    assert "A Partner can reverse that entry" in said and "Nothing was changed" in said


def test_the_refusal_is_a_value_error_so_every_caller_that_stops_on_a_refusal_stops():
    assert issubclass(jf.EntryCannotBeReused, ValueError)


# ── the kernel ───────────────────────────────────────────────────────────────────────────────────────────────────

def _kernel_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    rent = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_code": "5100", "account_name": "Rent Expense",
                                         "account_type": "Expense", "is_active": True})["id"]
    bank = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_code": "1001", "account_name": "HDFC Bank",
                                         "account_type": "Asset", "is_active": True})["id"]
    return db, rent, bank


def _post(db, rent, bank, amount=500_000, *, must_match=None, credit_to=None, ref="INV-1", date="2026-04-05", source_id=None):
    lines = [{"account_id": rent, "debit_paise": amount, "credit_paise": 0},
             {"account_id": credit_to or bank, "debit_paise": 0, "credit_paise": amount}]
    kwargs = {} if must_match is None else {"must_match": must_match}
    if source_id:
        kwargs.update(source_type="SalesInvoice", source_id=source_id)
    return pjs.phase2_journal_service._create_journal(
        db, firm_id=FIRM, client_id="CLI", entry_date=date, reference_no=ref, narration="x", entry_type="Sales",
        lines=lines, **kwargs)


def _live(db):
    return [e for e in db.rows("journal_entries") if e.get("reference_no") == "INV-1" and not e.get("deleted_at")]


def test_a_retry_with_the_same_figures_gets_the_same_entry_back(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, must_match="invoice INV-1")
    again = _post(db, rent, bank, must_match="invoice INV-1")
    assert again == first and len(_live(db)) == 1


def test_a_retry_with_other_figures_is_refused_and_writes_nothing(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, 500_000, must_match="invoice INV-1")
    lines_before = list(db.rows("journal_lines"))
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, 700_000, must_match="invoice INV-1")
    assert "₹5,000.00" in str(refused.value) and "₹7,000.00" in str(refused.value)
    assert [e["id"] for e in _live(db)] == [first]
    assert db.rows("journal_lines") == lines_before, "a refused reuse changed the ledger's lines"


def test_a_retry_that_puts_the_same_total_on_another_account_is_refused(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    other = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_code": "1002", "account_name": "Cash",
                                          "account_type": "Asset", "is_active": True})["id"]
    _post(db, rent, bank, must_match="invoice INV-1")
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, must_match="invoice INV-1", credit_to=other)
    assert "not in the same lines" in str(refused.value)


def test_without_the_opt_in_the_kernel_reuses_whatever_is_there_as_it_always_did(monkeypatch):
    """The control that keeps every other caller's behaviour: receipts, payments, imports and the rest do not ask."""
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, 500_000)
    assert _post(db, rent, bank, 700_000) == first


def test_an_entry_that_cannot_be_read_is_not_taken_to_be_the_same(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, must_match="invoice INV-1")
    real_table = db.table

    def table(name):
        if name == "journal_lines":
            raise RuntimeError("lines unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, must_match="invoice INV-1")
    assert "could not be read" in str(refused.value)
    assert [e["id"] for e in _live(db)] == [first]


def test_a_discarded_or_reversed_entry_does_not_hold_the_number(monkeypatch):
    """The fast path still looks at live, unreversed entries only: an entry the CA discarded frees its number, and the check never
    runs against it."""
    db, rent, bank = _kernel_setup(monkeypatch)
    dead = _post(db, rent, bank, 500_000, must_match="invoice INV-1")
    [row] = [e for e in db.rows("journal_entries") if e["id"] == dead]
    row["deleted_at"] = "2026-05-01T09:00:00+00:00"
    fresh = _post(db, rent, bank, 700_000, must_match="invoice INV-1")
    assert fresh != dead and [e["id"] for e in _live(db)] == [fresh]


def test_a_header_lookup_that_fails_refuses_and_does_not_fall_through_to_the_database(monkeypatch):
    """The lookup under the number and date is a read too. Failing open there reaches the database's own duplicate handling, which
    returns the winner without comparing, which is the bug this item fixes."""
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, 500_000, must_match="invoice INV-1")
    real_table = db.table

    def table(name):
        if name == "journal_entries":
            raise RuntimeError("header unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, 700_000, must_match="invoice INV-1")
    # The lookup itself failed, so no entry is KNOWN to be there: the sentence must not say one is (found by the independent review).
    assert "could not be checked" in str(refused.value) and "already in the ledger" not in str(refused.value), str(refused.value)
    monkeypatch.setattr(db, "table", real_table)
    assert [e["id"] for e in _live(db)] == [first]


def test_without_the_opt_in_a_failing_header_lookup_still_falls_through_as_it_always_did(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, 500_000)
    real_table = db.table
    calls = {"n": 0}

    def table(name):
        if name == "journal_entries" and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("one blip")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    assert _post(db, rent, bank, 500_000) == first, "the database's own duplicate handling no longer answered"


def test_a_reversed_entry_does_not_hold_the_number_either(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    old = _post(db, rent, bank, 500_000, must_match="invoice INV-1")
    [row] = [e for e in db.rows("journal_entries") if e["id"] == old]
    row["is_reversed"] = True
    fresh = _post(db, rent, bank, 700_000, must_match="invoice INV-1")
    assert fresh != old


def test_an_entry_of_this_document_under_another_number_blocks_a_second_posting(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    first = _post(db, rent, bank, 500_000, must_match="invoice INV-1", source_id="DOC-1")
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, 500_000, must_match="invoice INV-2", ref="INV-2", source_id="DOC-1")
    assert "INV-1" in str(refused.value) and "2026-04-05" in str(refused.value) and "twice" in str(refused.value)
    assert [e["id"] for e in db.rows("journal_entries")] == [first]


def test_an_entry_of_this_document_under_another_date_blocks_a_second_posting(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    _post(db, rent, bank, 500_000, must_match="invoice INV-1", source_id="DOC-1")
    with pytest.raises(jf.EntryCannotBeReused):
        _post(db, rent, bank, 500_000, must_match="invoice INV-1", date="2026-04-09", source_id="DOC-1")
    assert len(db.rows("journal_entries")) == 1


def test_another_documents_entry_or_a_reversed_or_discarded_one_does_not_block(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    one = _post(db, rent, bank, 500_000, must_match="invoice INV-1", source_id="DOC-1")
    # another document, another number: not blocked
    _post(db, rent, bank, 500_000, must_match="invoice INV-2", ref="INV-2", source_id="DOC-2")
    # the first document's entry reversed: the document may be posted afresh under a new number
    [row] = [e for e in db.rows("journal_entries") if e["id"] == one]
    row["is_reversed"] = True
    _post(db, rent, bank, 500_000, must_match="invoice INV-3", ref="INV-3", source_id="DOC-1")
    # ... and discarded the same way
    [third] = [e for e in db.rows("journal_entries") if e.get("reference_no") == "INV-3"]
    third["deleted_at"] = "2026-05-01T09:00:00+00:00"
    _post(db, rent, bank, 500_000, must_match="invoice INV-4", ref="INV-4", source_id="DOC-1")


def test_the_cost_of_goods_entry_of_an_invoice_is_not_read_as_the_invoice_held_under_another_number(monkeypatch):
    """The COGS journal of an invoice carries the invoice's source type and id (that is how a ledger row finds its document) under the
    number '<no>-COGS' and the entry type Journal. It is not the document's posting. Read as one, an invoice with stock lines and no
    link refused to be reposted, and the sentence advised reversing the cost of goods sold (found by the independent review)."""
    db, rent, bank = _kernel_setup(monkeypatch)
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "reference_no": "INV-1-COGS", "entry_date": "2026-04-05",
                                "entry_type": "Journal", "source_type": "SalesInvoice", "source_id": "DOC-1", "is_reversed": False,
                                "deleted_at": None, "reversal_of": None})
    assert _post(db, rent, bank, must_match="invoice INV-1", source_id="DOC-1"), "the cost-of-goods entry blocked the invoice's posting"
    assert pjs.phase2_journal_service.live_entry_of_source(
        db, firm_id=FIRM, client_id="CLI", source_type="SalesInvoice", source_id="DOC-1", entry_type="Sales")["reference_no"] == "INV-1"


def test_an_entry_of_another_source_type_with_the_same_source_id_does_not_block(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "reference_no": "RCPT-9", "entry_date": "2026-04-06",
                                "entry_type": "Sales", "source_type": "Receipt", "source_id": "DOC-1", "is_reversed": False,
                                "deleted_at": None, "reversal_of": None})
    assert _post(db, rent, bank, must_match="invoice INV-1", source_id="DOC-1")


def test_another_clients_entry_with_the_same_source_id_does_not_block(monkeypatch):
    """The source lookup is the client's own: an id is unique in practice, but a lookup that is not tied to the client would let one
    client's entry refuse another client's posting."""
    db, rent, bank = _kernel_setup(monkeypatch)
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "OTHER", "reference_no": "X-1", "entry_date": "2026-04-05",
                                "source_type": "SalesInvoice", "source_id": "DOC-1", "is_reversed": False, "deleted_at": None})
    assert _post(db, rent, bank, 500_000, must_match="invoice INV-1", source_id="DOC-1")


def test_a_source_lookup_that_fails_refuses(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    real_table = db.table
    state = {"entries_reads": 0}

    def table(name):
        if name == "journal_entries":
            state["entries_reads"] += 1
            if state["entries_reads"] == 2:      # the first read is the lookup under the number and date; the second is the source
                raise RuntimeError("source unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(jf.EntryCannotBeReused) as refused:
        _post(db, rent, bank, 500_000, must_match="invoice INV-1", source_id="DOC-1")
    assert "could not be checked" in str(refused.value) and "already in the ledger" not in str(refused.value), str(refused.value)
    monkeypatch.setattr(db, "table", real_table)
    assert db.rows("journal_entries") == []


# ── the invoice issue ────────────────────────────────────────────────────────────────────────────────────────────

def _route_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Goods", "kind": "good"})
    return db


def _line(rate_paise):
    return InvoiceLineIn(description="item", quantity=1, rate_paise=rate_paise, gst_rate_percent=18.0, service_catalogue_id="SVC-CLI")


def _new_invoice(no="INV-1", rate_paise=100_000):
    res = si.create_invoice(SalesInvoiceIn(client_id="CLI", customer_id="CUST-CLI", invoice_no=no, invoice_date="2025-06-01",
                                           supply_state_code="27", lines=[_line(rate_paise)]), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _row(db, invoice_id):
    return next(r for r in db.rows("client_sales_invoices") if r["id"] == invoice_id)


def _entries(db, number):
    return [e for e in db.rows("journal_entries") if e.get("reference_no") == number and not e.get("deleted_at")]


def _as_if_the_preflight_had_said_ready(monkeypatch):
    """The posting asks the same question as the pre-flight and refuses itself, so a change that lands between the pre-flight and the
    click (or a caller that never asked) is still caught. Taking the pre-flight out of the way is how that second line is driven."""
    monkeypatch.setattr(si.issue_readiness_service, "blockers_for_sales_invoice", lambda *a, **k: [])


def _preflight_codes(invoice_id):
    res = si.issue_preflight(invoice_id, CALLER)
    assert res["success"] is True, res
    return [b["code"] for b in res["data"]["blockers"]], res["data"]


def _issue_that_fails_after_posting(monkeypatch, invoice_id):
    """The failure this item is about: the journal is posted, then the second statement does not happen."""
    real = si.update_header

    def broken(*args, **kwargs):
        raise RuntimeError("the second write did not happen")

    monkeypatch.setattr(si, "update_header", broken)
    res = si.issue_invoice(invoice_id, CALLER)
    monkeypatch.setattr(si, "update_header", real)
    assert res["success"] is False, res
    return res


def test_the_failed_issue_leaves_a_draft_and_a_live_entry(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    assert _row(db, invoice_id)["status"] == "draft"
    assert len(_entries(db, "INV-1")) == 1, "this test's premise: a live entry is left behind"


def test_an_unchanged_draft_is_issued_against_the_entry_that_is_already_there(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-1")

    res = si.issue_invoice(invoice_id, CALLER)

    assert res["success"] is True, res
    assert res["data"]["journal_entry_id"] == left["id"]
    assert _row(db, invoice_id)["status"] == "issued"
    assert len(_entries(db, "INV-1")) == 1, "a retry of an unchanged draft posted a second entry"


def test_a_draft_changed_after_the_failed_issue_is_not_linked_to_the_old_entry(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice(rate_paise=100_000)
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-1")
    lines_before = list(db.rows("journal_lines"))

    edited = si.update_invoice(invoice_id, SalesInvoiceUpdateIn(lines=[_line(250_000)]), CALLER)
    assert edited["success"] is True, edited
    _as_if_the_preflight_had_said_ready(monkeypatch)

    res = si.issue_invoice(invoice_id, CALLER)

    assert res["success"] is False, "the invoice was issued against an entry that carries the old figures"
    assert res["error"].startswith("Cannot issue — An entry for invoice INV-1"), res["error"]
    assert "seed the Chart of Accounts" not in res["error"], "the refusal blamed the chart of accounts"
    assert "₹1,180.00" in res["error"] and "₹2,950.00" in res["error"], res["error"]
    assert _row(db, invoice_id)["status"] == "draft" and not _row(db, invoice_id).get("journal_entry_id")
    assert [e["id"] for e in _entries(db, "INV-1")] == [left["id"]]
    assert db.rows("journal_lines") == lines_before, "the refusal changed the ledger"


def test_a_draft_whose_number_was_corrected_after_the_failed_issue_is_not_posted_a_second_time(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice(no="INV-1")
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-1")
    edited = si.update_invoice(invoice_id, SalesInvoiceUpdateIn(invoice_no="INV-2"), CALLER)
    assert edited["success"] is True, edited
    _as_if_the_preflight_had_said_ready(monkeypatch)

    res = si.issue_invoice(invoice_id, CALLER)

    assert res["success"] is False and "INV-1" in res["error"] and "twice" in res["error"], res
    assert "seed the Chart of Accounts" not in res["error"]
    assert _row(db, invoice_id)["status"] == "draft"
    assert [e["id"] for e in db.rows("journal_entries")] == [left["id"]], "a second live entry was posted for the same invoice"


def test_a_draft_whose_date_was_corrected_after_the_failed_issue_is_not_posted_a_second_time(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    edited = si.update_invoice(invoice_id, SalesInvoiceUpdateIn(invoice_date="2025-06-03"), CALLER)
    assert edited["success"] is True, edited
    _as_if_the_preflight_had_said_ready(monkeypatch)

    res = si.issue_invoice(invoice_id, CALLER)

    assert res["success"] is False and "2025-06-01" in res["error"], res
    assert len(db.rows("journal_entries")) == 1


@pytest.mark.parametrize("pos,round_off", [("27", False), ("29", False), ("27", True), ("29", True)])
def test_an_unchanged_draft_of_each_shape_is_still_issued_against_its_own_entry(monkeypatch, pos, round_off):
    """The false refusal that would be worse than the bug: intra-state and inter-state, rounded and not. A retry of an unchanged draft
    finds the lines it posted before, whatever heads and round-off they carry."""
    db = _route_setup(monkeypatch)
    if round_off:
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_code": "5900", "account_name": "Round Off",
                                      "account_type": "Expense", "is_active": True})
    res = si.create_invoice(SalesInvoiceIn(client_id="CLI", customer_id="CUST-CLI", invoice_no="INV-9", invoice_date="2025-06-01",
                                           supply_state_code=pos, round_off_enabled=round_off, lines=[_line(123_457)]), CALLER)
    assert res["success"] is True, res
    invoice_id = res["data"]["id"]
    if round_off:
        assert int(_row(db, invoice_id).get("round_off_paise") or 0) != 0, "this case must carry a round-off line to mean anything"
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-9")

    again = si.issue_invoice(invoice_id, CALLER)

    assert again["success"] is True, again
    assert again["data"]["journal_entry_id"] == left["id"] and len(_entries(db, "INV-9")) == 1


def test_the_preflight_names_an_entry_the_draft_no_longer_matches_before_the_click_and_the_issue_refuses_from_it(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice(rate_paise=100_000)
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    codes, _ = _preflight_codes(invoice_id)
    assert codes == [], "an unchanged draft with its own entry left behind is ready: the click links it"

    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(lines=[_line(250_000)]), CALLER)
    lines_before, entries_before = list(db.rows("journal_lines")), list(db.rows("journal_entries"))
    codes, data = _preflight_codes(invoice_id)

    assert codes == [ir.ENTRY_ALREADY_IN_LEDGER] and data["ready"] is False
    [blocker] = data["blockers"]
    assert blocker["action"] is None and "invoice INV-1" in blocker["message"]
    assert "₹1,180.00" in blocker["message"] and "₹2,950.00" in blocker["message"], blocker["message"]
    assert db.rows("journal_lines") == lines_before and db.rows("journal_entries") == entries_before, "the pre-flight wrote"

    with pytest.raises(HTTPException) as refused:
        si.issue_invoice(invoice_id, CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail["code"] == ir.ENTRY_ALREADY_IN_LEDGER and refused.value.detail["message"] == blocker["message"]
    assert _row(db, invoice_id)["status"] == "draft"
    assert db.rows("journal_entries") == entries_before


def test_the_preflight_names_an_entry_held_under_another_number_or_date(monkeypatch):
    _route_setup(monkeypatch)
    invoice_id = _new_invoice(no="INV-1")
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(invoice_no="INV-2"), CALLER)
    codes, data = _preflight_codes(invoice_id)
    assert codes == [ir.ENTRY_ALREADY_IN_LEDGER] and "INV-1" in data["blockers"][0]["message"] and "twice" in data["blockers"][0]["message"]


def test_a_draft_with_nothing_left_behind_has_no_such_blocker_and_a_missing_chart_is_the_only_one_named(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    assert _preflight_codes(invoice_id)[0] == []
    for row in db.rows("chart_of_accounts"):
        row["is_active"] = False
    codes, _ = _preflight_codes(invoice_id)
    assert codes == [ir.COA_MISSING], "with the chart missing the lines cannot be built, so the chart is the only thing to name"


def test_a_preflight_whose_lines_cannot_be_built_does_not_stop_a_draft_the_posting_would_accept(monkeypatch):
    """Needs an entry to compare with, because the lines are only built when one is found; with none the patched failure never fires and
    the test would pass for no reason (found by the independent review)."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    assert len(_entries(db, "INV-1")) == 1, "this test's premise: an entry is there, so the lines are asked for"
    calls = {"n": 0}

    def cannot_build(*a, **k):
        calls["n"] += 1
        raise RuntimeError("unreadable")

    monkeypatch.setattr(pjs.phase2_journal_service, "sales_invoice_lines", cannot_build)
    assert pjs.phase2_journal_service.entry_left_behind_problem(db, FIRM, "CLI", _row(db, invoice_id)) is None
    assert calls["n"] >= 1, "the lines were never asked for, so the failure under test never happened"


def test_a_pre_flight_does_not_name_the_cost_of_goods_entry_as_a_stranded_sale(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "reference_no": "INV-1-COGS", "entry_date": "2025-06-01",
                                "entry_type": "Journal", "source_type": JS.SALES_INVOICE, "source_id": invoice_id, "is_reversed": False,
                                "deleted_at": None, "reversal_of": None})
    assert pjs.phase2_journal_service.entry_left_behind_problem(db, FIRM, "CLI", _row(db, invoice_id)) is None


# ── a draft with an entry behind it is not deleted ─────────────────────────────────────────────────────────────────

def test_a_draft_with_a_live_entry_behind_it_cannot_be_deleted_until_the_entry_is_reversed(monkeypatch):
    """The sequence the reviewer found: issue draft A, the posting succeeds and the second write fails; delete A (a draft may be
    deleted); create B with the same number on another date and issue it. Nothing is found under that number and date and nothing
    under B's source, so a second live entry posted and the sale was counted twice. The delete is refused while the entry is live."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-1")

    with pytest.raises(HTTPException) as refused:
        si.delete_invoice(invoice_id, CALLER)
    assert refused.value.status_code == 409 and "cannot be deleted yet" in refused.value.detail, refused.value.detail
    assert "INV-1" in refused.value.detail and "2025-06-01" in refused.value.detail and "Nothing was changed" in refused.value.detail
    assert _row(db, invoice_id)["status"] == "draft", "the draft was deleted although the entry is still live"

    pjs.phase2_journal_service.reverse_entry(db, FIRM, left["id"], "2025-06-02", created_by=None)
    done = si.delete_invoice(invoice_id, CALLER)
    assert done["success"] is True and done["data"]["deleted"] is True
    assert [r for r in db.rows("client_sales_invoices") if r["id"] == invoice_id] == []


def test_a_draft_with_nothing_behind_it_is_deleted_as_it_always_was(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    done = si.delete_invoice(invoice_id, CALLER)
    assert done["success"] is True and done["data"]["deleted"] is True
    assert [r for r in db.rows("client_sales_invoices") if r["id"] == invoice_id] == []


def test_a_draft_whose_ledger_cannot_be_read_is_not_deleted(monkeypatch):
    """A check that cannot look is not a check: the delete refuses, in words that do not claim an entry exists."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    real_table = db.table

    def table(name):
        if name == "journal_entries":
            raise RuntimeError("ledger unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(HTTPException) as refused:
        si.delete_invoice(invoice_id, CALLER)
    assert refused.value.status_code == 409 and "could not be checked" in refused.value.detail, refused.value.detail
    assert "already in the ledger" not in refused.value.detail
    monkeypatch.setattr(db, "table", real_table)
    assert _row(db, invoice_id)["status"] == "draft"


def test_the_cost_of_goods_entry_does_not_stop_a_draft_being_deleted(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "reference_no": "INV-1-COGS", "entry_date": "2025-06-01",
                                "entry_type": "Journal", "source_type": JS.SALES_INVOICE, "source_id": invoice_id, "is_reversed": False,
                                "deleted_at": None, "reversal_of": None})
    assert si.delete_invoice(invoice_id, CALLER)["data"]["deleted"] is True


def test_reversing_the_stranded_entry_clears_the_blocker_and_the_draft_can_be_issued(monkeypatch):
    """The remedy the refusal advises. A reversal copies the document's source onto itself and is not itself marked reversed, so a
    lookup by source that did not skip reversals would find the reversal and block the draft for ever (found by the independent review)."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice(rate_paise=100_000)
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    [left] = _entries(db, "INV-1")
    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(lines=[_line(250_000)]), CALLER)
    assert _preflight_codes(invoice_id)[0] == [ir.ENTRY_ALREADY_IN_LEDGER]

    reversal_id = pjs.phase2_journal_service.reverse_entry(db, FIRM, left["id"], "2025-06-02", created_by=None)

    assert [e for e in db.rows("journal_entries") if e["id"] == reversal_id][0].get("source_id") == invoice_id, \
        "this test's premise: the reversal carries the document's source"
    assert _preflight_codes(invoice_id)[0] == [], "reversing the stranded entry did not clear the blocker"
    res = si.issue_invoice(invoice_id, CALLER)
    assert res["success"] is True, res
    live = [e for e in _entries(db, "INV-1") if not e.get("is_reversed")]
    assert [e["id"] for e in live] == [res["data"]["journal_entry_id"]] and live[0]["id"] != left["id"]


def test_a_reversal_of_this_documents_entry_does_not_block_a_second_posting_in_the_kernel(monkeypatch):
    db, rent, bank = _kernel_setup(monkeypatch)
    db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "reference_no": "REV-X", "entry_date": "2026-04-06",
                                "source_type": "SalesInvoice", "source_id": "DOC-1", "is_reversed": False, "deleted_at": None,
                                "reversal_of": "some-original"})
    assert _post(db, rent, bank, must_match="invoice INV-1", source_id="DOC-1")


def test_a_ledger_that_cannot_be_read_makes_the_preflight_silent_and_the_posting_refuses(monkeypatch):
    """A pre-flight is a reading and not a gate: on a failed read it says nothing (it must not tell a person an entry exists on no
    evidence), while the posting, which is the gate, refuses because a check that cannot look is not a check."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    real_table = db.table

    def table(name):
        if name == "journal_entries":
            raise RuntimeError("ledger unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    assert pjs.phase2_journal_service.entry_left_behind_problem(db, FIRM, "CLI", _row(db, invoice_id)) is None
    assert _preflight_codes(invoice_id)[0] == []
    res = si.issue_invoice(invoice_id, CALLER)
    # A first-ever issue: nothing is in the ledger, so the refusal must not claim an entry is.
    assert res["success"] is False and "could not be checked" in res["error"] and "already in the ledger" not in res["error"], res
    monkeypatch.setattr(db, "table", real_table)
    assert _row(db, invoice_id)["status"] == "draft" and _entries(db, "INV-1") == []


@pytest.mark.parametrize("which", ["the entry's lines", "the lookup by source"])
def test_each_read_the_check_makes_is_silent_in_the_preflight_and_refuses_in_the_posting(monkeypatch, which):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    if which == "the entry's lines":
        _issue_that_fails_after_posting(monkeypatch, invoice_id)     # an entry exists, so its lines are read
    real_table = db.table
    entries_reads = {"n": 0}

    def table(name):
        if which == "the entry's lines" and name == "journal_lines":
            raise RuntimeError("lines unreadable")
        if which == "the lookup by source" and name == "journal_entries":
            entries_reads["n"] += 1
            if entries_reads["n"] % 2 == 0:   # each check reads the number-and-date lookup first and the lookup by source second
                raise RuntimeError("source unreadable")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    assert pjs.phase2_journal_service.entry_left_behind_problem(db, FIRM, "CLI", _row(db, invoice_id)) is None
    entries_reads["n"] = 0
    res = si.issue_invoice(invoice_id, CALLER)
    # Unreadable LINES of an entry that is known to be there say so; a failed lookup says only that the ledger could not be checked.
    words = "could not be read" if which == "the entry's lines" else "could not be checked"
    assert res["success"] is False and words in res["error"], res


def test_a_clean_draft_costs_the_preflight_two_ledger_reads_and_no_chart_lookups(monkeypatch):
    """The lines the issue would post are built only when an entry is found to compare them with; the common case, nothing left behind,
    must not add account lookups to every pre-flight and every issue click."""
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    real_table = db.table
    seen: list = []

    def table(name):
        seen.append(name)
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    assert pjs.phase2_journal_service.entry_left_behind_problem(db, FIRM, "CLI", _row(db, invoice_id)) is None
    assert seen == ["journal_entries", "journal_entries"], seen


def test_the_preflight_and_the_issue_agree_about_a_corrected_date(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice()
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(invoice_date="2025-06-03"), CALLER)
    codes, data = _preflight_codes(invoice_id)
    assert codes == [ir.ENTRY_ALREADY_IN_LEDGER] and "2025-06-01" in data["blockers"][0]["message"]
    with pytest.raises(HTTPException) as refused:
        si.issue_invoice(invoice_id, CALLER)
    assert refused.value.status_code == 422 and refused.value.detail["code"] == ir.ENTRY_ALREADY_IN_LEDGER
    assert len(db.rows("journal_entries")) == 1


def test_an_issued_invoice_with_no_link_is_not_reposted_onto_an_entry_with_other_figures(monkeypatch):
    db = _route_setup(monkeypatch)
    invoice_id = _new_invoice(rate_paise=100_000)
    _issue_that_fails_after_posting(monkeypatch, invoice_id)
    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(lines=[_line(250_000)]), CALLER)
    row = _row(db, invoice_id)
    row["status"], row["journal_entry_id"] = "issued", None

    res = si.repost_journal(invoice_id, CALLER)

    assert res["success"] is False and res["error"].startswith("Cannot repost — An entry for invoice INV-1"), res
    assert "Seed the Chart of Accounts" not in res["error"], "the refusal blamed the chart of accounts"
    assert "issue the draft again" not in res["error"], "an issued invoice was told to issue the draft"
    assert "A Partner can reverse that entry" in res["error"]
    assert not _row(db, invoice_id).get("journal_entry_id")


def test_the_builder_for_the_sales_invoice_asks_and_the_others_do_not():
    """The opt-in is on the one builder whose document is a draft with a live entry behind it; the others keep the kernel's default."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(pjs))
    asking = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("journal_for_"):
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "_create_journal" \
                        and any(k.arg == "must_match" for k in call.keywords):
                    asking.add(fn.name)
    assert asking == {"journal_for_sales_invoice"}, asking


def test_no_other_caller_of_the_kernel_anywhere_asks():
    """The scan above reads the `journal_for_*` builders of one module. The opt-in must also be absent from every other call of
    `_create_journal` in the backend (a reversal, the cost-of-goods journal, a job), whose retries keep the kernel's default."""
    import ast
    import pathlib
    root = pathlib.Path(pjs.__file__).resolve().parents[1]
    asking = set()
    for folder in ("services", "routers", "domain", "repositories", "jobs", "core"):
        for path in (root / folder).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(fn):
                    if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "_create_journal" \
                            and any(k.arg == "must_match" for k in call.keywords):
                        asking.add((path.relative_to(root).as_posix(), fn.name))
    assert asking == {("services/phase2_journal_service.py", "journal_for_sales_invoice")}, asking
