"""
Every query on a table that carries a `firm_id` carries its firm's scope, or says on a
frozen list why it does not (engineering-28).

THE RULE

    The service-role key bypasses row-level security, so the `.eq("firm_id", ...)` in
    application code is the PRIMARY tenant control in this product (CLAUDE.md,
    "Tenancy and access"), with RLS as defence in depth. Nothing checked that a query
    HAS one. The only thing that has ever found a missing filter is an audit reading
    the code, and an audit is a snapshot: the next route written is unreviewed.

    So this reads every PostgREST chain in `apps/api` (`tests/_firm_scope_scan.py`) and
    asks of each one that touches a table with a `firm_id` column: is it scoped?

      * by a firm FILTER (`.eq("firm_id", ...)`, `.in_`, `.match`, `.or_`, an embedded
        parent's), or a PAYLOAD carrying `firm_id` for an insert or upsert;
      * or CHILD-BY-PARENT: it is keyed on an id that a verified gate looked at, that
        was already used as the primary key of a scoped read, that came out of a scoped
        read or a call handed the firm, that is the caller's own identity, or that a
        helper's callers are ALL judged to have checked;
      * or the table has no firm column (its tenant is its parent's, and that is the
        assignment-scope rule's business, not this one's: the census counts them).

    A repository method, a function whose firm filter is conditional on an optional
    `firm_id`, a helper keyed on its parameters and a helper that inserts a payload it
    is handed are not judged alone: their CALLERS are, as the query the call stands for.

    What remains is `tests/fixtures/firm_scope_allowlist.txt`: every chain the reader
    cannot clear, with a category and a note naming what that category's check reads.

WHERE THE TABLE SET COMES FROM

    The production snapshot (`tests/fixtures/production_schema_*.json`), plus the
    tables a migration NEWER than the snapshot gives a `firm_id` (its meta file says
    which migration it was taken after). Never a list written here: a list is how the
    next table is the one nobody added.

THE ALLOWLIST IS AN EXACT EQUALITY, IN BOTH DIRECTIONS

    Like `scripts/ci/ruff_baseline.txt`. A new unscoped chain fails until somebody
    writes down why it is fine. A line whose chain no longer exists (somebody fixed
    it) ALSO fails, so a fix deletes its own line in the same commit and the list can
    only shrink on its own. The chain count per key is part of the equality.

    A category is not a pass. Each one has a check that reads the code and fails when
    the claim stops being true: a gate that is deleted, a lookup that stops raising,
    a function that gains a caller. The checks prove that the named evidence EXISTS and
    is where the note says; they do not prove it is sufficient, which is a reviewer's
    job and the reason the categories are few and named.

WHAT THIS DOES NOT SEE (and says so rather than implying it does)

    * The VALUE of a firm filter. `.eq("firm_id", x)` is read as scoped; whether `x` is
      the caller's firm is not. Two structural tests bound that from the outside: no
      route handler other than the platform console takes a `firm_id`, and no request
      model has a `firm_id` field.
    * `.rpc()` calls: a function takes the firm as an argument and there is no filter to
      read (the census does not count them; migration 475's catalogue check does).
    * A chain whose table is named by a variable (counted, budgeted, judged as though it
      had a firm column) or whose filters sit somewhere else (counted).
    * Tables with no firm column: 215 chains on 23 of them are NOT judged. 153 are on 17
      child tables keyed on a parent's id (nothing here asks whether the parent id was read
      under the firm), 49 on `firms` (keyed on its own id) and 13 on tables with no tenant.
    * A call the reader cannot tie to its helper by name: a same-name call it cannot
      resolve BLOCKS clearing that helper rather than being guessed at.
    * HOW MUCH THE CLEARING EVIDENCE PROVES. An independent review of this guard found
      that `flow`, read-origin and `gate` evidence is NAME-based and blind to branch, order
      and scope, so it can clear an unscoped chain: an id read off a firm's own row (a line's
      `service_catalogue_id`) used as `.in_("id", ids)` on another firm table is treated as
      having come out of a scoped read (that is the class of the inventory fix, which this
      guard did NOT flag); a call handed `firm_id` or `current_user` vouches for its return
      value even when the callee queries nothing; a non-ownership `assert_*` that names
      `firm_id` counts as a gate; a gate whose result is ignored still counts. An allowlist
      line is bound to (file, function, table, operation, count) and NOT to the chain's
      content, so a predicate can change under a standing key. Smaller: `.or_()` mentioning
      `firm_id`, `.filter("firm_id", "neq", x)` and `.eq("firm_id", None)` count as the
      filter; `.from_("t")` is read as no chain; a helper passed by reference is not a call;
      a call inside a `_USE_MOCK` branch is read as no query; a relation a newer migration
      gives a firm_id by a view, a multi-action ALTER, CREATE TABLE AS or LIKE is not found
      until the snapshot is refreshed. None is relied on by a chain in the tree today
      (measured). CLAUDE.md, the engineering-28 bullet, says the same at more length.

RUNTIME: one scan of the tree (8 to 18 s on a shared four-CPU machine), one read of the schema
fixture, shared by every test in the module.
"""
from __future__ import annotations

