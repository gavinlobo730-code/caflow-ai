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
from pydantic import BaseModel, Field, field_validator
from typing import Annotated, ClassVar, FrozenSet, Optional
from datetime import datetime, timezone
import uuid

from models.common import api_response
from core.authz import (
    assert_client_access, can_access_client, effective_client_ids, filter_by_client, is_firmwide,
    firmwide_roles_label,
)
from core.permissions import rbac
from services.audit_service import audited
from services.timeline_service import timeline_service
from domain.money_sentence import rupee_whole_text
from core import db_provider
from core.db_paging import fetch_all, fetch_all_ordered, fetch_window
from core.list_window import probe, split
from core.db_provider import privileged_for
from models.iso_date import OptionalIsoDate, PatchIsoDate
from models.clearable import drop_empty, patch_dict, removed_identifier_problem
from core.observability import capture_soft_failure

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# This router's tables split cleanly in two, and the split is the whole design:
#
#   FIRM-LEVEL, no client column at all — `entities` (a person or company the
#   firm knows about), `entity_relationships` and
#   `entity_to_entity_relationships` (entity↔entity edges). Deliberately shared
#   ACROSS clients: that sharing is what makes cross-client match detection
#   possible at all. Exempt, with the reason and the open question recorded in
#   the audit doc — see the note on `get_entity` below for the part of it that
#   is NOT exempt.
#
#   CLIENT-BEARING — `entity_roles` (client_id NOT NULL: "this person is a
#   Director AT this client"), `loans`, `properties`, and above all
#   `cross_client_matches`, whose every row names **two** clients.
#
# A cross-client match is the sharpest row in the sweep so far: its entire
# content is "this PAN appears at client A and at client B". Firm-scoping alone
# handed an Executive assigned to client A the existence of client B and a named
# person's connection to it. Both ends are checked — not either.

def _match_visible(current_user: dict, match: dict) -> bool:
    """A cross-client match is visible only if BOTH its clients are.

    Not either: the row exists to say that two named clients share a person, so
    seeing it with only one end authorised still discloses the other end.
    """
    return (can_access_client(current_user, match.get("client_id_a"))
            and can_access_client(current_user, match.get("client_id_b")))


def _assert_role_scope(current_user: dict, role: Optional[dict]) -> dict:
    """Check the client on an entity_role the caller has already loaded."""
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    assert_client_access(current_user, role.get("client_id"), detail="Role not found")
    return role


# ─── In-memory mock stores ────────────────────────────────────────────────────

_MOCK_ENTITIES:              list[dict] = []
_MOCK_ENTITY_ROLES:          list[dict] = []
_MOCK_RELATIONSHIPS:         list[dict] = []
_MOCK_CROSS_MATCHES:         list[dict] = []
_MOCK_ENTITY_TO_ENTITY_RELS: list[dict] = []
_MOCK_LOANS:                 list[dict] = []
_MOCK_PROPERTIES:            list[dict] = []

# Related-party loans live in their own table (migration 273). They are NOT
# public.loans: that is a client's own borrowings register (lender_name,
# account_number, emi_paise, outstanding_paise) which the browser reads and
# writes directly from /accounting/loans. This router wrote to it for a long
# time and never once succeeded -- it names entity_id, sanction_date and the
# two section flags, none of which that table has, and loan_type values its
# CHECK rejects.
LOANS_TABLE = "related_party_loans"


_db = db_provider.request_db_or_none


# ── Which entities a caller may see (POST-A-544) ──────────────────────────────
# The register has no client column, by design (the note at the top of this file), so until 21-11-2026 every member of staff
# read every person and company the firm knows, with PAN and email: an Executive assigned to one client could read the
# directors and shareholders of every other. The rule now, for a caller who is not firm-wide:
#
#   an entity is VISIBLE if it holds a role at one of the caller's clients, or holds NO role at all.
#
# The second half is what lets a person create an entity and then attach it: between those two steps it has no role, and
# hiding it would lose it for the person who just typed it. An entity whose every role is at a client outside the caller's
# reach is hidden, and hidden means absent: not in the list, 404 by id (the same words as one that does not exist), not the
# other end of an edge, and not a thing a role, a loan or a property can be attached to.
#
# The roles are read with the PRIVILEGED client, naming the firm, and that is the point and not a shortcut: the caller's own
# read of `entity_roles` is narrowed by the database to their clients, so it cannot tell "no role anywhere" from "roles only
# where I may not look", which is exactly the distinction the rule turns on. Only ids leave this function.
#
# Match detection is untouched: it is a Partner's (it refuses anybody else above) and reads the whole register.

