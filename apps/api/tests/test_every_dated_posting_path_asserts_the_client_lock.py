"""
The FY lock is the firm's own switch. The CLIENT lock is the portal's.

THE RULE THIS STATES
    A path that writes a dated accounting fact for a client must ask BOTH:

      period_validation_service.validate_posting_date(firm_id, date)
          — the financial year the FIRM closed (migration 020). Firm-scoped:
            it takes no client_id and cannot know about a filed return.

      period_lock_service.assert_open(db, firm_id, client_id, date)
          — the period a RETURN has closed, or a client year-end has
            (migrations 266/267/289/361). Client-scoped, answered in SQL by the
            same function the journal edit path enforces with.

    They are different questions with different answers, and only the second
    one knows that this client's GSTR-3B for June went to the portal on 20
    July. Checking the first alone reads as a guard and is not one.

WHAT THIS LIST IS NOT, SINCE MIGRATION 361
    It is not a list of paths that can post into a closed period. The posting
    KERNEL now asks `period_closure_reason` for every entry it writes, so the
    firm's locked year and the client's finalised year-end reach every one of
    these paths whether they ask or not.

    What is still missing on each is the FILED-RETURN branch, which the kernel
    deliberately does not carry: a filed GSTR-1 freezes the supplies it
    reported, not the whole ledger, and refusing every June posting from 11
    July would stop routine bookkeeping for every client in the practice.
    Migration 361's header carries the argument. So an entry here means "this
    path can write a dated fact inside a period whose return has gone to the
    portal", and whether that matters depends on whether the fact could change
    what the return said.

WHY A LIST OF DEBT RATHER THAN A CLEAN ASSERTION
    Thirty-four functions ask the first question and not the second. Some of
    those are correct and argued; most are simply not done yet. A guard that
    demanded all of them at once would have to be switched off, and a guard
    that is off protects nothing — so the debt is NAMED, with a reason each,
    and this test fails if the list GROWS.

    Same shape as test_no_posting_path_names_a_ledger_by_string.py's
    STILL_NAMING_IT, for the same reason: the entries are the work, and a list
    that can only shrink turns "we will get to it" into something a test can
    hold you to.
"""
from __future__ import annotations

import ast
import pathlib

API = pathlib.Path(__file__).resolve().parent.parent

