"""The source of the payroll CREATE PATH, not of one function.

WHY THIS EXISTS

Six guards across five files asserted a rule about how a payroll run is built by
reading `inspect.getsource(routers.payroll.create_run)`. PAY-21 lifted that
function's slip-building body into `_compute_and_store_slips` so that
`POST /runs/{run_id}/recompute` could call the same computation — and all six
failed, on a move that did not touch the rule any of them states.

Each of those rules is about the PATH that builds a run: the professional-tax
slabs are read once for the whole run, attendance goes through `_attendance_for`,
the pay in force goes through the one merge, the PT registration gaps reach
`statutory_gaps`, EDLI and the admin charge are totalled, the ₹500 floor is
applied per establishment. "Somewhere on the create path" is what they mean, so
that is what they read — `create_run` plus every module-level helper it calls,
resolved from the AST rather than named.

ONE DEFINITION, because six copies of this would be the shape the rules
themselves are about.
"""
from __future__ import annotations

import ast
import inspect
from typing import Callable


def create_path_source(*extra: Callable) -> str:
    """`create_run` + the module-level helpers it calls, plus any extra function.

    `extra` is for a guard that compares the create path against a SECOND reader
    — `statutory_position`, say — and needs both in one string.
    """
    import routers.payroll as pr

    src = inspect.getsource(pr.create_run)
    called = {c.func.id for c in ast.walk(ast.parse(src))
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    for name in sorted(called):
        fn = getattr(pr, name, None)
        if callable(fn) and getattr(fn, "__module__", None) == pr.__name__:
            src += "\n" + inspect.getsource(fn)
    for fn in extra:
        src += "\n" + inspect.getsource(fn)

    # A scan that stops following keeps passing while reading almost nothing.
    # `create_run` is a few dozen lines of guards and one delegation; the PATH
    # is several hundred, so a result the size of the door alone means the AST
    # walk stopped resolving and every caller has quietly gone vacuous.
    assert len(src) > 4 * len(inspect.getsource(pr.create_run)), (
        "create_path_source followed no helper — the guards that read it are "
        "asserting against `create_run` alone and no longer see the rule")
    return src
