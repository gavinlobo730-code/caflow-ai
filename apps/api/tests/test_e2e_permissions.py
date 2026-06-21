"""
Phase 5.2 WS-1 — Permission checks (RBAC matrix + assignment scope).

The cycle suites assert cross-firm DATA isolation; this asserts the ROLE layer
that the rbac() dependency enforces on every endpoint — using the same
core.permissions.can() the dependency calls — across all five roles, plus the
Module-9 assignment-scope model (only Partner is firm-wide).

Roles: Partner > Manager > Executive > Reviewer > Client.
"""
from core.permissions import can, is_at_least, Role
from core.authz import is_firmwide, can_access_client


PARTNER, MANAGER, EXEC, REVIEWER, CLIENT = "Partner", "Manager", "Executive", "Reviewer", "Client"
STAFF = [PARTNER, MANAGER, EXEC, REVIEWER]


# --------------------------------------------------------------------------- #
#  Accounting / invoice — the sales & purchase cycles
# --------------------------------------------------------------------------- #
def test_accounting_write_is_manager_plus():
    assert can(PARTNER, "accounting", "write") and can(MANAGER, "accounting", "write")
    assert not can(EXEC, "accounting", "write")        # Executive can read, not write
    assert not can(REVIEWER, "accounting", "write")


def test_accounting_read_is_executive_plus():
    assert can(EXEC, "accounting", "read")
    assert not can(REVIEWER, "accounting", "read")     # Reviewer is out of accounting
    assert not can(CLIENT, "accounting", "read")


def test_accounting_approve_is_partner_only():
    assert can(PARTNER, "accounting", "approve")
    assert not can(MANAGER, "accounting", "approve")   # posting/approval is Partner-only


def test_invoice_write_executive_plus_delete_partner_only():
    assert can(EXEC, "invoice", "write") and can(EXEC, "invoice", "read")
    assert not can(REVIEWER, "invoice", "write")
    assert can(MANAGER, "invoice", "approve") and not can(EXEC, "invoice", "approve")
    assert can(PARTNER, "invoice", "delete") and not can(MANAGER, "invoice", "delete")


# --------------------------------------------------------------------------- #
#  Compliance / engagement cycle
# --------------------------------------------------------------------------- #
def test_compliance_record_matrix():
    assert all(can(r, "compliance_record", "read") for r in STAFF)   # all staff read
    assert can(EXEC, "compliance_record", "write")
    assert not can(REVIEWER, "compliance_record", "write")
    assert can(MANAGER, "compliance_record", "approve")
    assert not can(EXEC, "compliance_record", "approve")
    assert can(PARTNER, "compliance_record", "delete") and not can(MANAGER, "compliance_record", "delete")


def test_engagement_is_manager_plus():
    assert can(MANAGER, "engagement", "write") and can(MANAGER, "engagement", "read")
    assert not can(EXEC, "engagement", "write")
    assert not can(REVIEWER, "engagement", "read")


# --------------------------------------------------------------------------- #
#  Banking / reporting / reminders
# --------------------------------------------------------------------------- #
def test_banking_uses_accounting_perms():
    # Banking endpoints guard on accounting.write (post) / accounting.read (queues).
    assert can(MANAGER, "accounting", "write") and not can(EXEC, "accounting", "write")


def test_reports_read_all_export_manager_plus():
    assert all(can(r, "report", "read") for r in STAFF)
    assert can(MANAGER, "report", "export") and not can(EXEC, "report", "export")


def test_reminder_write_executive_plus():
    assert can(EXEC, "reminder", "write") and not can(REVIEWER, "reminder", "write")
    assert all(can(r, "reminder", "read") for r in STAFF)


# --------------------------------------------------------------------------- #
#  Portal (CA-side) — never the Client role
# --------------------------------------------------------------------------- #
def test_portal_management_is_staff_only():
    assert can(EXEC, "portal", "write") and can(REVIEWER, "portal", "read")
    assert not can(CLIENT, "portal", "read")           # clients use the external surface
    assert not can(CLIENT, "portal", "write")


# --------------------------------------------------------------------------- #
#  Sensitive resources — Partner-gated
# --------------------------------------------------------------------------- #
def test_sensitive_resources_partner_gated():
    assert can(PARTNER, "billing", "write") and not can(MANAGER, "billing", "write")
    assert can(PARTNER, "practice", "read") and not can(MANAGER, "practice", "read")
    assert can(PARTNER, "payroll", "finalize") and not can(MANAGER, "payroll", "finalize")
    assert can(PARTNER, "assignment", "write") and not can(MANAGER, "assignment", "write")


# --------------------------------------------------------------------------- #
#  Unknown role / client lockout / hierarchy
# --------------------------------------------------------------------------- #
def test_unknown_role_denied_by_default():
    assert not can("Intern", "invoice", "read")        # fail-closed
    assert not can("", "client", "read")


def test_client_role_has_no_staff_access():
    for resource, action in [("client", "read"), ("accounting", "read"), ("invoice", "read"),
                             ("compliance_record", "read"), ("report", "read"), ("portal", "read")]:
        assert not can(CLIENT, resource, action), f"Client must not access {resource}.{action}"


def test_role_hierarchy():
    assert is_at_least(PARTNER, MANAGER) and is_at_least(MANAGER, EXEC)
    assert not is_at_least(EXEC, MANAGER)
    assert not is_at_least(REVIEWER, EXEC)


# --------------------------------------------------------------------------- #
#  Assignment scope (Module 9.0 / M3) — only Partner is firm-wide
# --------------------------------------------------------------------------- #
def test_only_partner_is_firmwide():
    assert is_firmwide({"role": PARTNER}) is True
    for r in (MANAGER, EXEC, REVIEWER, CLIENT):
        assert is_firmwide({"role": r}) is False, f"{r} must NOT be firm-wide"


def test_firmwide_can_access_any_client():
    # Partner (firm-wide) may access any client; mock/dev is permissive for others
    # (real assignment enforcement runs against the live DB / RLS).
    assert can_access_client({"role": PARTNER}, "ANY-CLIENT") is True
