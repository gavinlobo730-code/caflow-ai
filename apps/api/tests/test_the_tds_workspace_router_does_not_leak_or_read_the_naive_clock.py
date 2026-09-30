"""
The TDS workspace router does not hand a caught exception to the caller, does not
read the naive clock, and its rate registry has one key per entry (tds_income_tax-34).

WHAT WAS WRONG
    * Twelve handlers ended `except Exception as e: return api_response(False,
      None, str(e))`. For a PostgREST failure `str(e)` is the error dict — table,
      column, constraint, hint — delivered inside an HTTP 200. Only some of the
      twelve logged the cause.
    * `datetime.utcnow()` stamped five records: deprecated from Python 3.12 and
      naive, so the value only looks like UTC by convention.
    * `domain/tds/section_rates.py` declared `"194J(B)"` twice in one dict
      literal. Python keeps the last, so nothing computed differently — but a
      second copy is exactly where the next edit lands on the wrong one.
    * A computation snapshot's version is read and then written, so two saves at
      the same moment collided on UNIQUE (firm_id, client_id, financial_year,
      version) and the loser was told to press Save again.

WHAT IS ASSERTED — the rules, not a spelling of them
    * no except-handler in the router passes the caught exception (as `str(e)`,
      `repr(e)`, an f-string or the bare name) into a response or a detail;
    * every one of the twelve sites answers through `_could_not`, which names the
      ACTION and carries none of the exception's own text, for a dict-shaped
      database error and for an arbitrary one, and logs the cause;
    * nothing in the router calls a `utcnow`;
    * no dict literal in the rate registry repeats a key;
    * two snapshot saves that read the same maximum both succeed, with different
      versions; a failure that is NOT a unique violation is not retried.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

import core.supabase_client as supabase_client
import domain.income_tax.computation_workspace as cw
import routers.tds_workspace as tw

API = Path(__file__).resolve().parents[1]
ROUTER = API / "routers" / "tds_workspace.py"
SECTION_RATES = API / "domain" / "tds" / "section_rates.py"

SECRET = "postgres://svc:hunter2@10.0.0.7:6543/practice"
USER = {"id": "u1", "auth_user_id": "a1", "firm_id": "F-leak", "role": "Partner",
        "email": "ca@f.test"}


class _PgError(Exception):
    """The shape supabase-py raises: one dict argument carrying the detail."""
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message,
                          "details": SECRET, "hint": None})


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


# ── The rule, stated over the source ─────────────────────────────────────────

def _mentions(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """`except Exception` / `BaseException` / bare. A NARROW handler — the
    `except ValueError` that turns the TDS engine's own refusal into a 422 —
    catches a type whose message this codebase wrote for a human; a broad one
    catches whatever the database driver or a bug raised, which it did not."""
    t = handler.type
    return t is None or (isinstance(t, ast.Name) and t.id in ("Exception", "BaseException"))


def _handlers_that_answer_with_their_exception(tree: ast.AST) -> list[int]:
    """Line numbers of BROAD except-handlers whose exception variable reaches a
    RETURN or a raised HTTPException — any spelling: str(e), repr(e), an
    f-string, the bare name. Logging it is fine and is not matched."""
    bad: list[int] = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name or not _is_broad(handler):
            continue
        for stmt in ast.walk(handler):
            if isinstance(stmt, ast.Return) and stmt.value is not None \
                    and _mentions(stmt.value, handler.name):
                # `return _could_not(e, "...")` passes the exception to the one
                # function that decides what may be said about it.
                call = stmt.value
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                        and call.func.id == "_could_not":
                    continue
                bad.append(stmt.lineno)
            if isinstance(stmt, ast.Raise) and stmt.exc is not None \
                    and _mentions(stmt.exc, handler.name):
                bad.append(stmt.lineno)
    return bad


def test_no_handler_in_the_router_answers_with_its_own_exception():
    assert _handlers_that_answer_with_their_exception(_tree(ROUTER)) == []


def test_the_twelve_sites_answer_through_the_one_function():
    """A vacuity floor: the scan above passes on a router with no handlers."""
    src = ROUTER.read_text(encoding="utf-8")
    assert src.count("return _could_not(e,") >= 12


def test_the_rule_actually_detects_the_old_shape():
    """Negative control for the scan itself, on the exact line that was removed."""
    old = ast.parse(
        "def h():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        return api_response(False, None, str(e))\n")
    assert _handlers_that_answer_with_their_exception(old) == [5]
    fstring = ast.parse(
        "def h():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        return api_response(False, None, f'failed: {e}')\n")
    assert _handlers_that_answer_with_their_exception(fstring) == [5]


def test_a_narrow_handler_that_words_a_domain_refusal_is_not_the_rule():
    narrow = ast.parse(
        "def h():\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as ve:\n"
        "        raise HTTPException(422, detail=str(ve))\n")
    assert _handlers_that_answer_with_their_exception(narrow) == []


def test_nothing_in_the_router_reads_the_naive_clock():
    offenders = [n.lineno for n in ast.walk(_tree(ROUTER))
                 if isinstance(n, ast.Attribute) and n.attr == "utcnow"]
    assert offenders == []


def _duplicate_keys(tree: ast.AST) -> list[tuple[int, object]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: set = set()
        for key in node.keys:
            if isinstance(key, ast.Constant):
                if key.value in seen:
                    found.append((key.lineno, key.value))
                seen.add(key.value)
    return found


def test_no_dict_in_the_rate_registry_repeats_a_key():
    assert _duplicate_keys(_tree(SECTION_RATES)) == []


def test_the_key_scan_detects_a_repeat():
    assert _duplicate_keys(ast.parse('{"a": 1, "b": 2, "a": 1}')) == [(1, "a")]


def test_the_194j_b_limb_still_carries_the_professional_fee_figures():
    """Removing the repeated key changed no figure: the surviving entry is the
    professional-fee limb of s.194J — 10%, both limbs ₹50,000 — under its
    parent, in every year the registry holds."""
    from domain.tds import section_rates as sr
    for fy, year in sr.TDS_RATES_BY_FY.items():
        rule = year.sections["194J(B)"]
        assert (rule.individual_rate_bps, rule.company_rate_bps) == (1000, 1000), fy
        assert rule.parent_section == "194J", fy
        assert rule.single_threshold_paise == 50_000_00, fy
        assert rule.aggregate_threshold_paise == 50_000_00, fy
    assert sr.parent_of("194J(B)") == "194J"


# ── The behaviour, through the real handlers ─────────────────────────────────

def _boom(*_a, **_k):
    raise _PgError("XX000", f"connection to {SECRET} refused")


def _wire(monkeypatch, name):
    """Make ONE handler's body raise, however that handler reaches the database."""
    monkeypatch.setattr(tw, "assert_client_access", lambda *_: None)
    monkeypatch.setattr(tw, "can_access_client", lambda *_: True)
    if name in ("create_challan", ):
        monkeypatch.setattr(tw.period_validation_service, "validate_posting_date", _boom)
    elif name == "create_certificate":
        monkeypatch.setattr(tw.TDSValidator, "validate_pan", staticmethod(_boom))
    elif name == "upload_form26as":
        monkeypatch.setattr(tw, "_register_rows_for_fy", _boom)
    elif name == "deposit_due":
        monkeypatch.setattr(tw.deposit_due_rules, "build", _boom)
    else:
        monkeypatch.setattr(tw, "_USE_MOCK", False)
        monkeypatch.setattr(supabase_client, "get_supabase", _boom)


