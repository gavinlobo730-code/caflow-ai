"""
Role-Based Access Control for CAflow AI.
Roles: Partner > Manager > Executive > Reviewer > Client

Usage in routers:
    from core.permissions import rbac

    @router.get("/foo")
    def list_foo(current_user: dict = Depends(rbac("resource", "read"))):
        ...
"""
from enum import Enum
from typing import Callable
from fastapi import Depends, HTTPException, status
from core.exceptions import PermissionDeniedError


class Role(str, Enum):
    PARTNER   = "Partner"
    MANAGER   = "Manager"
    EXECUTIVE = "Executive"
    REVIEWER  = "Reviewer"
    CLIENT    = "Client"


# Role hierarchy — index 0 = least privileged
ROLE_HIERARCHY = [Role.CLIENT, Role.REVIEWER, Role.EXECUTIVE, Role.MANAGER, Role.PARTNER]

# M1 Role Model Unification — single canonical vocabulary is the Role enum above.
# Legacy/foreign role strings (from the old frontend type and DB CHECK constraints in
# migrations 001/021/022) are mapped to canonical roles so existing rows keep working
# during/after migration 081. Mapping rationale:
#   owner            -> Partner   (firm owner)
#   admin            -> Manager   (admin access level)
#   article / staff  -> Executive (delivery staff)
#   viewer           -> Reviewer  (read/approve-only)
LEGACY_ROLE_MAP = {
    "owner":   Role.PARTNER,
    "admin":   Role.MANAGER,
    "article": Role.EXECUTIVE,
    "staff":   Role.EXECUTIVE,
    "viewer":  Role.REVIEWER,
}

_ALL_STAFF = {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE, Role.REVIEWER}
_AT_LEAST_EXECUTIVE = {Role.PARTNER, Role.MANAGER, Role.EXECUTIVE}
_AT_LEAST_MANAGER   = {Role.PARTNER, Role.MANAGER}
_PARTNER_ONLY       = {Role.PARTNER}


