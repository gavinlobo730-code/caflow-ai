"""Reading Python source the way a guard should read it.

A GUARD THAT READS PROSE IS A GUARD THAT FORBIDS EXPLAINING THE FIX. Every
source-scanning test in this suite has hit the same trap: the scan trips on the
comment or docstring that describes the very thing it bans, so either the ban
loses its explanation or the guard is quietly narrowed. It cost
`domain/notification_fixtures.py` its plain explanation on 17-09-2026, and on
18-09-2026 it fired three more times in one new module -- on a route rename, on
a cadence column and on the `if internal_id:` predicate, each time because the
new code's own docstring said what it replaced.

So the blanking lives here once rather than being copied into a third module.
`test_one_supplier_master.py` had the only implementation and now imports it.
"""
import ast


def blank_python_docstrings(body: str) -> str:
    """A DOCSTRING IS PROSE, AND PROSE IS NOT A QUERY.

    `#` comments were blanked from the first run of `test_one_supplier_master`
    and docstrings were not, which is the same rule half-applied -- so a ban
    could be DESCRIBED in a comment and not in a docstring.

    Blanked through the AST, one node at a time, and NOT by blanking every
    triple-quoted string: a module-level SQL constant is triple-quoted too and
    is a real read of its table. A file that does not parse keeps its whole
    body, because the scan must never go quiet on a file it could not read.

    Whitespace is substituted in place rather than the text deleted, so every
    line number and column offset survives -- a caller reporting `file:line`
    still points at the right line.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:                                      # pragma: no cover
        return body
    lines = body.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)
                and doc.end_lineno is not None):
            spans.append((starts[doc.lineno - 1] + doc.col_offset,
                          starts[doc.end_lineno - 1] + doc.end_col_offset))
    out = list(body)
    for lo, hi in spans:
        for i in range(lo, min(hi, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)
