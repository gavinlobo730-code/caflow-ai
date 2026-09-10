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
import json
import logging
from fastapi import (APIRouter, Depends, HTTPException, Path, Query, UploadFile,
                     File, Form)
from fastapi.responses import Response
from typing import Optional

from models.common import api_response
from services import bank_erasure
from services.audit_service import log_event
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
    ReconciliationCreateIn, ReconciliationUpdateIn, ReconciliationAdjustmentIn,
    ReconcileItemsIn,
    ReconciliationReopenIn, EntriesRedraftIn, EntriesPassReadyIn, PassEntryIn,
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
from services.bank_entry_service import bank_entry_service, REDRAFT_CHUNK
from domain.banking import file_hash, StatementParseError
from domain.banking.normalizer import parse_statement_detailed
from domain.banking.tie_out import statement_check, totals_agreement
from domain.banking import vision
from services import statement_vision
from domain.banking.normalizer import (
    balance_agreement, header_fingerprint, inspect_statement, validate_mapping,
)
from services import bank_column_mapping_service as column_mappings

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


def _assert_statement_scope(db, current_user: dict, statement_id: str) -> str:
    return _assert_row_scope(db, current_user, "bank_statements", statement_id, "Statement")


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


#: An overdraft and a cash credit are MONEY OWED TO THE BANK, so their ledger is
#: a liability. bank_accounts.account_type has allowed these since migration 054
#: and the form offers them; the ledger was created Asset/'Bank' regardless.
#:
#: The SUBTYPE is 'Bank Overdraft' and that was checked, not chosen:
#: domain/reporting/schedule_iii.bs_bucket() substring-scans for the literal
#: "overdraft", so 'Bank OD' and 'Cash Credit' both fall to Other Current
#: Liabilities instead of Short Term Borrowings — the caption Schedule III
#: Division I puts "loans repayable on demand from banks" under.
_OVERDRAWN_BANK_TYPES = frozenset({"Cash Credit", "Overdraft"})
_OD_LEDGER = ("Liability", "Bank Overdraft")
_ASSET_LEDGER = ("Asset", "Bank")


def ledger_shape_for_bank(account_type: Optional[str]) -> tuple[str, str]:
    """(account_type, account_subtype) for a bank account's own ledger."""
    return _OD_LEDGER if (account_type or "") in _OVERDRAWN_BANK_TYPES else _ASSET_LEDGER


