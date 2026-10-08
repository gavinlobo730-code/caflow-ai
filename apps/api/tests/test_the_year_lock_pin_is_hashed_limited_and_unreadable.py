"""The year-lock PIN is a salted hash nobody signed in can read, and guesses at it are counted (POST-A-004).

WHAT WAS WRONG
    The PIN that authorises locking and unlocking a financial year was stored as typed in `firms.lock_pin`.
    `firms` is readable by every member of the firm over PostgREST, so a Manager, an Executive or a Reviewer
    could read it from a browser console; a Partner's own session could blank it; and the comparison was `!=`
    with no limit on the number of guesses at a four-character PIN.

WHAT THIS FILE HOLDS, AS RULES RATHER THAN SPELLINGS
    * the stored form: salted PBKDF2 at a stated work factor, never the PIN, never in `firms`;
    * the check: constant time, fails closed on anything it does not understand, upgrades an older form on use;
    * the limit: every attempt that reaches the comparison is counted, per person and per firm, and a refusal
      is a 429 with `Retry-After` even for the right PIN;
    * the trail: a wrong PIN leaves an audit row naming the year and the direction and never the PIN;
    * the reach: nothing in the API, outside the migrations, names `firms.lock_pin`, and nothing in the browser
      names either column or the table.

    The database half (the table nobody signed in can read, the CHECK that keeps `firms.lock_pin` empty, the
    backfill's hash verified by the Python verifier) is tests/test_480_the_year_lock_pin_pg.py.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.rate_window import SlidingWindowLimiter
from domain.firm import lock_pin
from services import year_lock_service as yls
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"

FIRM = "FIRM-PIN"
PIN = "Tr0ub4dor&3"           # not hex, so no digest can contain it by chance
ACTOR = "auth-user-1"


# ── the stored form and the check ────────────────────────────────────────────

def test_the_work_factor_is_a_stated_figure_and_is_what_a_new_hash_carries():
    """600,000 is OWASP's figure for PBKDF2-HMAC-SHA256; a constant lowered by accident is a weaker hash."""
    assert lock_pin.ITERATIONS >= 600_000
    stored = lock_pin.hash_pin(PIN)
    scheme, iterations, salt, digest = stored.split("$")
    assert scheme == "pbkdf2_sha256"
    assert int(iterations) == lock_pin.ITERATIONS
    assert len(salt) >= 32 and len(digest) == 64
    assert PIN not in stored


def test_two_hashes_of_one_pin_differ_and_both_verify():
    a = lock_pin.hash_pin(PIN, iterations=1_000)
    b = lock_pin.hash_pin(PIN, iterations=1_000)
    assert a != b
    assert lock_pin.verify(PIN, a).ok and lock_pin.verify(PIN, b).ok


def test_a_wrong_pin_does_not_verify_and_a_right_one_does():
    stored = lock_pin.hash_pin(PIN, iterations=1_000)
    assert lock_pin.verify(PIN, stored) == lock_pin.Verdict(True, True)       # below today's figure: upgrade
    assert not lock_pin.verify(PIN + " ", stored).ok
    assert not lock_pin.verify(PIN.lower(), stored).ok
    assert not lock_pin.verify("", stored).ok


def test_a_hash_made_at_the_current_work_factor_asks_for_no_upgrade():
    assert lock_pin.verify(PIN, lock_pin.hash_pin(PIN)) == lock_pin.Verdict(True, False)


def _legacy(pin: str, salt: str = "a1b2c3d4e5f60718293a4b5c6d7e8f90") -> str:
    """The form migration 480 writes: sha256 over the salt's bytes then the PIN's UTF-8 bytes."""
    return f"sha256${salt}${hashlib.sha256(salt.encode() + pin.encode('utf-8')).hexdigest()}"


def test_the_form_migration_480_writes_verifies_and_asks_to_be_rewritten():
    for pin in (PIN, "piné₹अ", "1234"):
        verdict = lock_pin.verify(pin, _legacy(pin))
        assert verdict == lock_pin.Verdict(True, True), pin
        assert not lock_pin.verify(pin + "x", _legacy(pin)).ok