def _roles_of_the_firm(db, firm_id: str, entity_id: Optional[str] = None) -> list[dict]:
    """(entity_id, client_id) of every role in the firm, or of one entity. Mock mode reads the in-memory store."""
    if not db:
        return [r for r in _MOCK_ENTITY_ROLES
                if r.get("firm_id") == firm_id and (entity_id is None or r.get("entity_id") == entity_id)]

    def roles():
        q = privileged_for(db).table("entity_roles").select("id, entity_id, client_id").eq("firm_id", firm_id)
        return q.eq("entity_id", entity_id) if entity_id else q

    return fetch_all(roles, label="entity_roles.who_may_see_an_entity")


def _hidden_entity_ids(db, current_user: dict) -> Optional[set[str]]:
    """The entities this caller may not see, or None when the caller sees the whole register (firm-wide)."""
    mine = effective_client_ids(current_user)
    if mine is None:
        return None
    with_a_role: set[str] = set()
    at_mine: set[str] = set()
    for role in _roles_of_the_firm(db, current_user["firm_id"]):
        entity_id = role.get("entity_id")
        if not entity_id:
            continue
        with_a_role.add(str(entity_id))
        if str(role.get("client_id")) in mine:
            at_mine.add(str(entity_id))
    return with_a_role - at_mine


def _entity_is_hidden(db, current_user: dict, entity_id: str) -> bool:
    """Whether ONE entity is hidden from this caller: it holds roles, and none of them at a client the caller may reach."""
    mine = effective_client_ids(current_user)
    if mine is None:
        return False
    roles = _roles_of_the_firm(db, current_user["firm_id"], entity_id)
    return bool(roles) and not any(str(r.get("client_id")) in mine for r in roles)


def _assert_entity_visible(db, current_user: dict, entity_id: Optional[str], detail: str = "Entity not found") -> None:
    """404 in the words THAT DOOR gives a missing entity, so a hidden one is not confirmed to exist. No entity named: nothing
    to ask."""
    if entity_id and _entity_is_hidden(db, current_user, entity_id):
        raise HTTPException(status_code=404, detail=detail)


#: One PAN is one entity in a firm (the unique key the cross-client matching rests on), so somebody who may not see an entity
#: still cannot add it again. Without this sentence they would be told "open it instead of adding it again" about a record
#: they cannot open. It says the one thing they need (who can attach it) and nothing about which client or whose name.
PAN_HELD_OUT_OF_REACH = (
    "A person or company with this PAN is already on your firm's register, connected to a client you are not assigned to. "
    "Ask a Partner to add them to your client.")


def _refuse_a_pan_a_hidden_entity_holds(db, current_user: dict, pan: Optional[str]) -> None:
    if not pan or effective_client_ids(current_user) is None:
        return
    firm_id = current_user["firm_id"]
    if not db:
        holder = next((e for e in _MOCK_ENTITIES if e.get("firm_id") == firm_id and e.get("pan") == pan), None)
    else:
        found = privileged_for(db).table("entities").select("id").eq("firm_id", firm_id).eq("pan", pan).limit(1).execute().data or []
        holder = found[0] if found else None
    if holder and _entity_is_hidden(db, current_user, str(holder["id"])):
        raise HTTPException(status_code=409, detail=PAN_HELD_OUT_OF_REACH)


def _assert_both_ends_visible(db, current_user: dict, from_entity_id: str, to_entity_id: str) -> None:
    """An edge is written between two entities the caller can see. The words are the ones these two doors already use for
    an end that does not exist."""
    for end in (from_entity_id, to_entity_id):
        _assert_entity_visible(db, current_user, end, detail="One or both entities not found in firm")


def _edges_between_visible(db, current_user: dict, edges: list[dict]) -> list[dict]:
    """Drop an entity-to-entity edge either end of which is hidden: the edge names both."""
    hidden = _hidden_entity_ids(db, current_user)
    if not hidden:
        return edges
    return [e for e in edges
            if str(e.get("from_entity_id")) not in hidden and str(e.get("to_entity_id")) not in hidden]


# ─── Pydantic Models ──────────────────────────────────────────────────────────

def _entity_pan(v: Optional[str]) -> Optional[str]:
    """A PAN is AAAAA9999A or it is absent — never stored as typed.

    Both doors take it, create and PATCH: a validator on one door only is one
    PATCH from being none. Blank means "not recorded" (an entity may have no
    PAN on file), and a malformed value is refused rather than kept, because
    the entity graph matches people ACROSS clients on this field — a typo
    splits one director into two.
    """
    if v is None or not str(v).strip():
        return None
    from core.validators import validate_pan
    normalised = str(v).strip().upper()
    problem = validate_pan(normalised)
    if problem:
        raise ValueError(problem)
    return normalised


