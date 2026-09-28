"""A payslip states whether the run behind it is final (apex-payroll-yearend-08).

WHAT WAS WRONG
    `build_payslip_pdf(slip, employee, run, employer, ytd=None)` received `run`
    — a `payroll_runs` row carrying `status` — and never read it. PAY-04 is
    explicit that a DRAFT run has deducted nothing: `_tds_already_deducted_this_fy`
    and its neighbours in `routers/payroll.py` all filter on
    `domain.payroll.run_status.PAYROLL_RELEASED` for exactly that reason. A
    payslip is the one document most likely to be printed or emailed the moment
    it exists, and this one carried no mark at all to say a draft's PF, ESI, TDS
    and net pay can still change before the run is finalised.

    `get_payslip_pdf`'s own `payroll_runs` embed did not even select `status`,
    so fixing `build_payslip_pdf` alone would have watermarked EVERY payslip
    downloaded through the single-slip endpoint as a draft, finalised ones
    included — `run.get("status")` would always have read `None`.

    Separately: the closing disclaimer paragraph was appended after the Net
    Pay/YTD block with no allowance for it, so for a representative slip
    (employer contributions shown, a year-to-date block present) everything up
    to and including the year-to-date table filled page 1 and the one-sentence
    disclaimer alone spilled onto a page 2 by itself — "Page 1 of 2 / Page 2 of
    2" for what is a one-page document.

WHAT THIS PINS
    (1) The SAME visual mechanism `services/year_end_pdf_service.py` already
        uses for its own draft cover page — the literal string
        "DRAFT — NOT FOR DISTRIBUTION" — appears when `run["status"]` is not in
        `domain.payroll.run_status.PAYROLL_RELEASED` ("finalized", "paid"), and
        is absent once it is.
    (2) `run` missing `status` altogether reads as NOT released (fail closed,
        the PAY-04 direction), not as silently final.
    (3) A representative payslip (basic/HRA/allowances, all four statutory
        deductions, employer PF/ESI/EDLI/admin, a six-month YTD) renders to
        ONE page, not two.
"""
from __future__ import annotations

import io

import pdfplumber
import pytest

from services.payslip_pdf_service import build_payslip_pdf, get_payslip_pdf


SLIP = {
    "id": "S1", "employee_id": "E1", "month": 9, "year": 2026,
    "basic_paise": 30_000_00, "hra_paise": 12_000_00, "medical_paise": 1_250_00,
    "special_allowance_paise": 5_000_00, "gross_paise": 48_250_00,
    "pf_employee_paise": 3_600_00, "esi_employee_paise": 0, "pt_paise": 200_00,
    "tds_paise": 1_500_00, "net_paise": 42_950_00,
    "working_days": 30, "days_present": 30,
    "pf_employer_paise": 3_600_00, "pf_employer_epf_paise": 2_100_00,
    "pf_employer_eps_paise": 1_500_00, "esi_employer_paise": 0,
    "edli_paise": 150_00, "pf_admin_paise": 150_00,
}
EMPLOYEE = {"name": "Asha Kumar", "pan": "ABCPK1234F", "designation": "Fitter",
            "department": "Assembly", "uan": "100200300400",
            "bank_account_no": "0011223344", "bank_ifsc": "HDFC0001234"}
EMPLOYER = {"legal_name": "Acme Manufacturing Private Limited",
            "epf_establishment_code": "MH/12345", "tan": "MUMB12345A"}
YTD = {"months": 6, "gross_paise": 48_250_00 * 6,
       "deductions_paise": (3_600_00 + 200_00 + 1_500_00) * 6,
       "tds_paise": 1_500_00 * 6, "net_paise": 42_950_00 * 6}

_BANNER = "DRAFT — NOT FOR DISTRIBUTION"


def _pages(pdf: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [page.extract_text() or "" for page in doc.pages]


def _text(pdf: bytes) -> str:
    return "\n".join(_pages(pdf))


# ── the draft banner ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["draft", "review"])
def test_an_unreleased_run_watermarks_the_payslip(status):
    run = {"month": "2026-09", "status": status}
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=YTD))
    assert _BANNER in body


@pytest.mark.parametrize("status", ["finalized", "paid"])
def test_a_released_run_carries_no_watermark(status):
    run = {"month": "2026-09", "status": status}
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=YTD))
    assert _BANNER not in body


def test_a_run_with_no_status_at_all_is_treated_as_not_final():
    """Fail CLOSED, PAY-04's direction — a run this function cannot prove is
    released must not be presented as though it were."""
    run = {"month": "2026-09"}
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=YTD))
    assert _BANNER in body


def test_no_run_at_all_is_also_treated_as_not_final():
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, {}, EMPLOYER, ytd=YTD))
    assert _BANNER in body


def test_the_watermark_does_not_disturb_the_employers_own_letterhead():
    """The banner is additive — every other regression this file's sibling
    (test_a_payslip_names_the_employer_not_the_practice.py) pins still holds."""
    run = {"month": "2026-09", "status": "draft"}
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=YTD))
    assert "Acme Manufacturing Private Limited" in body
    assert "Asha Kumar" in body


