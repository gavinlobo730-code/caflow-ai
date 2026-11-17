"""
Time entry export — CSV and XLSX.

Rate/amount columns are derived from integer paise; amounts are emitted as
integer paise plus a display string so no float arithmetic touches money.

The rate and the amount are `time_rate.entry_worth`'s, the rule the Time screen
shows (POST-A-169). The export used to read the legacy `hourly_rate_paise` alone,
so every hour priced since migration 451 (whose rate is in `billable_rate_paise`)
left in the file at a rate of 0 and an amount of 0. An hour with no rate, a
non-billable hour and a running entry leave those cells EMPTY: "nobody said what
it is worth" is not "it is worth nothing". The column keeps its old name, because
it is still the rate for an hour and a saved spreadsheet reads it by name.
"""
import csv
import io
from typing import Optional

from core.ist_clock import ist_day_iso
from domain.billing import time_rate
from domain.money_text import rupees_paise

EXPORT_COLUMNS = [
    "date", "user_name", "client_name", "task_id", "description",
    "started_at", "ended_at", "duration_minutes", "hours",
    "is_billable", "hourly_rate_paise", "amount_paise", "amount_inr",
]


def _paise_to_inr_str(paise: int) -> str:
    return f"{rupees_paise(paise)}"


def build_export_rows(entries: list[dict], users_by_id: dict, clients_by_id: dict) -> list[dict]:
    rows = []
    for e in entries:
        minutes = e.get("duration_minutes") or 0
        # amount = minutes * rate / 60, floored per entry in integer paise (time_rate.value_paise)
        worth = time_rate.entry_worth(e)
        rate_paise, amount_paise = worth["rate_paise"], worth["value_paise"]
        user = users_by_id.get(e.get("user_id"), {})
        client = clients_by_id.get(e.get("client_id"), {})
        rows.append({
            "date": ist_day_iso(e.get("started_at")),
            "user_name": user.get("full_name") or user.get("email") or e.get("user_id", ""),
            "client_name": client.get("client_name") or "",
            "task_id": e.get("task_id") or "",
            "description": e.get("description") or "",
            "started_at": e.get("started_at") or "",
            "ended_at": e.get("ended_at") or "",
            "duration_minutes": minutes,
            "hours": f"{minutes // 60}:{minutes % 60:02d}",
            "is_billable": "Yes" if e.get("is_billable") else "No",
            "hourly_rate_paise": "" if rate_paise is None else rate_paise,
            "amount_paise": "" if amount_paise is None else amount_paise,
            "amount_inr": "" if amount_paise is None else _paise_to_inr_str(amount_paise),
        })
    return rows


def rows_to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


def rows_to_xlsx(rows: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Time Entries"
    ws.append(EXPORT_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([row[c] for c in EXPORT_COLUMNS])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_time_entries(
    firm_id: str,
    fmt: str = "csv",
    user_id: Optional[str] = None,
    client_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    effective_client_ids: Optional[set] = None,
) -> tuple[bytes, str, str]:
    """
    Export filtered time entries.

    `effective_client_ids` is the caller's M2 assignment scope (None means
    "every client in the firm" — a firm-wide role, or mock/dev): entries
    whose client_id falls outside it are dropped before the file is built,
    mirroring the router's own list_entries -> filter_by_client. A
    client-less entry (internal/admin work) is always kept.

    Returns:
        (content_bytes, filename, media_type)
    """
    from repositories.time_tracking_repository import time_tracking_repo
    from repositories.user_repository import user_repo
    from repositories.client_repository import client_repo

    entries = time_tracking_repo.find_all(
        firm_id=firm_id,
        user_id=user_id,
        client_id=client_id,
        date_from=date_from,
        date_to=date_to,
    )
    if effective_client_ids is not None:
        entries = [e for e in entries if not e.get("client_id") or e.get("client_id") in effective_client_ids]

    try:
        users_by_id = {u["id"]: u for u in user_repo.find_all(firm_id=firm_id)}
    except Exception:
        users_by_id = {}
    try:
        clients_by_id = {c["id"]: c for c in client_repo.find_all(firm_id=firm_id)}
    except Exception:
        clients_by_id = {}

    rows = build_export_rows(entries, users_by_id, clients_by_id)

    suffix = f"{date_from or 'all'}_{date_to or 'all'}"
    if fmt == "xlsx":
        return (
            rows_to_xlsx(rows),
            f"time-entries-{suffix}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return rows_to_csv(rows), f"time-entries-{suffix}.csv", "text/csv"
