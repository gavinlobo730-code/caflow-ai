"""A sentence the SERVER writes that names a role as the one who may do something is on a list with the reason (POST-A-566).

Since 21 November 2026 a permission a Partner ticks decides what each member can do (`core.permissions.can_user`, `rbac`), so a
refusal or a note that says "Only Manager or above can approve a GST return" states the role's DEFAULT and is false for a member
who was ticked. POST-A-556 fixed that on the screens and the first part of POST-A-566 on the server's refusals that sit beside a
per-person permission check. What is left in the server's strings are the sentences that name a role BECAUSE THE CODE ASKS THE
ROLE, or that say what a Partner CAN do (never that only a Partner can, where a tick can also give it). Each is read once and
written here with why it is true; a new one fails until it is worded the same way (someone who may approve TDS, someone with
Banking approval) or is added here with its reason. The count per file is an equality in both directions, so a fixed sentence
removes its own row and the list only shrinks.

WHAT IT SEES AND WHAT IT DOES NOT
    It reads every string constant (not a docstring, not an HTML template) of `routers`, `services`, `domain`, `core`, `models`
    and `jobs` that names a role AND says who may or must do something. It does not see a sentence built from pieces by `+` or an
    f-string whose role word is inserted at run time, a sentence in a mail template, or one in a language other than English.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
FOLDERS = ("routers", "services", "domain", "core", "models", "jobs")

ROLE = re.compile(r"\b(Partners?|Managers?|Executives?|Reviewers?)\b")
WHO_MAY = re.compile(r"\b(only|Only|can|may|must|needs?|Requires?|requires?|ask|Ask|decide|above|approve|reopen)\b")

#: file -> (how many such sentences it holds, why each is true). Equality, both directions.
BY_DESIGN: dict[str, tuple[int, str]] = {
    "domain/ai/budget.py": (1, "says what a Partner CAN do (raise or remove the AI limit); the route asks `firm:admin`, which a Partner holds, and the sentence does not say only"),
    "domain/ai_copilot_service.py": (1, "the practice's own fee receivables are My practice's, a Partner's alone by role (guardrail G1), which no tick opens"),
    "domain/onboarding/first_run.py": (1, "says a Partner invites staff from the Team screen; `team:write` is a Partner's and is not given through a request"),
    "routers/lifecycle.py": (1, "tells the reader whom to ask: a Partner makes assignments"),
    "routers/relationships.py": (1, "tells the reader whom to ask: a Partner makes assignments"),
    "routers/shared_reports.py": (1, "says a Partner can change access on the Team screen, which is true and does not say only"),
    "routers/year_end.py": (2, "the year-end's final approval and its reopen are a Partner's by role in the code (`allowed_roles`), not a permission"),
    "routers/year_end_reviews.py": (5, "the year-end sign-off ladder is asked by role in the code (`_role_gte`: Executive submits, Manager approves or asks for a revision, Partner gives final approval and reopens)"),
    "services/access_request_service.py": (6, "a request for access is decided by a Partner who is not the asker, by role in the code (`_is_partner`): the owner's rule of 21-11-2026"),
    "services/approval_service.py": (1, "the code lets only the requester or a Partner cancel a request, by role"),
    "services/mfa_reset_service.py": (9, "a lost authenticator is reset through the approval engine by a Partner who is not the asker, by role in the code (`_is_partner`)"),
    "services/named_row_ownership.py": (1, "tells the reader whom to ask: a Partner assigns a member to a client"),
}


def sentences_naming_a_role(source: str) -> list[tuple[int, str]]:
    """(line, text) of every string constant that names a role and says who may or must; docstrings and HTML are left out."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            text = node.value
            if (25 < len(text) < 600 and ROLE.search(text) and WHO_MAY.search(text)
                    and "<h2>" not in text and "<p>" not in text and not text.lstrip().startswith(("select", "SELECT"))):
                found.append((node.lineno, text.replace("\n", " ")))
    return found


def _census() -> dict[str, int]:
    out: dict[str, int] = {}
    for folder in FOLDERS:
        for path in sorted((API / folder).rglob("*.py")):
            try:
                hits = sentences_naming_a_role(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            if hits:
                out[path.relative_to(API).as_posix()] = len(hits)
    return out


def test_every_server_sentence_that_names_a_role_is_listed_with_its_reason():
    found = _census()
    listed = {file: count for file, (count, _why) in BY_DESIGN.items()}
    assert found == listed, (
        "a server sentence names a role as the one who may. Read what the code asks: where it is a permission (`can_user`, `rbac`), "
        "name the permission (\"someone who may approve TDS\", \"someone with Banking approval\") or say nothing about who; where "
        "it is the role, add the file to BY_DESIGN with the reason. A reworded sentence lowers its file's count here.\n"
        f"found {found}\nlisted {listed}")


def test_every_listed_file_has_a_reason_and_exists():
    for file, (count, why) in BY_DESIGN.items():
        assert (API / file).is_file(), f"{file} is listed and is not there"
        assert count >= 1 and len(why) > 40, f"{file} has no reason worth the name"


def test_the_scan_is_not_vacuous():
    assert sum(_census().values()) >= 30, "the scan found almost nothing: it has stopped reading the tree"


def test_the_rule_catches_the_old_spellings_and_lets_the_new_ones_through():
    old = ('raise E("Only Manager or above can approve or submit a GST return.")\n'
           'raise E("Only a Manager or Partner can let a rule pass entries by itself.")\n'
           'raise E("A Partner can reverse that entry from the ledger so the invoice can be posted afresh")\n')
    assert len(sentences_naming_a_role(old)) == 3
    new = ('raise E("Only someone who may approve GST returns can approve or submit a GST return.")\n'
           'raise E("Only someone with Banking approval can let a rule pass entries by itself.")\n'
           'raise E("Someone who may approve Accounting can reverse that entry from the ledger so the invoice can be posted afresh")\n')
    assert sentences_naming_a_role(new) == []
    docstring = '"""A Partner can do it."""\n\ndef f():\n    """Only a Manager may call this one."""\n    return 1\n'
    assert sentences_naming_a_role(docstring) == [], "a docstring is for the reader of the code, not for the person"