import ast
import functools
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TESTS = Path(__file__).resolve().parent
API = TESTS.parent
sys.path.insert(0, str(TESTS))

import _firm_scope_scan as S  # noqa: E402

ALLOWLIST = TESTS / "fixtures" / "firm_scope_allowlist.txt"
SNAPSHOT = TESTS / "fixtures" / "production_schema_2026-09-03.json"
SNAPSHOT_META = TESTS / "fixtures" / "production_schema_2026-09-03.meta.json"


# ── The category vocabulary ──────────────────────────────────────────────────

#: category -> what it says. The CHECK for each is `_CHECKS[category]` below.
CATEGORIES = {
    "repository-contract":
        "A repository method keyed on an id, or inserting a payload, whose firm check is "
        "its CALLER's. Every call site is judged by this guard as the query it stands for "
        "(table `repo:<singleton>.<method>`), so a caller that does not carry the firm is a "
        "finding of its own. A NEW bare repository method fails here until it is named.",
    "principal-lookup":
        "Resolves who the caller is from the verified login (the auth id), or reads the "
        "principal's own memberships. There is no firm yet to filter on: finding it is the "
        "point.",
    "bearer-token":
        "Found by a secret, single-use token (a signing link, an invitation) that IS the "
        "credential. The row's own id is then used for the follow-up write.",
    "provider-callback":
        "A payment or email provider's SIGNED callback, correlated by the provider's own "
        "ids. An unsigned request is refused before any of this runs, and the firm is read "
        "off the row that matched.",
    "system-job":
        "The scheduler or the outbox worker acting across every firm by design. No request, "
        "so no tenant to filter on; never reached from a route handler.",
    "platform-admin":
        "The platform owner's cross-tenant console, every route behind "
        "`require_platform_admin`.",
    "numbering-series":
        "The one generic document-numbering read. Its scope is exactly the columns of the "
        "UNIQUE constraint (NUMBER_SERIES), and every series includes `firm_id`.",
    "gated-by-route":
        "A service or domain function reached from a route handler that asserts the client "
        "or the row with a verified gate before calling it (the note names the route and "
        "what it calls). The id arrives checked.",
    "gated-in-function":
        "The same function asserted the client with a gate, or was refused by a callee that "
        "was handed the firm, through a spelling of the value the reader does not connect "
        "to the chain (a batch gate, a dict handed on).",
    "looked-up-first":
        "An earlier call in the same function looked the id up under the firm and raises "
        "when it is not the firm's; the write that follows is keyed on the same id.",
    "from-scoped-row":
        "The id is a field of a row the caller fetched or created under the firm (the note "
        "names where).",
    "child-by-parent":
        "The row is keyed on a parent that was fetched under the firm; its own isolation is "
        "its parent's (migration 016's RLS reads it through the parent).",
    "own-insert-id":
        "The id belongs to a row the engine has just created from an id the route gated.",
    "payload-with-firm":
        "An insert whose payload carries `firm_id` in a dict the function builds, handed "
        "through a call the reader does not follow.",
    "helper-of-allowlisted-call":
        "A helper keyed on its parameters. The guard clears it when every call to it is "
        "judged scoped; here a call to it sits on this list under its own category, so the "
        "helper's chain is the same finding seen from the other side.",
    "unreachable-code":
        "No production caller: nothing in routers, services, domain or jobs calls it. "
        "WIRING IT UP would need its firm scope written first.",
    "reported-exposure":
        "A real cross-tenant exposure that was found and NOT fixed because the right fix is "
        "not obvious or changes behaviour. One sentence in the note says what it is.",
}

#: The tokens a category's note must carry (what its check reads).
REQUIRES = {
    "gated-by-route": ("route",),
    "gated-in-function": ("gate",),
    "own-insert-id": ("gate",),
    "looked-up-first": ("lookup",),
    "from-scoped-row": ("source",),
    "child-by-parent": ("source",),
    "bearer-token": ("token",),
    "provider-callback": ("signature",),
    "unreachable-code": ("symbol",),
}

#: Real exposures found and not fixed. None was left unfixed by this change; a key is
#: added here, with the sentence in its note, only by the person who finds the next one.
REPORTED_EXPOSURES: tuple = ()

#: What the reader cannot read, pinned EXACTLY. A new `.table(variable)` or a chain
#: handed on without a visible filter is a decision somebody makes on purpose.
UNREADABLE_BUDGET = {
    "table_named_by_a_variable": 41,
    "handed_on_without_a_visible_firm_filter": 8,
    "same_name_calls_not_provably_the_helper": 5,
}


