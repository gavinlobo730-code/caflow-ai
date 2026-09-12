"""
The firm-level TDS return screen stops inventing its own inputs.

THREE DEFECTS, ONE SCREEN — `apps/web/app/tds/returns/page.tsx`.

  §2.2 of the 12 September probe pass, no finding: the page assembled the
  whole return in the browser and had nowhere to read the deductor's identity
  from, so it made one up.

      const tan = "MUMB00000A";  // placeholder — must be configured per client
      deductor_pan: "AAAAA0000A",
      deductor_address: "Address not configured",

  Both literals are the RIGHT SHAPE, and `_validate_26q` only checks
  `len(...) != 10`, so the payload validated clean and the return was saved to
  `tds_returns` as "prepared" under a TAN belonging to nobody. That is worse
  than TDS-28 ("the CA re-types it"): a re-typed TAN is one the CA saw, and
  this one never appeared on screen. A quarter filed under a wrong TAN credits
  somebody else's deductees while §200/§201 exposure stays with the deductor
  who actually withheld.

  TDS-29: every deductee row went out with `tds_deposited_paise` set equal to
  `tds_deducted_paise`, unconditionally, whatever the challans held. So
  `total_deducted - total_deposited` was zero BY CONSTRUCTION and the engine's
  own shortfall check (`tds_computer:505-510`, which raises only when the gap
  is positive) could never fire. §201(1A) charges 1.5% a month from the date
  of DEDUCTION on exactly that gap.

  TDS-18: the save wrote `return_type: payload.form`, and `form` is the number
  the PERIOD's Act uses — "140" for a FY 2026-27 26Q, per CBDT Notification
  22/2026 — while `tds_returns.return_type` CHECKs the four routing keys
  (migration 037). From 1 April 2026 every save from this screen was rejected
  by the database.

WHAT THE FIX IS
    The server builds the statement from the posted books (it always could —
    `/26q/from-books` and its two siblings), reads the deductor from
    `client_statutory_identity` (migration 325, created for exactly this) and
    the client's own columns, and REFUSES by name when a registration is not
    recorded. `domain/tds/deductor.py` is the rule.
"""
import pytest
from fastapi import HTTPException

from domain.tds import deductor as dd
from routers import tds as td


CLIENT = {
    "client_name": "Apex Trading",
    "legal_name": "Apex Trading Solutions Private Limited",
    "pan": "AAACA1234B",
    "address_line1": "12 Nariman Point",
    "address_line2": "3rd Floor",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400021",
}
IDENTITY = {"tan": "MUMA12345B"}


# ---------------------------------------------------------------------------
# 1. The resolver: what it takes, and what it will not invent.
# ---------------------------------------------------------------------------
def test_a_recorded_registration_is_enough():
    who, codes = dd.resolve(IDENTITY, CLIENT)
    assert codes == []
    assert who is not None
    assert who.tan == "MUMA12345B"
    assert who.pan == "AAACA1234B"
    # The LEGAL name, not the display name — TRACES matches the PAN card.
    assert who.name == "Apex Trading Solutions Private Limited"
    assert who.address == "12 Nariman Point, 3rd Floor, Mumbai, Maharashtra 400021"


def test_no_tan_recorded_is_a_named_refusal_and_not_a_placeholder():
    who, codes = dd.resolve({}, CLIENT)
    assert who is None
    assert codes == [dd.GAP_TAN_MISSING]
    # And the sentence says where to go, because the CA cannot act on a code.
    assert "Statutory Identity" in dd.GAP_MESSAGES[dd.GAP_TAN_MISSING]


def test_the_literal_the_screen_used_to_send_is_not_produced_by_anything():
    """MUMB00000A and AAAAA0000A are both well-formed. Nothing may mint them."""
    who, _ = dd.resolve({}, CLIENT)
    assert who is None
    who, _ = dd.resolve(IDENTITY, {**CLIENT, "pan": None})
    assert who is None


def test_a_caller_supplied_value_wins_over_the_store():
    """The per-client compute form has always offered the block, and a client
    whose registrations are not yet recorded has no other way to compute a
    quarter. What a caller may not do is supply nothing and get something."""
    who, codes = dd.resolve(IDENTITY, CLIENT, tan="delz98765k")
    assert codes == []
    assert who.tan == "DELZ98765K", "a typed TAN is upper-cased, not rejected"


def test_a_caller_supplied_tan_is_validated_too():
    """It has never been near migration 325's CHECK — only the stored one has."""
    who, codes = dd.resolve(IDENTITY, CLIENT, tan="NOTATAN")
    assert who is None
    assert codes == [dd.GAP_TAN_MALFORMED]


def test_a_blank_supplied_value_falls_through_rather_than_clearing():
    who, codes = dd.resolve(IDENTITY, CLIENT, tan="   ", pan="")
    assert codes == []
    assert who.tan == "MUMA12345B" and who.pan == "AAACA1234B"


def test_nothing_recorded_at_all_names_every_gap_separately():
    who, codes = dd.resolve({}, {})
    assert who is None
    # Four different things somebody has to go and record. "The deductor
    # details are incomplete" would make the CA guess which.
    assert set(codes) == {dd.GAP_TAN_MISSING, dd.GAP_PAN_MISSING,
                          dd.GAP_NAME_MISSING, dd.GAP_ADDRESS_MISSING}


def test_a_partly_filled_block_is_never_returned():
    """A statement is filed under all four or under none."""
    who, codes = dd.resolve(IDENTITY, {**CLIENT, "pincode": None,
                                       "address_line1": None,
                                       "address_line2": None, "city": None,
                                       "state": None})
    assert who is None and codes == [dd.GAP_ADDRESS_MISSING]


