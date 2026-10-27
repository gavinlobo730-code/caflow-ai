"""Which ledger an intangible asset's accumulated amortisation belongs in, and whether this practice's chart can hold it there (POST-A-345).

ONE PREDICATE, READ BY EVERY WRITER. An asset is pointed at the Accumulated Amortisation ledger in three places: at creation
(`routers.fixed_assets.create_asset`), when work in progress is capitalised (`services.cwip_service`) and when a Partner posts the
reclassification of what is already in the shared ledger (`services.amortisation_reclass_service`). They must agree on WHICH assets
belong there, or the same asset is routed one way by the form that created it and another by the screen that moves it, and a firm
that mapped Computers & Software to the intangible line gets half its assets in each place. So the question is asked here, once:

    an asset belongs in the Accumulated Amortisation ledger when its category's COST ledger and that ledger classify to the SAME
    Schedule III line, by the account's own subtype and the CA's own mapping (the same classifier the balance sheet uses).

It is the line, not the category's name: the standard chart's Intangible Assets ledger is on the intangible line, but a chart whose
cost ledger is on the tangible line (migration 093's older chart seeded it as a Fixed Asset) answers "no", and the asset stays in the
shared ledger, where its cost is. An amortisation credited to the intangible line against a cost on the tangible line would create
the very mismatch this change removes. Where the answer is no, the reason comes back in words, because a screen that offers nothing
must say why.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.db_paging import fetch_all
from domain.fixed_assets.asset_ledger import OWN_ACCUMULATED_PATTERN, SHARED_ACCUMULATED_PATTERN, ledger_pattern
from domain.fixed_assets.integrity import AccumulatedLedgerFacts
from domain.reporting.year_end_lines import schedule_line_for_account


def line_of(row: dict) -> str:
    """The Schedule III line a chart row presents on: its subtype, outranked by the CA's own mapping (`classify`'s order)."""
    return schedule_line_for_account(row.get("account_type") or "", row.get("account_subtype"), row.get("schedule_iii_mapping"))


@dataclass(frozen=True)
class OwnLedger:
    row: Optional[dict]
    problem: Optional[str]


def asset_ledgers_query(db, firm_id: str, client_id: str):
    """The ACTIVE asset ledgers of the practice (firm-level, or this client's own), not yet run. The columns are those
    `line_of` needs to say which Schedule III line a ledger presents on. Written as a literal here, in the one place that builds this
    query, so that `tests/test_backend_columns_exist_pg.py` reads them against the schema: a column list held in a constant is a
    reference that scan cannot see (and the budget it keeps counts the ones it cannot)."""
    return (db.table("chart_of_accounts")
            .select("id, account_code, account_name, account_type, account_subtype, schedule_iii_mapping, is_active, client_id")
            .eq("firm_id", firm_id)
            .or_(f"client_id.eq.{client_id},client_id.is.null")
            .eq("is_active", True).eq("account_type", "Asset"))


def _chart_rows_like(db, firm_id: str, client_id: str, pattern: str) -> list[dict]:
    """ACTIVE asset ledgers of the practice (firm-level, or this client's own) whose name matches, ordered so the answer is stable."""
    rows = asset_ledgers_query(db, firm_id, client_id).ilike("account_name", pattern).execute().data or []
    return sorted(rows, key=lambda r: (str(r.get("account_code") or ""), str(r.get("id") or "")))


def chart_row(db, firm_id: str, account_id: str) -> Optional[dict]:
    rows = (db.table("chart_of_accounts")
            .select("id, account_code, account_name, account_type, account_subtype, schedule_iii_mapping, is_active, client_id")
            .eq("id", account_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def own_ledger(db, firm_id: str, client_id: str) -> OwnLedger:
    """The practice's Accumulated Amortisation ledger, or the reason there is not exactly one.

    EXACTLY ONE, because `_find_account` is an unordered `limit(1)` lookup: a client-level ledger and a firm-level one of the same
    name would be told apart by whichever Postgres returned first, and an asset's history would sit in either."""
    rows = _chart_rows_like(db, firm_id, client_id, OWN_ACCUMULATED_PATTERN)
    if not rows:
        return OwnLedger(None, "This practice's chart has no Accumulated Amortisation ledger, so an intangible asset's amortisation cannot "
                               "be kept apart from the tangible assets'. Add an active asset ledger named Accumulated Amortisation to "
                               "the chart of accounts and this screen will offer the move.")
    if len(rows) > 1:
        names = ", ".join(f"{r.get('account_code')} {r.get('account_name')}" for r in rows)
        return OwnLedger(None, f"More than one active ledger matches Accumulated Amortisation ({names}). Leave exactly one active, so "
                               "that an asset's history is always in the same place.")
    return OwnLedger(rows[0], None)


def shared_ledger(db, firm_id: str, client_id: str) -> Optional[dict]:
    """The shared Accumulated Depreciation ledger the journals fall back to (`Phase2JournalService._find_account`'s answer), or None."""
    from services.phase2_journal_service import phase2_journal_service
    try:
        account_id = phase2_journal_service._find_account(db, firm_id, client_id, SHARED_ACCUMULATED_PATTERN)
    except ValueError:
        return None
    return chart_row(db, firm_id, account_id)


def cost_ledger(db, firm_id: str, client_id: str, category: Optional[str]) -> Optional[dict]:
    """The ledger an asset of this category is debited to on acquisition (asset_ledger's table), or None where the chart has none."""
    from services.phase2_journal_service import phase2_journal_service
    try:
        account_id = phase2_journal_service._find_account(db, firm_id, client_id, ledger_pattern(category))
    except ValueError:
        return None
    return chart_row(db, firm_id, account_id)


def belongs_in_own_ledger(own: dict, cost: Optional[dict]) -> tuple[bool, str]:
    """Whether an asset whose cost sits in `cost` belongs in the `own` ledger, and if not, why in words."""
    if cost is None:
        return False, "its cost ledger could not be found on the chart"
    if line_of(cost) == line_of(own):
        return True, ""
    return False, (f"its cost ledger ({cost.get('account_name')}) presents on a different Schedule III line from the Accumulated "
                   f"Amortisation ledger ({own.get('account_name')}), and amortisation on one line against a cost on the other is "
                   "the mismatch this change removes")


def birth_pointer(db, firm_id: str, client_id: str, category: Optional[str]) -> Optional[str]:
    """The ledger id a NEW asset of this category should be created pointing at, or None for the shared ledger (the answer for every
    category whose cost is not on the intangible line, and for a chart that cannot hold the pointer). Never raises: a chart that cannot
    answer leaves the asset where every asset has always been, which is the safe direction."""
    try:
        own = own_ledger(db, firm_id, client_id)
        if own.row is None:
            return None
        shared = shared_ledger(db, firm_id, client_id)
        if shared is not None and line_of(shared) == line_of(own.row):
            return None            # the shared ledger is already on that line: nothing to separate
        ok, _why = belongs_in_own_ledger(own.row, cost_ledger(db, firm_id, client_id, category))
        return own.row["id"] if ok else None
    except Exception as exc:                                 # noqa: BLE001 — see the docstring; REPORTED, never silent
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="fixed_asset_accumulated_ledger.birth_pointer",
                             firm_id=firm_id, client_id=client_id, category=category)
        return None


def birth_pointer_fields(db, firm_id: str, client_id: str, category: Optional[str]) -> dict:
    """`{"accumulated_account_id": <ledger id>}` for a NEW asset whose accumulated amortisation belongs in the Accumulated Amortisation
    ledger, and `{}` for every other asset.

    EMPTY means the key is not in the insert at all, not that it is NULL: an insert that names a column the table does not yet have is
    refused whole by PostgREST, and that is the deploy-order risk of every writer of a new column. Both places an asset is born (the
    register's create form and the capitalisation of work in progress) spread this into their insert, so neither can disagree with the
    other, or with the reclassification, about which assets belong there."""
    pointer = birth_pointer(db, firm_id, client_id, category)
    return {"accumulated_account_id": pointer} if pointer else {}


def ledger_monthly_credit(db, firm_id: str, client_id: str, account_id: str) -> Optional[list]:
    """THIS CLIENT's net credit of a ledger month by month, [(period_month, credit minus debit), ...], from the pre-aggregated monthly
    rows (`account_period_balances`, migrations 227/228) and not from the ledger's lines: a few rows per ledger, whatever the volume.
    None where it could not be read."""
    try:
        rows = fetch_all(
            lambda: (db.table("account_period_balances").select("debit_paise,credit_paise,period_month")
                     .eq("firm_id", firm_id).eq("client_id", client_id).eq("account_id", account_id)),
            label="fixed_asset_accumulated_ledger.balance", key="period_month")
    except Exception as exc:                                               # noqa: BLE001 — reported; a refusal follows from None
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="fixed_asset_accumulated_ledger.ledger_monthly_credit",
                             firm_id=firm_id, client_id=client_id, account_id=account_id)
        return None
    return [(str(r["period_month"])[:10], int(r.get("credit_paise") or 0) - int(r.get("debit_paise") or 0)) for r in rows]


def balance_as_at(monthly: Optional[list], iso: str) -> Optional[int]:
    """The credit balance as at a date, from `ledger_monthly_credit`'s months: every month up to and including the date's own. A month
    end is exact; a date inside a month takes that whole month, which is only used for today."""
    if monthly is None:
        return None
    limit = str(iso)[:7] + "-01"
    return sum(net for month, net in monthly if month <= limit)


def ledger_credit_balance(db, firm_id: str, client_id: str, account_id: str, as_at: Optional[str] = None) -> Optional[int]:
    """THIS CLIENT's credit balance of a ledger (credit minus debit, so a credit balance is positive), all-time or as at a date. None
    where it could not be read."""
    monthly = ledger_monthly_credit(db, firm_id, client_id, account_id)
    if monthly is None:
        return None
    return sum(net for _m, net in monthly) if as_at is None else balance_as_at(monthly, as_at)


def fetch_facts(db, firm_id: str, client_id: str, assets) -> Optional[AccumulatedLedgerFacts]:
    """What the two register checks about the Accumulated Amortisation ledger need from the chart and the ledger, for ONE client, or None
    where it could not be worked out (the checks are then not asked, which is not the same as asking and being told "clean").

    `assets` are the client's live register rows (`id`, `is_disposed`, `asset_category` and `accumulated_account_id` selected). The chart
    is read once per DISTINCT category, so the cost is the size of the category list and not of the register."""
    try:
        own = own_ledger(db, firm_id, client_id)
        if own.row is None:
            return AccumulatedLedgerFacts(own_ledger_id=None, own_ledger_credit_paise=None, belongs_asset_ids=frozenset())
        shared = shared_ledger(db, firm_id, client_id)
        belongs: set = set()
        if shared is None or line_of(shared) != line_of(own.row):
            by_category: dict = {}
            for a in assets:
                if a.get("is_disposed") or a.get("accumulated_account_id"):
                    continue
                category = a.get("asset_category")
                if category not in by_category:
                    by_category[category] = belongs_in_own_ledger(own.row, cost_ledger(db, firm_id, client_id, category))[0]
                if by_category[category]:
                    belongs.add(str(a["id"]))
        return AccumulatedLedgerFacts(
            own_ledger_id=str(own.row["id"]),
            own_ledger_credit_paise=ledger_credit_balance(db, firm_id, client_id, own.row["id"]),
            belongs_asset_ids=frozenset(belongs))
    except Exception as exc:                                 # noqa: BLE001 — REPORTED; the two checks are then not asked
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="fixed_asset_accumulated_ledger.fetch_facts", firm_id=firm_id, client_id=client_id)
        return None
