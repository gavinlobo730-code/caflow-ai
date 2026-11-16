"""Which accounts of a chart are the GST control accounts, output and input.

ONE ANSWER, MOVED HERE FROM `services/gst_return_service._gl_gst_movements`
(POST-A-090), because a second reader needed it: the nightly books check that
asks whether output tax fell while money received rose. Two readers each
deciding which accounts hold output tax is the drift this codebase keeps
recording, so the rule lives once and both call it.

THE RULE (unchanged from where it was):

  * by `system_account_key` first — `gst_cgst`, `gst_sgst`, `gst_igst` are the
    output heads (migrations 092/098 key them on Liability accounts only) and
    `gst_input` is input credit;
  * and ONLY where the key finds nothing on a side, by the name, kept apart by
    `account_type`: output tax is a Liability named "GST Output…", input credit
    an Asset named "GST Input…". A chart built by `coa_seed_service` carries
    these accounts with the key left NULL (observed on a live firm: `1301 GST
    Input Tax Credit` and `2002 GST Output Tax Payable`, both NULL-keyed), and a
    key-only lookup found none of them, so the return read zero output tax.

Pure: takes the chart rows, reads nothing.
"""
from __future__ import annotations

from typing import Iterable

OUTPUT_KEYS: frozenset[str] = frozenset({"gst_cgst", "gst_sgst", "gst_igst"})
INPUT_KEY = "gst_input"


def output_and_input_ids(coa: Iterable[dict]) -> tuple[set[str], set[str]]:
    """(output-tax account ids, input-credit account ids) of these chart rows."""
    rows = list(coa)
    out_ids = {c["id"] for c in rows if c.get("system_account_key") in OUTPUT_KEYS}
    in_ids = {c["id"] for c in rows if c.get("system_account_key") == INPUT_KEY}
    if not out_ids:
        out_ids = {c["id"] for c in rows
                   if c.get("account_type") == "Liability"
                   and "gst output" in (c.get("account_name") or "").lower()}
    if not in_ids:
        in_ids = {c["id"] for c in rows
                  if c.get("account_type") == "Asset"
                  and "gst input" in (c.get("account_name") or "").lower()}
    return out_ids, in_ids
