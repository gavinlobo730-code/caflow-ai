"""Every function that makes or emails a payment link asks whether online payment is on, first (PRE-B-002 part 2).

WHY A RULE AND NOT THREE TESTS OF THREE ROUTES

    The gate is a call at the ROUTE (`online_payment.require_online_payment(...)`), not inside the engine,
    because `payment_service.create_link` is driven directly with the test double by twenty-seven call sites that a
    refusal would break. So the engine is one caller from being reached with no check the day a fourth door is
    written: a job, a second portal route, a bulk "send all payment links" button. A check on one door is one
    caller from being none (CLAUDE.md, the posture of every guard here), and three route tests prove three doors.

    This test derives the doors from the SOURCE. Every function in the product's own code (not the tests, not the
    engine itself) that calls `create_link` or `send_link_email` must also call `require_online_payment`, and the
    call must come BEFORE the first one. A function that does not is a way to make or mail a link that goes
    nowhere.

AND THE OTHER HALF OF "NO DEAD LINK REACHES A CUSTOMER": WHERE A GATEWAY ADDRESS CAN APPEAR

    The test double's address is only ever shown or mailed if some file prints a link. The files that name
    `short_url` or `pay_url` are listed, each with the reason it may: the engine, the providers, the one mail that
    carries a link, the portal route that returns it, and the rule that masks it. A PDF or any other mail naming
    one fails here and has to be argued for. The list is an EQUALITY, so it shrinks and grows deliberately.
"""
from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).resolve().parents[1]
ENGINE = "services/payment_service.py"
REACHES = {"create_link", "send_link_email"}
GATE = "require_online_payment"
_SKIP = {"__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", "tests", "migrations", "scripts"}


def _calls(fn: ast.AST) -> list[tuple[str, int]]:
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name:
                out.append((name, node.lineno))
    return out


def functions_that_reach_a_link(source: str) -> dict[str, dict]:
    """{function name: {"reach": first line of a create/send call, "gate": first line of the gate call or None}}."""
    found: dict[str, dict] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = _calls(node)
            reach = [ln for n, ln in calls if n in REACHES]
            if reach:
                gate = [ln for n, ln in calls if n == GATE]
                found[node.name] = {"reach": min(reach), "gate": min(gate) if gate else None}
    return found


def _product_files():
    for path in API.rglob("*.py"):
        rel = path.relative_to(API)
        if rel.parts[0] in _SKIP or any(p in _SKIP for p in rel.parts):
            continue
        yield path, rel.as_posix()


def _doors() -> dict[str, dict[str, dict]]:
    doors: dict[str, dict[str, dict]] = {}
    for path, rel in _product_files():
        if rel == ENGINE:
            continue
        src = path.read_text(encoding="utf-8")
        if not any(r in src for r in REACHES):
            continue
        found = functions_that_reach_a_link(src)
        if found:
            doors[rel] = found
    return doors


def test_every_function_that_reaches_the_engine_asks_first():
    doors = _doors()
    # Not vacuous: the three doors that exist today are found (staff create, staff send, portal pay).
    names = {(rel, fn) for rel, fns in doors.items() for fn in fns}
    assert names >= {("routers/payments.py", "create_payment_link"),
                     ("routers/payments.py", "send_payment_link"),
                     ("routers/portal_data.py", "portal_pay_invoice")}, names
    problems = []
    for rel, fns in doors.items():
        for fn, where in fns.items():
            if where["gate"] is None:
                problems.append(f"{rel}::{fn} reaches create_link/send_link_email and never asks {GATE}")
            elif where["gate"] > where["reach"]:
                problems.append(f"{rel}::{fn} asks {GATE} on line {where['gate']}, after reaching the engine on line {where['reach']}")
    assert not problems, "\n".join(problems)


def test_the_rule_fails_on_the_mistakes_it_exists_for():
    never = "def new_door():\n    payment_service.create_link(db, f, i, actor=a)\n"
    late = "def new_door():\n    payment_service.send_link_email(db, f, l, actor=a)\n    online_payment.require_online_payment('staff')\n"
    fine = "def new_door():\n    online_payment.require_online_payment('staff')\n    payment_service.create_link(db, f, i, actor=a)\n"
    bare = "def new_door():\n    create_link(db, f, i, actor=a)\n"
    assert functions_that_reach_a_link(never)["new_door"]["gate"] is None
    late_found = functions_that_reach_a_link(late)["new_door"]
    assert late_found["gate"] > late_found["reach"]
    fine_found = functions_that_reach_a_link(fine)["new_door"]
    assert fine_found["gate"] < fine_found["reach"]
    assert functions_that_reach_a_link(bare)["new_door"]["gate"] is None, "a bare name is a call too"
    assert functions_that_reach_a_link("def other():\n    return 1\n") == {}


def test_an_engine_that_asks_for_nothing_is_still_where_the_tests_drive_it():
    """The reason the gate is not inside `create_link`: the engine is driven directly with the test double."""
    src = (API / ENGINE).read_text(encoding="utf-8")
    assert f"{GATE}(" not in src, "the engine must not call the gate: its tests use the test double on purpose"


#: The files allowed to name a gateway address, and why. An EQUALITY: a PDF or another mail that grows one fails.
MAY_NAME_A_LINK_ADDRESS = {
    "services/payment_service.py": "the engine: stores, lists and emails the link, after the checks above",
    "services/payments/base.py": "the provider interface: PaymentLinkResult carries the address",
    "services/payments/mock.py": "the test double, which makes an address that goes nowhere (never shown, never mailed)",
    "services/payments/razorpay.py": "the real gateway adapter",
    "services/email_service.py": "send_payment_link_to_customer: the one mail that carries a link, sent on one click",
    "routers/portal_data.py": "the portal's pay route returns the address to the client's own browser, after the gate",
    "domain/payments/availability.py": "the rule that masks a stored address and refuses to mail a dead one",
}


def test_only_the_named_files_can_put_a_gateway_address_in_front_of_a_person():
    naming = set()
    for path, rel in _product_files():
        src = path.read_text(encoding="utf-8")
        if "short_url" in src or "pay_url" in src:
            naming.add(rel)
    assert naming == set(MAY_NAME_A_LINK_ADDRESS), (
        "a file that names a link address is a place one can reach a person: argue for it here (and ask the "
        f"availability rule first), or take it out. new: {sorted(naming - set(MAY_NAME_A_LINK_ADDRESS))}, "
        f"gone: {sorted(set(MAY_NAME_A_LINK_ADDRESS) - naming)}")


def test_no_pdf_and_no_other_mail_names_a_link_address():
    """The bullet above, stated about the places that matter: every PDF builder and every mail but one."""
    for path, rel in _product_files():
        name = path.name
        if "pdf" in name and rel not in MAY_NAME_A_LINK_ADDRESS:
            assert "short_url" not in path.read_text(encoding="utf-8") and "pay_url" not in path.read_text(encoding="utf-8"), rel
    mail_src = (API / "services" / "email_service.py").read_text(encoding="utf-8")
    functions = {n.name: ast.get_source_segment(mail_src, n) or "" for n in ast.walk(ast.parse(mail_src))
                 if isinstance(n, ast.FunctionDef)}
    carrying = sorted(n for n, seg in functions.items() if "pay_url" in seg or "short_url" in seg)
    assert carrying == ["send_payment_link_to_customer"], carrying
