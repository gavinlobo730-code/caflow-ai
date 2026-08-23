"""
Banking & Reconciliation router.

Phase B.0: a THIN HTTP layer over the banking domain service. All mutations
(import, account mapping, posting, ignore) are delegated to
services.banking_service — the single source of banking business logic. The
frontend calls these endpoints instead of writing to Supabase directly.

Columns use the canonical model (transaction_date, match_status).

IMPORTANT: posting is explicit and human-initiated — never auto-post.
CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from typing import Optional

from models.common import api_response
from core.authz import assert_client_access, filter_by_client

_logger = logging.getLogger("caflow.banking")


def _sync_opening_balances(db, firm_id: str, client_id: str, actor_id) -> bool:
    """Idempotently regenerate the client's opening-balance journal after a bank
    opening balance changes. Returns True on success, False on failure (caller
    rolls back). The reporting engine is unchanged — only the trigger moved here.

    actor_id MUST be the internal public.users.id (journal_entries.created_by FKs
    to users.id), never the Supabase auth id.

    SCOPED to the bank leg. Unscoped, saving a bank account recomputed AR and AP
    too, and on a live client that silently reversed 40.54 lakh of opening Trade
    Payables out of the GL because the vendor masters carried zero. A bank screen
    has no business reconciling payables."""
    try:
        from services.opening_balance_service import post_opening_balances, BANK
        post_opening_balances(firm_id, client_id, created_by=actor_id,
                              scope=frozenset({BANK}))
        return True
    except Exception as e:
        _logger.error("bank opening-balance sync failed: %s", e)
        return False
from models.banking import (
    BankAccountIn, BankAccountUpdateIn, StatementImportIn,
    TransactionAccountIn, PostBankTxnIn, MatchingRuleIn, MatchingRuleUpdateIn,
    CategorizeIn, MatchIn, BankMatchMultiIn, BankSplitsIn, BankPayeeIn,
    BankTransferPairIn, BankBatchIn, BankAttachmentIn, BankAttachmentRemoveIn,
    ReconciliationCreateIn, ReconciliationUpdateIn, ReconcileItemsIn,
    ReconciliationReopenIn,
)
from core.permissions import rbac
from services.banking_service import banking_service
from services.bank_matching_service import bank_matching_service
from services.bank_posting_service import bank_posting_service
from services.bank_reconciliation_service import bank_reconciliation_service
from services.bank_register_service import bank_register_service
from services.bank_split_service import bank_split_service
from services.bank_payee_service import bank_payee_service
from services.bank_transfer_service import bank_transfer_service
from services.bank_batch_service import bank_batch_service
from services.bank_candidate_search_service import bank_candidate_search_service
from domain.banking import parse_statement, file_hash, StatementParseError

# Defensive upload cap (bank statements are small; protects the parser/DB).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/api/banking", tags=["banking"])


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _scope_rows(current_user: dict, client_id: Optional[str], rows: list) -> list:
    """M2 assignment scoping for the "all clients" list endpoints below: when a
    specific client is requested the caller must actually be allowed to see it
    (assert_client_access); when no client is specified (firm-wide view), narrow
    the result set to the caller's assigned clients instead of returning every
    client in the firm's banking data to an Executive/Reviewer who isn't
    assigned to all of them."""
    if client_id:
        assert_client_access(current_user, client_id)
        return rows
    return filter_by_client(current_user, rows)


def _assert_row_scope(db, current_user: dict, table: str, row_id: str, label: str) -> str:
    """M2 assignment scoping for the endpoints below that are addressed by ROW ID.

    `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
    Manager, Executive or Reviewer sees only the clients in
    `user_client_assignments`. Endpoints that take a `client_id` parameter
    enforce that with `assert_client_access` / `_scope_rows`. Endpoints addressed
    by a row id have no `client_id` in the request, so they used to check
    `firm_id` and stop — which let a transaction or reconciliation id belonging
    to another manager's client straight through, on reads AND on writes
    (`/post` writes a journal into that client's books).

    The row id is the only thing standing between the two, and ids leak: they
    appear in URLs, in exports, in support threads. Firm scoping is not the same
    control as assignment scoping and cannot substitute for it.

    404 for both "no such row" and "not your client" — existence is not
    disclosed, matching `assert_client_access`'s own choice.

    Returns the row's client_id so a caller that needs it does not re-read.
    """
    rows = (db.table(table).select("client_id")
            .eq("id", row_id).eq("firm_id", current_user["firm_id"])
            .limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    assert_client_access(current_user, rows[0].get("client_id"))
    return rows[0].get("client_id")


def _assert_txn_scope(db, current_user: dict, txn_id: str) -> str:
    return _assert_row_scope(db, current_user, "bank_transactions", txn_id, "Bank transaction")


def _assert_recon_scope(db, current_user: dict, recon_id: str) -> str:
    return _assert_row_scope(db, current_user, "bank_reconciliations", recon_id, "Reconciliation")


def _assert_txn_batch_scope(db, current_user: dict, txn_ids: list) -> None:
    """Same rule for the batch endpoints, which name their rows in the BODY.

    These were missed by the first sweep because it looked for `{…_id}` in the
    path, and a list of ids in a JSON body matches nothing in a path. Found by
    tests/test_router_client_scope.py, which walks the registered routes rather
    than pattern-matching their URLs.

    Every DISTINCT client in the batch is checked BEFORE any row is touched.
    Per-row checking would let the rows before the first refusal land — and a
    batch endpoint is exactly where one foreign id would be slipped in among
    fifty legitimate ones. One read for the whole batch, not one per row.
    """
    ids = [i for i in (txn_ids or []) if i]
    if not ids:
        return
    rows = (db.table("bank_transactions").select("client_id")
            .in_("id", ids).eq("firm_id", current_user["firm_id"])
            .execute().data) or []
    for client_id in sorted({r.get("client_id") for r in rows if r.get("client_id")}):
        assert_client_access(current_user, client_id)


def _guard_foreign_bank_currency(db, firm_id: str, client_id: Optional[str], currency: str) -> None:
    """Allow a non-INR bank account ONLY when multi-currency is active for this client
    (env + firm entitlement + client enablement) and the currency is in the ISO master.
    Fail-safe: any missing gate ⇒ rejected, so INR stays the only option by default."""
    from domain.currency import resolve_currency_policy, currency_service
    firm = (db.table("firms").select("id, multi_currency_entitled")
            .eq("id", firm_id).limit(1).execute().data or [None])[0]
    client = (db.table("clients").select("id, functional_currency, multi_currency_enabled")
              .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0] if client_id else None
    if not resolve_currency_policy(firm, client).active:
        raise HTTPException(status_code=422,
                            detail="Multi-currency is not enabled for this client — foreign-currency bank accounts are unavailable.")
    if not currency_service.get_currency(db, currency):
        raise HTTPException(status_code=422, detail=f"Unsupported currency: {currency}.")


def _bank_ledger_conflict(db, firm_id: str, client_id: str, coa_account_id: str,
                          exclude_account_id: Optional[str] = None) -> Optional[str]:
    """The bank account already using this ledger, if any.

    Two bank accounts sharing one chart-of-accounts row makes per-bank
    reconciliation meaningless — "does the ledger agree with the statement" has no
    answer when the ledger is the sum of two statements — and collapses them into a
    single balance-sheet line. Caught here rather than left to be discovered at
    Reconcile."""
    if not coa_account_id:
        return None
    q = (db.table("bank_accounts").select("id, bank_name, account_no")
         .eq("firm_id", firm_id).eq("client_id", client_id)
         .eq("coa_account_id", coa_account_id))
    for row in (q.execute().data or []):
        if exclude_account_id and row.get("id") == exclude_account_id:
            continue
        return f"{row.get('bank_name')} (····{str(row.get('account_no') or '')[-4:]})"
    return None


def _next_bank_account_code(db, firm_id: str) -> str:
    """The next free 4-digit code in the bank block (1101 upwards).

    Scanned across the WHOLE firm, not one client: chart_of_accounts is unique on
    (firm_id, account_code), so a code already used by another client — or by the
    shared client_id IS NULL chart — is not available here either."""
    rows = (db.table("chart_of_accounts").select("account_code")
            .eq("firm_id", firm_id).execute().data or [])
    used = set()
    for r in rows:
        code = str(r.get("account_code") or "").strip()
        if code.isdigit():
            used.add(int(code))
    n = 1101
    while n in used:
        n += 1
    return str(n)


def _ensure_bank_ledger(db, firm_id: str, client_id: str, bank_name: str,
                        account_no: str) -> Optional[str]:
    """Create a chart-of-accounts row dedicated to one bank account, and return it.

    Every bank account needs its own ledger. Left to the CA it is a step that gets
    skipped — the Ledger Account field defaults to "not linked", and picking an
    existing bank row silently merges two banks into one balance. So the account is
    created here, named for the bank and the last four digits, the way QuickBooks
    and Xero do it.

    Returns None if creation fails; the caller then saves the bank account
    unlinked rather than refusing the save outright. An unlinked account is
    recoverable by editing it; a lost form is not.

    Retried because chart_of_accounts carries TWO firm-wide unique indexes —
    (firm_id, account_code) and (firm_id, account_name). Both are reachable in
    ordinary use: a firm with two clients banking at the same branch produces the
    same "HDFC Bank — 7890", and so does one client re-adding an account after
    deactivating it. Each attempt re-reads the codes and disambiguates the name."""
    last4 = str(account_no or "")[-4:]
    base = f"{bank_name.strip()} — {last4}" if last4 else bank_name.strip()
    for attempt in range(1, 6):
        name = base if attempt == 1 else f"{base} ({attempt})"
        try:
            row = (db.table("chart_of_accounts").insert({
                "firm_id": firm_id, "client_id": client_id,
                "account_code": _next_bank_account_code(db, firm_id),
                "account_name": name[:120],
                "account_type": "Asset", "account_subtype": "Bank", "is_active": True,
            }).execute().data or [{}])[0]
            if row.get("id"):
                return row["id"]
        except Exception as e:  # noqa: BLE001
            _logger.warning("ledger account %r for bank %s not created (attempt %d): %s",
                            name, bank_name, attempt, e)
    _logger.error("could not create a ledger account for bank %s — saving it unlinked",
                  bank_name)
    return None


# What stops a bank account being deleted outright, in the order a CA would care
# about. bank_statements / bank_reconciliations / payroll_runs each FK to
# bank_accounts with NO ACTION, so Postgres would refuse anyway — but refusing
# with a 500 is not an answer, and the fourth condition has no FK behind it at
# all: journal lines point at the CHART account, not the bank account, so a
# delete would leave posted money in the GL with nothing to attribute it to.
_DELETE_BLOCKERS = (
    ("statements",      "bank statements have been imported for it"),
    ("reconciliations", "it has been reconciled"),
    ("payroll",         "payroll has been paid from it"),
    ("ledger",          "its ledger account carries posted journal entries"),
)


def _delete_blockers(db, firm_id: str, client_id: str,
                     accounts: list[dict]) -> dict[str, list[str]]:
    """{bank_account_id: [reasons it cannot be permanently deleted]}.

    A fixed four queries whatever the number of accounts (CLAUDE.md, "Reporting
    performance") — the answer is one short list per account, so the reads are
    keyed by the account ids rather than scanning what they point at.
    """
    ids = [a["id"] for a in accounts if a.get("id")]
    coa_by_account = {a["id"]: a.get("coa_account_id") for a in accounts if a.get("id")}
    coa_ids = [c for c in coa_by_account.values() if c]
    out: dict[str, list[str]] = {i: [] for i in ids}
    if not ids:
        return out

    def _hit(table: str, col: str, values: list[str]) -> set:
        if not values:
            return set()
        try:
            rows = (db.table(table).select(col).in_(col, values).execute().data or [])
            return {r.get(col) for r in rows}
        except Exception as e:  # noqa: BLE001 — an unreadable table blocks the delete
            _logger.error("delete-check on %s failed: %s", table, e)
            return set(values)

    hits = {
        "statements":      _hit("bank_statements", "bank_account_id", ids),
        "reconciliations": _hit("bank_reconciliations", "bank_account_id", ids),
        "payroll":         _hit("payroll_runs", "paid_from_account_id", ids),
        "ledger":          _hit("journal_lines", "account_id", coa_ids),
    }
    for aid in ids:
        for key, reason in _DELETE_BLOCKERS:
            probe = coa_by_account.get(aid) if key == "ledger" else aid
            if probe and probe in hits[key]:
                out[aid].append(reason)
    return out


def _ledger_is_disposable(db, firm_id: str, coa_account_id: str,
                          bank_account_id: str) -> bool:
    """Whether the bank's ledger account can go with it.

    Only when nothing anywhere points at it and it looks like one this app
    created for a bank — subtype Bank. A chart account a CA built by hand is
    never removed as a side effect of deleting a bank account; it is simply left
    where it is."""
    if not coa_account_id:
        return False
    row = (db.table("chart_of_accounts").select("id, account_subtype")
           .eq("id", coa_account_id).eq("firm_id", firm_id).limit(1).execute().data or [{}])[0]
    if (row.get("account_subtype") or "") != "Bank":
        return False
    for table, col in (("journal_lines", "account_id"),
                       ("bank_transactions", "account_id"),
                       ("bank_transaction_splits", "account_id"),
                       ("bank_matching_rules", "suggested_account_id"),
                       ("ledger_balances", "account_id"),
                       ("chart_of_accounts", "parent_id")):
        try:
            if (db.table(table).select(col).eq(col, coa_account_id)
                  .limit(1).execute().data or []):
                return False
        except Exception as e:  # noqa: BLE001 — cannot prove it is unused ⇒ keep it
            _logger.warning("ledger-disposability check on %s failed: %s", table, e)
            return False
    others = (db.table("bank_accounts").select("id")
              .eq("firm_id", firm_id).eq("coa_account_id", coa_account_id)
              .execute().data or [])
    return all(o.get("id") == bank_account_id for o in others)


def _with_ledger_names(db, firm_id: str, rows: list[dict]) -> list[dict]:
    """Stamp each bank account with the code and name of the ledger it posts to.

    The account list used to say only "Linked", which answers the wrong question.
    Now that every bank has its own ledger, WHICH ledger is what ties the row to
    a line on the balance sheet — and it is what makes a refused delete
    actionable, since "its ledger account carries posted journal entries" is only
    useful if you can see which account that is.

    One extra query for the whole list, keyed by the ids already in hand."""
    coa_ids = list({r["coa_account_id"] for r in rows if r.get("coa_account_id")})
    coa: dict[str, dict] = {}
    if coa_ids:
        try:
            coa = {c["id"]: c for c in (
                db.table("chart_of_accounts").select("id, account_code, account_name")
                  .eq("firm_id", firm_id).in_("id", coa_ids).execute().data or [])}
        except Exception as e:  # noqa: BLE001 — a name is a nicety, the list is not
            _logger.warning("could not resolve bank ledger names: %s", e)
    for r in rows:
        c = coa.get(r.get("coa_account_id")) or {}
        r["ledger_account_code"] = c.get("account_code")
        r["ledger_account_name"] = c.get("account_name")
    return rows


# ─── Bank Accounts ────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_bank_accounts(
    client_id: str = Query(...),
    # A bare default, not Query(False, ...): the routers in this codebase are also
    # called directly from tests, and a Query() instance is truthy — which would
    # silently return deactivated accounts to every caller that omitted the flag.
    include_inactive: bool = False,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """The client's bank accounts, active only unless asked otherwise.

    include_inactive exists because filtering unconditionally made a deactivated
    account UNREACHABLE: the account list renders inactive rows (greyed, with an
    "inactive" chip, Edit still offered) but never received one, and the
    deactivation dialog promised "you can reactivate it later by editing it" —
    which nothing in the UI could do. Worse, a deactivated account keeps its
    opening balance in the GL, exactly as it should, so its money stayed on the
    balance sheet with no visible account to attribute it to."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    q = (db.table("bank_accounts").select("*")
         .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id))
    if not include_inactive:
        q = q.eq("is_active", True)
    rows = q.order("bank_name").execute().data or []
    return api_response(True, _with_ledger_names(db, current_user["firm_id"], rows))


@router.post("/accounts")
def create_bank_account(
    data: BankAccountIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    firm_id = current_user["firm_id"]
    payload = {"firm_id": firm_id, **data.model_dump()}
    # Multi-Currency Phase 5 — resolve the account currency. None ⇒ let the column
    # default to INR (byte-for-byte today's). A non-INR currency is allowed ONLY when
    # multi-currency is active for this client and the code is in the ISO master.
    cur = payload.pop("currency", None)
    if cur and cur != "INR":
        _guard_foreign_bank_currency(db, firm_id, payload.get("client_id"), cur)
        payload["currency"] = cur
    elif cur == "INR":
        payload["currency"] = "INR"
    # One ledger per bank. A ledger already spoken for is refused; an unlinked
    # account gets one created for it rather than defaulting to "not linked",
    # which is how two banks ended up sharing 1101 and showing as one line.
    chosen_coa = payload.get("coa_account_id")
    if chosen_coa:
        taken = _bank_ledger_conflict(db, firm_id, payload["client_id"], chosen_coa)
        if taken:
            raise HTTPException(
                status_code=422,
                detail=f"That ledger account is already linked to {taken}. Each bank "
                       f"account needs its own ledger, or their balances merge into one "
                       f"line and neither can be reconciled.")
    else:
        payload["coa_account_id"] = _ensure_bank_ledger(
            db, firm_id, payload["client_id"], payload["bank_name"], payload["account_no"])

    row = db.table("bank_accounts").insert(payload).execute()
    account = (row.data or [{}])[0]
    # Auto-sync opening balances to the GL (no manual post). Roll back on failure.
    if int(payload.get("opening_balance_paise") or 0) != 0 and payload.get("client_id"):
        if not _sync_opening_balances(db, current_user["firm_id"], payload["client_id"],
                                      current_user.get("id")):
            try:
                if account.get("id"):
                    db.table("bank_accounts").delete().eq("id", account["id"]).eq("firm_id", current_user["firm_id"]).execute()
            except Exception:
                pass
            return api_response(False, None, "Unable to save bank account. Please try again.")
    return api_response(True, account)


@router.patch("/accounts/{account_id}")
def update_bank_account(
    account_id: str,
    data: BankAccountUpdateIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    db = _db()
    update = data.model_dump(exclude_none=True)
    if not db:
        return api_response(True, update)
    firm_id = current_user["firm_id"]
    prior = (db.table("bank_accounts").select("*")
             .eq("id", account_id).eq("firm_id", firm_id).limit(1).execute().data or [{}])[0]
    assert_client_access(current_user, prior.get("client_id"))
    if update.get("coa_account_id"):
        taken = _bank_ledger_conflict(db, firm_id, prior.get("client_id"),
                                      update["coa_account_id"], exclude_account_id=account_id)
        if taken:
            raise HTTPException(
                status_code=422,
                detail=f"That ledger account is already linked to {taken}. Each bank "
                       f"account needs its own ledger, or their balances merge into one "
                       f"line and neither can be reconciled.")
    row = (db.table("bank_accounts").update(update)
           .eq("id", account_id).eq("firm_id", firm_id).execute())
    account = (row.data or [{}])[0]
    # Auto-sync opening balances only when the opening balance actually changed.
    if int(account.get("opening_balance_paise") or 0) != int(prior.get("opening_balance_paise") or 0):
        client_id = account.get("client_id") or prior.get("client_id")
        if client_id and not _sync_opening_balances(db, firm_id, client_id, current_user.get("id")):
            try:
                db.table("bank_accounts").update({k: prior.get(k) for k in update.keys()}).eq("id", account_id).eq("firm_id", firm_id).execute()
            except Exception:
                pass
            return api_response(False, None, "Unable to save bank account. Please try again.")
    return api_response(True, account)


@router.get("/accounts/deletable")
def bank_accounts_deletable(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Which of the client's bank accounts can be permanently deleted, and what
    is stopping the rest.

    Separate from the account list so the pickers that call it stay one query.
    The management table asks for this as well and uses it to decide whether to
    offer Delete at all — an action that would fail is worse than no action."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {})
    firm_id = current_user["firm_id"]
    accounts = (db.table("bank_accounts").select("id, coa_account_id")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
    blockers = _delete_blockers(db, firm_id, client_id, accounts)
    return api_response(True, {aid: {"deletable": not reasons, "blocked_by": reasons}
                               for aid, reasons in blockers.items()})


@router.delete("/accounts/{account_id}")
def delete_bank_account(
    account_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Permanently delete a bank account that has no footprint.

    WHY THIS EXISTS AND WHY IT IS NARROW
        Deactivation is right for an account that was real and is now closed:
        its statements, reconciliations and opening balance are the audit trail,
        and removing the account they belong to would falsify it. It is the wrong
        answer for an account created five minutes ago with a mistyped number,
        which deactivation leaves greyed in the list forever.

        So this deletes only what has no history at all — nothing imported,
        nothing reconciled, no payroll, and not a single posted journal line on
        its ledger. In that state there is no audit trail to protect, because
        nothing ever happened.

    Its ledger account goes with it when nothing anywhere references it and it
    is one this app created for a bank. A chart account built by hand is left
    alone; the response says which happened."""
    db = _db()
    if not db:
        return api_response(True, {"deleted": True, "mock": True})
    firm_id = current_user["firm_id"]
    account = (db.table("bank_accounts").select("*")
               .eq("id", account_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found.")
    assert_client_access(current_user, account.get("client_id"))

    # Re-checked server-side. The client asked /deletable to decide what to show;
    # it is not what decides whether the row goes.
    reasons = _delete_blockers(db, firm_id, account.get("client_id"), [account]).get(account_id, [])
    if reasons:
        raise HTTPException(
            status_code=409,
            detail=("This bank account cannot be deleted because "
                    + "; ".join(reasons)
                    + ". Deactivate it instead — that keeps its history and takes "
                      "it out of the pickers."))

    coa_id = account.get("coa_account_id")
    drop_ledger = _ledger_is_disposable(db, firm_id, coa_id, account_id)
    db.table("bank_accounts").delete().eq("id", account_id).eq("firm_id", firm_id).execute()
    ledger_removed = False
    if drop_ledger:
        try:
            db.table("chart_of_accounts").delete().eq("id", coa_id).eq("firm_id", firm_id).execute()
            ledger_removed = True
        except Exception as e:  # noqa: BLE001 — the bank account is already gone
            _logger.warning("bank ledger %s left in place after deleting account %s: %s",
                            coa_id, account_id, e)
    _logger.info("Deleted bank account %s (%s) for client %s; ledger %s",
                 account_id, account.get("bank_name"), account.get("client_id"),
                 "removed" if ledger_removed else "kept")
    return api_response(True, {"deleted": True, "ledger_account_removed": ledger_removed})


@router.get("/accounts/{account_id}/balance")
def bank_account_balance(
    account_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Current balance of one bank account (Multi-Currency Phase 5). Always returns the
    authoritative base (INR) balance; for a foreign-currency account it also returns the
    foreign balance, both DERIVED from posted journal lines (no stored balance)."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"account_id": account_id, "currency": "INR",
                                   "base_balance_paise": 0, "foreign_balance_minor": None})
    firm_id = current_user["firm_id"]
    acct = (db.table("bank_accounts").select("id, currency, coa_account_id, bank_name, account_no")
            .eq("id", account_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data or [None])[0]
    if not acct:
        raise HTTPException(status_code=404, detail="Bank account not found for this client.")
    cur = (acct.get("currency") or "INR").upper()
    base = foreign = 0
    if acct.get("coa_account_id"):
        from services.fx_reporting_service import _account_foreign_and_base
        foreign, base = _account_foreign_and_base(db, firm_id, client_id, acct["coa_account_id"], cur)
    return api_response(True, {
        "account_id": account_id, "bank_name": acct.get("bank_name"), "account_no": acct.get("account_no"),
        "currency": cur, "base_currency": "INR", "base_balance_paise": base,
        "foreign_balance_minor": (foreign if cur != "INR" else None),
    })


# ─── Statements ───────────────────────────────────────────────────────────────

@router.post("/statements/import")
def import_statement(
    data: StatementImportIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Store an already-parsed statement and its lines. (File parsing is Phase B.1.)"""
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"statement_id": "mock-id", "imported": len(data.rows)})
    result = banking_service.import_statement(
        db, current_user["firm_id"], data.client_id, data.bank_name,
        data.account_number, [r.model_dump() for r in data.rows],
        bank_account_id=data.bank_account_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, result)


@router.post("/statements/upload")
async def upload_statement(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    bank_name: str = Form("Bank"),
    account_number: Optional[str] = Form(None),
    bank_account_id: Optional[str] = Form(None),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Upload a CSV/XLSX bank statement. Parsing + normalization + dedup happen
    SERVER-SIDE (Banking B.1) — the browser sends the raw file only. Returns the
    counts of imported and duplicate-skipped transactions."""
    assert_client_access(current_user, client_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    try:
        txns = parse_statement(file.filename or "", content)
    except StatementParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db = _db()
    fmt = "xlsx" if (file.filename or "").lower().endswith(".xlsx") else "csv"
    if not db:
        return api_response(True, {"statement_id": "mock-id", "imported": len(txns),
                                   "duplicates_skipped": 0, "total_rows": len(txns)})
    file_meta = {
        "file_name": file.filename, "file_size_bytes": len(content),
        "source_format": fmt, "file_hash": file_hash(content),
    }
    result = banking_service.import_normalized(
        db, current_user["firm_id"], client_id, bank_name, account_number, txns,
        bank_account_id=bank_account_id, actor_id=current_user.get("auth_user_id"),
        file_meta=file_meta,
    )
    return api_response(True, result)


@router.get("/statements")
def list_statements(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    rows = banking_service.list_statements(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


# ─── Transactions ─────────────────────────────────────────────────────────────

@router.get("/transactions")
def list_transactions(
    statement_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    match_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    min_amount_paise: Optional[int] = Query(None),
    max_amount_paise: Optional[int] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """List bank transactions with date / amount / account filters (B.1, Part E)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = banking_service.list_transactions(
        db, current_user["firm_id"], statement_id=statement_id,
        client_id=client_id, match_status=match_status,
        date_from=date_from, date_to=date_to,
        min_amount_paise=min_amount_paise, max_amount_paise=max_amount_paise,
    )
    return api_response(True, _scope_rows(current_user, client_id, rows))


# ─── Bank register (Tier 1.1) ────────────────────────────────────────────────
# Declared before /transactions/{txn_id} — FastAPI matches in declaration order,
# and a parameterised route above this would swallow the static path.

@router.get("/register")
def bank_register(
    bank_account_id: str = Query(..., description="The bank account to show the register for"),
    client_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    status: str = Query("all", pattern="^(all|uncleared|pending|reconciled|unposted|needs_review)$"),
    q: Optional[str] = Query(None, description="Search narration, reference or category"),
    sort: str = Query("date", pattern="^(date|amount|description|balance|cleared)$"),
    desc: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """The ledger view of ONE bank account: every line the bank sent, in bank
    order, with the running balance after each and its cleared status.

    Read-only. Posted journals are immutable in this system, so corrections are
    reversals made in the journal — a register that offered an edit box would be
    promising something the ledger refuses.

    The running balance is computed over the whole account before filtering, so
    a filtered view still shows each line's TRUE balance rather than one
    restarted from the filter boundary. `view_opening_balance_paise` is the
    balance immediately before the first row returned, which is what makes a
    filtered register add up on screen.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {
            "account": None, "lines": [], "summary": {}, "divergence": None,
            "view_opening_balance_paise": 0, "filtered_count": 0, "total_count": 0,
            "limit": limit, "offset": offset, "sort": sort, "desc": desc,
        })
    return api_response(True, bank_register_service.register(
        db, current_user["firm_id"], bank_account_id, client_id=client_id,
        date_from=date_from, date_to=date_to, status=status, q=q,
        sort=sort, desc=desc, limit=limit, offset=offset,
    ))


# ─── Matching & Categorization (B.2) ──────────────────────────────────────────

@router.get("/queue")
def matching_queue(
    client_id: Optional[str] = Query(None),
    status: str = Query("for_review",
                        pattern="^(for_review|done|unmatched|categorized|matched|needs_review|ignored|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """One page of the work queue (B.2.4), with rule-based suggested categories
    inline.

    The screen uses three views: for_review (still to do), done (posted),
    ignored (set aside). The finer-grained unmatched/categorized/matched/
    needs_review views remain for callers that ask for them.

    PAGED, and it returns `total` alongside the page. A queue that renders
    every line of every statement is a read proportional to transaction
    volume — the shape CLAUDE.md rules out — and it also gave the CA an
    endless scroll with no sense of how much work was left. The total is the
    half that keeps paging honest: nothing is hidden if the screen can say
    how many there are."""
    db = _db()
    if not db:
        return api_response(True, {"rows": [], "total": 0, "limit": limit, "offset": offset})
    rows = bank_matching_service.queue(db, current_user["firm_id"], client_id, status,
                                       limit=limit, offset=offset)
    total = bank_matching_service.queue_total(db, current_user["firm_id"], client_id, status)
    return api_response(True, {
        "rows": _scope_rows(current_user, client_id, rows),
        "total": total, "limit": limit, "offset": offset,
    })


@router.get("/transactions/{txn_id}/suggestions")
def transaction_suggestions(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Ranked match suggestions with confidence (B.2.1). Suggestions only — no posting."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "suggestions": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_matching_service.suggestions(db, current_user["firm_id"], txn_id))


@router.get("/transactions/{txn_id}/candidate-search")
def transaction_candidate_search(
    txn_id: str,
    q: Optional[str] = Query(None, max_length=120),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    min_amount_paise: Optional[int] = Query(None, ge=0),
    max_amount_paise: Optional[int] = Query(None, ge=0),
    entity_type: Optional[str] = Query(None, max_length=40),
    party_id: Optional[str] = Query(None, max_length=64),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Find other matches (B.1.6) — the candidate list with the amount band lifted.

    /suggestions ranks the best five WITHIN a band; this searches everything the
    direction permits, so a CA who knows the invoice number can reach it. Read
    only — choosing a result still goes through /match.

    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "results": [], "total": 0})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_candidate_search_service.search(
        db, current_user["firm_id"], txn_id,
        q=q, date_from=date_from, date_to=date_to,
        min_amount_paise=min_amount_paise, max_amount_paise=max_amount_paise,
        entity_type=entity_type, party_id=party_id, limit=limit, offset=offset))


@router.post("/transactions/{txn_id}/categorize")
def categorize_transaction(
    txn_id: str,
    data: CategorizeIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Set a controlled category (B.2.2). No free-form categories."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "category": data.category})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_matching_service.categorize(
        db, current_user["firm_id"], txn_id, data.category))


@router.post("/transactions/{txn_id}/match")
def match_transaction(
    txn_id: str,
    data: MatchIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Accept a suggestion / manually link a transaction to an entity (B.2.5).
    Linkage only — does NOT post a journal (that is Phase B.3)."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "matched"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_matching_service.match(
        db, current_user["firm_id"], txn_id, data.matched_entity_type,
        data.matched_entity_id, category=data.category,
        actor_id=current_user.get("auth_user_id")))


@router.post("/transactions/{txn_id}/unmatch")
def unmatch_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Reject a suggestion / clear a manual match (B.2.5)."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "unmatched"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_matching_service.unmatch(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/match-multi")
def match_transaction_multi(
    txn_id: str,
    data: BankMatchMultiIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Multi-invoice bank allocation: match ONE bank transaction to MULTIPLE
    sales invoices (a credit transaction) or purchase bills (a debit
    transaction) in a single settlement. Unlike /match (linkage only, posts
    nothing), this immediately creates the settling receipt/purchase_payment
    and posts its journal — the CA's submission of the allocation split IS the
    explicit confirmation, mirroring how recording a receipt/payment from the
    Sales/Purchases pages is itself a single-step action."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "posted"})
    _assert_txn_scope(db, current_user, txn_id)
    result = bank_posting_service.match_and_settle_multi(
        db, current_user["firm_id"], txn_id, data.entity_type,
        [a.model_dump() for a in data.allocations],
        reference_no=data.reference_no, notes=data.notes, tds_paise=data.tds_paise,
        currency=data.currency, exchange_rate=data.exchange_rate,
        actor=current_user,
    )
    return api_response(True, result)


@router.patch("/transactions/{txn_id}")
def set_transaction_account(
    txn_id: str,
    data: TransactionAccountIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Map a transaction to a GL account (status → matched). Does not post."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "matched", "account_id": data.account_id})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, banking_service.set_account(
        db, current_user["firm_id"], txn_id, data.account_id))


@router.post("/transactions/{txn_id}/ignore")
def ignore_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "ignored"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, banking_service.ignore(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/unignore")
def unignore_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Undo an ignore — the transaction returns to the work queue."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "unmatched"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, banking_service.unignore(db, current_user["firm_id"], txn_id))


# ─── Posting Engine (B.3) ─────────────────────────────────────────────────────

@router.get("/ready-to-post")
def ready_to_post_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Categorized/matched transactions awaiting an explicit post (B.3.1)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.ready_to_post(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/pending")
def pending_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Phase 3.5: draft journal created from the transaction, awaiting approval in
    the journal review queue (not yet posted / settled / reconciled)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.pending(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/posted")
def posted_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Transactions already posted to the ledger (draft approved; journal id + who/when)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.posted(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.post("/transactions/batch-accept")
def batch_accept(
    data: BankBatchIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Apply each selected row's own strongest suggestion — a matching rule
    first, then how the payee was coded before (Tier 1.7).

    Returns an outcome for EVERY row. Rows legitimately fail (already posted,
    already excluded, nothing to accept) and a partial success reported as a
    success is how a transaction quietly stays uncoded until year end. Nothing
    is invented: a row with no rule and no history is skipped, not guessed at.
    """
    db = _db()
    if not db:
        return api_response(True, {"results": [], "applied": 0, "skipped": 0,
                                   "failed": 0, "total": 0})
    _assert_txn_batch_scope(db, current_user, data.transaction_ids)
    return api_response(True, bank_batch_service.accept(
        db, current_user["firm_id"], data.transaction_ids,
        actor_id=current_user.get("auth_user_id")))


@router.post("/transactions/batch-exclude")
def batch_exclude(
    data: BankBatchIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Exclude several transactions at once (Tier 1.7). Per-row outcomes.
    A posted transaction cannot be excluded — hiding a line that is on the books
    is the opposite of what exclusion means."""
    db = _db()
    if not db:
        return api_response(True, {"results": [], "applied": 0, "skipped": 0,
                                   "failed": 0, "total": 0})
    _assert_txn_batch_scope(db, current_user, data.transaction_ids)
    return api_response(True, bank_batch_service.set_excluded(
        db, current_user["firm_id"], data.transaction_ids, True,
        actor_id=current_user.get("auth_user_id")))


@router.post("/transactions/batch-include")
def batch_include(
    data: BankBatchIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Bring several excluded transactions back into the queue (Tier 1.7)."""
    db = _db()
    if not db:
        return api_response(True, {"results": [], "applied": 0, "skipped": 0,
                                   "failed": 0, "total": 0})
    _assert_txn_batch_scope(db, current_user, data.transaction_ids)
    return api_response(True, bank_batch_service.set_excluded(
        db, current_user["firm_id"], data.transaction_ids, False,
        actor_id=current_user.get("auth_user_id")))


@router.get("/transactions/{txn_id}/attachments")
def list_transaction_attachments(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Supporting documents on a bank transaction (Tier 1.8)."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "attachments": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_batch_service.list_attachments(
        db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/attachments")
def add_transaction_attachment(
    txn_id: str,
    data: BankAttachmentIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Attach a receipt, invoice or cheque image to a bank line (Tier 1.8).

    The link must be http or https. A javascript: or data: URL stored here and
    rendered as a link is stored XSS, so the scheme vocabulary is closed rather
    than sanitised.
    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "attachments": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_batch_service.add_attachment(
        db, current_user["firm_id"], txn_id, data.name, data.url,
        actor_id=current_user.get("auth_user_id")))


# POST rather than DELETE: the URL to remove is a body, and DELETE-with-a-body
# is unevenly supported by proxies and clients. A distinct path says the same
# thing without relying on that.
@router.post("/transactions/{txn_id}/attachments/remove")
def remove_transaction_attachment(
    txn_id: str,
    data: BankAttachmentRemoveIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Detach a document. Removing one already gone is not an error — the list
    ends up in the state the caller asked for."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "attachments": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_batch_service.remove_attachment(
        db, current_user["firm_id"], txn_id, data.url,
        actor_id=current_user.get("auth_user_id")))


@router.get("/transfer-suggestions")
def transfer_suggestions(
    client_id: str = Query(...),
    window_days: int = Query(4, ge=0, le=30),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Bank lines that look like the two halves of ONE movement between the
    client's own accounts (Tier 1.5).

    Read-only. Pairing happens only when a human confirms — and once paired,
    exactly one side produces a journal, because build_transfer_lines already
    writes both legs and posting both sides would count the same cash twice.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    pairs = bank_transfer_service.detect_pairs(
        db, current_user["firm_id"], client_id, window_days=window_days)
    return api_response(True, [bank_transfer_service.as_dict(p) for p in pairs])


@router.post("/transactions/{txn_id}/transfer-pair")
def pair_transfer(
    txn_id: str,
    data: BankTransferPairIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Confirm that two bank lines are one transfer (Tier 1.5).

    `txn_id` is the PRIMARY side — the outflow, which will carry the journal.
    The counterpart is recorded as part of the same movement and never produces
    a journal of its own.
    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "is_paired": True})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_transfer_service.pair(
        db, current_user["firm_id"], txn_id, data.counterpart_id,
        actor_id=current_user.get("auth_user_id")))


@router.delete("/transactions/{txn_id}/transfer-pair")
def unpair_transfer(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Undo a transfer pairing. Refused once the transfer has been posted —
    reverse the journal first. Idempotent when nothing is paired."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "is_paired": False})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_transfer_service.unpair(
        db, current_user["firm_id"], txn_id,
        actor_id=current_user.get("auth_user_id")))


@router.put("/transactions/{txn_id}/payee")
def set_transaction_payee(
    txn_id: str,
    data: BankPayeeIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Name who the money went to or came from (Tier 1.3).

    Optionally links a customer or vendor, which makes the Tier 1.4 history
    lookup exact rather than name-based. Sending an empty name clears the payee
    and any link together.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, **data.model_dump()})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_payee_service.set_payee(
        db, current_user["firm_id"], txn_id,
        payee_name=data.payee_name, payee_type=data.payee_type, payee_id=data.payee_id,
        actor_id=current_user.get("auth_user_id"),
    ))


@router.get("/transactions/{txn_id}/splits")
def get_transaction_splits(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """A transaction's split allocation, plus what is still unallocated (Tier 1.2)."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "splits": [], "is_split": False})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_split_service.get(db, current_user["firm_id"], txn_id))


@router.put("/transactions/{txn_id}/splits")
def replace_transaction_splits(
    txn_id: str,
    data: BankSplitsIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Allocate one bank line across several GL accounts (Tier 1.2).

    The splits must sum EXACTLY to what the bank moved — there is no rounding
    plug and no auto-balancing. An empty list clears the split and returns the
    transaction to an ordinary single-account posting.

    Refused once a journal exists: that journal is immutable (migration 251), so
    editing the splits under it would leave the ledger and its explanation
    disagreeing. Reverse the journal first.
    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id,
                                   "splits": [s.model_dump() for s in data.splits]})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_split_service.replace(
        db, current_user["firm_id"], txn_id,
        [s.model_dump() for s in data.splits],
        actor_id=current_user.get("auth_user_id"),
    ))


@router.post("/transactions/{txn_id}/posting-preview")
def posting_preview(
    txn_id: str,
    data: PostBankTxnIn,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Proposed balanced journal + settlement effect — NO writes (review drawer)."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "lines": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_posting_service.preview(
        db, current_user["firm_id"], txn_id, bank_account_id=data.bank_account_id,
        account_id=data.account_id, to_bank_account_id=data.to_bank_account_id,
        gst_rate_bps=data.gst_rate_bps, is_interstate=data.is_interstate))


@router.post("/transactions/{txn_id}/post")
def post_transaction(
    txn_id: str,
    data: PostBankTxnIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """
    Explicitly post a bank transaction to the ledger (B.3.2): category → balanced
    journal (shared engine) → settlement. Idempotent (one journal per transaction).
    Human-initiated only; refuses a locked financial year.

    Supplying gst_rate_bps splits a tax-INCLUSIVE bank charge into its taxable
    value and input GST (CGST Act s.16). The rate and the inter-state flag come
    from this request — a matching rule may prefill them in the drawer, but the
    person clicking Post is the one asserting them.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "posted", "posted_journal_id": "mock-je"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_posting_service.post(
        db, current_user["firm_id"], txn_id,
        bank_account_id=data.bank_account_id, account_id=data.account_id,
        to_bank_account_id=data.to_bank_account_id,
        # journal_entries.created_by FKs to public.users.id, not the Supabase
        # auth id — passing auth_user_id here made every bank post fail with
        # journal_entries_created_by_fkey. The auth id goes to audit_log only.
        actor_id=current_user.get("id"),
        actor_auth_id=current_user.get("auth_user_id"),
        gst_rate_bps=data.gst_rate_bps, is_interstate=data.is_interstate,
    ))


# ─── Reconciliation Engine (B.4) ──────────────────────────────────────────────

@router.post("/reconciliations")
def create_reconciliation(
    data: ReconciliationCreateIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Open a reconciliation session for a bank account + statement period (B.4.1)."""
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-recon", **data.model_dump()})
    return api_response(True, bank_reconciliation_service.create_session(
        db, current_user["firm_id"], data.client_id, data.bank_account_id,
        data.statement_start_date, data.statement_end_date,
        opening_balance_paise=data.opening_balance_paise,
        closing_balance_paise=data.closing_balance_paise,
        actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations")
def list_reconciliations(
    client_id: Optional[str] = Query(None),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_reconciliation_service.list_sessions(db, current_user["firm_id"], client_id, bank_account_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


# NOTE: must be declared BEFORE /reconciliations/{recon_id} — FastAPI matches in
# declaration order, and the parameterised route would otherwise swallow this
# path and try to look up a session called "opening-suggestion".
@router.get("/reconciliations/opening-suggestion")
def reconciliation_opening_suggestion(
    client_id: str = Query(...),
    bank_account_id: str = Query(...),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Where a new reconciliation for this account should start (B.4.1).

    Returns the closing balance the last completed reconciliation tied out to,
    plus whether the books still agree with it — the beginning-balance mismatch
    check. Read-only; opens nothing.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {
            "bank_account_id": bank_account_id, "source": "bank_account_opening",
            "previous_reconciliation": None, "completed_count": 0,
            "suggested_opening_paise": 0, "reconciled_book_balance_paise": 0,
            "mismatch_paise": 0, "matches": True,
        })
    return api_response(True, bank_reconciliation_service.opening_suggestion(
        db, current_user["firm_id"], client_id, bank_account_id))


@router.get("/reconciliations/{recon_id}")
def get_reconciliation(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Session header + live tie-out summary + counts."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.get_session(
        db, current_user["firm_id"], recon_id))


@router.patch("/reconciliations/{recon_id}")
def update_reconciliation(
    recon_id: str,
    data: ReconciliationUpdateIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Adjust opening/closing balance or adjustments (rejected once completed)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, **data.model_dump(exclude_none=True)})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.update_session(
        db, current_user["firm_id"], recon_id, data.model_dump(exclude_none=True),
        actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations/{recon_id}/items")
def reconciliation_items(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Reconciled / unreconciled / exception transactions + summary (B.4.2/B.4.4)."""
    db = _db()
    if not db:
        return api_response(True, {"reconciled": [], "unreconciled": [], "exceptions": []})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.report(
        db, current_user["firm_id"], recon_id))


@router.post("/reconciliations/{recon_id}/reconcile")
def reconcile_items(
    recon_id: str,
    data: ReconcileItemsIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Manually reconcile posted transactions — explicit human confirmation (B.4.2).
    No automatic reconciliation."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "reconciled": data.transaction_ids})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.reconcile(
        db, current_user["firm_id"], recon_id, data.transaction_ids,
        actor_id=current_user.get("auth_user_id")))


@router.post("/reconciliations/{recon_id}/unreconcile")
def unreconcile_items(
    recon_id: str,
    data: ReconcileItemsIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Manually unreconcile transactions (B.4.2)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "unreconciled": data.transaction_ids})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.unreconcile(
        db, current_user["firm_id"], recon_id, data.transaction_ids,
        actor_id=current_user.get("auth_user_id")))


@router.post("/reconciliations/{recon_id}/complete")
def complete_reconciliation(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Finalize the reconciliation. Allowed only when the balance ties out; the
    session becomes immutable afterwards (B.4.1/B.4.3)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "status": "completed"})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.complete(
        db, current_user["firm_id"], recon_id, actor_id=current_user.get("auth_user_id")))


@router.post("/reconciliations/{recon_id}/preview")
def preview_reconciliation(
    recon_id: str,
    data: ReconcileItemsIn,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """The tie-out as if these transactions were also reconciled (B.4 / 2.4).

    READ-ONLY — nothing is reconciled. Computed by the same tie-out the real
    reconcile uses, so the preview can never disagree with the result.
    """
    db = _db()
    if not db:
        return api_response(True, {"reconciliation_id": recon_id, "selected_count": 0})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.preview(
        db, current_user["firm_id"], recon_id, data.transaction_ids))


@router.get("/reconciliations/{recon_id}/history")
def reconciliation_history(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Every certification this session has carried, newest first (B.4 / 2.7).

    A session completed, reopened and completed again froze a snapshot each
    time; only the current one lives on `snapshot`, the rest in reopen_history.
    """
    db = _db()
    if not db:
        return api_response(True, {"reconciliation_id": recon_id,
                                   "current": None, "superseded": [], "reopen_count": 0})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.history(
        db, current_user["firm_id"], recon_id))


@router.get("/reconciliations/{recon_id}/report.pdf")
def reconciliation_report_pdf(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """The reconciliation statement as a PDF (B.4 / 2.6).

    For a COMPLETED session this serves the FROZEN snapshot — the figures the CA
    certified. A PDF that recomputed live would be a different document from the
    one that was signed off.
    """
    db = _db()
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable.")
    _assert_recon_scope(db, current_user, recon_id)
    from services.bank_reconciliation_pdf_service import get_reconciliation_pdf
    pdf_bytes, filename = get_reconciliation_pdf(db, current_user["firm_id"], recon_id)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/reconciliations/{recon_id}/reopen")
def reopen_reconciliation(
    recon_id: str,
    data: ReconciliationReopenIn,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Undo a completion so a certified period can be corrected.

    PARTNER ONLY — rbac("accounting", "approve") is the same gate as posting a
    journal and setting a year lock, which is the right company for undoing a
    signed-off reconciliation. A substantive reason is required, the action is
    audit-logged and put on the client timeline, and the frozen snapshot is
    preserved in reopen_history rather than overwritten.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "status": "in_progress"})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.reopen(
        db, current_user["firm_id"], recon_id, data.reason,
        actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations/{recon_id}/report")
def reconciliation_report(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Full backend-driven reconciliation report (B.4.4)."""
    db = _db()
    if not db:
        return api_response(True, {"reconciliation": {"id": recon_id}})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.report(
        db, current_user["firm_id"], recon_id))


@router.get("/reconciliations/{recon_id}/report.csv")
def reconciliation_report_csv(
    recon_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """CSV export of the reconciliation report (B.4.4). Returns a file download."""
    db = _db()
    csv_text = ""
    if db:
        _assert_recon_scope(db, current_user, recon_id)
        csv_text = bank_reconciliation_service.report_csv(
            db, current_user["firm_id"], recon_id)
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="reconciliation-{recon_id}.csv"'})


# ─── Matching rules (Phase B.2.3) ─────────────────────────────────────────────
#
# A rule annotates the work queue with a suggested category / counter account /
# narration. It NEVER posts and never writes to a transaction on its own — the
# CA accepts the suggestion. Precedence is creation order (bank_matching_service
# orders by created_at), so the first rule that fires wins.


def _rule_or_404(db, firm_id: str, rule_id: str) -> dict:
    """Fetch a rule scoped to the caller's firm. 404 rather than 403 for a rule
    belonging to another firm — the caller learns nothing about its existence."""
    res = (db.table("bank_matching_rules").select("*")
           .eq("id", rule_id).eq("firm_id", firm_id).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Matching rule not found.")
    return rows[0]


@router.get("/rules")
def list_rules(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Every rule for the client — INACTIVE ONES INCLUDED. The rules screen has
    to show a deactivated rule to let anyone reactivate it; the queue applies its
    own is_active filter (bank_matching_service.queue), so nothing is applied
    that shouldn't be. Ordered by created_at, which is also the precedence."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("bank_matching_rules").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
           .order("created_at").execute())
    return api_response(True, res.data or [])


@router.post("/rules")
def create_rule(
    data: MatchingRuleIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_matching_rules").insert(
        {"firm_id": current_user["firm_id"], **data.model_dump()}
    ).execute()
    return api_response(True, (row.data or [{}])[0])


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    data: MatchingRuleUpdateIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Edit a rule, or toggle it with {"is_active": false}. Only the supplied
    fields change. client_id is NOT editable — moving a rule between clients
    would silently re-target every suggestion it has ever made."""
    db = _db()
    if not db:
        return api_response(True, {"id": rule_id, **data.model_dump(exclude_none=True)})
    rule = _rule_or_404(db, current_user["firm_id"], rule_id)
    assert_client_access(current_user, rule["client_id"])
    fields = data.model_dump(exclude_none=True)
    # exclude_none means a null normally reads as "field omitted", so no field on
    # this endpoint can be cleared. For the GST rate that is not survivable: a
    # rule stamped 18% by mistake would keep proposing an input credit forever,
    # and 0 is NOT the escape hatch (0 positively means "this charge carries no
    # GST"). An EXPLICIT null clears it; an omitted one still means "leave it".
    if "suggested_gst_rate_bps" in data.model_fields_set and data.suggested_gst_rate_bps is None:
        fields["suggested_gst_rate_bps"] = None
    if not fields:
        return api_response(True, rule)
    # The GST-rate/account pairing can only be judged against the MERGED rule —
    # the model sees the patch alone, and "rate supplied, account already stored"
    # is perfectly valid. Same rule as MatchingRuleIn and migration 254's CHECK:
    # a rate with no account to code the ex-tax amount to cannot be posted.
    merged = {**rule, **fields}
    if merged.get("suggested_gst_rate_bps") is not None and not merged.get("suggested_account_id"):
        raise HTTPException(
            status_code=422,
            detail=("A GST rate needs an expense account to code the charge to — "
                    "the split books the ex-tax amount there."))
    if (merged.get("suggested_gst_rate_bps") is not None
            and (merged.get("txn_type") or "any") == "credit"):
        raise HTTPException(
            status_code=422,
            detail=("A GST rate applies to bank charges — money leaving the account. "
                    "Set the rule to debit (or any), not credit."))
    row = (db.table("bank_matching_rules").update(fields)
           .eq("id", rule_id).eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, (row.data or [{}])[0])


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Remove a rule outright. A rule is configuration, not a financial record —
    it has never written anything to the ledger, so there is nothing to preserve.
    To keep one for later, deactivate it instead (PATCH is_active=false)."""
    db = _db()
    if not db:
        return api_response(True, {"id": rule_id, "deleted": True})
    rule = _rule_or_404(db, current_user["firm_id"], rule_id)
    assert_client_access(current_user, rule["client_id"])
    (db.table("bank_matching_rules").delete()
     .eq("id", rule_id).eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, {"id": rule_id, "deleted": True})