def _ensure_bank_ledger(db, firm_id: str, client_id: str, bank_name: str,
                        account_no: str, account_type: Optional[str] = None) -> Optional[str]:
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
    _typ, _sub = ledger_shape_for_bank(account_type)
    last4 = str(account_no or "")[-4:]
    base = f"{bank_name.strip()} — {last4}" if last4 else bank_name.strip()
    for attempt in range(1, 6):
        name = base if attempt == 1 else f"{base} ({attempt})"
        try:
            row = (db.table("chart_of_accounts").insert({
                "firm_id": firm_id, "client_id": client_id,
                "account_code": _next_bank_account_code(db, firm_id),
                "account_name": name[:120],
                "account_type": _typ, "account_subtype": _sub, "is_active": True,
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
                     accounts: list[dict]) -> tuple[dict[str, list[str]],
                                                    dict[str, str | None]]:
    """({bank_account_id: [referential reasons]}, {bank_account_id: newest
    statement_to}).

    A fixed four queries whatever the number of accounts (CLAUDE.md, "Reporting
    performance") — the answer is one short list per account, so the reads are
    keyed by the account ids rather than scanning what they point at.

    The statements probe now selects `statement_to` alongside the key, which
    costs no extra round trip and is what dates the retention duty: a statement
    is the voucher for the entries posted off it, and the NEWEST one is held
    longest (services/bank_erasure.py).
    """
    ids = [a["id"] for a in accounts if a.get("id")]
    coa_by_account = {a["id"]: a.get("coa_account_id") for a in accounts if a.get("id")}
    coa_ids = [c for c in coa_by_account.values() if c]
    out: dict[str, list[str]] = {i: [] for i in ids}
    latest: dict[str, str | None] = {i: None for i in ids}
    if not ids:
        return out, latest

    def _rows(table: str, col: str, values: list[str], extra: str = "") -> list[dict]:
        if not values:
            return []
        try:
            select = f"{col}, {extra}" if extra else col
            return (db.table(table).select(select).in_(col, values).execute().data or [])
        except Exception as e:  # noqa: BLE001 — an unreadable table blocks the delete
            _logger.error("delete-check on %s failed: %s", table, e)
            # Unreadable means BLOCKED, not clear. The date stays None, so the
            # refusal falls back to the referential sentence rather than
            # inventing a statutory date from a query that did not answer.
            return [{col: v} for v in values]

    statements = _rows("bank_statements", "bank_account_id", ids, "statement_to")
    for row in statements:
        aid, end = row.get("bank_account_id"), row.get("statement_to")
        if aid in latest and end and (latest[aid] is None or str(end) > str(latest[aid])):
            latest[aid] = str(end)[:10]

    hits = {
        "statements":      {r.get("bank_account_id") for r in statements},
        "reconciliations": {r.get("bank_account_id") for r in
                            _rows("bank_reconciliations", "bank_account_id", ids)},
        "payroll":         {r.get("paid_from_account_id") for r in
                            _rows("payroll_runs", "paid_from_account_id", ids)},
        "ledger":          {r.get("account_id") for r in
                            _rows("journal_lines", "account_id", coa_ids)},
    }
    for aid in ids:
        for key, reason in _DELETE_BLOCKERS:
            probe = coa_by_account.get(aid) if key == "ledger" else aid
            if probe and probe in hits[key]:
                out[aid].append(reason)
    return out, latest


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
            db, firm_id, payload["client_id"], payload["bank_name"],
            payload["account_no"], payload.get("account_type"))

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
    blockers, latest = _delete_blockers(db, firm_id, client_id, accounts)
    # `reason` is the SAME sentence the DELETE would refuse with. The panel used
    # to build its own from blocked_by in the browser, which meant two wordings
    # of one refusal and neither of them naming a statute.
    return api_response(True, {
        aid: {
            "deletable": not reasons,
            "blocked_by": reasons,
            "reason": (bank_erasure.refusal(reasons, latest_statement_end=latest.get(aid))
                       if reasons else None),
        }
        for aid, reasons in blockers.items()
    })


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
    alone; the response says which happened.

    WHEN IT REFUSES, IT NAMES THE LAW
        A bank statement is the voucher for every receipt and payment posted off
        it, and Companies Act s. 128(5) requires the vouchers relevant to any
        entry kept for eight financial years. So the 409 says which statute,
        whose duty it is and the date it lapses, from the newest statement's
        own period — not "bank statements have been imported for it", which
        names nothing and never ends. services/bank_erasure.py writes it."""
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
    blockers, latest = _delete_blockers(db, firm_id, account.get("client_id"), [account])
    reasons = blockers.get(account_id, [])
    if reasons:
        raise HTTPException(
            status_code=409,
            detail=bank_erasure.refusal(
                reasons, latest_statement_end=latest.get(account_id)))

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

# Image formats a photographed statement arrives as. A scan is usually a PDF;
# a phone photo is not, and the parsers have no extension to dispatch on.
_IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".png": "image/png", ".webp": "image/webp"}


def _read_statement_file(filename: str, content: bytes, mapping, *,
                         allow_vision: bool, has_balances: bool):
    """(transactions, source_format, used_vision, printed_totals) for an upload.

    `printed_totals` is the "Grand Total" row the bank printed on the statement,
    when it printed one — the evidence, already inside the file, that every line
    was read. It comes off the SAME pass as the transactions; see
    normalizer.parse_statement_detailed for why it cannot be picked up later.
    A statement read by a vision model has none: what comes back is a model's
    reading, so its own totals would be evidence for itself.

    THE ORDER MATTERS. The deterministic parsers are tried first and always: a
    text PDF must never be sent to a model just because a model is available,
    because a parse from real characters beats a reading of pixels and costs
    nothing. Vision is only for what genuinely cannot be parsed — a scan or a
    photograph — and only when the CA has asked for it.

    WHY A SCAN IS NEVER IMPORTED UNVERIFIED
        A scan read with nothing checking it is a model's word for 300 numbers
        that nobody will read. So SOMETHING has to verify the arithmetic, and
        there are now two candidates: the totals the statement prints on itself,
        and the two balances the CA types.

        The totals are tried FIRST, from the last page alone, by a separate call
        that is shown no transactions and can only transcribe or decline
        (vision.read_printed_totals). If that finds nothing and no balances were
        given, the upload is refused THERE — one page-sized call in, rather than
        twenty — which keeps almost all of the "refuse before you spend" this
        used to get by demanding the balances up front, while no longer
        demanding them from the CA whose statement states its own totals.

        What is NOT relaxed is the outcome: `statement_check` has to come back
        verified or the import is refused. See upload_statement.
    """
    name = (filename or "").lower().strip()
    ext = name[name.rfind("."):] if "." in name else ""
    is_image = ext in _IMAGE_MIME

    if not is_image:
        try:
            parsed = parse_statement_detailed(filename or "", content, mapping)
            fmt = "pdf" if name.endswith(".pdf") else "xlsx" if name.endswith(".xlsx") else "csv"
            return parsed.transactions, fmt, False, parsed.printed_totals
        except StatementParseError as e:
            # Only a PDF with no readable text is a candidate for the model. A
            # malformed CSV is a malformed CSV and a picture will not help.
            if not (name.endswith(".pdf") and "scanned" in str(e).lower()):
                raise
            if not allow_vision:
                raise StatementParseError(
                    "This PDF is a scan — there is no text in it to read. It can "
                    "be read with AI instead: turn that on for this upload. If "
                    "the statement does not print its own totals you will also "
                    "be asked for the opening and closing balances, which is "
                    "how the figures get checked.") from e

    if not allow_vision:
        raise StatementParseError(
            "A photographed statement can be read with AI. Turn that on for "
            "this upload. If the statement does not print its own totals you "
            "will also be asked for the opening and closing balances, which is "
            "how the figures get checked.")
    if not statement_vision.available():
        raise StatementParseError(
            "Reading a scanned statement is not configured on this deployment. "
            "Upload the CSV or Excel export instead.")

    images = [content] if is_image else vision.page_images(content)
    mime = _IMAGE_MIME.get(ext, "image/png")

    # The last page, on its own, before anything else is read: that is where a
    # statement prints its totals, and this call is shown no transactions so it
    # cannot produce a figure by adding them up.
    printed = vision.read_printed_totals(
        images[-1], call_model=statement_vision.call, mime=mime)
    if printed is None and not has_balances:
        # One call in, not twenty. Nothing could check this reading.
        raise StatementParseError(
            "This scan does not print its own totals, so there is nothing to "
            "check the reading against. Give the opening and closing balances "
            "printed on the statement and upload it again — they are what "
            "proves every line was read.")

    txns = vision.read_statement(images, call_model=statement_vision.call, mime=mime)
    return txns, ("image" if is_image else "pdf-scan"), True, printed


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
def upload_statement(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    bank_name: str = Form("Bank"),
    account_number: Optional[str] = Form(None),
    bank_account_id: Optional[str] = Form(None),
    column_mapping: Optional[str] = Form(None),
    save_mapping: bool = Form(False),
    opening_balance_paise: Optional[int] = Form(None),
    closing_balance_paise: Optional[int] = Form(None),
    allow_vision: bool = Form(False),
    acknowledge_totals_mismatch: Optional[str] = Form(None),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Upload a CSV/XLSX/PDF bank statement, or a scan of one. Parsing + normalization + dedup happen
    SERVER-SIDE (Banking B.1) — the browser sends the raw file only. Returns the
    counts of imported and duplicate-skipped transactions.

    THE STATEMENT'S OWN TOTALS, CHECKED WITHOUT BEING ASKED
        Most Indian statements end with their own "Grand Total" of withdrawals
        and deposits. Where one is found the parse is summed against it before
        anything is written, so the strongest check in the import happens on
        every upload of such a file with nothing typed in. `totals_check` in the
        response says whether it ran and what it found.

    THE TIE-OUT, AND WHY IT ALSO BLOCKS
        Give it the opening and closing balances PRINTED ON THE STATEMENT and it
        checks `opening + credits - debits == closing` too. The two are not
        substitutes: the totals row cannot say whether this file is the whole
        period, and the balances cannot be had for free. Either failing refuses
        the import — see domain/banking/tie_out.py. The balances stay optional,
        because most existing callers do not send them and a statement that
        prints its own totals no longer needs them; `verified` says whether
        anything at all confirmed the parse, so an unchecked import and a
        checked one cannot read the same.

    EXCEPT ON A SCAN, WHERE ONE OF THEM IS REQUIRED
        `allow_vision` lets a scanned or photographed statement be read by a
        vision model, and there the arithmetic is not advisory: the import is
        refused unless `verified` comes back true. Either piece of evidence will
        do — a statement that prints its own totals needs nothing typed in, and
        one that does not still needs the balances. The totals are read from the
        last page by a SEPARATE call that is shown no transactions, so they
        cannot be a sum of the reading being checked (domain/banking/vision.py).
        A deterministic parse is always tried first and a text PDF never reaches
        the model.

    AND ONE WAY PAST THE TOTALS, WHICH IS WRITTEN DOWN
        `acknowledge_totals_mismatch` is a reason — at least ten characters —
        for importing although the statement's own totals row disagreed with the
        lines read from it. It exists because that was the one refusal with no
        way past: the evidence comes out of the file, so a CA who knows the
        bank's row is not comparable (it carries a brought-forward line, or the
        export is a filtered view) could do nothing but edit the statement by
        hand, which destroys the evidence and leaves nothing checked at all.

        It is narrow on purpose. It clears ONLY the printed-totals refusal,
        never the tie-out — those balances were typed into this same request, so
        a CA who does not want that check simply does not type them. The import
        does not come back `verified`, the reason is stored on the statement row
        beside the two differences it excused (migration 354), it is written to
        the audit log and to the client's timeline, and it is refused outright
        on a scan, where nothing but the model read the file.
    """
    assert_client_access(current_user, client_id)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    db = _db()

    # A mapping the CA supplied for THIS upload wins; otherwise a mapping saved
    # earlier for this account and this exact header layout; otherwise nothing,
    # and detect_format decides as it always has.
    mapping: Optional[dict] = None
    mapping_source = "detected"
    if column_mapping:
        try:
            mapping = json.loads(column_mapping)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="column_mapping must be a JSON object of column positions.")
        mapping_source = "supplied"
    elif db and bank_account_id:
        try:
            headers = inspect_statement(file.filename or "", content)["headers"]
            saved = column_mappings.find_mapping(
                db, current_user["firm_id"], bank_account_id, header_fingerprint(headers))
        except StatementParseError:
            saved = None            # unreadable file — the parse will say so
        if saved:
            mapping = saved.get("mapping")
            mapping_source = "saved"

    has_balances = (opening_balance_paise is not None
                    and closing_balance_paise is not None)
    try:
        txns, fmt, used_vision, printed = _read_statement_file(
            file.filename or "", content, mapping,
            allow_vision=allow_vision, has_balances=has_balances)
    except StatementParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # BEFORE anything is written. balance_agreement is computed after the import
    # and is advisory; this one decides whether the import happens at all, so it
    # has to run first — reporting "it does not add up" beside rows that are
    # already in the ledger would be a finding nobody can act on.
    ack_reason = (acknowledge_totals_mismatch or "").strip()
    if ack_reason and len(ack_reason) < 10:
        raise HTTPException(
            status_code=422,
            detail="Give a reason of at least 10 characters for importing a "
                   "statement whose own totals do not agree with it.")
    if ack_reason and used_vision:
        # A scan has nothing else that read the file. On the deterministic path
        # the CA can open the CSV and see the rows the parser saw; on this one
        # the only reading IS the thing whose arithmetic failed, so overriding
        # it would be accepting a model's word against the statement's own.
        raise HTTPException(
            status_code=422,
            detail="A scanned statement cannot be imported over a totals "
                   "mismatch — the only reading of the file is the one that "
                   "does not add up. Import it as a CSV or XLSX instead.")
    check = statement_check(txns, opening_paise=opening_balance_paise,
                            closing_paise=closing_balance_paise, printed=printed,
                            totals_mismatch_acknowledged=bool(ack_reason))
    if ack_reason and not check["acknowledged"]:
        # A reason typed against nothing. Storing it would put an explanation on
        # the record for a check that passed — and a box that can be ticked when
        # it does not apply is a box people tick out of habit.
        raise HTTPException(
            status_code=422,
            detail="There is nothing to acknowledge: this statement's own "
                   "totals were not checked, or they agree with the lines read "
                   "from it. Import it without a note.")
    if check["refusal"]:
        # A dict, so a screen can offer the way past without matching on the
        # wording of a sentence written for a human. lib/api errorMessage()
        # already flattens {message: ...} for display.
        raise HTTPException(status_code=422, detail={
            "message": check["refusal"], "code": check["refusal_code"]})
    if used_vision and not check["verified"]:
        # Belt and braces, and deliberately kept. Between them the two refusals
        # above should already cover this path — _read_statement_file refuses a
        # scan that nothing COULD check, and `refusal` refuses one that a check
        # rejected — so what is left here is "verified is false for some third
        # reason". That is unreachable today. It stays because the invariant is
        # the point: a scan is never imported unverified, whatever route the
        # code takes to get here, and the arithmetic decides it rather than the
        # fact that a model sounded sure.
        raise HTTPException(
            status_code=422,
            detail="A scanned statement is only accepted when its figures add "
                   "up to what the statement itself says — either its own "
                   "totals, or the opening and closing balances printed on it.")

    if not db:
        # Mock mode returns the same SHAPE as the real path. Omitting
        # column_source/balance_check here would leave the frontend reading
        # undefined in demo mode only — the kind of gap that is found by a
        # customer rather than by a test.
        return api_response(True, {"statement_id": "mock-id", "imported": len(txns),
                                   "duplicates_skipped": 0, "total_rows": len(txns),
                                   "column_source": mapping_source,
                                   "balance_check": balance_agreement(txns),
                                   "tie_out": check["tie_out"],
                                   "totals_check": check["totals_check"],
                                   "verified": check["verified"],
                                   "verification_gap": check["gap"],
                                   "totals_mismatch_acknowledged": check["acknowledged"],
                                   "read_with_ai": used_vision})
    file_meta = {
        "file_name": file.filename, "file_size_bytes": len(content),
        "source_format": fmt, "file_hash": file_hash(content),
    }
    acknowledgement = None
    if check["acknowledged"]:
        tot = check["totals_check"]
        acknowledgement = {
            "reason": ack_reason,
            "debit_difference_paise": tot["debit_difference_paise"],
            "credit_difference_paise": tot["credit_difference_paise"],
            # public.users.id — the INTERNAL user id, because the column FKs
            # users(id) (CLAUDE.md). current_user carries both, and this module
            # already has one scar from passing auth_user_id to a column that
            # wanted the other: the column-mapping save below.
            "by": current_user.get("id"),
        }
    result = banking_service.import_normalized(
        db, current_user["firm_id"], client_id, bank_name, account_number, txns,
        bank_account_id=bank_account_id, actor_id=current_user.get("auth_user_id"),
        file_meta=file_meta, totals_acknowledgement=acknowledgement,
    )

    # The mapping is saved only AFTER the import succeeded, and only when asked.
    # Saving a mapping that then failed to import would teach the account a
    # layout that does not work, and apply it silently to the next upload.
    if save_mapping and mapping and bank_account_id:
        try:
            headers = inspect_statement(file.filename or "", content)["headers"]
            column_mappings.save_mapping(
                db, current_user["firm_id"], client_id, bank_account_id,
                headers, mapping,
                # public.users.id — the INTERNAL user id. current_user carries
                # BOTH, and created_by FKs the internal one (CLAUDE.md). Passing
                # auth_user_id here failed the FK on every save, and the failure
                # was swallowed into mapping_saved=False: the statement imported,
                # the layout was silently not learned, and the next month asked
                # again.
                actor_id=current_user.get("id"))
            result["mapping_saved"] = True
        except (StatementParseError, Exception) as e:            # noqa: BLE001
            # The statement is already in. Failing the whole upload because the
            # convenience could not be stored would be the wrong trade.
            _logger.warning("column mapping not saved for account %s: %s",
                            bank_account_id, e)
            result["mapping_saved"] = False

    # Say which way the columns were read. "detected" and "saved" look identical
    # in the resulting data, and a CA who has just mapped a bank should be able
    # to see that the mapping is what was used.
    result["column_source"] = mapping_source
    result["balance_check"] = balance_agreement(txns)
    # Always present, whether they verified anything or named themselves a gap.
    # An unchecked import and a checked one must not look the same to the
    # caller, and `verified` is the one field that says which this was without
    # the caller having to reason about two checks that answer different
    # questions.
    result["tie_out"] = check["tie_out"]
    result["totals_check"] = check["totals_check"]
    result["verified"] = check["verified"]
    result["verification_gap"] = check["gap"]
    result["totals_mismatch_acknowledged"] = check["acknowledged"]
    # Say when a model read the statement. A CA reviewing these lines later is
    # entitled to know they came off a picture rather than a file, and the
    # source_format on the statement row records the same thing durably.
    result["read_with_ai"] = used_vision
    # Propose for what just landed — one chunk, so the upload stays fast; the
    # screen keeps redrafting while counts.undrafted is non-zero, then passes
    # the trusted-rule drafts with a progress bar (09-bank-entries.md).
    try:
        result["entries"] = bank_entry_service.redraft(
            db, current_user["firm_id"], client_id, limit=REDRAFT_CHUNK)
    except Exception as e:                                        # noqa: BLE001
        # The statement is in. A failed proposal costs the screen one extra
        # redraft call, not the import.
        _logger.warning("post-import redraft failed for client %s: %s", client_id, e)
        result["entries"] = {"drafted": 0, "changed": 0, "remaining": None}
    return api_response(True, result)



