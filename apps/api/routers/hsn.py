"""HSN/SAC smart lookup — search the FIRM'S OWN library (migration 179) merged
with the firm's own usage history (migration 101).

Architecture note (HSN/SAC redesign): this endpoint used to merge in
`public.hsn_master`, a Caflow-shipped global code list. It no longer does —
Caflow does not expose a shared HSN/SAC master to users. `_fetch_library_rows`
below reads only `firm_hsn_library`, so every result this endpoint returns is
a code the firm itself added to its own library. `hsn_master` is retained
elsewhere purely as an internal, non-exposed implementation detail and is not
read by this file.

CGST Rule 46(g): HSN/SAC is a mandatory tax-invoice field. This endpoint only
reduces manual entry — the returned rate is a *pre-fill hint*, never used in any
GST or journal computation without the existing CA-review path. The CA can always
override the code, rate, description and unit.
"""
import asyncio
import os
import re
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from models.common import api_response
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.hsn")

router = APIRouter(prefix="/api/hsn", tags=["hsn"])

# Keep only characters that are safe inside a PostgREST or()/ilike filter. HSN
# codes are digits; descriptions are words — so alphanumerics + space cover every
# real query while stripping commas/parens/dots that would break the or() string.
_SAFE_Q = re.compile(r"[^A-Za-z0-9 ]+")


def _pct_to_bps(pct) -> Optional[int]:
    """Convert a NUMERIC gst_rate_pct (e.g. 18.00) to integer basis points (1800).
    NULL (multiple/again-review rates) stays None. Integer bps mirrors the history
    table's gst_rate_bps so the frontend can treat every source identically."""
    if pct is None:
        return None
    try:
        return int(round(float(pct) * 100))
    except (TypeError, ValueError):
        return None


def _rank_library_rows(term: str, rows: list[dict]) -> list[dict]:
    """Relevance-rank a firm's own library rows for a search term.

    PostgREST can only order by a column, so a query like "audit" returns
    hits in bare hsn_code order — burying the obvious match. We re-rank in
    Python (the candidate set is already capped at limit*3) so the best match
    surfaces first, mirroring how a CA scans a code list:

      0 exact code           (typed "998212" → that code)
      1 code prefix          (typed "9982"  → codes starting 9982)
      2 code substring
      3 description prefix    (typed "audit" → "Auditing …")
      4 description substring (typed "audit" → "Financial auditING services")

    No keyword bucket: unlike the retired global master, a firm's own
    library is small and every row's description was written or chosen by
    the firm itself, so plain code/description matching is enough.

    Ties break by shorter code then code text, EXCEPT a row with a concrete
    GST rate always sorts before a same-bucket row with no rate. Pure +
    deterministic so it is unit-testable without a database.
    """
    t = (term or "").strip().lower()

    def rank(r: dict) -> tuple:
        code = (r.get("hsn_code") or "").lower()
        desc = (r.get("description") or "").lower()
        if code == t:
            bucket = 0
        elif t and code.startswith(t):
            bucket = 1
        elif t and t in code:
            bucket = 2
        elif t and desc.startswith(t):
            bucket = 3
        elif t and t in desc:
            bucket = 4
        else:
            bucket = 5
        has_no_rate = 0 if r.get("gst_rate_pct") is not None else 1
        return (bucket, has_no_rate, len(code), code)

    return sorted(rows, key=rank)


