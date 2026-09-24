"""What `plan_share` refuses, and why each refusal is not the others.

── WHY THERE IS A DOMAIN MODULE AT ALL ──────────────────────────────────────
Publishing a statement to a client's portal is two privileged writes — a file
into a storage bucket and a row saying that client may read it — and the browser
held both. Moving them behind `rbac()` is the point; deciding WHAT may be
written in one place is what stops the decision being re-made, differently, on
the next screen that shares something.

── THE PATH IS ASSEMBLED FROM A CALLER-SUPPLIED STRING ──────────────────────
Which is the one thing in here that is a security property rather than a
correctness one. `storage_path` is `shared_reports/{client_id}/{name}`, and the
portal decides what a client may open by exactly that prefix — so a file name
carrying `../` would write, and be readable, outside the client's own folder.
`_safe_name` is a WHITELIST for that reason: a blacklist of `..` and `/` has to
anticipate every encoding of a separator, and a report name only needs letters,
digits, dot, dash and underscore.
"""
from __future__ import annotations

import pytest

from domain.reporting.shared_report import (
    BUCKET,
    MAX_BYTES,
    REPORT_TYPES,
    ShareRefused,
    plan_share,
)

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CLIENT = "11111111-2222-3333-4444-555555555555"


def _plan(**over):
    kw = dict(
        client_id=_CLIENT,
        screen_report_id="trial",
        file_name="trial-accrual-FY2025-26.xlsx",
        content_type=_XLSX,
        size_bytes=42_000,
    )
    kw.update(over)
    return plan_share(**kw)


def test_the_trial_balance_is_the_one_that_never_worked():
    """The screen's id is `trial` and the column's value is `trial_balance`.
    Two of the three reports worked by coincidence; this is the translation
    whose absence made the button fail for as long as it existed."""
    assert _plan().report_type == "trial_balance"
    assert _plan(screen_report_id="bs").report_type == "balance_sheet"
    assert _plan(screen_report_id="pl").report_type == "pl"


def test_a_report_nobody_named_is_refused_rather_than_written_through():
    """The conditional this replaced passed an unknown id STRAIGHT THROUGH to
    the column, so the failure happened at the database, after the upload."""
    with pytest.raises(ShareRefused) as exc:
        _plan(screen_report_id="cash_flow")
    assert "cash_flow" in str(exc.value)


def test_case_and_whitespace_do_not_decide_whether_a_share_works():
    assert _plan(screen_report_id="  Trial ").report_type == "trial_balance"


def test_a_file_name_cannot_climb_out_of_the_clients_own_folder():
    plan = _plan(file_name="../../../etc/passwd")
    assert plan.storage_path == f"shared_reports/{_CLIENT}/passwd.xlsx"
    assert ".." not in plan.storage_path
    # A Windows separator is a separator too, and a name that is nothing but
    # dots must not survive as a leading-dot path.
    assert _plan(file_name=r"..\..\secrets").file_name == "secrets.xlsx"
    assert _plan(file_name="...").file_name.endswith(".xlsx")
    assert not _plan(file_name="...").file_name.startswith(".")


def test_the_client_id_is_in_the_path_and_must_be_one():
    """Without it every client's shares land in one folder, and the portal
    decides what a client may open by this prefix."""
    assert _plan().storage_path.startswith(f"shared_reports/{_CLIENT}/")
    for bad in ("", "all", "../other-firm"):
        with pytest.raises(ShareRefused):
            _plan(client_id=bad)


def test_an_empty_or_oversized_workbook_is_refused_with_its_own_sentence():
    """Two different things to go and do: a report that computed to nothing,
    and a file that is not one of these reports at all."""
    with pytest.raises(ShareRefused) as empty:
        _plan(size_bytes=0)
    with pytest.raises(ShareRefused) as big:
        _plan(size_bytes=MAX_BYTES + 1)
    assert str(empty.value) != str(big.value)
    assert "empty" in str(empty.value)
    assert "limit" in str(big.value)
    # The boundary is inclusive — exactly at the limit is allowed.
    assert _plan(size_bytes=MAX_BYTES).report_type == "trial_balance"


def test_only_a_workbook_is_shared_and_an_unstated_type_is_not_refused():
    """A browser that sends no content type is not sending a PDF; it is sending
    a Blob whose type the caller did not set. The plan stamps the xlsx type
    either way, so the portal's download is not left to guess."""
    with pytest.raises(ShareRefused):
        _plan(content_type="application/pdf")
    assert _plan(content_type=None).content_type == _XLSX
    assert _plan().content_type == _XLSX


def test_the_bucket_is_named_once():
    """The portal signs a URL for the row's `storage_path` against this bucket,
    so a second spelling is a share that uploads and then cannot be opened."""
    assert BUCKET == "Documents"


@pytest.mark.parametrize("screen_id", sorted(REPORT_TYPES))
def test_every_report_the_map_names_plans_without_raising(screen_id: str):
    assert _plan(screen_report_id=screen_id).storage_path
