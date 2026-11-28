"""A route that writes a table the row-level audit trigger does not cover records who wrote it, or says why it need not (POST-A-167).

THE PREMISE. Migration 111 attached `trg_audit_capture` to the firm tables that existed that day and nothing attached it to any table made later.
A freshly migrated database holds 223 tables without it (`tests/fixtures/tables_without_an_audit_trigger.txt`, held equal to the database by the
real-Postgres test at the foot of this file). A write the API makes to one of them leaves no row in the audit log unless the route says so with
`audit_service.log_event`. The first pass of this finding (16-11-2026) read the writers of the worst-affected tables by hand and fixed eight of
them; this is the RULE it asked for, so the next table and the next route are held without anybody remembering to read them.

WHAT IS HELD
    Every route (a POST, PUT, PATCH or DELETE in `routers/`) that can reach a write to one of those tables, directly or through the functions it
    calls, also reaches an audit call (`audit_service.log_event` or `log_write` (resolved through the imports, not by the name alone), `@audited`, or a write to `audit_log` / `platform_audit` itself), or is on
    `EXEMPT` below with one of five reasons. The list only shrinks: an entry whose route now audits, or no longer writes such a table, fails
    until it is taken off, so it cannot keep permitting a route that has since been fixed.

WHAT THE WALK SEES, AND WHAT IT DOES NOT
    It reads the source (`ast`) of `routers/`, `services/`, `domain/`, `core/`, `jobs/` and, since 28-11-2026, `repositories/`. It follows a call
    by its name to a function of the same module or of a module the caller imports (`from x import f`, `import x as m` then `m.f()`), and,
    since the same day, a call on an OBJECT BUILT FROM A CLASS to that class's method of the same name: an object a module builds at its top
    (`client_repo = ClientRepository()`) and another module imports, one a function builds for itself (`repo = Repo(db)`), and a class
    called directly (`Repo.method()`). It takes a table from `.table("name")` or `.from_("name")` followed by `.insert`, `.update`, `.upsert`
    or `.delete` in one chain, the name being a literal or a module-level constant. The wider walk found 48 more routes: six were a person's
    act with no record of who (acknowledging or dismissing an insight, changing its status, removing a task's dependency, writing a
    notification to a member, marking a Form 26AS as uploaded) and carry the marker now; 42 write only a log the product keeps and are on
    the list with their reason; and one route that was on the list turned out to record its write after all, and came off.
    A chain split over statements is read too since 28-11-2026 (`t = db.table("x")` and then `t.update(...)`, or `q = q.eq(...)` on the way): a
    name bound to a table is that table where it is written. Only one function in the tree had that shape (`relationships.create_loan`, whose
    table carries the trigger), so nothing new was flagged; it is held so the next one is. A write whose table name is a variable of the
    function cannot be followed by name, and the two the tree has are on `WRITES_THROUGH_A_VARIABLE` below with what bounds each, so a third
    fails the test that counts them.
    Four more shapes are read since 28-11-2026 (the last part of the finding):
      - a RELATIVE import (`from .x import f`, `from . import x`; 63 of them, all in `domain/`) is read against the importer's own package;
      - a function HANDED to another to be called (`run_in_threadpool(service.process, ...)`, `add_task(fn)`, a retry wrapper) is followed as
        a call, where the name is one the walk can place exactly (a function of the module, an import, a method of a known object), never
        by a bare name;
      - an object KEPT FROM A FUNCTION'S RETURN (`repo = make_repo()`, in a function or at the top of a module another imports) and an object
        HANDED IN AS AN ARGUMENT (`def f(repo: Repo)`) are read as the class the function hands back (its annotation, or the class it builds
        in a `return`) or the parameter names, and a call on them is a call of that class's method;
      - a METHOD is the method of ITS class: two classes in one module with a method of the same name are told apart, a method the class
        does not define is looked for in the base classes it names (in this module or another), and `self.other()` is the object's own.
    What that flagged: one route. The mail provider's webhook (`email_webhooks.resend_webhook`) hands its work to a function it passes to the
    thread pool, and that function moves the delivery rows of an invoice or a statement mail to what the provider reported. No person is in
    that request, so it is on EXEMPT with its reason. Nine other routes now reach more tables than the walk saw (the payment webhook, which
    turned out to record its write; three platform routes that write the platform's own audit table; three issue routes that count a use
    of a catalogue item; two portal routes that touch the portal session log), and none of them is newly unrecorded.
    It still does NOT see, and cannot by reading names: a table named in a variable of a function (the two on that list aside); an object whose
    class nothing in the source states (an unannotated parameter, a function with no annotation that builds no class in its `return`, a value
    pulled out of a dict or a list); a function reached through `getattr` or a table of functions; or a write made by the database itself (a
    trigger or `.rpc(...)`, which the real-Postgres tests of each function hold). A route that reaches an audit call on some path is read as
    audited for all of its writes, which is the cost of not tracing which branch writes what. A call named `log_event` counts only when the
    module imports it from `services.audit_service`. The ledger's own tables carry the trigger, so a journal posted by a route is audited as
    it always was.

THE FIVE REASONS A ROUTE MAY BE EXEMPT (each entry names its own words)
    derived     the rows are computed by the product from other records (a score, a reconciliation, a cache, a sync of portal data): no person
                stated them, and the records they were computed from are audited where they were written;
    own_log     the table IS a log, or each row names the person and the day it was made, so an audit row would say the same thing twice;
    lines       the rows are the lines of a header that carries the trigger, and the header's write is the audited act;
    personal    the row is the signed-in person's own preference;
    mail        the row records an email the product sent on somebody's behalf, which is itself the record of who sent it.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
FIXTURE = API / "tests" / "fixtures" / "tables_without_an_audit_trigger.txt"

WRITE_OPS = {"insert", "update", "upsert", "delete"}
AUDIT_CALLS = {"log_event", "log_write", "_audit"}   # `_audit` is followed into, not trusted by name
#: Tables that ARE the audit trail: a route that writes one has recorded who wrote.
AUDIT_TABLES = {"audit_log", "platform_audit"}
ROUTE_VERBS = {"post", "put", "patch", "delete"}
REASONS = {"derived", "own_log", "lines", "personal", "mail"}


def audit_less_tables() -> frozenset[str]:
    return frozenset(l.strip() for l in FIXTURE.read_text().splitlines() if l.strip())


class _Fn:
    def __init__(self, module: str, node: ast.AST):
        self.module = module
        self.node = node
        self.name = node.name
        self.writes: set[str] = set()
        self.audits = False
        self.calls: list[tuple[str | None, str | None, bool]] = []   # (owner, name, strict): strict is a function handed over, not called
        self.cls: str | None = None            # the class this is a method of
        self.returns: tuple[str | None, str] | None = None   # the class of the object it hands back, as its own module names it
        self.locals: dict[str, tuple[str | None, str]] = {}        # `repo = Repo(...)`
        self.held: dict[str, tuple[str | None, str | None]] = {}   # `repo = make_repo()`: the function whose return the name holds
        self.params: dict[str, tuple[str | None, str]] = {}        # `def f(repo: Repo)`


def _chains(fn: ast.AST, constants: dict[str, str] | None = None):
    """(table, ops) for every `.table("x")` / `.from_("x")` chain in a function; the name may be a module-level constant (`LOANS_TABLE = "x"`)."""
    constants = constants or {}

    def table_of(call: ast.Call) -> str | None:
        if not call.args:
            return None
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return constants.get(arg.id)
        return None

    def reaches_a_table(value: ast.AST, bound: dict[str, set[str]]) -> set[str]:
        """The tables a chain starts from: `db.table("x")...` names one, and `q.eq(...)...` names what `q` was bound to (POST-A-167, a chain split over statements)."""
        cur = value
        while True:
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                if cur.func.attr in ("table", "from_") and table_of(cur):
                    return {table_of(cur)}
                cur = cur.func.value
            elif isinstance(cur, ast.Attribute):
                cur = cur.value
            elif isinstance(cur, ast.Name):
                return set(bound.get(cur.id, ()))
            else:
                return set()

    # `q = db.table("x")` and then `q.update(...)`, or `q = q.eq(...)` on the way: the name is bound to the table. A name may be bound to
    # more than one table in a function, and then every one of them is read as the table it can write.
    bound: dict[str, set[str]] = collections.defaultdict(set)
    assigns = [(tg.id, st.value) for st in ast.walk(fn) if isinstance(st, ast.Assign) and isinstance(st.value, (ast.Call, ast.Attribute))
               for tg in st.targets if isinstance(tg, ast.Name)]
    for _ in range(3):
        for name, value in assigns:
            bound[name] |= reaches_a_table(value, bound)

    for c in ast.walk(fn):
        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)):
            continue
        ops: list[str] = []
        cur = c
        while True:
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                ops.append(cur.func.attr)
                if cur.func.attr in ("table", "from_") and table_of(cur):
                    yield table_of(cur), set(ops)
                    break
                cur = cur.func.value
            elif isinstance(cur, ast.Attribute):
                cur = cur.value
            elif isinstance(cur, ast.Name) and cur.id in bound:
                for table in sorted(bound[cur.id]):
                    yield table, set(ops)
                break
            else:
                break


def _class_called(call: ast.Call) -> tuple[str | None, str] | None:
    """`Repo(...)` -> (None, "Repo"); `mod.Repo(...)` -> ("mod", "Repo"); anything else is not an object being built from a named class.
    A lower-case name is a function call and is left alone (its return is not followed)."""
    fn = call.func
    if isinstance(fn, ast.Name) and fn.id[:1].isupper():
        return (None, fn.id)
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.attr[:1].isupper():
        return (fn.value.id, fn.attr)
    return None


def _class_named(node: ast.AST | None) -> tuple[str | None, str] | None:
    """The class an annotation or a base names: `Repo`, `mod.Repo`, `"Repo"`, `Optional[Repo]`, `Repo | None`. Lower-case names are not classes."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return (None, node.id) if node.id[:1].isupper() and node.id not in ("None", "Optional", "Any") else None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return (node.value.id, node.attr) if node.attr[:1].isupper() else None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _class_named(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return None
    if isinstance(node, ast.Subscript):
        return _class_named(node.slice)
    if isinstance(node, ast.BinOp):
        return _class_named(node.left) or _class_named(node.right)
    return None


