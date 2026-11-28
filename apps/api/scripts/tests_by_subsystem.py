#!/usr/bin/env python3
"""List the backend's test files by the part of the product they are about (POST-A-191).

    python3 scripts/tests_by_subsystem.py            how many files each subsystem holds
    python3 scripts/tests_by_subsystem.py tds        the files of one (or several: tds,gst)

The grouping is derived by `tests/_subsystems.py` from each file's name and imports; that module says why the files were not moved into
folders. To RUN a group: `pytest tests --subsystem tds`.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from tests._subsystems import SUBSYSTEMS, files_of, subsystem_of, wanted  # noqa: E402


def main(argv: list[str]) -> int:
    files = files_of(API / "tests")
    if len(argv) > 1:
        try:
            asked = wanted(argv[1])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        for f in files:
            if subsystem_of(str(f)) in asked:
                print(f"tests/{f.name}")
        return 0
    counts = collections.Counter(subsystem_of(str(f)) for f in files)
    for name in SUBSYSTEMS:
        print(f"{counts.get(name, 0):5}  {name}")
    print(f"{len(files):5}  in all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
