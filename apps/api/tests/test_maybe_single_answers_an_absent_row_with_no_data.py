"""`.maybe_single().execute()` must answer an absent row with `data=None`.

postgrest 0.18 returns None itself on zero rows, and 112 call sites read
`.data` straight off the result — so the first request to meet a genuinely
absent row (a firm with no branding saved, a month with no payroll run) raised
AttributeError and surfaced as a 500 instead of the 404 or empty state written
beneath it. core/supabase_client.py restores the contract at the library seam.

These tests drive the REAL postgrest request builders over a mocked HTTP
transport, so they exercise the code production runs rather than a fake of it.
"""
from __future__ import annotations

import httpx
import pytest
from postgrest import SyncPostgrestClient
from postgrest._sync.request_builder import SyncMaybeSingleRequestBuilder
from postgrest.exceptions import APIError

import core.supabase_client as supabase_client

_ZERO_ROWS = {
    "code": "PGRST116",
    "details": "The result contains 0 rows",
    "hint": None,
    "message": "JSON object requested, multiple (or no) rows returned",
}


def _builder(status: int, body) -> SyncMaybeSingleRequestBuilder:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = SyncPostgrestClient("http://postgrest.test")
    client.session = httpx.Client(
        base_url="http://postgrest.test", transport=httpx.MockTransport(handler)
    )
    return client.from_("firm_branding").select("*").eq("firm_id", "f").maybe_single()


def test_the_fix_is_installed_on_the_class_every_query_uses():
    assert SyncMaybeSingleRequestBuilder.execute is supabase_client._maybe_single_execute


def test_premise_the_library_itself_answers_an_absent_row_with_none():
    # Without this the next test could pass against a library that had already
    # been fixed upstream, and would be proving nothing.
    original = supabase_client._library_maybe_single_execute
    assert original is not None
    assert original(_builder(406, _ZERO_ROWS)) is None


def test_an_absent_row_is_a_response_whose_data_is_none():
    resp = _builder(406, _ZERO_ROWS).execute()
    assert resp is not None
    assert resp.data is None
    # The shape every call site reads: `(...execute().data) or {}` / `if not row`.
    assert (resp.data or {}) == {}


def test_a_present_row_comes_back_as_the_row():
    assert _builder(200, {"id": "a", "firm_id": "f"}).execute().data == {"id": "a", "firm_id": "f"}


def test_a_real_refusal_keeps_its_own_sqlstate():
    # The library used to swallow this and raise a generic "Missing response"
    # (code 204) instead, so document_failure_detail could never tell a
    # permission refusal from a transient fault.
    refusal = {"code": "42501", "details": None, "hint": None,
               "message": "permission denied for table firm_branding"}
    with pytest.raises(APIError) as exc:
        _builder(403, refusal).execute()
    assert exc.value.code == "42501"


def test_more_than_one_row_is_still_an_error():
    many = dict(_ZERO_ROWS, details="The result contains 2 rows")
    with pytest.raises(APIError) as exc:
        _builder(406, many).execute()
    assert exc.value.code == "PGRST116"