def _call(name):
    fn = getattr(tw, name)
    c = "C-leak"
    calls = {
        "tds_dashboard": lambda: fn(client_id=c, current_user=USER),
        "list_deductions": lambda: fn(client_id=c, quarter=None, limit=50, offset=0, current_user=USER),
        "deposit_due": lambda: fn(client_id=c, month="2026-06", current_user=USER),
        "list_challans": lambda: fn(client_id=c, from_date=None, to_date=None, limit=50, offset=0, current_user=USER),
        "create_challan": lambda: fn(tw.CreateChallanRequest(
            client_id=c, bsr_code="0510308", challan_date="2026-01-05", amount_paise=100000,
            challan_no="12345", section="194A", financial_year="2025-26", quarter="Q3"),
            current_user=USER),
        "get_challan": lambda: fn("ch-1", current_user=USER),
        "list_returns": lambda: fn(client_id=c, limit=50, offset=0, current_user=USER),
        "update_return_status": lambda: fn("r-1", tw.UpdateReturnStatusRequest(status="pending"),
                                           current_user=USER),
        "list_certificates": lambda: fn(client_id=c, limit=50, offset=0, current_user=USER),
        "create_certificate": lambda: fn(tw.CreateCertificateRequest(
            client_id=c, deductee_pan="ABCDE1234F", deductee_name="X", financial_year="2025-26",
            certificate_type="Form 16A", tds_amount_paise=1000, section="194A"),
            current_user=USER),
        "upload_form26as": lambda: fn(tw.Form26ASUploadRequest(client_id=c, financial_year="2025-26"),
                                      current_user=USER),
        "get_form26as": lambda: fn("u-1", current_user=USER),
    }
    return calls[name]()


SITES = {
    "tds_dashboard": "load the TDS dashboard",
    "list_deductions": "list the TDS deductions",
    "deposit_due": "build the TDS deposit worksheet",
    "list_challans": "list the TDS challans",
    "create_challan": "record the TDS challan",
    "get_challan": "read the TDS challan",
    "list_returns": "list the TDS returns",
    "update_return_status": "update the TDS return status",
    "list_certificates": "list the TDS certificates",
    "create_certificate": "record the TDS certificate",
    "upload_form26as": "reconcile the Form 26AS upload",
    "get_form26as": "read the Form 26AS reconciliation",
}


