"""A voucher's lines have an order, and multi-currency can be switched on
(ACC-16 and ACC-19).

TWO FINDINGS, ONE COMMIT, AND THEY ARE NOT RELATED — they share a test file
because they share a migration number and a review, not a subject.

ACC-16 — `journal_lines` had no ordering column, so a voucher's lines came back
    in whatever order Postgres happened to return them. That is not stable
    across reads: a CA opening the same manual journal twice could see the
    debits and credits interleaved differently, and a four-line bank charge
    (expense, CGST, SGST, bank) had no reason to read in the order it was
    entered. Migration 384 records the position each line held in the array
    `post_journal_atomic` was called with; `domain/accounting/line_order.py`
    derives an order for every line written before it, because migration 251
    makes a posted line immutable and a backfill for a DISPLAY order is not
    worth disabling that trigger against production for.

ACC-19 — all five multi-currency phases are BUILT and none of it could be
    turned on. `resolve_currency_policy` is `active = L1 AND L2 AND L3`; L2
    (`firms.multi_currency_entitled`) and L3 (`clients.multi_currency_enabled`)
    were READ by six routers and WRITTEN BY NOTHING — no endpoint, no Pydantic
    field, no screen, no seed. Only a manual UPDATE against the database could
    activate any of it. What is pinned below is the two writers, that the read
    says WHICH gate is down (a bare `active: false` is what made this
    unusable), and every refusal.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.currencies as cur
import services.phase2_journal_service as pjs
from domain.accounting import line_order
from services.manual_journal_service import manual_journal_service as svc

_HERE = Path(__file__).resolve().parent
_API = _HERE.parent
_MIG = _API / "migrations"

FIRM, CLIENT, ENTRY = "firm-1", "client-1", "entry-1"


# ══ ACC-16 — the rule, driven by the shared table ════════════════════════════

_TABLE = json.loads((_HERE / "fixtures" / "journal_line_order.json").read_text())


@pytest.mark.parametrize("case", _TABLE["cases"], ids=lambda c: c["name"])
def test_the_display_order_is_the_table(case):
    got = [r["id"] for r in line_order.in_display_order(case["rows"])]
    assert got == case["expected"], case["name"]


def test_the_table_is_not_empty_and_covers_both_sides_of_the_rule():
    """A fixture-driven test passes vacuously on an empty table, and it would
    pass on a table that only ever exercised one branch."""
    cases = _TABLE["cases"]
    assert len(cases) >= 6
    ordered = [c for c in cases if any(r.get("line_order") is not None for r in c["rows"])]
    derived = [c for c in cases if all(r.get("line_order") is None for r in c["rows"])]
    assert ordered, "no case exercises a line written from migration 384 onwards"
    assert derived, "no case exercises a line written before it"


def test_the_sort_is_stable_under_any_input_order():
    """The property that matters is that one voucher renders the SAME way on
    every read — so the answer cannot depend on what Postgres handed back."""
    rows = [
        {"id": "b", "line_order": None, "debit_paise": 100, "created_at": "t"},
        {"id": "a", "line_order": None, "debit_paise": 100, "created_at": "t"},
        {"id": "c", "line_order": None, "debit_paise": 0, "created_at": "t"},
    ]
    import itertools
    answers = {tuple(r["id"] for r in line_order.in_display_order(list(p)))
               for p in itertools.permutations(rows)}
    assert answers == {("a", "b", "c")}


def test_a_malformed_line_order_falls_back_rather_than_raising():
    """A display order that throws is worse than one that is merely
    conventional — the CA would see the voucher not at all."""
    rows = [
        {"id": "cr", "line_order": "not-a-number", "debit_paise": 0, "created_at": "t"},
        {"id": "dr", "line_order": None, "debit_paise": 100, "created_at": "t"},
    ]
    assert [r["id"] for r in line_order.in_display_order(rows)] == ["dr", "cr"]


def test_a_negative_line_order_is_not_treated_as_an_order():
    """Nothing writes one, so a negative value is corruption rather than
    intent — and sorting on it would put a line before position zero."""
    rows = [
        {"id": "bad", "line_order": -1, "debit_paise": 0, "created_at": "t"},
        {"id": "good", "line_order": 0, "debit_paise": 0, "created_at": "t"},
    ]
    assert [r["id"] for r in line_order.in_display_order(rows)] == ["good", "bad"]


def test_the_input_is_not_mutated():
    rows = [{"id": "b", "line_order": 1}, {"id": "a", "line_order": 0}]
    before = [r["id"] for r in rows]
    line_order.in_display_order(rows)
    assert [r["id"] for r in rows] == before


def test_there_is_no_second_implementation_in_the_browser():
    """The module's docstring says why there is no TypeScript mirror: the one
    place a CA SEES a voucher's lines reads GET /api/accounting/journal/{id}.
    If a screen ever renders lines out of a direct PostgREST read the rule has
    to be mirrored and pinned — PostgREST can express neither 'debits before
    credits' nor a fallback chain as an ORDER BY. This fails when that day
    comes, which is the point."""
    web = _API.parent / "web"
    hits = []
    for path in list(web.glob("lib/**/*.ts")) + list(web.glob("app/**/*.tsx")) + \
            list(web.glob("components/**/*.tsx")):
        if "node_modules" in str(path):
            continue
        if "line_order" in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(web)))
    assert hits == [], (
        "apps/web now mentions line_order — if a screen renders a voucher's "
        "lines from a direct PostgREST read, mirror domain/accounting/"
        "line_order.py and pin it to tests/fixtures/journal_line_order.json")


# ══ ACC-16 — the manual journal reads and writes it ══════════════════════════

class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows, sink, name):
        self._rows, self._sink, self._name = rows, sink, name

    def select(self, *a, **_k):
        self._sink.selects.append((self._name, a[0] if a else ""))
        return self

    def eq(self, c, v):
        self._rows = [r for r in self._rows if r.get(c) == v]
        return self

    def is_(self, c, _v):
        self._rows = [r for r in self._rows if r.get(c) is None]
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return _Result([dict(r) for r in self._rows])

    def update(self, patch):
        self._sink.writes.append((self._name, "update", patch))
        return self

    def delete(self):
        self._sink.writes.append((self._name, "delete", None))
        return self

    def insert(self, rows):
        self._sink.writes.append((self._name, "insert", rows))
        return self


class _Deferred:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Result(self._data)


class _DB:
    def __init__(self, entry: dict, lock_reason=None):
        self.entry, self.lock_reason = entry, lock_reason
        self.writes: list = []
        self.selects: list = []

    def table(self, name):
        return _Table([self.entry] if name == "journal_entries" else [], self, name)

    def rpc(self, fn, params):
        if fn == "journal_period_lock_reason":
            return _Deferred(self.lock_reason)
        if fn == "edit_posted_journal":
            return _Deferred({"id": ENTRY})
        raise AssertionError(f"unexpected rpc {fn}")


def _entry(lines, **over) -> dict:
    e = {
        "id": ENTRY, "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-06-15",
        "reference_no": "MJ-1", "narration": "Bank charges", "entry_type": "Journal",
        "is_posted": True, "is_reversed": False, "source_type": "manual",
        "created_at": "2026-06-15T00:00:00Z", "deleted_at": None, "lines": lines,
    }
    e.update(over)
    return e


def test_the_read_asks_for_every_column_the_rule_needs():
    """A read that omits `line_order` gets the DERIVED order for every line,
    including new ones — deterministic, and quietly the wrong order."""
    db = _DB(_entry([{"id": "l1", "account_id": "a1", "debit_paise": 100,
                      "credit_paise": 0, "line_order": 0}]))
    svc.get(db, FIRM, ENTRY)
    select = next(s for t, s in db.selects if t == "journal_entries")
    for col in line_order.REQUIRED_COLUMNS:
        assert col in select, f"the manual-journal read does not select {col}"


def test_a_voucher_written_from_384_reads_in_the_order_it_was_written():
    """PostgREST returned them shuffled; the CA sees expense, CGST, SGST, bank."""
    db = _DB(_entry([
        {"id": "bank", "account_id": "a4", "debit_paise": 0, "credit_paise": 59000,
         "line_order": 3, "created_at": "t"},
        {"id": "cgst", "account_id": "a2", "debit_paise": 4500, "credit_paise": 0,
         "line_order": 1, "created_at": "t"},
        {"id": "exp", "account_id": "a1", "debit_paise": 50000, "credit_paise": 0,
         "line_order": 0, "created_at": "t"},
        {"id": "sgst", "account_id": "a3", "debit_paise": 4500, "credit_paise": 0,
         "line_order": 2, "created_at": "t"},
    ]))
    got = svc.get(db, FIRM, ENTRY)
    assert [l["id"] for l in got["lines"]] == ["exp", "cgst", "sgst", "bank"]
    # And the totals still foot — the sort must not drop or duplicate a line.
    assert got["total_debit_paise"] == 59000 == got["total_credit_paise"]


def test_a_voucher_written_before_384_reads_debits_first():
    db = _DB(_entry([
        {"id": "cr", "account_id": "a2", "debit_paise": 0, "credit_paise": 59000,
         "line_order": None, "created_at": "2025-01-01T00:00:00Z"},
        {"id": "dr", "account_id": "a1", "debit_paise": 59000, "credit_paise": 0,
         "line_order": None, "created_at": "2025-01-01T00:00:00Z"},
    ]))
    assert [l["id"] for l in svc.get(db, FIRM, ENTRY)["lines"]] == ["dr", "cr"]


def test_an_edited_draft_is_renumbered_from_the_array_the_ca_saved():
    """A DRAFT edit does its own INSERT in Python rather than going through the
    RPC, so WITH ORDINALITY never sees it. Without the stamp an edited voucher
    would fall back to the derived order while the one beside it kept the order
    it was typed in. (The POSTED edit goes through `edit_posted_journal`, which
    migration 384 also replaces — pinned below.)"""
    db = _DB(_entry([{"id": "l1", "account_id": "a1", "debit_paise": 100,
                      "credit_paise": 0, "line_order": 0}], is_posted=False))
    lines = [
        {"account_id": "cr", "debit_paise": 0, "credit_paise": 59000},
        {"account_id": "dr1", "debit_paise": 50000, "credit_paise": 0},
        {"account_id": "dr2", "debit_paise": 9000, "credit_paise": 0},
    ]
    svc.update(db, FIRM, ENTRY, {"lines": lines}, actor_id="u1")
    inserted = next(rows for t, op, rows in db.writes
                    if t == "journal_lines" and op == "insert")
    assert [r["line_order"] for r in inserted] == [0, 1, 2]
    # The CA put the credit first and it STAYS first — the order recorded is
    # the one they saved, not the conventional one.
    assert [r["account_id"] for r in inserted] == ["cr", "dr1", "dr2"]


def test_the_non_rpc_posting_fallback_stamps_the_same_column():
    """A database double without `rpc` must produce the rows the real one does,
    or every mock-mode voucher falls back to the derived order and no test can
    see the column working."""
    src = inspect.getsource(pjs.Phase2JournalService._create_journal)
    assert '"line_order": i' in src, (
        "the non-RPC insert in _create_journal no longer stamps line_order")


# ══ ACC-16 — migration 384 ═══════════════════════════════════════════════════

def _mig(name: str) -> str:
    return (_MIG / name).read_text(encoding="utf-8")


_M384 = "384_a_voucher_shows_its_lines_in_order.sql"
_M384_BACK = "384_a_voucher_shows_its_lines_in_order_rollback.sql"

_HEAD_POST = "CREATE OR REPLACE FUNCTION public.post_journal_atomic"
_HEAD_EDIT = "CREATE OR REPLACE FUNCTION public.edit_posted_journal"


def _ancestor(head: str) -> str:
    """The migration that LAST defined this function before 384 — found the way
    the database finds it, by number, rather than named.

    THIS IS THE RULE AND NOT A SPELLING OF IT, and the distinction is the whole
    reason the function below exists. An earlier draft of this test named
    migration 243 as post_journal_atomic's predecessor and PASSED, because 384
    had faithfully been derived from 243 — while the live definition was 274's,
    which carries 271's SECURITY DEFINER and 274's own reversal stamp. The
    replacement would have reverted both and reproduced, exactly, the
    production incident 274's header records. A named ancestor goes stale the
    day somebody replaces the function again; this does not.
    """
    best = None
    for path in sorted(_MIG.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name.startswith("384_") or "rollback" in path.name:
            continue
        if head in path.read_text(encoding="utf-8"):
            best = path.name
    assert best, f"no migration defines {head}"
    return best


def _fn(sql: str, head: str) -> str:
    """One function's text, from its CREATE to its closing dollar-quote — so a
    comparison is of the function and not of the prose around it."""
    start = sql.index(head)
    for close in ("\n$function$;", "\n$$;"):
        at = sql.find(close, start)
        if at != -1:
            return sql[start:at + len(close)]
    raise AssertionError(f"{head} is not closed by a dollar-quote")


def test_384_adds_the_column_nullable_with_no_default():
    """Nullable and undefaulted is the whole design: an existing line stays
    NULL and is ordered by derivation, so migration 251's immutability trigger
    is never disabled for a display order."""
    sql = _mig(_M384)
    assert re.search(r"ADD COLUMN IF NOT EXISTS line_order INTEGER\s*;", sql)
    add = sql[sql.index("ADD COLUMN IF NOT EXISTS line_order"):]
    head = add[:add.index(";")]
    assert "NOT NULL" not in head and "DEFAULT" not in head
    assert "UPDATE public.journal_lines SET line_order" not in sql, "384 must not backfill"


def test_384_takes_the_order_from_the_array_on_the_posting_path():
    fn = _fn(_mig(_M384), _HEAD_POST)
    assert "WITH ORDINALITY AS t(l, ord)" in fn
    assert "COALESCE((l->>'line_order')::integer, (ord - 1)::integer)" in fn, (
        "WITH ORDINALITY is 1-based and the column is 0-based; a caller that "
        "sent its own line_order must still win")


def test_384_takes_the_order_from_the_array_on_the_edit_path_too():
    """`edit_posted_journal` DELETEs every line and re-INSERTs the array —
    "replace rather than reconcile". Left alone it would re-insert them with
    line_order NULL, so a voucher written in the CA's order LOST that order the
    first time it was corrected, silently: the derived rule still gives a
    stable answer, just the conventional one rather than theirs."""
    fn = _fn(_mig(_M384), _HEAD_EDIT)
    assert "WITH ORDINALITY AS t(ln, ord)" in fn
    assert "(ord - 1)::integer" in fn
    assert "narration, line_order)" in fn


_SUBS = {
    _HEAD_POST: [
        ("rate_date, line_order\n  )", "rate_date\n  )"),
        ("    NULLIF(l->>'rate_date', '')::date,\n"
         "    -- WITH ORDINALITY is 1-based; the column is 0-based so it reads as an\n"
         "    -- index. A caller that sent its own line_order still wins, which is what\n"
         "    -- lets manual_journal_service re-number an edited voucher.\n"
         "    COALESCE((l->>'line_order')::integer, (ord - 1)::integer)\n"
         "  FROM jsonb_array_elements(p_lines) WITH ORDINALITY AS t(l, ord);",
         "    NULLIF(l->>'rate_date', '')::date\n"
         "  FROM jsonb_array_elements(p_lines) AS l;"),
    ],
    _HEAD_EDIT: [
        ("credit_paise, narration, line_order)", "credit_paise, narration)"),
        ("           NULLIF(ln->>'narration', ''),\n"
         "           -- The array the CA saved IS the order (migration 384). WITH\n"
         "           -- ORDINALITY is 1-based and the column is 0-based.\n"
         "           (ord - 1)::integer\n"
         "      FROM jsonb_array_elements(p_lines) WITH ORDINALITY AS t(ln, ord);",
         "           NULLIF(ln->>'narration', '')\n"
         "      FROM jsonb_array_elements(p_lines) ln;"),
    ],
}


@pytest.mark.parametrize("head", [_HEAD_POST, _HEAD_EDIT])
def test_384s_functions_are_their_predecessors_plus_exactly_two_edits(head):
    """CREATE OR REPLACE overwrites whatever is there, so a replacement either
    carries every earlier change forward or silently reverts it. This states
    that only the two intended edits happened — against the ancestor found by
    NUMBER, so it cannot be pointed at a stale one."""
    prev = _mig(_ancestor(head))
    rebuilt = _fn(_mig(_M384), head)
    for new, old in _SUBS[head]:
        assert rebuilt.count(new) == 1, f"substitution not found — {new[:48]!r}"
        rebuilt = rebuilt.replace(new, old)
    assert rebuilt.strip() == _fn(prev, head).strip(), (
        f"384's {head} is no longer the body of its predecessor plus the two "
        "line_order edits — something else changed with it")


def test_the_ancestor_is_the_one_the_database_would_have():
    """Belt and braces on the helper itself: 274 replaced post_journal_atomic
    after 243, and 338 replaced edit_posted_journal after 266. A test that
    named the earlier of each pair passed while 384 reverted SECURITY DEFINER
    and the reversal stamp."""
    assert _ancestor(_HEAD_POST).startswith("274_")
    assert _ancestor(_HEAD_EDIT).startswith("338_")


@pytest.mark.parametrize("clause", [
    # post_journal_atomic — the privilege model (271) and the reversal stamp
    # (274) that a replacement derived from 243 would have silently reverted.
    "SECURITY DEFINER",
    "post_journal_atomic: caller has no user record in this database",
    "is not the caller''s firm",
    "only a Partner may post to the firm''s internal client",
    "v_reversed := NULLIF(p_entry->>'reversal_of', '')::uuid;",
    "COALESCE(is_reversed, false) = false",
    "REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM anon;",
    "GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated;",
    # …and the guards it has carried since 243.
    "post_journal_atomic: journal imbalance",
    "refusing to post a zero-value journal entry",
    "jsonb_populate_record(NULL::public.journal_entries, $1)",
    "AND deleted_at IS NULL",
    # edit_posted_journal — ACC-04's manual-only gate and the passbook rebuild.
    "IF COALESCE(v_entry.source_type, '') <> 'manual' THEN",
    "PERFORM public.apb_assert_no_drift();",
    "REVOKE ALL ON FUNCTION public.edit_posted_journal",
])
def test_384_keeps_every_load_bearing_clause_of_both_functions(clause):
    assert clause in _mig(_M384)


@pytest.mark.parametrize("head", [_HEAD_POST, _HEAD_EDIT])
def test_the_rollback_restores_each_predecessor_exactly(head):
    back, prev = _mig(_M384_BACK), _mig(_ancestor(head))
    assert _fn(back, head).strip() == _fn(prev, head).strip()
    assert "line_order" not in _fn(back, head)


def test_the_rollback_drops_the_column():
    assert "DROP COLUMN IF EXISTS line_order" in _mig(_M384_BACK)


# ══ ACC-19 — the two gates that nothing could write ══════════════════════════

class _CurTable:
    def __init__(self, rows, sink, name):
        self._rows, self._sink, self._name = list(rows), sink, name
        self._patch = None

    def select(self, *_a, **_k):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, c, v):
        self._rows = [r for r in self._rows if r.get(c) == v]
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self._patch is not None:
            for r in self._rows:
                r.update(self._patch)
            self._sink.writes.append((self._name, dict(self._patch),
                                      [r["id"] for r in self._rows]))
        return _Result([dict(r) for r in self._rows])


class _CurDB:
    def __init__(self, firm: dict | None = None, client: dict | None = None):
        self.firms = [firm] if firm else []
        self.clients = [client] if client else []
        self.writes: list = []

    def table(self, name):
        return _CurTable(getattr(self, name, []), self, name)


CALLER = {"firm_id": FIRM, "id": "u", "role": "Partner"}


@pytest.fixture
def live(monkeypatch):
    """Out of mock mode, on a database double. The mock branch answers a fixed
    policy and would pin nothing about the gates."""
    def _wire(db, platform=True):
        monkeypatch.setattr(cur, "_USE_MOCK", False)
        monkeypatch.setattr(cur, "assert_client_access", lambda *_a, **_k: None)
        import core.supabase_client as sc
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(cur, "multi_currency_platform_enabled", lambda: platform)
        return db
    return _wire


def _firm(entitled=False):
    return {"id": FIRM, "multi_currency_entitled": entitled}


def _client(enabled=False, functional="INR"):
    return {"id": CLIENT, "firm_id": FIRM, "multi_currency_enabled": enabled,
            "functional_currency": functional}


def test_the_policy_says_which_gate_is_down():
    """`active: false` alone is what made this feature unusable — a Partner
    ticked something and could not tell which of three switches was still
    down."""
    g = cur._gates(_firm(entitled=True), _client(enabled=False))
    assert g["firm"]["on"] is True
    assert g["client"]["on"] is False
    assert g["client"]["settable"] is True


def test_the_platform_gate_is_shown_and_never_offered():
    g = cur._gates(_firm(), _client())
    assert g["platform"]["settable"] is False
    assert "MULTI_CURRENCY_ENABLED" in g["platform"]["why"]
    assert not hasattr(cur, "set_platform_flag")


def test_the_gates_report_the_clients_real_functional_currency():
    """`resolve_currency_policy` fails SAFE and answers INR whenever the policy
    is inactive, so the top-level field cannot tell a CA their client's books
    are kept in dollars. The gate carries the real one, which is what lets the
    screen say why the checkbox is refused."""
    g = cur._gates(_firm(entitled=True), _client(enabled=True, functional="usd"))
    assert g["functional_currency"] == "USD"
    assert g["functional_currency_supported"] is False

    from domain.currency import resolve_currency_policy
    assert resolve_currency_policy(_firm(True), _client(True, "usd")).functional_currency == "INR"


def test_the_mock_branch_answers_the_same_shape(monkeypatch):
    """A mock reply missing `gates` renders an undefined gate as 'off' in dev
    and as something else in production."""
    monkeypatch.setattr(cur, "_USE_MOCK", True)
    monkeypatch.setattr(cur, "assert_client_access", lambda *_a, **_k: None)
    body = cur.get_currency_policy(client_id=CLIENT, current_user=CALLER)
    assert set(body["data"]) == {"active", "functional_currency", "gates"}
    assert set(body["data"]["gates"]) >= {"platform", "firm", "client",
                                          "functional_currency_supported"}


def test_the_firm_switch_writes_the_column_nothing_used_to_write(live):
    db = live(_CurDB(firm=_firm(entitled=False)))
    body = cur.set_firm_entitlement(enabled=True, current_user=CALLER)

    assert body["success"] is True
    assert db.writes == [("firms", {"multi_currency_entitled": True}, [FIRM])]
    assert db.firms[0]["multi_currency_entitled"] is True


def test_the_firm_switch_is_scoped_to_the_callers_own_firm(live):
    """There is no firm_id in the request, so a Partner can only ever change
    their own — the service-role key bypasses RLS, and the .eq() is the
    isolation control."""
    src = inspect.getsource(cur.set_firm_entitlement)
    assert '.eq("id", firm_id)' in src
    assert 'current_user.get("firm_id")' in src
    db = live(_CurDB(firm={"id": "SOMEONE-ELSE", "multi_currency_entitled": False}))
    with pytest.raises(HTTPException) as e:
        cur.set_firm_entitlement(enabled=True, current_user=CALLER)
    assert e.value.status_code == 404
    # The UPDATE statement runs; the .eq() means it touches no row, which is
    # the isolation control. Nothing was changed and the endpoint 404s.
    assert [ids for _t, _patch, ids in db.writes] == [[]]
    assert db.firms[0]["multi_currency_entitled"] is False


def test_the_client_switch_writes_the_other_column(live):
    db = live(_CurDB(firm=_firm(entitled=True), client=_client(enabled=False)))
    body = cur.set_client_currency_policy(client_id=CLIENT, enabled=True, current_user=CALLER)

    assert body["success"] is True
    assert db.clients[0]["multi_currency_enabled"] is True


def test_turning_a_client_on_under_an_unentitled_firm_is_refused_with_a_sentence(live):
    """Not a silent no-op. An inert checkbox is the defect this endpoint exists
    to end, and adding a second one would be the same mistake."""
    db = live(_CurDB(firm=_firm(entitled=False), client=_client()))
    with pytest.raises(HTTPException) as e:
        cur.set_client_currency_policy(client_id=CLIENT, enabled=True, current_user=CALLER)
    assert e.value.status_code == 409
    assert "off for the firm" in e.value.detail.lower()
    assert db.clients[0]["multi_currency_enabled"] is False


def test_turning_a_non_inr_client_on_is_refused_and_says_which_currency(live):
    """Capability B — presentation and translation — is not built, so
    `resolve_currency_policy` fails safe on a non-INR functional currency by
    design. The checkbox would be inert."""
    db = live(_CurDB(firm=_firm(entitled=True), client=_client(functional="USD")))
    with pytest.raises(HTTPException) as e:
        cur.set_client_currency_policy(client_id=CLIENT, enabled=True, current_user=CALLER)
    assert e.value.status_code == 409
    assert "USD" in e.value.detail
    assert db.clients[0]["multi_currency_enabled"] is False


@pytest.mark.parametrize("firm,client", [
    (_firm(entitled=False), _client(enabled=True)),
    (_firm(entitled=True), _client(enabled=True, functional="USD")),
])
def test_turning_a_client_off_is_never_refused(live, firm, client):
    """A client that should not be transacting in foreign currency has to be
    stoppable whatever the firm's state is."""
    db = live(_CurDB(firm=firm, client=client))
    cur.set_client_currency_policy(client_id=CLIENT, enabled=False, current_user=CALLER)
    assert db.clients[0]["multi_currency_enabled"] is False


