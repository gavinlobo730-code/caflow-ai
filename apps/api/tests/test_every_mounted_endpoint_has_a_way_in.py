"""An endpoint the product never calls is an endpoint nobody can use.

WHY THIS IS TREE-WIDE AND NOT ANOTHER PER-MODULE CHECK

`test_a_finished_payroll_endpoint_is_reachable.py` has enforced this for
`/api/payroll` since PAY-11, and it works: that module's own guard names its
one deliberate exception, the ECR retract, and had nothing else to report. The
other 46 prefixes, which have never had such a check, account for the rest —
239 of the 1,036 routes this app mounts, on the measurement of 16-09-2026.

READ `WHAT COUNTS AS "THE PRODUCT CALLS THIS"` BELOW BEFORE ANY NUMBER HERE.
Until 16-09-2026 the answer was "the URL appears somewhere in either frontend",
which the api client alone made true of almost everything; the count was 129
under that rule and is 239 under this one, and the product did not change.

That is the finding, and it is the argument for the file: the defect is not any
particular unreachable endpoint. It is that an endpoint can be written,
reviewed, tested and merged without one line of the product calling it, and
every test in the suite still passes — because every test in the suite calls it
directly.

WHY A BUDGET RATHER THAN A LIST OF EXEMPTIONS

The honest alternative was 137 entries each saying "deliberate". That is not a
policy, it is paperwork — the same conclusion Track F6's rule 3 reached after
its first shape failed on 23 files. Several of the 137 are also FALSE
POSITIVES of the matcher and cannot be cleared by writing prose about them: a
screen that builds a path suffix from a variable

    fetch(`${API}/api/public/engagement-letters/${token}${path}`)   // /sign

is genuinely calling the endpoint, and no static scan of this shape can see it.

So this is a RATCHET, like `MAX_UNREADABLE` in
test_backend_columns_exist_pg.py. The number may fall and may never rise. A new
endpoint with no caller pushes a module over its budget and fails here, naming
it; wiring one up lets the budget be lowered in the same commit. Nothing has to
be explained up front, and the situation cannot quietly get worse.

WHAT THIS CHECKS IS WEAKER THAN IT LOOKS, AND THE DIFFERENCE MATTERS

It matches PATHS, not (method, path) pairs — inherited from the payroll guard,
and a real limit rather than an oversight. One `fetch` to
`/api/dsc/${id}/renew` satisfies the pattern for `PATCH /api/dsc/{dsc_id}` and
`DELETE /api/dsc/{dsc_id}` as well, because all three are `/api/dsc/` followed
by something. This was found by writing the file: budgeting `/api/dsc` at 2 on
the assumption that only renew had been wired produced an actual count of 0
before the edit path existed.

So a green run means "some screen names a URL of this shape", NOT "every verb on
it is used". Tightening it would mean reading the `method:` out of each call
site's options object and pairing it with the URL — fragile against a verb held
in a variable, which is the same blind spot one level down. The looser check is
kept and its looseness written here, because a guard a reader trusts for more
than it proves is worse than one whose limits are on the label.
"""
from __future__ import annotations

import functools
import pathlib
import re

import pytest

from main import app

_REPO = pathlib.Path(__file__).resolve().parents[3]
WEB = _REPO / "apps" / "web"
#: The MARKETING site is a caller too, and until 16-09-2026 this scanner could
#: not see it. apps/marketing is a second frontend on its own origin, and it
#: reaches exactly one endpoint — POST /api/public/demo-request, the "Book a
#: demo" form, plus the GET that serves its firm-size options. Scanning only
#: apps/web reported both as unreachable, which is the opposite of true: they
#: are the most-used public endpoints on the site. An endpoint is reachable if
#: SOME frontend in this repository calls it.
MARKETING = _REPO / "apps" / "marketing"