# ── Read once ────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def firm_tables() -> frozenset[str]:
    meta = json.loads(SNAPSHOT_META.read_text(encoding="utf-8"))
    return frozenset(S.firm_tables_from_snapshot(schema())
                     | S.firm_tables_from_newer_migrations(
                         API / "migrations", meta["applied_through_migration"]))


@functools.lru_cache(maxsize=1)
def scan():
    chains, gates, unparsed, targets = S.scan_tree(API, set(firm_tables()), return_targets=True)
    return chains, gates, unparsed, targets


@functools.lru_cache(maxsize=1)
def current() -> dict[tuple, int]:
    return S.unscoped(scan()[0], set(firm_tables()))


@dataclass
class Entry:
    key: tuple
    count: int
    category: str
    note: str
    line: int
    tokens: dict = field(default_factory=dict)

    @property
    def file(self) -> str: return self.key[0]
    @property
    def function(self) -> str: return self.key[1]
    @property
    def table(self) -> str: return self.key[2]
    @property
    def op(self) -> str: return self.key[3]


def load_allowlist(text: str) -> dict[tuple, Entry]:
    out: dict[tuple, Entry] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) < 6:
            raise ValueError(f"allowlist line {n}: expected file | function | table | op | count | "
                             f"category [| note], got {raw!r}")
        file, function, table, op, count, category = parts[:6]
        note = parts[6] if len(parts) > 6 else ""
        key = (file, function, table, op)
        if key in out:
            raise ValueError(f"allowlist line {n}: {key} is listed twice (line {out[key].line})")
        tokens = dict(t.split("=", 1) for t in note.split() if "=" in t)
        out[key] = Entry(key, int(count), category, note, n, tokens)
    return out


def allowlist() -> dict[tuple, Entry]:
    return load_allowlist(ALLOWLIST.read_text(encoding="utf-8"))


def diff(found: dict[tuple, int], allowed: dict[tuple, Entry]):
    """(new, stale): what the tree has that the list does not account for, and what
    the list records that the tree no longer has. Counts are part of the equality."""
    new, stale = [], []
    for key in sorted(set(found) | set(allowed)):
        have = found.get(key, 0)
        want = allowed[key].count if key in allowed else 0
        if have > want:
            new.append((key, have - want))
        elif have < want:
            stale.append((key, want - have))
    return new, stale


def _describe(key: tuple, n: int, chains) -> str:
    detail = next((c.detail for c in chains if c.key == key), "")
    return f"  {n} x {' | '.join(key)}\n      {detail[:140]}"


# ── The rule ─────────────────────────────────────────────────────────────────

def test_every_query_on_a_firm_table_is_scoped_or_named_on_the_frozen_list():
    chains = scan()[0]
    new, stale = diff(current(), allowlist())
    problems = []
    if new:
        problems.append(
            "UNSCOPED, and not on tests/fixtures/firm_scope_allowlist.txt.\n"
            "A query on a table that carries a firm_id must filter on it (.eq('firm_id', ...)),\n"
            "insert a payload that carries it, or be keyed on an id somebody checked. If it\n"
            "is genuinely fine, add a line with a category and a note (and read what the\n"
            "category's check asks); if it is not, that is a cross-tenant read or write:\n"
            + "\n".join(_describe(k, n, chains) for k, n in new))
    if stale:
        problems.append(
            "ON THE LIST, BUT THE CHAIN IS GONE (or there are fewer of it). Delete the line,\n"
            "or lower its count, in the same commit as the fix:\n"
            + "\n".join(f"  {n} x {' | '.join(k)}" for k, n in stale))
    assert not problems, "\n\n".join(problems)


def test_the_list_is_well_formed_and_every_category_is_one_the_guard_knows():
    entries = allowlist()
    problems = []
    for e in entries.values():
        if e.category not in CATEGORIES:
            problems.append(f"line {e.line}: unknown category {e.category!r}")
            continue
        if e.count < 1:
            problems.append(f"line {e.line}: a count below 1 is a line to delete")
        for token in REQUIRES.get(e.category, ()):
            if not e.tokens.get(token):
                problems.append(f"line {e.line}: category {e.category} needs a `{token}=` in its note")
    ordered = sorted(entries)
    if list(entries) != ordered:
        problems.append("the list is not sorted by (file, function, table, operation)")
    assert not problems, "\n".join(problems)


def test_nothing_on_the_list_is_a_reported_exposure_nobody_listed_here():
    in_file = {k for k, e in allowlist().items() if e.category == "reported-exposure"}
    assert in_file == set(REPORTED_EXPOSURES), (
        "A `reported-exposure` line is a cross-tenant defect that is known and unfixed. It is "
        "pinned in REPORTED_EXPOSURES so that one cannot be added quietly, and the note must say "
        "in one sentence what it is.")
    for k in REPORTED_EXPOSURES:
        assert len(allowlist()[k].note) >= 40


# ── Each category's claim is checked against the code ────────────────────────