def test_the_client_switch_checks_assignment_scope(live):
    src = inspect.getsource(cur.set_client_currency_policy)
    assert "assert_client_access(current_user, client_id)" in src
    assert '.eq("firm_id", firm_id)' in src


def test_the_firm_gate_can_be_read_with_no_client_in_the_request(live):
    """A firm with no clients yet cannot read its own gate off a client's
    policy — and that is exactly the firm a Partner is switching this on for.
    The checkbox would snap back to Off after every save."""
    db = live(_CurDB(firm=_firm(entitled=True)))
    body = cur.get_firm_entitlement(current_user=CALLER)
    assert body["data"]["firm"]["on"] is True
    assert body["data"]["platform"]["on"] is True
    assert db is not None


@pytest.mark.parametrize("mock", [True, False])
def test_the_firm_level_answer_never_reports_a_client_gate(live, monkeypatch, mock):
    """Both branches. `_gates` builds five keys and only two of them mean
    anything with no client in the request — a `client: {on: false}` here would
    read as "this client is switched off" when no client was named at all."""
    if mock:
        monkeypatch.setattr(cur, "_USE_MOCK", True)
    else:
        live(_CurDB(firm=_firm(entitled=True)))
    body = cur.get_firm_entitlement(current_user=CALLER)
    assert set(body["data"]) == {"platform", "firm"}


def test_both_firm_answers_come_out_of_one_function():
    """Two readings of `firms.multi_currency_entitled` is exactly the drift
    this codebase keeps recording."""
    for fn in (cur.get_firm_entitlement, cur.get_currency_policy):
        assert "_gates(" in inspect.getsource(fn)


def test_writing_a_gate_is_partner_only():
    """It changes what the posting kernel accepts for every client of the
    firm."""
    for fn in (cur.set_firm_entitlement, cur.set_client_currency_policy):
        src = inspect.getsource(fn)
        assert 'rbac("settings", "write")' in src, fn.__name__
    from core.permissions import PERMISSIONS
    assert PERMISSIONS["settings"]["write"] == {"Partner"}