@pytest.mark.parametrize("stored", [
    None, "", "$", "plain", PIN, "md5$abc$def", "sha256$only-two", "sha256$a$b$c",
    "pbkdf2_sha256$600000$salt", "pbkdf2_sha256$notanumber$salt$00", "pbkdf2_sha256$0$salt$00",
    "pbkdf2_sha256$-5$salt$00", "pbkdf2_sha256$999999999999$salt$00", "pbkdf2_sha256$1000$saélt$00",
])
def test_anything_the_verifier_does_not_understand_is_a_no(stored):
    assert lock_pin.verify(PIN, stored) == lock_pin.Verdict(False, False)


def test_a_pin_with_no_utf8_form_is_a_no_and_never_an_exception():
    assert lock_pin.verify("\ud800", lock_pin.hash_pin(PIN, iterations=1_000)).ok is False
    assert lock_pin.problem_with("\ud800abc") is not None
    with pytest.raises(ValueError):
        lock_pin.hash_pin("\ud800abc")


def test_non_text_is_a_no():
    stored = lock_pin.hash_pin(PIN, iterations=1_000)
    for not_text in (None, 1234, b"1234", ["1234"]):
        assert lock_pin.verify(not_text, stored).ok is False


def test_the_bounds_apply_when_a_pin_is_set_and_not_when_one_is_checked():
    assert lock_pin.problem_with("x" * 3) is not None
    assert lock_pin.problem_with("x" * 4) is None
    assert lock_pin.problem_with("x" * 128) is None
    assert lock_pin.problem_with("x" * 129) is not None
    assert lock_pin.problem_with(None) is not None
    # A PIN set before the bound existed must still open the year it locked.
    assert lock_pin.verify("123", lock_pin.hash_pin("123", iterations=1_000)).ok


# ── the service: where it lives, what it counts, what it records ─────────────

def _setup(monkeypatch, pin=None, stored=None):
    monkeypatch.setattr(lock_pin, "ITERATIONS", 1_000)     # the figure is pinned above; these are about who gets in
    db = FakeDB()
    wire_e2e(monkeypatch, db, [yls])
    events: list[dict] = []

    def record(*args, **kwargs):
        events.append({"args": args, **kwargs})

    monkeypatch.setattr(yls, "log_event", record)
    db.seed("firms", {"id": FIRM, "locked_financial_years": [], "lock_pin": None})
    if stored is not None:
        db.seed("firm_lock_pins", {"firm_id": FIRM, "pin_hash": stored})
    elif pin is not None:
        db.seed("firm_lock_pins", {"firm_id": FIRM, "pin_hash": lock_pin.hash_pin(pin)})
    return db, events


def _lock(db, *, pin=None, actor=ACTOR, year="2025-26", lock=True, **kw):
    return yls.set_lock(db, FIRM, year, lock, pin=pin, actor_id=actor, actor_email="p@firm.test", **kw)


def test_the_first_pin_is_stored_as_a_hash_in_its_own_table_and_never_in_firms(monkeypatch):
    db, events = _setup(monkeypatch)
    state = _lock(db, pin=PIN)
    assert state["pin_set"] is True
    assert db.rows("firms")[0]["lock_pin"] is None
    (row,) = db.rows("firm_lock_pins")
    assert row["firm_id"] == FIRM and row["pin_hash"].startswith("pbkdf2_sha256$")
    assert PIN not in repr(db.rows("firm_lock_pins")) + repr(db.rows("firms")) + repr(events)
    # What the trail says: that a PIN was set, not what it is.
    assert events[-1]["args"][3] == "year_lock" and events[-1]["new_data"]["pin_set"] is True


def test_get_state_says_whether_a_pin_is_set_and_nothing_made_from_it(monkeypatch):
    db, _ = _setup(monkeypatch, pin=PIN)
    state = yls.get_state(db, FIRM)
    assert state == {"locked_financial_years": [], "pin_set": True}
    db2, _ = _setup(monkeypatch)
    assert yls.get_state(db2, FIRM)["pin_set"] is False


def test_a_wrong_pin_is_refused_audited_by_auth_id_and_never_written_down(monkeypatch):
    db, events = _setup(monkeypatch, pin=PIN)
    with pytest.raises(HTTPException) as e:
        _lock(db, pin="Wr0ng-guess!", lock=False)
    assert e.value.status_code == 403 and e.value.detail == "Incorrect lock PIN."
    (ev,) = events
    assert ev["args"][3] == "year_lock_pin_refused"
    assert ev["actor_id"] == ACTOR                      # the AUTH id, the audit-actor rule
    assert ev["new_data"] == {"financial_year": "2025-26", "lock": False}
    assert "Wr0ng-guess!" not in repr(events) and PIN not in repr(events)
    assert db.rows("firms")[0]["locked_financial_years"] == []        # nothing changed


