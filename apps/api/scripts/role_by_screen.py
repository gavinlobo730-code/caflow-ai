"""The role-by-screen table (POST-A-447, part 3): what each staff role is OFFERED in the menus, by role template.

Written from two sources and nothing else: the backend's permission table (`core.permissions.PERMISSIONS`, the
template `rbac()` falls back to) and the menu declarations in `apps/web` (the workspace tiles and their role rules,
each firm panel's entries with the pair each asks, the Settings links' roles, and the client workspace's sections).
It is a READING of those declarations, so it says what the menus draw for a role and not what a page then does: a
page may still narrow its rows to the person's assigned clients, hide a button, or be refused by the server.

    python3 scripts/role_by_screen.py            # print the document
    python3 scripts/role_by_screen.py --write    # rewrite docs/architecture/12-what-each-role-is-offered.md

`tests/test_the_role_by_screen_table_is_current.py` fails when the committed document differs from what this prints,
so a menu or permission change that moves what a role is offered moves the document in the same commit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
DOC = API.parents[1] / "docs" / "architecture" / "12-what-each-role-is-offered.md"
ROLES = ("Partner", "Manager", "Executive", "Reviewer")

sys.path.insert(0, str(API))


def _role_sets() -> dict[tuple[str, str], frozenset[str]]:
    from core.permissions import PERMISSIONS
    out: dict[tuple[str, str], frozenset[str]] = {}
    for resource, actions in PERMISSIONS.items():
        for action, roles in actions.items():
            out[(resource, action)] = frozenset(getattr(r, "value", str(r)) for r in roles)
    return out


def _objects(src: str):
    """Every `{ ... }` literal in a source, innermost children cut out, so a parent object's own keys are read apart
    from its children's. Template literals and strings are skipped so a brace inside one is not counted."""
    stack: list[int] = []
    spans: list[tuple[int, int]] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'`":
            j = i + 1
            while j < n and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            spans.append((stack.pop(), i))
        i += 1
    for start, end in spans:
        body = src[start + 1:end]
        inner = [(s - start - 1, e - start) for s, e in spans if start < s and e < end]
        own = list(body)
        for s, e in inner:
            for k in range(s, e):
                own[k] = " "
        yield "".join(own)


_STR = r'"([^"]*)"'
_PAIR = r'\[\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\]'


def _key(obj: str, key: str):
    m = re.search(rf"\b{key}:\s*{_STR}", obj)
    return m.group(1) if m else None


def _requires(obj: str):
    m = re.search(rf"\brequires:\s*{_PAIR}", obj)
    return (m.group(1), m.group(2)) if m else None


def _requires_any(obj: str):
    m = re.search(r"\brequiresAnyOf:\s*\[((?:\s*" + _PAIR + r"\s*,?)+)\s*\]", obj)
    return [(a, b) for a, b in re.findall(_PAIR, m.group(1))] if m else None


def _set_literal(src: str, name: str) -> set[str]:
    m = re.search(rf"const {name}\b[^=]*=\s*new Set(?:<[^>]*>)?\(\[(.*?)\]\)", src, re.S)
    assert m, f"{name} is not a Set literal any more"
    return set(re.findall(_STR, m.group(1)))


def _holders(pairs, sets) -> set[str]:
    out = set(ROLES)
    for p in pairs:
        assert p in sets, f"{p} is not a pair of core/permissions.py"
        out &= sets[p]
    return out


def _cell(roles: set[str]) -> list[str]:
    return ["yes" if r in roles else "-" for r in ROLES]


def _settings_lines() -> list[str]:
    lines: list[str] = []
    settings = (WEB / "lib" / "settings" / "groups.ts").read_text()
    lines += ["", "## Settings", "",
              "| Link | Goes to | " + " | ".join(ROLES) + " |", "|---|---|" + "---|" * len(ROLES)]
    seen = set()
    for obj in _objects(settings):
        href, label = _key(obj, "href"), _key(obj, "label")
        if not href or not label or (href, label) in seen:
            continue
        seen.add((href, label))
        m = re.search(r"\broles:\s*\[([^\]]*)\]", obj)
        roles = set(re.findall(_STR, m.group(1))) & set(ROLES) if m else set(ROLES)
        lines.append(f"| {label} | `{href}` | " + " | ".join(_cell(roles)) + " |")

    return lines


def _client_lines(sets) -> list[str]:
    lines: list[str] = []
    nav = (WEB / "lib" / "workspace" / "ClientNavContext.tsx").read_text()
    lines += ["", "## A client's workspace", "",
              "Drawn for every client the person may open (a Partner every client, everyone else their assigned ones).",
              "", "| Section | Asks | " + " | ".join(ROLES) + " |", "|---|---|" + "---|" * len(ROLES)]
    for obj in _objects(nav):
        sec, label = _key(obj, "id"), _key(obj, "label")
        if not sec or not label or "href:" not in obj:
            continue
        roles, asks = set(ROLES), ""
        req, anyof = _requires(obj), _requires_any(obj)
        if req:
            roles = _holders([req], sets)
            asks = f"`{req[0]}` `{req[1]}`"
        if anyof:
            roles = set().union(*(_holders([p], sets) for p in anyof))
            asks = " or ".join(f"`{a}` `{b}`" for a, b in anyof)
        lines.append(f"| {label} | {asks or 'nothing of its own'} | " + " | ".join(_cell(roles)) + " |")
    return lines


