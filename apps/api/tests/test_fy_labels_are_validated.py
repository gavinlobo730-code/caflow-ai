"""
Every financial-year label entering the API goes through one validated type.

WHAT WAS WRONG
    An Indian financial year is written '2026-27'. Fifty-six route parameters
    and request-model fields took one as a bare `str`, and every one handed it
    to code that reads the FIRST FOUR CHARACTERS and ignores the rest. So
    '2026-28' and '2026-99' were accepted and silently meant 2026-27 — stored
    on the row, and shown back to the CA as confirmation. '2026' meant it too.
    'garbage' raised ValueError out of the domain layer and reached the CA as
    a 500.

    ONE endpoint had a shape regex, ^\\d{4}-\\d{2}$, which '2026-28' passes.
    That is the whole problem in miniature: the shape is not the rule.

WHY A RATCHET AND NOT JUST TESTS FOR THE FIX
    Fifty-six is too many to keep right by hand, and the next endpoint is
    written by someone who has not read this file. So the rule is the
    annotation — `fy: FYLabel` — and this module fails if a new financial-year
    parameter goes in as a bare `str`.
"""
import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from core.ist_clock import ist_fy_label, normalise_fy_label
from main import app
from models.fy import FYLabel, OptionalFYLabel

pytestmark = pytest.mark.usefixtures("dev_header_auth")

API = pathlib.Path(__file__).resolve().parent.parent
FY_NAMES = {"financial_year", "fy", "to_fy", "target_financial_year"}
FY_TYPES = {"FYLabel", "OptionalFYLabel"}


def _sources():
    return sorted((API / "routers").glob("*.py")) + sorted((API / "models").glob("*.py"))


def _entry_points():
    """Every place a financial-year label crosses into the API.

    Two shapes, and only two: a field on a pydantic request model, and a
    parameter of a routed function. A plain helper's `fy: str` is NOT an
    entry point — nothing validates a function call, and annotating one with
    a pydantic type would look like a guard while doing nothing."""
    found = []
    for path in _sources():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    "BaseModel" in ast.unparse(b) for b in node.bases):
                for stmt in node.body:
                    if (isinstance(stmt, ast.AnnAssign)
                            and isinstance(stmt.target, ast.Name)
                            and stmt.target.id in FY_NAMES):
                        found.append((path.name, stmt.lineno,
                                      f"{node.name}.{stmt.target.id}",
                                      ast.unparse(stmt.annotation), None))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco = " ".join(ast.unparse(d) for d in node.decorator_list)
                if "router." not in deco and "app." not in deco:
                    continue
                args = node.args
                positional = list(args.args)
                for arg in positional + list(args.kwonlyargs):
                    if arg.arg not in FY_NAMES or arg.annotation is None:
                        continue
                    default = None
                    if arg in positional:
                        i = positional.index(arg)
                        k = i - (len(positional) - len(args.defaults))
                        if k >= 0:
                            default = ast.unparse(args.defaults[k])
                    found.append((path.name, arg.lineno,
                                  f"{node.name}.{arg.arg}",
                                  ast.unparse(arg.annotation), default))
    return found


# ── The ratchet ──────────────────────────────────────────────────────────────

def test_there_are_entry_points_to_check():
    """A scan that silently finds nothing would pass every test below."""
    assert len(_entry_points()) >= 50


def test_every_financial_year_entry_point_uses_the_validated_type():
    bare = [f"{f}:{ln} {what} -> {ann}"
            for f, ln, what, ann, _ in _entry_points()
            if not any(t in ann for t in FY_TYPES)]
    assert not bare, (
        "a financial-year label is entering the API as a bare string. Annotate "
        "it `FYLabel` (or `OptionalFYLabel`) from models.fy so it is validated "
        "and canonicalised like every other one:\n  " + "\n  ".join(bare))