class Ctx:
    """What a category's check reads: the tree's chains, its gates, its call targets."""

    def __init__(self):
        self.chains, _g, _u, self.targets = scan()
        self.gates = S.verified_gates(API)
        self.entries = allowlist()
        self._fn: dict[str, dict] = {}
        self._calls: dict[str, list] = {}

    def chains_of(self, entry: Entry):
        return [c for c in self.chains if c.key == entry.key and not c.scoped_by]

    def source(self, rel: str) -> str:
        return (API / rel).read_text(encoding="utf-8")

    def functions(self, rel: str) -> dict:
        got = self._fn.get(rel)
        if got is None:
            idx = S._index(self.source(rel), rel)
            got = {}
            for n in idx.parent:
                if isinstance(n, S.FN):
                    enc = S._qualname(n, idx.parent)
                    got[(enc + "." if enc != "<module>" else "") + n.name] = n
            self._fn[rel] = got
        return got

    def function(self, rel: str, name: str):
        fns = self.functions(rel)
        if name in fns:
            return fns[name]
        simple = [n for q, n in fns.items() if q.split(".")[-1] == name.split(".")[-1]]
        return simple[0] if len(simple) == 1 else None

    def text_of(self, rel: str, node: ast.AST) -> str:
        lines = self.source(rel).splitlines()
        return "\n".join(lines[node.lineno - 1:node.end_lineno])


def _simple(function: str) -> str:
    return S._simple_name(function)


def _calls_gate(ctx: Ctx, node: ast.AST, extra: tuple = ()) -> str | None:
    """The name of a verified gate (or of one of `extra`) the function calls."""
    for name in S._called_names(node):
        if name in extra:
            return name
        if S.GATE_RE.match(name) and name in ctx.gates:
            return name
    return None


def check_repository_contract(e: Entry, ctx: Ctx) -> list[str]:
    if not e.file.startswith("repositories/"):
        return [f"{e.key}: only a repository method is a repository contract"]
    cls, _, method = e.function.partition(".")
    method = method.split(".")[0]
    tree = ast.parse(ctx.source(e.file))
    singleton = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                and isinstance(n.value.func, ast.Name) and n.value.func.id == cls \
                and isinstance(n.targets[0], ast.Name):
            singleton = n.targets[0].id
    if singleton is None:
        return [f"{e.key}: {cls} has no module-level singleton, so no call site resolves to it and "
                f"nothing judges its callers"]
    if method not in ctx.targets.repos.get(singleton, {}):
        return [f"{e.key}: {singleton}.{method} is not a target the guard judges at call sites"]
    return []


def check_principal(e: Entry, ctx: Ctx) -> list[str]:
    if e.table.startswith(("call:", "repo:")):
        return []
    return [f"{c.file}:{c.line} is keyed on neither an auth id nor the principal's own user id: "
            f"{c.detail[:90]}" for c in ctx.chains_of(e)
            if not re.search(r"auth_user_id|portal_user_id|user_id", c.detail)]


def check_bearer(e: Entry, ctx: Ctx) -> list[str]:
    node = ctx.function(e.file, e.function)
    if node is None:
        return [f"{e.key}: the function is not in {e.file}"]
    problems = []
    if "token" not in ctx.text_of(e.file, node).lower():
        problems.append(f"{e.key}: the function never handles a token")
    if e.tokens["token"] not in ctx.source(e.file):
        problems.append(f"{e.key}: `{e.tokens['token']}` is not in {e.file}")
    return problems


def check_provider(e: Entry, ctx: Ctx) -> list[str]:
    node = ctx.function(e.file, e.tokens["signature"])
    if node is None:
        return [f"{e.key}: signature={e.tokens['signature']} is not a function in {e.file}"]
    text = ctx.text_of(e.file, node).lower()
    return [] if ("verif" in text or "signature" in text) else [
        f"{e.key}: {e.tokens['signature']} no longer verifies a signature"]


def check_system_job(e: Entry, ctx: Ctx) -> list[str]:
    problems = []
    if not (e.file.startswith("jobs/") or e.file == "services/email_outbox_service.py"):
        problems.append(f"{e.key}: a system job lives under jobs/ or is the outbox worker")
    problems += [f"{c.file}:{c.line} sits in an HTTP handler" for c in ctx.chains_of(e) if c.is_route]
    return problems


def check_platform(e: Entry, ctx: Ctx) -> list[str]:
    problems = []
    for q, node in ctx.functions("routers/platform.py").items():
        if S._is_route(node) and "platform_admin" not in ast.unparse(node.args):
            problems.append(f"routers/platform.py::{q} is a route without a platform-admin dependency")
    return problems


def check_numbering(e: Entry, ctx: Ctx) -> list[str]:
    from services import numbering
    return [f"NUMBER_SERIES[{t!r}] is not scoped by firm_id: {scope}"
            for t, (_f, scope) in numbering.NUMBER_SERIES.items() if "firm_id" not in scope]


