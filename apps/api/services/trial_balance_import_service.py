"""
Trial-balance import — turns an imported trial balance into real General Ledger
entries, so the numbers a CA imports actually appear in the reports.

WHAT THIS REPLACED, AND WHY
    The import wizard used to write opening_balance_dr_paise/_cr_paise onto
    chart_of_accounts. Those columns do not exist in any migration, so the whole
    feature was gated off behind a capability probe. Adding them would not have
    helped: nothing reads them. The reporting engine reads the JOURNAL, so an
    import that only touched the account master would have reported success and
    changed no report — worse than the honest "unavailable" banner it replaced.

    A trial balance is brought into the books by posting an opening journal
    entry whose lines reproduce it. That is what this service does.

RELATIONSHIP TO opening_balance_service.py
    Same discipline, different source. That service reconciles the ledger to
    master-record opening balances on customers/vendors/bank_accounts; this one
    reconciles it to an imported trial balance. Both post append-only balanced
    DELTAS and never mutate a posted journal.

    They must not share a journal family. opening_balance_service treats every
    entry with source_type='Opening' as its own and reverses anything in there
    that the master records do not justify — so a trial balance posted into that
    family would be silently backed out on the next customer edit. This service
    therefore posts under source_type='TrialBalance', and neither touches the
    other's entries. test_trial_balance_import_service.py pins that separation.

SCOPING
    chart_of_accounts is UNIQUE on (firm_id, account_name) AND on (firm_id, account_code), whichever client an account
    belongs to. Most accounts are firm-level (client_id NULL) and shared across a firm's clients, and
    phase2_journal_service._find_account resolves 'client_id = this client OR NULL' accordingly; any account this import has
    to create is created firm-level. But a client can own a ledger too (the per-bank ledgers routers/banking creates carry the
    client's id, with codes from 1101 up and names such as 'HDFC Bank - 7890'), so the NAMES this import may MATCH are this
    client's and the firm-level ones, while the CODES and NAMES it may not COLLIDE with are the whole firm's, another client's
    included (ledger POST-A-313): a code or a name another client's ledger holds answered 23505 at the insert, as a generic 500.
    The CLIENT scoping of the books lives on the journal entry, which is what makes one client's trial balance distinct from
    another's.

All money is integer paise. Opening positions are book figures, not supplies —
no GST arises (CGST Act s.7 — bringing forward a balance is not a supply).
"""
from __future__ import annotations

import os
import re
import uuid
import logging
from typing import Optional

from domain.accounting.trial_balance import (
    TrialBalanceRow,
    TrialBalanceError,
    validate,
    net_by_account,
    plan_delta,
    assert_balanced,
)
from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service
from core import db_provider
from core.db_paging import fetch_all
from core.ist_clock import ist_today

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.trial_balance_import")

# entry_type must be one of the journal_entries CHECK values
# (Sales/Purchase/Payment/Receipt/Journal/Contra/Opening).
TB_ENTRY_TYPE = "Opening"
# Identifies this import's journal family. Deliberately NOT 'Opening', which
# belongs to opening_balance_service — see the module docstring.
TB_SOURCE = "TrialBalance"
TB_REFERENCE = "TRIAL-BALANCE"


_db = db_provider.request_db


def _slug_code(name: str) -> str:
    """A deterministic account_code from a name.

    chart_of_accounts.account_code is NOT NULL with UNIQUE (firm_id, account_code),
    but trial-balance CSVs routinely have no code column. (The old wizard passed
    `account_code || null` straight into the insert, which would have violated
    the NOT NULL the moment the feature was switched on.)"""
    # rstrip AFTER truncating: cutting at 24 can land on a separator and leave
    # a trailing hyphen ("TB-BANK-HDFC-").
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper()[:24].rstrip("-")
    return f"TB-{slug or 'ACCOUNT'}"


