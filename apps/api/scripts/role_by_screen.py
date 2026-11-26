"""The role-by-screen table (POST-A-447, part 3): what each staff role is OFFERED in the menus, by role template.

Written from two sources and nothing else: the backend's permission table (`core.permissions.PERMISSIONS`, the
template `rbac()` falls back to) and the menu declarations in `apps/web` (the ONE table of which permission opens
which area and screen, `lib/access/screenAccess.ts`, since POST-A-543; each firm panel's entries with the pair each
names itself; the Settings links, each asked of the same table since POST-A-545; and the client workspace's sections).
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


def _rule(text: str) -> dict:
    """One `AccessRule` literal of `screenAccess.ts`: `{ all: [...], any: [...], partnerOnly: true }`."""
    def pairs(key: str) -> list[tuple[str, str]]:
        m = re.search(rf"\b{key}:\s*\[", text)
        if not m:
            return []
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"[": 1, "]": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        found = [(m2.start(), (m2.group(1), "read")) for m2 in re.finditer(r'read\("([a-z_]+)"\)', body)]
        found += [(m2.start(), (m2.group(1), m2.group(2))) for m2 in re.finditer(_PAIR, body)]
        return [pair for _, pair in sorted(found)]
    return {"all": pairs("all"), "any": pairs("any"), "partner_only": bool(re.search(r"\bpartnerOnly:\s*true", text))}


def _access_table() -> tuple[dict[str, dict], list[tuple[str, dict]]]:
    """(the rule of each area, the rule of each screen prefix), read from `apps/web/lib/access/screenAccess.ts`."""
    src = (WEB / "lib" / "access" / "screenAccess.ts").read_text()
    areas_at = src.index("export const AREA_RULES")
    areas_src = src[src.index("{", src.index("=", areas_at)):src.index("\n};", areas_at)]
    areas = {m.group(1): _rule(m.group(2)) for m in re.finditer(r"(?m)^  ([a-z]+): (\{.*\}),\s*$", areas_src)}
    assert len(areas) >= 13, f"the areas of screenAccess.ts are not being read: {sorted(areas)}"
    screens_at = src.index("export const SCREEN_RULES")
    screens_src = src[screens_at:src.index("\n];", screens_at)]
    screens = [(m.group(1), _rule(m.group(2))) for m in re.finditer(r'(?m)^  \["([^"]+)", (\{.*\})\],\s*$', screens_src)]
    assert len(screens) >= 30, f"the screens of screenAccess.ts are not being read: {len(screens)}"
    return areas, screens


def _rule_holders(rule: dict, sets) -> set[str]:
    """The roles whose TEMPLATE holds what a rule asks."""
    if rule["partner_only"]:
        return {"Partner"}
    out = set(ROLES)
    for pair in rule["all"]:
        assert pair in sets, f"{pair} is not a pair of core/permissions.py"
        out &= sets[pair]
    if rule["any"]:
        for pair in rule["any"]:
            assert pair in sets, f"{pair} is not a pair of core/permissions.py"
        out &= set().union(*(sets[pair] for pair in rule["any"]))
    return out & set(ROLES)


def _rule_words(rule: dict) -> str:
    if rule["partner_only"]:
        return "Partner only"
    parts = [f"`{a}` `{b}`" for a, b in rule["all"]]
    if rule["any"]:
        parts.append(" or ".join(f"`{a}` `{b}`" for a, b in rule["any"]))
    return " and ".join(parts)


def _screen_rule(screens: list[tuple[str, dict]], href: str):
    """The longest prefix the address is, or is under: the rule `screenRule()` answers in the browser."""
    path = re.split(r"[?#]", href)[0]
    path = path.rstrip("/") if len(path) > 1 else path
    best = None
    for prefix, rule in screens:
        if (path == prefix or path.startswith(prefix + "/")) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, rule)
    return best[1] if best else None


def _holders(pairs, sets) -> set[str]:
    out = set(ROLES)
    for p in pairs:
        assert p in sets, f"{p} is not a pair of core/permissions.py"
        out &= sets[p]
    return out


def _cell(roles: set[str]) -> list[str]:
    return ["yes" if r in roles else "-" for r in ROLES]


def _settings_lines(sets, areas, screens) -> list[str]:
    """The Settings links, each by what the ONE table asks for its page (POST-A-545: the pages used to be opened by a role, and each
    link repeated its page's guard). A link to a card on a page also asks the card's own pair (`requires`). The page a link goes
    to may be an area's screen (Team), so the area's rule is asked too, as the browser's `mayOpen` does. This says who may OPEN
    the page: changing what is on it is a second permission, and a person without that one is shown the page read-only."""
    lines: list[str] = []
    settings = (WEB / "lib" / "settings" / "groups.ts").read_text()
    lines += ["", "## Settings", "",
              "Who is offered each link, which is who may open the page. Changing what is on a page asks a second permission "
              "(the page's write), and a person who holds only the first is shown the page with its controls switched off.", "",
              "| Link | Goes to | Asks | " + " | ".join(ROLES) + " |", "|---|---|---|" + "---|" * len(ROLES)]
    seen = set()
    for obj in _objects(settings):
        href, label = _key(obj, "href"), _key(obj, "label")
        if not href or not label or (href, label) in seen:
            continue
        seen.add((href, label))
        assert not re.search(r"\broles:\s*\[", obj), f"{href} names roles again: the Settings pages follow the one table"
        roles, asks = set(ROLES), []
        owner = _area_of(href)
        if owner and owner in areas:
            roles &= _rule_holders(areas[owner], sets)
            asks.append(_rule_words(areas[owner]))
        own = _screen_rule(screens, href)
        if own:
            roles &= _rule_holders(own, sets)
            asks.append(_rule_words(own))
        card = _requires(obj)
        if card:
            roles &= _holders([card], sets)
            asks.append(f"`{card[0]}` `{card[1]}` (the card)")
        said = " and ".join(dict.fromkeys(a for a in asks if a)) or "nothing: every member's"
        lines.append(f"| {label} | `{href}` | {said} | " + " | ".join(_cell(roles)) + " |")

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


def _panel_lines(sets, tile_roles, labels, areas, screens) -> list[str]:
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
            # The one table: the rule of the area the address is in (Home lists the roots of two other areas) and the
            # screen's own rule. `_AREA_OF` is the route-ownership chain's answer for the addresses a panel lists.
            owner = _area_of(href)
            if owner and owner != ws_id and owner in areas:
                roles &= _rule_holders(areas[owner], sets)
            own = _screen_rule(screens, href)
            if own:
                roles &= _rule_holders(own, sets)
                words = _rule_words(own)
                if words not in asks:
                    asks.append(words)
            rows.append((label, href, ", ".join(asks), roles))
        rows.sort(key=lambda r: src.find(f'"{r[1]}"'))
        lines += ["", f"## {labels.get(ws_id, ws_id)} panel", "",
                  "| Entry | Goes to | Asks | " + " | ".join(ROLES) + " |",
                  "|---|---|---|" + "---|" * len(ROLES)]
        for label, href, asks, roles in rows:
            lines.append(f"| {label} | `{href}` | {asks or 'the tile only'} | " + " | ".join(_cell(roles)) + " |")

    return lines


def _area_of(href: str):
    """Which area owns an address: `lib/workspace/routeOwnership.ts`, read as the ordered list of prefixes it is."""
    src = (WEB / "lib" / "workspace" / "routeOwnership.ts").read_text()
    body = src[src.index("export function getActiveWorkspaceForPathname"):]
    path = re.split(r"[?#]", href)[0]
    for block in re.finditer(r"if \((.*?)\)\s*\n?\s*return \"([a-z]+)\";", body, re.S):
        cond, area = block.group(1), block.group(2)
        if any(path == exact for exact in re.findall(r'pathname === "([^"]+)"', cond)):
            return area
        if any(path.startswith(prefix) for prefix in re.findall(r'pathname\.startsWith\("([^"]+)"\)', cond)):
            return area
    return None


def build() -> str:
    sets = _role_sets()
    areas, screens = _access_table()

    tiles = []
    cfg = (WEB / "lib" / "workspace" / "workspaceConfig.ts").read_text()
    for obj in _objects(cfg[cfg.index("WORKSPACE_CONFIGS"):]):
        ws_id, label = _key(obj, "id"), _key(obj, "label")
        if not ws_id or not label or "defaultRoute" not in obj:
            continue
        assert ws_id in areas, f"the area {ws_id!r} has no rule in screenAccess.ts"
        tiles.append((ws_id, label, _rule_words(areas[ws_id]), _rule_holders(areas[ws_id], sets)))
    tile_roles = {t[0]: t[3] for t in tiles}

    lines = [
        "# What each role is offered",
        "",
        "Generated by `apps/api/scripts/role_by_screen.py`; do not edit by hand. "
        "`apps/api/tests/test_the_role_by_screen_table_is_current.py` fails when this file and the code disagree.",
        "",
        "**What it reads.** The role templates in `apps/api/core/permissions.py` (what `rbac()` falls back to when a "
        "person has no grant of their own), the one table of which permission opens which area of the firm menu and "
        "which screen (`apps/web/lib/access/screenAccess.ts`: since 21-11-2026 the menu, the page and the guide all "
        "follow it, and no list of roles hides an area or an address), each firm panel's entries and the permission "
        "each names itself, the Settings links (`apps/web/lib/settings/groups.ts`, each asked of the same table) and the client workspace's "
        "sections (`apps/web/lib/workspace/ClientNavContext.tsx`).",
        "",
        "**What it does not read.** A per-person grant or block (the Team screen's grid) changes what one person is "
        "offered and is not here: this is what each ROLE starts with. A page drawn for a role may still narrow its rows to the clients the person is "
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
        lines.append(f"| {label} | {asks or 'nothing: always offered'} | " + " | ".join(_cell(roles)) + " |")

    lines += _panel_lines(sets, tile_roles, {t[0]: t[1] for t in tiles}, areas, screens)
    lines += _settings_lines(sets, areas, screens) + _client_lines(sets)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = build()
    if "--write" in sys.argv:
        DOC.write_text(text)
    else:
        sys.stdout.write(text)