def _panel_lines(sets, tile_roles, labels, staff_hidden_hrefs, manager_hidden_hrefs) -> list[str]:
    lines: list[str] = []
    panels = {
        "home": "HomePanel.tsx", "clients": "ClientsPanel.tsx", "deadlines": "DeadlinesPanel.tsx",
        "work": "WorkPanel.tsx", "team": "TeamPanel.tsx", "ai": "AIPanel.tsx", "accounting": "AccountingPanel.tsx",
        "payroll": "PayrollPanel.tsx", "relationships": "RelationshipsPanel.tsx", "health": "HealthPanel.tsx",
        "practice": "PracticePanel.tsx", "knowledge": "KnowledgePanel.tsx", "engagements": "EngagementsPanel.tsx",
    }
    for ws_id, fname in panels.items():
        src = (WEB / "components" / "panels" / fname).read_text()
        rows = []
        seen = set()
        for obj in _objects(src):
            href, label = _key(obj, "href"), _key(obj, "label")
            if not href or not label or (href, label) in seen:
                continue
            seen.add((href, label))
            roles = set(tile_roles.get(ws_id, set(ROLES)))
            asks = []
            req = _requires(obj)
            if req:
                roles &= _holders([req], sets)
                asks.append(f"`{req[0]}` `{req[1]}`")
            if re.search(r"\bpartnerOnly:\s*true", obj):
                roles &= {"Partner"}
                asks.append("Partner only")
            if ws_id == "home":
                # The Home panel filters its links by the href role rule (canAccessHref).
                if href in manager_hidden_hrefs:
                    roles -= {"Manager"}
                if href in staff_hidden_hrefs:
                    roles -= {"Executive", "Reviewer"}
            rows.append((label, href, ", ".join(asks), roles))
        rows.sort(key=lambda r: src.find(f'"{r[1]}"'))
        lines += ["", f"## {labels.get(ws_id, ws_id)} panel", "",
                  "| Entry | Goes to | Asks | " + " | ".join(ROLES) + " |",
                  "|---|---|---|" + "---|" * len(ROLES)]
        for label, href, asks, roles in rows:
            lines.append(f"| {label} | `{href}` | {asks or 'the tile only'} | " + " | ".join(_cell(roles)) + " |")

    return lines


def build() -> str:
    sets = _role_sets()
    perm_src = (WEB / "lib" / "auth" / "permissions.ts").read_text()
    partner_only = _set_literal(perm_src, "PARTNER_ONLY_WORKSPACES")
    staff_hidden = _set_literal(perm_src, "STAFF_HIDDEN_WORKSPACES")
    staff_hidden_hrefs = _set_literal(perm_src, "STAFF_HIDDEN_HREFS")
    manager_hidden_hrefs = _set_literal(perm_src, "MANAGER_HIDDEN_HREFS")

    def workspace_roles(ws_id: str) -> set[str]:
        if ws_id in partner_only:
            return {"Partner"}
        return {"Partner", "Manager"} | (set() if ws_id in staff_hidden else {"Executive", "Reviewer"})

    tiles = []
    cfg = (WEB / "lib" / "workspace" / "workspaceConfig.ts").read_text()
    for obj in _objects(cfg[cfg.index("WORKSPACE_CONFIGS"):]):
        ws_id, label = _key(obj, "id"), _key(obj, "label")
        if not ws_id or not label or "defaultRoute" not in obj:
            continue
        roles = workspace_roles(ws_id)
        req, anyof = _requires(obj), _requires_any(obj)
        asks = ""
        if req:
            roles &= _holders([req], sets)
            asks = f"`{req[0]}` `{req[1]}`"
        if anyof:
            roles &= set().union(*(_holders([p], sets) for p in anyof))
            asks = " or ".join(f"`{a}` `{b}`" for a, b in anyof)
        tiles.append((ws_id, label, asks, roles))
    tile_roles = {t[0]: t[3] for t in tiles}

    lines = [
        "# What each role is offered",
        "",
        "Generated by `apps/api/scripts/role_by_screen.py`; do not edit by hand. "
        "`apps/api/tests/test_the_role_by_screen_table_is_current.py` fails when this file and the code disagree.",
        "",
        "**What it reads.** The role templates in `apps/api/core/permissions.py` (what `rbac()` falls back to when a "
        "person has no grant of their own), the workspace tiles and their role rules (`apps/web/lib/workspace/"
        "workspaceConfig.ts`, `apps/web/lib/auth/permissions.ts`), each firm panel's entries and the permission each "
        "asks, the Settings links' roles (`apps/web/lib/settings/groups.ts`) and the client workspace's sections "
        "(`apps/web/lib/workspace/ClientNavContext.tsx`).",
        "",
        "**What it does not read.** A per-person grant or block (the Team screen's grid) changes what one person is "
        "offered and is not here. A page drawn for a role may still narrow its rows to the clients the person is "
        "assigned to (a Partner sees every client; every other role sees only assigned ones), hide a button the "
        "person may not use, or be refused by the server. A Client-portal contact and an employee are not staff and "
        "have their own portals, which read only their own client's or their own records (see "
        "`docs/design-record/tenancy-and-security.md`).",
        "",
        "`yes` means the role is offered it; `-` that it is not.",
        "",
        "## The workspace tiles",
        "",
        "| Tile | Asks | " + " | ".join(ROLES) + " |",
        "|---|---|" + "---|" * len(ROLES),
    ]
    for _, label, asks, roles in tiles:
        lines.append(f"| {label} | {asks or 'the role rule only'} | " + " | ".join(_cell(roles)) + " |")

    lines += _panel_lines(sets, tile_roles, {t[0]: t[1] for t in tiles}, staff_hidden_hrefs, manager_hidden_hrefs)
    lines += _settings_lines() + _client_lines(sets)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = build()
    if "--write" in sys.argv:
        DOC.write_text(text)
    else:
        sys.stdout.write(text)