def _entity_gstin(v: Optional[str]) -> Optional[str]:
    """A GSTIN is a valid GSTIN or it is absent.

    The column has existed since migration 059 and neither model declared it,
    so Pydantic dropped whatever the form sent — a valid GSTIN and a malformed
    one alike vanished with no error (relationships-hub-06). Validated through
    the one authority, check digit included.
    """
    if v is None or not str(v).strip():
        return None
    from domain.gst.gstin import problem_with
    normalised = str(v).strip().upper()
    problem = problem_with(normalised)
    if problem:
        raise ValueError(problem)
    return normalised


class EntityIn(BaseModel):
    full_name: str
    entity_type: str  # Individual | Company | LLP | Partnership | Trust | HUF
    pan: Optional[str] = None
    gstin: Optional[str] = None

    @field_validator("pan", mode="before")
    @classmethod
    def pan_is_a_pan(cls, v):
        return _entity_pan(v)

    @field_validator("gstin", mode="before")
    @classmethod
    def gstin_is_a_gstin(cls, v):
        return _entity_gstin(v)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: OptionalIsoDate = None
    notes: Optional[str] = None


#: An entity's identifiers, with the words a person reads. An edit corrects one and never removes it (POST-A-399, fifth slice).
ENTITY_IDENTIFIERS = {"pan": "PAN", "gstin": "GSTIN"}
ENTITY_IDENTIFIER_WHY = "The register tells one person or company from another across the firm's clients by it."


class EntityUpdateIn(BaseModel):
    #: What an edit may CLEAR (POST-A-399, fifth slice; read through `models.clearable.patch_dict`): the contact particulars and the
    #: note, which are soft and optional. NOT the PAN or the GSTIN: the register matches one person across clients on them, so an
    #: edit corrects one and does not remove it (the route refuses in a sentence). NOT the name or the kind, which every entity has,
    #: and not the date of birth, which no screen edits.
    CLEARABLE: ClassVar[FrozenSet[str]] = frozenset({"email", "phone", "address", "notes"})

    full_name: Optional[str] = None
    entity_type: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None

    @field_validator("pan", mode="before")
    @classmethod
    def pan_is_a_pan(cls, v):
        return _entity_pan(v)

    @field_validator("gstin", mode="before")
    @classmethod
    def gstin_is_a_gstin(cls, v):
        return _entity_gstin(v)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: PatchIsoDate = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class EntityRoleIn(BaseModel):
    client_id: str
    role_type: str  # Director | Shareholder | Partner | Trustee | Proprietor | Guarantor | Authorized Signatory
    ownership_percent: Optional[float] = None  # numeric(5,2) — stored as float, displayed as percent
    effective_from: OptionalIsoDate = None
    effective_to: OptionalIsoDate = None
    notes: Optional[str] = None


class RelationshipIn(BaseModel):
    from_entity_id: str
    to_entity_id: str
    relationship_type: str  # e.g. Spouse | Parent | Child | Associated Company | Group Company
    description: Optional[str] = None
    effective_from: OptionalIsoDate = None
    effective_to: OptionalIsoDate = None


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
    effective_from: OptionalIsoDate = None
    effective_to: OptionalIsoDate = None
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
    # Bounded here so bad input is a 422 naming the field, not a 500 from the
    # table's CHECK. related_party_loans requires principal_paise > 0.
    principal_paise: int = Field(gt=0)   # integer paise — never float
    interest_rate: float    # annual % (display only — not used in calculations)
    sanction_date: OptionalIsoDate = None
    due_date: OptionalIsoDate = None
    notes: Optional[str] = None

    @field_validator("loan_type")
    @classmethod
    def loan_type_allowed(cls, v: str) -> str:
        """Mirrors the table's CHECK. Without this a typo'd loan_type reached
        Postgres and came back as an opaque 500 rather than a named field."""
        allowed = {"to_director", "from_director", "inter_company", "other"}
        if v not in allowed:
            raise ValueError(f"Invalid loan_type {v!r}. Allowed: {', '.join(sorted(allowed))}.")
        return v


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
    acquisition_date: OptionalIsoDate = None
    notes: Optional[str] = None


# ─── Entities ─────────────────────────────────────────────────────────────────

#: The most entities one read of the register may ask for. It is the register's own ceiling and not
#: `core.list_window.MAX_LIST_LIMIT`: the register screen loads the whole list at once and searches, sorts and filters it in the
#: browser, and a firm's directors, shareholders and counterparties run well past the shared 500. It is served to the screen
#: as `max_limit`, and `apps/web/lib/lists/window.ts` pins its one browser-side copy to this line.
ENTITY_LIST_MAX = 2000