def test_the_single_slip_download_path_reads_the_runs_status(monkeypatch):
    """get_payslip_pdf's own `payroll_runs` embed used to omit `status`
    entirely, so `run.get("status")` inside build_payslip_pdf always read None
    — which is "not released", so EVERY payslip downloaded this way would have
    been watermarked draft, finalised ones included. The embed must name the
    column, or this reads a stale row shape forever."""
    import inspect

    from services import payslip_pdf_service as pps

    src = inspect.getsource(pps.get_payslip_pdf)
    assert "payroll_runs(month, firm_id, client_id, status)" in src, (
        "the payroll_runs embed in get_payslip_pdf must select status, or "
        "build_payslip_pdf's run.get('status') always reads None"
    )


def test_get_payslip_pdf_end_to_end_reflects_a_finalized_run(monkeypatch):
    """The single-slip download path, exercised whole: a finalised run's own
    payslip carries no draft banner."""
    class _Res:
        data = {
            "id": "S1", **{k: v for k, v in SLIP.items() if k not in ("id",)},
            "payroll_employees": dict(EMPLOYEE),
            "payroll_runs": {"month": "2026-09", "firm_id": "F1",
                             "client_id": "C1", "status": "finalized"},
        }

    class _FakeTable:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Res()

    class _FakeDB:
        def table(self, name): return _FakeTable()

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _FakeDB())
    # load_employer and load_ytd hit the database too; keep the test to the one
    # thing it is pinning (status reaching the renderer) by short-circuiting
    # both to inert-but-valid answers.
    monkeypatch.setattr(
        "services.payslip_pdf_service.load_employer",
        lambda firm_id, client_id: dict(EMPLOYER))
    monkeypatch.setattr(
        "services.payslip_pdf_service.load_ytd",
        lambda firm_id, client_id, month, employee_ids: {})

    pdf, _filename = get_payslip_pdf("S1", "F1")
    assert _BANNER not in _text(pdf)


def test_get_payslip_pdf_end_to_end_reflects_a_draft_run(monkeypatch):
    class _Res:
        data = {
            "id": "S1", **{k: v for k, v in SLIP.items() if k not in ("id",)},
            "payroll_employees": dict(EMPLOYEE),
            "payroll_runs": {"month": "2026-09", "firm_id": "F1",
                             "client_id": "C1", "status": "draft"},
        }

    class _FakeTable:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Res()

    class _FakeDB:
        def table(self, name): return _FakeTable()

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _FakeDB())
    monkeypatch.setattr(
        "services.payslip_pdf_service.load_employer",
        lambda firm_id, client_id: dict(EMPLOYER))
    monkeypatch.setattr(
        "services.payslip_pdf_service.load_ytd",
        lambda firm_id, client_id, month, employee_ids: {})

    pdf, _filename = get_payslip_pdf("S1", "F1")
    assert _BANNER in _text(pdf)


# ── the disclaimer no longer strands itself on a page of its own ────────────

def test_a_representative_payslip_with_a_ytd_block_fits_on_one_page():
    """Employer contributions shown and a six-month YTD present — the shape
    that used to fill page 1 exactly and leave the closing disclaimer alone on
    a page 2. `run["status"]` is 'finalized' so the draft banner above plays no
    part in the height this measures."""
    run = {"month": "2026-09", "status": "finalized"}
    pdf = build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=YTD)
    pages = _pages(pdf)
    assert len(pages) == 1, (
        f"expected one page, got {len(pages)} — page 2 was:\n{pages[1] if len(pages) > 1 else ''}"
    )


def test_the_same_payslip_without_a_ytd_block_also_fits_on_one_page():
    run = {"month": "2026-09", "status": "finalized"}
    pdf = build_payslip_pdf(SLIP, EMPLOYEE, run, EMPLOYER, ytd=None)
    assert len(_pages(pdf)) == 1


def test_the_closing_disclaimer_is_never_the_only_thing_on_its_page():
    """Whatever the total content, IF a payslip still runs to a second page,
    that page must not be the disclaimer sentence alone with nothing else —
    the orphaned-page shape this fix exists to end. A heavier slip (every
    earning and deduction line populated) is used because it genuinely does
    not fit on one page even after the tightened spacing."""
    heavy_slip = {
        **SLIP,
        "da_paise": 500_00, "lta_paise": 100_00, "other_allowances_paise": 100_00,
        "one_time_earnings_paise": 200_00, "loan_recovery_paise": 100_00,
        "esi_employer_paise": 271_375,
    }
    run = {"month": "2026-09", "status": "finalized"}
    pdf = build_payslip_pdf(heavy_slip, EMPLOYEE, run, EMPLOYER, ytd=YTD)
    pages = _pages(pdf)
    if len(pages) > 1:
        last = pages[-1]
        assert "Net Pay" in last or "Year to Date" in last or "In words" in last, (
            "the last page carries only the disclaimer, orphaned, with "
            f"nothing else on it:\n{last}"
        )
