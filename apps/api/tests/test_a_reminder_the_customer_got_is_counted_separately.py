"""A path that emails nobody may not spend the customer's reminder number.

`email_service.send_payment_reminder_to_customer` ESCALATES ITS TONE on
`reminder_count`: 1 is a friendly reminder, 2 is "Second reminder", 3 or more is
"Final reminder ... significantly overdue". That makes the counter a statement
about what a real person received, and the nightly collections sweep advanced it
while sending nothing -- so the FIRST email a customer ever got could open as a
final demand.

Measured on production 18-09-2026, before the fix: two `client_sales_invoices`
rows at `reminder_count = 5` against ZERO `invoice_deliveries` rows with
`kind = 'reminder'`, both on the firm whose `internal_client_id` is NULL and
neither of them the practice's own fee invoice.

These assert the RULE rather than a spelling of it: which writer owns which
column, that the flagging path reaches no sender, and that an absent fee ledger
scopes to nothing rather than to every client. A rename must not make any of
them vacuous, so each one that walks the source also asserts it found something.
"""
import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from tests._python_source import blank_python_docstrings

API = Path(__file__).resolve().parents[1]

# The two pairs. `emailed` is written only after a real send; `internal` only by
# the sweep. Nothing may write across the pairs.
EMAILED_COLUMNS = ("reminder_count", "last_reminded_at")
INTERNAL_COLUMNS = ("internal_followup_count", "last_internal_followup_at")


def _source(obj) -> str:
    """The function's CODE: dedented, with its docstring blanked out.

    textwrap.dedent, NOT inspect.cleandoc -- cleandoc applies the docstring
    convention (strip the common indent of every line after the first), which
    shreds real Python indentation and makes ast.parse raise. A test that
    cannot parse its own subject proves nothing.

    And the docstring goes, because three of the substring assertions below
    failed on their first run against the very sentences explaining the fix:
    the new code says what it replaced, and a guard that reads prose is a guard
    that forbids explaining itself. blank_python_docstrings keeps offsets, so a
    failure still reports the right line.
    """
    return blank_python_docstrings(textwrap.dedent(inspect.getsource(obj)))


def _assigned_dict_keys(src: str) -> set[str]:
    """Every string key appearing in a dict literal in `src`.

    The two writers both build their update payload as a dict literal, so this
    reads what a function actually writes rather than what its docstring claims.
    """
    keys: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def test_the_sweep_writes_only_its_own_pair():
    from services import collections_service as coll

    written = _assigned_dict_keys(_source(coll.flag_overdue_for_internal_followup))
    assert set(INTERNAL_COLUMNS) <= written, (
        "the sweep must record its own cadence; without it the gate has no memory")
    for col in EMAILED_COLUMNS:
        assert col not in written, (
            f"{col} says a customer was emailed. This path emails nobody -- and "
            f"send_payment_reminder_to_customer reads the count to decide whether "
            f"the next real reminder is friendly, second or FINAL.")


def test_the_customer_facing_send_writes_only_the_emailed_pair():
    from services import collections_service as coll

    written = _assigned_dict_keys(_source(coll._dispatch_invoice_reminder))
    assert set(EMAILED_COLUMNS) <= written
    for col in INTERNAL_COLUMNS:
        assert col not in written, (
            f"{col} is the sweep's internal note count. A real send is not an "
            f"internal note, and crossing the pairs is what this test exists to stop.")


def test_the_two_cadence_gates_read_their_own_column():
    from services import collections_service as coll

    sweep = _source(coll.flag_overdue_for_internal_followup)
    assert "last_internal_followup_at" in sweep
    assert "last_reminded_at" not in sweep, (
        "reading the emailed column cut both ways: a real send suppressed the "
        "internal note for a week, and an internal note suppressed a real send")

    # The manual send numbers the NEXT email off what was actually emailed.
    manual = _source(coll.send_invoice_reminder)
    assert "reminder_count" in manual
    assert "internal_followup_count" not in manual


def test_the_flagging_path_reaches_no_sender():
    """Asserted on the CODE, not on the docstring that says it sends nothing."""
    from services import collections_service as coll

    tree = ast.parse(_source(coll.flag_overdue_for_internal_followup))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Call):
            f = node.func
            called.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))

    assert "services.email_service" not in imported
    assert not any(m.endswith("email_service") for m in imported), sorted(imported)
    senders = {c for c in called if c.startswith("send_") or c.startswith("_send")}
    assert not senders, f"the sweep must not send: {sorted(senders)}"
    assert "log" in called, "vacuity floor: the sweep still writes its timeline note"


def test_an_absent_fee_ledger_is_not_every_client():
    """`firms.internal_client_id` NULL is an unprovisioned firm, not a wildcard.

    Migration 074's own comment names that state, and it was live on one of the
    two production firms. `if internal_id:` dropped the client filter, so the
    sweep ran over every client's customer invoices.
    """
    from services import collections_service as coll

    src = _source(coll._open_invoices)
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)

    # An early return of an empty list, guarded on the scope being absent.
    returns_empty_when_unscoped = any(
        isinstance(n, ast.If)
        and any(
            isinstance(b, ast.Return)
            and isinstance(b.value, ast.List)
            and not b.value.elts
            for b in n.body
        )
        for n in fn.body
    )
    assert returns_empty_when_unscoped, (
        "an unprovisioned firm has an EMPTY fee ledger; answering with every "
        "client's invoices is what put reminder_count = 5 on two real customers")

    # And the production query no longer applies client_id conditionally.
    assert 'if internal_id:' not in src, (
        "a conditional client predicate is the defect itself: it silently widens")
    assert '.eq("client_id", internal_id)' in src, (
        "vacuity floor: the production fetch must still be client-scoped")


def _route_paths(module_path: Path) -> set[str]:
    """Every string path in an `@router.<verb>("...")` decorator in the module."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(module_path.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                out.add(dec.args[0].value)
    return out


def test_no_route_calls_the_internal_sweep_a_send():
    """Asserted on the DECORATORS, not on the file's text.

    The first draft grepped the whole of routers/billing.py for
    "send-reminders" and failed on this very change -- because the new route's
    own docstring explains what it was renamed FROM. A guard that reads prose
    is a guard that forbids explaining the fix, which is the same shape as the
    location- and spelling-named guards CLAUDE.md keeps having to restate.
    """
    paths = _route_paths(API / "routers" / "billing.py")
    assert "/collections/flag-followups" in paths, (
        f"vacuity floor: the route must exist. Found: {sorted(paths)}")
    assert "/collections/send-reminders" not in paths, (
        "the route said 'send'; it writes a timeline note and a counter")


def test_the_scheduler_calls_the_sweep_by_its_honest_name():
    """The scheduler's own header has always said 'no email'; its call did not."""
    tree = ast.parse((API / "jobs" / "scheduler.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                "collections_service"):
            imported.update(a.name for a in node.names)
    assert "flag_overdue_for_internal_followup" in imported, sorted(imported)
    assert "send_overdue_reminders" not in imported, (
        "the scheduler called a function whose name claimed a send it never made")
