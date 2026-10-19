"""Every GST return period entering the API goes through one validated type.

WHAT WAS WRONG
    A GST return period is written MMYYYY ('042026'). 27 route parameters and request-model fields took one as a plain
    string. Where it reached `return_period.parse_month`, which raises ValueError for anything that is not a month,
    '2026-04', '4/2026' and a month 13 reached the CA as a 500; '010000' was accepted and failed later, when a date was
    built from it; where it was only a key (`itc/register`) it was not checked at all. Four query parameters had
    `pattern=r"^\\d{6}$"`, which '139999' satisfies: the shape is not the rule. Found by filing a seeded year through the
    workspace doors.

WHAT IS HELD
    * `PeriodMMYYYY` / `OptionalPeriodMMYYYY` (models/gst_period.py) apply `parse_month`'s own rule and a sanity bound on the
      year, and are the only spelling: every `period` entry point in the routers and models is either typed or listed below
      with the reason it is not a GST return period;
    * every route and request model that takes one answers a malformed value with a 422 that names `period`;
    * the OpenAPI document keeps every period parameter REQUIRED (the typed spelling is keyword-only and has no default: a
      default of `...` makes a required parameter optional under this FastAPI, see b70).
"""
import ast
import pathlib

import pytest
from fastapi.testclient import TestClient

from main import app
from models.gst_period import OptionalPeriodMMYYYY, normalise_return_period

pytestmark = pytest.mark.usefixtures("dev_header_auth")

API = pathlib.Path(__file__).resolve().parent.parent

#: Entry points named like a period that are NOT a GST return period, with the reason. Anything not here is held to the type.
EXEMPT = {
    ("routers/analytics.py", "profitability_analytics"): "a relative window ('month', 'quarter'), not a return period",
    ("routers/analytics.py", "fee_concentration"): "a relative window",
    ("routers/analytics.py", "revenue_vs_effort"): "a relative window",
    ("routers/billing.py", "generate"): "a billing month, YYYY-MM",
    ("routers/fixed_assets.py", "reverse_depreciation"): "a depreciation month, YYYY-MM",
    ("routers/time_tracking.py", "my_summary"): "a relative window ('week')",
    ("routers/gst_portal.py", "ManualSnapshotRequest"): "free-form: a portal snapshot's own label, not read as a month",
    ("routers/mca_workspace.py", "CreateFilingRequest"): "an MCA form's period, whatever the form calls it",
    ("models/accounting.py", "DepreciationIn"): "a depreciation month, YYYY-MM",
    ("models/accounting.py", "DepreciationRunIn"): "depreciation months, YYYY-MM",
}
NAMES = {"period", "return_period", "from_period", "to_period", "tax_period"}
TYPES = {"PeriodMMYYYY", "OptionalPeriodMMYYYY"}


def _entry_points():
    """(file, owner, name, annotation) for every place a period crosses into the API: a field on a pydantic request model, or
    a parameter of a routed function. A plain helper's `period: str` is not an entry point: nothing validates a call."""
    found = []
    http = {"get", "post", "put", "patch", "delete"}
    for path in sorted((API / "routers").glob("*.py")) + sorted((API / "models").glob("*.py")):
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(API))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any("BaseModel" in ast.unparse(b) for b in node.bases):
                for st in node.body:
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id in NAMES:
                        found.append((rel, node.name, st.target.id, ast.unparse(st.annotation), st.lineno))
            if isinstance(node, ast.FunctionDef) and any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in http
                    for d in node.decorator_list):
                for arg in node.args.args + node.args.kwonlyargs:
                    if arg.arg in NAMES:
                        found.append((rel, node.name, arg.arg, ast.unparse(arg.annotation) if arg.annotation else "", arg.lineno))
    return found


# ── the type ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["042026", "122025", "012000", "032099", " 042026 "])
def test_a_month_and_a_year_pass_and_come_back_canonical(value):
    assert normalise_return_period(value) == value.strip()


@pytest.mark.parametrize("value", [
    "2026-04", "4/2026", "april", "42026", "0420266", "", " ", "139999", "000000", "132026", "010000", "041999", "042100",
    "04 2026", "04202a", "٠٤٢٠٢٦", "０４２０２６",
])
def test_anything_that_is_not_a_month_of_this_century_is_refused(value):
    with pytest.raises(ValueError):
        normalise_return_period(value)


@pytest.mark.parametrize("value", [42026, 42026.0, None, ["042026"], True])
def test_only_a_string_is_a_period(value):
    with pytest.raises(ValueError):
        normalise_return_period(value)


def test_the_optional_type_reads_blank_as_not_said_and_still_refuses_a_bad_one():
    from pydantic import BaseModel, ValidationError

    class M(BaseModel):
        period: OptionalPeriodMMYYYY = None

    assert M().period is None and M(period=None).period is None and M(period="  ").period is None
    assert M(period="042026").period == "042026"
    with pytest.raises(ValidationError):
        M(period="2026-04")


def test_the_type_uses_the_engines_own_parser_and_not_a_second_one():
    """A rule restated here would drift from the one the engine applies; the refusal text is the engine's, wrapped."""
    from domain.gst import return_period
    for bad in ("139999", "2026-04", "00"):
        with pytest.raises(ValueError):
            return_period.parse_month(bad)
        with pytest.raises(ValueError):
            normalise_return_period(bad)


# ── the rule: typed, or exempt with a reason ────────────────────────────────

