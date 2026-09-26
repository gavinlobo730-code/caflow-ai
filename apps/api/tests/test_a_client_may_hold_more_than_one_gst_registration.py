"""GST-20 — a client is one legal person and may hold several GSTINs.

The test that matters most here is
`test_a_gstin_the_client_does_not_hold_is_REFUSED_not_defaulted`: falling back
to the primary would file one registration's return under another's number,
which is the whole failure this feature exists to prevent and is invisible
until the portal rejects it — or worse, accepts it.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from domain.gst import registrations as reg

API = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = API / "migrations" / "390_a_client_may_hold_more_than_one_gst_registration.sql"
ROLLBACK = API / "migrations" / "390_a_client_may_hold_more_than_one_gst_registration_rollback.sql"

# Check digits are right — the fixture file is the authority and GST-29
# corrected three invented ones that were not.
MAHARASHTRA = "27AAPFU0939F1ZV"
KARNATAKA = "29AAPFU0939F1ZR"


def _sql_only(text: str) -> str:
    """The migration with its `--` commentary removed. A guard that greps the
    whole file cannot tell a statement from a paragraph explaining why that
    statement is NOT there."""
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


def _client(**over):
    base = {"id": "C1", "firm_id": "F1", "client_name": "Acme Industries",
            "legal_name": "Acme Industries Private Limited",
            "gstin": MAHARASHTRA, "state_code": "27",
            "gst_filing_frequency": "monthly", "gst_registration_date": None}
    base.update(over)
    return base


def _row(**over):
    base = {"id": "R1", "firm_id": "F1", "client_id": "C1",
            "gstin": KARNATAKA, "state_code": "29",
            "registration_type": reg.REGULAR, "filing_frequency": reg.MONTHLY,
            "trade_name": "Bengaluru depot", "effective_from": None,
            "effective_to": None, "deleted_at": None}
    base.update(over)
    return base


# ── The union ────────────────────────────────────────────────────────────────

def test_a_client_with_one_gstin_is_unchanged():
    """Every client today. The list has to be exactly what `clients.gstin`
    always was, or adding this feature changes what a return is filed under for
    a book of clients that never touches it."""
    regs = reg.all_registrations(_client(), [])
    assert [r.gstin for r in regs] == [MAHARASHTRA]
    assert regs[0].is_primary is True
    assert regs[0].id is None, "the primary is clients.gstin, not a row"


def test_the_primary_comes_FIRST():
    """A screen opens on `[0]`. If that is not the registration every existing
    document already carries, a CA who never touches the selector starts filing
    under a different GSTIN than yesterday."""
    regs = reg.all_registrations(_client(), [_row()])
    assert regs[0].gstin == MAHARASHTRA and regs[0].is_primary
    assert regs[1].gstin == KARNATAKA and not regs[1].is_primary


def test_a_client_with_no_gstin_holds_nothing():
    """`clients.gstin` is nullable — an unregistered client is real."""
    assert reg.all_registrations(_client(gstin=None), []) == []


def test_a_row_duplicating_the_primary_is_dropped():
    """Refused at the door, so reaching here means data predating the check.
    One GSTIN is one registration whatever two tables say."""
    regs = reg.all_registrations(_client(), [_row(gstin=MAHARASHTRA, state_code="27")])
    assert [r.gstin for r in regs] == [MAHARASHTRA]


# ── Resolving one ────────────────────────────────────────────────────────────

def test_no_gstin_means_the_primary():
    """What every caller predating this module meant, and still means."""
    assert reg.resolve(_client(), [_row()], None).gstin == MAHARASHTRA
    assert reg.resolve(_client(), [_row()], "").gstin == MAHARASHTRA


def test_a_second_registration_can_be_asked_for_by_name():
    assert reg.resolve(_client(), [_row()], KARNATAKA).gstin == KARNATAKA


def test_a_gstin_the_client_does_not_hold_is_REFUSED_not_defaulted():
    """THE ONE THAT MATTERS. A silent fall back to the primary files one
    registration's return under another's number."""
    with pytest.raises(ValueError) as e:
        reg.resolve(_client(), [_row()], "33AAPFU0939F1Z2")
    assert MAHARASHTRA in str(e.value) and KARNATAKA in str(e.value), (
        "the refusal must name what the client DOES hold, or the CA cannot act")


def test_a_client_with_no_registration_cannot_have_a_return_prepared():
    with pytest.raises(ValueError) as e:
        reg.resolve(_client(gstin=None), [], None)
    assert "no GST registration" in str(e.value)


# ── Adding one ───────────────────────────────────────────────────────────────

def test_the_check_digit_is_the_ONE_implementation():
    """`domain/gst/gstin.problem_with` is it, and this is not a second."""
    src = inspect.getsource(reg.problem_with_new)
    assert "problem_with" in src
    bad = reg.problem_with_new(_client(), [], gstin="29AAPFU0939F1Z9")
    assert not bad.ok


def test_the_primary_cannot_be_added_again():
    r = reg.problem_with_new(_client(), [], gstin=MAHARASHTRA)
    assert not r.ok
    assert "primary" in " ".join(r.reasons)


def test_a_registration_already_recorded_cannot_be_added_again():
    r = reg.problem_with_new(_client(), [_row()], gstin=KARNATAKA)
    assert not r.ok


def test_a_state_code_that_disagrees_with_the_gstin_is_refused():
    """A registration is state-wise (s.25(1)), so one of the two is wrong and
    guessing which puts every supply under it in the wrong state."""
    r = reg.problem_with_new(_client(), [], gstin=KARNATAKA, state_code="27")
    assert not r.ok
    assert "s.25(1)" in " ".join(r.reasons)


def test_the_state_is_taken_from_the_gstin_when_none_is_given():
    assert reg.problem_with_new(_client(), [], gstin=KARNATAKA).ok
    assert reg.state_code_of(KARNATAKA) == "29"


def test_the_state_is_the_PREFIX_not_a_validated_state_code():
    """The question is WHICH state. Falling through on a bad check digit would
    leave the registration stateless rather than merely unverified — the same
    call `place_of_supply` makes and says so."""
    assert reg.state_code_of("29ZZZZZ9999Z9Z9") == "29"


@pytest.mark.parametrize("bad", ["sole_trader", "", "REGULAR"])
def test_an_unknown_registration_type_is_refused(bad):
    r = reg.problem_with_new(_client(), [], gstin=KARNATAKA, registration_type=bad)
    assert not r.ok


@pytest.mark.parametrize("bad", ["annual", "", "Monthly"])
def test_an_unknown_filing_frequency_is_refused(bad):
    r = reg.problem_with_new(_client(), [], gstin=KARNATAKA, filing_frequency=bad)
    assert not r.ok


# ── Which returns a registration owes ────────────────────────────────────────

def test_a_composition_dealer_does_not_file_gstr1_and_3b():
    """s.10 is a different regime: CMP-08 quarterly with GSTR-4 annually.
    Offering it a GSTR-3B screen offers a return it must not file."""
    assert reg.COMPOSITION not in reg.FILES_GSTR1_AND_3B
    assert "CMP-08" in reg.OTHER_RETURN_FORMS[reg.COMPOSITION]


def test_files_cmp08_is_the_boolean_shape_files_gstr1_and_3b_already_is():
    """GST-25. A screen that decides whether to offer the CMP-08 panel must
    read a boolean off the wire, never compare `registration_type` to the
    literal string "composition" — the exact second-vocabulary trap this
    codebase keeps retiring elsewhere."""
    composition = reg.Registration(gstin="27AAAAA0000A1Z5", state_code="27",
                                   registration_type=reg.COMPOSITION)
    regular = reg.Registration(gstin="27AAAAA0000A1Z5", state_code="27",
                               registration_type=reg.REGULAR)
    isd = reg.Registration(gstin="27AAAAA0000A1Z5", state_code="27",
                           registration_type=reg.ISD)
    assert composition.files_cmp08
    assert not regular.files_cmp08
    assert not isd.files_cmp08


# ── GST-25: the PRIMARY can be composition too, migration 420 ───────────────
#
# Before 420, `primary_of()` hardcoded `registration_type=REGULAR`, so a
# client whose ONLY GSTIN — the common case for a small composition dealer —
# was its primary could never be recorded as anything but a regular filer.
# `clients.gst_registration_type` and `clients.composition_category` close
# that; the tests below are the negative control that would have failed on
# the old code.

def test_the_primarys_own_registration_type_is_read_not_hardcoded():
    client = _client(gst_registration_type=reg.COMPOSITION,
                     composition_category="manufacturer_trader")
    primary = reg.primary_of(client)
    assert primary.registration_type == reg.COMPOSITION
    assert primary.composition_category == "manufacturer_trader"
    assert not primary.files_gstr1_and_3b


def test_an_unset_primary_registration_type_still_defaults_to_regular():
    """Every client recorded before migration 420 has no such column read —
    `.get()` on an absent key — and must keep behaving exactly as it did."""
    primary = reg.primary_of(_client())
    assert primary.registration_type == reg.REGULAR
    assert primary.composition_category is None
    assert primary.files_gstr1_and_3b


def test_an_additional_registrations_own_composition_category_is_read():
    row = _row(registration_type=reg.COMPOSITION,
              composition_category="restaurant")
    regs = reg.all_registrations(_client(), [row])
    additional = regs[1]
    assert additional.registration_type == reg.COMPOSITION
    assert additional.composition_category == "restaurant"


def test_an_additional_registrations_composition_category_defaults_to_none():
    regs = reg.all_registrations(_client(), [_row()])
    assert regs[1].composition_category is None


@pytest.mark.parametrize("kind,form", [
    (reg.ISD, "GSTR-6"), (reg.TDS_DEDUCTOR, "GSTR-7"),
    (reg.TCS_COLLECTOR, "GSTR-8"),
])
def test_each_other_regime_names_the_form_it_actually_owes(kind, form):
    assert kind not in reg.FILES_GSTR1_AND_3B
    assert form in reg.OTHER_RETURN_FORMS[kind]


@pytest.mark.parametrize("kind", [reg.SEZ_UNIT, reg.SEZ_DEVELOPER,
                                  reg.CASUAL, reg.NON_RESIDENT])
def test_an_sez_or_casual_registration_DOES_file_the_ordinary_pair(kind):
    """An SEZ unit is an ordinary registered person whose supplies are
    zero-rated under IGST s.16, not a different return regime; s.27 shortens a
    casual or non-resident registration's VALIDITY, not its forms. Withholding
    the returns from them would be the mirror mistake."""
    assert kind in reg.FILES_GSTR1_AND_3B
    assert kind not in reg.OTHER_RETURN_FORMS


def test_every_type_either_files_the_pair_or_says_what_it_files():
    """No silent third state: a type in neither set would render with no
    return and no explanation."""
    for kind in reg.REGISTRATION_TYPES:
        assert (kind in reg.FILES_GSTR1_AND_3B) != (kind in reg.OTHER_RETURN_FORMS), kind


# ── The label ────────────────────────────────────────────────────────────────

def test_two_registrations_in_one_state_are_told_apart_by_the_trade_name():
    """s.25(2)'s proviso allows one per place of business, so the state code
    does not distinguish them and the GSTIN alone is unreadable."""
    a = reg.registration_of(_row(gstin=KARNATAKA, trade_name="Depot A"))
    assert "Depot A" in a.label and KARNATAKA in a.label


def test_the_primary_says_so_in_its_label():
    assert "primary" in reg.primary_of(_client()).label


# ── The service and the router ───────────────────────────────────────────────

def test_the_service_derives_the_state_rather_than_trusting_the_caller():
    """The column's CHECK requires it to equal the GSTIN's first two
    characters. Deriving it here means the two cannot go out of step through a
    path that forgot to send one."""
    from services import client_gst_registration_service as svc
    src = inspect.getsource(svc.create)
    assert 'reg.state_code_of(value)' in src


def test_a_registration_with_a_return_behind_it_cannot_be_WITHDRAWN():
    """The returns are keyed on the GSTIN. Removing the registration would
    leave them pointing at a number the client is no longer recorded as
    holding — and a registration that ENDED is closed, not withdrawn.

    BOTH return tables are asked, one at a time: a registration whose GSTR-3B
    exists but whose GSTR-1 does not is just as un-removable."""
    from fastapi import HTTPException
    from services import client_gst_registration_service as svc

    for table, form in (("gstr1_returns", "GSTR-1"), ("gstr3b_returns", "GSTR-3B")):
        db = _FakeDB(**{
            "clients": [_client()],
            "client_gst_registrations": [_row()],
            table: [{"id": "ret", "client_id": "C1", "gstin": KARNATAKA,
                     "period": "062026"}],
        })
        with pytest.raises(HTTPException) as e:
            svc.withdraw(db, "F1", "R1")
        assert e.value.status_code == 409
        assert form in str(e.value.detail)
        assert "cancelled or surrendered" in str(e.value.detail), (
            "the refusal has to say what to do instead, or Remove becomes the "
            "cancel button")

    # With no return under it, the registration is removable.
    db = _FakeDB(clients=[_client()], client_gst_registrations=[_row()])
    svc.withdraw(db, "F1", "R1")


def test_closing_is_not_deleting():
    from services import client_gst_registration_service as svc
    src = inspect.getsource(svc.close)
    assert "effective_to" in src
    assert "deleted_at" not in src, (
        "a cancelled registration still owes the returns for the periods it "
        "was live")


def test_the_compute_paths_take_a_gstin_and_default_to_the_primary():
    """THE RULE, NOT A SPELLING OF IT. This used to count one exact call
    string, and broke when the three compute paths began resolving the WHOLE
    registration rather than its number alone (GST-11) — a change that does
    not touch the rule it was written for. What matters is that every endpoint
    taking a `FromBooksRequest` resolves the registration from the request's
    own optional `gstin`, and that nothing reads `clients.gstin` to do it."""
    src = (API / "routers" / "gst.py").read_text()
    assert "gstin: Optional[str] = None" in src

    import ast
    import routers.gst as gst_router

    tree = ast.parse(src)
    resolved = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        takes_from_books = any(
            isinstance(a.annotation, ast.Name) and a.annotation.id == "FromBooksRequest"
            for a in node.args.args if a.annotation is not None)
        if not takes_from_books:
            continue
        body = ast.get_source_segment(src, node) or ""
        assert "_client_registration(db, firm_id, req.client_id, req.gstin)" in body, (
            f"{node.name} takes a FromBooksRequest and must resolve the "
            "registration from its own optional gstin — defaulting to the "
            "primary, never reading clients.gstin")
        resolved += 1
    assert resolved == 3, (
        f"expected the three from-books compute paths, found {resolved}")

    # And the drill-down, which is a Query endpoint rather than a body one but
    # must cover the same registration's window.
    assert "_client_registration(db, firm_id, client_id, gstin)" in src, (
        "the GSTR-3B detail path resolves the registration too")


def test_the_gstin_resolver_goes_through_the_registration_service():
    """Reading `clients.gstin` directly is what made a second registration
    unreachable. One resolver, and it is the one the screen shows."""
    import routers.gst as gst_router
    src = inspect.getsource(gst_router._client_registration)
    assert "client_gst_registration_service" in src
    assert 'table("clients")' not in src
    # `_client_gstin` survives for callers that want the number alone, and it
    # must go through the same resolver rather than growing a second read.
    thin = inspect.getsource(gst_router._client_gstin)
    assert "_client_registration(" in thin
    assert 'table("clients")' not in thin


def test_writes_are_a_CLIENT_action_not_a_gst_one():
    """`clients.gstin` — the primary — is written under `client.write`, and an
    additional registration is the same kind of fact about the same entity.
    A GST action would let an Executive who may COMPUTE a return also add the
    registration it is filed under, while being unable to correct the primary
    beside it."""
    src = (API / "routers" / "client_gst_registrations.py").read_text()
    assert 'rbac("client", "write")' in src
    assert 'rbac("gst", "write")' not in src
    assert 'rbac("gst", "read")' in src, "every GST screen needs the list"


# ── The one that breaks a client with two registrations ──────────────────────

def test_the_existing_return_lookup_is_keyed_on_the_REGISTRATION():
    """With the unique key narrowed to (client, period, gstin), a lookup still
    matching on (client, period) alone finds the OTHER registration's return
    and revises it — silently replacing one state's figures with another's,
    which is worse than the collision it replaced."""
    import routers.gst_workspace as ws
    src = inspect.getsource(ws._existing_return)
    assert "gstin: str" in src, "the GSTIN is a required parameter, not a default"
    assert '.eq("gstin", wanted)' in src
    # The mock branch has to match too, or the mock suite proves nothing.
    assert 'rec.get("gstin")' in src


def test_both_save_paths_pass_the_registration_through():
    src = (API / "routers" / "gst_workspace.py").read_text()
    assert src.count("body.client_id, body.period, gstin)") == 2


# ── The migration ────────────────────────────────────────────────────────────

def test_the_migration_creates_the_table_and_narrows_the_return_keys():
    text = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS public.client_gst_registrations" in text
    assert "uq_gstr1_return_per_registration" in text
    assert "uq_gstr3b_return_per_registration" in text
    assert "gstr1_returns_client_id_period_key" in text


def test_the_state_code_is_CHECKed_against_the_gstin():
    assert "CHECK (state_code = left(gstin, 2))" in MIGRATION.read_text()


def test_the_check_accepts_exactly_the_modules_vocabulary():
    """Compared against the module's own tuple rather than a list spelled here:
    a guard that names nine strings passes a WIDENED constraint."""
    text = MIGRATION.read_text()
    block = text[text.index("registration_type   TEXT"):]
    block = block[:block.index("filing_frequency")]
    assert set(re.findall(r"'([a-z_]+)'", block)) - {"regular"} == \
        set(reg.REGISTRATION_TYPES) - {"regular"}


def test_the_rollback_refuses_while_a_second_registration_exists():
    text = ROLLBACK.read_text()
    assert "RAISE EXCEPTION" in text
    assert "Refusing to roll back 390" in text
    # And refuses again on the rows the OLD constraint could not express —
    # restoring it would fail after the table had already gone.
    assert "more than one" in text


def test_the_backfill_gives_an_existing_return_its_clients_gstin():
    """Migration 234 added `gstr3b_returns.gstin` as a bare TEXT, so rows
    predating this migration can carry none. Before 390 a client held exactly
    ONE registration, so `clients.gstin` is the registration such a row was
    prepared under — and without the backfill the lookup, which now matches on
    the GSTIN, would miss it and save a SECOND return beside it."""
    text = _sql_only(MIGRATION.read_text())
    # BOTH tables, counted rather than merely present: `gstr3b_returns` is the
    # one that needs it (234 added its column as a bare TEXT) and `gstr1_returns`
    # carries the same statement because its NOT NULL has drifted from the
    # migrations once already. One assertion that either is there would pass on
    # a commit that dropped the other.
    assert text.count("SET gstin = c.gstin") == 2
    for table in ("gstr1_returns", "gstr3b_returns"):
        block = text[text.index(f"UPDATE public.{table} r"):]
        block = block[:block.index(";") + 1]
        assert "SET gstin = c.gstin" in block, table
        assert "r.gstin IS NULL" in block, table
        assert "c.gstin IS NOT NULL" in block, (
            f"{table}: a client with no GSTIN has nothing to back-fill FROM, "
            "and writing NULL over NULL is not what this statement is for")
    # Run while the old constraint still stands: that constraint is what
    # guarantees the update cannot collide with a row that already has one.
    assert text.index("SET gstin = c.gstin") < text.index("DROP CONSTRAINT IF EXISTS gstr1_returns")
    # And never a SET NOT NULL: one unbackfillable row would abort a deploy
    # that has no review step in front of it. Read off the STATEMENTS, since
    # the header explains at length why it is not used.
    assert "SET NOT NULL" not in text
    # The coalesce is what constrains a row that still has no GSTIN.
    assert text.count("coalesce(gstin, '')") == 2


def test_there_is_NO_backfill():
    """`clients.gstin` stays the primary, so every client's primary is already
    where it belongs. A backfill would create the duplicate row
    `all_registrations` then has to drop."""
    text = MIGRATION.read_text().lower()
    assert "insert into public.client_gst_registrations" not in text


# ── Behavioural: the two refusals that a source read cannot see ──────────────
#
# The source-reading tests above pin that the code SAYS the right thing. These
# two run it. Both were added because a negative control passed: mutating the
# service so `resolve` fell back to the primary instead of 422ing, and mutating
# a save path so it dropped the registration, left every assertion above green.


class _Q:
    """Just enough PostgREST to run these two paths, including `fetch_all`'s
    own `.gt()/.order()/.limit()` keyset walk."""

    def __init__(self, store, table):
        self._rows = list(store.get(table, []))

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def is_(self, col, _null):
        self._rows = [r for r in self._rows if r.get(col) is None]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, patch):
        for r in self._rows:
            r.update(patch)
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, **tables):
        self.store = tables

    def table(self, name):
        return _Q(self.store, name)


def test_the_service_REFUSES_a_gstin_the_client_does_not_hold():
    """422, not the primary. The domain module raises; the service has to turn
    that into a refusal rather than swallowing it — a fall back here files one
    registration's return under another's number, which is exactly what the
    domain refusal exists to prevent, re-introduced one layer up."""
    from fastapi import HTTPException
    from services import client_gst_registration_service as svc

    db = _FakeDB(clients=[_client()], client_gst_registrations=[_row()])

    # The two it holds resolve.
    assert svc.resolve(db, "F1", "C1", None).gstin == MAHARASHTRA
    assert svc.resolve(db, "F1", "C1", KARNATAKA).gstin == KARNATAKA

    # A third does not, and the refusal names what is on file.
    with pytest.raises(HTTPException) as e:
        svc.resolve(db, "F1", "C1", "33AAPFU0939F1Z2")
    assert e.value.status_code == 422
    assert MAHARASHTRA in str(e.value.detail)


def test_two_registrations_hold_ONE_PERIOD_EACH_and_the_lookup_tells_them_apart():
    """The defect the narrowed unique key creates if the lookup is not narrowed
    with it: two returns for one client and one period, and a read matching on
    (client, period) alone revises whichever it finds first."""
    import routers.gst_workspace as ws

    store = {
        "a": {"id": "a", "client_id": "C1", "period": "2026-06",
              "gstin": MAHARASHTRA, "status": "draft"},
        "b": {"id": "b", "client_id": "C1", "period": "2026-06",
              "gstin": KARNATAKA, "status": "draft"},
    }
    found = ws._existing_return(
        {"firm_id": "F1"}, "gstr1_returns", store, "C1", "2026-06", KARNATAKA)
    assert found is not None and found["id"] == "b", (
        "the Karnataka registration's own June return, not Maharashtra's")

    # A registration with no return for the period has none — not the other's.
    assert ws._existing_return(
        {"firm_id": "F1"}, "gstr1_returns", store, "C1", "2026-06",
        "33AAPFU0939F1Z2") is None
