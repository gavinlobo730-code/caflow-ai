# Can a CA run a client with foreign suppliers on this?

A second walkthrough, covering the surface the first one never touched. The
walkthrough of 1 September drove one client through a financial year and found
nine things; it had no non-resident vendors in it at all, and everything built
since — Form 27Q routing, the §195 rate table, the treaty table — arrived
afterwards. That code has unit tests and negative controls. It had never been
run against a database.

## How this was run

The same harness as the first walkthrough: the real FastAPI app, a real
PostgREST 12.2.3, and a real Postgres 16 with all 304 migrations applied. The
only thing replaced is identity — there is no GoTrue here, so
`get_current_user` is overridden with a Partner of the harness firm. Everything
downstream of that is untouched: `rbac()` still runs, every router and service
is real, and the posting kernel writes real journal entries.

Nothing here touched production.

**The client.** Meridian Software Labs Pvt Ltd, Bengaluru, paying four
overseas suppliers chosen so that between them they exercise every branch §195
has, plus one domestic supplier as the control:

| Supplier | Country | What it exercises |
|---|---|---|
| Helvetica Design AG | CH | royalty, TRC + Form 10F on file — the treaty path |
| Gulf Hosting FZE | AE | ordinary services, no PE — chargeability, nil |
| Beacon Analytics LLC | US | FTS, **no PAN**, no TRC — Act rate and the §206AA floor |
| Lion City Data Pte Ltd | SG | FTS where the treaty has **no article** — Article 7, nil |
| Pinnacle Engineering Services | IN | §194C, 2% — the control that must not change |

## What worked

**Every §195 branch computed correctly, through the real stack.**

| Bill | Base | Withheld | Reading |
|---|---|---|---|
| Helvetica, ₹5,00,000 royalty | 10% treaty | **₹52,000** | ₹50,000 + 4% cess ₹2,000 |
| Gulf Hosting, ₹2,00,000 hosting | — | **nil** | not chargeable, no PE |
| Beacon, ₹8,00,000 FTS | 20% | **₹1,66,400** | ₹1,60,000 + cess ₹6,400 |
| Lion City, ₹3,00,000 FTS | — | **nil** | treaty has no FTS article |
| Pinnacle, ₹5,00,000 job work | 2% | **₹10,000** | §194C, no surcharge, no cess |

The domestic control is untouched — 2%, no surcharge, no cess — which is the
thing that had to stay true while a whole second charging regime was added
beside it.

**The refusals fire, and they say what to do.** Booking the Swiss bill before
anyone had read the India–Switzerland agreement returned a 422 naming §90(2),
saying the software holds no treaty rates, and telling the CA to read the
article and record it. Recording `CH / royalty / 10% / Article 12(2)` in
Settings → DTAA Treaty Rates and retrying booked it at 10%. The same happened
for Singapore, where the answer recorded was "no article" and the bill then
withheld nil.

**27Q assembles.** Three 27Q rows carrying country, TIN, nature of payment and
the cess split; one 26Q row for the domestic vendor. `?return_type=27Q` returns
₹2,70,400 across three rows and `?return_type=26Q` returns ₹10,000 across one.

**26Q stops swallowing them.** `POST /api/tds/26q/from-books` for Q1 returned
**zero** deductees and an `excluded_non_resident` block naming all three bills,
₹2,70,400, with the reason: *"Payments to a non-resident are reported on Form
27Q under Rule 31A(4)(b), not on 26Q."*

**The calendar generates 27Q.** With a TDS engagement on the client, obligation
generation produced four `TDS26Q` and four `TDS27Q` rows — the 27Q ones only
because this client has vendors recorded as non-resident.

**The onboarding signposting from the first walkthrough works.** The first bill
failed with *"Product/Service is required on every line item. Pick one with
'+ Add Product/Service' on the line… a new client has an empty catalogue until
somebody adds to it"*, and the chart-of-accounts error said *"Please set up
Chart of Accounts before posting."* Both told me exactly what to do next. That
is fix 4 of the previous walkthrough doing its job.

## The findings

### 1. A nil-withheld foreign remittance leaves no trace anywhere — HIGH

`tds_register_service.sync_for_bill` writes a row only when
`status in IN_THE_BOOKS and deducted > 0`. The Dubai and Singapore bills
withheld nil, so **neither has a register row**.