def _resolve_or_create_accounts(db, firm_id: str, client_id: str,
                                rows: list[TrialBalanceRow]) -> dict[str, str]:
    """{account_name: account_id}, creating any account the trial balance names
    that the firm does not have yet.

    Matching is case-insensitive on name within the firm, scoped 'this client OR
    firm-level' to mirror _find_account. Without the case-insensitive match an
    import of "CASH" would try to create a second account alongside "Cash" and
    hit UNIQUE (firm_id, account_name) at the insert instead."""
    # THE WHOLE FIRM'S CHART, read with a client that sees all of it and in keyset pages. Both unique keys are the firm's, so a
    # check made over this client's accounts and the firm-level ones alone cannot see a code or a name another client's ledger
    # holds, and the insert then fails with 23505. `chart_of_accounts` is assignment-scoped, so read as the caller a member
    # assigned to some clients would not see the others' ledgers either; the route has authorised the caller, what comes back
    # is only names and codes used to avoid a collision, and the INSERT stays on the caller's own client. Without a privileged
    # client (mock mode, a test double) the one it was handed is all there is. PostgREST cuts a response at about a thousand
    # rows without saying so, and a code missed there is a code proposed twice.
    reader = db_provider.service_db_or_none() or db
    firm_chart = fetch_all(
        lambda: reader.table("chart_of_accounts").select("id, account_name, account_code, client_id").eq("firm_id", firm_id),
        key="id", label="trial balance import: the firm's chart of accounts")
    # MATCH by name only among this client's accounts and the firm-level ones; another client's ledger is not this client's
    # account, even where its name is the same.
    # (a uuid is compared as the lower-case text the database returns, so a client id typed in capitals is still this client's)
    mine = str(client_id).lower()
    by_name = {(r.get("account_name") or "").strip().casefold(): r["id"]
               for r in firm_chart if r.get("client_id") is None or str(r["client_id"]).lower() == mine}
    held_elsewhere = {(r.get("account_name") or "").strip().casefold()
                      for r in firm_chart if r.get("client_id") is not None and str(r["client_id"]).lower() != mine}
    used_codes = {(r.get("account_code") or "").strip().upper() for r in firm_chart}

    # Every refusal BEFORE the first insert: an import that stops half way has already created accounts as a side effect of
    # being rejected (the same reason `validate` runs before any database work).
    for row in rows:
        name = row.account_name.strip()
        if name.casefold() not in by_name and name.casefold() in held_elsewhere:
            raise TrialBalanceError(
                f"The account '{name}' is another client's ledger in this firm, and an account name can be used once in a "
                f"firm, so this import cannot create it again. Rename that row in the trial balance (for example with this "
                f"client's name) and run the import again.")

    resolved: dict[str, str] = {}
    for row in rows:
        name = row.account_name.strip()
        hit = by_name.get(name.casefold())
        if hit:
            resolved[name] = hit
            continue

        code = (row.account_code or "").strip() or _slug_code(name)
        # UNIQUE (firm_id, account_code): disambiguate rather than fail the whole
        # import because two names slugged to the same code.
        base, n = code, 2
        while code.upper() in used_codes:
            code = f"{base}-{n}"
            n += 1
        used_codes.add(code.upper())

        created = (db.table("chart_of_accounts").insert({
            "firm_id": firm_id,
            # Firm-level, matching every existing account in production and the
            # UNIQUE (firm_id, account_name) constraint. See module docstring.
            "client_id": None,
            "account_name": name,
            "account_code": code,
            "account_type": row.account_type,
            "is_active": True,
        }).execute().data or [])
        if not created:
            raise TrialBalanceError(
                f"Could not create the account '{name}'. Create it in the Chart "
                f"of Accounts first, then re-run the import.")
        resolved[name] = created[0]["id"]
        by_name[name.casefold()] = created[0]["id"]

    return resolved


