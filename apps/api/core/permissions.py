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
    # Payroll — salary data is sensitive. Manager+ to run; Partner-only to finalise.
    "payroll": {
        "read":     _AT_LEAST_MANAGER,
        "write":    _AT_LEAST_MANAGER,
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
    """Return True if role is allowed to perform action on resource."""
    try:
        r = _to_role(role)
    except ValueError:
        return False
    resource_perms = PERMISSIONS.get(resource, {})
    allowed_roles = resource_perms.get(action, set())
    return r in allowed_roles


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


def get_accessible_resources(role: str) -> dict[str, list[str]]:
    """Return all resource:action pairs accessible to a role."""
    result: dict[str, list[str]] = {}
    for resource, actions in PERMISSIONS.items():
        accessible = [action for action, roles in actions.items() if can(role, resource, action)]
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
        role = current_user.get("role", "")
        if not can(role, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' cannot perform '{action}' on '{resource}'",
            )
        return current_user

    # Give the dependency a stable name so FastAPI's OpenAPI can reference it
    _dependency.__name__ = f"rbac_{resource}_{action}"
    return _dependency
