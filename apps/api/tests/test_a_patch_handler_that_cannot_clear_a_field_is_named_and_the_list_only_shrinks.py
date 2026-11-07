"""A PATCH handler that cannot clear a field is NAMED, and the list only shrinks (POST-A-399).

THE RULE, NOT A SPELLING. A PATCH handler that reads its body as "what was sent" by dropping every null cannot tell a box the person did not touch from a box the person emptied, so an
edit screen that empties a box is told "saved" while the stored value stays. There are two spellings of the same read in this tree, and the guard sees both, with the variations of each a
new handler might use:

    * `body.model_dump(exclude_none=True)` (also the older `body.dict(...)`, and an `exclude_none=` that is anything but a literal False);
    * `{k: v for k, v in body.model_dump().items() if v is not None}` (also with the test inside an `and`).

The handlers that were given the explicit clear read their body through `models.clearable.patch_dict` and name the fields a person may clear in their model's `CLEARABLE`; every other
PATCH handler that still drops nulls is on `tests/fixtures/patch_handlers_that_cannot_clear.txt`.

    * a new PATCH handler that drops nulls and is not on the list fails;
    * a handler that was converted and is still on the list fails (the list is deleted from in the commit that converts, so it can only shrink);
    * a handler that reads through `patch_dict` must take a body model that names something it may clear, so the reader is never a no-op in disguise.

It finds a handler by its `@router.patch` decorator and its read by the call or the comprehension anywhere inside it. WHAT IT DOES NOT SEE, and `_NOT_SEEN` below names it so the sentence
cannot go stale: a handler that hands the body on to a helper or a service that drops the nulls (`routers/tasks.py::update_task` reads through `_changes_in`, which keeps the explicit null of
`due_date` and `assigned_to` on purpose; the sales cycle's `update_quotation`, `update_order` and `update_challan` and the purchase cycle's `update_order` and `update_receipt` hand
`payload.model_dump()` to a service that drops every null), a `@router.put`, and a service that reads a body it was given; the services' own reads are the ones in `services/`.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

API = Path(__file__).resolve().parents[1]
LIST = API / "tests" / "fixtures" / "patch_handlers_that_cannot_clear.txt"
#: The reader that lets a PATCH clear a field.
_READERS = ("patch_dict",)


#: Handlers the scan cannot see through, named so that the docstring above stays true: each is a real PATCH handler and each is NOT reported (a premise test: when one is converted, or the scan learns to
#: follow a call, this fails and the sentence is rewritten).
_NOT_SEEN = [
    "routers/tasks.py::update_task",
    "routers/sales_cycle.py::update_quotation", "routers/sales_cycle.py::update_order", "routers/sales_cycle.py::update_challan",
    "routers/purchase_cycle.py::update_order", "routers/purchase_cycle.py::update_receipt",
]
#: The two names a pydantic model dumps itself under.
_DUMPS = ("model_dump", "dict")


def _is_not_none_test(cond: ast.AST) -> bool:
    """`v is not None`, alone or as one part of an `and`."""
    if isinstance(cond, ast.BoolOp) and isinstance(cond.op, ast.And):
        return any(_is_not_none_test(c) for c in cond.values)
    return (isinstance(cond, ast.Compare) and len(cond.ops) == 1 and isinstance(cond.ops[0], ast.IsNot)
            and isinstance(cond.comparators[0], ast.Constant) and cond.comparators[0].value is None)


def _drops_nulls(sub: ast.AST) -> bool:
    """`x.model_dump(exclude_none=<anything but a literal False>)` (or `.dict(...)`), or a dict comprehension over `x.model_dump().items()` that keeps `v is not None`."""
    if isinstance(sub, ast.Call):
        f = sub.func
        return isinstance(f, ast.Attribute) and f.attr in _DUMPS and any(
            kw.arg == "exclude_none" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False) for kw in sub.keywords)
    if isinstance(sub, ast.DictComp):
        for gen in sub.generators:
            it = gen.iter
            over_dump = (isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "items"
                         and isinstance(it.func.value, ast.Call) and isinstance(it.func.value.func, ast.Attribute) and it.func.value.func.attr in _DUMPS)
            if over_dump and any(_is_not_none_test(c) for c in gen.ifs):
                return True
    return False


def _patch_handlers():
    """{"routers/x.py::handler": (drops_nulls, reads_patch_dict)} for every function decorated `@router.patch(...)`."""
    out = {}
    for path in sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "patch" for d in node.decorator_list):
                continue
            none = helper = False
            for sub in ast.walk(node):
                if _drops_nulls(sub):
                    none = True
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in _READERS:
                    helper = True
            out[f"routers/{path.name}::{node.name}"] = (none, helper)
    return out


def _listed():
    return {ln.strip() for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


def test_the_scan_sees_the_patch_handlers_and_every_way_of_reading_them():
    found = _patch_handlers()
    assert len(found) > 60, "the scan stopped seeing the PATCH handlers"
    assert any(none for none, _ in found.values()) and any(helper for _, helper in found.values())
    # one handler of each spelling, so a scan that learned only one of them cannot pass
    assert found["routers/accounting.py::update_account"][0], "the exclude_none spelling is no longer seen"
    assert found["routers/clients.py::update_client"][0], "the dict-comprehension spelling is no longer seen"


def test_the_detector_reads_every_spelling_it_knows_and_nothing_else():
    def drops(src: str) -> bool:
        return any(_drops_nulls(n) for n in ast.walk(ast.parse(src)))
    # the two spellings in the tree
    assert drops("body.model_dump(exclude_none=True)")
    assert drops("{k: v for k, v in body.model_dump().items() if v is not None}")
    # the variations a new handler might use
    assert drops("body.dict(exclude_none=True)"), "the older pydantic name"
    assert drops("body.model_dump(exclude_none=flag)"), "an exclude_none that is not a literal is not read as False"
    assert drops("{k: v for k, v in body.model_dump().items() if v is not None and k != 'id'}"), "the test inside an and"
    assert drops("{k: v for k, v in body.dict().items() if k != 'id' and v is not None}")
    # what is not this read
    assert not drops("body.model_dump()")
    assert not drops("body.model_dump(exclude_none=False)")
    assert not drops("body.model_dump(exclude_unset=True)"), "exclude_unset keeps an explicit null, which is the whole point"
    assert not drops("{k: v for k, v in body.model_dump().items()}")
    assert not drops("{k: v for k, v in body.model_dump().items() if k != 'id' or v is not None}"), "an or keeps a null"
    assert not drops("{k: v for k, v in rows.items() if v is not None}"), "a comprehension over something that is not the request body is not this read"


def test_the_handlers_the_scan_cannot_see_through_are_named_and_still_not_seen():
    found = _patch_handlers()
    for name in _NOT_SEEN:
        assert name in found, f"{name} is no longer a PATCH handler: take it out of _NOT_SEEN and out of the docstring"
        none, helper = found[name]
        assert not none and not helper, (f"{name} is now seen by the scan (it reads its own body): move it to {LIST.name} or convert it, and take it out of _NOT_SEEN so the docstring stays true")


def test_every_patch_handler_that_drops_nulls_is_on_the_list():
    reading = {name for name, (none, _) in _patch_handlers().items() if none}
    new = sorted(reading - _listed())
    assert not new, ("these PATCH handlers drop every null in their body, so an edit screen cannot clear a field through them: read it with models.clearable.patch_dict and "
                     f"name the fields a person may clear, or add the handler to {LIST.name} with the reason: {new}")


def test_the_list_only_shrinks():
    reading = {name for name, (none, _) in _patch_handlers().items() if none}
    stale = sorted(_listed() - reading)
    assert not stale, f"these handlers no longer drop nulls (converted, renamed or deleted): delete them from {LIST.name}: {stale}"


def test_a_handler_that_reads_through_the_patch_reader_takes_a_model_that_names_what_may_be_cleared():
    users = sorted(name for name, (_, helper) in _patch_handlers().items() if helper)
    assert len(users) >= 6, users
    for name in users:
        rel, func = name.split("::")
        module = importlib.import_module(rel.removesuffix(".py").replace("/", "."))
        fn = getattr(module, func)
        models = [p.annotation for p in inspect.signature(fn).parameters.values() if inspect.isclass(p.annotation) and hasattr(p.annotation, "model_fields")]
        assert any(getattr(m, "CLEARABLE", None) for m in models), f"{name} reads through patch_dict but none of its body models names a CLEARABLE field"


def test_a_handler_is_not_both_on_the_list_and_a_user_of_the_reader():
    both = sorted(name for name, (_, helper) in _patch_handlers().items() if helper and name in _listed())
    assert not both, f"these handlers read through patch_dict and are still on {LIST.name}: {both}"
