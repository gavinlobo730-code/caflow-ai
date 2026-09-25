"""Fetch the inputs `domain/related_party/disclosure` decides on.

The split is this repository's usual one: the RULE — who is a related party,
what the note must say, what cannot be derived — is in the domain module and
reads no database; this knows which tables answer and nothing else.

⚠️ WHAT IT REPLACED READ THE DATABASE ONCE PER ENTITY. The old inline report
looped `for eid in entity_ids` issuing one `entity_to_entity_relationships`
query each — a Singapore-to-Mumbai round trip per director. One `.in_()` does
it, and `_by_pan` likewise resolves every party's customer and vendor rows in
two queries rather than two per party.

THE TRANSACTIONS ARE MATCHED ON PAN, which is the identifier a CA matches on
by hand and the only one both sides carry: `entities.pan` against
`customers.pan` and `vendors.pan`. A party with no PAN is reported with NO
figures and `matched_on_pan=False`, never with zeroes — the disclosure module
turns that into a named gap, because "we could not look" and "there were none"
are different facts on a statutory note.
"""
from __future__ import annotations

from typing import Any, Optional

from core.db_paging import fetch_all
from domain.related_party.disclosure import (
    TRANSFER_PRICING_THRESHOLD_PAISE,
    Dealings,
    Disclosure,
    Party,
    build,
    standing_for,
)

#: Migration 273 gave the s.185/s.186 feature its own table; `public.loans` is
#: the client's BORROWINGS register and is a different thing entirely. Named
#: here so a reader does not reach for the obvious one.
RELATED_PARTY_LOANS_TABLE = "related_party_loans"

#: Only a settled document counts toward the volume a note discloses. A draft
#: has been issued to nobody. The vocabularies are migration 050's own.
_COUNTED_SALES_STATUSES = ("issued", "partially_paid", "paid")
_COUNTED_BILL_STATUSES = ("received", "partially_paid", "paid")


def _norm_pan(v: Any) -> str:
    return (v or "").strip().upper()


