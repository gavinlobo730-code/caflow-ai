"""What the ledger holds about a client's fixed assets, fetched once for both readers of the register (POST-A-110).

`domain/fixed_assets/integrity.register_findings` is pure: rows in, findings out. Two of its checks ask the LEDGER about the
register (a disposed asset with no disposal entry, an acquisition entry with no asset) and only a caller has a database, so this
is the one place that reads it. `GET /api/fixed-assets/register-integrity` and the nightly / Verify Books sweep
(`reconciliation_service.check_fixed_asset_register`) both call it, because two copies of a fetch over the same register are how
a screen and a sweep come to disagree about the same client (the module the rule lives in says the same of the rule).

LIVE MEANS: not deleted, not reversed (`is_reversed`, set on the original when a reversal posts) and not itself a reversal
(`reversal_of`). A reversed acquisition is the asset-delete path working; a reversed disposal is what leaves a disposed asset with
nothing behind it, which is the finding.
"""
from __future__ import annotations

from core.db_paging import fetch_all, fetch_all_in
from domain.accounting import journal_source as JS
from domain.fixed_assets.integrity import LedgerLinks


def _live_entries(db, firm_id: str, client_id: str, source_type: str):
    return (db.table("journal_entries").select("id, source_id, reference_no, entry_date")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("source_type", source_type)
            .is_("deleted_at", "null").eq("is_reversed", False).is_("reversal_of", "null"))


def fetch_ledger_links(db, firm_id: str, client_id: str, assets) -> LedgerLinks:
    """The ledger side of one client's register. `assets` are the register rows (live, `is_disposed` and `id` selected)."""
    disposed_ids = [str(a["id"]) for a in assets if a.get("is_disposed") and a.get("id")]
    disposal_entries = fetch_all_in(
        lambda: _live_entries(db, firm_id, client_id, JS.ASSET_DISPOSAL),
        "source_id", disposed_ids, label="fixed_assets.disposal_entries") if disposed_ids else []
    acquisitions = fetch_all(
        lambda: _live_entries(db, firm_id, client_id, JS.FIXED_ASSET),
        label="fixed_assets.acquisition_entries")
    return LedgerLinks(
        disposal_journalled_asset_ids=frozenset(str(e["source_id"]) for e in disposal_entries if e.get("source_id")),
        acquisition_journals=tuple(
            {"id": e.get("id"), "source_id": e.get("source_id"),
             "reference_no": e.get("reference_no"), "entry_date": e.get("entry_date")}
            for e in acquisitions),
    )
