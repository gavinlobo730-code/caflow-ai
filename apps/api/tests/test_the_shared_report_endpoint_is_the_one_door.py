"""POST /api/accounting/shared-reports — the door the browser's two privileged
writes moved behind.

Driven through the real endpoint function so the guards that matter are the
ones exercised: the assignment-scope check, the domain module's refusals, and
the FY label's validator — which is the one that reads as present and does
nothing when it is written the wrong way round.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

import routers.shared_reports as sr

FIRM = "FIRM-A"
CLIENT = "11111111-2222-3333-4444-555555555555"
CALLER = {"firm_id": FIRM, "id": "u1", "email": "ca@f.test", "role": "Partner"}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload(name: str = "trial.xlsx", body: bytes = b"PK\x03\x04payload") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(body), headers={"content-type": _XLSX})


def _call(**over):
    kw = dict(
        file=_upload(),
        client_id=CLIENT,
        report_id="trial",
        report_label="Trial Balance (Accrual) — FY 2025-26",
        financial_year="2025-26",
        current_user=CALLER,
    )
    kw.update(over)
    return sr.share_report_to_portal(**kw)


def test_the_trial_balance_share_reaches_the_table_with_the_value_it_accepts():
    """The whole point: `trial` is not a value the CHECK admits, so the browser
    sending it meant the insert failed after the upload, every time."""
    out = _call()
    assert out["success"] is True
    row = out["data"]["shared_report"]
    assert row["report_type"] == "trial_balance"
    assert row["firm_id"] == FIRM
    assert row["client_id"] == CLIENT
    assert row["shared_by"] == "u1"
    assert row["storage_path"] == f"shared_reports/{CLIENT}/trial.xlsx"
    assert row["file_size_bytes"] == len(b"PK\x03\x04payload")


def test_a_client_the_caller_cannot_reach_is_not_found():
    """Assignment scope, not just tenancy — an Executive who cannot see this
    client must not publish that client's balance sheet. The message is the
    same either way so it cannot be used to probe which clients exist."""
    def _no(user, client_id):  # noqa: ARG001
        return False

    real = sr.can_access_client
    sr.can_access_client = _no
    try:
        with pytest.raises(HTTPException) as exc:
            _call()
    finally:
        sr.can_access_client = real
    assert exc.value.status_code == 404
    assert "not found" in str(exc.value.detail).lower()


@pytest.mark.parametrize(
    "over",
    [
        {"report_id": "cash_flow"},
        {"file": _upload(body=b"")},
        {"file": _upload(name="x.pdf")},
    ],
    ids=["unknown report", "empty workbook", "not a workbook"],
)
def test_the_domain_refusals_reach_the_caller_as_a_sentence(over):
    """A 422 with the module's own wording, not a 500 and not a raw Postgres
    constraint message — which is what the browser used to show."""
    if "file" in over and over["file"].filename == "x.pdf":
        over["file"] = UploadFile(
            filename="x.pdf", file=io.BytesIO(b"%PDF"),
            headers={"content-type": "application/pdf"},
        )
    with pytest.raises(HTTPException) as exc:
        _call(**over)
    assert exc.value.status_code == 422
    assert exc.value.detail and not str(exc.value.detail).startswith("500")


def test_the_financial_year_is_validated_and_not_merely_annotated():
    """`FYLabel = Form(...)` builds the field from the default and DISCARDS the
    Annotated metadata, so the endpoint reads as guarded and validates nothing —
    and `2025-27` then means 2025-26. This asserts the parameter is declared the
    way that works, at the signature, because calling the function directly
    bypasses FastAPI's own validation entirely.
    """
    import inspect
    import typing

    from models.fy import FYLabel

    param = inspect.signature(sr.share_report_to_portal).parameters["financial_year"]
    hints = typing.get_type_hints(sr.share_report_to_portal, include_extras=True)
    assert hints["financial_year"] is FYLabel or typing.get_args(hints["financial_year"]), (
        "financial_year is no longer an Annotated FYLabel"
    )
    assert param.default is Ellipsis, (
        "financial_year carries a Form()/Query() DEFAULT — FastAPI then builds "
        "the field from it and throws the validator away. Write it as "
        "Annotated[FYLabel, Form()] = ... instead."
    )


def test_the_two_payload_literals_do_not_drift():
    """The mock answer and the live INSERT spell the same dict twice.

    That duplication is deliberate — `tests/test_backend_columns_exist_pg.py`
    reads the SOURCE to check every column against the real schema, so an
    insert whose payload is a name is invisible to it and counts against a
    budget with no headroom. Raising that budget is what its message invites
    and is the wrong trade on a door that writes a row granting a client read
    access to their own firm's statements.

    What duplication costs is drift, so this is the thing that stops it: the
    two literals must name the same columns, and the test reads them out of the
    AST rather than matching a spelling of them.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(sr))
    dicts = [
        {k.value for k in n.keys if isinstance(k, ast.Constant)}
        for n in ast.walk(tree)
        if isinstance(n, ast.Dict) and n.keys
        and {"firm_id", "client_id", "storage_path"} <= {
            k.value for k in n.keys if isinstance(k, ast.Constant)}
    ]
    assert len(dicts) == 2, (
        f"expected exactly two shared_reports payload literals, found "
        f"{len(dicts)} — if the duplication was removed, check that the "
        "INSERT still spells its columns out or the schema guard stops "
        "seeing them")
    assert dicts[0] == dicts[1], (
        f"the mock answer and the INSERT name different columns: "
        f"{dicts[0] ^ dicts[1]}")