def _entity_window(rows: list[dict], limit: int, *, scoped: bool = False):
    """The answer: the window, and whether the read found a row beyond it (`split` drops the probe row). `scoped` says the
    list is the caller's part of the register and not all of it, so the screen can say so in words."""
    entities, has_more = split(rows, limit)
    return api_response(True, {
        "entities": entities,
        "returned": len(entities),
        "has_more": has_more,
        "limit": limit,
        "max_limit": ENTITY_LIST_MAX,
        "scoped": scoped,
    })


@router.get("/entities")
def list_entities(
    entity_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: Annotated[int, Query(ge=1, le=ENTITY_LIST_MAX)] = 50,
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("client", "read")),
):
    """A window of the firm's entity register by name, and whether more exist beyond it. Every screen that lists the register
    used to take whatever came back as all of it (the explorer asked for 100, the ownership map took the default 50, the
    register page guessed from `rows == 2000`), so a firm with more entities had some of them missing without a word
    (POST-A-259). `has_more` comes from the read: one row more than the window is asked for and it is never returned."""
    db = _db()
    # None: the caller sees the whole register. A set (even an empty one): the caller is not firm-wide, and the answer says so.
    hidden = _hidden_entity_ids(db, current_user)
    scoped = hidden is not None
    if not db:
        result = [e for e in _MOCK_ENTITIES
                  if e.get("firm_id") == current_user["firm_id"] and str(e.get("id")) not in (hidden or ())]
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
        result = sorted(result, key=lambda e: ((e.get("full_name") or ""), str(e.get("id"))))
        return _entity_window(result[offset: offset + probe(limit)], limit, scoped=scoped)

    def register():
        q = privileged_for(db).table("entities").select("*").eq("firm_id", current_user["firm_id"])
        if entity_type:
            q = q.eq("entity_type", entity_type)
        if search:
            q = q.or_(f"full_name.ilike.%{search}%,pan.ilike.%{search}%,email.ilike.%{search}%")
        return q

    # Read in requests the server will honour: PostgREST answers at most 1,000 rows to one request and says nothing when it cuts
    # one short, so a window of up to ENTITY_LIST_MAX asked for in one range came back 1,000 long over a firm with 1,500 entities
    # and `has_more` read False because the answer was shorter than the window (POST-A-295). `id` breaks a tie between two
    # entities with one name, so the same row is never on two windows.
    if hidden:
        # THE WINDOW IS CUT AFTER THE NARROWING, NOT BEFORE. A window read from the database and narrowed afterwards comes back
        # short and says nothing (a page of 50 with 30 hidden rows is 20 rows and `has_more` False over a register that has more),
        # and the hidden ids cannot go into the query: a firm's can run to thousands, past what one request line carries. So a
        # caller with something hidden reads the matching register in the same name order and the window is taken from what is
        # left. It is a read of masters (one row per person or company the firm knows), not of transactions, and the register
        # screen already loads up to ENTITY_LIST_MAX of them at once.
        visible = [e for e in fetch_all_ordered(register, ["full_name"], label="entities.visible_to_the_caller")
                   if str(e.get("id")) not in hidden]
        return _entity_window(visible[offset: offset + probe(limit)], limit, scoped=True)
    rows = fetch_window(register, "full_name", count=probe(limit), start=offset, desc=False)
    return _entity_window(rows, limit, scoped=scoped)