@pytest.mark.parametrize("name,action", list(SITES.items()), ids=list(SITES))
def test_a_failing_handler_names_the_action_and_carries_none_of_the_error(
        name, action, monkeypatch, caplog):
    _wire(monkeypatch, name)
    with caplog.at_level(logging.ERROR, logger="caflow.tds_workspace"):
        out = _call(name)
    assert out["success"] is False
    said = str(out["error"])
    assert action in said, said
    for leaked in (SECRET, "hunter2", "10.0.0.7", "{'code'", "details"):
        assert leaked not in said, f"{name} handed '{leaked}' to the caller: {said}"
    # The cause is still somewhere a developer can read it.
    assert any(SECRET in (r.getMessage() + str(r.exc_info)) or r.exc_info
               for r in caplog.records), f"{name} logged nothing"


def test_a_database_refusal_a_ca_can_act_on_is_still_worded(monkeypatch):
    """`_could_not` speaks through core.exceptions.unhandled_failure, so a
    duplicate is a sentence about a duplicate and not the generic one."""
    monkeypatch.setattr(tw, "assert_client_access", lambda *_: None)

    def dup(*_a, **_k):
        raise _PgError("23505", 'duplicate key value violates unique constraint "tds_challans_key"')
    monkeypatch.setattr(tw.period_validation_service, "validate_posting_date", dup)
    out = _call("create_challan")
    assert out["success"] is False
    assert "already exists" in out["error"]
    assert SECRET not in out["error"] and "{'code'" not in out["error"]


# ── The snapshot version race ────────────────────────────────────────────────

class _Table:
    """A table that enforces the unique key migration 319 declares."""

    def __init__(self, db):
        self.db = db
        self._op = None
        self._payload = None

    def select(self, *_):
        self._op = "select"
        return self

    def eq(self, *_):
        return self

    def insert(self, row):
        self._op, self._payload = "insert", row
        return self

    def execute(self):
        db = self.db
        if self._op == "select":
            db.reads += 1
            snapshot = [{"version": r["version"]} for r in db.rows]
            # A concurrent saver lands its row AFTER we read and BEFORE we write.
            if db.reads == 1 and db.racer is not None:
                db.rows.append({**self._racer_row()})
            return _Res(snapshot)
        db.insert_attempts += 1
        if db.fail_with is not None:
            raise db.fail_with
        key = (self._payload["firm_id"], self._payload["client_id"],
               self._payload["financial_year"], self._payload["version"])
        if any((r["firm_id"], r["client_id"], r["financial_year"], r["version"]) == key
               for r in db.rows):
            raise _PgError("23505", 'duplicate key value violates unique constraint '
                                    '"tax_computation_snapshots_firm_id_client_id_financial_year__key"')
        db.rows.append(dict(self._payload))
        return _Res([dict(self._payload)])

    def _racer_row(self):
        return dict(self.db.racer)


class _Res:
    def __init__(self, data):
        self.data = data


class _FakeDb:
    def __init__(self, racer=None, fail_with=None, rows=None):
        self.rows = list(rows or [])
        self.racer = racer
        self.fail_with = fail_with
        self.reads = 0
        self.insert_attempts = 0

    def table(self, name):
        assert name == "tax_computation_snapshots"
        return _Table(self)


def _save(db, monkeypatch, **over):
    monkeypatch.setattr(cw, "_USE_MOCK", False)
    monkeypatch.setattr(cw, "_supabase", lambda: db)
    args = dict(firm_id="F1", client_id="C1", financial_year="2025-26",
                assessment_year="2026-27", regime="new", income={},
                computation_result={}, created_by="u1")
    args.update(over)
    return cw.save_computation_snapshot(**args)


def _existing(version):
    return {"firm_id": "F1", "client_id": "C1", "financial_year": "2025-26",
            "version": version}


def test_two_saves_at_the_same_moment_both_succeed_with_different_versions(monkeypatch):
    # One version already exists. Our save reads "max = 1", then another save
    # lands version 2 before we write — the unique key refuses our version 2.
    db = _FakeDb(rows=[_existing(1)], racer=_existing(2))
    snap = _save(db, monkeypatch)
    versions = sorted(r["version"] for r in db.rows)
    assert versions == [1, 2, 3], versions
    assert snap["version"] == 3
    assert db.insert_attempts == 2


def test_an_uncontended_save_writes_once(monkeypatch):
    db = _FakeDb(rows=[_existing(1)])
    snap = _save(db, monkeypatch)
    assert snap["version"] == 2 and db.insert_attempts == 1


def test_a_failure_that_is_not_a_unique_violation_is_not_retried(monkeypatch):
    db = _FakeDb(fail_with=_PgError("42501", "permission denied for table tax_computation_snapshots"))
    with pytest.raises(_PgError):
        _save(db, monkeypatch)
    assert db.insert_attempts == 1


def test_a_save_that_loses_every_race_hands_the_violation_to_the_caller(monkeypatch):
    db = _FakeDb(fail_with=_PgError("23505", "duplicate key value violates unique constraint"))
    with pytest.raises(_PgError) as e:
        _save(db, monkeypatch)
    assert e.value.args[0]["code"] == "23505"
    assert db.insert_attempts == cw._SNAPSHOT_VERSION_ATTEMPTS