# ─── Statement column mapping (audit Tier 3.2) ───────────────────────────────

@router.post("/statements/inspect")
def inspect_statement_file(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    bank_account_id: Optional[str] = Form(None),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Show a statement's header row and first rows so a CA can map the columns.

    This is the way past 'Unsupported bank statement format'. Nothing is stored
    and nothing is parsed into transactions — the file is here precisely because
    parsing it failed, so anything needing a working mapping comes after the CA
    supplies one.

    When the account already has a mapping for this exact header layout it is
    returned as `saved_mapping`, so the CA sees what will be used rather than
    being asked the same question twice.
    """
    assert_client_access(current_user, client_id)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    try:
        info = inspect_statement(file.filename or "", content)
    except StatementParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db = _db()
    saved = (column_mappings.find_mapping(db, current_user["firm_id"], bank_account_id,
                                          info["header_fingerprint"])
             if db and bank_account_id else None)
    info["saved_mapping"] = saved.get("mapping") if saved else None
    info["saved_mapping_id"] = saved.get("id") if saved else None
    return api_response(True, info)


@router.post("/statements/preview")
def preview_statement_with_mapping(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    column_mapping: str = Form(...),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Parse with the CA's mapping and show what it produces — WITHOUT importing.

    This is the safety net that replaces the column-label check an explicit
    mapping deliberately skips. Two things are returned and both matter: the
    parsed rows, so a human can see that the dates are dates and the money is
    the right way round; and `balance_check`, which tests the parse against the
    bank's OWN running balance. A mapping with debit and credit swapped parses
    perfectly and inverts the client's entire cash position — no label check
    would catch that, and the balance arithmetic catches it on the first row.
    """
    assert_client_access(current_user, client_id)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    try:
        mapping = json.loads(column_mapping)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="column_mapping must be a JSON object of column positions.")
    try:
        info = inspect_statement(file.filename or "", content)
        validate_mapping(mapping, len(info["headers"]))
        parsed = parse_statement_detailed(file.filename or "", content, mapping)
        txns = parsed.transactions
    except StatementParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return api_response(True, {
        "headers": info["headers"],
        "total_rows": info["total_rows"],
        "parsed_count": len(txns),
        # A row the mapping cannot read is skipped by _rows_to_txns, quietly and
        # for good reasons (totals lines, sub-headers). Reporting the gap turns
        # "quietly" into a number a CA can judge: 3 of 200 is a footer, 180 of
        # 200 is a wrong date column.
        "skipped_count": max(0, info["total_rows"] - len(txns)),
        "rows": [{
            "transaction_date": t.transaction_date,
            "description": t.description,
            "reference_no": t.reference_no,
            "debit_paise": t.debit_paise,
            "credit_paise": t.credit_paise,
            "balance_paise": t.balance_paise,
        } for t in txns[:20]],
        "balance_check": balance_agreement(txns),
        # What the bank printed about itself, when it printed anything. The
        # preview is where a CA judges a mapping before importing under it, and
        # a mapping whose parse does not sum to the statement's own totals is
        # wrong however plausible the twenty rows above look.
        "totals_check": totals_agreement(txns, parsed.printed_totals),
    })


