"""A parameter the API calls required is required, and its absence is a 422 and never a 500 (ledger, found by the seeded walk).

WHAT WAS WRONG
    Twenty-six routes took a financial-year (or accounting-year) label as
    `fy: Annotated[FYLabel, Query()] = ...`, a spelling this repository's own FY-label rule recommended "where argument
    order needs a default". Under the FastAPI this product is locked to (0.109.2) that spelling is NOT required: the
    published contract says `required: false`, the validator never runs on an absent value, and the handler is called
    with the literal `Ellipsis` as the year. So `GET /api/payroll/24q-source?client_id=…&quarter=Q2` answered
    "Internal server error" (`'ellipsis' object has no attribute 'split'`), the Form-based report-share route would have
    uploaded a workbook to storage before its insert failed on the same object, and the statement-analysis, GSTR-9,
    GSTR-4, GSTR-9C, Rule 37A, regime-election, self-assessment, advance-tax, bonus-register and TDS-projection screens
    all answered a missing year with a 500 and an error report each. Found by calling every read route of the real app
    over a seeded firm; nothing in the suite saw it because every test passed the year.

WHAT IS HELD
    * THE RULE, over the route table the app really serves and not over a list of spellings: no parameter of a routed
      function defaults to `...` unless it is a Pydantic body model (FastAPI reads `body: Model = ...` as required, which
      is proven below, and it is the one place the spelling is right);
    * the contract: every route parameter typed as a required year label is `required: true` in the OpenAPI document the
      app publishes, whether it travels as a query string or as a form field;
    * the behaviour: leaving the year out of each such route is a 422 that names the year, not a 500.
"""
from __future__ import annotations

import inspect
import typing

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator

from main import app
from models import fy as fy_module

pytestmark = pytest.mark.usefixtures("dev_header_auth")

HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}
client = TestClient(app, raise_server_exceptions=False)


def _routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _is_required_year(hint) -> bool:
    """True for `Annotated[str, BeforeValidator(models.fy._required_fy), …]` — FYLabel and AYLabel both."""
    return any(isinstance(m, BeforeValidator) and m.func is fy_module._required_fy
               for m in getattr(hint, "__metadata__", ()))


def _year_parameters() -> list[tuple[APIRoute, str]]:
    found = []
    for route in _routes():
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        for name, hint in hints.items():
            if name != "return" and _is_required_year(hint):
                found.append((route, name))
    return found


def test_no_parameter_defaults_to_the_ellipsis_except_a_body_model():
    offenders = []
    for route in _routes():
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        for name, p in inspect.signature(route.endpoint).parameters.items():
            if p.default is not Ellipsis:
                continue
            hint = hints.get(name)
            is_model = inspect.isclass(hint) and issubclass(hint, BaseModel)
            if not is_model:
                offenders.append(f"{sorted(route.methods)[0]} {route.path}  {name}")
    assert not offenders, (
        "a parameter written `= ...` is OPTIONAL under the FastAPI this product is locked to, and reaches the handler as "
        "the literal Ellipsis (a 500, or a write of 'Ellipsis'). Declare it with no default — keyword-only after a `*,` "
        f"when an earlier parameter has one: {offenders}")


def test_a_body_model_written_with_the_ellipsis_really_is_required():
    """The one place `= ...` is right, held so the rule above is not later widened or narrowed on a guess."""
    for path, method in (("/api/recurring-journals/{template_id}", "patch"), ("/api/billing/schedules/{schedule_id}", "patch")):
        body = app.openapi()["paths"][path][method]["requestBody"]
        assert body["required"] is True, path


def test_there_are_year_parameters_to_check():
    assert len(_year_parameters()) >= 40, "the scan found almost nothing, so the contract below would pass having checked nothing"


def _published_required(spec: dict, route: APIRoute, name: str) -> bool | None:
    """`required` as the published OpenAPI document says it, for a query/header/path parameter or a form field."""
    op = spec["paths"][route.path][sorted(m.lower() for m in route.methods if m not in ("HEAD", "OPTIONS"))[0]]
    for prm in op.get("parameters", []):
        if prm["name"] == name:
            return bool(prm.get("required"))
    content = (op.get("requestBody") or {}).get("content", {})
    for media in ("multipart/form-data", "application/x-www-form-urlencoded"):
        schema = (content.get(media) or {}).get("schema")
        if schema is None:
            continue
        if "$ref" in schema:
            schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
        if name in schema.get("properties", {}):
            return name in schema.get("required", [])
    return None


def test_every_required_year_parameter_is_published_as_required():
    spec = app.openapi()
    weak = []
    for route, name in _year_parameters():
        published = _published_required(spec, route, name)
        if published is not True:
            weak.append(f"{sorted(route.methods)[0]} {route.path}  {name}  published required={published}")
    assert not weak, f"typed as a required year but published as optional: {weak}"


def _url(route: APIRoute, spec: dict, omit: str) -> str:
    path = route.path
    for seg in [s[1:-1] for s in path.split("/") if s.startswith("{")]:
        path = path.replace("{" + seg + "}", "x")
    op = spec["paths"][route.path][sorted(m.lower() for m in route.methods if m not in ("HEAD", "OPTIONS"))[0]]
    query = {p["name"]: ("Q2" if p["name"] == "quarter" else "x")
             for p in op.get("parameters", []) if p["in"] == "query" and p.get("required") and p["name"] != omit}
    return path + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else "")


def _cases():
    return [pytest.param(sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))[0], r.path, name,
                         id=f"{sorted(r.methods)[0]} {r.path} {name}")
            for r, name in _year_parameters()]


@pytest.fixture()
def a_portal_employee():
    """The employee portal has its own door (a JWT that resolves to a payroll employee); without a stand-in the 403 comes
    before the request is validated, and the test would be about the door and not about the year."""
    from core.portal_auth import get_current_portal_employee
    app.dependency_overrides[get_current_portal_employee] = lambda: {"id": "e1", "firm_id": "firm-001", "client_id": "c1"}
    yield
    app.dependency_overrides.pop(get_current_portal_employee, None)


@pytest.mark.parametrize("method,path,name", _cases())
@pytest.mark.usefixtures("a_portal_employee")
def test_leaving_the_year_out_is_a_422_that_names_it(method, path, name):
    spec = app.openapi()
    route = next(r for r in _routes() if r.path == path and method in r.methods)
    url = _url(route, spec, omit=name)
    if method == "POST" and url and "multipart/form-data" in str(spec["paths"][path]["post"].get("requestBody", {})):
        res = client.post(url, headers=HEADERS, data={"client_id": "x", "report_id": "pl", "report_label": "P&L"},
                          files={"file": ("r.xlsx", b"x", "application/octet-stream")})
    else:
        res = client.request(method, url, headers=HEADERS)
    assert res.status_code == 422, (url, res.status_code, res.text[:200])
    locs = [tuple(e["loc"]) for e in res.json()["detail"]]
    assert any(loc[-1] == name for loc in locs), (url, locs)