def _callee(call: ast.Call) -> tuple[str | None, str | None]:
    fn = call.func
    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
    owner = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else None
    return owner, name


def _is_the_audit_service(imports: dict, owner: str | None, name: str) -> bool:
    """A call named `log_event` / `log_write` counts only when it is `services.audit_service`'s: another module has a `log_event` too (the task
    timeline's, which writes `task_timeline` and not `audit_log`), and a name is not a promise. `_audit` is a router's own helper and is followed
    into, so its own `log_event` is what counts."""
    if name == "_audit":
        return False
    if owner is None:
        return imports.get(name, (None, None))[0] == "services.audit_service"
    mod, attr = imports.get(owner, (None, None))
    return (mod == "services.audit_service" and attr is None) or (mod == "services" and attr == "audit_service")


class Walk:
    """The functions of a set of modules, who calls whom, and which write which tables. `sources` maps a dotted module name to its text."""

    def __init__(self, sources: dict[str, str]):
        self.funcs: dict[tuple[str, str], list[_Fn]] = collections.defaultdict(list)
        self.imports: dict[str, dict[str, tuple[str, str | None]]] = {}
        self.modules = set(sources)
        self.instances: dict[str, dict[str, tuple[str | None, str]]] = {}
        self.held: dict[str, dict[str, tuple[str | None, str | None]]] = {}    # a module-level `x = factory()`
        self.classes: dict[str, set[str]] = {}
        self.bases: dict[tuple[str, str], list[tuple[str | None, str]]] = {}
        for module, text in sources.items():
            tree = ast.parse(text)
            imp: dict[str, tuple[str, str | None]] = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom):
                    # a relative import (`from .x import f`, `from . import x`) is read against the importer's own package
                    target = ".".join(module.split(".")[:-n.level] + ([n.module] if n.module else [])) if n.level else (n.module or "")
                    for a in n.names if target else ():
                        imp[a.asname or a.name] = (target, a.name)
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        imp[(a.asname or a.name).split(".")[0]] = (a.name, None)
            self.imports[module] = imp
            # `repo = ClientRepository()` at module level, and `Something` defined as a class here: a call on either is a call of a METHOD
            # of this module's or the class's module (POST-A-167, the wider walk).
            self.instances.setdefault(module, {})
            self.held.setdefault(module, {})
            for st in tree.body:
                if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call):
                    made = _class_called(st.value)
                    for tg in st.targets:
                        if made and isinstance(tg, ast.Name):
                            self.instances[module][tg.id] = made
                        elif isinstance(tg, ast.Name):
                            # `repo = make_repo()` at the top of a module: the name holds whatever that function hands back
                            self.held[module][tg.id] = _callee(st.value)
            self.classes.setdefault(module, set()).update(n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
            method_of: dict[int, str] = {}
            for c in ast.walk(tree):
                if isinstance(c, ast.ClassDef):
                    self.bases[(module, c.name)] = [made for b in c.bases for made in [_class_named(b)] if made]
                    method_of.update({id(st): c.name for st in c.body if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))})
            constants = {t.id: v.value for t, v in ((tg, st.value) for st in tree.body if isinstance(st, ast.Assign)
                                                    for tg in st.targets if isinstance(tg, ast.Name))
                         if isinstance(v, ast.Constant) and isinstance(v.value, str)}
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f = _Fn(module, n)
                    f.writes = {t for t, ops in _chains(n, constants) if ops & WRITE_OPS}
                    # `repo = ClientRepository(db)` inside the function: a call on `repo` is a call of that class's method
                    f.locals = {tg.id: made for st in ast.walk(n) if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call)
                                for made in [_class_called(st.value)] if made
                                for tg in st.targets if isinstance(tg, ast.Name)}
                    f.cls = method_of.get(id(n))
                    # what it hands back: its annotation, or the class it builds in a `return`
                    f.returns = _class_named(n.returns) or next(
                        (made for st in ast.walk(n) if isinstance(st, ast.Return) and isinstance(st.value, ast.Call)
                         for made in [_class_called(st.value)] if made), None)
                    # `repo = make_repo()`: a call on `repo` is a call of a method of whatever class `make_repo` hands back
                    f.held = {tg.id: _callee(st.value) for st in ast.walk(n) if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call)
                              and not _class_called(st.value) for tg in st.targets if isinstance(tg, ast.Name)}
                    # `def f(repo: Repo)`: an object handed in, by the class its parameter names
                    f.params = {a.arg: made for a in (n.args.posonlyargs + n.args.args + n.args.kwonlyargs)
                                for made in [_class_named(a.annotation)] if made}
                    for c in ast.walk(n):
                        if isinstance(c, ast.Call):
                            owner, name = _callee(c)
                            if name in AUDIT_CALLS and _is_the_audit_service(imp, owner, name):
                                f.audits = True
                            f.calls.append((owner, name, False))
                            # a function handed to another to be called (`run_in_threadpool(service.process, ...)`, `add_task(fn)`,
                            # `retry(fn)`): followed as a call, and only where the name is one the walk can place exactly
                            for a in [*c.args, *(k.value for k in c.keywords)]:
                                handed = (None, a.id) if isinstance(a, ast.Name) else (
                                    (a.value.id, a.attr) if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) else None)
                                if handed:
                                    if handed[1] in AUDIT_CALLS and _is_the_audit_service(imp, *handed):
                                        f.audits = True
                                    f.calls.append((*handed, True))
                    if f.writes & AUDIT_TABLES:
                        f.audits = True
                    # `@audited("kind", "action")` (services/audit_service.py) records the write when the route answers success.
                    for d in n.decorator_list:
                        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "audited":
                            f.audits = True
                            f.audited_by_decorator = True
                    self.funcs[(module, n.name)].append(f)

    def _module_of_a_class(self, module: str, made: tuple[str | None, str]) -> str | None:
        """The module that defines the class `made` names, as `module` sees it: `Repo(...)` (imported, or defined here) or `mod.Repo(...)`."""
        prefix, cls = made
        imp = self.imports.get(module, {})
        if prefix is not None:
            mod, attr = imp.get(prefix, (None, None))
            candidate = (mod + "." + attr) if (mod and attr) else mod
            return candidate if candidate in self.modules and cls in self.classes.get(candidate, ()) else None
        if cls in self.classes.get(module, ()):
            return module
        mod, attr = imp.get(cls, (None, None))
        return mod if mod in self.modules and attr in self.classes.get(mod, ()) else None

    def _methods(self, where: str, cls: str, name: str, depth: int = 0) -> list[_Fn]:
        """The method `name` of the class `cls` of module `where`: its own, or the nearest one a base class it names gives it."""
        own = [g for g in self.funcs.get((where, name), []) if g.cls == cls]
        if own or depth > 5:
            return own
        found: list[_Fn] = []
        for base in self.bases.get((where, cls), []):
            base_module = self._module_of_a_class(where, base)
            if base_module:
                found += self._methods(base_module, base[1], name, depth + 1)
        return found

    def _handed_back(self, module: str, source: tuple[str | None, str | None], name: str, held: dict, depth: int) -> list[_Fn]:
        """`x = make()` and then `x.name()`: the method `name` of the class each function `make` can be hands back."""
        probe = _Fn.__new__(_Fn)
        probe.module, probe.cls, probe.locals, probe.params, probe.held = module, None, {}, {}, {k: v for k, v in held.items() if v != source}
        found: list[_Fn] = []
        for g in self._resolve(probe, source[0], source[1], depth=depth + 1):
            where = self._module_of_a_class(g.module, g.returns) if g.returns else None
            if where:
                found += self._methods(where, g.returns[1], name)
        return found

    def _resolve(self, f: _Fn, owner: str | None, name: str | None, strict: bool = False, depth: int = 0) -> list[_Fn]:
        """The functions a call `owner.name(...)` (or `name(...)`) made inside `f` can be. `strict` is for a function HANDED to another and
        not called: it is followed only where the walk can place it exactly, never by a bare name in the same module."""
        if name is None or depth > 4:
            return []
        imp = self.imports.get(f.module, {})
        found: list[_Fn] = []
        if owner is None:
            found += [g for g in self.funcs.get((f.module, name), []) if g.cls is None or not strict]
            if name in imp:
                mod, attr = imp[name]
                if attr:
                    found += self.funcs.get((mod, attr), [])
        elif owner == "self" and f.cls:
            # a method calling another method of its own object: its class's, or a base's; a name the class does not have is looked for
            # in the module as before (a function kept on the object)
            found += self._methods(f.module, f.cls, name) or ([] if strict else self.funcs.get((f.module, name), []))
        elif owner in f.locals or owner in self.instances.get(f.module, {}):
            # a call on an object this function, or this module, built from a class: the class's method of that name
            made = f.locals.get(owner) or self.instances[f.module][owner]
            where = self._module_of_a_class(f.module, made)
            found += self._methods(where, made[1], name) if where else ([] if strict else self.funcs.get((f.module, name), []))
        elif owner in f.params and self._module_of_a_class(f.module, f.params[owner]):
            # an object handed in as an argument, by the class its parameter names
            found += self._methods(self._module_of_a_class(f.module, f.params[owner]), f.params[owner][1], name)
        elif owner in f.held or owner in self.held.get(f.module, {}):
            # an object kept from a function's return, in this function or at the top of this module
            found += self._handed_back(f.module, f.held.get(owner) or self.held[f.module][owner], name, f.held, depth)
            if not found and not strict and owner not in imp:
                found += self.funcs.get((f.module, name), [])
        elif owner in imp:
            mod, attr = imp[owner]
            for candidate in ((mod + "." + attr) if attr else None, mod if attr is None else None):
                if candidate and candidate in self.modules:
                    found += [g for g in self.funcs.get((candidate, name), []) if g.cls is None]
            if attr and mod in self.modules:
                # `from repositories.x import x_repository` (an object the module built, from a class or kept from a function's return)
                # or `import Repo` (a class): its method
                made = self.instances.get(mod, {}).get(attr)
                where = self._module_of_a_class(mod, made) if made else (mod if attr in self.classes.get(mod, ()) else None)
                if where:
                    found += self._methods(where, made[1] if made else attr, name)
                elif attr in self.held.get(mod, {}):
                    found += self._handed_back(mod, self.held[mod][attr], name, {}, depth)
        elif not strict:
            found += self.funcs.get((f.module, name), [])
        return found

    def reach(self, start: _Fn) -> tuple[set[str], bool]:
        """Every table the function can write through what it calls, and whether anything it calls (or it) audits."""
        seen: set[int] = set()
        stack = [start]
        writes: set[str] = set()
        audits = False
        while stack:
            f = stack.pop()
            if id(f) in seen:
                continue
            seen.add(id(f))
            writes |= f.writes
            audits = audits or f.audits
            for owner, name, strict in f.calls:
                stack.extend(self._resolve(f, owner, name, strict))
        return writes, audits

    def write_routes(self) -> list[tuple[_Fn, str]]:
        routes = []
        for (module, _), fns in self.funcs.items():
            if not module.startswith("routers."):
                continue
            for f in fns:
                for d in f.node.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_VERBS
                            and isinstance(d.func.value, ast.Name) and d.func.value.id.endswith("router")):
                        routes.append((f, d.func.attr))
        return routes

    def unaudited(self, tables: frozenset[str]) -> dict[tuple[str, str], tuple[str, ...]]:
        """{(router module, function): the audit-less tables it can write} for each write route that reaches none of the audit calls."""
        out = {}
        for f, _verb in self.write_routes():
            writes, audits = self.reach(f)
            hit = writes & tables
            if hit and not audits:
                out[(f.module.split(".", 1)[1], f.name)] = tuple(sorted(hit))
        return out