def check_unreachable(e: Entry, ctx: Ctx) -> list[str]:
    symbol = e.tokens["symbol"]
    cls, _, methods = symbol.partition(".")
    problems = []
    defining = e.file
    if not methods:
        for rel, line in _call_sites(ctx, cls):
            problems.append(f"{rel}:{line} calls {cls}, which this list says nobody does")
        return problems
    methods = set(methods.split(","))
    singleton = None
    for n in ast.parse(ctx.source(defining)).body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                and isinstance(n.value.func, ast.Name) and n.value.func.id == cls \
                and isinstance(n.targets[0], ast.Name):
            singleton = n.targets[0].id
    for path in S.source_files(API):
        rel = str(path.relative_to(API))
        src = path.read_text(encoding="utf-8")
        if cls not in src and not (singleton and singleton in src):
            continue
        tree = ast.parse(src)
        aliases = {singleton} if singleton else set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Name) and n.value.func.id == cls:
                aliases |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in methods:
                recv = n.func.value
                direct = isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) and recv.func.id == cls
                if direct or (isinstance(recv, ast.Name) and recv.id in aliases):
                    problems.append(f"{rel}:{n.lineno} calls {cls}.{n.func.attr}, which this list "
                                    f"says nobody does")
    return problems


def _call_sites(ctx: Ctx, name: str) -> list[tuple[str, int]]:
    got = ctx._calls.get(name)
    if got is None:
        got = []
        for path in S.source_files(API):
            rel = str(path.relative_to(API))
            src = path.read_text(encoding="utf-8")
            if name not in src:
                continue
            idx = S._index(src, rel)
            for n in idx.attr_calls + idx.name_calls:
                called = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                if called == name and S._qualname(n, idx.parent).split(".")[-1] != name:
                    got.append((rel, n.lineno))
        ctx._calls[name] = got
    return got


def check_route(e: Entry, ctx: Ctx) -> list[str]:
    rel, _, fn = e.tokens["route"].partition("::")
    node = ctx.function(rel, fn)
    if node is None:
        return [f"{e.key}: route={e.tokens['route']} does not exist"]
    problems = []
    if not S._is_route(node):
        problems.append(f"{e.tokens['route']} is not an HTTP handler")
    gate = _calls_gate(ctx, node, ("assert_client_access", "can_access_client"))
    if gate is None:
        problems.append(f"{e.tokens['route']} no longer calls a verified gate before it reaches "
                        f"{e.function}")
    via = e.tokens.get("via") or (e.table[5:] if e.table.startswith("call:") else _simple(e.function))
    if via not in S._called_names(node):
        problems.append(f"{e.tokens['route']} no longer calls `{via}`")
    return problems


def check_gate_in_function(e: Entry, ctx: Ctx) -> list[str]:
    node = ctx.function(e.file, e.function)
    if node is None:
        return [f"{e.key}: the function is not in {e.file}"]
    gate = e.tokens["gate"]
    if gate not in S._called_names(node):
        return [f"{e.key}: {e.function} no longer calls `{gate}`"]
    if S.GATE_RE.match(gate) and gate not in ctx.gates:
        return [f"{e.key}: `{gate}` is not a verified gate (its definition does not name the firm "
                f"or call one that does)"]
    return []


def check_looked_up_first(e: Entry, ctx: Ctx) -> list[str]:
    node = ctx.function(e.file, e.function)
    if node is None:
        return [f"{e.key}: the function is not in {e.file}"]
    name = e.tokens["lookup"]
    handed = [c for c in ast.walk(node) if isinstance(c, ast.Call)
              and (getattr(c.func, "attr", None) == name or getattr(c.func, "id", None) == name)
              and S._handed_the_firm(c)]
    if not handed:
        return [f"{e.key}: {e.function} no longer calls `{name}` with the firm"]
    definition = ctx.function(e.file, name) or ctx.function(e.file, f"{e.function.split('.')[0]}.{name}")
    if definition is None or not S._code_mentions_firm(definition):
        return [f"{e.key}: `{name}` is not defined in {e.file} or does not name the firm"]
    if not any(isinstance(n, ast.Raise) for n in ast.walk(definition)):
        return [f"{e.key}: `{name}` no longer raises when the row is not the firm's"]
    return []


def check_source(e: Entry, ctx: Ctx) -> list[str]:
    rel, _, fn = e.tokens["source"].partition("::")
    if ctx.function(rel, fn) is None:
        return [f"{e.key}: source={e.tokens['source']} does not exist"]
    simple = fn.split(".")[-1]
    scoped = [c for c in ctx.chains if c.file == rel and c.function.split(".")[-1] == simple
              and c.scoped_by == "filter"]
    return [] if scoped else [f"{e.key}: {e.tokens['source']} no longer reads anything under the firm"]