def test_an_attempt_without_a_pin_is_refused_the_same_way_and_is_not_counted(monkeypatch):
    db, events = _setup(monkeypatch, pin=PIN)
    for _ in range(yls.FIRM_ATTEMPTS * 3):
        with pytest.raises(HTTPException) as e:
            _lock(db, pin=None)
        assert e.value.status_code == 403
    assert events == []                                  # nothing was put to the comparison
    assert "2025-26" in _lock(db, pin=PIN)["locked_financial_years"]     # and nothing was spent


def test_the_attempt_after_the_budget_is_a_429_even_for_the_right_pin(monkeypatch):
    db, _ = _setup(monkeypatch, pin=PIN)
    for _ in range(yls.ACTOR_ATTEMPTS):
        with pytest.raises(HTTPException) as e:
            _lock(db, pin="Wr0ng-guess!")
        assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        _lock(db, pin=PIN)
    assert e.value.status_code == 429
    wait = int(e.value.headers["Retry-After"])
    assert 1 <= wait <= yls.ATTEMPT_WINDOW_S
    assert "minute" in e.value.detail and "Nothing was changed" in e.value.detail
    assert db.rows("firms")[0]["locked_financial_years"] == []


def test_a_correct_pin_is_counted_too_so_a_flood_of_parallel_guesses_cannot_all_pass_the_check(monkeypatch):
    """The attempt is spent BEFORE the comparison and whatever its result. A limiter that counted only misses
    would let a burst all pass its check before the first miss was recorded."""
    db, _ = _setup(monkeypatch, pin=PIN)
    for _ in range(yls.ACTOR_ATTEMPTS):
        _lock(db, pin=PIN)
    with pytest.raises(HTTPException) as e:
        _lock(db, pin=PIN)
    assert e.value.status_code == 429


def test_the_window_reopens(monkeypatch):
    now = [1000.0]
    clock = lambda: now[0]  # noqa: E731
    db, _ = _setup(monkeypatch, pin=PIN)
    monkeypatch.setattr(yls, "_actor_attempts", SlidingWindowLimiter(yls.ACTOR_ATTEMPTS, yls.ATTEMPT_WINDOW_S, clock=clock))
    monkeypatch.setattr(yls, "_firm_attempts", SlidingWindowLimiter(yls.FIRM_ATTEMPTS, yls.ATTEMPT_WINDOW_S, clock=clock))
    for _ in range(yls.ACTOR_ATTEMPTS):
        with pytest.raises(HTTPException):
            _lock(db, pin="Wr0ng-guess!")
    with pytest.raises(HTTPException) as e:
        _lock(db, pin=PIN)
    assert e.value.status_code == 429
    now[0] += yls.ATTEMPT_WINDOW_S + 1
    assert "2025-26" in _lock(db, pin=PIN)["locked_financial_years"]


def test_one_person_cannot_spend_the_whole_firms_allowance_and_the_firm_has_its_own(monkeypatch):
    db, _ = _setup(monkeypatch, pin=PIN)

    def miss(actor):
        with pytest.raises(HTTPException) as e:
            _lock(db, pin="Wr0ng-guess!", actor=actor)
        return e.value.status_code

    assert [miss("A") for _ in range(yls.ACTOR_ATTEMPTS)] == [403] * yls.ACTOR_ATTEMPTS
    assert miss("A") == 429                               # refused on A's own window, without spending the firm's
    assert yls.FIRM_ATTEMPTS - yls.ACTOR_ATTEMPTS >= yls.ACTOR_ATTEMPTS
    assert [miss("B") for _ in range(yls.FIRM_ATTEMPTS - yls.ACTOR_ATTEMPTS)] == [403] * (yls.FIRM_ATTEMPTS - yls.ACTOR_ATTEMPTS)
    assert miss("C") == 429                               # the firm's window is full for everybody


def test_the_per_person_budget_is_tighter_than_the_firms():
    assert 1 <= yls.ACTOR_ATTEMPTS < yls.FIRM_ATTEMPTS
    assert yls.ATTEMPT_WINDOW_S >= 600


