"""
A timeline note is written in the shape `timeline_service.log` accepts.

WHAT WAS WRONG
    Six call sites wrote

        timeline_service.log(client_id=..., category=..., action="...",
                             description=..., severity=..., metadata={...})

    against a function whose parameters are (client_id, category, TITLE,
    description, severity, firm_id, ...) and which has no `action` and no
    `metadata`. Every one of them raised TypeError at the call — before
    log_timeline_event's own "never raises" guard could see anything — and
    what that did depended only on where the call sat:

      routers/tally_migration.py  every LIVE Tally import answered 500, and the
                                  background import it had just queued never
                                  ran (a background task rides on the response)
      routers/form_26as.py        every successful 26AS reconciliation was
                                  SAVED and then reported to the CA as a 500;
                                  "mark 26AS uploaded" never once answered 200
      routers/xbrl_engine.py      a CLEAN package could not be validated, and
                                  every partner review was SAVED and then
                                  reported as a 500
      form26as_service            swallowed by its own except — the mismatch
                                  note silently never reached the timeline

    Not one of them was caught, because a call's shape is not checked until
    the call runs, and the mock suite never ran the branches they sat in.

    They also omitted `firm_id`, which log() defaults to "" — and
    client_timeline_events.firm_id is a NOT NULL uuid, so even a well-shaped
    call would have been refused by the database and the refusal swallowed.

THE RULE, STATED ONCE
    Every call to `timeline_service.log` or `log_timeline_event` in apps/api
    must BIND to the function's real signature — checked by `inspect`, not by a
    list of forbidden keywords, so a parameter renamed tomorrow fails the same
    way. And the fixed endpoints are each CALLED below, because a scan cannot
    tell whether the branch a call sits in is ever reached.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from services import timeline_service as tl
from services.timeline_service import TimelineService

API_ROOT = Path(__file__).resolve().parents[1]
_SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules"}
_METHODS = {name: inspect.signature(getattr(TimelineService, name))
            for name in ("log", "log_timeline_event")}


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "timeline_service"):
            yield node


def _problem(node: ast.Call) -> str | None:
    """Why this call cannot bind, or None. A call spreading *args/**kwargs
    cannot be judged statically and is not guessed at."""
    if any(isinstance(a, ast.Starred) for a in node.args) or any(
            k.arg is None for k in node.keywords):
        return None
    sig = _METHODS[node.func.attr]
    try:
        sig.bind(None, *([None] * len(node.args)),
                 **{k.arg: None for k in node.keywords})
    except TypeError as exc:
        return str(exc)
    return None


def _scan() -> tuple[int, list[str]]:
    seen, bad = 0, []
    for path in API_ROOT.rglob("*.py"):
        if set(path.relative_to(API_ROOT).parts) & _SKIP:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _calls(tree):
            seen += 1
            why = _problem(node)
            if why:
                bad.append(f"{path.relative_to(API_ROOT)}:{node.lineno}  {why}")
    return seen, bad


def test_every_timeline_call_binds_to_the_real_signature():
    seen, bad = _scan()
    assert seen >= 90, f"only {seen} timeline calls found — the scan has gone blind"
    assert not bad, "timeline calls that raise TypeError when reached:\n  " + "\n  ".join(bad)


def test_the_scan_catches_the_shape_that_shipped():
    """Negative control: the exact call that broke the Tally import."""
    node = next(_calls(ast.parse(
        'timeline_service.log(client_id="", category="accounting", '
        'action="tally_import_started", description="x", severity="info", '
        'metadata={"job_id": "j"})')))
    assert _problem(node), "the scan passes the call that shipped the 500"


# ── The fixed endpoints, called ──────────────────────────────────────────────

FIRM = "firm-1"
PARTNER = {"id": "u-1", "auth_user_id": "a-1", "firm_id": FIRM,
           "email": "p@f.test", "role": "Partner"}


@pytest.fixture
def notes():
    tl.MOCK_TIMELINE_EVENTS.clear()
    yield tl.MOCK_TIMELINE_EVENTS
    tl.MOCK_TIMELINE_EVENTS.clear()


@pytest.fixture
def xbrl(monkeypatch):
    import domain.income_tax.xbrl_service as xs
    import routers.xbrl_engine as xr
    monkeypatch.setattr(xs, "_USE_MOCK", True)
    monkeypatch.setattr(xr, "can_access_client", lambda user, cid: True)
    monkeypatch.setitem(xs._MOCK_PACKAGES, "pkg-1",
                        {"id": "pkg-1", "firm_id": FIRM, "client_id": "client-1",
                         "financial_year": "2025-26", "status": "draft"})
    return xs, xr


def test_a_clean_xbrl_package_can_be_validated(xbrl, notes, monkeypatch):
    xs, xr = xbrl
    monkeypatch.setattr(xs, "validate_xbrl_package", lambda firm_id, pid: {
        "validation_errors": [], "missing_tags": [], "financial_year": "2025-26"})

    resp = xr.validate_package("pkg-1", current_user=PARTNER)

    assert resp["success"] is True
    assert [(n["client_id"], n["firm_id"], n["entity_id"]) for n in notes] == [
        ("client-1", FIRM, "pkg-1")]


def test_an_xbrl_review_that_was_saved_is_reported_as_saved(xbrl, notes):
    _xs, xr = xbrl
    resp = xr.review_package("pkg-1", current_user=PARTNER)

    assert resp["success"] is True
    assert resp["data"]["status"] == "reviewed"
    assert notes[0]["title"] == "XBRL package reviewed" and notes[0]["firm_id"] == FIRM


@pytest.fixture
def form26as(monkeypatch):
    import domain.income_tax.form26as_service as fs
    import routers.form_26as as fr
    monkeypatch.setattr(fs, "_USE_MOCK", True)
    monkeypatch.setattr(fr, "can_access_client", lambda user, cid: True)
    monkeypatch.setattr(fr, "assert_client_access", lambda user, cid: None)
    monkeypatch.setitem(fs._MOCK_UPLOADS, "up-1",
                        {"id": "up-1", "firm_id": FIRM, "client_id": "client-1",
                         "financial_year": "2025-26", "parse_status": "parsed"})
    return fs, fr


def test_marking_26as_uploaded_answers_and_notes_it(form26as, notes):
    _fs, fr = form26as
    resp = fr.mark_26as_uploaded("up-1", current_user=PARTNER)

    assert resp["success"] is True
    assert notes[0]["title"] == "Form 26AS uploaded"
    assert (notes[0]["firm_id"], notes[0]["entity_id"]) == (FIRM, "up-1")


def test_a_saved_26as_reconciliation_is_reported_as_saved(form26as, notes, monkeypatch):
    fs, fr = form26as
    monkeypatch.setattr(fs, "list_uploads", lambda firm, client, fy: [fs._MOCK_UPLOADS["up-1"]])
    monkeypatch.setattr(fs, "run_reconciliation", lambda **kw: {
        "id": "rec-1", "matched_count": 3, "mismatch_count": 0,
        "missing_in_books_count": 0, "not_in_26as_count": 0})

    resp = fr.run_reconciliation(
        fr.RunReconRequest(client_id="client-1", financial_year="2025-26"),
        current_user=PARTNER)

    assert resp["success"] is True
    assert notes[0]["title"] == "26AS reconciled" and notes[0]["severity"] == "success"
    assert (notes[0]["firm_id"], notes[0]["entity_id"]) == (FIRM, "rec-1")


def test_a_26as_mismatch_reaches_the_timeline(form26as, notes):
    fs, _fr = form26as
    fs._trigger_26as_ai_insight(FIRM, "client-1", "2025-26", 150_000, "rec-1", 50_000)

    assert len(notes) == 1, "the note was swallowed by the function's own except"
    n = notes[0]
    assert (n["firm_id"], n["client_id"], n["entity_id"]) == (FIRM, "client-1", "rec-1")
    assert n["amount_paise"] == 150_000 and n["severity"] == "warning"
