"""Every notification TYPE the code writes is one `notifications.type` accepts.

WHY THIS IS A RULE AND NOT A LIST
    `notifications.type` is CHECKed, and the CHECK was frozen at six values from
    migration 004 until migration 122 found that "every other notification type
    in notification_service.py, escalation_service.py and
    compliance_obligation_service.py would cause a CHECK constraint violation →
    silent write failure in production". 157 widened it again for 'workflow'. Each
    time the writer lived inside a `try/except: pass` — notifications are
    best-effort by design — so the failure was total and silent, and each time it
    was found by somebody reading a table that was empty.

    A hand-kept list of types would be the same mistake with a longer fuse, so
    this derives BOTH sides: the accepted set from the LAST migration that defines
    the constraint (found by number, as migration 450's own header says to), and
    the written set from the AST of every `notifications_repo.create({...})` and
    `.table("notifications").insert({...})` under apps/api.

WHAT IT HOLDS
    * every literal type the code writes is in the constraint, except the entries
      in KNOWN_NOT_ACCEPTED, which are findings recorded rather than fixed here;
    * the constants the new portal path writes through are in the constraint;
    * KNOWN_NOT_ACCEPTED is an equality, not a ceiling: fixing one without
      deleting its entry fails, so the list can only shrink.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from domain import practice_notices as rules

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"

#: Types the code writes that the CHECK refuses, each with what is wrong. These
#: are FINDINGS that are not part of any change that records them; deleting an
#: entry is how a fix is acknowledged.
KNOWN_NOT_ACCEPTED: dict[str, str] = {
    "invoice_overdue": (
        "services/invoice_lifecycle_service._notify_overdue writes this type AND a "
        "`message` key — the table has `body` (NOT NULL) and no `message` — so the "
        "overdue-invoice notice to the Partner has never been written. Both halves "
        "are wrong and the insert is inside a broad except."),
}


def _latest_definition() -> tuple[str, set[str]]:
    """(migration name, the accepted values) from the highest-numbered migration
    that ADDs the constraint."""
    best_num, best_name, best_body = -1, "", ""
    for path in MIGRATIONS.glob("*.sql"):
        if "rollback" in path.name or path.name.startswith("_"):
            continue
        sql = path.read_text(encoding="utf-8")
        sql = re.sub(r"--[^\n]*", "", sql)
        for m in re.finditer(
                r"add\s+constraint\s+notifications_type_check\s+check\s*\(\s*type\s+in\s*\((.*?)\)\s*\)\s*;",
                sql, re.I | re.S):
            num = int(path.name.split("_", 1)[0])
            if num > best_num:
                best_num, best_name, best_body = num, path.name, m.group(1)
    assert best_num >= 0, "no migration defines notifications_type_check"
    return best_name, set(re.findall(r"'([a-z_]+)'", best_body))


def _written_types() -> dict[str, list[str]]:
    """literal type -> the files that write it."""
    found: dict[str, list[str]] = {}
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.args[0], ast.Dict)
                    and isinstance(node.func, ast.Attribute)):
                continue
            target = node.func.value
            is_repo_create = (node.func.attr == "create"
                              and isinstance(target, ast.Name) and target.id == "notifications_repo")
            is_table_insert = (node.func.attr == "insert" and isinstance(target, ast.Call)
                               and isinstance(target.func, ast.Attribute) and target.func.attr == "table"
                               and target.args and isinstance(target.args[0], ast.Constant)
                               and target.args[0].value == "notifications")
            if not (is_repo_create or is_table_insert):
                continue
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if (isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    found.setdefault(v.value, []).append(rel)
    return found


def test_the_scan_reads_the_constraint_and_finds_writers():
    name, accepted = _latest_definition()
    assert {"task_assigned", "compliance_due", "workflow"} <= accepted, (name, accepted)
    written = _written_types()
    assert {"task_assigned", "compliance_due"} <= set(written), (
        "the AST scan found no writers — it would pass for every repository state")


def test_every_notification_type_the_code_writes_is_accepted_by_the_table():
    name, accepted = _latest_definition()
    offenders = {t: files for t, files in _written_types().items()
                 if t not in accepted and t not in KNOWN_NOT_ACCEPTED}
    assert not offenders, (
        f"these types are written by the code and refused by {name}'s CHECK — the "
        f"write fails, and notifications are best-effort so nobody is told:\n  "
        + "\n  ".join(f"{t}: {sorted(set(f))}" for t, f in offenders.items())
        + "\nWiden the constraint from the CURRENT definition, found by number, "
          "never re-derived from 122.")


def test_the_known_refusals_are_still_refusals():
    """An equality: fixing one without deleting its entry fails here."""
    _, accepted = _latest_definition()
    written = _written_types()
    stale = sorted(t for t in KNOWN_NOT_ACCEPTED if t in accepted or t not in written)
    assert not stale, (
        f"{stale} is no longer written, or is now accepted — delete it from "
        f"KNOWN_NOT_ACCEPTED, which is how a fix is acknowledged.")


def test_the_portal_message_type_is_in_the_constraint():
    _, accepted = _latest_definition()
    assert rules.PORTAL_MESSAGE_NOTIFICATION_TYPE in accepted, (
        "migration 450 widens notifications_type_check for the in-app half of "
        "'a client wrote to you'; without it every such notification fails its CHECK "
        "inside a best-effort block and no staff member is ever told")


def test_the_latest_definition_is_a_superset_of_the_one_before_it():
    """The next widening must extend the CURRENT constraint. 450 was derived from
    157; this holds the next author to the same."""
    defs = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if "rollback" in path.name or path.name.startswith("_"):
            continue
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        for m in re.finditer(
                r"add\s+constraint\s+notifications_type_check\s+check\s*\(\s*type\s+in\s*\((.*?)\)\s*\)\s*;",
                sql, re.I | re.S):
            defs.append((path.name, set(re.findall(r"'([a-z_]+)'", m.group(1)))))
    defs.sort(key=lambda d: int(d[0].split("_", 1)[0]))
    for (prev_name, prev), (name, cur) in zip(defs, defs[1:]):
        assert prev <= cur, (
            f"{name} drops {sorted(prev - cur)} that {prev_name} accepted — a "
            f"replacement that re-derives from an older ancestor silently reverts")
