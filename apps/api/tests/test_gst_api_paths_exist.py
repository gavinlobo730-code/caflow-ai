"""Every /api/… path apps/web/lib/data/gst.ts calls must be a real route.

WHAT THIS CATCHES
    routers/gst_workspace.py mounts under /api/gst-workspace; routers/gst.py
    mounts under /api/gst. Two GST routers, two prefixes, one letter of
    difference in the obvious guess. A frontend call written against the wrong
    one is a 404 at runtime and nothing at build time: the path is a template
    string, so tsc has nothing to check, and the backend suite never reads the
    frontend.

    The Rule 37 fetcher was written as /api/gst/itc/rule37 and the route is
    /api/gst-workspace/itc/rule37. Caught here before it shipped.

    Sibling of test_gstr3b_screen_contract.py: same failure shape — a frontend
    assumption about the backend that neither side's tooling can see — checked
    from the side that knows the answer.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
GST_DATA = WEB / "lib" / "data" / "gst.ts"

pytestmark = pytest.mark.skipif(not GST_DATA.is_file(),
                                reason="needs apps/web/lib/data/gst.ts")


def _code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _called_paths() -> set[str]:
    """The /api/... paths passed to apiGet/apiPost, query strings stripped.

    Only literal prefixes are readable: `/api/x/y?client_id=${id}` yields
    /api/x/y. A path assembled entirely from variables would not appear, and
    that is a limitation to know about rather than one to paper over.
    """
    code = _code_only(GST_DATA.read_text(encoding="utf-8"))
    out = set()
    for m in re.finditer(r"api(?:Get|Post)<[^>]*>\(\s*[`\"']([^`\"'$?]+)", code):
        out.add(m.group(1).rstrip("/"))
    return out


@pytest.fixture(scope="module")
def registered() -> set[str]:
    from main import app
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_the_scan_finds_the_calls():
    """Guard: an empty set would make the assertion below hold for any app."""
    paths = _called_paths()
    assert len(paths) >= 3, f"only found {sorted(paths)}"
    assert "/api/gst-workspace/itc/rule37" in paths, sorted(paths)
    assert "/api/gst/gstr3b/from-books" in paths, sorted(paths)


def test_both_gst_prefixes_really_are_different(registered):
    """If the two routers shared a prefix, the check below would pass on a
    wrong-prefix path and prove nothing."""
    assert "/api/gst/gstr3b/from-books" in registered
    assert "/api/gst/itc/rule37" not in registered, (
        "the workspace router now also answers under /api/gst — this test's "
        "premise no longer holds and it should be revisited")


def test_every_path_the_frontend_calls_is_registered(registered):
    missing = sorted(p for p in _called_paths() if p not in registered)
    assert not missing, (
        f"apps/web/lib/data/gst.ts calls paths the API does not serve: {missing}. "
        "Every one of these is a 404 the moment a CA clicks the button.")
