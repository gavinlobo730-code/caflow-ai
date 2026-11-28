#!/usr/bin/env python3
"""Record the checksum of a NEW migration, and refuse to re-record an old one (POST-A-583).

WHY THIS EXISTS
    Until 28-11-2026 `apply_migrations.py` ran a migration again whenever the file's checksum was not the one the database
    recorded. That is how a fix to a file that FAILED is retried. It also meant that editing a migration production had ALREADY
    APPLIED, even one word of a comment, ran the whole file again over a database every later migration had since changed, and
    a second run puts back what the file defined and silently undoes each later change to the same object. On 27-11-2026 a
    rename sweep did exactly that to eight applied migrations: production's ledger posting function went back to its September
    body for a day (migration 786 is the repair). The rule was written in three places and held by nothing. The runner now
    refuses to run such a file and fails the deploy (POST-A-584); this list is the first lock, so the edit never merges.

    `tests/fixtures/migration_checksums.txt` is the list of every migration's checksum, and
    `tests/test_an_applied_migration_is_never_edited.py` fails when a file no longer matches its line. This script is the one
    way a line is written.

USAGE (from apps/api)
    python3 scripts/db/freeze_migration_checksums.py            # add the lines of migrations not yet listed
    python3 scripts/db/freeze_migration_checksums.py --check    # write nothing; exit 1 on any difference
    python3 scripts/db/freeze_migration_checksums.py --replace 790_name.sql
        # ONLY for a migration that has not been merged: you changed your own new file after freezing it.
        # Never for a file that is on main: production has applied it, and the new bytes would run it again there.

It never changes an existing line by itself. A file that differs from its line is reported and the run fails, because the
right answer is almost always to put the file back.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_migrations import MIGRATIONS_DIR, discover_migrations  # noqa: E402  (the runner's own list and its own checksum)

MANIFEST = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "migration_checksums.txt"

HEADER = """\
# The checksum of every migration, as apply_migrations.py computes it (sha256 of the file's bytes).
# An applied migration is never edited, not even a comment: the runner would run it again in production.
# tests/test_an_applied_migration_is_never_edited.py holds every file to its line.
# A NEW migration adds its line with: python3 scripts/db/freeze_migration_checksums.py   (never edit a line by hand)
"""

EDITED = ("{name} no longer matches its recorded checksum. A migration production has applied is never edited, not even a "
          "comment: its checksum is what production matches on, a second run would undo every later change to what the file "
          "defines, and the runner refuses to run it and fails the deploy. Put the file back (git checkout origin/main -- apps/api/migrations/{name}). Only if this is your own NEW, unmerged "
          "migration: scripts/db/freeze_migration_checksums.py --replace {name}")
UNLISTED = ("{name} is not in tests/fixtures/migration_checksums.txt. A new migration records its checksum with: "
            "python3 scripts/db/freeze_migration_checksums.py")
GONE = ("{name} is in tests/fixtures/migration_checksums.txt and the file is gone. A migration production has applied is not "
        "deleted or renamed; if this one never merged, remove its line by hand.")


def current(migrations_dir: Path = MIGRATIONS_DIR) -> dict[str, str]:
    """filename -> checksum for every file the runner would apply, in the runner's order."""
    return {m.name: m.checksum() for m in discover_migrations(migrations_dir)}


def read_manifest(path: Path = MANIFEST) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        checksum, name = line.split(None, 1)
        out[name.strip()] = checksum
    return out


def problems(now: dict[str, str], recorded: dict[str, str]) -> list[str]:
    """Every way the files and the list disagree, each as a sentence that says what to do."""
    found = [EDITED.format(name=n) for n, c in now.items() if n in recorded and recorded[n] != c]
    found += [UNLISTED.format(name=n) for n in now if n not in recorded]
    found += [GONE.format(name=n) for n in recorded if n not in now]
    return found


def write_manifest(recorded: dict[str, str], order: list[str], path: Path = MANIFEST) -> None:
    listed = [n for n in order if n in recorded] + sorted(n for n in recorded if n not in order)
    path.write_text(HEADER + "".join(f"{recorded[n]}  {n}\n" for n in listed), encoding="utf-8")


def freeze(migrations_dir: Path = MIGRATIONS_DIR, manifest: Path = MANIFEST, replace: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Add the lines of unlisted migrations (and re-record the ones named in `replace`). Returns (added, still wrong)."""
    now, recorded = current(migrations_dir), read_manifest(manifest)
    added = [n for n in now if n not in recorded]
    for n in added:
        recorded[n] = now[n]
    for n in replace:
        if n not in now:
            raise SystemExit(f"--replace {n}: no such migration")
        recorded[n] = now[n]
    wrong = [p for p in problems(now, recorded)]
    write_manifest(recorded, list(now), manifest)
    return added, wrong


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on any difference")
    ap.add_argument("--replace", action="append", default=[], metavar="FILE",
                    help="re-record YOUR OWN new, unmerged migration after changing it")
    args = ap.parse_args(argv)
    if args.check:
        wrong = problems(current(), read_manifest())
        for p in wrong:
            print(p, file=sys.stderr)
        return 1 if wrong else 0
    added, wrong = freeze(replace=tuple(args.replace))
    for n in added:
        print(f"recorded {n}")
    for n in args.replace:
        print(f"re-recorded {n} (it must not be on main)")
    for p in wrong:
        print(p, file=sys.stderr)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
