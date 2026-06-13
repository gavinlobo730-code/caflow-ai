"""
Relationships router — Entity management, roles, cross-entity relationships,
cross-client PAN/email match detection, loan intelligence (Sec 185/186),
property intelligence, and related party report generation.

Phase 7: Unified Intelligence Layer — PracticeSync
Chapter 15: Relationship Intelligence

All monetary values in integer paise — never float.
CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from models.common import api_response
from core.permissions import rbac
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


# ─── In-memory mock stores ────────────────────────────────────────────────────

_MOCK_ENTITIES:              list[dict] = []
_MOCK_ENTITY_ROLES:          list[dict] = []
_MOCK_RELATIONSHIPS:         list[dict] = []
_MOCK_CROSS_MATCHES:         list[dict] = []
_MOCK_ENTITY_TO_ENTITY_RELS: list[dict] = []
_MOCK_LOANS:                 list[dict] = []
_MOCK_PROPERTIES:            list[dict] = []

# Transfer pricing threshold: ₹1 crore = 1,00,00,000 paise (Sec 92 IT Act)
TRANSFER_PRICING_THRESHOLD_PAISE = 1_00_00_000_00  # ₹1,00,00,000 in paise


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class EntityIn(BaseModel):
    full_name: str
    entity_type: str  # Individual | Company | LLP | Partnership | Trust | HUF
    pan: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[str] = None
    notes: Optional[str] = None


class EntityUpdateIn(BaseModel):
    full_name: Optional[str] = None
    entity_type: Optional[str] = None
    pan: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[str] = None
    notes: Optional[str] = None


class EntityRoleIn(BaseModel):
    client_id: str
    role_type: str  # Director | Shareholder | Partner | Trustee | Proprietor | Guarantor | Authorized Signatory
    ownership_percent: Optional[float] = None  # numeric(5,2) — stored as float, displayed as percent
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    notes: Optional[str] = None


class RelationshipIn(BaseModel):
    from_entity_id: str
    to_entity_id: str
    relationship_type: str  # e.g. Spouse | Parent | Child | Associated Company | Group Company
    description: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


class CrossMatchReviewIn(BaseModel):
    is_confirmed: bool
    notes: Optional[str] = None


class EntityToEntityRelIn(BaseModel):
    """Holding / subsidiary / associate / JV relationships between entities."""
    from_entity_id: str
    to_entity_id: str
    # CGST Act Sec 2(76) — related party; Companies Act Sec 2(87) — subsidiary
    relationship_type: str  # holding | subsidiary | associate | joint_venture | related_party
    ownership_percent: Optional[float] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    notes: Optional[str] = None


class LoanIn(BaseModel):
    """
    Loan from a client to an entity.
    Section 185 IT Act — loans to directors require CA review.
    All amounts in integer paise. Never float.
    """
    client_id: str
    entity_id: str          # borrower entity
    loan_type: str          # to_director | from_director | inter_company | other
    principal_paise: int    # integer paise — CGST Act Sec 15 arithmetic rules apply
    interest_rate: float    # annual % (stored as float, display only — not used in calculations)
    sanction_date: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None


class PropertyIn(BaseModel):
    """
    Property linked to a client and optionally an entity.
    Annual rent tracked for Schedule HP (IT Act Sec 22-27).
    All amounts in integer paise.
    """
    client_id: str
    entity_id: Optional[str] = None
    address: str
    property_type: str      # residential | commercial | land | industrial
    cost_paise: int         # integer paise — IT Act Sec 48 cost of acquisition
    annual_rent_paise: int = 0  # integer paise — IT Act Sec 23 annual value
    acquisition_date: Optional[str] = None
    notes: Optional[str] = None


# ─── Entities ─────────────────────────────────────────────────────────────────

@router.get("/entities")
def list_entities(
    entity_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = list(_MOCK_ENTITIES)
        if entity_type:
            result = [e for e in result if e.get("entity_type") == entity_type]
        if search:
            s = search.lower()
            result = [
                e for e in result
                if s in (e.get("full_name") or "").lower()
                or s in (e.get("pan") or "").lower()
                or s in (e.get("email") or "").lower()
            ]
        return api_response(True, result[offset: offset + limit])

    q = db.table("entities").select("*").eq("firm_id", current_user["firm_id"])
    if entity_type:
        q = q.eq("entity_type", entity_type)
    if search:
        q = q.or_(f"full_name.ilike.%{search}%,pan.ilike.%{search}%,email.ilike.%{search}%")
    res = q.order("full_name").range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])


@router.post("/entities")
def create_entity(
    data: EntityIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":         str(uuid.uuid4()),
        "firm_id":    firm_id,
        "created_at": now,
        "updated_at": now,
        **data.model_dump(),
    }

    if not db:
        _MOCK_ENTITIES.append(row)
        timeline_service.log(
            row["id"], "lifecycle", "Entity Created",
            f"Entity {data.full_name} ({data.entity_type}) created", "info",
            firm_id=firm_id,
        )
        return api_response(True, row)

    res = db.table("entities").insert({
        "firm_id": firm_id,
        **data.model_dump(),
    }).execute()
    created = (res.data or [row])[0]

    timeline_service.log(
        created["id"], "lifecycle", "Entity Created",
        f"Entity {data.full_name} ({data.entity_type}) created", "info",
        firm_id=firm_id,
        entity_type="entity", entity_id=created["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, created)


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: str,
    data: EntityUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    update = data.model_dump(exclude_none=True)
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not db:
        for i, e in enumerate(_MOCK_ENTITIES):
            if e["id"] == entity_id:
                _MOCK_ENTITIES[i].update(update)
                return api_response(True, _MOCK_ENTITIES[i])
        raise HTTPException(status_code=404, detail="Entity not found")

    existing = db.table("entities").select("id").eq("id", entity_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Entity not found")

    res = db.table("entities").update(update).eq("id", entity_id).eq("firm_id", firm_id).execute()
    return api_response(True, (res.data or [{}])[0])


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        entity = next((e for e in _MOCK_ENTITIES if e["id"] == entity_id), None)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        roles = [r for r in _MOCK_ENTITY_ROLES if r.get("entity_id") == entity_id]
        relationships = [
            r for r in _MOCK_RELATIONSHIPS
            if r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id
        ]
        return api_response(True, {**entity, "roles": roles, "relationships": relationships})

    entity = db.table("entities").select("*").eq("id", entity_id).eq("firm_id", firm_id).single().execute().data
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    roles = db.table("entity_roles").select("*").eq("entity_id", entity_id).eq("firm_id", firm_id).execute().data or []
    relationships = db.table("entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute().data or []

    return api_response(True, {**entity, "roles": roles, "relationships": relationships})


# ─── Roles ────────────────────────────────────────────────────────────────────

@router.post("/entities/{entity_id}/roles")
def add_entity_role(
    entity_id: str,
    data: EntityRoleIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                str(uuid.uuid4()),
        "firm_id":           firm_id,
        "entity_id":         entity_id,
        "client_id":         data.client_id,
        "role":              data.role_type,   # schema column is "role"
        "ownership_percent": data.ownership_percent,
        "effective_from":    data.effective_from,
        "effective_to":      data.effective_to,
        "notes":             data.notes,
        "created_at":        now,
        "updated_at":        now,
    }

    if not db:
        _MOCK_ENTITY_ROLES.append(row)
        timeline_service.log(
            data.client_id, "lifecycle", "Relationship Added",
            f"Entity assigned role {data.role_type} for client {data.client_id}", "info",
            firm_id=firm_id,
        )
        return api_response(True, row)

    entity = db.table("entities").select("id, full_name").eq("id", entity_id).eq("firm_id", firm_id).single().execute().data
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    db_row = {
        "firm_id":           firm_id,
        "entity_id":         entity_id,
        "client_id":         data.client_id,
        "role":              data.role_type,
        "ownership_percent": data.ownership_percent,
        "effective_from":    data.effective_from,
        "effective_to":      data.effective_to,
        "notes":             data.notes,
    }
    res = db.table("entity_roles").insert(db_row).execute()
    created = (res.data or [row])[0]

    timeline_service.log(
        data.client_id, "lifecycle", "Relationship Added",
        f"{entity['full_name']} assigned as {data.role_type}", "info",
        firm_id=firm_id,
        entity_type="entity_role", entity_id=created["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, created)


@router.delete("/roles/{role_id}")
def remove_entity_role(
    role_id: str,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        global _MOCK_ENTITY_ROLES
        _MOCK_ENTITY_ROLES = [r for r in _MOCK_ENTITY_ROLES if r["id"] != role_id]
        return api_response(True, {"deleted": True, "role_id": role_id})

    existing = db.table("entity_roles").select("id").eq("id", role_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")

    db.table("entity_roles").delete().eq("id", role_id).eq("firm_id", firm_id).execute()
    return api_response(True, {"deleted": True, "role_id": role_id})


# ─── Relationships ────────────────────────────────────────────────────────────

@router.post("/relationships")
def create_relationship(
    data: RelationshipIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                str(uuid.uuid4()),
        "firm_id":           firm_id,
        "from_entity_id":    data.from_entity_id,
        "to_entity_id":      data.to_entity_id,
        "relationship_type": data.relationship_type,
        "description":       data.description,
        "effective_from":    data.effective_from,
        "effective_to":      data.effective_to,
        "created_at":        now,
        "updated_at":        now,
    }

    if not db:
        _MOCK_RELATIONSHIPS.append(row)
        timeline_service.log(
            data.from_entity_id, "lifecycle", "Relationship Added",
            f"Relationship {data.relationship_type} created", "info",
            firm_id=firm_id,
        )
        return api_response(True, row)

    from_e = db.table("entities").select("id").eq("id", data.from_entity_id).eq("firm_id", firm_id).single().execute().data
    to_e   = db.table("entities").select("id").eq("id", data.to_entity_id).eq("firm_id", firm_id).single().execute().data
    if not from_e or not to_e:
        raise HTTPException(status_code=404, detail="One or both entities not found in firm")

    res = db.table("entity_relationships").insert(row).execute()
    created = (res.data or [row])[0]

    timeline_service.log(
        data.from_entity_id, "lifecycle", "Relationship Added",
        f"Relationship {data.relationship_type} created between entities", "info",
        firm_id=firm_id,
        entity_type="entity_relationship", entity_id=created["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, created)


@router.get("/relationships")
def list_relationships(
    entity_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = [
            r for r in _MOCK_RELATIONSHIPS
            if r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id
        ]
        return api_response(True, result)

    res = db.table("entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute()
    return api_response(True, res.data or [])


# ─── Cross-Client Matches ─────────────────────────────────────────────────────

@router.get("/cross-client-matches")
def list_cross_client_matches(
    entity_id: Optional[str] = Query(None),
    reviewed: Optional[bool] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = list(_MOCK_CROSS_MATCHES)
        if entity_id:
            result = [m for m in result if m.get("entity_id") == entity_id]
        if reviewed is None:
            result = [m for m in result if not m.get("reviewed")]
        elif reviewed:
            result = [m for m in result if m.get("reviewed")]
        return api_response(True, result)

    q = db.table("cross_client_matches").select("*").eq("firm_id", firm_id)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    elif reviewed is None:
        q = q.eq("reviewed", False)
    elif reviewed:
        q = q.eq("reviewed", True)
    res = q.order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/cross-client-matches/detect")
def detect_cross_client_matches(
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Scan entities for cross-client PAN/email matches.
    For each entity with a PAN, find other entity_roles sharing the same PAN
    across different client_ids. Insert cross_client_matches rows (skip duplicates).
    """
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        pan_map: dict[str, list[dict]] = {}
        for role in _MOCK_ENTITY_ROLES:
            entity = next((e for e in _MOCK_ENTITIES if e["id"] == role.get("entity_id")), None)
            if entity and entity.get("pan"):
                pan = entity["pan"].upper()
                if pan not in pan_map:
                    pan_map[pan] = []
                pan_map[pan].append({"role": role, "entity": entity})

        new_count = 0
        now = datetime.now(timezone.utc).isoformat()
        for pan, entries in pan_map.items():
            client_ids = list({e["role"]["client_id"] for e in entries})
            if len(client_ids) < 2:
                continue
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    a, b = entries[i], entries[j]
                    if a["role"]["client_id"] == b["role"]["client_id"]:
                        continue
                    already = any(
                        m.get("match_value") == pan
                        and m.get("client_id_a") == a["role"]["client_id"]
                        and m.get("client_id_b") == b["role"]["client_id"]
                        for m in _MOCK_CROSS_MATCHES
                    )
                    if not already:
                        _MOCK_CROSS_MATCHES.append({
                            "id":           str(uuid.uuid4()),
                            "firm_id":      firm_id,
                            "match_value":  pan,
                            "entity_id":    a["entity"]["id"],
                            "client_id_a":  a["role"]["client_id"],
                            "client_id_b":  b["role"]["client_id"],
                            "match_type":   "pan",
                            "reviewed":     False,
                            "confirmed":    None,
                            "created_at":   now,
                        })
                        new_count += 1
        return api_response(True, {"new_matches_detected": new_count})

    entities_with_pan = db.table("entities").select("id, pan, full_name").eq("firm_id", firm_id).not_.is_("pan", "null").execute().data or []

    pan_entity_map: dict[str, list[dict]] = {}
    for entity in entities_with_pan:
        pan = (entity.get("pan") or "").upper().strip()
        if not pan:
            continue
        roles = db.table("entity_roles").select("client_id").eq("entity_id", entity["id"]).eq("firm_id", firm_id).execute().data or []
        for role in roles:
            if pan not in pan_entity_map:
                pan_entity_map[pan] = []
            pan_entity_map[pan].append({
                "entity_id": entity["id"],
                "client_id": role["client_id"],
            })

    now = datetime.now(timezone.utc).isoformat()
    new_count = 0

    for pan, entries in pan_entity_map.items():
        client_ids = list({e["client_id"] for e in entries})
        if len(client_ids) < 2:
            continue

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                if a["client_id"] == b["client_id"]:
                    continue
                existing_check = db.table("cross_client_matches").select("id").eq("firm_id", firm_id).eq("match_value", pan).eq("client_id_a", a["client_id"]).eq("client_id_b", b["client_id"]).execute().data
                if existing_check:
                    continue
                try:
                    db.table("cross_client_matches").insert({
                        "id":          str(uuid.uuid4()),
                        "firm_id":     firm_id,
                        "match_value": pan,
                        "entity_id":   a["entity_id"],
                        "client_id_a": a["client_id"],
                        "client_id_b": b["client_id"],
                        "match_type":  "pan",
                        "reviewed":    False,
                        "created_at":  now,
                    }).execute()
                    new_count += 1
                except Exception:
                    pass  # Skip duplicates

    return api_response(True, {"new_matches_detected": new_count})


