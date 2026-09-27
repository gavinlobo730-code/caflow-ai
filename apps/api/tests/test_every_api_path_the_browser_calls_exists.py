"""Every /api path the frontend names is served by a route the app mounts.

The Compliance Calendar called GET /api/mca/calendar/firm on every load. The
route is /api/mca-workspace/calendar/firm, so every call 404'd and the three
MCA deadlines it exists to show silently never appeared
(home-and-global-nav-05). test_every_mounted_endpoint_has_a_way_in.py guards
the OTHER direction — a route nothing calls — and could not see this one.

A path literal's `${…}` interpolations are read as one path segment each. A
literal whose tail is built at runtime (a variable suffix, a string split
across lines) cannot be checked statically; the few that exist are listed in
DYNAMIC with the reason, and the list is asserted to still match something,
so it cannot outlive the code it describes.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
_LITERAL = re.compile(r"""[`'"](/api/[^`'"\s]*)""")
_INTERP = re.compile(r"\$\{[^}]*\}")

# Normalised path -> why a static scan cannot resolve it.
DYNAMIC = {
    "/api/audit/entity/zz": "lib/api builds the tail across a line break "
                            "(`/api/audit/entity/${type}/` + `${id}`)",
    "/api/income-tax/presumptive/zz": "the scheme is one of 44ad/44ada/44ae, each "
                                      "its own route",
    "/api/recurring-invoices/zz/zz": "`${action}` is pause/resume/archive, each its "
                                     "own route",
    "/api/tds/26q/compute": "named in a doc comment in lib/data/tds.ts, not called",
    "/api/year-end/zz/exports/zz": "`${path}` is financial-statements/notes/"
                                   "complete-pack, each its own route",
}


def _called_paths() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in list(_WEB.rglob("*.ts")) + list(_WEB.rglob("*.tsx")):
        s = str(p)
        if any(x in s for x in ("node_modules", "/.next/", "/out/")) or s.endswith(".test.ts"):
            continue
        for m in _LITERAL.finditer(p.read_text(errors="ignore")):
            path = _INTERP.sub("zz", m.group(1).split("?")[0])
            if "${" in path:
                continue
            path = path.rstrip("/") or path
            out.setdefault(path, set()).add(str(p.relative_to(_WEB)))
    return out


@pytest.fixture(scope="module")
def routes():
    from fastapi.routing import APIRoute
    from main import app
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _served(path: str, routes) -> bool:
    return any(r.path_regex.match(path) or r.path_regex.match(path + "/") for r in routes)


def test_the_scan_sees_the_frontend():
    assert len(_called_paths()) > 300


def test_every_path_the_browser_names_is_served(routes):
    dead = {p: sorted(files) for p, files in _called_paths().items()
            if p not in DYNAMIC and not _served(p, routes)}
    assert not dead, "\n".join(f"{p}  <- {', '.join(f)}" for p, f in sorted(dead.items()))


def test_every_dynamic_entry_still_describes_real_code():
    called = _called_paths()
    stale = [p for p in DYNAMIC if p not in called]
    assert not stale, f"DYNAMIC entries no longer in the frontend: {stale}"


def test_the_rule_catches_the_calendar_path_it_was_written_for(routes):
    assert not _served("/api/mca/calendar/firm", routes)
    assert _served("/api/mca-workspace/calendar/firm", routes)