#: Per-prefix ceilings, measured against the tree of 2026-09-16. Lower one in
#: the same commit that wires a screen up; raising one is a claim that a new
#: endpoint is deliberately unreachable, and belongs in a review.
#:
#: `/api/payroll`'s 6 is the ECR retract — which
#: test_a_finished_payroll_endpoint_is_reachable.py registers with its reason,
#: and that file stays the stricter check for its own module — plus five
#: api-client members no screen calls: the run status PATCH, the attendance
#: settings PUT, both halves of the bonus disqualification and the employee
#: import template. Under the concatenation all five looked wired up.
BUDGET: dict[str, int] = {
    "/api/workflows": 10, "/api/year-end": 10, "/api/banking": 9,
    "/api/task-recurring": 9, "/api/tasks": 9, "/api/copilot": 8,
    "/api/billing": 7, "/api/engagements": 7, "/api/income-tax": 6,
    "/api/memory": 7, "/api/relationships": 7, "/api/ai-insights": 6,
    "/api/compliance-records": 6, "/api/intelligence": 6, "/api/payroll": 6,
    "/api/analytics": 5, "/api/automation": 5, "/api/gst-portal": 5,
    "/api/itr": 5, "/api/lifecycle": 5, "/api/portal": 5, "/api/risks": 5,
    "/api/sales-invoices": 5, "/api/compliance": 4,
    "/api/firm-hsn-rate-history": 4, "/api/gst": 4, "/api/health": 4,
    "/api/mca-workspace": 4, "/api/recurring-invoices": 4, "/api/xbrl": 4,
    "/api/ai-copilot": 3, "/api/invoices": 3, "/api/purchase-cycle": 3,
    "/api/reminders": 3, "/api/tds": 3, "/api/accounting": 2,
    "/api/assignments": 2, "/api/customers": 2, "/api/form-26as": 2,
    "/api/identity": 2, "/api/insights": 2, "/api/notifications": 2,
    "/api/onboarding": 2, "/api/public": 2, "/api/sales-cycle": 2,
    "/api/scheduler": 2, "/api/settings": 2, "/api/vendors": 2,
    "/api/approvals": 1, "/api/customer-statements": 1,
    "/api/document-intelligence-v2": 1, "/api/documents": 1,
    "/api/eway-bill": 1, "/api/knowledge": 1, "/api/payments": 1,
    "/api/practice": 1, "/api/purchase-bills": 1, "/api/purchase-payments": 1,
    "/api/rcm-documents": 1, "/api/recurring-journals": 1,
    "/api/tally-migration": 1, "/api/tds-workspace": 1, "/api/team": 1,
    "/api/time-entries": 1,
}

# ---------------------------------------------------------------------------
# 129 -> 239 ON 16-09-2026: THE MEASUREMENT CHANGED, THE PRODUCT DID NOT
# ---------------------------------------------------------------------------
# `_sources()` stopped concatenating both frontends into one string and began
# attributing every URL literal to a screen that can reach it — the block over
# that function, below, says how and why. Under the old rule 907 looked reached;
# under this one 797 are. The 110 in between were named by nothing but an
# api-client method with no caller — `api.notifications.count`,
# `api.risks.*`, `api.intelligence.*`, the whole analytics surface T7 is about
# — and a budget of 129 was never a measurement of this product. It was a
# measurement of `lib/api/index.ts`.
#
# So this is a ratchet re-zeroed against an honest scale, not a ratchet let
# out. Every prefix above is the EXACT count on the tree of 16-09-2026,
# because `test_no_budget_entry_is_stale` refuses slack. The direction of
# travel is unchanged: lower one in the commit that wires a screen up, and
# raising one still needs a reason in a review.
#
# Nothing the old ladder recorded is undone. 133 -> 132 -> 130 -> 129 each
# marked a real endpoint being wired to a real screen (the recurring purchase
# bills, POST /api/itr/bf-losses and its siblings, the disallowance status
# PATCH); all four are still reached under the stricter rule, and the reasons
# are in git history at this file's previous revision.
# 239 -> 238: the advance-tax screen now POSTs to
# /api/income-tax/interest/234ab, so a CA sees s.234A and s.234B beside the
# s.234C it has always shown (IT-13). The engine and the endpoint were
# already there; nothing called them.
TOTAL_BUDGET = 238