def _sources() -> dict[str, str]:
    found = {}
    for sub in ("routers", "services", "domain", "core", "jobs", "repositories"):
        for p in (API / sub).rglob("*.py"):
            if p.name == "__init__.py" or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(API).with_suffix("")
            found[".".join(rel.parts)] = p.read_text(encoding="utf-8")
    return found


#: {(router, route function): (reason, why)}. Filled by reading each route; every reason is one of REASONS and says WHY in words.
EXEMPT: dict[tuple[str, str], tuple[str, str]] = {
    ("form_26as", "run_reconciliation"): ("derived", "Writes the comparison of Form 26AS with the books, computed by the product from records that are audited where they were written."),
    ("gst_portal", "run_sync_job"): ("derived", "Stores what the portal returned and the job's own result; nobody stated these figures."),
    ("health", "calculate_score"): ("derived", "A client's health score is computed from the books and stored with its history; nobody states it."),
    ("health", "recalculate_all"): ("derived", "The same computation over every client of the firm."),
    ("health", "resolve_alert"): ("own_log", "The alert row names who resolved it and when (resolved_by, resolved_at)."),
    ("inventory", "open_count_session"): ("own_log", "The session row names who opened it (created_by) and its lines are the stock the book held that day, copied by the product."),
    ("notifications", "set_email_preference"): ("personal", "The signed-in person's own choice about which mails they get."),
    ("payroll", "create_run"): ("lines", "The slips are the lines of a payroll run, whose own row carries the trigger; the run is the audited act."),
    ("payroll", "update_run_status"): ("own_log", "payroll_run_transitions IS the run's log: every move is a row with the person (actor_id)."),
    ("payroll", "disburse_run"): ("own_log", "payroll_run_transitions IS the run's log: every move is a row with the person (actor_id)."),
    ("portal", "create_document_request"): ("mail", "The only table it writes without a trigger is the log of the mail it sent, which names the sender."),
    ("portal", "send_message"): ("mail", "The only table it writes without a trigger is the log of the mail it sent, which names the sender."),
    ("portal_data", "portal_post_message"): ("mail", "The only table it writes without a trigger is the log of the mail it sent, which names the sender."),
    ("reconciliation", "verify_books"): ("derived", "The findings are computed by the product from the books; each finding is later resolved by a person through its own route."),
    ("recurring_invoices", "create_recurring"): ("lines", "Writes the lines of a recurring-invoice template, whose header carries the trigger."),
    ("recurring_invoices", "update_recurring"): ("lines", "Rewrites the lines of a recurring-invoice template, whose header carries the trigger."),
    ("recurring_journals", "generate_one"): ("derived", "Records that a template was run; the entry it posted is audited by the ledger's own trigger."),
    ("recurring_journals", "run_due"): ("derived", "Records which templates ran and moves their next date; the entries posted are audited by the ledger's own trigger."),
    ("relationships", "detect_cross_client_matches"): ("derived", "The matches are found by the product from client records; each is reviewed by a person through its own route."),
    ("service_catalogue", "record_service_used"): ("derived", "Counts a use of a catalogue item; nobody states the count."),
    # ── the wider walk of 28-11-2026 (repositories, and calls on an object built from a class): 42 more, each read ──
    ("ai_insights", "generate_insights"): ("derived", "The insights are computed by the product from the client's records; a person acknowledging or dismissing one is recorded by its own route."),
    ("banking", "create_bank_account"): ("lines", "journal_lines are the lines of the opening-balance entry, whose header carries the trigger and the edit log; the bank account's own row carries the trigger."),
    ("banking", "create_reconciliation"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("banking", "reconcile_items"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("banking", "unreconcile_items"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("banking", "update_bank_account"): ("lines", "journal_lines are the lines of the opening-balance entry, whose header carries the trigger and the edit log; the bank account's own row carries the trigger."),
    ("billing", "flag_overdue_for_followup"): ("derived", "The follow-up lines are written by the product for every fee invoice that is overdue; the person chose only to run it, and nothing is sent."),
    ("fixed_assets", "create_asset"): ("lines", "journal_lines are the lines of a ledger entry whose header carries the trigger and the edit log; the other table without a trigger is the client's activity timeline, the product's own line about the act."),
    ("fixed_assets", "dispose_asset"): ("lines", "journal_lines are the lines of a ledger entry whose header carries the trigger and the edit log; the other table without a trigger is the client's activity timeline, the product's own line about the act."),
    ("fixed_assets", "post_depreciation"): ("lines", "journal_lines are the lines of a ledger entry whose header carries the trigger and the edit log; the other table without a trigger is the client's activity timeline, the product's own line about the act."),
    ("fixed_assets", "run_depreciation"): ("lines", "journal_lines are the lines of a ledger entry whose header carries the trigger and the edit log; the other table without a trigger is the client's activity timeline, the product's own line about the act."),
    ("identity", "record_login_event"): ("own_log", "login_events and login_sessions ARE the sign-in log, each row the signed-in person's own; the notification is the product's notice of a new device."),
    ("identity", "session_seen"): ("own_log", "login_sessions IS the sign-in log, the row the signed-in person's own; the notification is the product's notice of a new device."),
    ("knowledge", "archive_instruction"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("knowledge", "create_instruction"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("knowledge", "update_instruction"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "create_onboarding"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "create_proposal"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "create_renewal"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "update_onboarding_status"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "update_onboarding_task"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "update_proposal_status"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("lifecycle", "update_renewal_status"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("notifications", "archive_one"): ("personal", "The signed-in person putting one of their own notifications away."),
    ("notifications", "read_all"): ("personal", "The signed-in person marking their own notifications as read."),
    ("notifications", "read_one"): ("personal", "The signed-in person marking one of their own notifications as read."),
    ("payroll", "delete_employee"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("payroll", "import_employees"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("payroll", "put_attendance"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("payroll", "upsert_declaration"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("relationships", "add_entity_role"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("relationships", "create_entity"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("relationships", "create_relationship"): ("own_log", "The only table without a trigger it writes is the client's activity timeline, a line the product adds about the act; the record the act changed carries the trigger, which records who wrote."),
    ("signup", "request_link"): ("own_log", "A public request with no signed-in person and no firm yet: the sign-up link row is the record of who asked (the address) and when."),
    ("task_extras", "add_dependency"): ("own_log", "The task's own timeline row names who added the dependency and which one (actor_id, new_value); removing one is recorded by the audit log."),
    ("task_extras", "add_tag"): ("own_log", "The task's own timeline row names who added the tag; the tag row itself carries the trigger."),
    ("task_recurring", "generate_tasks"): ("derived", "The notifications and the task timeline lines are written by the product about the tasks it generated from the saved schedules; the tasks carry the trigger."),
    ("task_templates", "instantiate_template"): ("derived", "The notifications, the task timeline lines and the mail log are written by the product about the tasks it made from the template; the tasks carry the trigger."),
    ("tasks", "trigger_escalations"): ("derived", "The escalation rows, notifications, task timeline lines and the mail log are written by the product for the tasks that are overdue; nobody states them."),
    ("tasks", "trigger_recurring_generation"): ("derived", "The notifications and the task timeline lines are written by the product about the tasks it generated from the saved schedules; the tasks carry the trigger."),
    ("timeline", "write_timeline_event"): ("own_log", "The event row IS the record: the server sets its actor to the signed-in person and its firm from the caller."),
    # ── the last part (28-11-2026): a function handed to the thread pool is followed, and this is the one route that flagged ──
    ("email_webhooks", "resend_webhook"): ("mail", "The mail provider's own signed report of what became of a mail the product sent (delivered, bounced, complained): it moves the delivery row of that invoice or statement mail, and no person is in the request to name."),
}


#: A write whose TABLE is a variable of the function, which the walk cannot read: {(module, function): what bounds the table}. The tree has two; a
#: third (or one that stops being one) fails `test_a_write_through_a_variable_table_is_on_the_list`, so the blind spot is counted and not silent.
WRITES_THROUGH_A_VARIABLE: dict[tuple[str, str], str] = {
    ("domain.tally.migration_service", "rollback_migration"): "deletes only from `_ROLLBACK_TABLES`, customers and vendors, which carry the audit trigger.",
    ("services.numbering", "insert_with_number"): "inserts into the table its caller names; no product code calls it today (only tests do), so nothing reaches it from a route.",
}


def _variable_table_writers(sources: dict[str, str]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for module, text in sources.items():
        tree = ast.parse(text)
        constants = {tg.id for st in tree.body if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str)
                     for tg in st.targets if isinstance(tg, ast.Name)}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for c in ast.walk(fn):
                if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)):
                    continue
                ops: list[str] = []
                cur: ast.AST = c
                while True:
                    if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                        ops.append(cur.func.attr)
                        if cur.func.attr in ("table", "from_") and cur.args:
                            arg = cur.args[0]
                            named_by_a_variable = (isinstance(arg, ast.Name) and arg.id not in constants) or not isinstance(arg, (ast.Name, ast.Constant))
                            if named_by_a_variable and set(ops) & WRITE_OPS:
                                found.add((module, fn.name))
                            break
                        cur = cur.func.value
                    elif isinstance(cur, ast.Attribute):
                        cur = cur.value
                    else:
                        break
    return found


@pytest.fixture(scope="module")
def walk() -> Walk:
    return Walk(_sources())


def test_the_walk_reads_enough_to_mean_something(walk):
    """A walk that found a handful of routes would pass anything. These floors were measured on 27-11-2026 (689 write routes, 336 of them
    reaching an audit-less table and an audit call, 121 reaching one with none) and are well under them. The wider walk of 28-11-2026 reads
    the repositories too: it must find them, and must reach a write through one of their objects."""
    assert sum(1 for module in walk.modules if module.startswith("repositories.")) >= 20
    assert any(walk.instances.get(module) for module in walk.modules if module.startswith("repositories.")), "no repository builds an object the walk can follow"
    routes = walk.write_routes()
    assert len(routes) >= 600, len(routes)
    tables = audit_less_tables()
    reaching = [f for f, _ in routes if walk.reach(f)[0] & tables]
    assert len(reaching) >= 300, len(reaching)


def test_every_route_that_writes_a_table_with_no_trigger_audits_or_is_exempt(walk):
    flagged = walk.unaudited(audit_less_tables())
    unexplained = {k: v for k, v in flagged.items() if k not in EXEMPT}
    assert not unexplained, (
        "These routes can write a table the audit trigger does not cover and reach no audit call. Record who wrote with "
        "`audit_service.log_event(firm_id, entity_type, entity_id, action, actor_id=<the person's AUTH id>, new_data=...)`, or, if the rows are not a "
        "person's statement, add the route to EXEMPT with its reason:\n"
        + "\n".join(f"  {m}.{fn}: {', '.join(t)}" for (m, fn), t in sorted(unexplained.items())))


def test_an_exemption_that_no_longer_applies_is_taken_off(walk):
    flagged = walk.unaudited(audit_less_tables())
    stale = sorted(f"{m}.{fn}" for (m, fn) in EXEMPT if (m, fn) not in flagged)
    assert not stale, f"these routes are on EXEMPT and are no longer unaudited writers of a table with no trigger (they audit now, or write none): {stale}"


def test_every_exemption_names_a_reason_it_can_state():
    for key, (reason, why) in EXEMPT.items():
        assert reason in REASONS, f"{key}: '{reason}' is not one of {sorted(REASONS)}"
        assert len(why.split()) >= 4, f"{key}: the reason is not said in words"


# ── the rule can fail ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _case(router: str, service: str = "") -> Walk:
    sources = {"routers.r": router}
    if service:
        sources["services.s"] = service
    return Walk(sources)


T = frozenset({"some_table"})


def test_a_route_that_writes_such_a_table_directly_and_says_nothing_is_flagged():
    w = _case("@router.post('/x')\ndef f(db):\n    db.table('some_table').insert({}).execute()\n")
    assert w.unaudited(T) == {("r", "f"): ("some_table",)}


def test_the_same_route_with_an_audit_call_is_not_flagged():
    w = _case("from services.audit_service import log_event\n@router.post('/x')\ndef f(db, u):\n    db.table('some_table').insert({}).execute()\n    log_event('f', 'x', '1', 'create', actor_id=u['auth_user_id'])\n")
    assert w.unaudited(T) == {}


def test_a_write_reached_through_an_imported_service_is_followed():
    router = "from services import s\n@router.post('/x')\ndef f(db):\n    s.save(db)\n"
    service = "def save(db):\n    db.table('some_table').update({}).eq('id', 1).execute()\n"
    assert _case(router, service).unaudited(T) == {("r", "f"): ("some_table",)}
    audited = "from services.audit_service import log_event\ndef save(db):\n    db.table('some_table').update({}).eq('id', 1).execute()\n    log_event('f', 'x', '1', 'update')\n"
    assert _case(router, audited).unaudited(T) == {}


def test_a_read_of_such_a_table_is_not_a_write():
    w = _case("@router.post('/x')\ndef f(db):\n    return db.table('some_table').select('*').execute()\n")
    assert w.unaudited(T) == {}


def test_writing_the_audit_table_itself_counts_as_recording():
    w = _case("@router.post('/x')\ndef f(db):\n    db.table('some_table').insert({}).execute()\n    db.table('audit_log').insert({}).execute()\n")
    assert w.unaudited(T) == {}


def test_a_table_that_carries_the_trigger_is_not_this_rules_concern():
    w = _case("@router.post('/x')\ndef f(db):\n    db.table('journal_entries').insert({}).execute()\n")
    assert w.unaudited(T) == {}


REPOSITORY = "class ThingRepo:\n    def create(self, row):\n        return db.table('some_table').insert(row).execute()\nthing_repo = ThingRepo()\n"


def test_a_write_made_through_an_object_another_module_built_from_a_class_is_followed():
    """`from repositories.x import thing_repo` then `thing_repo.create(...)`: the repository instance the walk could not read before."""
    w = Walk({"routers.r": "from repositories.x import thing_repo\n@router.post('/a')\ndef make(body):\n    return thing_repo.create(body)\n",
              "repositories.x": REPOSITORY})
    assert w.unaudited(T) == {("r", "make"): ("some_table",)}


def test_a_write_made_through_an_object_the_function_builds_itself_is_followed():
    w = Walk({"routers.r": "from repositories.x import ThingRepo\n@router.post('/a')\ndef make(body):\n    repo = ThingRepo()\n    return repo.create(body)\n",
              "repositories.x": REPOSITORY})
    assert w.unaudited(T) == {("r", "make"): ("some_table",)}


def test_a_write_made_through_a_class_named_through_its_module_is_followed():
    w = Walk({"routers.r": "from repositories import x\n@router.post('/a')\ndef make(body):\n    repo = x.ThingRepo()\n    return repo.create(body)\n",
              "repositories.x": REPOSITORY})
    assert w.unaudited(T) == {("r", "make"): ("some_table",)}


def test_an_audit_call_inside_the_method_counts_and_a_method_of_another_name_is_not_followed():
    audited_repo = ("from services.audit_service import log_event\nclass ThingRepo:\n    def create(self, row):\n        log_event('f', 'thing', '1', 'create')\n"
                    "        return db.table('some_table').insert(row).execute()\n    def other(self, row):\n        return db.table('some_table').insert(row).execute()\n"
                    "thing_repo = ThingRepo()\n")
    router = "from repositories.x import thing_repo\n@router.post('/a')\ndef make(body):\n    return thing_repo.create(body)\n"
    assert Walk({"routers.r": router, "repositories.x": audited_repo, "services.audit_service": "def log_event(*a, **k):\n    pass\n"}).unaudited(T) == {}
    reads_only = "class ThingRepo:\n    def find(self):\n        return db.table('some_table').select('*').execute()\n    def create(self, row):\n        return db.table('some_table').insert(row).execute()\nthing_repo = ThingRepo()\n"
    reader = "from repositories.x import thing_repo\n@router.post('/a')\ndef look(body):\n    return thing_repo.find()\n"
    assert Walk({"routers.r": reader, "repositories.x": reads_only}).unaudited(T) == {}


def test_a_table_named_through_a_module_constant_is_followed():
    w = _case("LOANS = 'some_table'\n@router.post('/x')\ndef f(db):\n    db.table(LOANS).insert({}).execute()\n")
    assert w.unaudited(T) == {("r", "f"): ("some_table",)}


def test_a_log_event_of_another_module_is_not_the_audit_log():
    # the task timeline has a `log_event` too; it writes `task_timeline`, so a route that only calls it has recorded nothing in the audit log
    w = _case("from repositories.task_extras_repo import log_event\n@router.post('/x')\ndef f(db):\n    db.table('some_table').insert({}).execute()\n    log_event('f', 'x')\n")
    assert w.unaudited(T) == {("r", "f"): ("some_table",)}


def test_the_marker_counts_as_recording():
    w = _case("from services.audit_service import audited\n@router.post('/x')\n@audited('widget', 'create')\ndef f(db, current_user):\n    db.table('some_table').insert({}).execute()\n")
    assert w.unaudited(T) == {}


def test_a_chain_split_over_two_statements_is_followed():
    w = _case("@router.post('/x')\ndef f(db):\n    t = db.table('some_table')\n    t.insert({}).execute()\n")
    assert w.unaudited(T) == {("r", "f"): ("some_table",)}


def test_a_name_rebound_on_the_way_is_still_that_table():
    w = _case("@router.post('/x')\ndef f(db):\n    q = db.table('some_table').select('*')\n    q = q.eq('id', 1)\n    q.update({}).execute()\n")
    assert w.unaudited(T) == {("r", "f"): ("some_table",)}


def test_a_name_bound_to_something_that_is_not_a_table_writes_nothing():
    w = _case("@router.post('/x')\ndef f(db, rows):\n    t = rows.copy()\n    t.update({})\n    db.table('other_table').select('*').execute()\n")
    assert w.unaudited(T) == {}


def test_a_chain_split_over_statements_that_audits_is_not_flagged():
    w = _case("from services.audit_service import log_event\n@router.post('/x')\ndef f(db, u):\n    t = db.table('some_table')\n    t.update({}).execute()\n    log_event('f', 'x', '1', 'update', actor_id=u['auth_user_id'])\n")
    assert w.unaudited(T) == {}


def test_a_write_through_a_variable_table_is_on_the_list(walk):
    found = _variable_table_writers(_sources())
    assert found == set(WRITES_THROUGH_A_VARIABLE), (
        "A write whose table is a variable of the function is invisible to the walk by name. The tree has the two on WRITES_THROUGH_A_VARIABLE; "
        f"new: {sorted(found - set(WRITES_THROUGH_A_VARIABLE))}, no longer such a write: {sorted(set(WRITES_THROUGH_A_VARIABLE) - found)}. "
        "Either write the table as a literal or a module constant, or add the function with what bounds the table.")


def test_the_variable_table_finder_is_not_blind():
    one = {"services.x": "def f(db, table):\n    db.table(table).insert({}).execute()\n"}
    assert _variable_table_writers(one) == {("services.x", "f")}
    literal = {"services.x": "T = 'a'\ndef f(db):\n    db.table(T).insert({}).execute()\n    db.table('b').delete().execute()\n"}
    assert _variable_table_writers(literal) == set()
    read = {"services.x": "def f(db, table):\n    db.table(table).select('*').execute()\n"}
    assert _variable_table_writers(read) == set()



# ── the last four shapes (28-11-2026): each is followed, and each can fail ─────────────────────────────────────────────────────────────────

SAVES = "def save(db):\n    db.table('some_table').insert({}).execute()\n"


def test_a_relative_import_is_read_against_the_importers_own_package():
    """`from .store import save` inside `domain.gst.build` is `domain.gst.store.save`; before, the dot was dropped and nothing was followed."""
    router = "from domain.gst import build\n@router.post('/x')\ndef f(db):\n    build.run(db)\n"
    sources = {"routers.r": router, "domain.gst.build": "from .store import save\ndef run(db):\n    save(db)\n", "domain.gst.store": SAVES}
    assert Walk(sources).unaudited(T) == {("r", "f"): ("some_table",)}
    module_form = {"routers.r": router, "domain.gst.build": "from . import store\ndef run(db):\n    store.save(db)\n", "domain.gst.store": SAVES}
    assert Walk(module_form).unaudited(T) == {("r", "f"): ("some_table",)}
    two_up = {"routers.r": router, "domain.gst.build": "from ..shared import save\ndef run(db):\n    save(db)\n", "domain.shared": SAVES}
    assert Walk(two_up).unaudited(T) == {("r", "f"): ("some_table",)}


def test_a_function_handed_to_another_to_be_called_is_followed():
    """The mail webhook's shape: `await run_in_threadpool(service.process, ...)` calls `process` without the source ever writing `process(`."""
    router = "from services import s\n@router.post('/x')\nasync def f(db):\n    return await run_in_threadpool(s.save, db)\n"
    assert _case(router, SAVES).unaudited(T) == {("r", "f"): ("some_table",)}
    by_name = "from services.s import save\n@router.post('/x')\ndef f(db, tasks):\n    tasks.add_task(save, db)\n"
    assert _case(by_name, SAVES).unaudited(T) == {("r", "f"): ("some_table",)}
    keyword = "from services.s import save\n@router.post('/x')\ndef f(db):\n    retry(attempts=3, call=save)\n"
    assert _case(keyword, SAVES).unaudited(T) == {("r", "f"): ("some_table",)}


def test_a_value_handed_over_is_not_followed_by_its_bare_name():
    """`log(row.save)` hands over an attribute of something the walk cannot place. A function of this module that happens to be called `save`
    is NOT that, and following it would invent a write (or, worse, an audit call) the route does not make."""
    router = ("def save(db):\n    db.table('some_table').insert({}).execute()\n"
              "@router.post('/x')\ndef f(db, row):\n    note(row.save)\n")
    assert _case(router).unaudited(T) == {}
    hides = ("from services.audit_service import log_event\n@router.post('/x')\ndef f(db, row):\n    db.table('some_table').insert({}).execute()\n    note(row.log_event)\n")
    assert _case(hides).unaudited(T) == {("r", "f"): ("some_table",)}


def test_an_audit_call_handed_to_another_to_be_called_counts():
    router = ("from services import audit_service\n@router.post('/x')\ndef f(db, tasks):\n    db.table('some_table').insert({}).execute()\n"
              "    tasks.add_task(audit_service.log_event, 'f', 'x', '1', 'create')\n")
    assert _case(router).unaudited(T) == {}


FACTORY = REPOSITORY + "def get_repo() -> ThingRepo:\n    return thing_repo\ndef build_repo():\n    return ThingRepo()\ndef opaque():\n    return _made\n"


def test_an_object_kept_from_a_functions_return_is_followed():
    for factory in ("get_repo", "build_repo"):      # the annotation says the class, or the `return` builds it
        router = f"from repositories.x import {factory}\n@router.post('/a')\ndef make(body):\n    repo = {factory}()\n    return repo.create(body)\n"
        assert Walk({"routers.r": router, "repositories.x": FACTORY}).unaudited(T) == {("r", "make"): ("some_table",)}, factory
    # a function that says nothing about what it hands back is one of the things the walk cannot read, and it invents nothing for it
    router = "from repositories.x import opaque\n@router.post('/a')\ndef make(body):\n    repo = opaque()\n    return repo.create(body)\n"
    assert Walk({"routers.r": router, "repositories.x": FACTORY}).unaudited(T) == {}


def test_an_object_a_module_keeps_from_a_functions_return_and_another_imports_is_followed():
    holder = "from repositories.x import get_repo\nrepo = get_repo()\n"
    router = "from services.s import repo\n@router.post('/a')\ndef make(body):\n    return repo.create(body)\n"
    assert Walk({"routers.r": router, "services.s": holder, "repositories.x": FACTORY}).unaudited(T) == {("r", "make"): ("some_table",)}


def test_an_object_handed_in_as_an_argument_is_read_by_the_class_its_parameter_names():
    service = "from repositories.x import ThingRepo\ndef save(repo: ThingRepo, row):\n    return repo.create(row)\n"
    router = "from services import s\n@router.post('/a')\ndef make(body, repo):\n    return s.save(repo, body)\n"
    assert Walk({"routers.r": router, "services.s": service, "repositories.x": REPOSITORY}).unaudited(T) == {("r", "make"): ("some_table",)}
    optional = service.replace("repo: ThingRepo", "repo: 'ThingRepo | None'")
    assert Walk({"routers.r": router, "services.s": optional, "repositories.x": REPOSITORY}).unaudited(T) == {("r", "make"): ("some_table",)}
    unannotated = service.replace("repo: ThingRepo", "repo")
    assert Walk({"routers.r": router, "services.s": unannotated, "repositories.x": REPOSITORY}).unaudited(T) == {}


TWO_CLASSES = ("class Reader:\n    def run(self, row):\n        return db.table('some_table').select('*').execute()\n"
               "class Writer:\n    def run(self, row):\n        return db.table('some_table').insert(row).execute()\n"
               "reader = Reader()\nwriter = Writer()\n")


def test_two_classes_in_one_module_with_a_method_of_the_same_name_are_told_apart():
    """Before, a method was found by its name in the class's module, so `reader.run()` was read as `Writer.run` too and a route that only read was flagged."""
    reads = "from repositories.x import reader\n@router.post('/a')\ndef look(body):\n    return reader.run(body)\n"
    assert Walk({"routers.r": reads, "repositories.x": TWO_CLASSES}).unaudited(T) == {}
    writes = "from repositories.x import writer\n@router.post('/a')\ndef make(body):\n    return writer.run(body)\n"
    assert Walk({"routers.r": writes, "repositories.x": TWO_CLASSES}).unaudited(T) == {("r", "make"): ("some_table",)}


def test_a_method_the_class_does_not_define_is_found_in_the_base_it_names_and_self_is_the_objects_own():
    base = "class Base:\n    def create(self, row):\n        return self._store(row)\n    def _store(self, row):\n        return db.table('some_table').insert(row).execute()\n"
    child = "from repositories.base import Base\nclass ThingRepo(Base):\n    pass\nthing_repo = ThingRepo()\n"
    router = "from repositories.x import thing_repo\n@router.post('/a')\ndef make(body):\n    return thing_repo.create(body)\n"
    assert Walk({"routers.r": router, "repositories.x": child, "repositories.base": base}).unaudited(T) == {("r", "make"): ("some_table",)}
    # a child that overrides the method is read as its own, not as the base's
    overrides = "from repositories.base import Base\nclass ThingRepo(Base):\n    def create(self, row):\n        return None\nthing_repo = ThingRepo()\n"
    assert Walk({"routers.r": router, "repositories.x": overrides, "repositories.base": base}).unaudited(T) == {}