@router.patch("/cross-client-matches/{match_id}/review")
def review_cross_client_match(
    match_id: str,
    data: CrossMatchReviewIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        for i, m in enumerate(_MOCK_CROSS_MATCHES):
            if m["id"] == match_id:
                _MOCK_CROSS_MATCHES[i]["reviewed"] = True
                _MOCK_CROSS_MATCHES[i]["confirmed"] = data.is_confirmed
                return api_response(True, _MOCK_CROSS_MATCHES[i])
        raise HTTPException(status_code=404, detail="Match not found")

    existing = db.table("cross_client_matches").select("id").eq("id", match_id).eq("firm_id", firm_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Match not found")

    update: dict = {
        "reviewed":     True,
        "is_confirmed": data.is_confirmed,
    }
    if data.notes:
        update["notes"] = data.notes

    res = db.table("cross_client_matches").update(update).eq("id", match_id).eq("firm_id", firm_id).execute()
    return api_response(True, (res.data or [{}])[0])


# ─── Entity-to-Entity Relationships ──────────────────────────────────────────
# Companies Act Sec 2(87): subsidiary; Sec 2(6): associate company
# CGST Act Sec 2(76): related party

@router.post("/entity-to-entity")
def create_entity_to_entity_relationship(
    data: EntityToEntityRelIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a holding/subsidiary/associate/JV relationship between two entities."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                str(uuid.uuid4()),
        "firm_id":           firm_id,
        "from_entity_id":    data.from_entity_id,
        "to_entity_id":      data.to_entity_id,
        "relationship_type": data.relationship_type,
        "ownership_percent": data.ownership_percent,
        "effective_from":    data.effective_from,
        "effective_to":      data.effective_to,
        "notes":             data.notes,
        "created_at":        now,
        "updated_at":        now,
    }

    if not db:
        _MOCK_ENTITY_TO_ENTITY_RELS.append(row)
        return api_response(True, row)

    res = db.table("entity_to_entity_relationships").insert(row).execute()
    return api_response(True, (res.data or [row])[0])


@router.get("/entity-to-entity")
def list_entity_to_entity_relationships(
    entity_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = [
            r for r in _MOCK_ENTITY_TO_ENTITY_RELS
            if r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id
        ]
        return api_response(True, result)

    res = db.table("entity_to_entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute()
    return api_response(True, res.data or [])


# ─── Loan Intelligence ────────────────────────────────────────────────────────
# Section 185 Companies Act: loans/advances to directors — requires CA review
# Section 186 Companies Act: loans to other companies — requires CA review
# Section 92 IT Act: transfer pricing for international related party transactions

@router.post("/loans")
def create_loan(
    data: LoanIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Create a loan record. Automatically flags Section 185 violations.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Section 185 Companies Act — loan to director auto-flag
    section_185_flagged = data.loan_type == "to_director"
    # Section 186 Companies Act — inter-company loan flag
    section_186_flagged = data.loan_type == "inter_company"

    row = {
        "id":                    str(uuid.uuid4()),
        "firm_id":               firm_id,
        "client_id":             data.client_id,
        "entity_id":             data.entity_id,
        "loan_type":             data.loan_type,
        "principal_paise":       data.principal_paise,  # integer paise — never float
        "interest_rate":         data.interest_rate,
        "sanction_date":         data.sanction_date,
        "due_date":              data.due_date,
        "notes":                 data.notes,
        "section_185_flagged":   section_185_flagged,
        "section_186_flagged":   section_186_flagged,
        "created_at":            now,
        "updated_at":            now,
    }

    if not db:
        _MOCK_LOANS.append(row)
        if section_185_flagged:
            timeline_service.log(
                data.client_id, "compliance", "Section 185 Flag",
                f"Loan to director entity flagged — Section 185 Companies Act. "
                f"Principal: ₹{data.principal_paise // 100:,}",
                "warning", firm_id=firm_id,
            )
        return api_response(True, row)

    res = db.table("loans").insert(row).execute()
    created = (res.data or [row])[0]

    if section_185_flagged:
        timeline_service.log(
            data.client_id, "compliance", "Section 185 Flag",
            f"Loan to director flagged under Section 185 Companies Act. "
            f"Principal: ₹{data.principal_paise // 100:,}",
            "warning", firm_id=firm_id,
            entity_type="loan", entity_id=created["id"],
            actor_id=current_user.get("auth_user_id"),
        )

    return api_response(True, created)


@router.get("/loans")
def list_loans(
    client_id: Optional[str] = Query(None),
    flagged_only: bool = Query(False),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = list(_MOCK_LOANS)
        if client_id:
            result = [l for l in result if l.get("client_id") == client_id]
        if flagged_only:
            result = [l for l in result if l.get("section_185_flagged") or l.get("section_186_flagged")]
        return api_response(True, result)

    q = db.table("loans").select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if flagged_only:
        q = q.or_("section_185_flagged.eq.true,section_186_flagged.eq.true")
    res = q.order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.get("/loans/section-185-report")
def section_185_report(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Return all Section 185 flagged loans.
    Section 185 Companies Act prohibits companies from advancing loans to directors.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = [l for l in _MOCK_LOANS if l.get("section_185_flagged")]
        if client_id:
            result = [l for l in result if l.get("client_id") == client_id]
        total_paise = sum(l["principal_paise"] for l in result)
        return api_response(True, {
            "flagged_loans": result,
            "count": len(result),
            "total_principal_paise": total_paise,  # integer paise
        })

    q = db.table("loans").select("*").eq("firm_id", firm_id).eq("section_185_flagged", True)
    if client_id:
        q = q.eq("client_id", client_id)
    rows = q.execute().data or []
    total_paise = sum(r["principal_paise"] for r in rows)
    return api_response(True, {
        "flagged_loans": rows,
        "count": len(rows),
        "total_principal_paise": total_paise,  # integer paise
    })


# ─── Property Intelligence ────────────────────────────────────────────────────
# IT Act Sec 22-27: income from house property
# IT Act Sec 48: cost of acquisition for capital gains

@router.post("/properties")
def create_property(
    data: PropertyIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Create a property record with rental income tracking.
    IT Act Sec 22: annual value of property chargeable as income from house property.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if data.cost_paise < 0 or data.annual_rent_paise < 0:
        raise HTTPException(status_code=422, detail="cost_paise and annual_rent_paise must be non-negative integers")

    row = {
        "id":                 str(uuid.uuid4()),
        "firm_id":            firm_id,
        "client_id":          data.client_id,
        "entity_id":          data.entity_id,
        "address":            data.address,
        "property_type":      data.property_type,
        "cost_paise":         data.cost_paise,         # integer paise — IT Act Sec 48
        "annual_rent_paise":  data.annual_rent_paise,  # integer paise — IT Act Sec 23
        "acquisition_date":   data.acquisition_date,
        "notes":              data.notes,
        "created_at":         now,
        "updated_at":         now,
    }

    if not db:
        _MOCK_PROPERTIES.append(row)
        return api_response(True, row)

    res = db.table("properties").insert(row).execute()
    return api_response(True, (res.data or [row])[0])


@router.get("/properties")
def list_properties(
    client_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = list(_MOCK_PROPERTIES)
        if client_id:
            result = [p for p in result if p.get("client_id") == client_id]
        if entity_id:
            result = [p for p in result if p.get("entity_id") == entity_id]
        return api_response(True, result)

    q = db.table("properties").select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    res = q.order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


# ─── Related Party Report ─────────────────────────────────────────────────────
# CGST Act Sec 2(76): definition of related party
# Companies Act Sec 188: related party transactions
# AS 18 / Ind AS 24: related party disclosures

@router.get("/related-party-report")
def related_party_report(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Auto-generate related party disclosure summary for a client.
    CGST Act Sec 2(76) — related party definition.
    Companies Act Sec 188 — related party transactions requiring board approval.
    AS 18 / Ind AS 24 — related party disclosures in financial statements.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        # Collect all entity roles for this client
        client_roles = [r for r in _MOCK_ENTITY_ROLES if r.get("client_id") == client_id]
        entity_ids = [r["entity_id"] for r in client_roles]

        # Get related party role types — CGST Act Sec 2(76)
        related_party_roles = {"Director", "Shareholder", "Partner", "Trustee", "Guarantor", "related_party"}
        related_parties = [r for r in client_roles if r.get("role") in related_party_roles]

        # Entity-to-entity relationships involving these entities
        e2e_rels = [
            r for r in _MOCK_ENTITY_TO_ENTITY_RELS
            if r.get("from_entity_id") in entity_ids or r.get("to_entity_id") in entity_ids
        ]

        # Section 185 loans for this client
        sec185_loans = [l for l in _MOCK_LOANS if l.get("client_id") == client_id and l.get("section_185_flagged")]

        # Transfer pricing: inter-company loans > ₹1 crore (Sec 92 IT Act)
        # TRANSFER_PRICING_THRESHOLD_PAISE = 1_00_00_000_00 paise
        transfer_pricing_flags = [
            l for l in _MOCK_LOANS
            if l.get("client_id") == client_id
            and l.get("loan_type") == "inter_company"
            and l.get("principal_paise", 0) >= TRANSFER_PRICING_THRESHOLD_PAISE
        ]

        return api_response(True, {
            "client_id":              client_id,
            "related_parties":        related_parties,
            "related_party_count":    len(related_parties),
            "entity_to_entity_rels":  e2e_rels,
            "section_185_loans":      sec185_loans,
            "transfer_pricing_flags": transfer_pricing_flags,
            "transfer_pricing_count": len(transfer_pricing_flags),
            # AS 18 / Ind AS 24 — disclosures required if any related parties exist
            "disclosure_required":    len(related_parties) > 0,
        })

    # DB path
    client_roles = db.table("entity_roles").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
    entity_ids = [r["entity_id"] for r in client_roles]

    related_party_roles = {"Director", "Shareholder", "Partner", "Trustee", "Guarantor", "related_party"}
    related_parties = [r for r in client_roles if r.get("role") in related_party_roles]

    e2e_rels: list[dict] = []
    for eid in entity_ids:
        rows = db.table("entity_to_entity_relationships").select("*").eq("firm_id", firm_id).or_(
            f"from_entity_id.eq.{eid},to_entity_id.eq.{eid}"
        ).execute().data or []
        e2e_rels.extend(rows)

    sec185_loans = db.table("loans").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("section_185_flagged", True).execute().data or []

    # Transfer pricing threshold: Sec 92 IT Act — international related party > ₹1 crore
    tp_rows = db.table("loans").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("loan_type", "inter_company").gte("principal_paise", TRANSFER_PRICING_THRESHOLD_PAISE).execute().data or []

    return api_response(True, {
        "client_id":              client_id,
        "related_parties":        related_parties,
        "related_party_count":    len(related_parties),
        "entity_to_entity_rels":  e2e_rels,
        "section_185_loans":      sec185_loans,
        "transfer_pricing_flags": tp_rows,
        "transfer_pricing_count": len(tp_rows),
        "disclosure_required":    len(related_parties) > 0,
    })
