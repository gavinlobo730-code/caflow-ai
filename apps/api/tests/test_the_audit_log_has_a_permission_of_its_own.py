"""The audit log is read on a permission of its own, so approving journals and reading the log are two decisions (POST-A-550).

WHAT WAS WRONG
    Both audit routes (the firm's log, and the history of one record) asked `accounting` `approve`, the permission that approves a
    manual journal and locks a year. Since the screens follow the permissions a Partner ticks (POST-A-545), a Partner who let a Manager
    approve journals had also given them every entry of the audit log: who changed which client, document and ledger entry, and when.
    The tick screen could only say so beside the tick ("Opens: Audit log").

WHAT IS ASSERTED
    * the server's table holds `audit` `read`, a Partner's alone to start with, and nothing else under `audit`;
    * BOTH audit routes ask that pair and neither asks `accounting` `approve` (read off the router's own source);
    * the decision is two decisions, both ways: a Manager given the approval of journals is refused the log, and a Manager given the
      log may not approve a journal; a Partner holds both from the start; a Partner whose `audit` `read` was taken away is refused;
    * the screens agree with the server: the access table opens the audit log's page on `audit` `read`, the journal page's history
      panel asks the same pair before it sends anything, and no screen still says the history is "Partner only" (a role word, where
      the rule is a permission);
    * the role fixture the browser harness serves carries the pair for a Partner and for nobody else.
"""
from __future__ import annotations

import ast
import json
import pathlib

from core.permissions import PERMISSIONS, Role, can_user, resolve_permission

API = pathlib.Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
ACCESS_TABLE = WEB / "lib" / "access" / "screenAccess.ts"                       # apps/web/lib/access/screenAccess.ts
HISTORY_PANEL = WEB / "components" / "accounting" / "EntryHistory.tsx"          # apps/web/components/accounting/EntryHistory.tsx
ROLE_FIXTURE = WEB / "scripts" / "drive" / "role-permissions.json"              # apps/web/scripts/drive/role-permissions.json


def test_the_table_holds_the_pair_and_it_is_a_partners_to_start_with():
    assert PERMISSIONS["audit"] == {"read": {Role.PARTNER}}
    for role in ("Manager", "Executive", "Reviewer", "Client"):
        assert resolve_permission(role, None, "audit", "read") is False, role
    assert resolve_permission("Partner", None, "audit", "read") is True


def _pairs_the_audit_router_asks() -> list[tuple[str, str]]:
    tree = ast.parse((API / "routers" / "audit.py").read_text(encoding="utf-8"))
    pairs = []
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "rbac":
            pairs.append(tuple(a.value for a in call.args))
    return pairs


def test_both_audit_routes_ask_the_pair_and_neither_asks_the_one_that_approves_in_the_books():
    pairs = _pairs_the_audit_router_asks()
    assert len(pairs) == 2, f"the audit router has {len(pairs)} guarded routes; this test knows two (the log, and one record's history)"
    assert set(pairs) == {("audit", "read")}, pairs


def _manager(**overrides: bool) -> dict:
    return {"id": "u-m", "role": "Manager", "permission_overrides": {tuple(k.split(":")): v for k, v in overrides.items()}}


def test_approving_journals_and_reading_the_log_are_two_decisions():
    approver = _manager(**{"accounting:approve": True})
    assert can_user(approver, "accounting", "approve") is True, "premise: the Manager was given the approval of journals"
    assert can_user(approver, "audit", "read") is False, "the approval of journals still opens the audit log"

    reader = _manager(**{"audit:read": True})
    assert can_user(reader, "audit", "read") is True
    assert can_user(reader, "accounting", "approve") is False, "reading the log now lets a Manager approve in the books"

    partner = {"id": "u-p", "role": "Partner", "permission_overrides": {}}
    assert can_user(partner, "audit", "read") is True and can_user(partner, "accounting", "approve") is True
    blocked = {"id": "u-p2", "role": "Partner", "permission_overrides": {("audit", "read"): False}}
    assert can_user(blocked, "audit", "read") is False, "a Partner whose tick was taken away still reads the log"
    assert can_user(blocked, "accounting", "approve") is True


def test_the_screens_ask_the_same_pair_as_the_server():
    table = ACCESS_TABLE.read_text(encoding="utf-8")
    assert '["/settings/audit-log", { all: [read("audit")] }]' in table
    assert '["/settings/audit-log", { all: [["accounting", "approve"]] }]' not in table

    panel = HISTORY_PANEL.read_text(encoding="utf-8")
    assert 'can("audit", "read")' in panel, "the journal page's history panel does not ask the audit log's own permission"
    asks = panel.index("if (open && mayRead && !loaded && !loading) void load();")
    assert asks > panel.index('can("audit", "read")'), "the panel decides whether to ask before it knows the permission"
    assert "Partner only" not in panel, "the history panel still names a role where the rule is a permission"
    assert '<RequestAccess resource="audit" action="read"' in panel, "a person without the permission is not offered a way to ask"


def test_the_browser_harness_serves_the_pair_to_a_partner_and_to_nobody_else():
    maps = json.loads(ROLE_FIXTURE.read_text(encoding="utf-8"))
    assert maps["Partner"].get("audit") == ["read"]
    for role in ("Manager", "Executive", "Reviewer"):
        assert "audit" not in maps[role] or maps[role]["audit"] == [], role
