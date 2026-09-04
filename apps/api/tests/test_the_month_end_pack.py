"""
The month-end pack: what a CA hands over when the month is done.

WHAT WAS MISSING

Three things, and one of them was a wrong number rather than a missing feature.

1. THE STATUTORY SUMMARY UNDERSTATED THE EPFO CHALLAN.
   `pf_total_paise` is the 12% either side — employee and employer. Two more
   amounts go on the SAME challan, which migration 329 added and this summary
   never learned about: EDLI at 0.5% (EDLI 1976) and the administrative charge
   at 0.5% floored at Rs 500 per establishment.

   So a CA reconciling this screen against the challan they were about to pay
   was short by roughly 1% of PF wages every month — about Rs 150 a member at
   the Rs 15,000 ceiling — with no line to explain the difference. The LEDGER
   was fixed for this in migration 329; the screen was not.

2. THIRTY PAYSLIPS MEANT THIRTY CLICKS, AND THIRTY FILES OF THE SAME NAME.
   The single-slip endpoint names its file `payslip-YYYY-MM.pdf` — the month,
   not the person — which is fine for one download and useless for a month-end
   pack.

3. THE SALARY REGISTER WAS JSON AND NOTHING ELSE.
   A register is a document. It goes to the client, into the audit file, and
   beside the bank advice, and the only way to get one out was to read a screen
   and retype it.

NEGATIVE CONTROLS
    Drop edli/pf_admin from the summary and
    test_the_summary_reports_the_whole_challan fails.
    Give every payslip in the zip the same name and
    test_two_employees_do_not_collide_in_the_zip fails.
    Write paise into the CSV instead of rupees and
    test_the_register_is_in_rupees_at_the_file_boundary fails.
"""
from __future__ import annotations

import csv
import io

import pytest

from domain.payroll import register as reg


# ─── the register file ──────────────────────────────────────────────────────

def _rows(blob: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(blob.decode("utf-8-sig"))))


def _slip(**kw) -> dict:
    base = {
        "working_days": 26, "days_present": 26, "lop_days": 0,
        "basic_paise": 3_000_000, "hra_paise": 0, "da_paise": 0,
        "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
        "other_allowances_paise": 0, "one_time_earnings_paise": 0,
        "gross_paise": 3_000_000,
        "pf_employee_paise": 180_000, "esi_employee_paise": 0,
        "pt_paise": 20_000, "tds_paise": 0, "loan_recovery_paise": 0,
        "net_paise": 2_800_000,
        "pf_employer_paise": 180_000, "esi_employer_paise": 0,
        "edli_paise": 7_500, "pf_admin_paise": 7_500,
        "payroll_employees": {"name": "Asha Rao", "pan": "ABCPA1234A",
                              "designation": "Analyst", "department": "Ops",
                              "bank_account_no": "12345678", "bank_ifsc": "HDFC0001234"},
    }
    base.update(kw)
    return base


def test_the_register_is_in_rupees_at_the_file_boundary():
    """Money crosses the API as integer paise and becomes rupees only at the
    boundary where a document is produced — the same rule domain/gst/money.py
    follows for the statutory payloads."""
    rows = _rows(reg.to_csv([_slip()]))
    header, body = rows[0], rows[1]
    assert body[header.index("Gross")] == "30000.00"
    assert body[header.index("Net Pay")] == "28000.00"
    assert body[header.index("PF (employee)")] == "1800.00"


def test_the_amounts_carry_no_thousands_separator():
    """A register is pasted back into a spreadsheet as often as it is read.
    parseFloat("1,25,000") is 1, and grouping is what makes that happen."""
    rows = _rows(reg.to_csv([_slip(gross_paise=12_500_000, net_paise=12_500_000)]))
    header, body = rows[0], rows[1]
    assert body[header.index("Gross")] == "125000.00"
    assert "," not in body[header.index("Gross")]


def test_a_negative_amount_keeps_its_sign():
    """A one-time earning can be a RECOVERY of an earlier overpayment
    (migration 331), so the register has to be able to print one."""
    rows = _rows(reg.to_csv([_slip(one_time_earnings_paise=-400_000)]))
    header, body = rows[0], rows[1]
    assert body[header.index("Bonus / Incentive / Arrears")] == "-4000.00"