# ---------------------------------------------------------------------------
# WHAT COUNTS AS "THE PRODUCT CALLS THIS", AND WHY IT IS NOT A CONCATENATION
# ---------------------------------------------------------------------------
#
# Until 16-09-2026 `_sources()` read every .ts/.tsx in both frontends into ONE
# string and asked whether the endpoint's shape appeared anywhere in it. That
# is 7 MB of text in which `apps/web/lib/api/index.ts` — 5,025 lines, 519
# members, 371 distinct URL literals — kept an endpoint "reached" whether or
# not a single screen ever called the method holding it.
#
# So the guard was answering a question nobody asked. It said "some file in
# this repository writes this URL down", and was read as "a CA can get at
# this". Measured against the tree of 16-09-2026: 907 endpoints looked
# reached and 110 of them were named by nothing but an api-client method with
# no caller, `api.notifications.count` among them. The api client itself
# already carried the argument, beside a wrapper that had been deleted rather
# than repointed:
#
#     an unused helper that still builds the URL is the thing someone wires a
#     button to next
#                                       -- lib/api/index.ts, `copilot.clientChat`
#
# THE RULE
#
#     A URL literal counts only where a SCREEN can reach it.
#
# A screen is any file under `app/` or `components/` in either frontend, and
# counts whole. Everything under `lib/` is cut into UNITS — each top-level
# declaration, plus, for `export const api`, each `namespace.method` member —
# and a unit counts only once live code NAMES it. That is a fixed point: a
# screen names `getGstr1Return`, which names `buildPeriod`, which holds the
# URL, and all three are live; nothing names `api.notifications.count`, so its
# body never joins the text and `GET /api/notifications/count` reports itself.
#
# IT MATCHES ON NAMES, NOT ON IMPORTS, AND THAT IS THE DECISION
#
# The import graph is the obvious alternative and it is three things rather
# than one: a module resolver for `@/`, an import parser, and a chaser for
# re-exports — and `lib/api/index.ts` is imported by nearly every screen, so
# it would have needed this member-level cut anyway. Matching the NAME is one
# rule. Its failure mode is also the right way round: two units sharing a name
# make the check GENEROUS, so a collision can leave an endpoint looking
# reached that is not, and can never invent a loss that is not there. A rename
# breaks the link and the endpoint drops out — which is the report wanted, not
# a false alarm.
#
# WHAT IT STILL CANNOT SEE
#
# The second data path. Roughly 320 `.from("…").select(…)` calls read ~83
# tables straight from the browser over PostgREST and name no `/api/` URL at
# all, so a screen built entirely on that path is invisible here in both
# directions — it cannot lose an endpoint and it cannot protect one. That is
# not fixable in this file; it is the frontend's own architecture, recorded in
# CLAUDE.md, and `test_frontend_columns_exist_pg.py` is the guard that covers
# it instead.
#
# AND THE RESIDUAL, MEASURED RATHER THAN ASSERTED
#
# Deleting a route page outright and asking whether this guard notices:
# 133 of 159 pages were silently deletable under the concatenation, 77 under
# this rule. The 77 are pages whose every endpoint is ALSO called by another
# screen — a shared editor component, a second tab on the same module.
# Deleting one of those orphans nothing, and the guard is right to be quiet.
# What it means is that this file is a floor, never a ceiling: it is the
# Playwright walk that checks a screen still renders.

_COMMENT_OR_STRING_START = re.compile(r"//|/\*|[\"'`]")


