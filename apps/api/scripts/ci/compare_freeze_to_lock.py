#!/usr/bin/env python3
"""Does what an environment actually has installed equal what the lock says (engineering-04)?

    docker run --rm --entrypoint pip practicesync-api:ci freeze \\
        | python3 scripts/ci/compare_freeze_to_lock.py requirements.txt

Reads `pip freeze` on stdin and the compiled lock named on the command line, and exits

    0   every pinned package is installed at its pinned version and nothing else is
    1   a difference, each one printed
    2   one side could not be read, or was empty: an empty comparison passes everything

WHY A SCRIPT AND NOT `diff`. `pip freeze` and a pip-compile file spell a name differently (`pdfminer.six`
against `pdfminer-six`, `PyJWT` against `pyjwt`), a pip-compile file carries hashes, backslashes and `# via`
comments, and `pip freeze` leaves out pip, setuptools and wheel, which the base image carries and the lock
deliberately does not pin. Normalising both sides once, here, is what makes "identical" mean something.

It is run in the `docker image` workflow against the image, which is the check that the image is the lock; two
builds a week apart that both pass it have an identical `pip freeze` by construction.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: What pip itself leaves out of `pip freeze`, and the base image installs.
TOOLING = {"pip", "setuptools", "wheel", "distribute"}


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins_in_lock(text: str) -> dict[str, str]:
    """name -> version for every `name==version` in a pip-compile file."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if m:
            pins[normalise(m.group(1))] = m.group(2)
    return pins


def pins_in_freeze(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)$", line.strip())
        if m and normalise(m.group(1)) not in TOOLING:
            pins[normalise(m.group(1))] = m.group(2)
    return pins


def compare(lock: dict[str, str], installed: dict[str, str]) -> list[str]:
    problems = []
    for name in sorted(lock.keys() - installed.keys()):
        problems.append(f"in the lock and NOT installed: {name}=={lock[name]}")
    for name in sorted(installed.keys() - lock.keys()):
        problems.append(f"installed and NOT in the lock: {name}=={installed[name]}")
    for name in sorted(lock.keys() & installed.keys()):
        if lock[name] != installed[name]:
            problems.append(f"{name}: lock says {lock[name]}, installed is {installed[name]}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        lock = pins_in_lock(Path(argv[1]).read_text(encoding="utf-8"))
    except OSError as e:
        print(f"cannot read the lock: {e}", file=sys.stderr)
        return 2
    installed = pins_in_freeze(sys.stdin.read())
    if not lock or not installed:
        print(f"nothing to compare ({len(lock)} pinned, {len(installed)} installed): an empty comparison "
              "passes everything, so it is refused", file=sys.stderr)
        return 2
    problems = compare(lock, installed)
    for p in problems:
        print(p)
    if problems:
        return 1
    print(f"the installed set is the lock: {len(lock)} packages, identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
