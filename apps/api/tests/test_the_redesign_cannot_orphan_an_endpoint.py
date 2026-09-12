"""Which screen reaches which endpoint, frozen — so a rebuild cannot lose one.

`test_every_mounted_endpoint_has_a_way_in.py` counts, per prefix, how many
endpoints NO screen reaches, and ratchets the count downward. That is the right
guard for ordinary work: it stops a new endpoint being merged with nothing
calling it.

It is the WRONG guard for a REDESIGN. Rebuild a module's screens and the count
can stay exactly where it was while the SET changes underneath it — the new
screens reach four endpoints the old ones did not, and quietly stop reaching
four the old ones did. Every budget still holds, the total is unchanged, and a
CA discovers on a Tuesday in November that the button which used to reverse a
depreciation posting is gone.

So this file pins the SET, not the count. `tests/fixtures/reachable_endpoints.json`
records every mounted endpoint that some screen named on the day it was written.
Afterwards:

  * an endpoint in the snapshot that is STILL MOUNTED and no longer reached is a
    FAILURE, named individually — a screen that called it was deleted or
    rewritten, and nothing replaced the call;
  * an endpoint in the snapshot that is no longer MOUNTED is fine — deleting an
    endpoint and its callers together is a legitimate change, and this guard is
    not a museum;
  * an endpoint reached that was not in the snapshot is fine — that is the
    ratchet's business, not this one's.

WHAT IT CANNOT SEE is inherited wholesale from the ratchet, deliberately: the
match is on PATHS, not (method, path) pairs, and a path built from a variable
(`${API}/api/public/engagement-letters/${token}${path}`) matches everything of
that shape. A green run here means "some file in apps/web still names a URL of
this shape", never "the screen still works". It is the floor, not the ceiling —
the Playwright walk over the converted modules is what checks the rest.

REFRESHING IT IS DELIBERATE AND SHOULD BE RARE:

    cd apps/api && python3 -m tests.test_the_redesign_cannot_orphan_an_endpoint

Run that only when the losses it reports are ones somebody has read and
accepted, and say in the commit message which ones and why.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from tests.test_every_mounted_endpoint_has_a_way_in import (
    _pattern,
    _routes,
    _sources,
)

SNAPSHOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "reachable_endpoints.json"

#: A snapshot that overlaps the mounted app less than this is not describing
#: this app any more — refuse rather than report hundreds of "losses" that are
#: really one stale file.
MIN_STILL_MOUNTED = 0.80

#: A truncated or half-written fixture passes every other test in here
#: vacuously. The tree of 2026-09-12 reaches ~770 of 904 routes.
MIN_ENTRIES = 600


def _snapshot() -> list[str]:
    return json.loads(SNAPSHOT.read_text())


def reached_now() -> set[str]:
    """Every mounted endpoint some non-test file in apps/web names."""
    blob = _sources()
    return {
        f"{method} {path}"
        for method, path in _routes()
        if _pattern(path).search(blob)
    }


def mounted_now() -> set[str]:
    return {f"{method} {path}" for method, path in _routes()}


@pytest.fixture(scope="module")
def state() -> tuple[list[str], set[str], set[str]]:
    return _snapshot(), reached_now(), mounted_now()


def test_the_snapshot_is_not_empty(state):
    """A fixture written by a half-finished refresh must not pass silently."""
    snapshot, _, _ = state
    assert len(snapshot) >= MIN_ENTRIES, (
        f"{SNAPSHOT.name} holds {len(snapshot)} endpoints, expected at least "
        f"{MIN_ENTRIES}. A truncated snapshot makes every other test in this "
        f"file pass without checking anything.")


def test_the_snapshot_is_sorted_and_unique(state):
    """So a refresh produces a diff a reviewer can read."""
    snapshot, _, _ = state
    assert snapshot == sorted(set(snapshot)), (
        "the snapshot is not sorted-unique — regenerate it with "
        "`python3 -m tests.test_the_redesign_cannot_orphan_an_endpoint`")


def test_the_snapshot_describes_this_app(state):
    """Most of what it names must still be mounted, or it is simply stale."""
    snapshot, _, mounted = state
    still = [e for e in snapshot if e in mounted]
    assert len(still) >= MIN_STILL_MOUNTED * len(snapshot), (
        f"only {len(still)} of {len(snapshot)} snapshotted endpoints are still "
        f"mounted. That is a rewrite, not a regression — read the change, then "
        f"refresh the snapshot deliberately.")


def test_no_endpoint_has_lost_its_way_in(state):
    """The point of the file.

    An endpoint the product still serves, that a screen used to call and none
    calls now. Deleting the endpoint too is fine; deleting only the caller
    leaves a CA with a capability the software has and cannot be asked for.
    """
    snapshot, reached, mounted = state
    lost = sorted(e for e in snapshot if e in mounted and e not in reached)

    by_prefix: dict[str, list[str]] = {}
    for entry in lost:
        path = entry.split(" ", 1)[1]
        by_prefix.setdefault("/".join(path.split("/")[:3]), []).append(entry)

    assert not lost, "\n".join(
        f"{prefix}: {', '.join(items)}" for prefix, items in sorted(by_prefix.items())
    ) + (
        f"\n\n{len(lost)} endpoint(s) are still mounted and no screen names "
        f"them any more. Wire each one back into whatever screen replaced its "
        f"caller, delete the endpoint if it is genuinely gone, or — if the loss "
        f"is deliberate and understood — refresh "
        f"tests/fixtures/reachable_endpoints.json and say which in the commit."
    )


if __name__ == "__main__":  # pragma: no cover - the refresher
    entries = sorted(reached_now())
    SNAPSHOT.write_text(json.dumps(entries, indent=1) + "\n")
    print(f"wrote {len(entries)} reachable endpoints to {SNAPSHOT}")
