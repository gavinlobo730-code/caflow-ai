"""No route is answered by a different, earlier-registered route.

Starlette matches routes in REGISTRATION ORDER and the first full match wins.
So a static path registered after a parameterised sibling that also matches it
is unreachable — its handler never runs, and the parameterised one runs with
the static segment as its id:

  * `GET /api/gst-workspace/gstr1/{return_id}` sat above `/gstr1/amendments`,
    `/gstr1/exceptions` and `/gstr1/advances`, so all three ran `get_gstr1`
    as a lookup for a return whose id was "advances" — PostgREST 400'd on the
    invalid uuid and the screen showed "Unable to complete GST operation".
  * `GET /api/vendors/{vendor_id}` sat above `/ap-aging`, so the payables
    ageing looked up a vendor called "ap-aging".

Both were found in production on 27-09-2026. No test caught them because a test
that calls the handler FUNCTION bypasses the router's ordering entirely.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Route

_PARAM = re.compile(r"\{([^}:]+)(:[^}]+)?\}")


def _sample(path: str) -> str:
    """A concrete URL for `path`: each parameter replaced by a token no static
    segment in this codebase spells."""
    return _PARAM.sub(lambda m: "zzsample" + m.group(1), path)


def shadowed(app) -> list[tuple[str, str, list[str]]]:
    """(earlier path, shadowed path, methods) for every route whose own sample
    URL is matched first by an earlier route sharing a method."""
    routes = [r for r in app.routes if isinstance(r, (APIRoute, Route))]
    out = []
    for i, later in enumerate(routes):
        url = _sample(later.path)
        for earlier in routes[:i]:
            shared = set(earlier.methods or ()) & set(later.methods or ())
            if shared and earlier.path_regex.match(url):
                out.append((earlier.path, later.path, sorted(shared)))
                break
    return out


def test_no_route_in_the_application_is_shadowed():
    from main import app

    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    assert len(routes) > 800, len(routes)  # vacuity floor: the app really loaded
    found = shadowed(app)
    assert not found, "\n".join(
        f"{m} {later} is answered by the earlier {earlier} — register the "
        f"static route first" for earlier, later, m in found)


def test_the_rule_catches_a_static_route_below_its_parameterised_sibling():
    router = APIRouter(prefix="/api/vendors")

    @router.get("/{vendor_id}")
    def one(vendor_id: str):  # pragma: no cover - never called
        return vendor_id

    @router.get("/ap-aging")
    def ageing():  # pragma: no cover
        return {}

    app = FastAPI()
    app.include_router(router)
    assert shadowed(app) == [("/api/vendors/{vendor_id}", "/api/vendors/ap-aging", ["GET"])]


def test_the_rule_is_quiet_when_the_static_route_comes_first_or_the_method_differs():
    router = APIRouter(prefix="/api/x")

    @router.get("/ap-aging")
    def ageing():  # pragma: no cover
        return {}

    @router.get("/{item_id}")
    def one(item_id: str):  # pragma: no cover
        return item_id

    @router.post("/bulk")
    def bulk():  # pragma: no cover - POST, so GET /{item_id} cannot shadow it
        return {}

    @router.get("/{item_id}/statement")
    def statement(item_id: str):  # pragma: no cover - deeper path, no clash
        return item_id

    app = FastAPI()
    app.include_router(router)
    assert shadowed(app) == []


def test_premise_starlette_really_does_answer_with_the_first_match():
    from fastapi.testclient import TestClient

    router = APIRouter()

    @router.get("/v/{vendor_id}")
    def one(vendor_id: str):
        return {"handler": "get_vendor", "id": vendor_id}

    @router.get("/v/ap-aging")
    def ageing():  # pragma: no cover - that is the point
        return {"handler": "ap_aging"}

    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/v/ap-aging").json() == {"handler": "get_vendor", "id": "ap-aging"}