def test_trusted_callers_and_a_firm_with_no_pin_spend_no_attempts(monkeypatch):
    db, _ = _setup(monkeypatch, pin=PIN)
    for _ in range(yls.FIRM_ATTEMPTS * 3):
        _lock(db, pin=None, bypass_pin=True)
    db2, _ = _setup(monkeypatch)
    for _ in range(yls.FIRM_ATTEMPTS * 3):
        _lock(db2, pin=None)
    assert yls._firm_attempts.hit_or_wait(FIRM) is None   # the firm's window is untouched by all of that


def test_a_short_or_unstorable_first_pin_is_refused_and_stores_nothing(monkeypatch):
    for bad in ("123", "x" * 129, "\ud800abcd"):
        db, _ = _setup(monkeypatch)
        with pytest.raises(HTTPException) as e:
            _lock(db, pin=bad)
        assert e.value.status_code == 422, bad
        assert db.rows("firm_lock_pins") == [] and db.rows("firms")[0]["locked_financial_years"] == []


def test_a_pin_set_before_the_length_rule_still_opens_its_year(monkeypatch):
    db, _ = _setup(monkeypatch, pin="123")
    assert "2025-26" in _lock(db, pin="123")["locked_financial_years"]


def test_a_first_pin_on_an_unlock_is_adopted_as_it_always_was(monkeypatch):
    db, _ = _setup(monkeypatch)
    assert _lock(db, pin=PIN, lock=False)["pin_set"] is True
    assert len(db.rows("firm_lock_pins")) == 1


def test_an_older_form_is_rewritten_as_pbkdf2_the_first_time_it_is_used(monkeypatch):
    db, _ = _setup(monkeypatch, stored=_legacy(PIN))
    assert "2025-26" in _lock(db, pin=PIN)["locked_financial_years"]
    (row,) = db.rows("firm_lock_pins")
    assert row["pin_hash"].startswith("pbkdf2_sha256$1000$")           # the patched work factor
    assert lock_pin.verify(PIN, row["pin_hash"]).ok
    assert "2025-26" not in _lock(db, pin=PIN, lock=False)["locked_financial_years"]     # and it still opens


def test_a_failed_upgrade_never_fails_the_lock(monkeypatch):
    db, _ = _setup(monkeypatch, stored=_legacy(PIN))
    soft: list[str] = []
    monkeypatch.setattr(yls, "capture_soft_failure", lambda exc, *, operation, **ctx: soft.append(operation))

    real_table = db.table

    class Boom:
        def __init__(self, q):
            self._q = q

        def update(self, *a, **k):
            raise RuntimeError("database went away")

        def __getattr__(self, name):
            return getattr(self._q, name)

    monkeypatch.setattr(db, "table", lambda name: Boom(real_table(name)) if name == "firm_lock_pins" else real_table(name))
    assert "2025-26" in _lock(db, pin=PIN)["locked_financial_years"]
    assert soft == ["year_lock.pin_rehash"]
    assert db.rows("firm_lock_pins")[0]["pin_hash"].startswith("sha256$")      # unchanged, and still valid


def test_two_requests_setting_the_first_pin_at_once_the_loser_is_told_and_nothing_is_overwritten(monkeypatch):
    db, _ = _setup(monkeypatch)
    real_table = db.table

    class Racer:
        def __init__(self, q):
            self._q = q

        def insert(self, *a, **k):
            raise Exception('duplicate key value violates unique constraint "firm_lock_pins_pkey" (23505)')

        def __getattr__(self, name):
            return getattr(self._q, name)

    monkeypatch.setattr(db, "table", lambda name: Racer(real_table(name)) if name == "firm_lock_pins" else real_table(name))
    with pytest.raises(HTTPException) as e:
        _lock(db, pin=PIN)
    assert e.value.status_code == 409
    assert db.rows("firms")[0]["locked_financial_years"] == []


def test_another_failure_to_store_the_pin_is_not_dressed_up_as_a_conflict(monkeypatch):
    db, _ = _setup(monkeypatch)
    real_table = db.table

    class Down:
        def __init__(self, q):
            self._q = q

        def insert(self, *a, **k):
            raise RuntimeError("connection refused")

        def __getattr__(self, name):
            return getattr(self._q, name)

    monkeypatch.setattr(db, "table", lambda name: Down(real_table(name)) if name == "firm_lock_pins" else real_table(name))
    with pytest.raises(RuntimeError):
        _lock(db, pin=PIN)
    assert db.rows("firms")[0]["locked_financial_years"] == []


