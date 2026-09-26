# GSTN offline utilities, fetched by the owner and extracted 26-09-2026

GSTR-9C, GSTR-8 and the GSTR-4 Annual return have no public API-schema document
the way e-invoice and e-way bill do — the only place GSTN publishes their JSON
shape and validation rules is inside the **offline utility** itself, a
macro-enabled Excel workbook (`.xlsm`) a taxpayer fills in and exports to JSON
for upload to the portal. The macros ARE the specification.

**How this was extracted.** Each `.xlsm` is a zip; inside it,
`xl/vbaProject.bin` is an OLE compound file holding the VBA source in a
proprietary compressed form. `oletools.olevba --decode` (the same tool this
class of file is normally opened with for MALWARE analysis, because a macro
workbook is exactly the shape a malicious document takes) decompresses it back
to plain Basic source. What is committed here is the DECOMPRESSED SOURCE of
the modules that carry statutory content — the JSON field names, the
validation rules, the table-to-field mapping — with the generic
infrastructure every GSTN offline utility ships (a JSON parser/serializer
library, a PDF renderer, a SHA-256 implementation, a signing helper, a
suspicious-macro scanner's own output) left out, because none of it says
anything about GSTR-9C, GSTR-8 or GSTR-4 in particular.

**This replaces a claim, not just adds to it.** `THE-PLAN.md`'s 25-09-2026
entry says "the VBA macros behind all three offline utilities were extracted
... and are the primary source a future build should start from" — true of
the description, false of the artefact: nothing from that extraction was ever
written to disk, so the very first thing a future build found was the
original zip files and nothing else. This directory is that extraction, done
again and this time committed, specifically so the sentence is never true a
third time.

| Directory | Source file | Version |
|---|---|---|
| `gstr9c/` | `GSTR_9C_Offline_Utility.xlsm` | (as uploaded) |
| `gstr8/` | `GSTR_8_Offline_Utility.xlsm` | (as uploaded) |
| `gstr4-annual/` | `GSTR_4_Annual_Offline_Utility(v4.2).xlsm` | v4.2 |

## What each module is

**gstr9c/** — `Export_JSON_Module` builds the upload JSON from the sheet
cells (the field names and nesting are the schema); `ValidateMod` and
`Validate_Functions` are the cross-checks the utility runs before it will
export (which cells must foot to which, what a blank means, what triggers a
hard stop vs. a warning); `Common_Module` and `Variable_Initialize` hold the
sheet/row/column constants the other two read positions from.

**gstr8/** — same three-way split: `ExportMod` (JSON shape), `ValidateMod`
(validation), `MainMod` (sheet layout and table structure), plus `ImportMod`
(reads a JSON back in — useful for confirming a field name the export side
states ambiguously) and `CommonUtil`/`ExtraMod` (shared helpers).

**gstr4-annual/** — this bundle is NOT one return. `CMP08Mod` is the
quarterly CMP-08 statement (small: four lines — outward supplies including
exempt, inward supplies attracting reverse charge including import of
services, tax paid, interest paid — each carrying taxable value plus
IGST/CGST/SGST/cess). `B2BMod`, `B2BRCMod`, `InoutsupMod`, `URPMod`, `IMPS`
and `TDSTCSMod` are the ANNUAL GSTR-4's own tables (outward B2B supplies,
inward reverse-charge supplies, inward supplies overall, inward from
unregistered persons, import of services, and TDS/TCS credit received) —
GSTR-4 consolidates the year's four CMP-08 statements and adds detail CMP-08
itself does not carry. `MainMod`/`HomeMod`/`CommonUtil` are sheet plumbing.

## What is NOT settled by reading this

The offline utility specifies the FORM — what JSON GSTN's own tool sends and
what it refuses before sending. It does not specify the RATE: CGST Act s.10's
composition levy is 1% for a manufacturer or trader, 1% for a restaurant/other
food-service supplier under the first proviso (with a further 5% band under
s.10(1) as amended), and 6% for another supplier of services under s.10(2A) up
to the ₹50 lakh limit — and WHICH of those a given registration is a fact
about the dealer's own business, not something the JSON shape states or this
extraction can answer. That has to be recorded, not derived, the same
discipline `vendors.msme_status` and `capital_gains.transferred_asset_nature`
already follow elsewhere in this product — and is `[S]`-graded here (egress to
every `.gov.in` is refused at this environment's proxy), so the rate figures
above are recorded from memory and must be confirmed against Rule 7 / s.10
before they are relied on for money.
