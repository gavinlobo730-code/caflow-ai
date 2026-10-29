"""A write of a table the signed-in role cannot write is made on a client that can (POST-A-354, from POST-A-323).

THE DEFECT
    Production's signed-in database role holds no INSERT, UPDATE or DELETE on 157 tables (read on 28-10-2026). A write to one of them
    made on the caller's own session, which is the signed-in role whenever `USE_USER_JWT` is on (it has been in production since
    15-08-2026), is refused with 42501, and every test double accepts any caller. POST-A-323 found twelve tables written that way
    (GSTR-4 annual, GSTR-9C, the e-commerce operator, `rcm_documents`, the stock count), 90 of the 157 are empty in production, and
    the cases that do not announce themselves are the ones nobody has used yet. The twelve are held by their own file; this is the
    rule over the rest.

WHAT IS HELD
    * (source) every write of a table on `fixtures/tables_the_signed_in_role_cannot_write.txt` is classified by where its client
      comes from. A client made by `privileged_for`, `service_db`, `get_service_supabase` and their kin is PRIVILEGED; one made by
      `get_supabase`, `request_db` and their kin is the REQUEST's; a name bound in the function is judged by what it was bound to
      (a helper such as `_lock_table_db(db)` by what that helper returns); a PARAMETER is judged by what every caller in the source
      passes for it, followed up to five calls up, through a resolved call only. A write on the request's client fails, and so does
      one whose client cannot be traced, unless it is on the reviewed list below with the reason it is safe; the list only shrinks.
    * the detector is shown the shapes it must read: a request-bound variable, a parameter whose caller passes the request's client,
      one whose callers all pass the privileged client, a helper that rebinds the client, and a write in a function nothing calls.
    * (real Postgres, in the file of the same name ending `_pg`) every table on the list that exists in the migration-built database
      is one the signed-in roles cannot write.

WHAT IT CANNOT SEE
    A client reached through an attribute (`self._db`), a dictionary or a callback; a write made by SQL text (the table-use scanner
    reports those and the rule fails them); and `scripts/`, which run with a service key and are one-off by definition.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from tests._call_graph import CallGraph, called_name, chain_of
from tests._table_uses import sources, uses

API = Path(__file__).resolve().parent.parent
LIST_FILE = API / "tests" / "fixtures" / "tables_the_signed_in_role_cannot_write.txt"
CLOSED = [ln.strip() for ln in LIST_FILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]

#: Tables whose writers have moved to the privileged client AHEAD of the migration that takes the signed-in write away. The Python ships
#: first and the grant follows at least an hour later, because the old API against a revoked grant fails soft and wrong (the entry on
#: POST-A-319 in docs/design-record/tenancy-and-security.md). A table is held to this rule from the day its writers move, and moves
#: from this file to the closed list in the migration that revokes it; the file is empty between such changes.
IN_FLIGHT_FILE = API / "tests" / "fixtures" / "tables_about_to_be_closed.txt"
ABOUT_TO_BE_CLOSED = ([ln.strip() for ln in IN_FLIGHT_FILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
                      if IN_FLIGHT_FILE.exists() else [])

#: Names whose call hands back the privileged client, and the request's.
PRIVILEGED = {"privileged_for", "service_db", "service_db_or_none", "service_db_or_503", "get_service_supabase", "_service_client",
              "fx_writer", "acting_as_request_person"}
REQUEST = {"get_supabase", "request_db", "request_db_or_none"}
DEPTH = 5

#: (file, function): why the write is safe although the rule cannot trace its client. Shrink-only.
REVIEWED: dict[tuple[str, str], str] = {
    ("services/document_header_writer.py", "<module>"):
        "the six UPDATE statements are held in lambdas at module level, one literal chain per table so the firm-scope reader can read each; "
        "the only caller is `update_header`, which hands them the client `header_writer` returns (the privileged one wherever there is one) "
        "and the document, firm and client it was asked to name, and refuses a call that names none of the three.",
    ("services/phase2_journal_service.py", "_create_journal"):
        "the two inserts are the branch for a database double that has no `rpc()`; the real client always has one, so production posts "
        "through the privileged ledger door (`ledger_rpc`, POST-A-317) a few lines above and never reaches them.",
}


def _worst(kinds: list):
    if "REQUEST" in kinds:
        return "REQUEST"
    unknown = [k for k in kinds if isinstance(k, tuple)]
    return unknown[0] if unknown else "PRIVILEGED"


def _passes_through(e, ident: str) -> bool:
    """Does the value BE the name (`db`, `db or _db()`, `a if x else db`), as opposed to merely taking it as an argument?"""
    if isinstance(e, ast.Name):
        return e.id == ident
    if isinstance(e, ast.BoolOp):
        return any(_passes_through(v, ident) for v in e.values)
    if isinstance(e, ast.IfExp):
        return _passes_through(e.body, ident) or _passes_through(e.orelse, ident)
    return False


class _Classifier:
    def __init__(self, graph: CallGraph):
        self.g = graph
        self._returns: dict = {}
        self._params: dict = {}
        self._visiting: set = set()
        self._module_names = {mod: self._module_level(mod) for mod in graph.mods}

    # names bound at module level (`_db = db_provider.service_db_or_none`)
    def _module_level(self, mod: str) -> dict:
        out: dict = {}
        for n in self.g.mods[mod].body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                v = n.value
                name = v.attr if isinstance(v, ast.Attribute) else getattr(v, "id", None)
                if name in PRIVILEGED:
                    out[n.targets[0].id] = "PRIVILEGED"
                elif name in REQUEST:
                    out[n.targets[0].id] = "REQUEST"
        return out

    def _call_kind(self, call: ast.Call, key, depth: int):
        name = called_name(call)
        if name in PRIVILEGED:
            return "PRIVILEGED"
        if name in REQUEST:
            return "REQUEST"
        mod = key[0]
        if name in self._module_names.get(mod, {}):
            return self._module_names[mod][name]
        targets = self.g.resolve(call, mod, self.g.imports_in(key), key[1].split(".")[0] if "." in key[1] else None)
        if targets and depth > 0:
            return _worst([self.returns(t, depth - 1) for t in targets])
        return ("UNKNOWN", f"call {name}")

    def returns(self, key, depth: int):
        if (key, depth) in self._returns:
            return self._returns[(key, depth)]
        self._returns[(key, depth)] = "PRIVILEGED"                  # a cycle is not a reason to fail
        fn = self.g.funcs[key]
        parents = {c: p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}

        def _no_client_guard(r) -> bool:
            """`if not db: return db` hands back a falsy value, which is no client at all."""
            p = parents.get(r)
            return (isinstance(r.value, ast.Name) and isinstance(p, ast.If) and isinstance(p.test, ast.UnaryOp)
                    and isinstance(p.test.op, ast.Not) and isinstance(p.test.operand, ast.Name) and p.test.operand.id == r.value.id)

        rets = [r.value for r in ast.walk(fn) if isinstance(r, ast.Return) and r.value is not None and not _no_client_guard(r)]
        result = _worst([self.expr(e, key, depth) for e in rets]) if rets else ("UNKNOWN", "returns nothing")
        self._returns[(key, depth)] = result
        return result

    def expr(self, e, key, depth: int):
        if isinstance(e, ast.Call):
            return self._call_kind(e, key, depth)
        if isinstance(e, ast.BoolOp):
            # `service_db_or_none() or request_db`: the first operand is None only where no database is configured (mock mode, where
            # there are no grants to be refused by), so the fallback to the caller's own client never reaches a real database
            if isinstance(e.op, ast.Or) and isinstance(e.values[0], ast.Call) and called_name(e.values[0]) in PRIVILEGED:
                return "PRIVILEGED"
            return _worst([self.expr(v, key, depth) for v in e.values])
        if isinstance(e, ast.IfExp):
            return _worst([self.expr(e.body, key, depth), self.expr(e.orelse, key, depth)])
        if isinstance(e, ast.Name):
            return self.name(e.id, key, depth)
        if isinstance(e, ast.Constant) and e.value is None:
            return "PRIVILEGED"                                     # `db=None` is no client at all
        return ("UNKNOWN", ast.unparse(e)[:40])

    def name(self, ident: str, key, depth: int):
        fn = self.g.funcs[key]
        if (key, ident) in self._visiting:
            return "PRIVILEGED"                                     # `db = db or _db()`: the self-reference adds nothing
        bound = [n.value for n in ast.walk(fn)
                 if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == ident]
        is_parameter = ident in CallGraph.parameters(fn)
        if bound:
            self._visiting.add((key, ident))
            try:
                kinds = [self.expr(v, key, depth) for v in bound]
                # a rebinding that reads the parameter back (`db = db or _db()`) is judged by the parameter as well
                if is_parameter and any(_passes_through(v, ident) for v in bound):
                    kinds.append(self.parameter(key, ident, depth))
            finally:
                self._visiting.discard((key, ident))
            return _worst(kinds)
        if ident in self._module_names.get(key[0], {}):
            return self._module_names[key[0]][ident]
        if is_parameter:
            return self.parameter(key, ident, depth)
        return ("UNKNOWN", f"name {ident}")

    def parameter(self, key, ident: str, depth: int):
        if depth <= 0:
            return ("UNKNOWN", f"{ident} passed down too far")
        memo = (key, ident, depth)
        if memo in self._params:
            return self._params[memo]
        self._params[memo] = "PRIVILEGED"
        kinds, calls = [], 0
        for caller, call in self.g.callers(key):
            if caller == key:
                continue
            calls += 1
            arg = self.g.argument_for(call, key, ident)
            if arg is None:
                continue                                            # the caller leaves the default
            kinds.append(self.expr(arg, caller, depth - 1))
        if kinds:
            result = _worst(kinds)
        elif calls:
            result = "PRIVILEGED"                                   # every caller leaves it to the function's own default or fallback
        else:
            result = ("UNKNOWN", "no caller found")
        self._params[memo] = result
        return result


def _enclosing(graph: CallGraph, mod: str, line: int):
    best = None
    for (m, name), fn in graph.funcs.items():
        if m == mod and fn.lineno <= line <= (fn.end_lineno or 10**9):
            if best is None or fn.lineno >= graph.funcs[best].lineno:
                best = (m, name)
    return best


def _handle_receiver(graph: CallGraph, mod: str, line: int, table: str):
    """For `base = privileged_for(db).table("t")` kept in a variable: the expression the handle was made from, or None."""
    key = _enclosing(graph, mod, line)
    if key is None:
        return None
    for node in ast.walk(graph.funcs[key]):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for method, link in chain_of(node.value):
                if method in {"table", "from_"} and link.args and isinstance(link.args[0], ast.Constant) and link.args[0].value == table:
                    return link.func.value
    return None


def verdicts(root: Path, closed: list[str], source_files=None):
    """{(file, function): [(kind, table, line)]} for every write of a closed table."""
    graph = CallGraph(root)
    classify = _Classifier(graph)
    out: dict = {}
    files = source_files if source_files is not None else list(sources())
    for rel, text in files:
        if rel.startswith("scripts/"):
            continue
        mod = rel[:-3].replace("/", ".")
        for table in closed:
            if table not in text:
                continue
            for kind, fn_name, line, receiver, _verbs in uses(text, table):
                if kind == "unchained":
                    handle = _handle_receiver(graph, mod, line, table)
                    if handle is not None:
                        key = _enclosing(graph, mod, line)
                        out.setdefault((rel, fn_name), []).append((classify.expr(handle, key, DEPTH), table, line))
                        continue
                if kind in {"unchained", "raw_write"}:
                    out.setdefault((rel, fn_name), []).append((("UNKNOWN", f"a {kind} the rule cannot read"), table, line))
                    continue
                if kind != "write":
                    continue
                key = _enclosing(graph, mod, line)
                if key is None:
                    out.setdefault((rel, fn_name), []).append((("UNKNOWN", "a write outside any function"), table, line))
                    continue
                out.setdefault((rel, fn_name), []).append((classify.expr(receiver, key, DEPTH), table, line))
    return out


def _bad(found: dict) -> dict:
    return {k: [(kind, t, ln) for kind, t, ln in v if kind != "PRIVILEGED"] for k, v in found.items()
            if any(kind != "PRIVILEGED" for kind, _t, _ln in v)}


@pytest.fixture(scope="module")
def found():
    return verdicts(API, CLOSED + ABOUT_TO_BE_CLOSED)


def test_every_write_of_a_closed_table_is_on_a_client_that_can_write_it_or_is_reviewed(found):
    bad = _bad(found)
    new = {k: v for k, v in bad.items() if k not in REVIEWED}
    assert not new, ("these functions write a table the signed-in role cannot write on the caller's own session, or on a client the rule "
                     "cannot trace. Make the write with `privileged_for(db)` (the route's own checks stay, and the statement must name the "
                     "firm and the client), or add the function to REVIEWED with the reason it is safe:\n  "
                     + "\n  ".join(f"{k}: {[(str(kind), t) for kind, t, _ in v]}" for k, v in sorted(new.items())))


def test_a_reviewed_function_still_fails_the_rule_and_still_gives_its_reason(found):
    bad = _bad(found)
    for key, reason in REVIEWED.items():
        assert key in bad, f"{key} now passes (or is gone): delete it from REVIEWED, the list only shrinks"
        assert len(reason) > 60, f"{key} needs a reason"


def test_the_rule_reads_enough_to_mean_something(found):
    writes = sum(len(v) for v in found.values())
    assert writes >= 250, f"only {writes} writes of closed tables found; the scan has gone blind"
    assert sum(1 for v in found.values() for kind, _t, _ln in v if kind == "PRIVILEGED") >= 200
    assert len(CLOSED) >= 150 and "journal_entries" in CLOSED and "gstr9c_reconciliations" in CLOSED


# ── the rule against code written for the purpose ──────────────────────────────────────────────────────────────────────────
def _verdict(tmp_path, files: dict[str, str], table="things") -> dict:
    sources_: list[tuple[str, str]] = []
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = textwrap.dedent(body)
        path.write_text(text)
        sources_.append((rel, text))
    return _bad(verdicts(tmp_path, [table], sources_))


def test_a_variable_bound_to_the_requests_client_is_flagged(tmp_path):
    bad = _verdict(tmp_path, {"services/a.py": '''
        from core.supabase_client import get_supabase
        def save(row):
            db = get_supabase()
            db.table("things").insert(row).execute()
    '''})
    assert [kind for v in bad.values() for kind, _t, _l in v] == ["REQUEST"]


def test_a_variable_bound_to_a_privileged_client_is_not(tmp_path):
    assert _verdict(tmp_path, {"services/a.py": '''
        from core import db_provider
        def save(row):
            db = db_provider.service_db()
            db.table("things").insert(row).execute()
    '''}) == {}


def test_a_parameter_whose_caller_passes_the_requests_client_is_flagged(tmp_path):
    bad = _verdict(tmp_path, {
        "services/a.py": '''
            def save(db, row):
                db.table("things").insert(row).execute()
        ''',
        "routers/r.py": '''
            from core.supabase_client import get_supabase
            from services import a
            def route(row):
                db = get_supabase()
                a.save(db, row)
        '''})
    assert [kind for v in bad.values() for kind, _t, _l in v] == ["REQUEST"]


def test_a_parameter_whose_callers_all_pass_the_privileged_client_is_not(tmp_path):
    assert _verdict(tmp_path, {
        "services/a.py": '''
            def save(db, row):
                db.table("things").insert(row).execute()
        ''',
        "routers/r.py": '''
            from core import db_provider
            from services import a
            def first(row):
                a.save(db_provider.service_db(), row)
            def second(row):
                a.save(db=db_provider.service_db_or_none(), row=row)
        '''}) == {}


def test_one_caller_on_the_requests_client_is_enough_to_flag_the_parameter(tmp_path):
    bad = _verdict(tmp_path, {
        "services/a.py": '''
            def save(db, row):
                db.table("things").insert(row).execute()
        ''',
        "routers/r.py": '''
            from core import db_provider
            from services import a
            def first(row):
                a.save(db_provider.service_db(), row)
            def second(row):
                a.save(db_provider.request_db(), row)
        '''})
    assert [kind for v in bad.values() for kind, _t, _l in v] == ["REQUEST"]


def test_a_helper_that_rebinds_the_client_is_judged_by_what_it_returns(tmp_path):
    assert _verdict(tmp_path, {"services/a.py": '''
        from core import db_provider
        def _writer(db):
            return db_provider.service_db()
        def save(db, row):
            db = _writer(db)
            db.table("things").insert(row).execute()
    '''}) == {}
    bad = _verdict(tmp_path, {"services/a.py": '''
        from core import db_provider
        def _writer(db):
            return db_provider.request_db()
        def save(db, row):
            db = _writer(db)
            db.table("things").insert(row).execute()
    '''})
    assert [kind for v in bad.values() for kind, _t, _l in v] == ["REQUEST"]


def test_a_write_in_a_function_nothing_calls_cannot_be_traced_and_is_flagged(tmp_path):
    bad = _verdict(tmp_path, {"services/a.py": '''
        def save(db, row):
            db.table("things").insert(row).execute()
    '''})
    assert [str(kind) for v in bad.values() for kind, _t, _l in v] == [str(("UNKNOWN", "no caller found"))]


def test_privileged_for_at_the_statement_is_privileged_whatever_the_parameter_is(tmp_path):
    assert _verdict(tmp_path, {"services/a.py": '''
        from core.db_provider import privileged_for
        def save(db, row):
            privileged_for(db).table("things").insert(row).execute()
    '''}) == {}


def test_a_table_not_on_the_list_is_not_judged(tmp_path):
    assert _verdict(tmp_path, {"services/a.py": '''
        from core.supabase_client import get_supabase
        def save(row):
            get_supabase().table("other").insert(row).execute()
    '''}, table="things") == {}