@router.get("/statements/column-mappings")
def list_column_mappings(
    client_id: Optional[str] = Query(None),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """Saved column mappings, so a CA can see and correct what a bank taught us."""
    if client_id:
        assert_client_access(current_user, client_id)
    db = _db()
    rows = column_mappings.list_mappings(db, current_user["firm_id"],
                                         client_id=client_id,
                                         bank_account_id=bank_account_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.delete("/statements/column-mappings/{mapping_id}")
def delete_column_mapping(
    mapping_id: str = Path(...),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Forget a mapping. The next upload of that layout asks again.

    Scoped like every other row-addressed banking endpoint: resolve the row
    inside the firm, check the caller may reach its client, and 404 for both
    'no such row' and 'not your client' so the status cannot be used to probe
    which ids exist.
    """
    db = _db()
    if not db:
        return api_response(True, {"deleted": True})
    rows = (db.table("bank_statement_column_mappings").select("id, client_id")
            .eq("firm_id", current_user["firm_id"]).eq("id", mapping_id)
            .limit(1).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Column mapping not found.")
    assert_client_access(current_user, rows[0].get("client_id"))
    ok = column_mappings.delete_mapping(db, current_user["firm_id"], mapping_id)
    return api_response(True, {"deleted": ok})



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


@router.delete("/statements/{statement_id}")
def delete_statement(
    statement_id: str = Path(...),
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Undo a mis-imported statement (BANK-06).

    The wrong file, the wrong client, the wrong month. Until this there was no
    way back: the only DELETE in this router was for a saved column mapping, so
    a statement imported by mistake stayed in the register for ever, and its
    lines kept surfacing in the match queue.

    WHY THIS IS A HARD DELETE AND NOT A SOFT ONE
        The whole point is to import the RIGHT file afterwards, and the import
        dedupes on a unique (client_id, import_hash) — see
        banking_service._existing_hashes. Rows left behind under a deleted_at
        would silently skip every line of the re-import, which is the failure
        this endpoint exists to end. So the statement and its lines go, and the
        audit_log keeps the whole of both.

    WHY ONLY AN UNTOUCHED STATEMENT
        A statement is the VOUCHER for every receipt and payment posted off it
        — Companies Act s. 128(5) reaches it expressly, which is why
        services/bank_erasure.py refuses to delete a bank account that has one.
        A statement nothing has been posted, matched, ignored or reconciled
        from is not yet the voucher for any entry: it is an import. That is the
        line, and it is drawn on the LINES rather than on the file.
    """
    db = _db()
    if not db:
        return api_response(True, {"statement_id": statement_id, "deleted": True})

    # Row-addressed with no client_id in the request, so the mount guard never
    # fires — the same helper every other row-addressed endpoint here uses.
    _assert_statement_scope(db, current_user, statement_id)
    statement = (db.table("bank_statements").select("*")
                 .eq("firm_id", current_user["firm_id"]).eq("id", statement_id)
                 .limit(1).execute().data)[0]

    txns = (db.table("bank_transactions").select("*")
            .eq("firm_id", current_user["firm_id"])
            .eq("statement_id", statement_id).execute().data) or []

    posted = [t for t in txns if t.get("match_status") == "posted" or t.get("posted_journal_id")]
    decided = [t for t in txns if t.get("match_status") in ("matched", "ignored")]
    reconciled = [t for t in txns if t.get("reconciliation_id")]

    if posted or decided or reconciled:
        parts = []
        if posted:
            parts.append(f"{len(posted)} already posted to the ledger")
        if reconciled:
            parts.append(f"{len(reconciled)} in a completed reconciliation")
        if decided:
            parts.append(f"{len(decided)} matched or ignored")
        raise HTTPException(
            status_code=422,
            detail=("This statement can no longer be removed as a mis-import: "
                    + ", ".join(parts) + ". A statement lines have been posted "
                    "off is the voucher for those entries (Companies Act "
                    "s. 128(5)) — reverse the journals and unmatch the lines "
                    "first, or leave it and import the right file alongside it."))

    # The WHOLE statement and every line, before either goes — the log is what
    # is immutable, not the row (migrations 275/276's rule for a journal).
    log_event(
        current_user["firm_id"], "bank_statement", statement_id, "delete",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data=dict(statement),
        metadata={"transactions": txns, "transaction_count": len(txns)},
    )

    # bank_transactions FK to bank_statements ON DELETE CASCADE (migration 006),
    # so the lines go with the header; deleted explicitly first so a database
    # without the cascade cannot leave them orphaned and still matchable.
    db.table("bank_transactions").delete().eq(
        "firm_id", current_user["firm_id"]).eq("statement_id", statement_id).execute()
    db.table("bank_statements").delete().eq(
        "firm_id", current_user["firm_id"]).eq("id", statement_id).execute()

    return api_response(True, {
        "statement_id": statement_id,
        "deleted": True,
        "transactions_removed": len(txns),
    })


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
    """Reject a suggestion / clear a manual match (B.2.5).

    NOT the way to undo a POSTED transaction — bank_matching_service.unmatch
    refuses one, deliberately. Use /undo, which reverses the journal and
    un-settles the document as well. The screen's Undo button pointed here for
    a long time and 409'd on every click.
    """
    db = _db()
    if not db:
        # Was `return api_response(True, ...)`: a mock-mode success that touched
        # nothing. It made the whole suite pass over an Undo button that could
        # never work in production, which is exactly the failure a mock is
        # supposed to surface. It now runs the real service against the
        # in-memory source like every other endpoint here.
        return api_response(True, {"id": txn_id, "match_status": "unmatched",
                                   "note": "mock mode — no database"})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_matching_service.unmatch(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/undo")
def undo_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Put a posted transaction back in the queue.

    Reverses its journal (append-only — the original entry is never touched),
    gives the settled invoice or bill back what this line paid off, and takes
    back any credit an overpayment granted. The row returns to `matched` when a
    document is still linked, because undoing the POSTING is not undoing the
    CA's identification of which invoice it was.
    """
    db = _db()
    if not db:
        raise HTTPException(status_code=503,
                            detail="Undo needs the database — it reverses a journal.")
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_posting_service.undo(
        db, current_user["firm_id"], txn_id,
        actor_id=current_user.get("id"), actor_auth_id=current_user.get("auth_user_id")))


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
    """Map a transaction to a GL account (status → matched). Does not post.

    With `derive_category`, the category is derived from that account rather
    than asked for separately — the ledger-first path the Categorize screen
    uses. See domain/banking/account_category for what is derived and, more
    importantly, for the guarantee that the counter leg still posts to exactly
    the account chosen.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "matched", "account_id": data.account_id})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, banking_service.set_account(
        db, current_user["firm_id"], txn_id, data.account_id,
        derive_category=data.derive_category))


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

    Either a pasted link, which must be http or https — a javascript: or data:
    URL stored here and rendered as a link is stored XSS, so the scheme
    vocabulary is closed rather than sanitised — or a file already uploaded to
    the firm's document store, by its document id. An uploaded document is
    NEVER stored as a url: the store's link is signed and expires within the
    hour, so a fresh one is minted when someone opens it.
    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "attachments": []})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_batch_service.add_attachment(
        db, current_user["firm_id"], txn_id, data.name, data.url, data.document_id,
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
        db, current_user["firm_id"], txn_id, data.url, data.document_id,
        actor_id=current_user.get("auth_user_id")))
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


