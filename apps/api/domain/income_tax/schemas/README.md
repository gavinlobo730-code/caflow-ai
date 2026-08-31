# ITR JSON schemas — AY 2026-27

The Income Tax Department's own JSON schemas, downloaded from the e-filing
portal (Downloads → Income Tax Returns → AY 2026-27 → per form → "Schema").

They are committed rather than fetched because `domain/income_tax/itr_json.py`
maps this product's payload keys onto their field names, and that mapping has to
be reviewable against the exact document it was written from. A schema fetched
at build time would let the field names shift under the mapping silently.

## What is here

| File | Schema version | AY | Notes |
|---|---|---|---|
| `ITR1_2026_Main_V1.1.json` | Ver1.0 | 2026-27 | Resident individuals, salary/one house/other sources |
| `ITR2_2026_Main_V1.2.json` | Ver1.0 | 2026-27 | Individuals/HUF without business income |
| `ITR3_2026_Main_V1.1.json` | Ver1.0 | 2026-27 | Individuals/HUF with business or professional income |
| `ITR4_2026_Main_V1.1.json` | Ver1.0 | 2026-27 | Presumptive income — §44AD / §44ADA / §44AE |
| `ITR5_2026_Main_V1.1.json` | Ver1.0 | 2026-27 | Firms, LLPs, AOPs, BOIs |
| `ITR6_2026_Main_V1.0.json` | Ver1.0 | 2026-27 | Companies other than those claiming §11 exemption |
| `ITR7_2026_Main_V0.1.json` | Ver1.0 | 2026-27 | Trusts and institutions. File version V0.1 — a DRAFT |

All seven forms are here.

## Two things the schemas settle

**Amounts are whole rupees, as JSON integers** — not paise, and not decimals.
Every monetary field is `"type": "integer"`. So the paise-to-rupee conversion
belongs exactly where `domain/gst/money.py` already puts the GST one: at the
statutory payload boundary, and nowhere earlier.

**A software provider ID is mandatory.** Every schema requires
`CreationInfo.SWCreatedBy` and `CreationInfo.JSONCreatedBy` to match
`[S][W][0-9]{8}` — an `SW########` number the Department issues to registered
software providers. A file without one is rejected at upload whatever else it
contains. That is a registration step, not a coding one, and it gates real
filing the same way GSP registration gates GST filing (see CLAUDE.md, "Filing to
the government portals through the software"). `CreationInfo.Digest` is
similarly required, as 44 characters or a literal `-`.

## Provenance

Recorded so a future reader can tell whether these are still current — the
portal revises schemas mid-year (ITR-1's page showed a first release of
15-May-2026 and a latest of 30-Jun-2026).

```
ITR1_2026_Main_V1.1.json  sha256:(see git)              148,921 bytes
ITR2_2026_Main_V1.2.json  sha256:(see git)              390,622 bytes
ITR3_2026_Main_V1.1.json  sha256:66f4bd705e0e0788…  1,060,874 bytes
ITR4_2026_Main_V1.1.json  sha256:5e9af50083ad92fa…    252,342 bytes
ITR5_2026_Main_V1.1.json  sha256:3bb5f158f63556c3…  1,027,777 bytes
ITR6_2026_Main_V1.0.json  sha256:15fb24266820944b…  1,260,124 bytes
ITR7_2026_Main_V0.1.json  sha256:481460087c828ab0…    424,421 bytes
```

Do not hand-edit these files. They are the Department's, and a local edit would
make the mapping agree with something the portal will not accept.

## The filing due date the schemas pin

Each schema fixes `ItrFilingDueDate` to a literal, and they do not all agree:

| Form | Pinned due date |
|---|---|
| ITR-1, ITR-2 | `2026-07-31` |
| ITR-4 | `2026-08-31` |
| ITR-3, ITR-5, ITR-6, ITR-7 | not pinned |

31 July is the §139(1) default and is what
`services/compliance_engine.itr_due_date` returns. ITR-4 alone says 31 August.

`compliance_engine` is deliberately NOT changed to match. A pattern in a schema
file is not a CBDT notification, and two of the three forms that pin a date
agree with the statute. If the August date reflects a real extension it should
be recorded as an extension, against the circular that granted it — not adopted
because one JSON file was convenient to read.