@router.post("/entities")
def create_entity(
    data: EntityIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()
    _refuse_a_pan_a_hidden_entity_holds(db, current_user, data.pan)

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

    res = privileged_for(db).table("entities").insert({
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


def _refuse_a_removed_identifier(data: "EntityUpdateIn", stored: dict) -> None:
    """422 when the edit EMPTIES a PAN or a GSTIN the entity carries. One sent empty over nothing is not refused (nothing is written)."""
    problem = removed_identifier_problem(data, stored, ENTITY_IDENTIFIERS, why=ENTITY_IDENTIFIER_WHY)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: str,
    data: EntityUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    # POST-A-399. An emptied email, phone, address or note is cleared (written NULL); every other null still reads "not sent".
    update = patch_dict(data)
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    _assert_entity_visible(db, current_user, entity_id)
    if not db:
        for i, e in enumerate(_MOCK_ENTITIES):
            if e["id"] == entity_id and e.get("firm_id") == firm_id:
                _refuse_a_removed_identifier(data, e)
                _MOCK_ENTITIES[i].update(drop_empty(update, ENTITY_IDENTIFIERS))
                return api_response(True, _MOCK_ENTITIES[i])
        raise HTTPException(status_code=404, detail="Entity not found")

    existing = privileged_for(db).table("entities").select("id, pan, gstin").eq("id", entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Entity not found")
    _refuse_a_removed_identifier(data, existing)
    drop_empty(update, ENTITY_IDENTIFIERS)

    res = privileged_for(db).table("entities").update(update).eq("id", entity_id).eq("firm_id", firm_id).execute()
    return api_response(True, (res.data or [{}])[0])


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    _assert_entity_visible(db, current_user, entity_id)

    if not db:
        entity = next((e for e in _MOCK_ENTITIES if e["id"] == entity_id and e.get("firm_id") == firm_id), None)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        # The entity itself is firm-level, but its ROLES each name a client:
        # "this person is a Director at client B" is client B's business.
        roles = filter_by_client(current_user, [
            r for r in _MOCK_ENTITY_ROLES
            if r.get("entity_id") == entity_id and r.get("firm_id") == firm_id])
        relationships = [
            r for r in _MOCK_RELATIONSHIPS
            if (r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id) and r.get("firm_id") == firm_id
        ]
        return api_response(True, {**entity, "roles": roles,
                                   "relationships": _edges_between_visible(db, current_user, relationships)})

    entity = privileged_for(db).table("entities").select("*").eq("id", entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    roles = filter_by_client(current_user, db.table("entity_roles").select("*").eq("entity_id", entity_id).eq("firm_id", firm_id).execute().data or [])
    relationships = privileged_for(db).table("entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute().data or []

    return api_response(True, {**entity, "roles": roles,
                               "relationships": _edges_between_visible(db, current_user, relationships)})


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

    # task #231 audit finding: client_id was caller-supplied and inserted
    # unchecked — a role could be planted cross-referencing another firm's
    # real client_id. Checked before the mock branch below (like
    # customers.py/vendors.py's identical fix) so it applies regardless of
    # whether this deployment is running against mock data or a real DB.
    assert_client_access(current_user, data.client_id)
    _assert_entity_visible(db, current_user, entity_id)

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

    entity = privileged_for(db).table("entities").select("id, full_name").eq("id", entity_id).eq("firm_id", firm_id).maybe_single().execute().data
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
        target = next((r for r in _MOCK_ENTITY_ROLES if r["id"] == role_id and r.get("firm_id") == firm_id), None)
        # The role names a client (client_id NOT NULL, migration 059) — deleting
        # "X is a Director at client B" is editing client B's record.
        _assert_role_scope(current_user, target)
        _MOCK_ENTITY_ROLES = [r for r in _MOCK_ENTITY_ROLES if r["id"] != role_id]
        return api_response(True, {"deleted": True, "role_id": role_id})

    existing = db.table("entity_roles").select("id, client_id").eq("id", role_id).eq("firm_id", firm_id).maybe_single().execute().data
    _assert_role_scope(current_user, existing)

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
    _assert_both_ends_visible(db, current_user, data.from_entity_id, data.to_entity_id)

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
        from_e_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.from_entity_id and e.get("firm_id") == firm_id), None)
        to_e_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.to_entity_id and e.get("firm_id") == firm_id), None)
        if not from_e_mock or not to_e_mock:
            raise HTTPException(status_code=404, detail="One or both entities not found in firm")
        _MOCK_RELATIONSHIPS.append(row)
        timeline_service.log(
            data.from_entity_id, "lifecycle", "Relationship Added",
            f"Relationship {data.relationship_type} created", "info",
            firm_id=firm_id,
        )
        return api_response(True, row)

    from_e = privileged_for(db).table("entities").select("id").eq("id", data.from_entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    to_e   = privileged_for(db).table("entities").select("id").eq("id", data.to_entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    if not from_e or not to_e:
        raise HTTPException(status_code=404, detail="One or both entities not found in firm")

    res = privileged_for(db).table("entity_relationships").insert(row).execute()
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
    _assert_entity_visible(db, current_user, entity_id)

    if not db:
        result = [
            r for r in _MOCK_RELATIONSHIPS
            if (r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id)
            and r.get("firm_id") == firm_id
        ]
        return api_response(True, _edges_between_visible(db, current_user, result))

    res = privileged_for(db).table("entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute()
    return api_response(True, _edges_between_visible(db, current_user, res.data or []))


# ─── Cross-Client Matches ─────────────────────────────────────────────────────

@router.get("/cross-client-matches")
def list_cross_client_matches(
    entity_id: Optional[str] = Query(None),
    reviewed: Optional[bool] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    # entity_id (Entity Detail's "Cross-Client Matches" tab) wants the full
    # match history for one entity, confirmed/dismissed included — it renders
    # a Status badge for all three states, not just pending ones — so it
    # intentionally bypasses the reviewed filter rather than combining with
    # it. Without entity_id (the firm-wide listing pages), reviewed defaults
    # to unreviewed-only; `elif reviewed:` / `else:` (not `elif reviewed is
    # None:` / `elif reviewed:`) is required so an EXPLICIT reviewed=false
    # still lands on the unreviewed branch instead of falling through both
    # elifs unfiltered — `False` is falsy, so a plain `elif reviewed:` never
    # matches it and previously left the query with no reviewed filter at all.
    if not db:
        result = [m for m in _MOCK_CROSS_MATCHES if m.get("firm_id") == firm_id]
        if entity_id:
            result = [m for m in result if m.get("entity_id") == entity_id]
        elif reviewed:
            result = [m for m in result if m.get("reviewed")]
        else:
            result = [m for m in result if not m.get("reviewed")]
        return api_response(True, [m for m in result if _match_visible(current_user, m)])

    q = db.table("cross_client_matches").select("*").eq("firm_id", firm_id)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    elif reviewed:
        q = q.eq("reviewed", True)
    else:
        q = q.eq("reviewed", False)
    res = q.order("created_at", desc=True).execute()
    return api_response(True, [m for m in (res.data or [])
                               if _match_visible(current_user, m)])


@router.post("/cross-client-matches/detect")
def detect_cross_client_matches(
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Scan entities for cross-client PAN/email matches.
    For each entity with a PAN, find other entity_roles sharing the same PAN
    across different client_ids. Insert cross_client_matches rows (skip duplicates).
    """
    # A firm-WIDE scan: it reads every entity_role in the firm and writes match
    # rows pairing clients. There is no honest partial version — running it over
    # one Executive's book and calling the result "the firm's cross-client
    # matches" would be worse than refusing, because the gaps are invisible.
    # 403, not the 404 used for a row: no id is involved and nothing is hidden.
    if not is_firmwide(current_user):
        raise HTTPException(
            status_code=403,
            detail=f"Cross-client match detection scans every client in the firm "
                   f"and is limited to {firmwide_roles_label()}.")
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        pan_map: dict[str, list[dict]] = {}
        for role in _MOCK_ENTITY_ROLES:
            if role.get("firm_id") != firm_id:
                continue
            entity = next((e for e in _MOCK_ENTITIES if e["id"] == role.get("entity_id") and e.get("firm_id") == firm_id), None)
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
                        m.get("firm_id") == firm_id
                        and m.get("match_value") == pan
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

    entities_with_pan = privileged_for(db).table("entities").select("id, pan, full_name").eq("firm_id", firm_id).not_.is_("pan", "null").execute().data or []

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
                except Exception as swallowed:
                    capture_soft_failure(swallowed, operation="relationships.cross_client_match_insert", firm_id=firm_id)

    return api_response(True, {"new_matches_detected": new_count})


@router.patch("/cross-client-matches/{match_id}/review")
@audited("cross_client_match", "review")
def review_cross_client_match(
    match_id: str,
    data: CrossMatchReviewIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        for i, m in enumerate(_MOCK_CROSS_MATCHES):
            if m["id"] == match_id and m.get("firm_id") == firm_id:
                if not _match_visible(current_user, m):
                    break
                _MOCK_CROSS_MATCHES[i]["reviewed"] = True
                _MOCK_CROSS_MATCHES[i]["confirmed"] = data.is_confirmed
                return api_response(True, _MOCK_CROSS_MATCHES[i])
        raise HTTPException(status_code=404, detail="Match not found")

    # client_id_a/client_id_b are selected so the check below has both ends —
    # confirming a match is a judgement recorded against two named clients.
    existing = db.table("cross_client_matches").select("id, client_id_a, client_id_b").eq("id", match_id).eq("firm_id", firm_id).maybe_single().execute().data
    if not existing or not _match_visible(current_user, existing):
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
@audited("entity_relationship", "create")
def create_entity_to_entity_relationship(
    data: EntityToEntityRelIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a holding/subsidiary/associate/JV relationship between two entities."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()
    _assert_both_ends_visible(db, current_user, data.from_entity_id, data.to_entity_id)

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
        from_e_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.from_entity_id and e.get("firm_id") == firm_id), None)
        to_e_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.to_entity_id and e.get("firm_id") == firm_id), None)
        if not from_e_mock or not to_e_mock:
            raise HTTPException(status_code=404, detail="One or both entities not found in firm")
        _MOCK_ENTITY_TO_ENTITY_RELS.append(row)
        return api_response(True, row)

    # task #231 audit finding: unlike create_relationship immediately above
    # this in the same file, this endpoint inserted from_entity_id/to_entity_id
    # with NO ownership check at all — mirror that endpoint's exact guard.
    from_e = privileged_for(db).table("entities").select("id").eq("id", data.from_entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    to_e   = privileged_for(db).table("entities").select("id").eq("id", data.to_entity_id).eq("firm_id", firm_id).maybe_single().execute().data
    if not from_e or not to_e:
        raise HTTPException(status_code=404, detail="One or both entities not found in firm")

    res = privileged_for(db).table("entity_to_entity_relationships").insert(row).execute()
    return api_response(True, (res.data or [row])[0])


@router.get("/entity-to-entity")
def list_entity_to_entity_relationships(
    entity_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]
    _assert_entity_visible(db, current_user, entity_id)

    if not db:
        result = [
            r for r in _MOCK_ENTITY_TO_ENTITY_RELS
            if (r.get("from_entity_id") == entity_id or r.get("to_entity_id") == entity_id)
            and r.get("firm_id") == firm_id
        ]
        return api_response(True, _edges_between_visible(db, current_user, result))

    res = privileged_for(db).table("entity_to_entity_relationships").select("*").eq("firm_id", firm_id).or_(
        f"from_entity_id.eq.{entity_id},to_entity_id.eq.{entity_id}"
    ).execute()
    return api_response(True, _edges_between_visible(db, current_user, res.data or []))


# ─── Loan Intelligence ────────────────────────────────────────────────────────
# Section 185 Companies Act: loans/advances to directors — requires CA review
# Section 186 Companies Act: loans to other companies — requires CA review

@router.post("/loans")
@audited("related_party_loan", "create")
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

    # task #231 audit finding: client_id/entity_id were both caller-supplied
    # and inserted unchecked — a loan record could be planted cross-referencing
    # another firm's real client_id/entity_id.
    assert_client_access(current_user, data.client_id)
    _assert_entity_visible(db, current_user, data.entity_id, detail="Entity not found in firm")
    if db:
        entity = privileged_for(db).table("entities").select("id").eq("id", data.entity_id).eq("firm_id", firm_id).maybe_single().execute().data
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found in firm")
    else:
        entity_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.entity_id and e.get("firm_id") == firm_id), None)
        if not entity_mock:
            raise HTTPException(status_code=404, detail="Entity not found in firm")

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
        # FKs to public.users.id (the internal id), never the Supabase auth id.
        "created_by":            current_user.get("id"),
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
                f"Principal: {rupee_whole_text(data.principal_paise)}",
                "warning", firm_id=firm_id,
            )
        return api_response(True, row)

    res = db.table(LOANS_TABLE).insert(row).execute()
    created = (res.data or [row])[0]

    if section_185_flagged:
        timeline_service.log(
            data.client_id, "compliance", "Section 185 Flag",
            f"Loan to director flagged under Section 185 Companies Act. "
            f"Principal: {rupee_whole_text(data.principal_paise)}",
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
    if client_id:
        # Module 9 assignment-scoping: an Executive/Reviewer must not read
        # Section 185/186 loan data for a client in their own firm that they
        # aren't assigned to — role-only rbac() doesn't enforce this, only
        # assert_client_access does.
        assert_client_access(current_user, client_id)

    if not db:
        result = [l for l in _MOCK_LOANS if l.get("firm_id") == firm_id]
        if client_id:
            result = [l for l in result if l.get("client_id") == client_id]
        if flagged_only:
            result = [l for l in result if l.get("section_185_flagged") or l.get("section_186_flagged")]
        return api_response(True, filter_by_client(current_user, result))

    q = db.table(LOANS_TABLE).select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if flagged_only:
        q = q.or_("section_185_flagged.eq.true,section_186_flagged.eq.true")
    res = q.order("created_at", desc=True).execute()
    # With no client named this is every related-party loan of the firm, and each row names a client. The database's own
    # rule narrows it when the server reads as the caller; this is the second lock, so the answer does not depend on which
    # client the server happened to read with (POST-A-543). A Partner's list is unchanged.
    return api_response(True, filter_by_client(current_user, res.data or []))


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
    if client_id:
        assert_client_access(current_user, client_id)

    if not db:
        result = [l for l in _MOCK_LOANS if l.get("section_185_flagged") and l.get("firm_id") == firm_id]
        if client_id:
            result = [l for l in result if l.get("client_id") == client_id]
        result = filter_by_client(current_user, result)
        total_paise = sum(l["principal_paise"] for l in result)
        return api_response(True, {
            "flagged_loans": result,
            "count": len(result),
            "total_principal_paise": total_paise,  # integer paise
        })

    q = db.table(LOANS_TABLE).select("*").eq("firm_id", firm_id).eq("section_185_flagged", True)
    if client_id:
        q = q.eq("client_id", client_id)
    # Narrowed BEFORE the count and the total are taken, so a member of staff is not told how many flagged loans, or how
    # much principal, sit at clients they are not assigned to (POST-A-543).
    rows = filter_by_client(current_user, q.execute().data or [])
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
@audited("property", "create")
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

    # task #231 audit finding: client_id/entity_id were both caller-supplied
    # and inserted unchecked — a property record could be planted
    # cross-referencing another firm's real client_id/entity_id.
    assert_client_access(current_user, data.client_id)
    _assert_entity_visible(db, current_user, data.entity_id, detail="Entity not found in firm")
    if db and data.entity_id:
        entity = privileged_for(db).table("entities").select("id").eq("id", data.entity_id).eq("firm_id", firm_id).maybe_single().execute().data
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found in firm")
    elif not db and data.entity_id:
        entity_mock = next((e for e in _MOCK_ENTITIES if e["id"] == data.entity_id and e.get("firm_id") == firm_id), None)
        if not entity_mock:
            raise HTTPException(status_code=404, detail="Entity not found in firm")

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
    if client_id:
        assert_client_access(current_user, client_id)

    if not db:
        result = [p for p in _MOCK_PROPERTIES if p.get("firm_id") == firm_id]
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

@router.get("/roles")
def list_client_roles(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Every entity role recorded at one client, with the entity's own details.

    ⚠️ THIS ENDPOINT DID NOT EXIST, AND THAT IS WHY THE SCREEN SHOWED NOTHING.
    `/clients/{id}/relationships` declared `roles` state, rendered
    "Associated Entities (0)" from it and NEVER FETCHED IT — its `loadAll`
    read only `cross_client_matches`. So a CA who linked a director saw the
    row until they refreshed, and then it was gone. There was no API to fetch
    them from: `entity_roles` has no client-scoped list route, and the row
    carries only an `entity_id`, so even a direct read would have rendered a
    UUID where a name belongs.

    The entity is joined SERVER-SIDE, in one `.in_()` rather than one query
    per role, so the name reaches the note and the screen from the same place.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        return api_response(True, _mock_roles(firm_id, client_id))

    from services.related_party_service import RelatedPartyService
    return api_response(True, RelatedPartyService(db).roles_for_client(firm_id, client_id))


def _mock_roles(firm_id: str, client_id: str) -> list[dict]:
    """The same shape the service builds, off the in-memory stores."""
    by_id = {e["id"]: e for e in _MOCK_ENTITIES if e.get("firm_id") == firm_id}
    out = []
    for r in _MOCK_ENTITY_ROLES:
        if r.get("firm_id") != firm_id or r.get("client_id") != client_id:
            continue
        e = by_id.get(r.get("entity_id")) or {}
        out.append({
            **r,
            "entity_name": e.get("full_name"),
            "entity_type": e.get("entity_type"),
            "pan": e.get("pan"),
            "email": e.get("email"),
        })
    out.sort(key=lambda r: ((r.get("role") or ""), (r.get("entity_name") or "")))
    return out


@router.get("/related-party-report")
def related_party_report(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """The AS 18 related-party note, for review.

    ⚠️ THIS ENDPOINT HAD NO CALLER ANYWHERE IN `apps/web` — built, mounted and
    reachable by nobody, the `capital_wip` shape. What it computed could not
    have been rendered either: it returned raw `entity_roles` rows carrying an
    `entity_id` and no name, so the note would have listed UUIDs.

    AND IT DROPPED REAL RELATED PARTIES IN SILENCE. Its test was a literal set
    of six role names against a screen that offers eleven, so a **Karta of an
    HUF**, a **Proprietor** and a **Beneficiary** never appeared. A note that
    omits a related party is a WRONG disclosure, which is worse than none.

    `domain/related_party/disclosure.py` is the authority now — three answers
    per role rather than in-or-out, a shareholder decided on their holding
    rather than their label, and every party's transactions matched on PAN
    against the customer and vendor masters. `services/related_party_service`
    fetches. This decides nothing either of them decides.

    Prepare-only. Nothing is filed, signed or posted.
    """
    assert_client_access(current_user, client_id)
    db = _db()
    firm_id = current_user["firm_id"]

    from domain.related_party.disclosure import Party, build, standing_for
    from services.related_party_service import as_payload

    if not db:
        parties = []
        for r in _mock_roles(firm_id, client_id):
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
        entity_ids = {p.entity_id for p in parties}
        return api_response(True, as_payload(build(
            client_id=client_id,
            parties=parties,
            section_185_loans=[
                l for l in _MOCK_LOANS
                if l.get("firm_id") == firm_id and l.get("client_id") == client_id
                and l.get("section_185_flagged")
            ],
            entity_relationships=[
                r for r in _MOCK_ENTITY_TO_ENTITY_RELS
                if r.get("firm_id") == firm_id
                and (r.get("from_entity_id") in entity_ids
                     or r.get("to_entity_id") in entity_ids)
            ],
            extra_gaps=[
                "Transactions are not matched here because no database is "
                "connected, so no figures are shown against any party."
            ],
        )))

    from services.related_party_service import RelatedPartyService
    return api_response(True, as_payload(
        RelatedPartyService(db).disclosure(firm_id, client_id)
    ))