def _current_tb_net(db, firm_id: str, client_id: str) -> dict[str, int]:
    """Net (debit − credit) paise per account across this client's already-posted
    trial-balance family — the position the ledger currently carries from earlier
    imports."""
    entries = (db.table("journal_entries").select("id")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("source_type", TB_SOURCE).is_("deleted_at", "null")
               .execute().data or [])
    ids = [e["id"] for e in entries]
    if not ids:
        return {}
    lines = (db.table("journal_lines").select("account_id, debit_paise, credit_paise")
             .in_("journal_entry_id", ids).execute().data or [])
    net: dict[str, int] = {}
    for l in lines:
        acc = l.get("account_id")
        net[acc] = net.get(acc, 0) + int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
    return net


def _default_opening_date(db, client_id: str) -> str:
    """The client's financial-year start, else 1 April of the current FY.

    The Indian financial year runs 1 April to 31 March, so a trial balance
    brought forward without an explicit date belongs at the FY start."""
    try:
        cl = (db.table("clients").select("financial_year_start")
              .eq("id", client_id).limit(1).execute())
        if cl.data and cl.data[0].get("financial_year_start"):
            return str(cl.data[0]["financial_year_start"])
    except Exception as e:
        _logger.warning("trial_balance: client FY-start lookup failed: %s", e)
    # The Indian day: at 01:40 IST on 1 April the UTC clock still reads March (see opening_balance_service).
    today = ist_today()
    fy_start = today.year if today.month >= 4 else today.year - 1
    return f"{fy_start}-04-01"


def preview_trial_balance(rows: list[TrialBalanceRow]) -> dict:
    """Validate without touching the database, so the wizard can show the CA what
    is wrong before they commit to posting anything."""
    total_dr, total_cr = validate(rows)
    return {"valid": True, "rows": len(rows),
            "total_debit_paise": total_dr, "total_credit_paise": total_cr}


def import_trial_balance(
    firm_id: str,
    client_id: str,
    rows: list[TrialBalanceRow],
    opening_date: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Post ONE balanced journal bringing the client's ledger to this trial balance.

    Idempotent: re-importing an unchanged trial balance computes a zero delta and
    posts nothing. Refuses an unbalanced trial balance, and refuses to write into
    a locked financial year."""
    # Validate BEFORE any database work — an inadmissible trial balance must not
    # create accounts as a side effect of being rejected.
    validate(rows)

    if _USE_MOCK:
        return {"posted": False, "mock": True, "reason": "no DB configured"}

    db = _db()
    date = opening_date or _default_opening_date(db, client_id)

    # FY-lock check before any mutation. Nothing posted is ever deleted, so a
    # block here leaves the books untouched.
    period_validation_service.validate_posting_date(firm_id, date)

    accounts = _resolve_or_create_accounts(db, firm_id, client_id, rows)
    target = {accounts[name]: amount for name, amount in net_by_account(rows).items()}
    current = _current_tb_net(db, firm_id, client_id)

    lines = plan_delta(target, current)
    if not lines:
        return {"posted": False, "reason": "the ledger already matches this trial balance",
                "opening_date": date, "accounts": len(accounts)}

    # Belt and braces: the delta balances by construction, but an unbalanced
    # journal must never reach the posting kernel.
    assert_balanced(lines)

    reference = f"{TB_REFERENCE}-{uuid.uuid4().hex[:8].upper()}"
    entry_id = phase2_journal_service._create_journal(
        db, firm_id, client_id, date, reference,
        "Trial balance imported", TB_ENTRY_TYPE, lines,
        is_posted=True, source_type=TB_SOURCE, created_by=created_by,
    )

    total_dr = sum(l["debit_paise"] for l in lines)
    _logger.info("Posted trial-balance import %s for client %s (%d line(s), %d paise each side)",
                 entry_id, client_id, len(lines), total_dr)
    return {"posted": True, "journal_entry_id": entry_id, "opening_date": date,
            "accounts": len(accounts), "adjustment_lines": len(lines),
            "total_debit_paise": total_dr, "total_credit_paise": total_dr}