Those are the two remittances a department is most likely to ask about. Both
rest on a claim — that the payment is not chargeable in India because the payee
has no permanent establishment — and the register that 27Q is assembled from
has no record that the payment happened at all.

It also disables the two controls built for exactly this: the missing-Form-15CA
gap and the undated-no-PE-declaration gap are computed inside `sync_for_bill`,
after the early return, so on a nil remittance they can never fire. Rule 37BB
requires Form 15CA for a remittance whether or not tax was deducted (Part D
exists for non-taxable ones).

### 2. The statutory gaps are computed and thrown away — HIGH

`sync_for_bill` returns `statutory_gaps` naming five conditions: residency not
classified, 27Q identifiers missing, §195 rates never confirmed against the
Finance Act, an undated no-PE declaration, and no Form 15CA recorded.

`routers/purchase_bills._sync_tds_register` is declared `-> None` and discards
the return value. Nothing else reads it. Grepping the backend, the only
occurrence of `statutory_gaps` outside payroll is the line that sets it.

Payroll's equivalent reaches the caller —
`api_response(True, {**run, "statutory_gaps": statutory_gaps})`. The TDS one
does not, so all five codes are dead on arrival. **This is a gap in work
completed earlier in this session, not pre-existing.**

### 3. The single bill-create path has no duplicate guard — MEDIUM

The bulk import checks `(client_id, vendor_id, bill_no)` before inserting.
The ordinary create path does not, and there is no unique index behind it —
`purchase_bills` has only its primary key.

The walkthrough booked HEL/04 twice, and got two bills, two posted journals and
**two 27Q rows for one supplier invoice**: ₹1,04,000 withheld where ₹52,000 was
due. Nothing warned. For a foreign remittance this compounds — a duplicated
27Q row is a duplicated deductee entry in a filed return.

### 4. A database CHECK violation reaches the CA as "Internal server error" — MEDIUM

Creating an engagement with `billing_cycle: "annual"` (the constraint wants
`"Annually"`) returned `{"success": false, "error": "Internal server error"}`.
The real message — `fee_engagements_billing_cycle_check` — went only to the
log.

This is the same class the previous walkthrough found on the money-document
paths, fixed there by `core.exceptions.document_failure_detail`. Five routers
use it: accounting, purchase_bills, purchase_payments, receipts, tds.
`engagements.py` is not among them, and neither is most of the rest of the
router layer.

### 5. `financial_year` on obligation generation is a Query param — LOW

`POST /api/compliance/obligations/generate` takes `client_id` and
`financial_year` as query parameters. Sending them in the JSON body — the
obvious thing to try, and what every neighbouring endpoint accepts — is
silently ignored and the current FY is used instead. The walkthrough asked for
2025-26 four times and generated 2026-27 without a word.

## One finding retracted

The first pass recorded a HIGH finding that a TRC vendor could be booked with
no treaty rate recorded. That was wrong: an earlier aborted run of the same
script had already written the `CH / royalty` row, so the retry found it. On a
clean slate — with the row deleted — the refusal fires correctly. Recorded here
because a walkthrough that only reports what it wants to find is not evidence.

## So: could a CA run a foreign-paying client on this?

The tax is computed correctly and the returns separate correctly. What is
missing is the paper trail around the two answers that are *nil*, and the
plumbing that would show a CA the gaps the software already knows about.

Findings 1 and 2 are the same shape as the phantom-journal finding from the
first walkthrough: the software knows something is wrong and tells nobody.
Finding 2 is worse in one respect — the reporting was built, and then not
connected.

## What to do next, in order

1. **Write a register row for a nil-withheld foreign remittance** (finding 1) —
   with the reason for non-deduction, which 27Q asks for anyway. This also
   turns findings 1 and 2's controls back on.
2. **Surface `statutory_gaps`** (finding 2) on the receive response and
   wherever a CA reviews a quarter, the way payroll does.
3. **Guard the single create path against a duplicate bill** (finding 3).
4. **Extend `document_failure_detail` to the rest of the router layer**
   (finding 4).
5. Accept the query/body inconsistency (finding 5) or make the endpoint take
   a body.

## What has been fixed since

Worked through in the order above. Each fix carries negative controls — the
count is how many of its new tests fail against the code as it was.

