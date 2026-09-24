"""What a report shared to a client's portal is, and what may be shared.

── THE DEFECT THIS EXISTS FOR ───────────────────────────────────────────────
`shareToPortal` on the client accounting screen built the workbook, uploaded it
to Supabase Storage **from the browser**, and inserted into `shared_reports`
over PostgREST. So `rbac()` ran on neither half, and what it publishes is a
client's Profit & Loss, Balance Sheet or Trial Balance to that client's own
portal. RLS was the only control on either write.

This module decides; it reads nothing and writes nothing. The service uploads
and inserts, and the router hands it the request.

── THE VOCABULARY IS THE COLUMN'S ───────────────────────────────────────────
`shared_reports.report_type` is CHECKed (migration 032, widened by 412), and the
screen's own ids are not those values. Keeping the map here rather than in the
browser is what stops a fourth report being added with a type the database
refuses — which is exactly what happened to the Trial Balance, whose button had
never once worked because "trial" fell through a conditional that translated
only "bs".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: The screen's id for each report, and what the table calls it. A TOTAL map:
#: a report that is offered and not named here is refused rather than written
#: through as its own screen id.
REPORT_TYPES: dict[str, str] = {
    "pl": "pl",
    "bs": "balance_sheet",
    "trial": "trial_balance",
}

#: Everything the CHECK admits. The three above are what this screen shares;
#: the other two are written by nothing yet and are listed so a caller can be
#: told what the column would take rather than only what this screen offers.
ALLOWED_REPORT_TYPES = frozenset(
    set(REPORT_TYPES.values()) | {"gst_summary", "tds_summary"}
)

#: The storage bucket. Named once so the browser's path and the server's cannot
#: drift — the portal reads the row's `storage_path` and signs a URL for it, so
#: a mismatch is a share that uploads and then cannot be opened.
BUCKET = "Documents"

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: 10 MB. A Schedule III statement is tens of kilobytes; anything near this is
#: not one of these reports, and an unbounded upload from a browser is how a
#: storage bucket becomes somebody else's disk.
MAX_BYTES = 10 * 1024 * 1024


class ShareRefused(ValueError):
    """The share is refused, with a sentence the screen can render."""


@dataclass(frozen=True)
class SharePlan:
    """Everything the service needs, decided and validated."""
    report_type: str
    storage_path: str
    file_name: str
    content_type: str


def plan_share(
    *,
    client_id: str,
    screen_report_id: str,
    file_name: str,
    content_type: str | None,
    size_bytes: int,
) -> SharePlan:
    """Decide what would be written, or refuse and say why."""
    report_type = REPORT_TYPES.get((screen_report_id or "").strip().lower())
    if report_type is None:
        raise ShareRefused(
            f"{screen_report_id!r} is not a report this screen shares. "
            f"Known: {', '.join(sorted(REPORT_TYPES))}."
        )
    # Belt and braces: the map above is the vocabulary, and this is the column's.
    # If the two ever disagree the write would fail at the database with a
    # constraint error, which is the one place a CA cannot act on it.
    if report_type not in ALLOWED_REPORT_TYPES:
        raise ShareRefused(
            f"{report_type!r} is not a value shared_reports.report_type accepts"
        )

    if not client_id or not _UUID.fullmatch(client_id):
        raise ShareRefused("a client must be named, by id")

    if size_bytes <= 0:
        raise ShareRefused("the workbook is empty")
    if size_bytes > MAX_BYTES:
        raise ShareRefused(
            f"the workbook is {size_bytes // 1024} KB; the limit is "
            f"{MAX_BYTES // (1024 * 1024)} MB"
        )
    if content_type and content_type != _XLSX:
        raise ShareRefused("only an .xlsx workbook can be shared to the portal")

    safe = _safe_name(file_name)
    return SharePlan(
        report_type=report_type,
        # THE CLIENT ID IS IN THE PATH and the file name is sanitised, because a
        # path is assembled from a caller-supplied string: without both, a name
        # carrying `../` writes outside the client's own folder, and the portal
        # decides what a client may open by exactly this prefix.
        storage_path=f"shared_reports/{client_id}/{safe}",
        file_name=safe,
        content_type=_XLSX,
    )


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(name: str) -> str:
    """A file name with no path in it.

    Deliberately a whitelist rather than a blacklist of `..` and `/`: a
    blacklist has to anticipate every encoding of a separator, and this only has
    to keep the characters a report name actually needs.
    """
    base = (name or "report.xlsx").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = _UNSAFE.sub("-", base).lstrip(".") or "report.xlsx"
    if not cleaned.lower().endswith(".xlsx"):
        cleaned += ".xlsx"
    return cleaned[-120:]
