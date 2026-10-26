"""The one place the API calls `file_it_declaration`, held to the function it calls (POST-A-340, migration 548).

WHAT IS HELD
    * THE PAYLOAD IS THE FUNCTION'S: every key the service sends in `p_declaration` and in each line is a key the migration's SQL
      reads (`p_declaration->>'key'`, `x->>'key'`), and every key the SQL reads is one the service sends. A column added to one
      side and not the other is a filing that silently drops a figure, which is the defect this function exists to end.
    * THE FUNCTION'S THREE REFUSALS ARE THE SERVICE'S THREE EXCEPTIONS, mapped by the message ("declaration_verified:") or the
      SQLSTATE (40001 the row could not be taken, 42501 the employee is not that client's) exactly as the database sends them, and
      any other failure passes through unchanged so a door cannot mistake it for a refusal.
    * THE ANSWER IS THE DECLARATION'S ID, a string. Anything else means the function is not the one this module was written
      against, and the module says so instead of handing a door a value it will write into an audit row.
    * THE ARGUMENTS ARE THE PRIVILEGED CLIENT'S (`rpc` on the client handed in, never a signed-in session's: the function is
      executable by the service role alone) and the flag is a real boolean.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from postgrest.exceptions import APIError

from services import it_declaration_service as svc

MIGRATION = next(p for p in (Path(__file__).resolve().parents[1] / "migrations").glob("548_a_tax_declaration_is_filed_in_one_transaction*.sql")
                 if not p.name.endswith("_rollback.sql"))


class _Rpc:
    def __init__(self, owner, fn, params):
        self.owner, self.fn, self.params = owner, fn, params

    def execute(self):
        self.owner.calls.append((self.fn, self.params))
        if self.owner.raises is not None:
            raise self.owner.raises
        return type("R", (), {"data": self.owner.answer})()


class _Client:
    def __init__(self, answer="11111111-2222-3333-4444-555555555555", raises=None):
        self.calls, self.answer, self.raises = [], answer, raises

    def rpc(self, fn, params):
        return _Rpc(self, fn, params)


def _file(client, **over):
    args = dict(firm_id="f", client_id="c", employee_id="e", fy="2026-27", regime="old", rent_paid_declared_paise=1,
                landlord_name="L", landlord_address="A", landlord_pan="ABCDE1234F", rent_is_metro=True, lta_declared_paise=2,
                home_loan_interest_declared_paise=3, lender_name="B", lender_pan="ABCDE1234G", other_income_declared_paise=4,
                house_property_loss_declared_paise=5, items=[{"section": "80C", "label": "LIC", "amount_declared_paise": 6,
                                                              "proof_reference": "ref-7",
                                                              "proof_attachments": [{"name": "receipt", "url": "https://x.test/r.pdf"}]}],
                refuse_verified=False)
    args.update(over)
    return svc.file_declaration(client, **args)


def _sql() -> str:
    return re.sub(r"--[^\n]*", "", MIGRATION.read_text())


# ── the payload is the function's ────────────────────────────────────────────────────────────────────────────────────
def test_the_service_sends_exactly_the_keys_it_declares():
    client = _Client()
    _file(client)
    [(fn, params)] = client.calls
    assert fn == "file_it_declaration" == svc.FUNCTION
    assert set(params) == {"p_declaration", "p_items", "p_refuse_verified"}
    assert tuple(params["p_declaration"]) == svc.HEADER_KEYS
    assert [tuple(i) for i in params["p_items"]] == [svc.ITEM_KEYS]
    assert params["p_refuse_verified"] is False


def test_every_value_goes_under_its_own_key():
    """The keys being the function's is half of it. Every argument below has its own value (the figures are 1 to 5, the names and the
    PANs differ, the metro flag is True), so a value under the wrong key, a flag negated or a figure dropped to nothing is a different
    payload; `tests/…` asserting only the key set passed all of those."""
    client = _Client()
    _file(client)
    [(_, params)] = client.calls
    assert params["p_declaration"] == {
        "firm_id": "f", "client_id": "c", "employee_id": "e", "fy": "2026-27", "regime": "old",
        "rent_paid_declared_paise": 1, "landlord_name": "L", "landlord_address": "A", "landlord_pan": "ABCDE1234F",
        "rent_is_metro": True,
        "lta_declared_paise": 2,
        "home_loan_interest_declared_paise": 3, "lender_name": "B", "lender_pan": "ABCDE1234G",
        "other_income_declared_paise": 4,
        "house_property_loss_declared_paise": 5,
    }
    assert params["p_items"] == [{"section": "80C", "label": "LIC", "amount_declared_paise": 6, "proof_reference": "ref-7",
                                  "proof_attachments": [{"name": "receipt", "url": "https://x.test/r.pdf"}]}]
    # The header's values are all different, so the assertion above cannot pass by two columns swapping with each other.
    figures = [params["p_declaration"][k] for k in svc.HEADER_KEYS if k.endswith("_paise")]
    assert len(set(figures)) == len(figures)


def test_every_key_the_service_sends_is_one_the_function_reads():
    sql = _sql()
    for key in svc.HEADER_KEYS:
        assert f"p_declaration->>'{key}'" in sql, f"the function never reads p_declaration->>'{key}'"
    for key in svc.ITEM_KEYS:
        assert re.search(rf"x->>?'{key}'", sql), f"the function never reads the line key {key!r}"


def test_every_key_the_function_reads_is_one_the_service_sends():
    sql = _sql()
    header = set(re.findall(r"p_declaration->>'(\w+)'", sql))
    lines = set(re.findall(r"\bx->>?'(\w+)'", sql))
    assert header == set(svc.HEADER_KEYS), (header ^ set(svc.HEADER_KEYS))
    assert lines == set(svc.ITEM_KEYS), (lines ^ set(svc.ITEM_KEYS))


def test_a_line_is_cut_to_the_keys_the_function_reads_and_extra_keys_are_not_sent():
    client = _Client()
    _file(client, items=[{"section": "80C", "label": "x", "amount_declared_paise": 1, "proof_reference": "r", "proof_attachments": [],
                          "amount_verified_paise": 999, "status": "verified"}])
    [(_, params)] = client.calls
    assert set(params["p_items"][0]) == set(svc.ITEM_KEYS), "a verified amount smuggled in a line must never reach the function"


def test_the_flag_is_a_real_boolean_in_both_directions():
    for flag in (True, False):
        client = _Client()
        _file(client, refuse_verified=flag)
        assert client.calls[0][1]["p_refuse_verified"] is flag


# ── the answer ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_answer_is_the_declarations_id():
    assert _file(_Client(answer="abc")) == "abc"


@pytest.mark.parametrize("answer", [None, "", 7, ["x"], {"id": "x"}])
def test_an_answer_that_is_not_an_id_is_an_error_and_not_a_value_to_audit(answer):
    with pytest.raises(RuntimeError, match="not the declaration's id"):
        _file(_Client(answer=answer))


# ── the three refusals ──────────────────────────────────────────────────────────────────────────────────────────────
def _api_error(message, code):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


def test_a_verified_declaration_is_declaration_verified():
    with pytest.raises(svc.DeclarationVerified):
        _file(_Client(raises=_api_error("declaration_verified: the declaration for 2026-27 is verified and is not the employee's to change", "P0001")))


def test_a_row_that_could_not_be_taken_is_declaration_busy():
    with pytest.raises(svc.DeclarationBusy):
        _file(_Client(raises=_api_error("file_it_declaration: could not take the declaration for employee x and year y", "40001")))


def test_an_employee_that_is_not_that_clients_is_out_of_scope():
    with pytest.raises(svc.DeclarationOutOfScope):
        _file(_Client(raises=_api_error("file_it_declaration: employee x is not an employee of client y of firm z", "42501")))


def test_the_verified_refusal_is_known_by_its_message_when_no_sqlstate_comes_with_it():
    """A client that reports only the text (the real-database double does) still gets the refusal."""
    with pytest.raises(svc.DeclarationVerified):
        _file(_Client(raises=_Msg("declaration_verified: nope")))


class _Msg(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.code = ""


@pytest.mark.parametrize("raised", [_api_error("permission denied for function file_it_declaration", "42501"),
                                    _api_error("something else", "XX000"), RuntimeError("connection reset")])
def test_any_other_failure_passes_through_unchanged(raised):
    """Including the database's own "permission denied" (also SQLSTATE 42501): a function that is not granted to the client that
    called it is a deployment fault, and a door must not report it as "employee not found"."""
    with pytest.raises(type(raised)) as e:
        _file(_Client(raises=raised))
    assert e.value is raised
