"""
The reader behind the firm-scope guard reads what it says it reads (engineering-28).

`test_every_query_on_a_firm_table_carries_its_firm_scope.py` is only as good as
`tests/_firm_scope_scan.py`: a reader that clears too much leaves the guard green over
a missing filter, and one that clears too little buries the real findings in a list
nobody reads. So the reader has its own tests, over synthetic sources, and each kind of
evidence is tested TWICE: that it clears what it should, and that the look-alike it must
not clear is not cleared. Several of the look-alikes are bugs the first version had and
a negative control found:

  * `cache[auth_user_id] = row` verified the KEY (every Name in an assignment target was
    bound, not only the slot being assigned);
  * `row["firm_id"]` stamped onto the next insert counted as a check of the row, which is
    the opposite of one;
  * a comparison made BEFORE the read counted as a comparison of what it returned;
  * a gate whose docstring said `firm_id` was "verified";
  * a helper nothing calls (a dependency the framework calls) was cleared by "its
    callers", of which there are none.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _firm_scope_scan as S  # noqa: E402

TABLES = {"customers", "vendors", "clients"}


def read(source: str, rel: str = "routers/x.py", gates=None, targets=None):
    return S.scan_source(textwrap.dedent(source), rel, TABLES, gates, targets)[0]


def of(chains, function: str, table: str | None = None):
    got = [c for c in chains if c.function == function and (table is None or c.table == table)]
    assert got, f"no chain in {function}: {[(c.function, c.table) for c in chains]}"
    return got


def scoped(chains, function: str, table: str | None = None) -> bool:
    return all(c.scoped_by for c in of(chains, function, table))


# ── a filter ─────────────────────────────────────────────────────────────────

def test_a_firm_filter_scopes_a_chain_however_it_is_spelled():
    chains = read('''
        def a(db, firm_id, i):
            return db.table("customers").select("*").eq("id", i).eq("firm_id", firm_id).execute()
        def b(db, firm_ids, i):
            return db.table("customers").select("*").in_("firm_id", firm_ids).execute()
        def c(db, firm_id):
            return db.table("customers").select("*").match({"firm_id": firm_id}).execute()
        def d(db, firm_id):
            return db.table("customers").select("*").or_(f"firm_id.eq.{firm_id},firm_id.is.null").execute()
    ''')
    for fn in "abcd":
        assert scoped(chains, fn), fn


def test_a_chain_with_no_firm_filter_on_a_firm_table_is_not_scoped():
    chains = read('''
        def leak(db, i):
            return db.table("customers").select("*").eq("id", i).execute()
        def by_client(db, client_id, firm_id):
            return db.table("customers").select("*").eq("client_id", client_id).execute()
    ''')
    assert not scoped(chains, "leak")
    assert not scoped(chains, "by_client"), "a client_id filter is not a firm filter"
    assert set(S.unscoped(chains, TABLES)) == {
        ("routers/x.py", "leak", "customers", "read"),
        ("routers/x.py", "by_client", "customers", "read")}


def test_a_table_with_no_firm_column_is_not_this_rules_and_a_variable_table_is():
    chains = read('''
        def lines(db, i):
            return db.table("journal_lines").select("*").eq("entry_id", i).execute()
        def anything(db, table, i):
            return db.table(table).select("*").eq("id", i).execute()
    ''')
    assert S.unscoped(chains, TABLES) == {("routers/x.py", "anything", "<dynamic>", "read"): 1}


def test_a_chain_built_across_statements_is_read_as_one_and_a_rebind_ends_it():
    chains = read('''
        def ok(db, firm_id, i):
            q = db.table("customers").select("*")
            q = q.eq("firm_id", firm_id)
            if i:
                q = q.eq("id", i)
            return q.execute()
        def other_table_after(db, firm_id):
            q = db.table("customers").select("*")
            q = q.eq("firm_id", firm_id)
            q = db.table("vendors").select("*")
            return q.execute()
    ''')
    assert scoped(chains, "ok")
    assert scoped(chains, "other_table_after", "customers")
    assert not scoped(chains, "other_table_after", "vendors"), (
        "the firm filter belonged to the chain that was rebound, not to the new one")


def test_a_chain_handed_on_is_marked_so_it_is_counted_not_guessed_at():
    chains = read('''
        def build(db):
            return db.table("customers").select("*")
        def hand_over(db, helper):
            q = db.table("customers").select("*")
            return helper(q)
    ''')
    assert all(c.built_elsewhere for c in chains)
    assert not any(c.scoped_by for c in chains)


def test_an_embedded_parents_firm_counts_only_through_an_inner_join():
    chains = read('''
        def inner(db, firm_id):
            return db.table("customers").select("id, p:parents!inner(id)").eq("parents.firm_id", firm_id).execute()
        def outer(db, firm_id):
            return db.table("customers").select("id, p:parents(id)").eq("parents.firm_id", firm_id).execute()
    ''')
    assert scoped(chains, "inner")
    assert not scoped(chains, "outer"), "a left join with a filter on the parent still returns every row"


# ── a payload ────────────────────────────────────────────────────────────────

def test_an_insert_is_scoped_by_a_payload_that_carries_the_firm():
    chains = read('''
        def literal(db, firm_id):
            return db.table("customers").insert({"firm_id": firm_id, "name": "x"}).execute()
        def named(db, firm_id, data):
            row = {**data, "name": "x"}
            row["firm_id"] = firm_id
            return db.table("customers").insert(row).execute()
        def listed(db, firm_id, names):
            rows = [{"firm_id": firm_id, "name": n} for n in names]
            return db.table("customers").insert(rows).execute()
        def forgot(db, data):
            row = {"name": data["name"]}
            return db.table("customers").insert(row).execute()
        def from_request(db, data):
            return db.table("customers").insert(data).execute()
    ''')
    for fn in ("literal", "named", "listed"):
        assert scoped(chains, fn), fn
    assert not scoped(chains, "forgot")
    assert not scoped(chains, "from_request"), "a payload the reader cannot see carries nothing it can vouch for"


# ── a gate ───────────────────────────────────────────────────────────────────

GATED = '''
    def get(db, current_user, cid):
        _assert_customer_scope(current_user, cid)
        return db.table("customers").select("*").eq("id", cid).execute()
'''


def test_an_id_handed_to_a_gate_earlier_in_the_function_is_child_by_parent():
    assert scoped(read(GATED), "get")


def test_only_a_verified_gate_counts_and_only_one_called_before_the_read():
    assert not scoped(read(GATED, gates={"some_other_gate"}), "get")
    assert scoped(read(GATED, gates={"_assert_customer_scope"}), "get")
    after = read('''
        def get(db, current_user, cid):
            row = db.table("customers").select("*").eq("id", cid).execute()
            _assert_customer_scope(current_user, cid)
            return row
    ''')
    assert not scoped(after, "get"), "a gate that runs after the read protected nothing it read"
    other = read('''
        def get(db, current_user, cid, other_id):
            _assert_customer_scope(current_user, other_id)
            return db.table("customers").select("*").eq("id", cid).execute()
    ''')
    assert not scoped(other, "get"), "the gate must be handed the id the chain is keyed on"


def test_a_read_that_is_itself_the_argument_of_a_gate_is_gated():
    chains = read('''
        def get(db, current_user, cid):
            return _assert_customer_scope(current_user, db.table("customers").select("*").eq("id", cid).execute())
    ''')
    assert scoped(chains, "get")


def test_a_gate_is_asked_about_the_same_field_however_the_value_is_spelled():
    chains = read('''
        def create(db, current_user, data):
            assert_client_access(current_user, data.client_id)
            payload = {"firm_id": current_user["firm_id"], **data.model_dump()}
            return db.table("customers").select("*").eq("id", payload["client_id"]).execute()
        def other_field(db, current_user, data):
            assert_client_access(current_user, data.client_id)
            payload = {"firm_id": current_user["firm_id"], **data.model_dump()}
            return db.table("customers").select("*").eq("id", payload["vendor_id"]).execute()
    ''')
    assert scoped(chains, "create")
    assert not scoped(chains, "other_field"), "a different field of the same dict was not the one asserted"


def test_a_gate_counts_only_if_its_code_names_the_firm_not_its_docstring(tmp_path):
    (tmp_path / "routers").mkdir()
    (tmp_path / "routers" / "g.py").write_text(textwrap.dedent('''
        def _assert_talks(current_user, row):
            """404 unless the row is in the caller's firm (firm_id)."""
            return row
        def _assert_asks(current_user, row):
            if row.get("firm_id") != current_user["firm_id"]:
                raise ValueError("no")
            return row
        def _assert_delegates(current_user, row):
            return _assert_asks(current_user, row)
        def _assert_pass_through(current_user, row):
            return row
    '''), encoding="utf-8")
    verdicts = S.gate_verdicts(tmp_path)
    assert verdicts["_assert_talks"][0] is False
    assert verdicts["_assert_asks"][0] is True
    assert verdicts["_assert_delegates"][0] is True, "a gate that calls a verified gate is one"
    assert verdicts["_assert_pass_through"][0] is False


def test_a_gate_name_is_verified_only_if_every_definition_carrying_it_is(tmp_path):
    (tmp_path / "routers").mkdir()
    (tmp_path / "routers" / "a.py").write_text(
        "def _assert_scope(u, r):\n    return r['firm_id'] == u['firm_id']\n", encoding="utf-8")
    (tmp_path / "routers" / "b.py").write_text(
        "def _assert_scope(u, r):\n    return r\n", encoding="utf-8")
    ok, bad = S.gate_verdicts(tmp_path)["_assert_scope"]
    assert ok is False and bad == ["routers/b.py"]


# ── a parent, a flow, the caller ─────────────────────────────────────────────

def test_a_value_used_as_the_primary_key_of_a_scoped_read_is_a_checked_parent():
    chains = read('''
        def child(db, firm_id, pid):
            db.table("customers").select("*").eq("id", pid).eq("firm_id", firm_id).execute()
            return db.table("vendors").select("*").eq("parent_id", pid).execute()
        def not_the_key(db, firm_id, pid):
            db.table("customers").select("*").eq("client_id", pid).eq("firm_id", firm_id).execute()
            return db.table("vendors").select("*").eq("parent_id", pid).execute()
    ''')
    assert scoped(chains, "child", "vendors")
    assert not scoped(chains, "not_the_key", "vendors"), (
        "a read that merely FILTERED on the value returned nothing for a stranger; nothing was refused")


def test_an_id_that_came_out_of_a_scoped_read_is_checked_and_a_key_in_a_container_is_not():
    chains = read('''
        def loop(db, firm_id):
            rows = db.table("customers").select("*").eq("firm_id", firm_id).execute().data
            for r in rows:
                db.table("vendors").update({"x": 1}).eq("customer_id", r["id"]).execute()
        def appended(db, firm_id, svc):
            made = []
            made.append(svc.create(firm_id=firm_id))
            for m in made:
                db.table("vendors").update({"x": 1}).eq("id", m).execute()
        def key_into_a_cache(db, firm_id, cache, auth_user_id):
            row = db.table("customers").select("*").eq("firm_id", firm_id).execute().data
            cache[auth_user_id] = row
            return db.table("vendors").select("*").eq("id", auth_user_id).execute()
    ''')
    assert scoped(chains, "loop", "vendors")
    assert scoped(chains, "appended", "vendors")
    assert not scoped(chains, "key_into_a_cache", "vendors"), (
        "assigning a checked value into cache[key] checks the value, not the key it was filed under")


def test_the_callers_own_identity_is_not_a_tenant_the_caller_chose():
    chains = read('''
        def mine(db, current_user):
            return db.table("clients").select("*").eq("user_id", current_user["id"]).execute()
        def theirs(db, current_user, user_id):
            return db.table("clients").select("*").eq("user_id", user_id).execute()
    ''')
    assert scoped(chains, "mine")
    assert not scoped(chains, "theirs")


# ── a check made after the read ──────────────────────────────────────────────

def test_only_a_comparison_of_the_rows_firm_made_after_the_read_is_a_check():
    chains = read('''
        def compared(db, firm_id, i):
            row = db.table("customers").select("*").eq("id", i).execute().data[0]
            if row.get("firm_id") != firm_id:
                raise ValueError("no")
            return row
        def stamped(db, i):
            row = db.table("customers").select("*").eq("id", i).execute().data[0]
            return {"firm_id": row["firm_id"], "x": 1}
        def compared_before(db, firm_id, i, other):
            if other.get("firm_id") != firm_id:
                raise ValueError("no")
            row = db.table("customers").select("*").eq("id", i).execute().data[0]
            return row
    ''')
    assert scoped(chains, "compared")
    assert not scoped(chains, "stamped"), "reading the row's firm to copy it onto the next row is not a check"
    assert not scoped(chains, "compared_before")


def test_a_client_gate_after_a_read_is_not_a_check_of_the_row_it_read():
    """`can_access_client(user, None)` is True: a firm-level row with no client passes
    it whoever's it is, so handing the row's client to it AFTER the read vouches for
    nothing. A gate that takes the ROW and raises on a foreign one is another matter."""
    chains = read('''
        def client_gate(db, current_user, i):
            row = db.table("customers").select("*").eq("id", i).execute().data[0]
            can_access_client(current_user, row.get("client_id"))
            return row
        def row_gate(db, current_user, i):
            row = db.table("customers").select("*").eq("id", i).execute().data[0]
            _assert_row_scope(current_user, row)
            return row
    ''')
    assert not scoped(chains, "client_gate")
    assert scoped(chains, "row_gate")


# ── a call that stands for a query ───────────────────────────────────────────

def _tree(tmp_path, files: dict[str, str]):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    return S.scan_tree(tmp_path, {"customers"})[0]


def keys(chains):
    return set(S.unscoped(chains, {"customers"}))


def test_a_repository_call_is_judged_as_the_query_it_stands_for(tmp_path):
    chains = _tree(tmp_path, {
        "repositories/thing_repository.py": '''
            class ThingRepository:
                def find_by_id(self, id, firm_id=None):
                    q = _get_db().table("customers").select("*").eq("id", id)
                    if firm_id:
                        q = q.eq("firm_id", firm_id)
                    return q.execute().data
                def create(self, data):
                    return _get_db().table("customers").insert(data).execute()
            thing_repo = ThingRepository()
        ''',
        "routers/r.py": '''
            from repositories.thing_repository import thing_repo
            @router.get("/a")
            def a(cid, current_user):
                return thing_repo.find_by_id(cid)
            @router.get("/b")
            def b(cid, current_user):
                return thing_repo.find_by_id(cid, firm_id=current_user["firm_id"])
            @router.post("/c")
            def c(data, current_user):
                return thing_repo.create({"firm_id": current_user["firm_id"], **data})
            @router.post("/d")
            def d(data, current_user):
                return thing_repo.create(data)
        ''',
    })
    got = keys(chains)
    assert ("routers/r.py", "a", "repo:thing_repo.find_by_id", "read") in got
    assert ("routers/r.py", "b", "repo:thing_repo.find_by_id", "read") not in got
    assert ("routers/r.py", "c", "repo:thing_repo.create", "insert") not in got
    assert ("routers/r.py", "d", "repo:thing_repo.create", "insert") in got
    # The repository's own bare method is the contract the callers are judged against.
    assert ("repositories/thing_repository.py", "ThingRepository.create", "customers", "insert") in got


def test_a_call_inside_the_mock_branch_is_not_a_query(tmp_path):
    chains = _tree(tmp_path, {
        "repositories/thing_repository.py": '''
            class ThingRepository:
                def find_by_id(self, id, firm_id=None):
                    return _get_db().table("customers").select("*").eq("id", id).execute().data
            thing_repo = ThingRepository()
        ''',
        "routers/r.py": '''
            from repositories.thing_repository import thing_repo
            _USE_MOCK = True
            @router.get("/a")
            def a(cid):
                if _USE_MOCK:
                    return thing_repo.find_by_id(cid)
                return thing_repo.find_by_id(cid)
        ''',
    })
    got = [c for c in chains if c.function == "a"]
    assert [c.scoped_by for c in sorted(got, key=lambda c: c.line)] == ["mock-branch", None]


def test_a_helper_keyed_on_its_parameter_is_cleared_by_callers_that_all_looked(tmp_path):
    base = {
        "services/h.py": '''
            def put(db, customer_id):
                return db.table("customers").update({"x": 1}).eq("id", customer_id).execute()
        ''',
        "routers/good.py": '''
            from services import h
            @router.post("/a")
            def good(db, current_user, customer_id):
                _assert_customer_scope(current_user, customer_id)
                return h.put(db, customer_id)
            def _assert_customer_scope(current_user, customer_id):
                return current_user["firm_id"] == customer_id
        ''',
    }
    assert keys(_tree(tmp_path, base)) == set()
    # Nothing calls the helper: nobody judged it, so it is not cleared.
    only_helper = {"services/h.py": base["services/h.py"]}
    other = tmp_path / "other"
    assert keys(_tree(other, only_helper)) == {("services/h.py", "put", "customers", "update")}


def test_a_helper_whose_only_caller_has_no_caller_is_not_cleared(tmp_path):
    """`get_current_user` is called by the framework, not by a line of code: a chain of
    'my callers checked' that ends there has not ended at anything that looked."""
    chains = _tree(tmp_path, {
        "services/h.py": '''
            def put(db, customer_id):
                return db.table("customers").update({"x": 1}).eq("id", customer_id).execute()
        ''',
        "core/dep.py": '''
            from services import h
            def a_dependency(db, customer_id):
                return h.put(db, customer_id)
        ''',
    })
    assert ("services/h.py", "put", "customers", "update") in keys(chains)
    assert ("core/dep.py", "a_dependency", "call:put", "update") in keys(chains)


def test_a_same_name_call_that_cannot_be_tied_to_the_helper_blocks_clearing_it(tmp_path):
    files = {
        "services/h.py": '''
            def record(db, customer_id):
                return db.table("customers").update({"x": 1}).eq("id", customer_id).execute()
        ''',
        "routers/good.py": '''
            from services import h
            @router.post("/a")
            def good(db, current_user, customer_id):
                _assert_customer_scope(current_user, customer_id)
                return h.record(db, customer_id)
            def _assert_customer_scope(current_user, customer_id):
                return current_user["firm_id"] == customer_id
        ''',
        # A call named `record` on something the reader cannot resolve.
        "routers/unknown.py": '''
            @router.post("/b")
            def b(store, event):
                return store.record(event)
        ''',
    }
    chains = _tree(tmp_path, files)
    assert ("services/h.py", "record", "customers", "update") in keys(chains)
    assert sum(1 for c in chains if c.table == "unresolved:record") == 1


def test_a_same_name_call_that_is_provably_to_another_module_blocks_nothing(tmp_path):
    files = {
        "services/h.py": '''
            def record(db, customer_id):
                return db.table("customers").update({"x": 1}).eq("id", customer_id).execute()
        ''',
        "services/other.py": '''
            def record(event):
                return event
        ''',
        "routers/good.py": '''
            from services import h
            from services import other
            @router.post("/a")
            def good(db, current_user, customer_id):
                _assert_customer_scope(current_user, customer_id)
                other.record(customer_id)
                return h.record(db, customer_id)
            def _assert_customer_scope(current_user, customer_id):
                return current_user["firm_id"] == customer_id
        ''',
    }
    assert keys(_tree(tmp_path, files)) == set()


def test_a_helper_that_inserts_what_it_is_handed_is_judged_at_its_callers(tmp_path):
    files = {
        "services/w.py": '''
            def put(db, payload):
                return db.table("customers").insert(payload).execute()
            def relay(db, row):
                return put(db, row)
        ''',
        "routers/r.py": '''
            from services import w
            @router.post("/a")
            def a(db, current_user, data):
                return w.put(db, {"firm_id": current_user["firm_id"], **data})
            @router.post("/b")
            def b(db, current_user, data):
                return w.relay(db, {"firm_id": current_user["firm_id"], **data})
        ''',
    }
    assert keys(_tree(tmp_path, files)) == set()
    files["routers/r.py"] += '''
            @router.post("/c")
            def c(db, data):
                return w.put(db, data)
    '''
    other = tmp_path / "second"
    got = keys(_tree(other, files))
    assert ("routers/r.py", "c", "call:put", "insert") in got
    assert ("services/w.py", "put", "customers", "insert") in got


def test_the_table_set_and_the_census_count_what_they_say(tmp_path):
    chains = _tree(tmp_path, {
        "services/a.py": '''
            def f(db, table, firm_id, i):
                db.table("customers").select("*").eq("firm_id", firm_id).execute()
                db.table("journal_lines").select("*").eq("entry_id", i).execute()
                db.table(table).select("*").eq("id", i).execute()
        ''',
    })
    c = S.census(chains, {"customers"})
    assert c["chains"] == 3
    assert c["judged"] == 2
    assert c["unjudged_no_firm_column"] == 1
    assert c["table_named_by_a_variable"] == 1
    assert c["by_evidence"] == {"filter": 1, "unscoped": 1}