def test_every_gap_code_carries_a_sentence():
    for name in dir(dd):
        if name.startswith("GAP_") and name != "GAP_MESSAGES":
            code = getattr(dd, name)
            assert dd.GAP_MESSAGES.get(code), f"{name} has no CA-facing message"


def test_the_refusal_detail_is_the_sentences_not_the_codes():
    detail = dd.refusal_detail([dd.GAP_TAN_MISSING, dd.GAP_PAN_MISSING])
    assert dd.GAP_TAN_MISSING not in detail
    assert "no TAN recorded" in detail and "no PAN recorded" in detail


def test_the_display_name_is_used_when_there_is_no_legal_name():
    assert dd.deductor_name({"client_name": "Apex"}) == "Apex"
    assert dd.deductor_name({"client_name": "Apex", "legal_name": "  "}) == "Apex"


def test_the_address_skips_blanks_rather_than_leaving_commas():
    assert dd.format_address({"city": "Pune", "state": "MH"}) == "Pune, MH"
    assert dd.format_address({"address_line1": "A", "pincode": "411001"}) == "A, 411001"
    assert dd.format_address({}) == ""


# ---------------------------------------------------------------------------
# 2. The three from-books routes ask it, and refuse when it refuses.
# ---------------------------------------------------------------------------
USER = {"id": "u1", "firm_id": "F1", "role": "Partner", "auth_user_id": "a1"}


class _DB:
    """Just enough PostgREST for the two reads `_deductor_for` makes."""
    def __init__(self, identity=None, client=None, fail=False):
        self._identity, self._client, self._fail = identity, client, fail
        self._table = None

    def table(self, name):
        self._table = name
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("PostgREST said no")
        return type("R", (), {"data": self._identity if self._table
                              == "client_statutory_identity" else self._client})()


@pytest.fixture
def routed(monkeypatch):
    """Every from-books route, with the service replaced by a spy."""
    calls: list[tuple] = []
    for name in ("tds_26q_from_books", "tds_27q_from_books", "tds_24q_from_books"):
        monkeypatch.setattr(
            f"services.tds_return_service.{name}",
            lambda *a, **k: calls.append(a) or {"form": "26Q"})
    return calls


def _req(**over):
    return td.FromBooksRequest(client_id="C1", financial_year="2025-26",
                               quarter="Q3", **over)


@pytest.mark.parametrize("fn", ["compute_26q_from_books", "compute_27q_from_books",
                                "compute_24q_from_books"])
def test_the_deductor_block_is_no_longer_required_in_the_request(fn, routed, monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _DB(IDENTITY, CLIENT))
    out = getattr(td, fn)(_req(), user=USER)
    assert out["success"] is True
    # …and what reached the service is what the books hold.
    args = routed[0]
    assert args[5] == "MUMA12345B"
    assert args[6] == "Apex Trading Solutions Private Limited"
    assert args[7] == "AAACA1234B"


@pytest.mark.parametrize("fn", ["compute_26q_from_books", "compute_27q_from_books",
                                "compute_24q_from_books"])
def test_an_unrecorded_tan_refuses_before_the_books_are_read(fn, routed, monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB({}, CLIENT))
    with pytest.raises(HTTPException) as e:
        getattr(td, fn)(_req(), user=USER)
    assert e.value.status_code == 422
    assert "no TAN recorded" in e.value.detail
    assert routed == [], "the statement was built anyway"


def test_a_supplied_block_still_works_because_the_compliance_tab_sends_one(routed, monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB({}, {}))
    out = td.compute_26q_from_books(
        _req(tan="DELZ98765K", deductor_name="Other Ltd",
             deductor_pan="AABCT1332L", deductor_address="1 Road, Delhi 110001"),
        user=USER)
    assert out["success"] is True
    assert routed[0][5] == "DELZ98765K"


def test_a_failed_read_reports_the_gap_rather_than_passing_the_identifiers(routed, monkeypatch):
    """The other direction — treating a failed read as 'the identifiers are
    fine' — is the one that files."""
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB(fail=True))
    with pytest.raises(HTTPException) as e:
        td.compute_26q_from_books(_req(), user=USER)
    assert e.value.status_code == 422
    assert routed == []


# ---------------------------------------------------------------------------
# 3. TDS-18 — the routing column cannot take a display form.
# ---------------------------------------------------------------------------
def test_the_stored_return_type_is_one_of_the_four_routing_keys():
    from pydantic import ValidationError
    from routers.tds_workspace import CreateReturnRequest
    for key in ("24Q", "26Q", "27Q", "27EQ"):
        assert CreateReturnRequest(client_id="C1", return_type=key, quarter="Q3",
                                   financial_year="2026-27").return_type == key


@pytest.mark.parametrize("form", ["138", "140", "143", "144", "26q", "Form 26Q"])
def test_the_acts_own_form_number_is_refused_where_the_routing_key_belongs(form):
    """`statement_form` returns 140 for a FY 2026-27 26Q. Storing it hit
    migration 037's CHECK and the CA saw "Failed to save TDS return"."""
    from pydantic import ValidationError
    from routers.tds_workspace import CreateReturnRequest
    with pytest.raises(ValidationError):
        CreateReturnRequest(client_id="C1", return_type=form, quarter="Q3",
                            financial_year="2026-27")


def test_the_two_vocabularies_really_do_differ_for_the_current_year():
    """The premise, in one line: if these were equal, TDS-18 would be moot."""
    from domain.tds import vocabulary as v
    assert v.statement_form(v.RESIDENT_NON_SALARY, fy_label="2025-26") == "26Q"
    assert v.statement_form(v.RESIDENT_NON_SALARY, fy_label="2026-27") == "140"