class RelatedPartyService:
    """Reads for the AS 18 note. Decides nothing the domain module decides."""

    def __init__(self, db):
        self.db = db

    # ── roles ────────────────────────────────────────────────────────────
    def roles_for_client(self, firm_id: str, client_id: str) -> list[dict]:
        """Every recorded role at this client, with the entity's own details.

        The screen could not list these at all before: there was no endpoint,
        and `entity_roles` carries only an `entity_id`, so a row on its own
        renders as a UUID. The entity is joined here rather than in the
        browser, so the name reaches every caller including the note.
        """
        roles = fetch_all(
            lambda: self.db.table("entity_roles")
            .select("id, entity_id, client_id, role, ownership_percent, "
                    "effective_from, effective_to, notes")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id),
            label="entity_roles",
        )
        if not roles:
            return []
        entity_ids = sorted({r["entity_id"] for r in roles if r.get("entity_id")})
        entities = self._entities_by_id(firm_id, entity_ids)
        out = []
        for r in roles:
            e = entities.get(r.get("entity_id")) or {}
            out.append({
                **r,
                "entity_name": e.get("full_name"),
                "entity_type": e.get("entity_type"),
                "pan": e.get("pan"),
                "email": e.get("email"),
            })
        # Newest first is what the screen showed; the ROLE is the stable sort
        # key here because `entity_roles` has no meaningful created order to a
        # reader — a note lists directors together.
        out.sort(key=lambda r: ((r.get("role") or ""), (r.get("entity_name") or "")))
        return out

    def _entities_by_id(self, firm_id: str, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        rows = fetch_all(
            lambda: self.db.table("entities")
            .select("id, full_name, entity_type, pan, gstin, email")
            .eq("firm_id", firm_id)
            .in_("id", ids),
            label="entities",
        )
        return {r["id"]: r for r in rows}

    # ── the note ─────────────────────────────────────────────────────────
    def disclosure(self, firm_id: str, client_id: str) -> Disclosure:
        roles = self.roles_for_client(firm_id, client_id)
        entity_ids = sorted({r["entity_id"] for r in roles if r.get("entity_id")})

        parties: list[Party] = []
        for r in roles:
            rule = standing_for(r.get("role") or "", r.get("ownership_percent"))
            parties.append(Party(
                entity_id=r.get("entity_id") or "",
                name=r.get("entity_name") or "(unnamed entity)",
                pan=r.get("pan"),
                role=r.get("role") or "",
                ownership_percent=r.get("ownership_percent"),
                standing=rule.standing,
                reason=rule.reason,
                effective_from=r.get("effective_from"),
                effective_to=r.get("effective_to"),
            ))

        dealings = self._dealings_by_pan(
            firm_id, client_id, [p.pan for p in parties if p.pan]
        )
        parties = [
            Party(**{**p.__dict__, "dealings": dealings.get(_norm_pan(p.pan))})
            for p in parties
        ]

        return build(
            client_id=client_id,
            parties=parties,
            section_185_loans=self._loans(firm_id, client_id, flagged=True),
            transfer_pricing_flags=self._transfer_pricing(firm_id, client_id),
            entity_relationships=self._entity_edges(firm_id, entity_ids),
        )

    # ── the pieces ───────────────────────────────────────────────────────
    def _entity_edges(self, firm_id: str, entity_ids: list[str]) -> list[dict]:
        """Every entity-to-entity edge touching one of these parties.

        TWO `.in_()` QUERIES, NOT ONE PER ENTITY. The old code issued a query
        per entity with an `.or_()` inside it; an edge can match on either
        end, so the two directions are read separately and de-duplicated by
        id — which also keeps a PostgREST or-expression out of the code, and
        two separate fakes stand in for the database in this suite.
        """
        if not entity_ids:
            return []
        seen: dict[str, dict] = {}
        for column in ("from_entity_id", "to_entity_id"):
            rows = fetch_all(
                lambda col=column: self.db.table("entity_to_entity_relationships")
                .select("id, from_entity_id, to_entity_id, relationship_type, "
                        "ownership_percent, effective_from, effective_to, notes")
                .eq("firm_id", firm_id)
                .in_(col, entity_ids),
                label="entity_to_entity_relationships",
            )
            for row in rows:
                seen[row["id"]] = row
        return list(seen.values())

    def _loans(self, firm_id: str, client_id: str, *, flagged: bool) -> list[dict]:
        def q():
            b = (self.db.table(RELATED_PARTY_LOANS_TABLE)
                 .select("id, entity_id, loan_type, principal_paise, interest_rate, "
                         "sanction_date, due_date, section_185_flagged, "
                         "section_186_flagged, notes")
                 .eq("firm_id", firm_id)
                 .eq("client_id", client_id))
            return b.eq("section_185_flagged", True) if flagged else b
        return fetch_all(q, label=RELATED_PARTY_LOANS_TABLE)

    def _transfer_pricing(self, firm_id: str, client_id: str) -> list[dict]:
        """IT Act s.92 — an inter-company loan at or above the threshold.

        `gte`, not `gt`: s.92's limb is "exceeds" on some readings and "of or
        above" on others, and the threshold is a REPORTING trigger here rather
        than a charge, so the inclusive test is the one that cannot hide a
        transaction from a CA.
        """
        return fetch_all(
            lambda: self.db.table(RELATED_PARTY_LOANS_TABLE)
            .select("id, entity_id, loan_type, principal_paise, sanction_date, notes")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("loan_type", "inter_company")
            .gte("principal_paise", TRANSFER_PRICING_THRESHOLD_PAISE),
            label="transfer_pricing",
        )

    def _dealings_by_pan(
        self, firm_id: str, client_id: str, pans: list[str]
    ) -> dict[str, Dealings]:
        """What each related party bought and sold, matched on PAN.

        FOUR QUERIES IN TOTAL, whatever the number of parties: the customer
        and vendor masters filtered by PAN, then that client's invoices and
        bills filtered by the ids those returned. A read per party would be
        proportional to the note's length rather than to its answer.
        """
        wanted = sorted({_norm_pan(p) for p in pans if _norm_pan(p)})
        if not wanted:
            return {}

        customers = fetch_all(
            lambda: self.db.table("customers")
            .select("id, pan").eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("pan", wanted),
            label="customers",
        )
        vendors = fetch_all(
            lambda: self.db.table("vendors")
            .select("id, pan").eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("pan", wanted),
            label="vendors",
        )
        cust_pan = {c["id"]: _norm_pan(c.get("pan")) for c in customers}
        vend_pan = {v["id"]: _norm_pan(v.get("pan")) for v in vendors}

        sales: dict[str, list[dict]] = {}
        if cust_pan:
            rows = fetch_all(
                lambda: self.db.table("client_sales_invoices")
                .select("id, customer_id, total_paise, outstanding_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("customer_id", sorted(cust_pan)),
                label="client_sales_invoices",
            )
            for r in rows:
                if (r.get("status") or "") not in _COUNTED_SALES_STATUSES:
                    continue
                sales.setdefault(cust_pan.get(r.get("customer_id"), ""), []).append(r)

        bills: dict[str, list[dict]] = {}
        if vend_pan:
            rows = fetch_all(
                lambda: self.db.table("purchase_bills")
                .select("id, vendor_id, net_payable_paise, outstanding_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("vendor_id", sorted(vend_pan)),
                label="purchase_bills",
            )
            for r in rows:
                if (r.get("status") or "") not in _COUNTED_BILL_STATUSES:
                    continue
                bills.setdefault(vend_pan.get(r.get("vendor_id"), ""), []).append(r)

        out: dict[str, Dealings] = {}
        for pan in wanted:
            out[pan] = Dealings(
                matched_on_pan=True,
                sales_paise=sum(int(r.get("total_paise") or 0) for r in sales.get(pan, [])),
                purchases_paise=sum(int(r.get("net_payable_paise") or 0) for r in bills.get(pan, [])),
                # `outstanding_paise` is GENERATED on both tables (migration
                # 278) — read it, never re-subtract. The two note columns'
                # signs differ between the tables, which is exactly why.
                receivable_paise=sum(int(r.get("outstanding_paise") or 0) for r in sales.get(pan, [])),
                payable_paise=sum(int(r.get("outstanding_paise") or 0) for r in bills.get(pan, [])),
            )
        return out


def as_payload(d: Disclosure) -> dict:
    """The shape the endpoint serves. One place, so the screen and any later
    PDF read the same object."""
    def party(p: Party) -> dict:
        return {
            "entity_id": p.entity_id,
            "name": p.name,
            "pan": p.pan,
            "role": p.role,
            "ownership_percent": (
                float(p.ownership_percent) if p.ownership_percent is not None else None
            ),
            "standing": p.standing.value,
            "reason": p.reason,
            "effective_from": p.effective_from,
            "effective_to": p.effective_to,
            # Always present, null where the party carries no PAN — an absent
            # key and a null key read the same to a screen and are different
            # bugs (`journal_source`'s discipline).
            "dealings": None if p.dealings is None or not p.dealings.matched_on_pan else {
                "sales_paise": p.dealings.sales_paise,
                "purchases_paise": p.dealings.purchases_paise,
                "receivable_paise": p.dealings.receivable_paise,
                "payable_paise": p.dealings.payable_paise,
            },
        }

    return {
        "client_id": d.client_id,
        "parties": [party(p) for p in d.parties],
        "included_count": len(d.included),
        "undetermined_count": len(d.undetermined),
        "disclosure_required": d.disclosure_required,
        "section_185_loans": d.section_185_loans,
        "transfer_pricing_flags": d.transfer_pricing_flags,
        "transfer_pricing_count": len(d.transfer_pricing_flags),
        "entity_relationships": d.entity_relationships,
        "gaps": d.gaps,
        "notes": d.notes,
    }