def check_payload_with_firm(e: Entry, ctx: Ctx) -> list[str]:
    node = ctx.function(e.file, e.function)
    if node is None:
        return [f"{e.key}: the function is not in {e.file}"]
    for n in ast.walk(node):
        if isinstance(n, ast.Dict) and S._dict_has_firm(n):
            return []
    return [f"{e.key}: {e.function} builds no payload with a firm_id any more"]


def check_helper_of_call(e: Entry, ctx: Ctx) -> list[str]:
    """Some call to this helper is on the list under a category that is not this one
    (or is itself such a helper whose own support is, down to a real reason)."""
    name = _simple(e.function)

    def supported(entry: Entry, seen: frozenset) -> bool:
        target = _simple(entry.function)
        for other in ctx.entries.values():
            if other.table != f"call:{target}" or other.key in seen:
                continue
            if other.category != "helper-of-allowlisted-call" \
                    or supported(other, seen | {entry.key}):
                return True
        return False

    return [] if supported(e, frozenset()) else [
        f"{e.key}: no allowlisted call to `{name}` stands behind this helper, so the guard cleared "
        f"nothing and the helper should be judged on its own"]


def check_reported(e: Entry, ctx: Ctx) -> list[str]:
    return [] if len(e.note) >= 40 else [f"{e.key}: a reported exposure says in a sentence what it is"]


_CHECKS = {
    "repository-contract": check_repository_contract,
    "principal-lookup": check_principal,
    "bearer-token": check_bearer,
    "provider-callback": check_provider,
    "system-job": check_system_job,
    "platform-admin": check_platform,
    "numbering-series": check_numbering,
    "gated-by-route": check_route,
    "gated-in-function": check_gate_in_function,
    "own-insert-id": check_gate_in_function,
    "looked-up-first": check_looked_up_first,
    "from-scoped-row": check_source,
    "child-by-parent": check_source,
    "payload-with-firm": check_payload_with_firm,
    "helper-of-allowlisted-call": check_helper_of_call,
    "unreachable-code": check_unreachable,
    "reported-exposure": check_reported,
}


def test_every_category_has_a_check_and_the_checks_are_the_vocabulary():
    assert set(_CHECKS) == set(CATEGORIES)


def test_what_each_allowlisted_line_claims_is_still_true_of_the_code():
    ctx = Ctx()
    problems: list[str] = []
    for e in ctx.entries.values():
        problems += _CHECKS[e.category](e, ctx)
    assert not problems, (
        "An allowlisted line says something about the code (a gate is called, a lookup raises,\n"
        "a function has no caller) and the code no longer agrees. Re-read the function; either\n"
        "the claim is false and the chain is a finding, or the note is stale:\n  "
        + "\n  ".join(problems))


# ── What the reader could not read is counted, not ignored ───────────────────

def test_the_chains_the_reader_cannot_read_are_budgeted_exactly():
    census = S.census(scan()[0], set(firm_tables()))
    got = {k: census[k] for k in UNREADABLE_BUDGET}
    assert got == UNREADABLE_BUDGET, (
        f"The reader's blind spots moved: {got} against the budget {UNREADABLE_BUDGET}. A table named "
        "by a variable, a chain handed on without a firm filter you can see, or a same-name call "
        "that cannot be tied to its helper is a place a missing filter would not be found. Add the "
        "scope where the reader can see it, or move the budget on purpose.")
    assert scan()[2] == 0, "a file under apps/api no longer parses, so none of its queries was read"


def test_the_scan_covers_what_it_claims_to_and_no_evidence_kind_went_vacuous():
    census = S.census(scan()[0], set(firm_tables()))
    assert census["judged"] >= 2200, census
    assert census["calls_judged_as_queries"] >= 450, census
    for kind in ("filter", "payload", "gate", "flow", "parent-read", "callers", "pass-through",
                 "principal", "post-fetch"):
        assert census["by_evidence"].get(kind, 0) > 0, (
            f"no chain is cleared by `{kind}` any more: either the reader stopped recognising it "
            f"or the pattern is gone; {census['by_evidence']}")
    assert census["by_evidence"]["unscoped"] == sum(current().values())


def test_the_firm_table_set_comes_from_the_snapshot_and_newer_migrations():
    meta = json.loads(SNAPSHOT_META.read_text(encoding="utf-8"))
    tables = firm_tables()
    from_snapshot = {t for t, cols in schema().items() if "firm_id" in cols}
    assert from_snapshot <= tables
    assert len(from_snapshot) >= 290
    for sentinel in ("customers", "vendors", "clients", "journal_entries", "purchase_bills",
                     "payroll_runs", "client_sales_invoices", "receipts", "gstr1_returns"):
        assert sentinel in tables, sentinel
    # Tables created after the snapshot, so a table-set read from the snapshot alone would
    # let every one of them through unscoped.
    for newer in ("ai_firm_budgets", "email_outbox", "scheduler_claims", "gst_credit_ledger_openings"):
        assert newer in tables, newer
    assert isinstance(meta["applied_through_migration"], int)


