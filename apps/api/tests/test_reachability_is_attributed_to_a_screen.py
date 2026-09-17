"""An endpoint is reached because a SCREEN reaches it, not because a file says so.

WHAT WAS WRONG

`test_every_mounted_endpoint_has_a_way_in.py` and the orphan guard that
imports it both ask one question — does the product call this endpoint — and
until 16-09-2026 they answered it by concatenating every .ts/.tsx in both
frontends into a single 7 MB string and searching that. `lib/api/index.ts` is
5,025 lines of that string and names 371 distinct URLs, so an endpoint was
"reached" the moment somebody wrote an api-client method for it. Whether a
screen ever called the method made no difference at all.

That is the failure the whole safety net exists to prevent, one level up:
133 of 159 route pages could be deleted outright with the orphan guard
reporting nothing.

THE RULE, WHICH IS THE DURABLE HALF

    A URL literal counts only where a SCREEN can reach it.

Files under `app/` and `components/` are screens and count whole. Everything
under `lib/` is cut into units — each top-level declaration, and for the api
client each `namespace.method` member — and a unit joins only when live code
NAMES it, to a fixed point.

This file pins that rule against a frontend built in a temporary directory,
so it tests the RULE rather than today's tree: the real one changes every
week and an assertion about `api.notifications.count` would be wrong the day
somebody wires it up. The last test is the only one that touches the real
tree, and it asserts a shape — that attribution removes something — for the
same reason.
"""
from __future__ import annotations

import pathlib

import pytest

from tests.test_every_mounted_endpoint_has_a_way_in import (
    _frontend_files,
    _screens_and_units,
    _sources,
    WEB,
)

API_CLIENT = """\
import { supabase } from "@/lib/supabase/client";

const BASE_URL = "http://localhost:8000";

export const api = {
  ledger: {
    called: () => request("/api/reached-through-a-called-member"),
    uncalled: () => request("/api/reached-by-nobody"),
  },
  loose: () => request("/api/a-bare-member-on-api"),
};
"""

DATA_MODULE = """\
import { api } from "@/lib/api";

function helper(id: string) {
  return request(`/api/deep/${id}/working`);
}

export async function calledByAScreen(id: string) {
  return helper(id);
}

export async function neverCalled(id: string) {
  return request(`/api/never/${id}`);
}
"""

SCREEN = """\
"use client";
import { api } from "@/lib/api";
import { calledByAScreen } from "@/lib/data/thing";

export default function Page() {
  api.ledger.called();
  api.loose();
  calledByAScreen("x");
  fetch("/api/written-into-the-screen-itself");
  return null;
}
"""


@pytest.fixture(scope="module")
def frontend(tmp_path_factory) -> str:
    root = tmp_path_factory.mktemp("frontend")
    (root / "app" / "thing").mkdir(parents=True)
    (root / "lib" / "api").mkdir(parents=True)
    (root / "lib" / "data").mkdir(parents=True)
    (root / "components").mkdir(parents=True)
    (root / "lib" / "api" / "index.ts").write_text(API_CLIENT)
    (root / "lib" / "data" / "thing.ts").write_text(DATA_MODULE)
    (root / "app" / "thing" / "page.tsx").write_text(SCREEN)
    (root / "lib" / "data" / "thing.test.ts").write_text(
        'it("x", () => request("/api/named-only-by-a-test"));\n')
    return _sources((root,))


def test_a_screen_writing_the_url_itself_is_reached(frontend):
    assert "/api/written-into-the-screen-itself" in frontend


def test_an_api_client_member_a_screen_calls_is_reached(frontend):
    assert "/api/reached-through-a-called-member" in frontend


def test_an_api_client_member_nobody_calls_is_not(frontend):
    """The point of the file.

    `api.ledger.uncalled` sits two lines below `api.ledger.called` in the same
    namespace of the same file. Under the concatenation the two were the same
    thing.
    """
    assert "/api/reached-by-nobody" not in frontend


def test_a_bare_member_on_api_itself_is_reached(frontend):
    """`api.search` is not inside a namespace, and dropping it would report a
    live endpoint as orphaned."""
    assert "/api/a-bare-member-on-api" in frontend


def test_a_lib_function_is_followed_through_a_private_helper(frontend):
    """The screen names `calledByAScreen`; the URL is one hop further in."""
    assert "/api/deep/" in frontend


def test_a_lib_function_nobody_calls_is_not_reached(frontend):
    assert "/api/never/" not in frontend


def test_a_test_file_cannot_make_an_endpoint_look_reachable(frontend):
    assert "/api/named-only-by-a-test" not in frontend


def test_components_are_screens_too():
    """A shared editor under `components/` is where half this product's calls
    live; treating it as a library would orphan every one of them."""
    folders = {folder for folder, _ in _frontend_files((WEB,))}
    assert {"app", "components", "lib"} <= folders
    screens, _ = _screens_and_units((WEB,))
    assert len(screens) > 300, (
        "the screen seed collapsed — every lib unit would then look dead and "
        "the guards that import this would report hundreds of false losses")


def test_attribution_actually_removes_something_from_the_real_tree():
    """A shape assertion, deliberately, and not a named endpoint.

    Naming one would be wrong the day it is wired up — which is the outcome
    this whole file is for. What must stay true is that the attributed text is
    a strict subset: the moment every api-client member is in it, `_sources()`
    has quietly reverted and every guard built on it is answering the old
    question again.
    """
    attributed = _sources()
    _, units = _screens_and_units((WEB,))
    members = [(name, body) for rel, name, body in units
               if name is not None and "." in name
               and rel.endswith("lib/api/index.ts")]
    assert len(members) > 400, (
        f"the api client cut into {len(members)} members — it holds over 500, "
        f"so the object walk has stopped part way and everything after it is "
        f"silently uncut")
    dropped = [name for name, body in members
               if body not in attributed and "/api/" in body]
    assert dropped, (
        "every single api-client member that names a URL is in the attributed "
        "text. On a client this size that means the cut or the fixed point has "
        "stopped discriminating, and the guards built on _sources() are back "
        "to asking whether the URL is written down anywhere.")