def test_the_service_needs_only_the_service_client(monkeypatch):
    """`firm_lock_pins` has no privilege for `authenticated`, which is what a request-scoped client is under
    USE_USER_JWT. The router hands the service a db built by the service-role provider, and the service
    reaches for no other."""
    import routers.accounting as accounting
    assert accounting._prod_db.__name__ == "service_db_or_none"
    src = (API / "services" / "year_lock_service.py").read_text(encoding="utf-8")
    for name in ("request_db", "get_supabase", "db_provider"):
        assert name not in src, name


def test_the_year_lock_route_carries_the_pin_through_and_refuses_an_oversized_one(monkeypatch):
    import routers.accounting as accounting
    db, events = _setup(monkeypatch, pin=PIN)
    monkeypatch.setattr(accounting, "_prod_db", lambda: db)
    partner = {"firm_id": FIRM, "auth_user_id": ACTOR, "id": "internal-id", "email": "p@firm.test", "role": "Partner"}

    wrong = accounting.YearLockIn(financial_year="2025-26", lock=True, pin="Wr0ng-guess!")
    with pytest.raises(HTTPException) as e:
        accounting.set_year_lock(wrong, partner)
    assert e.value.status_code == 403 and events[-1]["actor_id"] == ACTOR     # not the internal id

    right = accounting.YearLockIn(financial_year="2025-26", lock=True, pin=PIN)
    out = accounting.set_year_lock(right, partner)
    assert out["success"] is True and out["data"]["locked_financial_years"] == ["2025-26"]
    assert out["data"]["pin_set"] is True and PIN not in repr(out)

    with pytest.raises(ValidationError):
        accounting.YearLockIn(financial_year="2025-26", lock=True, pin="x" * 129)
    assert accounting.YearLockIn(financial_year="2025-26", lock=True, pin="x" * 128).pin == "x" * 128


