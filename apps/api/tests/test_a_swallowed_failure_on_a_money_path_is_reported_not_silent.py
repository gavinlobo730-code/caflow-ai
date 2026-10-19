"""A broad handler on a money or ledger path REPORTS what it swallows (POST-A-021, the first slice).

WHAT WAS WRONG
    1,056 `except Exception` handlers sit in routers, services, domain and core, and 162 of them did nothing at all (`pass` or
    `continue`). Most are right to be fail-soft: an audit-log or timeline write must not undo a posting that already happened.
    But silent is a different thing from soft. Two kinds on the paths that move money were the dangerous ones:

      * THE BEST-EFFORT WRITES beside a posting (the audit entry, the timeline line, the delivery log, the reminder counter): a
        broken column or a revoked privilege made every one of them fail on every call for every firm, and nothing said so (the
        health engine's four phantom columns lived like that for months);
      * THE COMPENSATIONS: a credit, debit, sales-debit or purchase-credit note that failed after its allocation row was written
        undoes the allocation and the document's totals in a `try`, and if the UNDO failed too the caller was told "could not
        save" while the allocation stayed, as were the half-created vendor, customer and bank account that a failed opening-balance
        sync deletes. A failed rollback is a ledger that disagrees with what the user was told.

WHAT IS HELD
    * in the files listed below no broad handler is only `pass` / `continue`: each reports through `capture_soft_failure` (a
      failure that loses truth) or `capture_posting_failure` (a failure that loses money: every rollback) with a literal,
      `operation`, unique across these files so two different losses never share one Sentry issue;
    * the reporting helpers never raise, so a fail-soft path stays fail-soft (held by `test_soft_failure_visibility`);
    * driven for real: a forced exception in an audit, timeline or settings read still lets the operation finish, and is reported
      with its operation name and the firm;
    * the repo-wide budget of silent swallows (`test_soft_failure_visibility`) fell with this change, and the files below can
      never go back to silence without the rule here failing.

WHAT IS NOT DONE
    The other ~110 silent handlers (engagement letters, lifecycle, search, tasks, the AI copilot ...) are not money paths and are
    the next slices of the ledger line; a lint rule for broad handlers (BLE001 / S110) would add about a thousand baselined
    findings at once and is left until those are triaged.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

#: The money and ledger paths covered by this slice. Adding a file here is a statement that it has no silent broad handler.
MONEY_PATH_FILES = (
    "services/bank_posting_service.py", "services/collections_service.py", "services/bank_reconciliation_service.py",
    "services/bank_matching_service.py", "services/journal_posting_service.py", "services/recurring_invoice_service.py",
    "services/bank_batch_service.py", "services/banking_service.py", "services/bank_transfer_service.py",
    "services/bank_split_service.py", "services/bank_payee_service.py", "services/late_interest_service.py",
    "services/payment_service.py", "services/internal_client_service.py", "repositories/invoice_repository.py",
    "routers/customer_statements.py", "routers/credit_notes.py", "routers/debit_notes.py", "routers/sales_debit_notes.py",
    "routers/purchase_credit_notes.py", "routers/banking.py", "routers/vendors.py", "routers/customers.py",
)
REPORTERS = {"capture_soft_failure", "capture_posting_failure"}


def silent_broad_handlers(source: str) -> list[int]:
    """Line numbers of `except Exception` / bare handlers whose whole body is `pass` or `continue`."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        name = ast.unparse(node.type) if node.type is not None else "bare"
        if name in ("Exception", "BaseException", "bare") and all(isinstance(b, (ast.Pass, ast.Continue)) for b in node.body):
            out.append(node.lineno)
    return out


def reporter_calls(source: str) -> list[ast.Call]:
    return [n for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in REPORTERS]


def _read(relative: str) -> str:
    return (API_ROOT / relative).read_text(encoding="utf-8")


# ── the rule over the tree ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("relative", MONEY_PATH_FILES)
def test_no_broad_handler_on_a_money_path_is_silent(relative):
    silent = silent_broad_handlers(_read(relative))
    assert not silent, (
        f"{relative} swallows an exception without a word at lines {silent}. Report it with capture_soft_failure(exc, "
        "operation=...) (a lost audit, timeline or settings read) or capture_posting_failure (a failed rollback).")


def test_every_report_names_its_operation_literally_and_no_two_share_one():
    seen: dict[str, str] = {}
    total = 0
    for relative in MONEY_PATH_FILES:
        for call in reporter_calls(_read(relative)):
            total += 1
            ops = [k.value for k in call.keywords if k.arg == "operation" and isinstance(k.value, ast.Constant)]
            assert ops and isinstance(ops[0].value, str), f"{relative}:{call.lineno} has no literal operation"
            operation = ops[0].value
            assert operation not in seen, f"{operation!r} is used at {seen[operation]} and {relative}:{call.lineno}"
            seen[operation] = f"{relative}:{call.lineno}"
    assert total >= 45, f"only {total} reports on the money paths: the wiring has regressed"