@router.get("/search")
async def search_hsn(
    q: str = Query("", description="HSN/SAC code or description fragment"),
    type: Optional[str] = Query(None, description="Filter: 'goods' or 'services'"),
    client_id: Optional[str] = Query(None, description="Merge this client's usage history first"),
    limit: int = Query(15, ge=1, le=50),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Search HSN/SAC by code OR description. Results are the firm's own recently/
    frequently used codes first (rate-bearing, from history), then the rest of
    the firm's own library — de-duped by code. Each row carries a pre-fill
    hint: description, GST rate (bps) and unit (UQC)."""
    try:
        term = _SAFE_Q.sub(" ", (q or "").strip()).strip()
        if _USE_MOCK:
            return api_response(True, [])

        # Empty query with a client scope = "recent codes" affordance: show the
        # firm's most recently used codes for this client so the picker is useful
        # before the CA types anything. Without a client scope there is nothing to
        # recommend, so stay empty (never full-load the library).
        if not term and not client_id:
            return api_response(True, [])

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id", "")

        def _fetch_history_rows() -> list[dict]:
            if not client_id:
                return []
            hq = (
                db.table("hsn_sac_preferences")
                .select("hsn_sac,sample_description,gst_rate_bps,use_count,last_used_at")
                .eq("firm_id", firm_id)
                .eq("client_id", client_id)
                .order("last_used_at", desc=True)
                .order("use_count", desc=True)
                .limit(limit * 2)
            )
            if term:
                hq = hq.or_(f"hsn_sac.ilike.{term}*,description_key.ilike.*{term}*")
            return hq.execute().data or []

        def _fetch_library_rows() -> list[dict]:
            if not term:
                return []
            lq = (
                db.table("firm_hsn_library")
                .select("hsn_code,description,gst_rate_pct,hsn_type,uqc")
                .eq("firm_id", firm_id)
                .eq("is_active", True)
                .or_(f"hsn_code.ilike.{term}*,description.ilike.*{term}*")
                .order("hsn_code")
                .limit(limit * 3)
            )
            if type in ("goods", "services"):
                lq = lq.eq("hsn_type", type)
            return lq.execute().data or []

        # The history and library reads are independent — profiling this endpoint
        # showed they ran back-to-back (sequential round trips) even though
        # nothing depends on either's result, which was the dominant cost on the
        # common path: a client with little/no history yet (or any first-time
        # search term) always fell through past the history query to the library
        # query, paying BOTH round trips one after another. Firing them
        # concurrently (each Supabase call is blocking, so each runs in its own
        # thread) roughly halves that latency for the description-typeahead's
        # most frequent case. Trade-off: the library query now always runs even
        # when history alone would have satisfied `limit` — acceptable for a
        # keystroke-driven typeahead, where most requests get superseded by a
        # newer one before their result is even used.
        history_rows, library_rows = await asyncio.gather(
            asyncio.to_thread(_fetch_history_rows),
            asyncio.to_thread(_fetch_library_rows),
        )

        out: list[dict] = []
        seen: set[str] = set()

        # 1) Firm history first — codes the CA actually picked (with the rate
        #    they used), ranked recency-then-frequency. On an empty query this
        #    is the whole result (recent list); with a term it is the matching
        #    history.
        for r in history_rows:
            code = (r.get("hsn_sac") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            n = r.get("use_count") or 1
            out.append({
                "hsn_code":    code,
                "description": r.get("sample_description") or "",
                "gst_rate_bps": r.get("gst_rate_bps"),
                "uqc":         None,
                "hsn_type":    None,
                "source":      "history",
                "reason":      ("Recently used" if not term
                                else f"Used {n} time" + ("s" if n != 1 else "")),
            })
            if len(out) >= limit:
                return api_response(True, out)

        # An empty query never reads the library — recent history is the whole set.
        if not term:
            return api_response(True, out)

        # 2) The firm's own library — code prefix OR description substring, then
        #    relevance-ranked (exact code > prefix > description) since PostgREST
        #    can only pre-sort by hsn_code.
        for r in _rank_library_rows(term, library_rows):
            code = (r.get("hsn_code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({
                "hsn_code":    code,
                "description": r.get("description") or "",
                "gst_rate_bps": _pct_to_bps(r.get("gst_rate_pct")),
                "uqc":         r.get("uqc"),
                "hsn_type":    r.get("hsn_type"),
                "source":      "library",
                "reason":      None,
            })
            if len(out) >= limit:
                break

        return api_response(True, out)
    except Exception as e:
        _logger.error("search_hsn: %s", e)
        return api_response(False, None, "Unable to search HSN/SAC. Please try again.")
