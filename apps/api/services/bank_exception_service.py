"""What a partner should look at on this client's bank, and why.

THE MODULE THIS SERVES HAD NO SERVICE, AND SAID SO
    `domain/banking/exceptions.py` is 315 lines of rules deciding which posted
    bank lines carry a reason to look, and its own docstring names
    `services/bank_exception_service.py` as the thing that gathers their
    context. That file did not exist, so nothing ever evaluated a rule and no
    partner ever saw a flag. `tests/test_a_domain_module_has_a_reader.py`
    carried the gap as a named entry rather than pretending it was fine.

    This is that file. It fetches; the rules decide. Nothing here re-states a
    threshold, re-words a message or adds a rule — the one place a rule lives
    is the domain module, and a service that quietly added an eighth would be
    the second implementation this codebase keeps having to delete.

IT REPORTS. NOTHING IS BLOCKED, AND THAT IS THE OWNER'S DECISION
    `BankException.blocking` is computed by the rules and is deliberately
    consumed by nobody, here included: the module's own argument — that a
    platform should not hold a CA's books hostage to a threshold it invented —
    is right, and raising a flag is not blocking a posting. A test asserts this
    service never calls `blocks_posting`, so wiring a gate stays a decision
    somebody takes rather than a line somebody adds.

THE POPULATION IS WHAT WAS PASSED, NOT WHAT IS WAITING
    Risk-based review is a partner testing what is unusual in work that has
    been DONE; what is still waiting is the Entries tab's own job and already
    has a screen. So the subjects are lines with `match_status = 'posted'`.

THE READ IS BOUNDED BY THE PERIOD, WHICH IS WHY THE PERIOD IS REQUIRED
    CLAUDE.md's reporting rule: what crosses the wire must be proportional to
    the ANSWER, not to the ledger. A review list's answer is the handful of
    flagged lines, and the ledger it is drawn from is unbounded — a client
    three years in has thirty-six months of statements. So `from_date` and
    `to_date` have NO DEFAULT. An optional period is how the ledger-sized read
    comes back: somebody omits it once and the query silently becomes every
    line the client has ever had. BANK-07 is the recorded instance.

    `_duplicate_suspect` compares each line against its NEIGHBOURS, so the
    fetch reaches `duplicate_window_days` either side of the period and the
    margin is used for siblings only — a line dated outside the period is
    never itself a subject, or asking for June would report May's lines.

HOW "HAVE WE SEEN THIS BEFORE" IS ANSWERED WITHOUT READING THE HISTORY
    `_new_payee` and `_unusual_account` ask whether a payee or a counter
    account has appeared before. Read naively that is the whole ledger, which
    is exactly the rule above. It is asked the other way round instead: take
    the period's own payees and accounts — tens, not thousands — and ask
    whether ANY earlier line carries one, `.in_()` over that small set,
    stopping the moment every one of them has been seen. A payee that appears
    constantly is answered by the first page; only a genuinely new one costs
    pages, and there are few of those or the flag would be worthless.

    **THE HISTORY HAS THREE STATES, NOT TWO.** Complete, truncated, and EMPTY —
    a client whose earliest bank data is this very period. The third was found
    by writing the test: with no earlier lines, every payee is a first payee and
    every account one not used before, so both rules fire on EVERY row and the
    list a partner opens is the statement back again. True of everything is
    information about nothing, which is the module's own argument about
    warnings. So an empty history withholds them too, under its own sentence —
    "there is nothing to have seen" is a different thing to tell a partner from
    "we could not tell".

    **A cap that is hit WITHHOLDS those two rules rather than running them on a
    partial set**, and says so in `gaps`. Running them would report every payee
    the truncated read happened to miss as "first time in this client's bank
    history" — a sentence that is simply false, on a list whose whole value is
    that a partner can trust the few rows in it.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from core.db_paging import fetch_all
from core.observability import capture_soft_failure
from domain.banking import exceptions as rules
from domain.banking.matcher import bill_open_paise, invoice_open_paise
from core.ist_clock import ist_today

_logger = logging.getLogger(__name__)

# EVERY PROJECTION IN THIS MODULE IS A LITERAL AT ITS OWN CALL SITE.
# `tests/test_backend_columns_exist_pg.py` reads `.select()` arguments as TEXT
# against the real schema, so a projection reached through a module constant,
# an f-string or a `", ".join(...)` is invisible to it — and a column renamed
# out from under one would be discovered in production instead of in CI. The
# repetition is the price, and it is the same decision `domain/firm/identity`
# and `BankEntryService._document_numbers` both record.

# How many pages the "seen before" probe may read before it gives up and says
# so. Each page is 1,000 rows, so this is a generous bound on a question that
# is usually answered by the first one.
_HISTORY_PAGE_CAP = 5

GAP_HISTORY_INCOMPLETE = "history_incomplete"
GAP_HISTORY_EMPTY = "no_earlier_history"
GAP_DOCUMENTS_UNREAD = "matched_documents_unread"

GAP_SENTENCES = {
    GAP_HISTORY_INCOMPLETE:
        "This client has more bank history than could be read in one pass, so "
        "'first time' could not be established. The two rules that depend on "
        "it — a new payee, and a ledger account not used before — were NOT "
        "applied to this period rather than applied to a partial history, "
        "which would report payees as new that are not.",
    GAP_HISTORY_EMPTY:
        "This is the earliest period this client has bank data for, so every "
        "payee is a first payee and every ledger account is one not used "
        "before. Those two rules were NOT applied: true of every line, they "
        "say nothing about any of them, and a list where every row is flagged "
        "is a list nobody reads.",
    GAP_DOCUMENTS_UNREAD:
        "The documents some of these lines were matched to could not be read, "
        "so how much each one still owed is unknown. The settlement checks — "
        "short or over settlement, and a weak match — were not applied to "
        "those lines.",
}


def _period_rows(db, firm_id: str, client_id: str, *, from_date: str, to_date: str,
                 margin_days: int, bank_account_id: Optional[str]) -> list[dict]:
    """Every line in the period, plus the duplicate window either side."""
    lo = (date.fromisoformat(from_date) - timedelta(days=margin_days)).isoformat()
    hi = (date.fromisoformat(to_date) + timedelta(days=margin_days)).isoformat()

    # Resolved ONCE, outside the page builder: `fetch_all` calls it per page and
    # this is a read of its own.
    statements = _statement_ids(db, firm_id, bank_account_id) if bank_account_id else None

    def one_page():
        # The whole chain is written out here rather than assembled through a
        # helper taking `q`: the column guard follows `.eq()`/`.gte()` back to
        # the table the chain STARTED on, and a builder passed in as a
        # parameter breaks that trail. firm_id explicitly, not RLS alone —
        # CLAUDE.md: the app-layer filter is the primary isolation control.
        q = (db.table("bank_transactions")
             .select("id, transaction_date, description, payee_name, debit_paise, "
                     "credit_paise, account_id, category, match_status, "
                     "matched_entity_type, matched_entity_id")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .gte("transaction_date", lo).lte("transaction_date", hi))
        if statements is not None:
            q = q.in_("statement_id", statements)
        return q

    return fetch_all(one_page)


def _statement_ids(db, firm_id: str, bank_account_id: str) -> list[str]:
    """`bank_transactions` carries no bank_account_id — only `statement_id`, so
    the account is one hop away (CLAUDE.md, BankPostingService.bank_account_id_for).
    Bounded by how many statements the account has, which is months, not lines."""
    rows = fetch_all(lambda: db.table("bank_statements").select("id")
                     .eq("firm_id", firm_id).eq("bank_account_id", bank_account_id))
    return [str(r["id"]) for r in rows]


def _seen_before(db, firm_id: str, client_id: str, *, column: str, wanted: set[str],
                 before: str, bank_account_id: Optional[str]) -> tuple[set[str], bool]:
    """Which of `wanted` appear on a line dated before `before`.

    Returns (seen, complete). `complete` is False when the cap was hit with
    the question still open — see the module docstring for why that WITHHOLDS
    the two rules rather than answering them.
    """
    if not wanted:
        return set(), True
    seen: set[str] = set()
    page_size, last_id = 1000, None
    statements = _statement_ids(db, firm_id, bank_account_id) if bank_account_id else None
    for _ in range(_HISTORY_PAGE_CAP):
        # The two questions are spelled out rather than interpolated, for the
        # reason at the top of this module: `f"id, {column}"` is a projection
        # the column guard cannot read.
        base = db.table("bank_transactions")
        q = (base.select("id, payee_name") if column == "payee_name"
             else base.select("id, account_id"))
        q = (q.eq("firm_id", firm_id).eq("client_id", client_id)
             .lt("transaction_date", before)
             .in_(column, sorted(wanted - seen))
             .order("id").limit(page_size))
        if statements is not None:
            q = q.in_("statement_id", statements)
        if last_id:
            q = q.gt("id", last_id)
        rows = q.execute().data or []
        for r in rows:
            value = r.get(column)
            if value is not None:
                seen.add(str(value))
        if len(rows) < page_size or seen >= wanted:
            return seen, True
        last_id = rows[-1]["id"]
    return seen, False


def _any_earlier_line(db, firm_id: str, client_id: str, *, before: str,
                      bank_account_id: Optional[str]) -> bool:
    """Whether this client has ANY bank line before the period.

    One row, not a count — the question is existence. It is asked separately
    from `_seen_before` because an EMPTY history and a TRUNCATED one are
    different facts with different answers: truncated means "we could not
    tell", empty means "there is nothing to have seen", and reporting the
    second as the first would tell a partner to go and widen a search that has
    nothing to find.
    """
    q = (db.table("bank_transactions").select("id")
         .eq("firm_id", firm_id).eq("client_id", client_id)
         .lt("transaction_date", before).limit(1))
    if bank_account_id:
        q = q.in_("statement_id", _statement_ids(db, firm_id, bank_account_id))
    return bool(q.execute().data)


def _matched_documents(db, firm_id: str, rows: list[dict]) -> tuple[dict, bool]:
    """{(type, id): {outstanding_paise, document_no, party_name}} for the
    matched lines on this page.

    ONE query per document TYPE, chunked — never one per row. Only the two
    kinds that carry an OPEN figure are read: a receipt or a payment is itself
    a settlement, so "short of what the document still owed" is not a question
    about it. `outstanding_paise` comes from `domain/banking/matcher`, which is
    the one definition of what a document still has open (migration 278).
    """
    wanted: dict[str, set[str]] = {}
    for t in rows:
        kind, eid = t.get("matched_entity_type"), t.get("matched_entity_id")
        if eid and kind in ("sales_invoice", "purchase_bill"):
            wanted.setdefault(kind, set()).add(str(eid))

    out: dict[tuple[str, str], dict] = {}
    complete = True
    for kind, ids in wanted.items():
        ordered = sorted(ids)
        for i in range(0, len(ordered), 200):
            chunk = ordered[i:i + 200]
            try:
                if kind == "sales_invoice":
                    # THE §34 NOTE COLUMNS ARE NOT SYMMETRIC AND THE NAMES DO
                    # NOT TELL YOU WHICH WAY THEY GO. On an invoice it is
                    # `credited_paise` (subtracts) and `debit_note_paise`
                    # (adds); on a bill it is `credit_note_paise` (adds) and
                    # `debited_paise` (subtracts) — migration 210 added the
                    # INCREASE document to both sides at once. The first draft
                    # of this had them crossed on both tables and
                    # test_backend_columns_exist_pg caught it, which is what
                    # that guard is for: `invoice_open_paise` reads the key off
                    # the row, so a wrong name is a silent zero, not an error.
                    found = (db.table("client_sales_invoices").select(
                        "id, invoice_no, total_paise, paid_paise, credited_paise, "
                        "debit_note_paise, outstanding_paise, customer_id")
                        .eq("firm_id", firm_id).in_("id", chunk).execute().data) or []
                    for r in found:
                        out[(kind, str(r["id"]))] = {
                            "outstanding_paise": invoice_open_paise(r),
                            "document_no": r.get("invoice_no"),
                            "party_kind": "customer",
                            "party_id": (str(r["customer_id"]) if r.get("customer_id") else None),
                        }
                else:
                    found = (db.table("purchase_bills").select(
                        "id, bill_no, net_payable_paise, paid_paise, credit_note_paise, "
                        "debited_paise, outstanding_paise, vendor_id")
                        .eq("firm_id", firm_id).in_("id", chunk).execute().data) or []
                    for r in found:
                        out[(kind, str(r["id"]))] = {
                            "outstanding_paise": bill_open_paise(r),
                            "document_no": r.get("bill_no"),
                            "party_kind": "vendor",
                            "party_id": (str(r["vendor_id"]) if r.get("vendor_id") else None),
                        }
            except Exception as e:                            # pragma: no cover
                # Never fatal: a document that cannot be read costs those lines
                # their settlement checks, not the whole list — the bargain
                # BankEntryService._attach_matched_documents already makes. The
                # difference is that here it is REPORTED rather than silent,
                # because a settlement check that did not run looks exactly
                # like one that passed.
                capture_soft_failure(e, operation="bank_exceptions.matched_document",
                                     entity_type=kind)
                complete = False

    # The document rows carry a party ID, and `_weak_match` asks whether the
    # party's NAME appears in the narration. Resolved here, chunked, one query
    # per party type — never one per document. Dropping it instead would make
    # that rule fire on every inexact amount, which is the opposite of a list a
    # partner can trust.
    wanted_parties: dict[str, set[str]] = {}
    for meta in out.values():
        if meta.get("party_id"):
            wanted_parties.setdefault(meta["party_kind"], set()).add(meta["party_id"])
    names: dict[tuple[str, str], str] = {}
    for kind, ids in wanted_parties.items():
        ordered = sorted(ids)
        for i in range(0, len(ordered), 200):
            chunk = ordered[i:i + 200]
            try:
                # EACH TABLE IS WRITTEN OUT AT ITS OWN CALL, and the branch is
                # the price of that. `tests/test_backend_columns_exist_pg.py`
                # reads these references as TEXT, so a `db.table(table)` with a
                # variable is invisible to it and a column renamed out from
                # under this would be found in production rather than in CI —
                # BankEntryService._document_numbers records the same reasoning
                # and it is why the first draft of this raised that guard's
                # unreadable-reference budget instead of obeying it.
                if kind == "customer":
                    rows = (db.table("customers").select("id, name")
                            .eq("firm_id", firm_id).in_("id", chunk).execute().data) or []
                else:
                    rows = (db.table("vendors").select("id, name")
                            .eq("firm_id", firm_id).in_("id", chunk).execute().data) or []
            except Exception as e:                            # pragma: no cover
                capture_soft_failure(e, operation="bank_exceptions.party_name",
                                     entity_type=kind)
                complete = False
                continue
            for r in rows:
                if r.get("name"):
                    names[(kind, str(r["id"]))] = str(r["name"])
    for meta in out.values():
        meta["party_name"] = names.get((meta.get("party_kind"), meta.get("party_id")))
    return out, complete


def review_list(db, firm_id: str, client_id: str, *, from_date: str, to_date: str,
                bank_account_id: Optional[str] = None,
                policy: Optional[rules.ExceptionPolicy] = None,
                today: Optional[date] = None) -> dict:
    """The flagged lines of one period, worst first, with what could not be asked.

    `from_date` and `to_date` are REQUIRED and keyword-only — see the module
    docstring on why an optional period is the defect rather than a convenience.
    """
    policy = policy or rules.ExceptionPolicy()
    today = today or ist_today()

    window = _period_rows(db, firm_id, client_id, from_date=from_date, to_date=to_date,
                          margin_days=policy.duplicate_window_days,
                          bank_account_id=bank_account_id)
    # The margin is for SIBLINGS only. A line outside the period is never a
    # subject, or asking about June reports May's lines back.
    subjects = [t for t in window
                if t.get("match_status") == "posted"
                and from_date <= str(t.get("transaction_date"))[:10] <= to_date]

    siblings = tuple(
        (str(t.get("id")), str(t.get("transaction_date"))[:10],
         max(int(t.get("debit_paise") or 0), int(t.get("credit_paise") or 0)),
         t.get("payee_name"))
        for t in window)

    documents, documents_complete = _matched_documents(db, firm_id, subjects)

    payees = {str(t["payee_name"]).strip() for t in subjects
              if (t.get("payee_name") or "").strip()}
    accounts = {str(t["account_id"]) for t in subjects if t.get("account_id")}
    history_empty = False
    try:
        history_empty = not _any_earlier_line(
            db, firm_id, client_id, before=from_date, bank_account_id=bank_account_id)
        if history_empty:
            seen_payees, seen_accounts = set(), set()
            payees_complete = accounts_complete = True
        else:
            seen_payees, payees_complete = _seen_before(
                db, firm_id, client_id, column="payee_name", wanted=payees,
                before=from_date, bank_account_id=bank_account_id)
            seen_accounts, accounts_complete = _seen_before(
                db, firm_id, client_id, column="account_id", wanted=accounts,
                before=from_date, bank_account_id=bank_account_id)
    except Exception as e:                                    # pragma: no cover
        capture_soft_failure(e, operation="bank_exceptions.history")
        seen_payees, seen_accounts = set(), set()
        payees_complete = accounts_complete = False
    history_complete = payees_complete and accounts_complete

    # A rule is WITHHELD by being given nothing it can fire on, never by being
    # taken out of RULES: the domain module owns which rules exist, and a
    # service that filtered the tuple would be a second place deciding.
    # `known_*` sets carrying every value in the period make both history rules
    # answer None for every line, which is exactly "not applied".
    if not history_complete or history_empty:
        seen_payees = {p.lower() for p in payees}
        seen_accounts = set(accounts)

    flagged: list[dict] = []
    for t in subjects:
        doc = documents.get((t.get("matched_entity_type"), str(t.get("matched_entity_id"))))
        ctx = rules.TxnContext(
            known_payees=frozenset(p.lower() for p in seen_payees),
            known_accounts=frozenset(seen_accounts),
            matched_outstanding_paise=(doc or {}).get("outstanding_paise"),
            matched_document_no=(doc or {}).get("document_no"),
            matched_party_name=(doc or {}).get("party_name"),
            siblings=siblings,
        )
        found = rules.evaluate(t, ctx, policy, today)
        if not found:
            continue
        flagged.append({
            "transaction_id": str(t.get("id")),
            "transaction_date": str(t.get("transaction_date"))[:10],
            "description": t.get("description"),
            "payee_name": t.get("payee_name"),
            "debit_paise": int(t.get("debit_paise") or 0),
            "credit_paise": int(t.get("credit_paise") or 0),
            "matched_document_no": (doc or {}).get("document_no"),
            "exceptions": [
                # `blocking` travels so the screen can show that a rule WOULD
                # stop this if anything did — it is never acted on. The domain
                # module's docstring is the authority on that distinction.
                {"code": e.code, "severity": e.severity, "message": e.message,
                 "blocking": e.blocking, "detail": e.detail}
                for e in found
            ],
        })

    # Worst first, and a stable order under it so the list does not reshuffle
    # between two reads of the same period.
    flagged.sort(key=lambda r: (
        rules.SEVERITY_ORDER.get(r["exceptions"][0]["severity"], 9),
        r["transaction_date"], r["transaction_id"]))

    gaps = []
    if history_empty:
        gaps.append({"code": GAP_HISTORY_EMPTY,
                     "message": GAP_SENTENCES[GAP_HISTORY_EMPTY]})
    if not history_complete:
        gaps.append({"code": GAP_HISTORY_INCOMPLETE,
                     "message": GAP_SENTENCES[GAP_HISTORY_INCOMPLETE]})
    if not documents_complete:
        gaps.append({"code": GAP_DOCUMENTS_UNREAD,
                     "message": GAP_SENTENCES[GAP_DOCUMENTS_UNREAD]})

    return {
        "from_date": from_date,
        "to_date": to_date,
        "bank_account_id": bank_account_id,
        "reviewed_count": len(subjects),
        "flagged": flagged,
        "gaps": gaps,
        # The thresholds this answer was computed at. Materiality is a
        # judgement, so a list that does not say what it was measured against
        # cannot be argued with — the module's own point about thresholds.
        "policy": {
            "materiality_paise": policy.materiality_paise,
            "settlement_tolerance_paise": policy.settlement_tolerance_paise,
            "settlement_block_paise": policy.settlement_block_paise,
            "cash_withdrawal_paise": policy.cash_withdrawal_paise,
            "duplicate_window_days": policy.duplicate_window_days,
        },
    }
