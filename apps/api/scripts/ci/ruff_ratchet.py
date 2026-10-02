"""Python lint as a ratchet: a finding that is not already on the books fails, and the books only shrink (engineering-01).

WHY A RATCHET AND NOT `ruff check`
    Measured on 01-10-2026, the day this was written, `ruff check` over apps/api with the rules in
    pyproject.toml reports 1,154 findings: 432 unused imports, 252 `raise` without `from` inside an `except`,
    123 unused variables, 89 functions over the complexity limit, 33 over the statement limit, and so on.
    A step that fails on those is red on its first run and stays red until somebody tidies a 20,000-test
    repository, which is a separate and reviewable job. A step that ignores them says nothing to the next
    careless unused import. So the findings that exist today are written down in `ruff_baseline.txt` and the
    gate fails on anything that is not in it. `ruff` has no baseline feature of its own, and `--add-noqa` would
    edit a thousand lines of code other work is changing; this file is the baseline.

WHAT IS COMPARED, AND WHY NOT LINE NUMBERS
    A line number moves whenever anybody adds a line above it, so a baseline keyed on line numbers goes stale
    on every unrelated commit. Source text moves when code is reformatted. A finding is identified instead by
    (file, rule, SCOPE): the dotted name of the innermost function or class it sits in, or `<module>`. That
    survives both. The number beside it is how many findings of that rule that scope carries, and for the two
    SIZE rules (C901 complexity, PLR0915 statements) it is the MEASURED size, so a function that is already
    over the limit cannot get longer either. Moving a finding to a new scope, adding one to a scope that has
    one, or growing a measured function are all "new". The only thing this cannot see is fixing one finding and
    adding another of the same rule in the same function in the same commit, which nets to nothing.

THE BASELINE ONLY SHRINKS, AND THAT IS ENFORCED FROM BOTH SIDES
    - A finding the baseline does not cover fails the gate (exit 1) and is printed with its line.
    - A baseline line that no longer fires, or that fires less, ALSO fails (exit 1): a fixed finding must
      leave the baseline in the commit that fixed it, or the slack is a hole the next finding in that scope
      walks through. `--update` does this for you, and it can only LOWER or DELETE: it never adds a line and
      never raises a number, and it refuses to write at all while there is a new finding.
    - `--init` writes a first baseline and refuses when one exists, so regenerating cannot be used to absorb
      a new finding.

A TOOL THAT DID NOT RUN IS NOT A CLEAN RESULT
    Exit 0 means "ran, nothing new, nothing stale". Exit 1 means "ran, something to do". Exit 2 means ruff is
    missing, crashed, printed something that is not JSON, or looked at fewer files than the repository has
    (`--show-files` must name a file in each of the first-party packages): an empty report from a run that
    checked nothing would otherwise be a clean one. `ruff` is run with `--exit-zero`, so ANY non-zero exit from
    it is the abnormal kind and is exit 2 here.

THE VERSION IS PINNED (requirements-dev.txt)
    A newer ruff can fire on code that did not change, and the gate would go red with no commit of ours. Bump it
    on purpose, with the baseline.

Usage (from apps/api):
    python scripts/ci/ruff_ratchet.py             # the gate
    python scripts/ci/ruff_ratchet.py --update    # drop baseline lines that no longer fire (never adds)
    python scripts/ci/ruff_ratchet.py --init      # first baseline only
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

API = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().with_name("ruff_baseline.txt")

#: Rules whose figure is a SIZE read out of ruff's message, `(23 > 15)`: the baseline stores the size, and a
#: function may get smaller but never larger. Every other rule is a count of findings.
SIZE_RULES = frozenset({"C901", "PLR0915"})

#: A first-party package that `--show-files` must name at least one file in. A run that did not reach these
#: checked the wrong directory, and its empty report is not a clean one.
MUST_SEE = ("core/", "domain/", "routers/", "services/", "tests/")

MODULE_SCOPE = "<module>"

_SIZE = re.compile(r"\((\d+) > \d+\)")


class RatchetError(Exception):
    """The run cannot be trusted to mean 'nothing found'. Exit code 2."""


@dataclass(frozen=True)
class Diagnostic:
    path: str       # relative to apps/api, forward slashes
    row: int
    col: int
    code: str
    message: str


Key = tuple  # (path, code, scope)


# ── scope ───────────────────────────────────────────────────────────────────────

def scope_spans(source: str) -> list[tuple[int, int, str]]:
    """(first line, last line, dotted name) for every def and class in `source`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans: list[tuple[int, int, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                spans.append((child.lineno, child.end_lineno or child.lineno, name))
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return spans


def scope_of(spans: list[tuple[int, int, str]], row: int) -> str:
    """The innermost def or class holding `row`, else the module. Innermost = the latest-starting span that
    still contains the row, because spans nest."""
    best: Optional[tuple[int, str]] = None
    for start, end, name in spans:
        if start <= row <= end and (best is None or start >= best[0]):
            best = (start, name)
    return best[1] if best else MODULE_SCOPE


# ── reading ruff ────────────────────────────────────────────────────────────────

def diagnostics_from_json(report: object, root: Path) -> list[Diagnostic]:
    if not isinstance(report, list):
        raise RatchetError("ruff's JSON report is not a list — it did not produce a report")
    out: list[Diagnostic] = []
    for item in report:
        try:
            filename = Path(item["filename"]).resolve()
            rel = filename.relative_to(root.resolve()).as_posix()
            out.append(Diagnostic(rel, int(item["location"]["row"]), int(item["location"]["column"]),
                                  str(item["code"] or "E999"), str(item["message"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise RatchetError(f"a ruff diagnostic is not in the shape this reads ({exc!r}): {item!r}") from exc
    return out


def to_counts(diags: Iterable[Diagnostic], read_source: Callable[[str], str]) -> dict[Key, int]:
    """{(path, code, scope): count}, or the measured size for a SIZE rule."""
    spans_by_path: dict[str, list] = {}
    counts: dict[Key, int] = defaultdict(int)
    for d in diags:
        if d.path not in spans_by_path:
            spans_by_path[d.path] = scope_spans(read_source(d.path))
        key = (d.path, d.code, scope_of(spans_by_path[d.path], d.row))
        if d.code in SIZE_RULES:
            m = _SIZE.search(d.message)
            if not m:
                raise RatchetError(f"{d.path}:{d.row} {d.code}: cannot read the measured size out of {d.message!r}")
            counts[key] = max(counts[key], int(m.group(1)))
        else:
            counts[key] += 1
    return dict(counts)


# ── the baseline file ───────────────────────────────────────────────────────────

HEADER = """\
# The Python lint findings that existed on the day the ratchet was written (engineering-01).
# Read scripts/ci/ruff_ratchet.py before touching this file.
#
#   path :: rule :: scope :: n
#
# `n` is how many findings of that rule the scope carries, or for C901 and PLR0915 the measured size of the
# function. This file may only SHRINK: `python scripts/ci/ruff_ratchet.py --update` deletes lines that no
# longer fire and lowers numbers that fell, and cannot add or raise anything. A line is a defect the product
# carries today, written down. It is never a judgement that the code is fine.
"""

_LINE = re.compile(r"^(?P<path>\S+) :: (?P<code>[A-Z]+[0-9]+) :: (?P<scope>\S+) :: (?P<n>[1-9][0-9]*)$")


def read_baseline(text: str) -> dict[Key, int]:
    out: dict[Key, int] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise RatchetError(f"baseline line {number} is not `path :: rule :: scope :: n`: {raw!r}")
        key = (m["path"], m["code"], m["scope"])
        if key in out:
            raise RatchetError(f"baseline line {number}: {key} is listed twice")
        out[key] = int(m["n"])
    return out


def render_baseline(counts: dict[Key, int]) -> str:
    rows = [f"{p} :: {c} :: {s} :: {n}\n" for (p, c, s), n in sorted(counts.items()) if n > 0]
    return HEADER + "".join(rows)


# ── the verdict ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    new: dict       # key -> (current, baseline): findings the baseline does not cover
    stale: dict     # key -> (current, baseline): baseline lines that fire less than they say, or not at all

    @property
    def clean(self) -> bool:
        return not self.new and not self.stale


def judge(current: dict[Key, int], baseline: dict[Key, int]) -> Verdict:
    new = {k: (n, baseline.get(k, 0)) for k, n in current.items() if n > baseline.get(k, 0)}
    stale = {k: (current.get(k, 0), n) for k, n in baseline.items() if current.get(k, 0) < n}
    return Verdict(new, stale)


def lowered(current: dict[Key, int], baseline: dict[Key, int]) -> dict[Key, int]:
    """The baseline after `--update`: each line at the lower of what it says and what fires, none added."""
    return {k: min(n, current.get(k, 0)) for k, n in baseline.items() if min(n, current.get(k, 0)) > 0}


# ── running ruff ────────────────────────────────────────────────────────────────

def _run(args: list[str], ruff: str) -> str:
    try:
        proc = subprocess.run([*shlex.split(ruff), *args], cwd=API, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise RatchetError(f"{ruff!r} is not installed — `pip install -r requirements-dev.txt`") from exc
    except subprocess.TimeoutExpired as exc:
        raise RatchetError("ruff did not finish in five minutes") from exc
    if proc.returncode != 0:
        raise RatchetError(f"ruff {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def run_ruff(ruff: str = "ruff") -> list[Diagnostic]:
    files = [ln for ln in _run(["check", "--show-files", "--no-cache", "."], ruff).splitlines() if ln.strip()]
    rel = [Path(f).resolve().relative_to(API.resolve()).as_posix() for f in files]
    for package in MUST_SEE:
        if not any(r.startswith(package) for r in rel):
            raise RatchetError(f"ruff's file list has nothing under {package} ({len(rel)} files) — it checked the "
                               "wrong tree, and an empty report from that is not a clean one")
    out = _run(["check", "--exit-zero", "--no-cache", "--output-format", "json", "."], ruff)
    try:
        report = json.loads(out)
    except ValueError as exc:
        raise RatchetError(f"ruff's output is not JSON ({exc}); first bytes: {out[:120]!r}") from exc
    return diagnostics_from_json(report, API)


def _source(path: str) -> str:
    try:
        return (API / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ── the command line ────────────────────────────────────────────────────────────

def describe(key: Key, now: int, was: int) -> str:
    path, code, scope = key
    unit = "size" if code in SIZE_RULES else "findings"
    return f"{path} :: {code} :: {scope}  ({unit}: {now}, baseline {was})"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--ruff", default="ruff", help="the ruff command, e.g. `ruff` or `python -m ruff`")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="delete baseline lines that no longer fire; never adds")
    mode.add_argument("--init", action="store_true", help="write a first baseline; refused when one exists")
    args = ap.parse_args(argv)

    try:
        diags = run_ruff(args.ruff)
        current = to_counts(diags, _source)
        if args.init:
            if args.baseline.exists():
                raise RatchetError(f"{args.baseline} exists. The baseline is shrunk with --update and is never "
                                   "regenerated, because regenerating is how a new finding gets absorbed.")
            args.baseline.write_text(render_baseline(current), encoding="utf-8")
            print(f"wrote {args.baseline} — {len(diags)} findings in {len(current)} lines")
            return 0
        baseline = read_baseline(args.baseline.read_text(encoding="utf-8"))
    except (RatchetError, OSError) as exc:
        print(f"ERROR the lint did not run: {exc}")
        return 2

    v = judge(current, baseline)
    print(f"ruff: {len(diags)} findings in {len(current)} (file, rule, scope) lines · baseline holds "
          f"{len(baseline)} lines · {len(v.new)} NEW · {len(v.stale)} stale")

    if v.new:
        by_key = defaultdict(list)
        spans: dict[str, list] = {}
        for d in diags:
            spans.setdefault(d.path, scope_spans(_source(d.path)))
            by_key[(d.path, d.code, scope_of(spans[d.path], d.row))].append(d)
        for key in sorted(v.new):
            now, was = v.new[key]
            print(f"NEW   {describe(key, now, was)}")
            for d in by_key[key]:
                print(f"        {d.path}:{d.row}:{d.col}: {d.code} {d.message}")
    if v.stale and not v.new:
        for key in sorted(v.stale):
            now, was = v.stale[key]
            print(f"STALE {describe(key, now, was)}")

    if args.update:
        if v.new:
            print("Not writing the baseline: fix the NEW findings above first. --update never adds a finding.")
            return 1
        shrunk = lowered(current, baseline)
        args.baseline.write_text(render_baseline(shrunk), encoding="utf-8")
        print(f"baseline shrunk: {len(baseline)} -> {len(shrunk)} lines")
        return 0

    if v.new:
        print("\nFix the new findings. They are not added to the baseline: it may only shrink.")
    elif v.stale:
        print("\nThese findings are fixed, so their baseline lines have to go. Run "
              "`python scripts/ci/ruff_ratchet.py --update` and commit the result; the slack they leave would "
              "let the next finding in the same place through.")
    return 0 if v.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