def test_the_register_totals_itself():
    """A register is checked by adding it up against the run header and the
    journal. A file that makes somebody do that by hand invites the arithmetic
    to be skipped."""
    rows = _rows(reg.to_csv([_slip(), _slip(gross_paise=1_000_000, net_paise=900_000)]))
    header, total = rows[0], rows[-1]
    assert total[header.index("Employee")] == "TOTAL"
    assert total[header.index("Gross")] == "40000.00"
    assert total[header.index("Net Pay")] == "37000.00"


def test_an_empty_month_is_a_header_and_no_total():
    """No slips means no total row to add up — a TOTAL of zero beneath no rows
    reads as a month that was run and paid nobody."""
    rows = _rows(reg.to_csv([]))
    assert len(rows) == 1 and rows[0][0] == "Employee"


def test_the_employee_is_flattened_out_of_the_join():
    rows = _rows(reg.to_csv([_slip()]))
    header, body = rows[0], rows[1]
    assert body[header.index("Employee")] == "Asha Rao"
    assert body[header.index("PAN")] == "ABCPA1234A"
    assert body[header.index("Bank IFSC")] == "HDFC0001234"


def test_the_column_order_is_the_document_s_order():
    """Identity, attendance, EARNED, DEDUCTED, PAID — the order a payslip reads
    in, so a register and a payslip can be checked against each other line by
    line. Pinned because a register whose columns move between months cannot be
    diffed, and diffing two months is most of what one is for."""
    names = [h for h, _k in reg.COLUMNS]
    assert names.index("Basic") < names.index("Gross")
    assert names.index("Gross") < names.index("PF (employee)")
    assert names.index("TDS") < names.index("Net Pay")
    assert names[0] == "Employee"


def test_the_file_carries_a_bom_so_excel_reads_utf8():
    """Without it Excel opens a UTF-8 file as the local code page, which is
    where an employee's name turns into mojibake."""
    assert reg.to_csv([_slip()]).startswith(b"\xef\xbb\xbf")


# ─── the payslip zip ────────────────────────────────────────────────────────

def test_two_employees_do_not_collide_in_the_zip():
    """The single-slip endpoint names every file for the MONTH, so thirty
    downloads are thirty files called the same thing. And two employees
    genuinely can share a name, so the collision is resolved rather than
    assumed away — a zip entry written twice under one name is not an error,
    it is a file the reader silently keeps only one of."""
    from services.payslip_pdf_service import _payslip_filename
    used: set = set()
    a = _payslip_filename("Asha Rao", "2026-08", used)
    b = _payslip_filename("Asha Rao", "2026-08", used)
    assert a == "payslip-2026-08-Asha-Rao.pdf"
    assert b == "payslip-2026-08-Asha-Rao-2.pdf"
    assert a != b


def test_a_name_that_is_not_a_filename_still_becomes_one():
    from services.payslip_pdf_service import _payslip_filename
    used: set = set()
    assert _payslip_filename("R. Krishnan / Ops", "2026-08", used) \
        == "payslip-2026-08-R-Krishnan-Ops.pdf"
    assert _payslip_filename("///", "2026-08", used) == "payslip-2026-08-employee.pdf"


# ─── the statutory summary ══════════════════════════════════════════════════

import routers.payroll as payroll_mod  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-PACK"
USER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    d.seed("payroll_runs", {
        "id": "RUN-1", "firm_id": FIRM, "client_id": "CLI", "month": "2026-08",
        "status": "finalized", "headcount": 2,
        "total_gross_paise": 10_000_000, "total_net_paise": 8_600_000,
        "total_pf_paise": 360_000,        # 12% employee + 12% employer
        "total_edli_paise": 15_000,       # 0.5% EDLI
        "total_pf_admin_paise": 50_000,   # the Rs 500 establishment floor
        "total_esi_paise": 0, "total_pt_paise": 40_000, "total_tds_paise": 0,
        "total_one_time_paise": 5_000_000,
    })
    return d