# ─── Bank entries (migration 322, docs/architecture/09-bank-entries.md) ──────
# A statement line becomes a voucher; the draft is on the row; the CA passes
# ready drafts in bulk and answers the rest. These read stored columns — the
# pools are read by redraft, in chunks, and by the detail of ONE line.

_ENTRY_STATES = "^(to_do|needs_you|proposed|ready|covered|passed|set_aside|all)$"


@router.get("/entries")
def list_entries(
    client_id: str = Query(...),
    state: str = Query("to_do", pattern=_ENTRY_STATES),
    bank_account_id: Optional[str] = Query(None),
    # 1000, not 200: DataTable's shared "rows per page" control
    # (components/ui/data-table.tsx PAGE_SIZES) offers up to 1000, and this
    # was the one screen capped below that. Picking 1000 in the Entries
    # toolbar sent limit=1000 straight into a 422 "Input should be less than
    # or equal to 200" — a plain validation error, but the screen has no
    # request-level error copy, so it rendered as the same "Something went
    # wrong" card a real 500 does. The other server-paged screen
    # (GET /accounting/ledger) already allows 1000; this endpoint's per-row
    # work (kind_for, narration parsing, one chunked splits query, GST
    # eligibility) is no heavier, so there is no reason for a lower ceiling.
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, max_length=200),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """One page of entries in a state, with the total. `to_do` is everything
    still needing anyone (needs_you + proposed + ready)."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"rows": [], "total": 0, "limit": limit, "offset": offset,
                                   "ledger_order": []})
    rows, total = bank_entry_service.list_entries(
        db, current_user["firm_id"], client_id, state=state, limit=limit, offset=offset,
        q_text=q, bank_account_id=bank_account_id)
    return api_response(True, {
        "rows": rows, "total": total, "limit": limit, "offset": offset,
        "ledger_order": bank_matching_service.ledger_order(db, current_user["firm_id"], client_id),
    })


@router.get("/entries/counts")
def entry_counts(
    client_id: str = Query(...),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("banking", "read")),
):
    """One number per state, plus undrafted (the screen redrafts while it is
    non-zero) and trusted_pending (the screen passes these with a progress
    bar). SQL counts, never a scan."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {s: 0 for s in
                                   ("needs_you", "proposed", "ready", "covered", "passed",
                                    "set_aside", "to_do", "undrafted", "trusted_pending")})
    return api_response(True, bank_entry_service.counts(
        db, current_user["firm_id"], client_id, bank_account_id=bank_account_id))


