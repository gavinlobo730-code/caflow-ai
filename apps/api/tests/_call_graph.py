"""One call graph of the API's own source, shared by the rules that follow a value from where it is made to where it is used.

Two rules need it: `test_a_request_that_names_a_row_asks_whose_it_is.py` (does anything a route calls ask whose a named row is) and
`test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can.py` (which client does a write's receiver come from).
Each used to carry its own resolver and the copies would have drifted.

WHAT IT RESOLVES, AND WHAT IT DOES NOT
    A call is resolved to a function or method of the source tree by (1) a bare name defined in the same module, (2) a name imported
    from a module, (3) `module.name(...)` where `module` is an imported module, (4) `instance.method(...)` where the instance was
    imported by name and the module defines exactly one method of that name, (5) `self.method(...)` inside the class, and (6) the one
    method of that name in the whole tree where there is exactly one. Anything else (a call through a variable, a callback, a
    dictionary of functions) is unresolved, and a rule that depends on it has to treat an unresolved caller as unknown and not as safe.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

SCAN_DIRS = ("services", "domain", "repositories", "routers", "models", "core", "jobs")


def called_name(call: ast.Call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def chain_of(call: ast.Call) -> list[tuple[str, ast.Call]]:
    """[(method, call)] from the outermost call inward, e.g. `db.table(t).update(x).eq(a, b)` -> eq, update, table."""
    out, node = [], call
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        out.append((node.func.attr, node))
        node = node.func.value
    return out


class CallGraph:
    def __init__(self, root: Path, scan_dirs: tuple[str, ...] = SCAN_DIRS):
        self.mods: dict[str, ast.Module] = {}
        for d in scan_dirs:
            if not (root / d).is_dir():
                continue
            for p in (root / d).rglob("*.py"):
                try:
                    tree = ast.parse(p.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                self.mods[p.relative_to(root).with_suffix("").as_posix().replace("/", ".")] = tree
        self.funcs: dict[tuple[str, str], ast.AST] = {}
        self.imports: dict[str, dict] = {}
        self.by_name: dict[str, list[tuple[str, str]]] = {}
        for mod, tree in self.mods.items():
            self.imports[mod] = self.imports_of(tree)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs[(mod, node.name)] = node
                elif isinstance(node, ast.ClassDef):
                    for b in node.body:
                        if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.funcs[(mod, f"{node.name}.{b.name}")] = b
        for (mod, name) in self.funcs:
            self.by_name.setdefault(name.split(".")[-1], []).append((mod, name))
        self._callers: dict[tuple[str, str], list[tuple[tuple[str, str], ast.Call]]] | None = None

    def imports_of(self, scope) -> dict:
        out: dict = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Import):
                for a in node.names:
                    out[a.asname or a.name.split(".")[0]] = ("mod", a.name if a.asname else a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for a in node.names:
                    full = f"{node.module}.{a.name}"
                    out[a.asname or a.name] = ("mod", full) if full in self.mods else ("sym", node.module, a.name)
        return out

    def imports_in(self, key: tuple[str, str]) -> dict:
        """The module's imports and those made inside the function itself."""
        local = dict(self.imports[key[0]])
        local.update(self.imports_of(self.funcs[key]))
        return local

    def resolve(self, call: ast.Call, mod: str, imports: dict, cls) -> list[tuple[str, str]]:
        f = call.func
        if isinstance(f, ast.Name):
            if (mod, f.id) in self.funcs:
                return [(mod, f.id)]
            i = imports.get(f.id)
            if i and i[0] == "sym" and (i[1], i[2]) in self.funcs:
                return [(i[1], i[2])]
            return []
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name):
                if f.value.id == "self" and cls and (mod, f"{cls}.{f.attr}") in self.funcs:
                    return [(mod, f"{cls}.{f.attr}")]
                i = imports.get(f.value.id)
                if i and i[0] in ("mod", "sym"):
                    if i[0] == "mod" and (i[1], f.attr) in self.funcs:
                        return [(i[1], f.attr)]
                    methods = [k for k in self.funcs if k[0] == i[1] and k[1].endswith("." + f.attr)]
                    if len(methods) == 1:
                        return methods
            candidates = self.by_name.get(f.attr, [])
            if len(candidates) == 1:
                return candidates
        return []

    def calls_of(self, key: tuple[str, str]) -> list[tuple[ast.Call, list[tuple[str, str]]]]:
        """Every call inside the function and what each resolves to."""
        mod, name = key
        imports = self.imports_in(key)
        cls = name.split(".")[0] if "." in name else None
        return [(c, self.resolve(c, mod, imports, cls)) for c in ast.walk(self.funcs[key]) if isinstance(c, ast.Call)]

    def callers(self, key: tuple[str, str]) -> list[tuple[tuple[str, str], ast.Call]]:
        """(caller, call node) for every resolved call of `key` anywhere in the tree."""
        if self._callers is None:
            self._callers = collections.defaultdict(list)
            for caller in self.funcs:
                for call, targets in self.calls_of(caller):
                    for target in targets:
                        self._callers[target].append((caller, call))
        return self._callers.get(key, [])

    @staticmethod
    def parameters(fn) -> list[str]:
        return [a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]

    def argument_for(self, call: ast.Call, key: tuple[str, str], parameter: str):
        """The expression a call passes for the named parameter of `key`, or None."""
        names = self.parameters(self.funcs[key])
        if names and names[0] in ("self", "cls"):
            names = names[1:]
        for kw in call.keywords:
            if kw.arg == parameter:
                return kw.value
        if parameter in names and names.index(parameter) < len(call.args):
            return call.args[names.index(parameter)]
        return None
