"""The browser drive's fallback permission map is the Partner map `core/permissions.py` gives.

The money-editor drive's stub (`apps/web/scripts/drive/stub.mjs`) answers an
unrouted `GET /api/identity/permissions` with
`apps/web/scripts/drive/partner-permissions.json`, because a screen now offers
a write button only when that map admits it (`usePermissions().can`), and a
stub that answered the read with `[]` hid every button from every scenario
that had not routed the map itself (107 scenarios failed on 17-11-2026).

A hand-written copy of the matrix in the drive would drift from the one in
Python, and a drive that offered a Partner a button the backend refuses (or
hid one it admits) would drive a screen nobody sees. So the file is the
generator's output and this test holds it there; when it fails, run
`python3 scripts/write_drive_permission_fixture.py` from `apps/api`.
"""
from __future__ import annotations

import json
import pathlib

from core.permissions import get_accessible_resources

FIXTURE = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "partner-permissions.json"
STUB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web" / "scripts" / "drive" / "stub.mjs"


def test_the_fixture_is_the_partner_map():
    served = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = {r: sorted(a) for r, a in get_accessible_resources("Partner").items()}
    assert {r: sorted(a) for r, a in served.items()} == expected, (
        "apps/web/scripts/drive/partner-permissions.json is not the Partner map core/permissions.py gives; "
        "run `python3 scripts/write_drive_permission_fixture.py` from apps/api"
    )


def test_the_fixture_is_not_empty():
    # An empty map would pass the equality above only if the matrix were empty; say so separately, because an
    # empty map is what makes every button vanish.
    served = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert served.get("accounting") and "write" in served["accounting"]


def test_the_stub_reads_the_fixture():
    source = STUB.read_text(encoding="utf-8")
    assert "partner-permissions.json" in source, "stub.mjs no longer serves the generated Partner map"
