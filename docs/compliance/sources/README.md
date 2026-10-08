# Primary sources, fetched by hand

**Every `.gov.in` is refused at this environment's egress proxy** — `curl` to any of
them returns `CONNECT tunnel failed, response 403`, which is the network policy rather
than a block at the government end. So for most of this repository's history, statutory
constants have been written from knowledge and graded `[S]`, with the grade travelling
on every answer that uses them.

This directory is the exception. Everything here was **fetched by a human from the
publisher's own site** and extracted to text. A claim resting on a file in here is
`[P]` — primary — and may be marked `verified=True` in the code, which elsewhere it may
not be.

**That distinction is about PROVENANCE, not confidence.** A `[S]` figure may well be
right; it just has not been read off the document. The point of keeping these files is
that the next reader can check, and that a later correction has something to argue
against.

## What is here, and what it settled

### `e-invoice/` — NIC's Invoice Registration Portal
Fetched **18-09-2026** from `einv-apisandbox.nic.in` (the API developer portal, which
needs no login for these) and `einvoice1.gst.gov.in`.

| File | What it is |
|---|---|
| `generate-irn-api-and-validations.txt` | the Generate IRN API doc, including the **39 system validations** plus the e-commerce, item, calculation-of-values and e-way-bill validations |
| `field-regular-expressions.txt` | the field-level regex for every INV-01 attribute — the authority on decimal precision and on which fields may be negative |
| `notified-schema-to-api-mapping.txt` | Form GST INV-01 as notified, mapped to API attribute paths (`TranDtls.SupTyp` and so on) |
| `eway-bill-schema-to-api-mapping.txt` | how an e-way bill is derived from an IRN request |
| `master-codes-transaction-and-document-types.txt` | `B2B / SEZWP / SEZWOP / EXPWP / EXPWOP / DEXP` and `INV / CRN / DBN` |
| `irp-error-codes.txt` | the IRP's error codes with reason and resolution |
| `sample-signed-invoice-decoded.json` | a **real signed INV-01 payload**, decoded out of the JWT in NIC's published sample |
| `sample-signed-qr-decoded.json` | the signed QR-code payload |

The sample payloads are worth more than they look: they are what the system actually
emits, rather than what a specification says it should.

**Read the validations file before changing anything about e-invoicing.** Several of its
rules are STRICTER than the CGST Rules, and the two must not be collapsed — see
`domain/gst/irp_validations.py` for that separation and why it is load-bearing.

### `gst-offline-utilities/` — GSTN's offline utilities (VBA source)
**Extracted 26-09-2026.** Downloaded by the owner as GSTN's published offline utilities
(macro-enabled `.xlsm` workbooks) on 25-09-2026 or 26-09-2026. **The page the three were
downloaded from and the exact day were not written down**, so neither is stated here
rather than invented; if the owner still has either, add it to this paragraph.

GSTR-9C, GSTR-8 and the annual GSTR-4 have no public API-schema document the way
e-invoice has: the only place GSTN publishes their JSON shape and the checks it runs is
inside the utility, whose macros therefore ARE the specification. Each `.xlsm` was
opened with `oletools.olevba --decode` and the decompressed VBA of the modules that
carry statutory content was committed as text (the generic infrastructure every GSTN
utility ships, a JSON library, a PDF renderer, a SHA-256 and a signing helper, was left
out because it says nothing about these returns). The workbooks themselves are not here.

| Directory | Source file | Version | Modules |
|---|---|---|---|
| `gstr9c/` | `GSTR_9C_Offline_Utility.xlsm` | (as uploaded) | 5 |
| `gstr8/` | `GSTR_8_Offline_Utility.xlsm` | (as uploaded) | 6 |
| `gstr4-annual/` | `GSTR_4_Annual_Offline_Utility(v4.2).xlsm` | v4.2 | 10 (CMP-08's four lines are among them) |

**What it settled, and the grade.** The FORM: JSON field names and nesting, which cells
must foot to which, and what the utility refuses before it will export. A claim about
the form that rests on these files is `[P]`. **It does NOT settle the law or the rates**:
a rate is an Excel cell value the VBA text does not carry (the GSTR-8 rate check is read
as a band from the macros alone), and which composition rate applies to a dealer is a
fact about the dealer. So `domain/gst/composition.py` and `domain/gst/gstr8.py` keep
`VERIFIED = False` and grade their rates `[S]`. The modules are read by
`domain/gst/composition.py`, `gstr8.py`, `gstr4_annual.py` and `gstr9c.py`; the
directory's own `README.md` says what each module is.

**Not here:** any other utility (GSTR-9, GSTR-1, GSTR-3B and the rest): only these three
have been fetched. Nor a later version of the three above. A utility's version moves within a year, so a layout read from `gstr9c/`
may predate the one a CA is using today.

### `gst-notifications/` — CBIC
Fetched **18-09-2026** from `taxinformation.cbic.gov.in`. These settled the §50(3)
interest rate, which this repository had wrong three times; the reasoning is in
`domain/gst/late_filing.py` and in CLAUDE.md.

## How to add to this directory

Extract the PDF to text and commit the text, not the PDF: the text is what is greppable,
diffable and reviewable, and a 147-page Gazette PDF will not upload through most of the
paths a human has to use to get it here. Record **where it came from and on what date**
in the table above. A file with no provenance is worth less than no file, because it
reads as authoritative.