def test_every_period_entry_point_is_typed_or_named_as_not_a_return_period():
    typed = {(f, o, n) for f, o, n, ann, _ in _entry_points() if any(t in ann for t in TYPES)}
    loose = [(f, o, n, ann, ln) for f, o, n, ann, ln in _entry_points()
             if not any(t in ann for t in TYPES) and (f, o) not in EXEMPT]
    assert not loose, (
        "A period crossing into the API as a bare `str` reaches the engine as a 500 when it is not a month. Annotate it "
        "`PeriodMMYYYY` (models/gst_period.py), or list it in EXEMPT with the reason it is not a GST return period:\n"
        + "\n".join(f"  {f}:{ln} {o}.{n}: {ann}" for f, o, n, ann, ln in loose))
    assert len(typed) >= 25, f"only {len(typed)} typed entry points found; the scan has gone blind"


def test_the_exemptions_still_exist():
    """An exemption whose entry point is gone, or has since been typed, is stale and says something false."""
    present = {(f, o): ann for f, o, n, ann, _ in _entry_points()}
    for key, reason in EXEMPT.items():
        assert key in present, f"{key} is exempt ({reason}) but is no longer an entry point"
        assert not any(t in present[key] for t in TYPES), f"{key} is typed now; remove it from EXEMPT"


def test_a_typed_required_query_parameter_is_keyword_only_with_no_default():
    """`period: PeriodMMYYYY = Query(...)` would validate nothing (the Annotated metadata is dropped when Query sits in
    the default), and `= ...` after `Annotated[..., Query()]` makes a required parameter optional under this FastAPI. The
    spelling is `*, period: Annotated[PeriodMMYYYY, Query(...)]`."""
    for path in sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for arg, default in zip(node.args.args[len(node.args.args) - len(node.args.defaults):], node.args.defaults,
                                    strict=True):
                if arg.annotation is not None and any(t in ast.unparse(arg.annotation) for t in TYPES) \
                        and arg.arg in NAMES:
                    pytest.fail(f"{path.name}:{arg.lineno} {node.name}({arg.arg}) has a default ({ast.unparse(default)}); "
                                "the typed period is keyword-only with none")


# ── what the doors answer ───────────────────────────────────────────────────

def _period_operations():
    """(method, path, where) for every operation whose query string or JSON body carries a `period`, read off the OpenAPI
    document the app serves. `where` is 'query' or 'body'."""
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    out = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if any(p["name"] == "period" and p["in"] == "query" for p in op.get("parameters", [])):
                out.append((method, path, "query"))
            body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
            ref = body.get("$ref", "").rsplit("/", 1)[-1]
            if ref and "period" in (schemas.get(ref, {}).get("properties") or {}):
                out.append((method, path, f"body:{ref}"))
    return out


def _is_exempt_operation(path: str, where: str) -> bool:
    exempt_models = {"ManualSnapshotRequest", "CreateFilingRequest", "DepreciationIn", "DepreciationRunIn"}
    if where.startswith("body:") and where.split(":", 1)[1].split("__")[-1] in exempt_models:
        return True
    return any(path.startswith(p) for p in ("/api/analytics", "/api/billing", "/api/fixed-assets", "/api/time"))


def test_the_scan_of_the_openapi_document_finds_the_operations_it_should():
    ops = [o for o in _period_operations() if not _is_exempt_operation(o[1], o[2])]
    assert len(ops) >= 25, f"only {len(ops)} GST period operations found: the scan has gone blind"


@pytest.mark.parametrize("bad", ["2026-04", "139999"])
def test_every_door_answers_a_malformed_period_with_a_422_that_names_it(bad):
    client = TestClient(app, raise_server_exceptions=False)
    failures = []
    for method, path, where in _period_operations():
        if _is_exempt_operation(path, where):
            continue
        url = path.replace("{", "x").replace("}", "")
        if where == "query":
            resp = client.request(method.upper(), url, params={"client_id": "c1", "period": bad, "line": "3.1a"})
        else:
            resp = client.request(method.upper(), url, json={"client_id": "c1", "period": bad})
        names_period = False
        if resp.status_code == 422:
            detail = resp.json().get("detail") or []
            names_period = any(isinstance(d, dict) and d.get("loc", [None])[-1] == "period" for d in detail)
        if not names_period:
            failures.append((method.upper(), path, where, resp.status_code))
    assert not failures, f"{len(failures)} door(s) did not refuse period={bad!r} with a 422 naming it: {failures}"


def test_the_500_that_started_this_is_a_422_now():
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/gst/gstr1/from-books", json={"client_id": "c1", "period": "2026-04"})
    assert resp.status_code == 422
    assert "MMYYYY" in resp.text


def test_a_good_period_is_not_refused_at_the_door():
    """Whatever the door answers next, it is not the period validator."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/gst/gstr1/from-books", json={"client_id": "c1", "period": "042026"})
    detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else None
    if resp.status_code == 422 and isinstance(detail, list):
        assert not any(d.get("loc", [None])[-1] == "period" for d in detail if isinstance(d, dict))


def test_every_period_parameter_is_still_required_in_the_document_the_app_serves():
    spec = app.openapi()
    for method, path, where in _period_operations():
        if where != "query" or _is_exempt_operation(path, where):
            continue
        param = next(p for p in spec["paths"][path][method]["parameters"] if p["name"] == "period")
        assert param["required"] is True, f"{method.upper()} {path}: period is optional in the served document"
