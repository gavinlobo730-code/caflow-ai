"""Voucher import — fetch the inputs, post what the plan called new (ACC-17).

`domain/accounting/voucher_import` is the rule and decides what each voucher IS;
this fetches the chart, the entries that already hold a voucher number and the
period answers, hands them to `plan`, and posts the new vouchers.

THERE IS NO WRITE PATH IN THIS FILE. Every voucher is posted by
`manual_journal_service.create`, which is `phase2_journal_service._create_journal`
— the one posting kernel — so the double-entry assertion, the closure check, the
`(client, reference_no, entry_date)` dedupe and the atomic header-and-lines RPC all
apply exactly as they do to a journal typed on the editor. A posted entry is never
rewritten, and this never edits one: a voucher that is already recorded is skipped.
`tests/test_voucher_import.py` asserts the module does not name `journal_entries`
or `journal_lines` as a write target.

BY NAMED VOUCHER, NOT ALL OR NOTHING. A voucher is atomic (one RPC writes the
header and every line). The FILE is not, because posting is one voucher per kernel
call: a voucher the kernel refuses — a period closed between the plan and the
post, say — is reported under its own number and the vouchers around it still
land, which is what "the 197 good vouchers post and the 3 bad ones are listed"
means. The plan has already refused everything it can foresee, so a refusal here
is the rare one.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.accounting import voucher_import as vi
from services import period_lock_service
from services.period_validation_service import period_validation_service

_logger = logging.getLogger("caflow.voucher_import")

_CHUNK = 100

STATUSES = ("draft", "posted")


def _chart(db, firm_id: str, client_id: str) -> list[dict]:
    """The accounts a voucher of this client may use: its own, and the firm-level
    ones every client of the firm shares (`client_id` NULL — migration 057).

    Two readable queries rather than one `.or_()` with the client interpolated into
    a string: that idiom is invisible to the backend column scan and its budget
    says not to grow it.
    """
    own = fetch_all(
        lambda: db.table("chart_of_accounts")
        .select("id, account_code, account_name, account_type, is_active, client_id")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="voucher_import_chart_client")
    shared = fetch_all(
        lambda: db.table("chart_of_accounts")
        .select("id, account_code, account_name, account_type, is_active, client_id")
        .eq("firm_id", firm_id).is_("client_id", "null"),
        key="id", label="voucher_import_chart_firm")
    seen: set[str] = set()
    out: list[dict] = []
    for a in own + shared:
        if a.get("id") and a["id"] not in seen:
            seen.add(a["id"])
            out.append(a)
    return out


def _existing(db, firm_id: str, client_id: str, references: list[str]) -> dict[str, list[dict]]:
    """Live entries of this client that already carry one of these numbers, with
    their totals — what the plan compares a re-upload against.

    A soft-deleted entry is not live: the CA discarded it and its number is free.
    A REVERSED one still is, which is why `is_reversed` travels.
    """
    entries: list[dict] = []
    for i in range(0, len(references), _CHUNK):
        chunk = references[i:i + _CHUNK]
        entries.extend(fetch_all(
            lambda chunk=chunk: db.table("journal_entries")
            .select("id, reference_no, entry_date, entry_type, is_reversed, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("reference_no", chunk).is_("deleted_at", "null"),
            key="id", label="voucher_import_existing"))
    totals: dict[str, int] = {}
    ids = [e["id"] for e in entries if e.get("id")]
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i:i + _CHUNK]
        for line in fetch_all(
                lambda chunk=chunk: db.table("journal_lines")
                .select("id, journal_entry_id, debit_paise")
                .in_("journal_entry_id", chunk),
                key="id", label="voucher_import_existing_lines"):
            eid = line.get("journal_entry_id")
            totals[eid] = totals.get(eid, 0) + int(line.get("debit_paise") or 0)
    out: dict[str, list[dict]] = {}
    for e in entries:
        out.setdefault(e.get("reference_no") or "", []).append({
            "id": e.get("id"), "entry_date": e.get("entry_date"),
            "entry_type": e.get("entry_type"),
            "is_reversed": bool(e.get("is_reversed")),
            "total_paise": totals.get(e.get("id"), 0),
        })
    return out


def _period_asker(db, firm_id: str, client_id: str):
    """The two questions `manual_journal_service.create` asks of a POSTED entry,
    as one callable the plan can put to every distinct date once.

    The firm's locked financial year, then the client's own lock — a finalised
    year or a return filed for the date, because a manual voucher can move any
    account including the tax ledgers. Both are memoised per date or year for the
    open case only, so a thousand legs on twelve dates ask twelve questions; a
    closed period is never remembered and is reported as accurately as before.
    """
    fy_cache: dict = {}
    lock_cache: dict = {}

    def ask(date_iso: str) -> Optional[str]:
        try:
            period_validation_service.validate_posting_date_cached(firm_id, date_iso, fy_cache)
        except HTTPException as e:
            return str(e.detail)
        except ValueError as e:
            return str(e)
        return period_lock_service.lock_reason(db, firm_id, client_id, date_iso, lock_cache)

    return ask


def _refusal_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        d = exc.detail
        return str(d.get("message") if isinstance(d, dict) else d)
    return str(exc)


def import_vouchers(db, firm_id: str, client_id: str, *, legs: list, status: str,
                    actor_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Judge every voucher, post the new ones, and say what became of each.

    `status` is REQUIRED and has no default: `posted` puts the vouchers on the
    books now and `draft` leaves them off-books for review and approval, and an
    import that did one by omission is the shape this codebase keeps refusing.
    `actor_id` is the INTERNAL users.id (`journal_entries.created_by` FKs to it).
    """
    if status not in STATUSES:
        raise HTTPException(status_code=422, detail="status must be 'draft' or 'posted'.")
    if not legs:
        raise HTTPException(status_code=422, detail="The file has no rows to import.")
    if len(legs) > vi.MAX_LEGS:
        raise HTTPException(
            status_code=422,
            detail=(f"{len(legs)} lines is more than one import takes ({vi.MAX_LEGS}). "
                    f"Split the file by month and upload the parts — a re-upload "
                    f"skips every voucher that is already in."))
    numbers = {(l.voucher_no or "").strip() for l in legs}
    numbers.discard("")
    if len(numbers) > vi.MAX_VOUCHERS:
        raise HTTPException(
            status_code=422,
            detail=(f"{len(numbers)} vouchers in one request is more than posts safely "
                    f"({vi.MAX_VOUCHERS}). The import screen sends them in smaller "
                    f"batches; a script should do the same."))

    chart = _chart(db, firm_id, client_id)
    existing = _existing(db, firm_id, client_id, sorted(numbers))
    # A DRAFT is off-books and is checked when it is approved, so only a voucher
    # going on the books now is asked about its period — manual_journal_service.create's
    # own rule, kept so the two doors cannot disagree about when a lock applies.
    verdicts = vi.plan(
        legs, chart, existing,
        period_problem=_period_asker(db, firm_id, client_id) if status == "posted" else None)

    new = [v for v in verdicts if v.status == vi.NEW]
    posted_ids: dict[str, str] = {}
    failed: dict[str, str] = {}
    if new and not dry_run:
        from core.exceptions import document_failure_detail
        from core.observability import capture_posting_failure
        from services.manual_journal_service import manual_journal_service
        for v in new:
            try:
                made = manual_journal_service.create(db, firm_id, {
                    "client_id": client_id,
                    "entry_date": v.entry_date,
                    "reference_no": v.voucher_no,
                    "narration": v.narration,
                    "entry_type": v.entry_type,
                    "status": status,
                    "lines": [dict(l) for l in v.lines],
                }, actor_id=actor_id)
                posted_ids[v.voucher_no] = str(made.get("id") or "")
            except (HTTPException, ValueError) as e:
                failed[v.voucher_no] = _refusal_text(e)
            except Exception as e:                                  # noqa: BLE001
                capture_posting_failure(
                    e, operation="voucher_import.post", firm_id=firm_id,
                    client_id=client_id, reference_no=v.voucher_no,
                    entry_date=v.entry_date)
                failed[v.voucher_no] = document_failure_detail(e, action="post this voucher")

    results = []
    final: list[vi.VoucherVerdict] = []
    for v in verdicts:
        problems = list(v.problems)
        shown = v.status
        if v.voucher_no in failed:
            shown, problems = vi.REJECTED, [failed[v.voucher_no]]
            v = vi.VoucherVerdict(voucher_no=v.voucher_no, rows=v.rows, status=vi.REJECTED,
                                  problems=tuple(problems))
        final.append(v)
        results.append({
            "voucher_no": v.voucher_no,
            "rows": list(v.rows),
            "status": "would_create" if dry_run and shown == vi.NEW else shown,
            "problems": problems,
            "entry_date": v.entry_date,
            "entry_type": v.entry_type,
            "total_paise": v.total_paise,
            "id": posted_ids.get(v.voucher_no) or v.existing_id,
        })
    summary = vi.summarise(final)

    return {
        "status": status,
        "dry_run": dry_run,
        "vouchers": summary.vouchers,
        "created": 0 if dry_run else summary.new,
        "would_create": summary.new if dry_run else 0,
        "already_recorded": summary.already_recorded,
        "rejected": summary.rejected,
        "created_paise": 0 if dry_run else summary.new_paise,
        "would_create_paise": summary.new_paise if dry_run else 0,
        "results": results,
    }