@router.get("/entries/{txn_id}")
def get_entry(
    txn_id: str,
    current_user: dict = Depends(rbac("banking", "read")),
):
    """The one line the CA opened: the row, live document candidates, the
    payee's history with its evidence, and any transfer counterpart."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "suggestions": [], "history": None})
    _assert_txn_scope(db, current_user, txn_id)
    return api_response(True, bank_entry_service.get_entry(db, current_user["firm_id"], txn_id))


@router.post("/entries/redraft")
def redraft_entries(
    data: EntriesRedraftIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Propose for one chunk of open lines and say how many remain. Writes
    proposals only — nothing posts, nothing is matched, nothing is paired."""
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"drafted": 0, "changed": 0, "remaining": 0,
                                   "stale_before": data.stale_before})
    return api_response(True, bank_entry_service.redraft(
        db, current_user["firm_id"], data.client_id, limit=data.limit,
        stale_before=data.stale_before, txn_ids=data.transaction_ids))


@router.post("/entries/pass-ready")
def pass_ready_entries(
    data: EntriesPassReadyIn,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """One chunk of "Pass N ready". Every line comes back with its outcome; a
    refused line carries the refusal on the row and is not retried by the
    next chunk. With only_trusted, each line passes as the person who trusted
    its rule, not as the caller.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"passed": 0, "failed": 0, "skipped": 0, "remaining": 0,
                                   "results": []})
    return api_response(True, bank_entry_service.pass_ready(
        db, current_user["firm_id"], data.client_id, limit=data.limit,
        only_trusted=data.only_trusted, bank_account_id=data.bank_account_id,
        txn_ids=data.transaction_ids,
        actor_id=current_user.get("id"), actor_auth_id=current_user.get("auth_user_id")))


@router.post("/transactions/{txn_id}/pass")
def pass_entry(
    txn_id: str,
    data: Optional[PassEntryIn] = None,
    current_user: dict = Depends(rbac("banking", "write")),
):
    """Pass ONE line: apply its draft (or the CA's own coding) and post it
    through the one posting path. A PROPOSED draft may be passed here — the
    click is the CA accepting it — but never in bulk.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "status": "passed",
                                   "reason": "mock", "posted_journal_id": "mock-je"})
    _assert_txn_scope(db, current_user, txn_id)
    out = bank_entry_service.pass_entry(
        db, current_user["firm_id"], txn_id,
        actor_id=current_user.get("id"), actor_auth_id=current_user.get("auth_user_id"),
        gst_rate_bps=data.gst_rate_bps if data else None,
        is_interstate=bool(data.is_interstate) if data else False)
    if out["status"] == "failed":
        # One line, one click: the refusal is the response, not a row in a list.
        raise HTTPException(status_code=422, detail=out["reason"])
    return api_response(True, out)


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
    """Adjust the opening/closing balance (rejected once completed).

    The documented adjustment is NOT settable here — see
    PUT /reconciliations/{id}/adjustment, which is Manager+ and needs a reason.
    A body still carrying `adjustments_paise` is rejected by the model rather
    than ignored: silently dropping it would show the CA a figure that never
    landed.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, **data.model_dump(exclude_none=True)})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.update_session(
        db, current_user["firm_id"], recon_id, data.model_dump(exclude_none=True),
        actor_id=current_user.get("auth_user_id")))


@router.put("/reconciliations/{recon_id}/adjustment")
def set_reconciliation_adjustment(
    recon_id: str,
    data: ReconciliationAdjustmentIn,
    current_user: dict = Depends(rbac("banking", "approve")),
):
    """Record — or clear — the documented difference the reconciled lines do not
    explain. MANAGER+ , and a reason is mandatory for any non-zero figure.

    WHY IT HAS ITS OWN ROUTE AND ITS OWN TIER (BANK-05)

    This is the one figure in the module that can force a period to tie out, and
    completing a period freezes a snapshot that is rendered as a certified "Bank
    Reconciliation Statement". It used to ride on the generic PATCH under
    rbac("banking", "write") as a bare integer: no reason, no audit row, nothing
    printed on the document. An Executive who could not find a ₹47,300
    difference could type it in and complete the period, and nobody reading the
    PDF afterwards could tell what the ₹47,300 was.

    rbac("banking", "approve") is the Manager tier core/permissions.py has
    defined for signing off a reconciliation since it was written, and which no
    router referenced at all until this one. The reason, the author, the audit
    row, the timeline warning and the line on the PDF are in
    bank_reconciliation_service.set_adjustment; migration 355 backs the pairing
    with a CHECK so no other write path can leave a plug unexplained.
    """
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id,
                                   "adjustments_paise": data.adjustments_paise,
                                   "adjustments_reason": data.reason})
    _assert_recon_scope(db, current_user, recon_id)
    return api_response(True, bank_reconciliation_service.set_adjustment(
        db, current_user["firm_id"], recon_id, data.adjustments_paise, data.reason,
        actor_id=current_user.get("auth_user_id"),
        # public.users.id — the column FKs users(id), not the auth id (CLAUDE.md).
        actor_internal_id=current_user.get("id")))


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
    # A new rule may cover lines already drafted from history or nothing.
    # Mark them for re-proposal; the screen redrafts in chunks on its next load.
    bank_entry_service.mark_stale(db, current_user["firm_id"], data.client_id)
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
    # TRUSTED is the one place the product acts without a click (migration
    # 322, 09-bank-entries.md). Promoting needs banking.approve — a Manager or
    # Partner — and records WHO, because that person is the journal's
    # created_by for everything the rule passes. An Executive may write a
    # rule; only someone answerable for the books may let it post. Demoting
    # needs no more than editing the rule, and clears the record.
    if "is_trusted" in fields:
        if fields["is_trusted"]:
            from core.permissions import can
            if not can(current_user.get("role") or "", "banking", "approve"):
                raise HTTPException(
                    status_code=403,
                    detail="Only a Manager or Partner can let a rule pass entries by itself.")
            if not (rule.get("suggested_account_id") or fields.get("suggested_account_id")):
                raise HTTPException(
                    status_code=422,
                    detail="A trusted rule must name a ledger — it cannot pass an entry without one.")
            fields["trusted_by"] = current_user.get("id")
            fields["trusted_at"] = _now_iso()
        else:
            fields["trusted_by"] = None
            fields["trusted_at"] = None
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
            detail=("A GST rate needs a ledger to code the amount to — "
                    "the split books the ex-tax amount there."))
    row = (db.table("bank_matching_rules").update(fields)
           .eq("id", rule_id).eq("firm_id", current_user["firm_id"]).execute())
    # What the rule proposes may have changed; what it is trusted to do has not
    # changed which lines it covers, so only a payload edit re-proposes.
    if any(k in fields for k in ("description_pattern", "amount_min_paise", "amount_max_paise",
                                 "txn_type", "suggested_account_id", "suggested_category",
                                 "suggested_gst_rate_bps", "suggested_is_interstate", "is_active")):
        bank_entry_service.mark_stale(db, current_user["firm_id"], rule["client_id"])
    return api_response(True, (row.data or [{}])[0])


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


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
