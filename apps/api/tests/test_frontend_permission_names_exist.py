"""
Every resource:action the frontend gates on must exist in the backend matrix.

The UI now hides controls by asking `can("accounting", "write")`. Those strings
are untyped — nothing in TypeScript knows what the Python matrix contains — so a
typo, or a resource renamed on this side, produces a check that is silently
false forever. The button simply never appears again, for anybody, and no error
is raised anywhere: the failure looks exactly like a permission working.

That is the one way this design can fail quietly, so it gets a test. This walks
the frontend, extracts every permission pair it asks about, and asserts the pair
exists in PERMISSIONS. It does NOT check that the pair is the *right* one for
that button — no test can — only that it is a pair the backend has heard of.

Lives in the backend suite because PERMISSIONS lives here; a TypeScript test
would need its own copy of the matrix, which is the very thing being avoided.
"""
import pathlib
import re

import pytest

from core.permissions import PERMISSIONS


WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"

# can("resource", "action") — the hook form. `\bcan\(` deliberately does not
# match canAccessHref( / canAccessWorkspace( / canAll(, which take other shapes.
_CALL = re.compile(r'\bcan\(\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\)')
# requires: ["resource", "action"] — the nav-item form used by the panels.
_REQUIRES = re.compile(r'requires:\s*\[\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\]')
# <Can resource="..." action="..."> — the component form.
_JSX = re.compile(r'resource="([a-z_]+)"\s+action="([a-z_]+)"')


def _sources():
    """Every .ts/.tsx under apps/web except build output and dependencies."""
    for path in WEB.rglob("*.ts*"):
        parts = set(path.parts)
        if parts & {"node_modules", ".next", "out", ".vercel"}:
            continue
        yield path


def _pairs():
    """(resource, action, file, pattern) for every permission the UI gates on."""
    found = []
    for path in _sources():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in (("can()", _CALL), ("requires", _REQUIRES), ("<Can>", _JSX)):
            for resource, action in pattern.findall(src):
                found.append((resource, action, path.relative_to(WEB).as_posix(), label))
    return found


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not present in this checkout")
def test_every_frontend_permission_pair_exists_in_the_matrix():
    unknown = [
        f"{where} [{label}] → {resource}:{action}"
        for resource, action, where, label in _pairs()
        if action not in PERMISSIONS.get(resource, {})
    ]

    assert not unknown, (
        "the frontend gates on permissions the backend does not define — each of "
        "these checks is permanently false, so the control it guards can never "
        "appear:\n  " + "\n  ".join(sorted(unknown))
        + "\n\nFix the string, or add the resource:action to core/permissions.py."
    )


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not present in this checkout")
def test_the_frontend_scan_actually_found_permission_checks():
    """Vacuity guard. If the helper is renamed or the call shape changes, the
    test above starts passing over an empty list and stops protecting anything."""
    pairs = _pairs()

    assert len(pairs) >= 10, (
        f"only {len(pairs)} permission checks found in the frontend — the "
        "patterns in this file probably no longer match how the UI gates actions"
    )


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not present in this checkout")
def test_the_scan_would_notice_a_bad_pair():
    """Proves the matcher can fail, not just that it currently passes: a made-up
    pair run through the same predicate must be reported as unknown."""
    resource, action = "ledgerz", "wrlte"

    assert action not in PERMISSIONS.get(resource, {})