def test_over_http_the_refusal_is_a_429_with_retry_after_and_the_sentence_the_screen_shows(monkeypatch):
    """The Lock Year screen reads `detail` off a non-2xx answer, and a client backs off on `Retry-After`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routers.accounting as accounting
    from core.auth import get_current_user

    db, _ = _setup(monkeypatch, pin=PIN)
    monkeypatch.setattr(accounting, "_prod_db", lambda: db)
    app = FastAPI()
    app.include_router(accounting.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "internal-id", "auth_user_id": ACTOR, "firm_id": FIRM, "email": "p@firm.test", "role": "Partner"}
    http = TestClient(app, raise_server_exceptions=False)

    body = {"financial_year": "2025-26", "lock": True, "pin": "Wr0ng-guess!"}
    for _ in range(yls.ACTOR_ATTEMPTS):
        r = http.post("/api/accounting/year-lock", json=body)
        assert r.status_code == 403 and r.json()["detail"] == "Incorrect lock PIN."
    r = http.post("/api/accounting/year-lock", json={**body, "pin": PIN})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "Too many attempts" in r.json()["detail"]
    assert http.post("/api/accounting/year-lock", json={**body, "pin": "x" * 129}).status_code == 422


# ── the reach: rules over the tree ───────────────────────────────────────────

_LOCK_PIN_COLUMN = re.compile(r"(?<![A-Za-z_])lock_pin(?![A-Za-z_])")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                ids.add(id(body[0].value))
    return ids


def names_the_retired_column(source: str) -> list[int]:
    """Lines whose CODE (not a docstring, not a comment) holds the string `lock_pin` as a word: a select list,
    a dict key, a `.get("lock_pin")`. The module `domain.firm.lock_pin` is an import, not a string."""
    tree = ast.parse(source)
    docs = _docstring_nodes(tree)
    return sorted(
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
        and _LOCK_PIN_COLUMN.search(n.value)
    )


def _api_sources():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).parts
        if rel[0] in {"tests", "migrations", "node_modules"} or any(p.startswith(".") for p in rel):
            continue
        yield path


def test_the_detector_sees_a_select_a_key_and_a_get_and_ignores_prose():
    assert names_the_retired_column('db.table("firms").select("locked_financial_years, lock_pin")')
    assert names_the_retired_column('update["lock_pin"] = pin')
    assert names_the_retired_column('row.get("lock_pin")')
    assert not names_the_retired_column('"""the lock_pin column"""\n# lock_pin\nfrom domain.firm import lock_pin\n')
    assert not names_the_retired_column('db.table("firm_lock_pins").select("pin_hash")')


def test_nothing_in_the_api_reads_or_writes_the_retired_column():
    scanned = 0
    offenders = []
    for path in _api_sources():
        scanned += 1
        lines = names_the_retired_column(path.read_text(encoding="utf-8"))
        if lines:
            offenders.append(f"{path.relative_to(API)}:{lines}")
    assert scanned > 200, "the scan found almost no source; it is looking in the wrong place"
    assert not offenders, (
        f"`firms.lock_pin` is retired (migration 480) and its CHECK refuses any value but NULL; the PIN lives in "
        f"firm_lock_pins behind services/year_lock_service. Code naming the column: {offenders}")


def test_the_browser_names_neither_the_retired_column_nor_the_table():
    scanned = 0
    for folder in ("app", "components", "lib"):
        for path in (WEB / folder).rglob("*"):
            if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not _LOCK_PIN_COLUMN.search(text), f"{path} names firms.lock_pin"
            assert "firm_lock_pins" not in text, f"{path} reaches for the PIN table, which the browser cannot read"
    assert scanned > 300


def test_the_pin_table_is_named_as_a_literal_and_every_read_and_write_of_it_carries_the_firm():
    """`firm_lock_pins` is keyed on the firm. A table reached through a variable is a chain the firm-scope guard
    cannot read (its budget of such chains is exact), and a chain on it with no firm filter is one firm's PIN
    read or replaced by another's request."""
    tree = ast.parse((API / "services" / "year_lock_service.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table"]
    assert calls and all(isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str) for c in calls)
    assert len([c for c in calls if c.args[0].value == "firm_lock_pins"]) == 3, \
        "the table is read once, inserted once and rewritten once"

    # And the guard that judges those chains knows the table is a firm table, so a chain on it with no firm
    # filter is a red line there and not a silent pass.
    import json
    from tests import _firm_scope_scan as S
    meta = json.loads((API / "tests" / "fixtures" / "production_schema_2026-09-03.meta.json").read_text(encoding="utf-8"))
    newer = S.firm_tables_from_newer_migrations(API / "migrations", meta["applied_through_migration"])
    assert "firm_lock_pins" in newer


_SECRET_NAMES = {"pin", "raw", "stored", "stored_hash", "computed", "expected", "digest", "salt", "pin_hash"}


def secret_comparisons(source: str) -> list[int]:
    """Lines where `==`, `!=` or `in` has an operand that names a PIN or a digest. A PIN or a digest is compared
    with hmac.compare_digest or not at all."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
            names = {n.id for part in [node.left, *node.comparators] for n in ast.walk(part) if isinstance(n, ast.Name)}
            if names & _SECRET_NAMES:
                hits.append(node.lineno)
    return hits


def test_the_comparison_detector_sees_the_spelling_it_replaced():
    assert secret_comparisons("if pin != stored_pin: pass\n")
    assert secret_comparisons("ok = computed == expected\n")
    assert secret_comparisons("ok = row['pin_hash'] == digest\n")
    assert not secret_comparisons("if scheme == PBKDF2_SCHEME: pass\nif len(parts) == 4: pass\n")


@pytest.mark.parametrize("relative", ["domain/firm/lock_pin.py", "services/year_lock_service.py"])
def test_a_pin_or_a_digest_is_compared_in_constant_time_or_not_at_all(relative):
    source = (API / relative).read_text(encoding="utf-8")
    assert not secret_comparisons(source), f"{relative}: a PIN or digest is compared with an operator"
    if relative.startswith("domain"):
        calls = [n for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "compare_digest"]
        assert calls, "the verifier no longer calls hmac.compare_digest anywhere"


def test_every_scheme_the_verifier_understands_goes_through_the_one_comparison():
    """`_same` is the comparison; both schemes' branches call it, so a third scheme added without it shows here."""
    tree = ast.parse((API / "domain" / "firm" / "lock_pin.py").read_text(encoding="utf-8"))
    verify = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "verify")
    uses = [n for n in ast.walk(verify) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_same"]
    assert len(uses) == 2
