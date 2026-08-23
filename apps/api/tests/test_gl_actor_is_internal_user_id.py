"""
Whoever posts to the general ledger is identified by public.users.id.

`journal_entries.created_by` carries `FOREIGN KEY (created_by) REFERENCES
users(id)` in production. `current_user` holds TWO ids — `auth_user_id` (the
Supabase JWT `sub`, i.e. auth.users.id) and `id` (the internal users row) —
and only the second one satisfies that constraint.

Bank posting passed the first. Every attempt to post a bank transaction died
with

    insert or update on table "journal_entries"
    violates foreign key constraint "journal_entries_created_by_fkey"

which reached the CA as a bare "Internal server error". It was not a
regression from the posting-gate removal: the old draft path set `created_by`
on the unposted journal too, so it failed identically — production has zero
journal_entries rows with source_type='bank_transaction'.

Two things are proved here, because a per-endpoint test only covers the
endpoint someone remembered to write a test for — the same failure mode as
the bug:

  1. The two GL-writing endpoints hand the service the internal id (and the
     auth id separately, for audit_log, where the rest of the app writes it).
  2. `test_no_router_hands_the_auth_id_to_a_gl_writer` walks the AST of every
     router and fails for any call into a journal-writing service that passes
     `auth_user_id` as `actor_id`/`created_by`.
"""
import ast
import pathlib

import pytest

import routers.banking as rb
import routers.accounting as ra


AUTH_ID = "58a43a7a-dfb9-43c1-97c9-45f98da47877"   # auth.users.id (JWT sub)
USER_ID = "a61789ae-9862-45fc-ab90-9b2efa13774d"   # public.users.id
CURRENT_USER = {"id": USER_ID, "auth_user_id": AUTH_ID, "firm_id": "firm-1",
                "role": "Partner", "email": "ca@example.com"}


class _Captured(dict):
    """Records the kwargs a patched service method was called with."""


@pytest.fixture
def captured(monkeypatch):
    seen = _Captured()

    def _capture(*_a, **kw):
        seen.update(kw)
        return {"id": "txn-1", "status": "posted"}

    # Both endpoints short-circuit to a mock response when there is no DB, so
    # the fake has to be truthy — the assertion is about what the ROUTER
    # passes on, not about anything the service does with it.
    monkeypatch.setattr(rb, "_db", lambda: object())
    monkeypatch.setattr(rb, "_assert_txn_scope", lambda *a, **k: "client-1")
    monkeypatch.setattr(ra, "_prod_db", lambda: object())
    monkeypatch.setattr(ra, "_assert_draft_scope", lambda *a, **k: None)
    monkeypatch.setattr(rb.bank_posting_service, "post", _capture)
    monkeypatch.setattr(ra.journal_posting_service, "post_draft", _capture)
    return seen


def test_bank_post_identifies_the_actor_by_internal_user_id(captured):
    """The FK-bearing one. actor_id must be users.id, never the JWT sub."""
    rb.post_transaction("txn-1", rb.PostBankTxnIn(), current_user=CURRENT_USER)
    assert captured["actor_id"] == USER_ID, (
        "bank post sent the Supabase auth id as actor_id — "
        "journal_entries_created_by_fkey rejects it")
    assert captured["actor_id"] != AUTH_ID
    # audit_log.actor_id has no FK and every other router writes the auth id
    # there; keeping it on one id space is what makes the filter usable.
    assert captured["actor_auth_id"] == AUTH_ID


def test_draft_approval_identifies_the_actor_by_internal_user_id(captured):
    """journal_entries.posted_by is the same id space as created_by. It has no
    FK, so this one failed silently — writing an id that resolves to no user."""
    ra.post_draft_journal("je-1", current_user=CURRENT_USER)
    assert captured["actor_id"] == USER_ID
    assert captured["actor_id"] != AUTH_ID
    assert captured["actor_auth_id"] == AUTH_ID


# ── Nobody forgot one ─────────────────────────────────────────────────────────

# Services whose actor argument reaches phase2_journal_service._create_journal
# (the single posting kernel) as created_by, or journal_entries.posted_by.
_GL_WRITERS = {
    "bank_posting_service",
    "journal_posting_service",
    "manual_journal_service",
    "phase2_journal_service",
    "opening_balance_service",
    "trial_balance_import_service",
    "purchase_payment_service",
    "receipt_service",
}
_GL_ACTOR_KWARGS = {"actor_id", "created_by", "posted_by"}

_ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "routers"


def _is_auth_user_id(node: ast.AST) -> bool:
    """Matches `<anything>.get("auth_user_id")` and `<anything>["auth_user_id"]`."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        arg = node.args[0]
        return isinstance(arg, ast.Constant) and arg.value == "auth_user_id"
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value == "auth_user_id"
    return False


def _gl_calls_passing_the_auth_id():
    out = []
    for path in sorted(_ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            recv = node.func.value
            if not isinstance(recv, ast.Name) or recv.id not in _GL_WRITERS:
                continue
            for kw in node.keywords:
                if kw.arg in _GL_ACTOR_KWARGS and _is_auth_user_id(kw.value):
                    out.append(f"{path.name}:{node.lineno} "
                               f"{recv.id}.{node.func.attr}({kw.arg}=…auth_user_id)")
    return out


def test_the_ast_sweep_actually_finds_the_gl_calls():
    """A sweep matching nothing would pass the test below vacuously."""
    found = 0
    for path in sorted(_ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id in _GL_WRITERS:
                found += 1
    assert found >= 15, f"expected the GL-writing call sites, found {found}"


def test_no_router_hands_the_auth_id_to_a_gl_writer():
    offenders = _gl_calls_passing_the_auth_id()
    assert not offenders, (
        "these calls identify the GL actor by the Supabase auth id; "
        "journal_entries.created_by FKs to public.users.id:\n  "
        + "\n  ".join(offenders))
