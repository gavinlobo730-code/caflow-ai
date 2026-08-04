"""
Payee (Tier 1.3) and learn-from-history (Tier 1.4).

1.3 puts a name on the other side of a bank line, optionally pointing at a
customer or vendor. 1.4 reads back what was done with that payee before.

BOTH ARE SUGGESTIONS UNTIL A HUMAN ACTS. `suggest_payee` proposes; only
`set_payee` writes, and only when called. Nothing in the queue path mutates a
transaction — the same contract the matching rules have had since B.2.3.

ONE BOUNDED QUERY, NOT ONE PER ROW
    The categorize queue can show a hundred transactions. Asking the database
    "how was this payee coded before?" a hundred times would be a hundred round
    trips. Instead the history for the whole client is fetched ONCE, bounded and
    already filtered to rows that carry a coding, and the per-row work is a
    dictionary lookup. That is why `history_index` exists separately from
    `suggest_for`.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from domain.banking.history import (
    learning_key, summarise, describe, HistorySuggestion,
    KEY_PAYEE_ID, KEY_COUNTERPARTY,
)
from domain.banking.narration import parse_narration, party_matches

_logger = logging.getLogger("caflow.bank_payee")

PAYEE_TYPES = ("customer", "vendor", "other")

# How far back to learn. A client with years of history does not need all of it
# to answer "what do we usually do with this payee", and an unbounded read on a
# queue render is how a page gets slow enough that people stop using it.
HISTORY_WINDOW = 2000


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class BankPayeeService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    # ── 1.3 write ───────────────────────────────────────────────────────────
    def set_payee(self, db, firm_id: str, txn_id: str, *, payee_name: Optional[str],
                  payee_type: Optional[str] = None, payee_id: Optional[str] = None,
                  actor_id: Optional[str] = None) -> dict:
        """Name the other side of a bank line, optionally linking a party.

        Clearing is legitimate — an empty name removes the payee entirely,
        including any link, so a wrong association cannot survive as a dangling
        id with no name beside it.
        """
        txn = self._get_txn(db, firm_id, txn_id)
        name = (payee_name or "").strip()

        if not name:
            update = {"payee_name": None, "payee_type": None, "payee_id": None}
        else:
            ptype = (payee_type or "other").strip().lower()
            if ptype not in PAYEE_TYPES:
                raise HTTPException(status_code=422,
                                    detail=f"payee_type must be one of: {', '.join(PAYEE_TYPES)}")
            if payee_id and ptype == "other":
                raise HTTPException(
                    status_code=422,
                    detail="A linked payee must be a customer or a vendor. Use 'other' for a "
                           "payee that is neither — it carries a name and no link.")
            if ptype in ("customer", "vendor") and not payee_id:
                raise HTTPException(
                    status_code=422,
                    detail=f"Select the {ptype}, or record the payee as 'other'.")
            if payee_id:
                self._validate_party(db, firm_id, txn["client_id"], ptype, payee_id)
            update = {"payee_name": name, "payee_type": ptype, "payee_id": payee_id or None}

        update["updated_at"] = _now()
        (db.table("bank_transactions").update(update)
         .eq("id", txn_id).eq("firm_id", firm_id).execute())

        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "update", actor_id=actor_id,
                      new_data={k: v for k, v in update.items() if k != "updated_at"},
                      metadata={"source": "bank_payee"})
        except Exception:  # pragma: no cover - audit must never block
            pass
        return {**txn, **update}

    def _validate_party(self, db, firm_id: str, client_id: str, ptype: str, party_id: str) -> None:
        """The linked party must belong to this firm AND this client.

        payee_id carries no foreign key (the reference is polymorphic — see
        migration 257), so this check is the only thing standing between a typo
        and a bank line pointing at another client's customer.
        """
        table = "customers" if ptype == "customer" else "vendors"
        rows = (db.table(table).select("id, client_id")
                .eq("id", party_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=422,
                                detail=f"That {ptype} does not belong to this firm.")
        if rows[0].get("client_id") not in (None, client_id):
            raise HTTPException(status_code=422,
                                detail=f"That {ptype} belongs to a different client.")

    # ── 1.3 auto-fill ───────────────────────────────────────────────────────
    def suggest_payee(self, db, firm_id: str, client_id: str, txn: dict,
                      parties: Optional[list[dict]] = None) -> Optional[dict]:
        """Who this line looks like it was with — a proposal, never written.

        The narration parser already extracts a counterparty; this tries to match
        it against the client's real customers and vendors so the CA gets a LINK
        rather than a string. When nothing matches, the parsed name is still
        offered as an 'other' payee, because a name is more useful than nothing.
        """
        if txn.get("payee_name"):
            return None                      # already answered by a human
        parsed = parse_narration(txn.get("description"))
        if not parsed.counterparty:
            return None

        for p in (parties if parties is not None else self.parties(db, firm_id, client_id)):
            if party_matches(p.get("name"), parsed):
                return {"payee_name": p["name"], "payee_type": p["type"], "payee_id": p["id"],
                        "source": "matched_party"}
        return {"payee_name": parsed.counterparty, "payee_type": "other", "payee_id": None,
                "source": "narration"}

    def parties(self, db, firm_id: str, client_id: str) -> list[dict]:
        """The client's customers and vendors, flattened for matching. Fetched
        once per queue render, not once per transaction."""
        out: list[dict] = []
        for table, ptype, name_col in (("customers", "customer", "customer_name"),
                                       ("vendors", "vendor", "vendor_name")):
            try:
                rows = (db.table(table).select(f"id, {name_col}")
                        .eq("firm_id", firm_id).eq("client_id", client_id)
                        .execute().data) or []
            except Exception:  # pragma: no cover - a hint must never break the queue
                rows = []
            out.extend({"id": r["id"], "name": r.get(name_col), "type": ptype} for r in rows)
        return out

    # ── 1.4 learn from history ──────────────────────────────────────────────
    def history_index(self, db, firm_id: str, client_id: str) -> dict:
        """learning key -> past codings, built in ONE query for the whole client.

        Only transactions that were actually POSTED teach anything: a draft is a
        proposal, and an uncategorized row is not a decision. Learning from
        unposted rows would let one mistaken suggestion, accepted once, become
        the evidence for suggesting itself forever.

        Note what is NOT excluded here: rows currently on screen. A posted
        transaction sitting in the queue is a real past decision and should
        absolutely teach the unposted one below it. Only a transaction's OWN row
        has to be kept out of its own evidence — `suggest_for` does that, because
        it is the only place that knows which row is being annotated.
        """
        try:
            rows = (db.table("bank_transactions")
                    .select("id, description, payee_id, payee_name, account_id, category, "
                            "posted_at, transaction_date, posted_journal_id")
                    .eq("firm_id", firm_id).eq("client_id", client_id)
                    .order("transaction_date", desc=True)
                    .limit(HISTORY_WINDOW).execute().data) or []
        except Exception:  # pragma: no cover
            return {}

        index: dict = {}
        for r in rows:
            if not r.get("posted_journal_id"):
                continue
            if not (r.get("account_id") or r.get("category")):
                continue
            key = learning_key(r)
            if key is None:
                continue
            index.setdefault(key, []).append(r)
        return index

    def suggest_for(self, txn: dict, index: dict) -> Optional[HistorySuggestion]:
        """What history proposes for ONE transaction. A dictionary lookup —
        no query.

        A transaction's own row is dropped from its evidence. Without that, an
        already-posted transaction would suggest itself back at 100% and read as
        corroboration rather than as the single decision it is.
        """
        key = learning_key(txn)
        if key is None:
            return None
        own_id = txn.get("id")
        rows = [r for r in index.get(key, []) if r.get("id") != own_id or own_id is None]
        if not rows:
            return None
        return summarise(rows, key)

    @staticmethod
    def as_dict(s: Optional[HistorySuggestion]) -> Optional[dict]:
        """The wire shape. Carries the EVIDENCE, not just the answer — a CA
        cannot audit '92% confident', but can judge '8 of the last 9 times'."""
        if s is None:
            return None
        return {
            "account_id": s.account_id,
            "category": s.category,
            "times_seen": s.times_seen,
            "total_seen": s.total_seen,
            "share_bps": s.share_bps,
            "is_unanimous": s.is_unanimous,
            "last_seen": s.last_seen,
            "summary": describe(s),
            "matched_on": "linked party" if s.key_kind == KEY_PAYEE_ID else "payee name",
            "alternatives": [
                {"account_id": a.account_id, "category": a.category, "times": a.times}
                for a in s.alternatives
            ],
        }


bank_payee_service = BankPayeeService()
