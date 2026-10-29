"""A malformed id in a named row answers as a missing row (POST-A-353, second half).

THE GAP
    The rule of POST-A-338 promises that a row which is not this client's (another client's, another firm's, deleted, invented) is a 404
    "That vendor was not found." in the same words. A string that is not a UUID is also a row that cannot exist, but PostgREST rejects it
    with a type error (SQLSTATE 22P02, "invalid input syntax for type uuid") before it looks for a row, and the route turned that into a
    500, so the answer differed from the promise exactly for the input a person typing an id by hand is likeliest to send.

WHAT IS HELD
    * every ownership lookup in `services/named_row_ownership` answers a 22P02 as the same 404 a missing row gets;
    * any OTHER database error still propagates (a lookup that could not run must not read as "not found");
    * the answer is taken from the database's own error and not from a pattern in the helper's first line, because the test suites use
      readable ids that are not UUIDs, so a shape check there would refuse them.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

from services import named_row_ownership as nro

CASES = [
    (nro.vendor_is_the_clients, "vendor"),
    (nro.customer_is_the_clients, "customer"),
    (nro.purchase_bill_is_the_clients, "bill"),
    (nro.bank_account_is_the_clients, "bank account"),
    (nro.sales_invoice_is_the_clients, "invoice"),
]


class _Query:
    def __init__(self, exc=None, data=None):
        self._exc, self._data = exc, data or []

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def execute(self):
        if self._exc:
            raise self._exc
        return type("R", (), {"data": self._data})()


class _Db:
    def __init__(self, exc=None, data=None):
        self._exc, self._data = exc, data

    def table(self, _name):
        return _Query(self._exc, self._data)


def _type_error():
    return APIError({"message": 'invalid input syntax for type uuid: "not-an-id"', "code": "22P02", "hint": None, "details": None})


@pytest.mark.parametrize("check, what", CASES)
def test_a_malformed_id_is_the_404_a_missing_row_gets(check, what):
    with pytest.raises(HTTPException) as e:
        check(_Db(exc=_type_error()), "firm", "client", "not-an-id")
    assert e.value.status_code == 404 and e.value.detail == f"That {what} was not found."


@pytest.mark.parametrize("check, what", CASES)
def test_it_reads_exactly_as_a_row_that_is_not_there(check, what):
    with pytest.raises(HTTPException) as missing:
        check(_Db(data=[]), "firm", "client", "11111111-1111-1111-1111-111111111111")
    with pytest.raises(HTTPException) as malformed:
        check(_Db(exc=_type_error()), "firm", "client", "not-an-id")
    assert (missing.value.status_code, missing.value.detail) == (malformed.value.status_code, malformed.value.detail)


@pytest.mark.parametrize("check, what", CASES)
def test_another_database_error_is_not_read_as_not_found(check, what):
    boom = APIError({"message": "connection reset", "code": "08006", "hint": None, "details": None})
    with pytest.raises(APIError):
        check(_Db(exc=boom), "firm", "client", "11111111-1111-1111-1111-111111111111")


@pytest.mark.parametrize("check, what", CASES)
def test_a_row_that_is_there_passes(check, what):
    check(_Db(data=[{"id": "x"}]), "firm", "client", "11111111-1111-1111-1111-111111111111")


@pytest.mark.parametrize("check, what", CASES)
def test_nothing_named_asks_nothing(check, what):
    check(_Db(exc=_type_error()), "firm", "client", None)
    check(_Db(exc=_type_error()), "firm", "client", "  ")