**1 and 2 — the nil remittance and the discarded gaps** (`883968a3`).
`tds_register_service` now writes a register row whenever a bill is on the
books and either tax was deducted or §195 was the section in play, carrying
`non_deduction_reason`. That is the field 27Q asks for anyway, and writing it
also turns the missing-15CA and undated-declaration controls back on, since
both are computed after the early return that used to skip a nil remittance.
`_sync_tds_register` is now `-> dict` and the receive response carries
`tds_register`, including `{"synced": False, "reason": ...}` when the sync
itself failed — which is how the stale-schema-cache case surfaced while this
was being verified, instead of vanishing. `describe_gaps` turns the five codes
into sentences. Migration 312. Three negative controls.

**3 — the duplicate bill** (this commit). Migration 313 adds a unique partial
index on `(client_id, vendor_id, lower(btrim(bill_no)))`, excluding cancelled
and soft-deleted bills and bills with no number, and all three insert paths
check first so a CA gets a sentence rather than a constraint name. The bulk
path's existing guard now ignores cancelled bills too — without that it
refused the *correction* after a cancellation. Production was checked for
existing duplicates before writing the index: there are none, so it cannot
fail on merge. Four negative controls; 21 new tests.

**4 — "Internal server error"** (this commit). Rather than adding
`document_failure_detail` to ninety-odd routers one at a time, `main.py`'s two
catch-alls now classify by SQLSTATE through `core.exceptions.unhandled_failure`:
a CHECK, foreign-key, not-null or `RAISE EXCEPTION` refusal becomes a 400 (409
for a duplicate) carrying the database's own sentence, a permission or
missing-table fault stays a 500 but says which kind and does not invite a
retry, and everything else — a `KeyError`, a timeout, a bug — still gets
"Internal server error", which for those is the honest answer. The engagement
case from finding 4 now reads
`fee_engagements_billing_cycle_check` instead. Four negative controls.

**5 — the ignored `financial_year`** (this commit). The endpoint now accepts
both a query parameter and a JSON body, refuses rather than choosing when the
two disagree, and validates the label: `normalise_fy_label` in
`core/ist_clock.py` accepts `YYYY-YY` and `YYYY-YYYY`, canonicalises, and
refuses a second half that does not follow the first. That last part is the
one a shape regex cannot catch — `2026-28` passed `^\d{4}-\d{2}$` and
generated FY 2026-27's due dates under a label naming no year at all. Four
negative controls.

**What the finding-5 sweep found — and how much bigger it was.** The first
pass grepped for `Query(` and reported eleven unvalidated financial-year
parameters. That was an undercount by a factor of five: an AST scan of every
route function and request model found **56** places a financial-year label
enters the API, because labels arrive in request BODIES too, and only one was
validated. Twelve of the 56 sat on statutory paths — Form 24Q's deductee rows,
the §234C estimator, GSTR-9, the Schedule III ratios and trend, the year-end
engagement — where a label that parses to the wrong year produces the wrong
return rather than an empty list.

The sweep was done rather than deferred, and not by editing 56 sites to the
same rule by hand, which is how one gets missed. `models/fy.py` holds one
validated type — `FYLabel` / `OptionalFYLabel` — every entry point is annotated
with it, and `tests/test_fy_labels_are_validated.py` fails if a new
financial-year parameter goes in as a bare `str`.

Two things worth recording because neither was visible from reading the code:

* **`fy: FYLabel = Query(...)` validates nothing.** FastAPI builds the field
  from `Query()` when it sits in the default position and DISCARDS the
  Annotated metadata carrying the validator. No error, no warning; the
  endpoint reads as guarded and is not. Six parameters would have shipped that
  way. It was caught by probing the behaviour before converting anything, and
  the ratchet test would have passed either way — so it has its own test,
  `test_query_never_sits_in_the_default_position`. The working form is
  `Annotated[FYLabel, Query(...)]`. Pydantic's own `Field()` in the default
  position does NOT have this problem, which is exactly what makes it easy to
  assume `Query()` behaves the same.
* **Every financial-year value on production is already canonical.** All 38
  such columns across 38 tables were checked before the type was written to
  canonicalise as well as validate — `2026-2027` in, `2026-27` stored. Had any
  row held a non-canonical label, normalising on the read side would have
  stopped matching it.

## What this walkthrough did not cover

Paying the foreign supplier and the challan under Rule 30, the 27Q return
document itself (there is no 27Q assembler — only the register it would read),
Form 15CB's UDIN path, and everything the first walkthrough also left out:
bank import, GST assembly, fixed assets, year-end and ITR.
