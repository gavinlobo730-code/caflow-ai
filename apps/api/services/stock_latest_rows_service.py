"""Each stock item's latest stock-ledger row, asked of the database in ONE question (POST-A-435).

The stock register shows these rows and the nightly cache-drift check compares the catalogue's cached figures against them, so both ask
here and nowhere else. The rule (newest `created_at`, then the larger `id`) is `public.stock_latest_rows` (migration 588) and its twin
`domain/inventory/latest_rows`, held identical by `tests/test_stock_latest_rows_parity_pg.py`.

It runs on the privileged client, naming the firm and the client (the function's grant is service_role's alone; a route asserts the
caller's access before it asks). The function returns ONE jsonb value, an array, because PostgREST cuts a set of rows at db-max-rows
without a word; an answer that is not an array RAISES, because a register of zeros reads as nothing in stock. A database double with no
function to call is answered by the twin over the client's rows.
"""
from __future__ import annotations

from core.db_paging import fetch_all
from domain.inventory.latest_rows import latest_rows


def latest_rows_for(db, firm_id: str, client_id: str, item_ids) -> dict[str, dict]:
    """{item id: its latest row} for the asked items that have a row of this firm and client; an item with none is absent."""
    items = sorted({str(i) for i in (item_ids or []) if i is not None})
    if not items:
        return {}
    from core.db_provider import privileged_for
    client = privileged_for(db)
    if hasattr(client, "rpc"):
        data = getattr(client.rpc("stock_latest_rows", {"p_firm": firm_id, "p_client": client_id, "p_items": items}).execute(),
                       "data", None)
        if not isinstance(data, list):
            raise ValueError(f"stock_latest_rows returned {type(data).__name__}, not an array of rows")
        return {str(r["service_catalogue_id"]): r for r in data if isinstance(r, dict) and r.get("service_catalogue_id") is not None}
    rows = fetch_all(lambda: (client.table("inventory_stock_ledger")
                              .select("id, firm_id, client_id, service_catalogue_id, created_at, running_qty_units, "
                                      "running_avg_cost_paise, running_value_paise")
                              .eq("firm_id", firm_id).eq("client_id", client_id)),
                     label="inventory.latest_rows_twin")
    return latest_rows(rows, firm_id, client_id, items)