def test_the_summary_reports_the_whole_challan(db):
    """EDLI and the administrative charge are remitted on the SAME challan as
    the 12% either side. A summary that shows only the contributions is short
    of what the CA is about to pay, with nothing on screen to explain it."""
    out = payroll_mod.statutory_summary(client_id="CLI", month="2026-08",
                                        current_user=USER)["data"]
    assert out["pf_total_paise"] == 360_000
    assert out["edli_paise"] == 15_000
    assert out["pf_admin_paise"] == 50_000
    assert out["pf_challan_total_paise"] == 425_000, "contributions + EDLI + admin"


def test_the_summary_says_how_much_was_not_the_salary_bill(db):
    """A month whose gross jumped is the first thing a CA looks at here, and a
    bonus is the usual reason (migration 331)."""
    out = payroll_mod.statutory_summary(client_id="CLI", month="2026-08",
                                        current_user=USER)["data"]
    assert out["one_time_paise"] == 5_000_000
    assert out["gross_paise"] == 10_000_000


def test_a_run_with_no_edli_reports_the_contributions_alone(db):
    """A client with no PF-applicable employee owes nothing extra, and the
    challan total must then equal the contributions rather than being padded."""
    for r in db.rows("payroll_runs"):
        r["total_edli_paise"] = 0
        r["total_pf_admin_paise"] = 0
    out = payroll_mod.statutory_summary(client_id="CLI", month="2026-08",
                                        current_user=USER)["data"]
    assert out["pf_challan_total_paise"] == out["pf_total_paise"] == 360_000


def test_a_month_with_no_run_is_none_not_zeroes(db):
    """Zeroes would read as a month that ran and owed nothing."""
    assert payroll_mod.statutory_summary(client_id="CLI", month="2026-09",
                                         current_user=USER)["data"] is None


# ─── 4. The headers a browser is allowed to read ─────────────────────────────
#
# A fourth thing was wrong, and it was invisible from the server side because
# the server sends the header correctly either way.
#
# A browser lets script read only the seven CORS-safelisted response headers —
# Cache-Control, Content-Language, Content-Length, Content-Type, Expires,
# Last-Modified, Pragma — unless the server names the others in
# Access-Control-Expose-Headers. `apps/web` is on Cloudflare Pages and this API
# is on Render, so EVERY request is cross-origin.
#
# So `Content-Disposition` was unreadable across all twelve download endpoints.
# `lib/api`'s downloadFile reads it for the filename, never found it, and
# silently fell back to its own — which is why a downloaded payslip arrived
# named for the month rather than the person even before the bulk endpoint
# existed. And X-Payslip-Problems, the header the zip uses to say which
# employees it could not render, would have been the same as not sending it.

def _cors_kwargs():
    """The CORSMiddleware options as main.py actually registers them."""
    import main
    from fastapi.middleware.cors import CORSMiddleware
    for mw in main.app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw.kwargs
    raise AssertionError("CORSMiddleware is not installed")


def test_the_filename_header_is_readable_by_the_browser():
    exposed = _cors_kwargs().get("expose_headers") or []
    assert "Content-Disposition" in exposed, (
        "downloadFile reads Content-Disposition for the filename; without this "
        "it is invisible cross-origin and every download uses the fallback name"
    )


def test_the_payslip_problems_header_is_readable_by_the_browser():
    exposed = _cors_kwargs().get("expose_headers") or []
    assert "X-Payslip-Problems" in exposed, (
        "a zip cannot carry a message in its body; if this header cannot be "
        "read, a zip one payslip short says nothing at all"
    )


def test_every_header_a_download_endpoint_sets_is_exposed():
    """The rule, not the two instances. A future endpoint that reports on a
    header and forgets to expose it is the same bug again, and the failure mode
    is silence rather than an error."""
    import re
    from pathlib import Path

    routers = Path(__file__).resolve().parent.parent / "routers"
    exposed = {h.lower() for h in (_cors_kwargs().get("expose_headers") or [])}
    safelisted = {
        "cache-control", "content-language", "content-length",
        "content-type", "expires", "last-modified", "pragma",
    }
    missing = set()
    for path in routers.glob("*.py"):
        for name in re.findall(r'["\'](Content-Disposition|X-[A-Za-z0-9-]+)["\']\s*:',
                               path.read_text()):
            if name.lower() not in safelisted and name.lower() not in exposed:
                missing.add(f"{name} ({path.name})")
    assert not missing, (
        "these response headers are set by a router but not named in "
        f"expose_headers, so no browser can read them: {sorted(missing)}"
    )