# function -> why it does not (yet) assert the client lock. Entries may be
# REMOVED as each is done. Adding one needs a reason that survives review.
NOT_YET: dict[str, str] = {
    # ── Deliberate, argued where the code lives ──────────────────────────────
    "services/receipt_service.py:create_receipt_core":
        "DELIBERATE — a receipt moves Bank and Debtors and touches no output "
        "tax; public.filings records only GSTR-1/3B, returns of SUPPLIES. "
        "Argued in the module and pinned by test_documents_locked_by_filed_"
        "return.py::test_a_receipt_is_deliberately_NOT_locked_by_a_filed_return.",
    "services/receipt_service.py:create_foreign_receipt":
        "DELIBERATE — same argument as create_receipt_core.",
    "services/opening_balance_service.py:post_opening_balances":
        "Opening balances are dated the FY's first day by construction; the "
        "year-open check is the question that applies to them.",
    "services/period_validation_service.py:validate_posting_date_cached":
        "This IS the FY check. Not a posting path.",
    "routers/service_catalogue.py:_resolve_opening_balance_date":
        "Resolves a date; posts nothing.",

    # ── Cancellations and reversals: the reversal is dated TODAY ─────────────
    # These post into an OPEN period on purpose, so the ledger never disagrees
    # with a filed return. What changes is the source document's status — and
    # a filed return's payload is frozen at filing (gst_filing_record_service
    # stores filing_data), so a regenerated return is not what a CA is shown.
    # Left out of this phase deliberately: adding the lock here would REFUSE a
    # legitimate cancellation, and whether it should is a return-regeneration
    # question rather than a posting one.
    "routers/sales_invoices.py:cancel_invoice":
        "Cancellation reversal is dated today; see the block comment above.",
    "routers/purchase_bills.py:cancel_purchase_bill":
        "Cancellation reversal is dated today; see the block comment above.",
    "routers/accounting.py:reverse_journal_entry":
        "The reversal is dated today by construction; see the block comment above.",
    "routers/payroll.py:reverse_run":
        "Payroll run reversal, dated today; see the block comment above.",
    "services/reversal_service.py:reverse_receipt":
        "Receipt reversal, dated today; see the block comment above.",
    "services/reversal_service.py:reverse_payment":
        "Payment reversal, dated today; see the block comment above.",
    "services/bank_posting_service.py:undo":
        "Undo posts a dated-today reversal; see the block comment above.",

    # ── Not yet done. Each is one call in the shape this phase established ───
    "routers/sales_invoices.py:repost_journal":
        "Posts a journal at the INVOICE's own date, so it can land in a filed "
        "period even though the request is made today.",
    "routers/fixed_assets.py:create_asset":
        "Posts the acquisition journal at the asset's purchase date, which may "
        "sit inside a filed GSTR-3B whose ITC the asset's tax belongs to.",
    "routers/fixed_assets.py:dispose_asset":
        "Posts at the disposal date; a disposal is a supply and reaches GSTR-1.",
    "routers/inventory.py:adjust_stock":
        "Posts a dated stock adjustment, which moves the P&L in a period a "
        "return may already have reported.",
    "routers/inventory.py:writedown_stock_to_nrv":
        "Posts a dated writedown, same exposure as adjust_stock.",
    "routers/purchase_payments.py:create_purchase_payment":
        "The payment side of the receipts argument, and it has NOT been taken: "
        "a payment moves Bank and Creditors, but it can also carry TDS, which "
        "does land in a return. Decide it deliberately rather than by default.",
    "routers/purchase_payments.py:_create_foreign_payment":
        "Same question as create_purchase_payment, plus §195 withholding.",
    "services/purchase_payment_service.py:create_payment_core":
        "The service behind create_purchase_payment; same undecided question.",
    "services/purchase_payment_service.py:create_foreign_payment_core":
        "The service behind _create_foreign_payment; same undecided question.",
    "routers/year_end_adjustments.py:post_adjustment":
        "Posts a date inside the very year the engagement is closing, which is "
        "the year most likely to carry a filed return.",
    "routers/gst_workspace.py:save_gstr1":
        "Writes the RETURN row rather than the ledger; whether saving a draft "
        "return for a filed period should be refused is its own question.",
    "routers/gst_workspace.py:save_gstr3b":
        "Same as save_gstr1 — the return row, not a journal.",
    "routers/gst_workspace.py:save_gstr9":
        "Same as save_gstr1, and GSTR-9 is annual, so the period test differs.",
    "routers/tds_workspace.py:create_challan":
        "A challan is a dated payment to the government; it does not reach a "
        "GST return, so the lock's current filing types do not cover it.",
    "routers/tds_workspace.py:create_return":
        "A TDS return is not a GST period; see create_challan.",
    "services/manual_journal_service.py:update":
        "The SQL guard covers the posted-row rewrite; this Python path checks "
        "only the FY, so the two disagree about what closed means. `create` "
        "was the other half and is done (ACC-12): it now asserts the whole "
        "rule when the entry is posted, because a manual journal can credit "
        "GST Output Payable directly and is the free-form path a filed return "
        "has to stop.",
    "services/banking_service.py:post_transaction":
        "Posts at the bank transaction's own date, which can be months back.",
    "services/bank_posting_service.py:post":
        "The Pass path — posts at the statement line's date, and a statement "
        "imported late covers months whose returns are filed.",
    "services/trial_balance_import_service.py:import_trial_balance":
        "A bulk dated import, the one path that can move a whole year at once.",
    "domain/currency/fx_revaluation_service.py:revalue":
        "Posts at a period-end date and reverses the day after; both dates "
        "need the test, not just the FY.",
}

_FY_CHECKS = ("validate_posting_date", "validate_posting_date_cached")