def test_a_rollback_that_fails_is_a_posting_failure_not_a_soft_one():
    """A compensation that did not run leaves the ledger disagreeing with what the user was told, which is money."""
    for relative, operations in {
        "routers/credit_notes.py": {"credit_note.allocation_rollback"},
        "routers/debit_notes.py": {"debit_note.allocation_rollback"},
        "routers/sales_debit_notes.py": {"sales_debit_note.allocation_rollback"},
        "routers/purchase_credit_notes.py": {"purchase_credit_note.allocation_rollback"},
        "routers/banking.py": {"bank_account.create_rollback", "bank_account.update_rollback"},
        "routers/vendors.py": {"vendor.create_rollback", "vendor.bulk_create_rollback", "vendor.update_rollback"},
        "routers/customers.py": {"customer.create_rollback", "customer.bulk_create_rollback", "customer.update_rollback"},
    }.items():
        found = {}
        for call in reporter_calls(_read(relative)):
            op = next(k.value.value for k in call.keywords if k.arg == "operation")
            found[op] = call.func.id
        for op in operations:
            assert found.get(op) == "capture_posting_failure", (relative, op, found)


# ── negative controls: the rule is shown to fail on the shape it exists for ─────────────────────────

def test_the_scan_sees_a_silent_handler_and_ignores_a_reporting_or_narrow_one():
    assert silent_broad_handlers("try:\n    f()\nexcept Exception:\n    pass\n") == [3]
    assert silent_broad_handlers("for x in y:\n    try:\n        f()\n    except Exception:  # c\n        continue\n") == [4]
    assert silent_broad_handlers("try:\n    f()\nexcept:\n    pass\n") == [3]
    assert silent_broad_handlers("try:\n    f()\nexcept Exception as e:\n    capture_soft_failure(e, operation='a.b')\n") == []
    assert silent_broad_handlers("try:\n    f()\nexcept KeyError:\n    pass\n") == []


# ── driven for real: the operation survives the failure and the failure is reported ────────────────

@pytest.fixture
def spy(monkeypatch):
    """Replace both reporters in a module and record what reaches them."""
    seen: list[tuple[str, str, dict]] = []

    def install(module):
        monkeypatch.setattr(module, "capture_soft_failure",
                            lambda exc, *, operation, **ctx: seen.append(("soft", operation, ctx)), raising=True)
        return seen
    return install


def _boom(*_a, **_k):
    raise RuntimeError("the audit table is unreachable")


def test_a_failed_batch_audit_entry_is_reported_and_does_not_raise(monkeypatch, spy):
    import services.audit_service as audit
    import services.bank_batch_service as mod
    seen = spy(mod)
    monkeypatch.setattr(audit, "log_event", _boom)
    mod.BankBatchService._log_batch("firm-1", "approve", [{"transaction_id": "t1", "status": "applied"}], "u1")
    assert seen == [("soft", "bank_batch.audit_log", {"firm_id": "firm-1"})]


def test_a_failed_transfer_audit_entry_is_reported_with_the_transaction(monkeypatch, spy):
    import services.audit_service as audit
    import services.bank_transfer_service as mod
    seen = spy(mod)
    monkeypatch.setattr(audit, "log_event", _boom)
    mod.BankTransferService._log("firm-1", "txn-9", "u1", {"x": 1})
    assert seen == [("soft", "bank_transfer.audit_log", {"firm_id": "firm-1", "txn_id": "txn-9"})]


def test_a_failed_journal_audit_entry_is_reported(monkeypatch, spy):
    import services.audit_service as audit
    import services.journal_posting_service as mod
    seen = spy(mod)
    monkeypatch.setattr(audit, "log_event", _boom)
    mod.JournalPostingService()._audit("firm-1", "je-1", "approve", "u1", {})
    assert seen == [("soft", "journal_posting.audit_log", {"firm_id": "firm-1", "journal_id": "je-1"})]


def test_a_failed_reconciliation_timeline_line_is_reported(monkeypatch, spy):
    import services.bank_reconciliation_service as mod
    seen = spy(mod)
    monkeypatch.setattr(mod.timeline_service, "log", _boom)
    mod.BankReconciliationService()._log({"id": "r1", "client_id": "c1", "firm_id": "firm-1"}, "u1", "Title", "Desc")
    assert seen == [("soft", "bank_reconciliation.timeline", {"firm_id": "firm-1", "recon_id": "r1"})]


def test_a_failed_statement_audit_entry_is_reported(monkeypatch, spy):
    import routers.customer_statements as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "log_event", _boom)
    mod._audit({"firm_id": "firm-1", "auth_user_id": "u1", "email": "e@f.in"}, "cust-1", "download", "c1", "2026-04-01", "2026-04-30")
    assert seen == [("soft", "customer_statement.audit_log", {"firm_id": "firm-1", "customer_id": "cust-1"})]


def test_an_unreadable_reminder_setting_falls_back_to_the_default_and_says_so(monkeypatch, spy):
    import services.collections_service as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "_USE_MOCK", False)

    class Broken:
        def table(self, *_a):
            raise RuntimeError("settings table unreachable")

    assert mod.reminder_settings("firm-1", Broken()) == dict(mod.REMINDER_DEFAULTS)
    assert seen == [("soft", "collections.reminder_settings", {"firm_id": "firm-1"})]


def test_the_report_reaches_the_error_log_without_sentry(monkeypatch, caplog):
    """SENTRY_DSN is optional: the report must also be a log line at ERROR, which is what made the original silence visible."""
    import services.audit_service as audit
    import services.bank_transfer_service as mod
    monkeypatch.setattr(audit, "log_event", _boom)
    with caplog.at_level(logging.ERROR, logger="caflow.observability"):
        mod.BankTransferService._log("firm-1", "txn-9", "u1", {})
    messages = [r.getMessage() for r in caplog.records]
    assert any("bank_transfer.audit_log" in m and "txn-9" in m for m in messages), messages
