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
    It still does NOT see: a table named in a variable of a function, a chain split over statements (`t = db.table("x"); t.update(...)`), an
    object handed in as an argument or returned by a function (`db_provider.service_db_or_none()` kept in a module variable and called), a
    function passed as a callback, a relative import (63, all in `domain/`), or a write made by the database itself (a trigger or
    `.rpc(...)`). The mail provider's webhook (`email_webhooks.resend_webhook`) is one such: it writes delivery and suppression rows through a
    client it is handed, and there is no person in it to name. A method is found by its NAME in the class's module, so two classes in one
    module with a method of the same name are read as one. A route that reaches an audit call on some path is read as audited for all of
    its writes, which is the cost of not tracing which branch writes what. A call named `log_event` counts only when the module imports it
    from `services.audit_service`. The ledger's own tables carry the trigger, so a journal posted by a route is audited as it always was.

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
        self.calls: list[tuple[str | None, str | None]] = []


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
        self.classes: dict[str, set[str]] = {}
        for module, text in sources.items():
            tree = ast.parse(text)
            imp: dict[str, tuple[str, str | None]] = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and n.module:
                    for a in n.names:
                        imp[a.asname or a.name] = (n.module, a.name)
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        imp[(a.asname or a.name).split(".")[0]] = (a.name, None)
            self.imports[module] = imp
            # `repo = ClientRepository()` at module level, and `Something` defined as a class here: a call on either is a call of a METHOD
            # of this module's or the class's module (POST-A-167, the wider walk).
            self.instances.setdefault(module, {})
            for st in tree.body:
                if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call):
                    made = _class_called(st.value)
                    for tg in st.targets:
                        if made and isinstance(tg, ast.Name):
                            self.instances[module][tg.id] = made
            self.classes.setdefault(module, set()).update(n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
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
                    for c in ast.walk(n):
                        if isinstance(c, ast.Call):
                            fn = c.func
                            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                            owner = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else None
                            if name in AUDIT_CALLS and _is_the_audit_service(imp, owner, name):
                                f.audits = True
                            f.calls.append((owner, name))
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

    def _resolve(self, f: _Fn, owner: str | None, name: str | None) -> list[_Fn]:
        if name is None:
            return []
        imp = self.imports.get(f.module, {})
        found: list[_Fn] = []
        if owner is None:
            found += self.funcs.get((f.module, name), [])
            if name in imp:
                mod, attr = imp[name]
                if attr:
                    found += self.funcs.get((mod, attr), [])
        elif owner in getattr(f, "locals", {}) or owner in self.instances.get(f.module, {}):
            # a call on an object this function, or this module, built from a class: the class's method of that name
            made = getattr(f, "locals", {}).get(owner) or self.instances[f.module][owner]
            where = self._module_of_a_class(f.module, made)
            found += self.funcs.get((where, name), []) if where else self.funcs.get((f.module, name), [])
        elif owner in imp:
            mod, attr = imp[owner]
            for candidate in ((mod + "." + attr) if attr else None, mod if attr is None else None):
                if candidate and candidate in self.modules:
                    found += self.funcs.get((candidate, name), [])
            if attr and mod in self.modules:
                # `from repositories.x import x_repository` (an object the module built) or `import Repo` (a class): its method
                made = self.instances.get(mod, {}).get(attr)
                where = self._module_of_a_class(mod, made) if made else (mod if attr in self.classes.get(mod, ()) else None)
                if where:
                    found += self.funcs.get((where, name), [])
        else:
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
            for owner, name in f.calls:
                stack.extend(self._resolve(f, owner, name))
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
}


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