def test_a_table_a_newer_migration_gives_a_firm_id_is_a_firm_table(tmp_path):
    (tmp_path / "470_old.sql").write_text(
        "CREATE TABLE public.zz_old (id uuid, firm_id uuid);", encoding="utf-8")
    (tmp_path / "477_new.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.zz_new (\n  id uuid primary key,\n  firm_id uuid not null,\n"
        "  note text\n);\n-- CREATE TABLE public.zz_commented (firm_id uuid);\n"
        "ALTER TABLE public.zz_existing ADD COLUMN IF NOT EXISTS firm_id uuid;\n"
        "CREATE TABLE public.zz_plain (id uuid, name text);", encoding="utf-8")
    (tmp_path / "477_new_rollback.sql").write_text(
        "CREATE TABLE public.zz_rollback (firm_id uuid);", encoding="utf-8")
    found = S.firm_tables_from_newer_migrations(tmp_path, 470)
    assert found == {"zz_new", "zz_existing"}


# ── The value of a firm filter, bounded from the outside ─────────────────────

def test_no_route_outside_the_platform_console_takes_a_firm_id_from_the_request():
    offenders = []
    for path in S.source_files(API):
        rel = str(path.relative_to(API))
        if not rel.startswith("routers/") or rel == "routers/platform.py":
            continue
        src = path.read_text(encoding="utf-8")
        if "firm_id" not in src:
            continue
        for n in S._index(src, rel).parent:
            if isinstance(n, S.FN) and S._is_route(n) and "firm_id" in S._fn_params(n):
                offenders.append(f"{rel}::{n.name}")
    assert not offenders, (
        "A route that takes a firm_id from the request lets the caller choose the tenant the "
        f"service-role key then filters on: {offenders}")


def test_no_request_model_has_a_firm_id_field():
    offenders = []
    for path in sorted((API / "models").rglob("*.py")):
        for c in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(c, ast.ClassDef) and re.search(r"(In|Create|Update|Request|Body|Payload)$", c.name):
                for b in c.body:
                    if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name) \
                            and b.target.id == "firm_id":
                        offenders.append(f"{path.relative_to(API)}::{c.name}")
    assert not offenders, f"a request model that names the firm lets the body choose it: {offenders}"


# ── The controls: the guard goes red when it should ──────────────────────────

def _unscoped_in(rel: str, source: str) -> dict[tuple, int]:
    """The unscoped chains the reader finds in ONE file, read on its own."""
    chains = S.scan_source(source, rel, set(firm_tables()), S.verified_gates(API))[0]
    return S.unscoped(chains, set(firm_tables()))


def _newly_unscoped(rel: str, before: str, after: str) -> list[tuple]:
    """What editing a file adds to the unscoped chains found in it (read on its own,
    so a chain the tree-wide pass clears through its callers is in BOTH and cancels)."""
    base = _unscoped_in(rel, before)
    return sorted(k for k, n in _unscoped_in(rel, after).items() if n > base.get(k, 0))


def _guard_verdict(extra: tuple) -> list[tuple]:
    """What the guard reports if the tree gained one more unscoped chain at `extra`."""
    found = dict(current())
    found[extra] = found.get(extra, 0) + 1
    return [k for k, _n in diff(found, allowlist())[0]]


def test_deleting_a_firm_filter_from_a_scoped_query_turns_the_guard_red():
    rel = "routers/firm_hsn_library.py"
    src = (API / rel).read_text(encoding="utf-8")
    needle = 'query = db.table("firm_hsn_library").select("*").eq("firm_id", firm_id)'
    assert src.count(needle) == 1, "the control's premise moved: pick another scoped query"
    mutated = src.replace(needle, 'query = db.table("firm_hsn_library").select("*")')
    added = _newly_unscoped(rel, src, mutated)
    assert added == [(rel, "list_library", "firm_hsn_library", "read")], added
    # The reader sees it, and the guard (which compares against the frozen list) reports it.
    assert _guard_verdict(added[0]) == [added[0]]
    # Nothing is added by leaving the file alone.
    assert _newly_unscoped(rel, src, src) == []


def test_a_query_that_is_gated_not_filtered_survives_losing_its_filter_by_design():
    """The rule is `scoped`, not `filtered`: a read keyed on a client the same function
    asserted with a verified gate is child-by-parent and stays clear. This pins that the
    control above is a CONTROL (it removes the only evidence) and not an accident."""
    rel = "routers/customers.py"
    src = (API / rel).read_text(encoding="utf-8")
    needle = '.eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id))'
    assert src.count(needle) == 1
    assert _newly_unscoped(rel, src, src.replace(needle, '.eq("client_id", client_id))')) == []