def test_query_never_sits_in_the_default_position():
    """THE TRAP, and the reason this test exists at all.

        fy: FYLabel = Query(...)          <- reads correctly, validates NOTHING
        fy: Annotated[FYLabel, Query()]   <- validates

    FastAPI builds the field from `Query()` when it is the default, and the
    Annotated metadata carrying the validator is dropped. Nothing fails, no
    warning is issued, and the endpoint looks guarded in review. This was
    caught by probing the behaviour rather than trusting it, and the ratchet
    above would have passed happily either way."""
    broken = [f"{f}:{ln} {what}"
              for f, ln, what, ann, default in _entry_points()
              if default and "Query(" in default and any(t in ann for t in FY_TYPES)]
    assert not broken, (
        "Query() in the default position silently discards the validator. "
        "Move it inside: `Annotated[FYLabel, Query(...)]`:\n  " + "\n  ".join(broken))


def test_no_endpoint_still_relies_on_a_shape_regex():
    """^\\d{4}-\\d{2}$ accepts '2026-28'. A weaker check next to the real one
    is worse than none: a reviewer sees a pattern and stops looking."""
    for path in _sources():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if any(n in line for n in FY_NAMES) and r"\d{4}-\d{2}" in line:
                pytest.fail(f"{path.name}:{i} still shape-checks a financial year: {line.strip()}")


# ── What the type does ───────────────────────────────────────────────────────

class _Req(BaseModel):
    financial_year: FYLabel
    other: OptionalFYLabel = None


@pytest.mark.parametrize("given,canonical", [
    ("2026-27", "2026-27"),
    ("2026-2027", "2026-27"),     # a CA writes both
    (" 2026-27 ", "2026-27"),
    ("1999-00", "1999-00"),       # the century turn still pairs
])
def test_a_label_that_names_a_year_is_accepted_and_canonicalised(given, canonical):
    assert _Req(financial_year=given).financial_year == canonical


@pytest.mark.parametrize("bad", ["2026-28", "2026-99", "2026-26", "2026",
                                 "garbage", "", None, "26-27"])
def test_anything_that_is_not_a_financial_year_is_refused(bad):
    with pytest.raises(ValidationError):
        _Req(financial_year=bad)


def test_an_optional_label_may_be_absent_but_not_wrong():
    assert _Req(financial_year="2026-27", other=None).other is None
    assert _Req(financial_year="2026-27", other="").other is None, (
        "`?fy=` is the same statement as omitting it — the caller named no year")
    assert _Req(financial_year="2026-27", other="2025-2026").other == "2025-26"
    with pytest.raises(ValidationError):
        _Req(financial_year="2026-27", other="2025-27")


def test_a_required_label_does_not_get_the_blank_latitude():
    """Blank means 'no answer' for something optional and 'missing answer' for
    something required. Coercing a required label to None would push the
    failure downstream into `financial_year or _current_fy()`."""
    with pytest.raises(ValidationError):
        _Req(financial_year="")


def test_the_current_label_is_one_the_type_accepts():
    """ist_fy_label is what every `or _current_fy()` fallback produces. If the
    validator and the generator disagreed about the shape, the default itself
    would be unusable."""
    assert normalise_fy_label(ist_fy_label()) == ist_fy_label()


# ── Through the real app ─────────────────────────────────────────────────────

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}


@pytest.mark.parametrize("url", [
    "/api/accounting/schedule-iii/ratios?client_id=client-001&fy={fy}",
    "/api/accounting/schedule-iii/trend?client_id=client-001&to_fy={fy}",
    "/api/accounting/statement-analysis?financial_year={fy}",
    "/api/payroll/declarations?client_id=client-001&fy={fy}",
    "/api/timeline?client_id=client-001&financial_year={fy}",
    "/api/year-end/engagements?financial_year={fy}",
    "/api/income-tax/advance-tax?client_id=client-001&fy={fy}",
])
def test_a_year_that_does_not_exist_is_refused_at_the_edge(url):
    """'2026-28' is the case a shape regex waves through. Whatever each of
    these endpoints does downstream, none of them should get that far."""
    res = client.get(url.format(fy="2026-28"), headers=HEADERS)
    assert res.status_code == 422, f"{url} accepted a year that does not exist: {res.text[:200]}"


@pytest.mark.parametrize("url", [
    "/api/timeline?client_id=client-001&financial_year={fy}",
    "/api/year-end/engagements?financial_year={fy}",
])
def test_a_real_year_still_gets_through(url):
    res = client.get(url.format(fy="2025-26"), headers=HEADERS)
    assert res.status_code == 200, res.text
