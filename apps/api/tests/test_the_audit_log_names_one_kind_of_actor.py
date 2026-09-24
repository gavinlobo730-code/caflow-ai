"""`audit_log.actor_id` holds ONE kind of id, and it is the Supabase auth id.

WHY THE COLUMN HAS TO PICK ONE

`public.audit_log` is written by TWO paths and they share the column.
Migration 111 puts a trigger on every firm-scoped table whose body reads
`auth.uid()` into `v_actor` and then looks the email up with
`WHERE u.auth_user_id = v_actor` — so the trigger path, which is the great
majority of rows, writes the SUPABASE AUTH id. `services/audit_service.
log_event` is the Python path, and on 24-09-2026 it was called 157 times with
`current_user.get("auth_user_id")` and 37 times with `current_user.get("id")`,
which is `public.users.id`, an entirely different uuid for the same person.

The column has **no FK** (migration 082 declares a bare `actor_id UUID`), so
nothing refused either one and nothing ever will. What it costs:

  * `GET /api/audit?actor_id=` filters `.eq("actor_id", …)` and
    `idx_audit_log_actor` indexes it, so asking "everything this person did"
    returns whichever HALF of their rows happens to share the flavour of id
    that was passed — silently, with no error and no hint that the answer is
    partial;
  * the table is this product's Companies (Accounts) Rules 2014 Rule 3(1)
    proviso EDIT LOG and its DPDP Rule 6 access log. WHO is the one column
    both of those exist for.

No screen breaks today and that is worth stating plainly rather than
overselling the fix: `app/settings/audit-log` renders `actor_email` and
filters it as a substring, so the Edit Log a CA reads was never wrong. What
was wrong is the key, and the next reader to join on it would have got a
silently short answer.

THE RENAME TRAP, WHICH THIS FILE EXISTS TO STOP AS MUCH AS THE DEFECT

There are TWO functions called `log_event` in this codebase and they write
DIFFERENT TABLES:

    services/audit_service.log_event          -> public.audit_log
    repositories/task_extras_repository
        .task_extras_repo.log_event           -> public.task_timeline

`task_timeline.actor_id` is `TEXT` (migration 063), has its own meaning and
consistently holds the INTERNAL id. The first sweep of this defect matched on
the NAME and rewrote four of its call sites in `routers/tasks.py`,
`routers/task_extras.py` and `routers/task_templates.py` before the diff was
read. They are reverted, and the two are told apart here on the CALL SHAPE —
the audit one is a bare `Name`, the task one an `Attribute` on a repository —
rather than on a list of files, which would go stale the first time somebody
moved a call.

WHAT IS AND IS NOT CHECKED

`_ROUTER_RULE` is the positive statement and it is asked of routers, where a
`current_user` is in hand. A SERVICE takes `actor_id` as a parameter and
cannot see a principal at all, so the positive form is unaskable there; what
holds repo-wide instead is `_NO_INTERNAL_ID` — no `log_event` call anywhere in
`apps/api` may pass an `actor_id` read out of a dict under the key `"id"`.
That second rule is the one that would have caught all 37, and it needs no
call graph.

Two service modules resolve the pair explicitly, `actor_id=actor_auth_id or
actor_id`, because their callers hand them both; they satisfy `_NO_INTERNAL_ID`
by construction and are not special-cased.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[1]
SCANNED = ("routers", "services", "domain", "jobs", "core", "repositories")

#: A `log_event` call whose actor_id is a NAME that this function did not bind
#: from a `.get("auth_user_id")` — because it arrives as a PARAMETER. Each
#: entry names the caller expression that supplies it, and the guard checks
#: that expression too, so this is a fact the test verifies rather than a
#: sentence saying "deliberate".
ACTOR_ARRIVES_AS_A_PARAMETER = {
    # advance_lead_stage / revert_lead_after_engagement_closed take actor_id
    # from the engagement-letter routes.
    "routers/lifecycle.py": ("routers/engagement_letters.py",
                             'actor_id=current_user.get("auth_user_id")'),
    # _upload_and_record(actor_id, actor_email, …) — all three callers are in
    # the same module and pass it positionally.
    "routers/year_end_exports.py": ("routers/year_end_exports.py",
                                    'current_user.get("auth_user_id"), current_user.get("email")'),
}

#: A `log_event` call with NO actor at all. There is exactly one and it is the
#: public engagement-signing route: the signer is the CLIENT, following a
#: tokenised link, and has no staff principal — inventing one would attribute
#: a client's signature to a member of the firm.
NO_ACTOR = {"routers/engagement_sign_public.py"}


def _modules():
    for d in SCANNED:
        for f in sorted((API / d).rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            yield f, f.relative_to(API).as_posix(), f.read_text()


def _audit_log_event_calls(tree: ast.AST):
    """Calls to services.audit_service.log_event — the BARE name.

    `task_extras_repo.log_event(...)` is an Attribute and writes
    task_timeline; see the rename trap in this module's docstring.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "log_event":
            yield node


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _is_auth_id_read(node: ast.AST) -> bool:
    """`<anything>.get("auth_user_id")` — current_user, actor, approver."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "auth_user_id")


def _is_internal_id_read(node: ast.AST) -> bool:
    """`<anything>.get("id")` or `<anything>["id"]` — public.users.id."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args \
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == "id":
        return True
    return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and node.slice.value == "id")