def _mask(text: str) -> str:
    """Comments and string bodies blanked to spaces, newlines kept.

    Brace counting has to ignore a `{` inside a comment or a string, and a
    naive two-pass (strip comments, then strip strings) gets it backwards: a
    URL in a string loses its `//` first and the unbalanced quote left behind
    then swallows the rest of the file. One left-to-right scan is the only
    order that is right.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        m = _COMMENT_OR_STRING_START.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        i, tok = m.start(), m.group(0)
        if tok == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif tok == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif tok == "`":
            # A template literal ends at the backtick that is not inside a
            # `${ … }` substitution.
            j, inner = i + 1, 0
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "`" and not inner:
                    j += 1
                    break
                if text[j:j + 2] == "${":
                    inner += 1
                    j += 2
                    continue
                if text[j] == "}" and inner:
                    inner -= 1
                j += 1
        else:
            j = i + 1
            while j < n and text[j] != tok:
                if text[j] == "\\":
                    j += 1
                if text[j:j + 1] == "\n":
                    break
                j += 1
            j = min(j + 1, n)
        out.append("".join(c if c == "\n" else " " for c in text[i:j]))
        i = j
    return "".join(out)


#: A top-level declaration, matched at column 0 and at brace depth 0.
_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:function\*?|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)")

_API_OPEN = "export const api = {"


def _depth_delta(line: str) -> int:
    return (line.count("{") + line.count("(") + line.count("[")
            - line.count("}") - line.count(")") - line.count("]"))


def _top_level_symbols(masked: list[str], lines: list[str]):
    """[(name, body)] per column-0 declaration; the body runs to the next one.

    Everything between two declarations belongs to the first, which is what
    makes this safe without a parser: a comment, a blank line or a stray
    statement is attributed somewhere rather than dropped.
    """
    depth, starts = 0, []
    for i, line in enumerate(masked):
        if depth == 0 and line[:1] not in (" ", "\t", ""):
            m = _DECL.match(line)
            if m:
                starts.append((i, m.group(1)))
        depth = max(0, depth + _depth_delta(line))
    out = []
    for n, (i, name) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        out.append((name, "\n".join(lines[i:end])))
    head = "\n".join(lines[: starts[0][0]]) if starts else "\n".join(lines)
    return out, head


def _api_members(masked: list[str], lines: list[str]):
    """[(namespace|None, name, body)] for `export const api`'s own members.

    The api client is one 3,000-line object literal, so a top-level cut leaves
    it whole and the concatenation problem survives inside it. Namespaces open
    at two spaces of indent, members at four.
    """
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(_API_OPEN))
    except StopIteration:
        return []
    out, depth, ns, cur = [], 0, None, None

    def close(at: int) -> None:
        nonlocal cur
        if cur is not None:
            out.append((cur[0], cur[1], "\n".join(lines[cur[2]:at + 1])))
            cur = None

    for i in range(start, len(lines)):
        line = masked[i]
        if depth == 1:
            m = re.match(r"^  ([A-Za-z_$][\w$]*)\s*:", line)
            if m:
                close(i - 1)
                if line.rstrip().endswith("{"):
                    ns = m.group(1)          # a namespace: api.gst, api.tds …
                else:
                    ns, cur = None, (None, m.group(1), i)   # api.search
        elif depth == 2 and ns:
            m = re.match(r"^    ([A-Za-z_$][\w$]*)\s*:", line)
            if m:
                close(i - 1)
                cur = (ns, m.group(1), i)
        depth += _depth_delta(line)
        if depth < 1:
            ns = None
        if depth <= 0 and i > start:
            close(i)
            return out
    close(len(lines) - 1)
    return out


def _frontend_files(roots):
    for root in roots:
        for folder in ("app", "lib", "components"):
            directory = root / folder
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if path.suffix in (".ts", ".tsx") and ".test." not in path.name:
                    yield folder, path


def _screens_and_units(roots):
    """(screen texts, [(file, unit name or None, body)]).

    A unit named `None` is the module head — its imports and anything above
    the first declaration. It joins only when some other unit of the same file
    does, so a file nothing reaches contributes nothing at all.
    """
    screens, units = [], []
    for folder, path in _frontend_files(roots):
        text = path.read_text(errors="ignore")
        if folder in ("app", "components"):
            screens.append(text)
            continue
        lines = text.split("\n")
        masked = _mask(text).split("\n")
        rel = str(path)
        members = _api_members(masked, lines)
        for namespace, name, body in members:
            units.append((rel, f"{namespace}.{name}" if namespace else name, body))
        symbols, head = _top_level_symbols(masked, lines)
        for name, body in symbols:
            if name == "api" and members:
                continue                      # already cut, member by member
            units.append((rel, name, body))
        units.append((rel, None, head))
    return screens, units


_WORD = re.compile(r"[A-Za-z_$][\w$]*")
#: Overlapping on purpose: `api.tds.sections` has to yield BOTH `api.tds` and
#: `tds.sections`, and a consuming match gives only the first.
_ATTR = re.compile(r"([A-Za-z_$][\w$]*)\s*\.\s*(?=([A-Za-z_$][\w$]*))")


@functools.lru_cache(maxsize=None)
def _sources(roots: tuple = ()) -> str:
    """The code a SCREEN can actually reach, in both frontends.

    Tests are excluded so a test that merely NAMES an endpoint cannot make it
    look reachable — the exact mistake this guards against, one level up.
    """
    screens, units = _screens_and_units(roots or (WEB, MARKETING))
    seed = "\n".join(screens)
    live = [seed]
    words = set(_WORD.findall(seed))
    pairs = {f"{a}.{b}" for a, b in _ATTR.findall(seed)}
    live_files: set[str] = set()
    pending = [u for u in units if u[1] is not None]
    changed = True
    while changed:
        changed, still, added = False, [], []
        for rel, name, body in pending:
            if (name in pairs) if "." in name else (name in words):
                live.append(body)
                live_files.add(rel)
                added.append(body)
                changed = True
            else:
                still.append((rel, name, body))
        pending = still
        if added:
            chunk = "\n".join(added)
            words |= set(_WORD.findall(chunk))
            pairs |= {f"{a}.{b}" for a, b in _ATTR.findall(chunk)}
    live.extend(body for rel, name, body in units
                if name is None and rel in live_files)
    return "\n".join(live)


def _pattern(path: str) -> re.Pattern:
    """The path's static chunks in order, with anything between them.

    Matching only the last segment would be far too loose — "settlement" and
    "loans" occur in screens that have nothing to do with the endpoint.
    """
    chunks = re.split(r"\{[^}]+\}", path)
    return re.compile(r"[^\s\"'`]*?".join(re.escape(c) for c in chunks))


def _routes() -> set[tuple[str, str]]:
    out = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in (getattr(route, "methods", set()) or set()):
            if method not in ("HEAD", "OPTIONS"):
                out.add((method, path))
    return out


@pytest.fixture(scope="module")
def unreached() -> dict[str, list[str]]:
    blob = _sources()
    by_prefix: dict[str, list[str]] = {}
    for method, path in sorted(_routes()):
        if not _pattern(path).search(blob):
            by_prefix.setdefault("/".join(path.split("/")[:3]), []).append(
                f"{method} {path}")
    return by_prefix


def test_the_route_scan_still_sees_the_app(unreached):
    """A scan that stops matching keeps passing while checking nothing."""
    assert len(_routes()) > 500, (
        "the app mounts far fewer routes than expected — the scan is probably "
        "reading a half-imported app, not a shrunken product")


def test_no_module_exceeds_its_unreachable_budget(unreached):
    over = {
        prefix: (len(items), BUDGET.get(prefix, 0), items)
        for prefix, items in unreached.items()
        if len(items) > BUDGET.get(prefix, 0)
    }
    assert not over, "\n".join(
        f"{prefix}: {found} unreachable, budget {allowed} — {items}"
        for prefix, (found, allowed, items) in sorted(over.items())
    ) + (
        "\n\nAn endpoint no screen calls cannot be used by a CA, however well "
        "it is tested. Wire it up, or raise the budget in the same commit and "
        "say why."
    )


def test_the_total_only_goes_down(unreached):
    """The per-module budgets can hide a shuffle; the total cannot."""
    found = sum(len(v) for v in unreached.values())
    assert found <= TOTAL_BUDGET, (
        f"{found} endpoints reach no screen, budget {TOTAL_BUDGET}. Lower the "
        f"budget when you wire one up; raising it needs a reason.")


def test_no_budget_entry_is_stale(unreached):
    """A budget that outlives its debt is how a ratchet stops ratcheting."""
    slack = {
        prefix: (allowed, len(unreached.get(prefix, [])))
        for prefix, allowed in BUDGET.items()
        if allowed > len(unreached.get(prefix, []))
    }
    assert not slack, (
        f"these budgets are above what the tree actually owes — lower them: "
        f"{ {p: f'budget {a}, actual {n}' for p, (a, n) in sorted(slack.items())} }"
    )