# Permission matrix — resource -> action -> set of roles allowed
PERMISSIONS: dict[str, dict[str, set[str]]] = {
    # ── Firm administration ──────────────────────────────────────────────────
    "firm": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
        "admin":  _PARTNER_ONLY,
    },
    # ── Identity (self-service) ──────────────────────────────────────────────
    # login/logout events the frontend records for the CALLER, about the caller.
    # Every staff role must be able to write its own, so this is _ALL_STAFF —
    # it is telemetry, not a privilege. Modelled as its own resource rather than
    # borrowed from "team" (Partner-only write) or left on "ai" (read, and the
    # wrong subject entirely), so the guard states what it actually protects.
    "identity": {
        "write":  _ALL_STAFF,
    },
    # ── Clients ──────────────────────────────────────────────────────────────
    "client": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_MANAGER,
        "delete": _PARTNER_ONLY,
    },
    # ── Practice (firm-as-internal-client) — Partner/Owner only (Amendment v1.1, G1) ─
    "practice": {
        "read":  _PARTNER_ONLY,
        "write": _PARTNER_ONLY,
    },
    # ── Billing / Revenue Operations — Partner/Owner only (exposes fee economics) ─
    "billing": {
        "read":  _PARTNER_ONLY,
        "write": _PARTNER_ONLY,
    },
    # ── Knowledge Base articles (Amendment v1.1 Batch 6) ─────────────────────
    # Read by all staff (client-scoped rows further assignment-gated in service/RLS);
    # authoring governed: Manager+.
    "knowledge": {
        "read":  _ALL_STAFF,
        "write": _AT_LEAST_MANAGER,
    },
    # ── Client instructions — read all staff (assignment-gated); write Executive+
    # (Executive only for assigned clients, enforced in service/RLS). Reviewer read-only.
    "client_instruction": {
        "read":  _ALL_STAFF,
        "write": _AT_LEAST_EXECUTIVE,
    },
    # ── Compliance records ───────────────────────────────────────────────────
    "compliance_record": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
        "delete": _PARTNER_ONLY,
    },
    # ── Compliance (generic alias used by document_intelligence_v2 and notices) ─
    "compliance": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
        "delete": _PARTNER_ONLY,
    },
    # ── Tasks ────────────────────────────────────────────────────────────────
    "task": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "delete": _AT_LEAST_MANAGER,
    },
    # ── Documents ────────────────────────────────────────────────────────────
    "document": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_EXECUTIVE,
        "approve": {Role.PARTNER, Role.MANAGER, Role.REVIEWER},
        "delete": _PARTNER_ONLY,
    },
    # ── Client activity timeline ─────────────────────────────────────────────
    # An append-only record of work that ALREADY happened: a journal posted, a
    # document uploaded, a compliance record updated. Each of those actions has
    # its own guard, and the least privileged of them (document:approve) admits
    # Reviewer — so gating the LOG more tightly than the action it records would
    # simply break logging for work the person was entitled to do.
    # Write only: `client_timeline_events` has no UPDATE or DELETE grant for
    # `authenticated` at all, so history cannot be rewritten from a browser.
    "timeline": {
        "write":  _ALL_STAFF,
        # No DELETE grant exists for `authenticated` on client_timeline_events,
        # so this is belt-and-braces — but if one is ever added, erasing a
        # client's activity history should be the most restricted act on the
        # table, not inherit the permissive write tier above.
        "delete": _PARTNER_ONLY,
    },
    # ── Team management ──────────────────────────────────────────────────────
    "team": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
        "delete": _PARTNER_ONLY,
    },
    # ── Reports / dashboards / insights ─────────────────────────────────────
    "report": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_MANAGER,
        "export": _AT_LEAST_MANAGER,
    },
    # ── Settings / automation ────────────────────────────────────────────────
    "settings": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _PARTNER_ONLY,
    },
    # ── DSC (Digital Signature Certificate) tracker ──────────────────────────
    # All staff may read the firm's DSC inventory; Partner/Manager manage
    # (create / renew / soft-delete) certificates.
    "dsc": {
        "read":   _ALL_STAFF,
        "write":  _AT_LEAST_MANAGER,
        "delete": _AT_LEAST_MANAGER,
    },
    # ── Accounting ───────────────────────────────────────────────────────────
    "accounting": {
        "read":   _AT_LEAST_EXECUTIVE,
        "write":  _AT_LEAST_MANAGER,
        "approve": _PARTNER_ONLY,   # post/approve journal entry
    },
    # ── Banking — deliberately looser than `accounting`, and the reason matters.
    # Categorising a bank statement is the work a practice HIRES someone to do:
    # mechanical, high-volume, and reversible (a correction is an append-only
    # reversal, and a transaction can be unmatched and re-posted). Routing it
    # through accounting.write/approve meant a Partner personally approving every
    # statement line — 15,000 a month across 50 clients — which is not review, it
    # is rubber-stamping.
    #
    # A MANUAL journal stays Partner-only, because that is judgement rather than
    # clerical. That distinction is the whole point of this resource existing.
    "banking": {
        "read":   _AT_LEAST_EXECUTIVE,
        "write":  _AT_LEAST_EXECUTIVE,   # import, categorise, match, post, exclude
        "approve": _AT_LEAST_MANAGER,    # sign off a reconciliation
    },
    # ── GST (compute, validate, approve for filing) ──────────────────────────
    "gst": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── TDS ──────────────────────────────────────────────────────────────────
    "tds": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        # Recording the firm's reading of a DTAA article (migration 310) is a
        # professional position the firm withholds tax on and defends to an
        # assessing officer, not a preference. MANAGER, deliberately the same
        # tier as dtaa_treaty_rates' RESTRICTIVE RLS policies — the app-layer
        # check is the primary control and RLS is defence in depth (CLAUDE.md),
        # so the two disagreeing would mean one of them is decorative.
        "write":   _AT_LEAST_MANAGER,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── Income Tax ───────────────────────────────────────────────────────────
    "income_tax": {
        "read":    _ALL_STAFF,
        "compute": _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── Notifications (every authenticated staff member can read/mark own) ───
    "notification": {
        "read":  _ALL_STAFF,
        "write": _ALL_STAFF,
    },
    # ── Workflows ────────────────────────────────────────────────────────────
    "workflow": {
        "read":       _ALL_STAFF,
        "instantiate": _AT_LEAST_EXECUTIVE,
    },
    # ── Risks ────────────────────────────────────────────────────────────────
    "risk": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # ── AI assistant ─────────────────────────────────────────────────────────
    "ai": {
        "read":     _ALL_STAFF,       # general assistant (Reviewer can ask questions)
        "copilot":  _AT_LEAST_MANAGER,  # firm-context AI (sees client list, risks)
    },
    # ── Automation engine ────────────────────────────────────────────────────
    "automation": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
    # ── Reminders ────────────────────────────────────────────────────────────
    "reminder": {
        "read":  _ALL_STAFF,
        "write": _AT_LEAST_EXECUTIVE,
    },
    # ── MCA / ROC filings ────────────────────────────────────────────────────
    "mca": {
        "read":    _ALL_STAFF,
        "write":   _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,   # CGST/CA rules: Partner or Manager can approve MCA filings
    },
    # ── Year End Engagements (Schedule III, audit pack, adjustments) ───────────
    "year_end": {
        "read":          _AT_LEAST_EXECUTIVE,
        "write":         _AT_LEAST_EXECUTIVE,
        "approve":       _AT_LEAST_MANAGER,   # approve adjustments, lock notes
        "final_approve": _PARTNER_ONLY,       # Partner-only: lock engagement
    },
    # ── XBRL Engine ──────────────────────────────────────────────────────────
    "xbrl": {
        "read":    _AT_LEAST_EXECUTIVE,
        "write":   _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── E-Invoice ────────────────────────────────────────────────────────────
    "einvoice": {
        "read":    _ALL_STAFF,
        "write":   _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── E-Way Bill ───────────────────────────────────────────────────────────
    "eway_bill": {
        "read":    _ALL_STAFF,
        "write":   _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
    },
    # ── Tally Migration ──────────────────────────────────────────────────────
    "tally_migration": {
        "read":    _AT_LEAST_MANAGER,
        "write":   _AT_LEAST_MANAGER,
        "approve": _PARTNER_ONLY,
    },
    # ── M1 phantom-resource fixes ────────────────────────────────────────────
    # These resources were referenced by rbac() in routers but had NO entry here,
    # so can() fail-closed → every guarded endpoint returned 403 for ALL roles
    # (including Partner). Definitions below restore correct behaviour.
    #
    # Analytics / executive dashboards (firm-level metrics) — Manager+.
    "analytics": {
        "read":   _AT_LEAST_MANAGER,
        "write":  _AT_LEAST_MANAGER,
        "export": _AT_LEAST_MANAGER,
    },
    # AI Copilot (firm-context AI — sees client list / risks). Manager+ for now,
    # mirroring the existing "ai":"copilot" intent. Per-client assignment gating
    # is deferred to Module 9.0/M5 (AI-context security); until then keep it to
    # Manager+ rather than re-opening it to all staff.
    "copilot": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # Fee engagements / proposals / engagement letters — Manager+.
    "engagement": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # Sales/client invoices (accounting domain).
    "invoice": {
        "read":    _AT_LEAST_EXECUTIVE,
        "write":   _AT_LEAST_EXECUTIVE,
        "approve": _AT_LEAST_MANAGER,
        "delete":  _PARTNER_ONLY,
    },
    # Payroll — salary data is sensitive. Manager+ to run; Partner-only to
    # finalise, and Partner-only to switch payroll ON for a client at all.
    #
    # `enable` is separate from `write` because it is a different KIND of
    # decision: writing payroll is running the month, enabling it commits the
    # firm to running payroll for a client — the cost brake in
    # docs/architecture/10-payroll.md, and what the subscription is sized on.
    # A Manager agreeing an input cut-off is doing their job; a Manager adding
    # a payroll client is making a commercial commitment. Migration 332 also
    # takes the column away from the browser entirely, so this is the one door.
    "payroll": {
        "read":     _AT_LEAST_MANAGER,
        "write":    _AT_LEAST_MANAGER,
        "enable":   _PARTNER_ONLY,
        "finalize": _PARTNER_ONLY,
    },
    # Time tracking — staff log/read their own time; firm-level reports Manager+.
    "time_entry": {
        "read":   _ALL_STAFF,
        "write":  _ALL_STAFF,
        "report": _AT_LEAST_MANAGER,
        "delete": _AT_LEAST_MANAGER,
    },
    # Team workload / capacity views — Manager+.
    "workload": {
        "read":  _AT_LEAST_MANAGER,
        "write": _AT_LEAST_MANAGER,
    },
    # ── Client portal (CA-facing management of a client's portal) ─────────────
    # Staff manage portal document-requests/messages/dues. NOT for the Client role
    # (clients use the separate external /portal surface). Closes the previously
    # unauthenticated /api/portal/* endpoints.
    "portal": {
        "read":  _ALL_STAFF,
        "write": _AT_LEAST_EXECUTIVE,
    },
    # ── Client assignments (Module 9.0 M3) — Partner administers; Manager+ may view ─
    "assignment": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
    # ── Governance approvals (Module 9.0 M4) — maker/checker ─────────────────
    # request: any staff may submit (maker). approve: Partner-only (checker).
    # read: Manager+ (the approval inbox).
    "approval": {
        "request": _AT_LEAST_EXECUTIVE,
        "read":    _AT_LEAST_MANAGER,
        "approve": _PARTNER_ONLY,
    },
    # ── Firm Branding & Document Customization ────────────────────────────────
    # Branding (logo, colors, invoice templates, email templates) affects all
    # documents the firm sends to clients. Partner-only writes; Manager+ reads.
    "branding": {
        "read":  _AT_LEAST_MANAGER,
        "write": _PARTNER_ONLY,
    },
}


# ── Core helpers ─────────────────────────────────────────────────────────────

def _to_role(role: str) -> Role:
    """Normalize a role string to the canonical Role enum.

    Accepts any case ('partner' → Role.PARTNER) and maps legacy/foreign role
    strings (owner/admin/article/staff/viewer) to their canonical equivalent so
    rows written under older constraints (migrations 001/021/022) still authorize
    correctly. Raises ValueError on a genuinely unknown role.
    """
    if role is None:
        raise ValueError("Unknown role: None")
    # Canonical match first (case-insensitive).
    for candidate in (role, role.title(), role.capitalize()):
        try:
            return Role(candidate)
        except ValueError:
            continue
    # Legacy/foreign vocabulary.
    mapped = LEGACY_ROLE_MAP.get(role.strip().lower())
    if mapped is not None:
        return mapped
    raise ValueError(f"Unknown role: {role!r}")


def canonical_role(role: str | None) -> str | None:
    """Public, non-raising form of `_to_role` — returns the canonical role string
    ('Partner', 'Reviewer', …) or None for anything unrecognised.

    Exists so callers outside this module (the /api/identity/permissions endpoint)
    can canonicalise a stored role without importing a private helper or catching
    ValueError at every call site.
    """
    try:
        return _to_role(role).value
    except ValueError:
        return None


def can(role: str, resource: str, action: str) -> bool:
    """Return True if the ROLE DEFAULT allows this action on this resource.

    This is the TEMPLATE, not the last word. Since migration 403 a firm may
    record a per-person answer that overrides it, and `can_user` below is what
    every request actually goes through. `can` stays because two things still
    need the role's own answer with nobody in particular in mind: pre-filling a
    new member's grid, and `/api/identity/role-matrix`, which shows a Partner
    what each role grants before they start overriding it.
    """
    try:
        r = _to_role(role)
    except ValueError:
        return False
    resource_perms = PERMISSIONS.get(resource, {})
    allowed_roles = resource_perms.get(action, set())
    return r in allowed_roles


# ── Per-person access (migration 403) ────────────────────────────────────────
#
# A role is five buckets and a practice is not staffed in five buckets: one
# Executive runs GST and TDS and never touches payroll, another runs payroll and
# nothing else. Without a per-person answer the firm either promotes somebody to
# reach one screen — handing them every other screen that tier opens — or does
# the work outside the product.
#
# THE ROLE IS NOT REPLACED. It keeps answering `public.get_my_role()` in 61 RLS
# policies across 32 migrations (the control protecting the ~83 tables the
# browser reads directly over PostgREST, where rbac() never runs) and
# `core.authz._FIRMWIDE_ROLES` — which is a DIFFERENT question this grid
# deliberately does not answer: whether a person sees every client in the firm
# or only their assigned book is about SCOPE, not about which screens open, and
# folding it into the same checkbox would let a firm widen someone's client
# access while believing they had only granted them a module.
#
# THREE STATES, AND THE THIRD IS THE ABSENCE OF A ROW. No override means the
# role decides, which is exactly the behaviour every existing member has today —
# so this is inert until somebody ticks something.

#: Pairs a deny row may never take away from a Partner.
#:
#: Without this the grid is unrepairable: the one person who could restore
#: access is the person whose access was removed, and there is no second door —
#: no CLI, no break-glass endpoint, and `team:write` is the only thing that can
#: write this table. A Partner who unticks their own "Team · write" to see what
#: it does would lock the firm out of its own access control permanently.
#:
#: Deliberately applies to EVERY Partner rather than only the last one: letting
#: one Partner strip another Partner's team access is a governance dispute the
#: software should not referee silently, and "is this the last Partner" is a
#: question that needs a database read inside a function that must not make one.
UNREVOKABLE_FOR_PARTNER: frozenset[tuple[str, str]] = frozenset({
    ("team", "read"),
    ("team", "write"),
    ("firm", "read"),
    ("firm", "admin"),
})

#: Pairs whose GRANT lets the holder change what other people may do.
#:
#: Not refused — a Partner appointing a senior Manager to run the firm's access
#: is a real decision, and every practice tool allows an admin to appoint
#: another admin. Named so the Team screen can say plainly what the tick means,
#: because it otherwise looks exactly like the other thirty. `team:write` in
#: particular IS "may become a Partner": its holder can grant themselves
#: `firm:admin` and everything else.
PRIVILEGE_CHANGING: frozenset[tuple[str, str]] = frozenset({
    ("team", "write"),
    ("firm", "admin"),
    ("firm", "write"),
    ("settings", "write"),
    ("automation", "write"),
})


def is_known_permission(resource: str, action: str) -> bool:
    """True if (resource, action) is a pair PERMISSIONS actually defines.

    `user_permissions` stores the pair as free TEXT with no CHECK, because the
    vocabulary is this dict and a CHECK constraint cannot read a Python dict —
    a hand-copied list in SQL would be the second authority this codebase keeps
    having to delete. So the API door validates through here instead, and the
    resolver below ignores an unrecognised pair, which makes a stale row inert
    rather than dangerous.
    """
    return action in PERMISSIONS.get(resource, {})


def resolve_permission(
    role: str,
    overrides: dict | None,
    resource: str,
    action: str,
) -> bool:
    """The one rule: a per-person row wins, the role decides where there is none.

    `overrides` is keyed EITHER by the tuple ``(resource, action)`` or by the
    string ``"resource:action"`` — the second because the same map crosses the
    wire as JSON, where a tuple key cannot survive, and having the caller
    remember to convert is how one call site ends up silently reading nothing.

    An unknown pair falls through to the role, which fails closed for a resource
    PERMISSIONS does not define.
    """
    role_says = can(role, resource, action)
    if not is_known_permission(resource, action):
        # A pair PERMISSIONS does not define is INERT, override or not. The
        # column is free TEXT with no CHECK — the vocabulary is this dict and
        # SQL cannot read one — so a row written under an older vocabulary can
        # outlive it, and honouring one would pre-grant a `rbac("tarot","read")`
        # somebody adds to a router next year, silently, to whoever happened to
        # have the stale row. `can` already fails closed here, which is the
        # answer this returns.
        return role_says
    over = _override_for(overrides, resource, action)
    if over is None:
        return role_says
    if over is False and (resource, action) in UNREVOKABLE_FOR_PARTNER:
        # A Partner keeps the four pairs above whatever the grid says. Applied
        # here rather than refused at the write door as well as here: the write
        # door DOES refuse it (so the screen can explain), and this is the
        # backstop for a row that reached the table another way — a restored
        # backup, a hand-run UPDATE, a future importer.
        if canonical_role(role) == Role.PARTNER.value:
            return True
    return over


def _override_for(overrides: dict | None, resource: str, action: str):
    """The stored answer for one pair, or None where there is none."""
    if not overrides:
        return None
    for key in ((resource, action), f"{resource}:{action}"):
        if key in overrides:
            value = overrides[key]
            # A row's `granted` is NOT NULL, so anything else here is a caller
            # sending a shape this function does not define. Treat it as no
            # opinion rather than as a deny: inventing a refusal out of a
            # malformed value is how a permission disappears with no record of
            # anybody having removed it.
            return value if isinstance(value, bool) else None
    return None


def can_user(user: dict, resource: str, action: str) -> bool:
    """Return True if THIS PERSON may perform action on resource.

    The authority. `rbac()` goes through here, so all 1037 of its call sites
    got per-person access without changing — which is the whole reason the
    override is resolved at this seam rather than beside each guard.

    The overrides ride on `current_user` (loaded once per user per 30s by
    `core.auth._get_user_and_firm`), so this makes no database call and adds no
    Singapore-to-Mumbai round trip to any request.
    """
    return resolve_permission(
        str(user.get("role") or ""),
        user.get("permission_overrides"),
        resource,
        action,
    )


def require_permission(role: str, resource: str, action: str) -> None:
    """Raise PermissionDeniedError if role cannot perform action on resource."""
    if not can(role, resource, action):
        raise PermissionDeniedError(action, resource)


def is_at_least(role: str, minimum: str) -> bool:
    """Return True if role is at or above minimum in the hierarchy."""
    try:
        return ROLE_HIERARCHY.index(_to_role(role)) >= ROLE_HIERARCHY.index(_to_role(minimum))
    except ValueError:
        return False


def get_accessible_resources(role: str, overrides: dict | None = None) -> dict[str, list[str]]:
    """Return all resource:action pairs accessible to a role, or to a PERSON.

    With no `overrides` this is the role's own template, which is what
    `/api/identity/role-matrix` shows a Partner and what a new member's grid is
    pre-filled from. With them it is what that person may actually reach, which
    is what `/api/identity/permissions` must answer — a screen deciding whether
    to render a control from the role alone would offer an Executive granted
    payroll a screen with no button on it, and hide nothing from an Executive
    whose payroll was taken away.

    Resolved through `resolve_permission` rather than restating it, so the
    Partner floor and the tuple/string key handling cannot drift from `rbac()`.
    """
    result: dict[str, list[str]] = {}
    for resource, actions in PERMISSIONS.items():
        accessible = [
            action for action in actions
            if resolve_permission(role, overrides, resource, action)
        ]
        if accessible:
            result[resource] = accessible
    return result


# ── FastAPI Dependency factory ────────────────────────────────────────────────

def rbac(resource: str, action: str) -> Callable:
    """
    FastAPI dependency factory — validates JWT *and* enforces RBAC in one shot.

    Usage:
        @router.get("/foo")
        def list_foo(current_user: dict = Depends(rbac("client", "read"))):
            ...

    Raises 401 if no/invalid JWT, 403 if role lacks permission.
    """
    from core.auth import get_current_user  # avoid circular import at module level

    def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        # can_user, NOT can: since migration 403 a firm may record a per-person
        # answer, and this is the seam that gives all 1037 call sites of this
        # factory per-person access without one of them changing. A guard here
        # that read the role directly would be an endpoint the grid silently
        # does not govern, which is worse than no grid.
        if not can_user(current_user, resource, action):
            role = current_user.get("role", "")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                # Says "You" rather than naming the role, because the refusal may
                # now be a per-person one and blaming the role would send the
                # reader to change something that is not what refused them.
                detail=f"You cannot perform '{action}' on '{resource}'"
                       + (f" (role: {role})" if role else ""),
            )
        return current_user

    # Give the dependency a stable name so FastAPI's OpenAPI can reference it
    _dependency.__name__ = f"rbac_{resource}_{action}"
    return _dependency
