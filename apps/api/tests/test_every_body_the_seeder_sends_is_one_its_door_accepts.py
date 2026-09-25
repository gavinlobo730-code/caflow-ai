"""Run the seeder against the app's OWN ROUTE TABLE and validate every body.

── WHAT THIS CATCHES THAT NOTHING ELSE DOES ─────────────────────────────────
`scripts/seed_demo_firm.py` sent a payroll employee as

    {"date_of_joining": ..., "hra_paise": ...}

and `models.payroll.EmployeeIn` declares `joining_date` and `hra_percent`.
Pydantic ignores an unknown field, so the request was accepted, the employee
was stored with NO joining date and NO house rent allowance, and nothing
anywhere said so. Two fields, silently dropped, on the master data a §192
withholding is computed from.

A test that reads the seeder cannot see that, and `test_the_seeder_actually_
seeds.py` — which really does POST through the routers — cannot either,
because payroll's mock branches answer `{"id": "mock-id"}` and
`{"id": "mock-run"}` CONSTANTS. Twelve months of a roster cannot be walked
there: the second attendance row collides with the first on the same id.

So this module runs `seed()` against a recorder that answers plausibly and
checks each body against **the request model FastAPI itself resolved for that
path**. No hand-written path→model map: the map is `app.routes`, so a door
added tomorrow is covered the day it is written, and a body sent to a path
that does not exist is a failure rather than a 404 nobody ran.

⚠️ WHAT IT DOES NOT PROVE. Nothing here executes a router body, so it says
nothing about rbac, the catalogue gate, the invoice-series rule or the order
the doors must be called in — that is exactly what the TestClient module next
to it is for. The two are complementary and neither replaces the other.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from domain.demo import fixture

_API_ROOT = Path(__file__).resolve().parents[1]


def _seeder():
    """The script, imported by path — it lives in `scripts/`, which is not a
    package, and copying its logic here would test the copy."""
    spec = importlib.util.spec_from_file_location(
        "seed_demo_firm", _API_ROOT / "scripts" / "seed_demo_firm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _doors(app) -> list[tuple[str, re.Pattern, type | None]]:
    """(method, path regex, request model or None) for every route in the app.

    Read off `route.dependant.body_params` rather than a list written here.
    THAT is the rule: the app decides what a path accepts, and a map in a test
    is one rename away from asserting nothing.

    ⚠️ EVERY route is listed, model or not, and the two are told apart by the
    THIRD element. The first draft listed only the doors that take a body, so
    a path with no validated body — `POST /runs/{id}/finalize`, whose
    `Optional[ReleaseIn] = None` FastAPI resolves to no body param at all —
    came back as *this path does not exist*, which is a different and much
    more alarming claim than the truth."""
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        params = [p for p in route.dependant.body_params
                  if getattr(p, "type_", None) is not None]
        model = params[0].type_ if len(params) == 1 else None
        if model is not None and not hasattr(model, "model_validate"):
            model = None                   # a scalar body, nothing to check
        for method in route.methods:
            out.append((method, route.path_regex, model))
    return out


class _Recorder:
    """The seeder's `Api` surface. Answers plausibly; validates on the way in.

    The answers are deliberately GENEROUS — a unique id and a `total_paise` on
    every response — because the point is to walk every branch of the seeder,
    including the ones a real refusal would cut short. What is STRICT is the
    request."""

    def __init__(self, models):
        self.models = models
        self.calls: list[tuple[str, str]] = []
        self.unmatched: list[tuple[str, str]] = []
        self.invalid: list[str] = []
        self._n = 0

    def _door_for(self, method: str, path: str):
        """(matched, model). `matched` False means no route serves this path
        at all; a model of None means the route exists and declares no body
        this test can check."""
        for m, rx, model in self.models:
            if m == method and rx.fullmatch(path):
                return True, model
        return False, None

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path))
        return {"success": True, "data": [], "error": None}

    def post(self, path: str, body: dict) -> dict:
        return self._write("POST", path, body)

    def put(self, path: str, body: dict) -> dict:
        return self._write("PUT", path, body)

    def _write(self, method: str, path: str, body: dict) -> dict:
        self.calls.append((method, path))
        matched, model = self._door_for(method, path)
        if not matched:
            self.unmatched.append((method, path))
        elif model is not None:
            try:
                model.model_validate(body)
            except ValidationError as e:
                self.invalid.append(
                    f"{method} {path} -> {model.__name__}: {e.errors()[:3]}")
            # A field the MODEL does not declare is dropped in silence by
            # Pydantic, which is the whole defect this module exists for.
            unknown = set(body) - set(model.model_fields)
            if unknown:
                self.invalid.append(
                    f"{method} {path} -> {model.__name__} has no field(s) "
                    f"{sorted(unknown)}; Pydantic would DROP them and the "
                    f"request would still succeed.")
        self._n += 1
        return {"success": True, "error": None, "data": {
            "id": f"seeded-{self._n:05d}",
            # Every figure the seeder reads back off a response. Plausible
            # rather than computed — nothing here is an accounting claim.
            "total_paise": 118_000_00,
            "months_posted": 1, "remaining_months": 0,
            "imported": 1, "drafted": 1, "remaining": 0,
        }}


@pytest.fixture(scope="module")
def _run():
    from main import app
    seeder = _seeder()
    rec = _Recorder(_doors(app))
    seeder.seed(rec, fixture.build(), add_to_existing=False)
    return rec


def test_every_path_the_seeder_posts_to_exists(_run):
    assert not _run.unmatched, (
        "the seeder writes to paths this app does not serve:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in sorted(set(_run.unmatched))))


def test_every_body_satisfies_the_model_its_door_declares(_run):
    assert not _run.invalid, "\n  ".join([""] + sorted(set(_run.invalid)))


#: The doors this tranche added. Named because the previous run of the seeder
#: never reached any of them — a body-shape check that silently walked past
#: the payroll leg would be exactly as vacuous as the fixture tests were.
_DOORS_THIS_SEEDER_MUST_WALK = [
    ("POST", "/api/banking/accounts"),
    ("POST", "/api/banking/statements/import"),
    ("POST", "/api/banking/entries/redraft"),
    ("POST", "/api/fixed-assets"),
    ("POST", "/api/fixed-assets/run-depreciation"),
    ("PUT", "/api/payroll/enablement"),
    ("POST", "/api/payroll/employees"),
    ("PUT", "/api/payroll/attendance"),
    ("POST", "/api/payroll/runs"),
    # Not new, but newly REACHED: `msme_status` is not a field of `VendorIn`
    # and was being dropped, so every vendor was unclassified. It is recorded
    # through the ageing screen's own door, which answers 503 with no
    # database — so this is the only place it can be checked at all.
    ("POST", "/api/accounting/schedule-iii/ageing/classify"),
]


@pytest.mark.parametrize("method,path", _DOORS_THIS_SEEDER_MUST_WALK)
def test_the_seeder_reaches_the_door(_run, method, path):
    assert (method, path) in _run.calls, f"{method} {path} was never called"


def test_a_run_is_finalized_and_disbursed(_run):
    """The two run-scoped doors, matched on SHAPE rather than on an id.

    A payroll month is only worth seeding if it is taken somewhere: a book of
    twelve drafts has posted no journal, paid nobody and left Salaries
    Expense nil."""
    finalized = [p for m, p in _run.calls
                 if m == "POST" and p.endswith("/finalize")]
    disbursed = [p for m, p in _run.calls
                 if m == "POST" and p.endswith("/disburse")]
    assert finalized, "no payroll run was finalized"
    assert disbursed, "no payroll run was disbursed"
    # One month is left a DRAFT and one finalized-but-unpaid, deliberately —
    # see fixture.DemoPayrollMonth. So neither count may equal the number of
    # runs created.
    runs = [p for m, p in _run.calls if m == "POST" and p == "/api/payroll/runs"]
    assert len(finalized) < len(runs), "every run was finalized; no draft is left to show"
    assert len(disbursed) < len(finalized), "every finalized run was paid"


def test_the_bank_statement_carries_no_line_for_money_already_recorded():
    """The decision in `fixture.DemoBankLine`, asserted rather than trusted.

    Passing a statement line CREATES a voucher, so a line for a receipt the
    ledger already holds invites the CA to record the same rupees twice. Every
    generated line is an OUTFLOW the books do not have; the only credits are
    added by the seeder, against invoices nobody paid.
    """
    firm = fixture.build()
    assert any(c.bank_lines for c in firm.clients), "no statement lines at all"
    assert not [ln for c in firm.clients for ln in c.bank_lines if ln.is_credit], (
        "a generated statement line is a CREDIT — every receipt in this "
        "fixture is already posted, so a credit here would be the same money "
        "twice")


def test_only_the_bank_charge_declares_gst():
    """BANK-24: a RECORDED ZERO declares nothing, so a line that carries no
    GST must leave the field unset rather than send 0."""
    firm = fixture.build()
    with_gst = {ln.description for c in firm.clients for ln in c.bank_lines
                if ln.gst_rate_bps is not None}
    assert with_gst, "no bank line carries GST — BANK-24 has nothing to show"
    assert all("Bank charges" in d for d in with_gst), sorted(with_gst)
    assert not [ln for c in firm.clients for ln in c.bank_lines
                if ln.gst_rate_bps == 0], (
        "a line records a GST rate of ZERO, which declares nothing and is "
        "indistinguishable from an unmarked line")


# ── the negative controls ────────────────────────────────────────────────────
#
# A guard that asserts an ABSENCE has to be shown catching its own positive
# case, or it passes for the wrong reason for ever. Both of these are the real
# defects this module found on its first run, reduced to one call each.

def test_the_guard_notices_a_field_the_model_does_not_declare():
    """`msme_status` on `POST /api/vendors/` — the live one. `VendorIn` has no
    such field, Pydantic dropped it in silence, and every seeded vendor went
    in unclassified."""
    from main import app

    rec = _Recorder(_doors(app))
    rec.post("/api/vendors/", {"client_id": "c", "name": "Probe",
                               "msme_status": "micro"})
    assert any("msme_status" in m for m in rec.invalid), rec.invalid


def test_the_guard_notices_a_path_the_app_does_not_serve():
    from main import app

    rec = _Recorder(_doors(app))
    rec.post("/api/vendors/mistyped", {"client_id": "c", "name": "Probe"})
    assert rec.unmatched == [("POST", "/api/vendors/mistyped")]


def test_the_guard_notices_a_body_the_model_refuses():
    """A field present and WRONG, as against a field absent — a different
    failure with a different message, and neither implies the other."""
    from main import app

    rec = _Recorder(_doors(app))
    rec.post("/api/banking/accounts", {"client_id": "c", "bank_name": "B",
                                       "account_no": "1", "account_type": "Piggy"})
    assert any("BankAccountIn" in m for m in rec.invalid), rec.invalid


def test_no_statement_is_imported_for_a_credit_card():
    """`import_statement` is the flag, and it has to be CHECKABLE.

    `account_kind.mirror_imported_statement` runs on the upload path;
    `POST /statements/import` takes already-parsed rows and does not mirror
    them, so a card statement sent through that door would carry every sign
    inverted. The seeder imports for `banks[0]`, so two things must hold and
    both are asserted: the flag is off on every card, and a card is never a
    client's FIRST account — otherwise the flag is decided by an ordering
    accident rather than by itself.
    """
    firm = fixture.build()
    cards = [(c.name, b) for c in firm.clients for b in c.banks
             if b.account_type == "Credit Card"]
    assert cards, "no credit card at all — BANK-21's liability ledger is unshown"
    for name, card in cards:
        assert not card.import_statement, f"{name}: {card.bank_name}"
    for c in firm.clients:
        if c.banks:
            assert c.banks[0].account_type != "Credit Card", c.name
            assert c.banks[0].import_statement, c.name


def test_the_guard_notices_the_payroll_payload_this_seeder_used_to_send():
    """The other live one, kept as the payload it actually was.

    `EmployeeIn` declares `joining_date` and `hra_percent`; the seeder sent
    `date_of_joining` and `hra_paise`. Both were dropped in silence, so every
    seeded employee had no joining date and a house rent allowance of ZERO in
    a §192 working built to show exactly that. Pinned here rather than
    described, because a defect a guard only *would have* caught is a claim
    and not a control.
    """
    from main import app

    rec = _Recorder(_doors(app))
    rec.post("/api/payroll/employees", {
        "client_id": "c", "name": "Probe", "pan": "AAAPK1234A",
        "date_of_joining": "2025-04-01",
        "basic_paise": 32_000_00, "hra_paise": 12_800_00,
    })
    assert len(rec.invalid) == 1, rec.invalid
    assert "date_of_joining" in rec.invalid[0]
    assert "hra_paise" in rec.invalid[0]