def _attr_calls(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            out.add(n.func.attr)
    return out


def _functions_missing_the_client_lock() -> dict[str, None]:
    found: dict[str, None] = {}
    for root in ("routers", "services", "domain"):
        for path in sorted((API / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:                                   # pragma: no cover
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = _attr_calls(fn)
                if calls & set(_FY_CHECKS) and "assert_open" not in calls:
                    found[f"{root}/{path.relative_to(API / root).as_posix()}:{fn.name}"] = None
    return found


def test_no_new_posting_path_checks_only_the_firms_own_lock():
    missing = _functions_missing_the_client_lock()
    new = sorted(set(missing) - set(NOT_YET))
    assert not new, (
        "these ask the FY lock but not the client's, and are not on the "
        "acknowledged list:\n  " + "\n  ".join(new) +
        "\n\nAdd period_lock_service.assert_open(db, firm_id, client_id, date) "
        "beside the FY check, or add an entry to NOT_YET with the reason.")


def test_the_debt_list_only_shrinks():
    """An entry that no longer applies must be DELETED, not left behind.

    A stale entry is worse than none: it silently re-permits the defect if the
    call is ever removed and re-added, and it makes the list read longer than
    the work actually left.
    """
    missing = _functions_missing_the_client_lock()
    stale = sorted(set(NOT_YET) - set(missing))
    assert not stale, (
        "these are on the debt list but no longer miss the lock — delete "
        "their entries:\n  " + "\n  ".join(stale))


def test_every_debt_entry_gives_a_reason():
    for key, why in NOT_YET.items():
        assert why and len(why) > 20, f"{key} has no real reason: {why!r}"


def test_the_six_gst_document_routers_are_clean():
    """The claim this phase actually makes, asserted directly rather than by
    the absence of a list entry.

    Every path that creates, edits, issues or receives a document that lands in
    a GST return asks both questions. Sales invoices, sales credit notes and
    sales debit notes reached this in SALES-15; purchase bills, purchase credit
    notes and purchase debit notes reach it here (PUR-08), which is the whole
    purchase half of the ledger.
    """
    document_routers = (
        "sales_invoices.py", "credit_notes.py", "sales_debit_notes.py",
        "purchase_bills.py", "purchase_credit_notes.py", "debit_notes.py",
    )
    offenders = []
    for name in document_routers:
        path = API / "routers" / name
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = _attr_calls(fn)
            if not (calls & set(_FY_CHECKS)) or "assert_open" in calls:
                continue
            key = f"routers/{name}:{fn.name}"
            if key not in NOT_YET:
                offenders.append(key)
    assert not offenders, (
        "a GST document path checks only the firm's own lock:\n  "
        + "\n  ".join(offenders))


def test_the_posting_kernels_draft_approval_asserts_it():
    """post_draft is the one path where a document that was NEVER checked can
    still reach the books: a draft journal is off-books until somebody approves
    it, and approval posts with the DRAFT's date, not today's."""
    src = (API / "services" / "journal_posting_service.py").read_text()
    tree = ast.parse(src)
    post_draft = next(fn for fn in ast.walk(tree)
                      if isinstance(fn, ast.FunctionDef) and fn.name == "post_draft")
    calls = _attr_calls(post_draft)
    assert "validate_posting_date" in calls, "the FY lock must stay"
    assert "assert_open" in calls, "and the client's lock must be asked too"


def test_post_draft_selects_the_columns_its_own_guards_read():
    """A guard that reads a column the SELECT never asked for is not a guard.

    post_draft tested `je.get("deleted_at")` to refuse a soft-deleted draft and
    logged the timeline against `je.get("client_id")`, while _SELECT asked for
    neither — so both were always None: a deleted draft could be posted, and
    every timeline row was written with no client. The mock suite could not see
    it because FakeDB skips its column projection when the select carries an
    embed, and this one carries journal_lines(...).
    """
    from services.journal_posting_service import journal_posting_service as svc
    for column in ("client_id", "deleted_at"):
        assert column in svc._SELECT, (
            f"post_draft reads {column} but does not select it")
