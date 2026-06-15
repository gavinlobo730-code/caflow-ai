"""
Production-readiness audit fixes — regression guards.

The Phase 14 routers (itr/xbrl/form-26as/einvoice/eway-bill/tally-migration/
gst-portal) existed but were never mounted in main.py, so their frontend pages
were dead 404s. This test fails if any of them is unmounted again.
"""
from main import app

_PREFIXES = [
    "/api/itr", "/api/xbrl", "/api/form-26as", "/api/einvoice",
    "/api/eway-bill", "/api/tally-migration", "/api/gst-portal",
]


def test_phase14_routers_are_mounted():
    paths = {getattr(r, "path", "") for r in app.routes}
    missing = [p for p in _PREFIXES if not any(path.startswith(p) for path in paths)]
    assert not missing, f"Phase 14 routers not mounted (dead frontend pages): {missing}"
