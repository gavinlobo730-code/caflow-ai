"""
Client-assignment scope on the recurring-invoice router.

`recurring_invoices` imported no authz, so any member of a firm could read,
edit, pause, archive and RUN any client's recurring templates.

THE ONE THAT NEEDED A DIFFERENT ANSWER
    `POST /api/recurring-invoices/run` is not a list — it is a **write across
    every client in the firm**, generating draft invoices. Narrowing its output
    would be the wrong shape entirely: the drafts would already exist by then.

    So the RUN is confined instead. A Partner or Manager is firm-wide and gets
    the single firm-wide call as before; an Executive generates only for the
    clients they are assigned to. The merged response keeps the same shape for
    everyone, so no caller has to know which of the two happened.
"""
import pytest
from fastapi import HTTPException

import routers.recurring_invoices as ri

FIRM = "firm-1"
MINE, ALSO_MINE, THEIRS = "client-mine", "client-also", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "executive"}

TEMPLATES = {
    "T-MINE": {"id": "T-MINE", "client_id": MINE, "frequency": "monthly"},
    "T-THEIRS": {"id": "T-THEIRS", "client_id": THEIRS, "frequency": "monthly"},
}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(ri, "assert_client_access", _check)
    return seen


@pytest.fixture(autouse=True)
def templates(monkeypatch):
    monkeypatch.setattr(ri.recurring, "get_template",
                        lambda firm_id, tid, **_k: TEMPLATES.get(tid))


# ══════════════════════════════════════════════════════════════════════════════
# Templates
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_template_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        ri._assert_template_scope(USER, "T-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_template_resolves_to_its_client(deny):
    assert ri._assert_template_scope(USER, "T-MINE") == MINE


def test_an_unknown_template_is_the_same_404_as_a_forbidden_one(deny):
    with pytest.raises(HTTPException) as missing:
        ri._assert_template_scope(USER, "no-such-template")
    with pytest.raises(HTTPException) as hidden:
        ri._assert_template_scope(USER, "T-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


@pytest.mark.parametrize("fn,args", [
    ("get_recurring", ()),
    ("pause_recurring", ()),
    ("resume_recurring", ()),
    ("archive_recurring", ()),
    ("history_recurring", ()),
    ("run_one_recurring", ()),
])
def test_every_template_endpoint_refuses_before_it_acts(fn, args, deny, monkeypatch):
    """`/run` on a single template generates draft invoices into that client's
    books. A refusal afterwards is not a refusal."""
    reached = []
    for name in ("set_status", "template_history", "run_for_template"):
        monkeypatch.setattr(ri.recurring, name,
                            lambda *a, **k: reached.append(name) or {})
    with pytest.raises(HTTPException) as e:
        getattr(ri, fn)("T-THEIRS", *args, current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], f"{fn} reached the service despite the refusal"


def test_creating_a_template_for_another_clients_books_is_refused(deny, monkeypatch):
    created = []
    monkeypatch.setattr(ri.recurring, "create_template",
                        lambda *a, **k: created.append(a) or {})

    class _Body:
        client_id = THEIRS
        lines = []
        def model_dump(self): return {"client_id": THEIRS}

    with pytest.raises(HTTPException):
        ri.create_recurring(_Body(), current_user=USER)
    assert created == []


def test_the_template_list_is_narrowed_when_no_client_is_named(deny, monkeypatch):
    monkeypatch.setattr(ri.recurring, "list_templates",
                        lambda *a, **k: list(TEMPLATES.values()))
    monkeypatch.setattr(ri, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r["client_id"] == MINE])
    out = ri.list_recurring(client_id=None, status=None, current_user=USER)
    assert [t["id"] for t in out["data"]] == ["T-MINE"]


def test_naming_a_client_checks_it_instead_of_narrowing(deny, monkeypatch):
    monkeypatch.setattr(ri.recurring, "list_templates", lambda *a, **k: [])
    monkeypatch.setattr(ri, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        ri.list_recurring(client_id=THEIRS, status=None, current_user=USER)
    assert deny == [THEIRS]


# ══════════════════════════════════════════════════════════════════════════════
# The firm-wide generation run — a WRITE, so the run is confined, not the output
# ══════════════════════════════════════════════════════════════════════════════

def _spy(monkeypatch):
    calls = []

    def _gen(firm_id, client_id=None, as_of=None, actor=None, db=None):
        calls.append(client_id)
        return {"generated": [{"template_id": f"t-{client_id}"}],
                "skipped": [], "failed": [],
                "generated_count": 1, "skipped_count": 0, "failed_count": 0}

    monkeypatch.setattr(ri.recurring, "generate_due_recurring_invoices", _gen)
    return calls


def test_a_firmwide_role_still_runs_the_job_in_one_call(deny, monkeypatch):
    """Partner and Manager are firm-wide, so effective_client_ids returns None
    and the behaviour is identical to before — one call, client_id=None. The fix
    must not turn one query into N for the people who legitimately see everyone."""
    calls = _spy(monkeypatch)
    monkeypatch.setattr(ri, "effective_client_ids", lambda _u: None)
    ri.run_due_recurring(client_id=None, as_of=None,
                         current_user={"id": "p", "firm_id": FIRM, "role": "partner"})
    assert calls == [None]


def test_an_assigned_role_generates_only_for_its_own_clients(deny, monkeypatch):
    """Without this, anyone in the firm could create draft invoices in EVERY
    client's books by hitting one endpoint with no parameters."""
    calls = _spy(monkeypatch)
    monkeypatch.setattr(ri, "effective_client_ids", lambda _u: {ALSO_MINE, MINE})
    out = ri.run_due_recurring(client_id=None, as_of=None, current_user=USER)
    assert calls == [ALSO_MINE, MINE]          # sorted, so the order is total
    assert out["data"]["generated_count"] == 2


def test_the_merged_response_keeps_the_original_shape(deny, monkeypatch):
    """Callers must not have to know which of the two branches ran."""
    _spy(monkeypatch)
    monkeypatch.setattr(ri, "effective_client_ids", lambda _u: {MINE})
    out = ri.run_due_recurring(client_id=None, as_of=None, current_user=USER)["data"]
    assert set(out) == {"generated", "skipped", "failed",
                        "generated_count", "skipped_count", "failed_count"}
    assert out["generated_count"] == len(out["generated"])


def test_naming_a_client_you_are_not_on_refuses_the_run_outright(deny, monkeypatch):
    calls = _spy(monkeypatch)
    with pytest.raises(HTTPException) as e:
        ri.run_due_recurring(client_id=THEIRS, as_of=None, current_user=USER)
    assert e.value.status_code == 404
    assert calls == [], "the generation job ran despite the refusal"


def test_naming_a_client_you_are_on_runs_exactly_that_one(deny, monkeypatch):
    calls = _spy(monkeypatch)
    ri.run_due_recurring(client_id=MINE, as_of=None, current_user=USER)
    assert calls == [MINE]


def test_an_assigned_role_with_no_clients_generates_nothing(deny, monkeypatch):
    """An empty assignment set means no books to write into — not "all of them",
    which is what an unguarded `client_id=None` would have meant."""
    calls = _spy(monkeypatch)
    monkeypatch.setattr(ri, "effective_client_ids", lambda _u: set())
    out = ri.run_due_recurring(client_id=None, as_of=None, current_user=USER)
    assert calls == []
    assert out["data"]["generated_count"] == 0