def test_a_new_query_on_customers_with_no_firm_scope_fails():
    rel = "routers/customers.py"
    src = (API / rel).read_text(encoding="utf-8")
    leaky = src + (
        "\n\ndef _a_helper_somebody_adds(db, customer_id):\n"
        "    return db.table(\"customers\").select(\"*\").eq(\"id\", customer_id).execute().data\n")
    added = _newly_unscoped(rel, src, leaky)
    assert added == [(rel, "_a_helper_somebody_adds", "customers", "read")], added
    assert _guard_verdict(added[0]) == [added[0]]
    scoped = src + (
        "\n\ndef _a_helper_somebody_adds(db, firm_id, customer_id):\n"
        "    return (db.table(\"customers\").select(\"*\").eq(\"id\", customer_id)\n"
        "            .eq(\"firm_id\", firm_id).execute().data)\n")
    assert _newly_unscoped(rel, src, scoped) == []


def test_an_allowlist_line_whose_chain_was_fixed_is_stale_and_fails():
    entries = allowlist()
    key = ("routers/zz_fixed.py", "handler", "customers", "read")
    padded = dict(entries)
    padded[key] = Entry(key, 1, "gated-by-route", "route=x::y", 999)
    _new, stale = diff(current(), padded)
    assert stale == [(key, 1)]
    # a count recorded too high is stale too: a fix that removes ONE of two chains
    some = next(k for k, e in entries.items() if e.count == 1)
    bumped = dict(entries)
    bumped[some] = Entry(some, 2, entries[some].category, entries[some].note, entries[some].line)
    assert diff(current(), bumped)[1] == [(some, 1)]
    # and a new chain under an existing key is new
    fewer = dict(entries)
    fewer[some] = Entry(some, 0, entries[some].category, entries[some].note, entries[some].line)
    assert diff(current(), fewer)[0] == [(some, 1)]


def test_a_doctored_note_fails_its_category_check():
    ctx = Ctx()
    route = next(e for e in ctx.entries.values() if e.category == "gated-by-route")
    assert check_route(route, ctx) == []
    gone = Entry(route.key, route.count, route.category, "route=routers/invoices.py::no_such_route",
                 route.line, {"route": "routers/invoices.py::no_such_route"})
    assert check_route(gone, ctx), "a route that does not exist must fail its check"
    not_a_route = Entry(route.key, route.count, route.category,
                        "route=routers/invoices.py::_assert_invoice_scope",
                        route.line, {"route": "routers/invoices.py::_assert_invoice_scope"})
    assert any("not an HTTP handler" in p for p in check_route(not_a_route, ctx))

    lookup = next(e for e in ctx.entries.values() if e.category == "looked-up-first")
    assert check_looked_up_first(lookup, ctx) == []
    wrong = Entry(lookup.key, lookup.count, lookup.category, "lookup=_audit", lookup.line,
                  {"lookup": "_audit"})
    assert check_looked_up_first(wrong, ctx), "a helper that does not look the row up must fail"

    unreachable = next(e for e in ctx.entries.values() if e.category == "unreachable-code"
                       and e.tokens["symbol"] == "generate_recurring_invoice")
    assert check_unreachable(unreachable, ctx) == []
    reached = Entry(unreachable.key, unreachable.count, unreachable.category, "symbol=get_invoice_pdf",
                    unreachable.line, {"symbol": "get_invoice_pdf"})
    assert check_unreachable(reached, ctx), "a function with a production caller is not unreachable"


def test_a_helper_is_cleared_only_when_every_call_to_it_is_and_somebody_calls_it(tmp_path):
    (tmp_path / "services").mkdir()
    (tmp_path / "routers").mkdir()
    (tmp_path / "services" / "h.py").write_text(
        "def put(db, customer_id):\n"
        "    return db.table('customers').update({'x': 1}).eq('id', customer_id).execute()\n",
        encoding="utf-8")
    (tmp_path / "routers" / "r.py").write_text(
        "from services import h\n"
        "from core.authz import assert_client_access\n"
        "def _assert_customer_scope(current_user, customer_id):\n"
        "    return current_user['firm_id'] == customer_id\n"
        "@router.post('/a')\n"
        "def good(customer_id, current_user):\n"
        "    _assert_customer_scope(current_user, customer_id)\n"
        "    return h.put(db, customer_id)\n", encoding="utf-8")
    chains, _g, _u = S.scan_tree(tmp_path, {"customers"})
    assert S.unscoped(chains, {"customers"}) == {}
    (tmp_path / "routers" / "r2.py").write_text(
        "from services import h\n"
        "@router.post('/b')\n"
        "def bad(customer_id):\n"
        "    return h.put(db, customer_id)\n", encoding="utf-8")
    chains, _g, _u = S.scan_tree(tmp_path, {"customers"})
    keys = set(S.unscoped(chains, {"customers"}))
    assert ("routers/r2.py", "bad", "call:put", "update") in keys
    assert ("services/h.py", "put", "customers", "update") in keys, (
        "one unchecked caller leaves the helper's own chain unscoped")