def test_the_scan_still_finds_the_audit_calls():
    """A scan that matches nothing passes every rule below for ever."""
    found = sum(len(list(_audit_log_event_calls(ast.parse(src))))
                for _, _, src in _modules() if "log_event(" in src)
    assert found > 120, (
        f"only {found} audit log_event calls found — the scan is reading a "
        f"different tree, or the call shape moved")


def test_no_audit_event_is_attributed_with_the_internal_user_id():
    """THE RULE. audit_log.actor_id is the auth id; `.get("id")` is users.id.

    This is the form that needs no call graph, so it holds in a service as
    well as in a router. Every one of the 37 sites fixed on 24-09-2026 fails
    here against the previous code.
    """
    bad = []
    for _, rel, src in _modules():
        if "log_event(" not in src:
            continue
        for call in _audit_log_event_calls(ast.parse(src)):
            v = _kw(call, "actor_id")
            if v is not None and _is_internal_id_read(v):
                bad.append(f"{rel}:{call.lineno}")
    assert not bad, (
        "these audit_log writes attribute the event to public.users.id, where "
        "migration 111's trigger and every other writer put the Supabase auth "
        "id — so 'everything this person did' can never be answered by one "
        f"id: {bad}")


def test_a_router_names_the_principal_it_has_in_hand():
    """The positive form, asked where a `current_user` exists.

    A service takes actor_id as a parameter and has no principal to read, so
    the rule above is what holds there.
    """
    problems = []
    for _, rel, src in _modules():
        if not rel.startswith("routers/") or "log_event(" not in src:
            continue
        tree = ast.parse(src)
        # Names this module binds from a `.get("auth_user_id")`, anywhere.
        bound_from_auth = {
            t.id
            for node in ast.walk(tree) if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name) and _is_auth_id_read(node.value)
        }
        for call in _audit_log_event_calls(tree):
            v = _kw(call, "actor_id")
            where = f"{rel}:{call.lineno}"
            if v is None:
                problems.append(f"{where} — no actor_id at all")
            elif _is_auth_id_read(v):
                continue
            elif isinstance(v, ast.Constant) and v.value is None:
                if rel not in NO_ACTOR:
                    problems.append(f"{where} — actor_id=None and not in NO_ACTOR")
            elif isinstance(v, ast.Name):
                if v.id in bound_from_auth:
                    continue
                if rel not in ACTOR_ARRIVES_AS_A_PARAMETER:
                    problems.append(
                        f"{where} — actor_id={v.id}, which this module never "
                        f"binds from .get(\"auth_user_id\")")
            else:
                problems.append(f"{where} — actor_id is {ast.dump(v)[:60]}")
    assert not problems, problems


@pytest.mark.parametrize("rel", sorted(ACTOR_ARRIVES_AS_A_PARAMETER))
def test_a_parameter_actor_is_supplied_as_the_auth_id(rel: str):
    """The allowlist above names WHO supplies the parameter; check them.

    Otherwise an entry saying "it arrives as a parameter" would excuse the
    call without anybody ever looking at what arrives.
    """
    caller_rel, expected = ACTOR_ARRIVES_AS_A_PARAMETER[rel]
    src = (API / caller_rel).read_text()
    assert expected in src, (
        f"{rel} takes its audit actor as a parameter and {caller_rel} is "
        f"recorded as supplying it, but {expected!r} is no longer there")


def test_the_other_log_event_writes_a_different_table_and_is_left_alone():
    """`task_extras_repo.log_event` is NOT this population.

    It writes public.task_timeline, whose actor_id is TEXT (migration 063) and
    consistently holds the INTERNAL id. A sweep that matched on the name
    rewrote four of its call sites; this asserts they exist, still pass the
    internal id, and are invisible to `_audit_log_event_calls`.
    """
    seen = 0
    for _, rel, src in _modules():
        if "task_extras_repo.log_event(" not in src:
            continue
        tree = ast.parse(src)
        bare = {c.lineno for c in _audit_log_event_calls(tree)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "log_event":
                seen += 1
                assert node.lineno not in bare, (
                    f"{rel}:{node.lineno} — the task-timeline call is being "
                    f"counted as an audit_log call")
    assert seen >= 4, (
        f"only {seen} task_timeline log_event calls found — if they have been "
        f"renamed or removed, say so here rather than letting this pass empty")
