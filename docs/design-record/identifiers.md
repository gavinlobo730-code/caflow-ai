# Design record: Identifiers: GSTIN, UAN, IFSC, party identifiers in imports, the firm's own GSTIN, FY and AY labels, ITR forms

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Identifiers

- **A TALLY IMPORT IS A BULK IMPORT OF AN IDENTIFIER SOMEBODY TYPED, AND IT
  WITHHOLDS RATHER THAN REFUSES.** `validate_migration_data` tested a
  CUSTOMER's GSTIN against a private shape regex, appended a sentence to
  `validation_errors` and left `status` at `validated` — and nothing reads
  `validation_errors`: the preview counts only `failed` items, `execute_import`
  skips only those, and `_import_single_item` wrote the value straight into
  `customers.gstin` over PostgREST, the one door `models/parties.CustomerIn`
  does not stand in front of. The error was recorded and moved nothing. The
  VENDOR branch asked nothing at all, which is the worse half — a wrong GSTIN
  there costs the client the input tax credit — and the PAN was never looked
  at, although `tds_computer.has_pan` reads any non-empty value as a PAN on
  file, so a malformed one suppresses §206AA's floor and §40(a)(ia) disallows
  the WHOLE expenditure for the under-deduction.
  **`domain/tally/party_identifiers.py` is the rule** and asks
  `gstin.problem_with` and `core.validators.validate_pan` — one authority, no
  second pattern (a test forbids a GSTIN-shaped literal in the importer).
  **THE PARTY IS IMPORTED AND THE IDENTIFIER IS NOT, and both halves of that
  are decisions.** Marking the item `failed` would drop a customer whose name,
  address and email are fine AND block the whole export, because the migration
  screen disables its import button on any error count — one typo among two
  thousand legacy customers making a migration impossible for the clients who
  most need one, `opening_documents`' reason for not checking a carried-over
  number against Rule 46(b). And the identifier is WITHHELD rather than
  imported with a warning because the error is not symmetric: an absent GSTIN
  makes the party B2C and their credit waits until somebody records the real
  number, while a well-formed WRONG one declares a stranger's registration on
  every invoice and is undone only by a §37(3) amendment inside a window.
  **The rule is asked TWICE** — at validation for the sentences the preview
  names, at the INSERT for the value — so `tally_data` keeps what the export
  actually said and the CA has something to re-key from; the same discipline
  `fx_revaluation`'s `plan()` and `revalue()` share. The withheld list is
  served WHOLE while `by_type` is sliced to ten, because one is a sample and
  the other is a list of actions. A Tally LEDGER carries no state field, so the
  GSTIN-vs-state agreement the four party models make is deliberately not
  attempted here — only the GSTIN's own first two characters, which
  `problem_with` already tests.
  ⚠️ **THE TWO INSERTS ARE NOT COLLAPSED AND THEIR PAYLOAD IS NOT BOUND TO A
  NAME**, and that cost a CI cycle to learn. The note on
  `domain/firm/identity`'s projections says a `.select()` reached through a
  name is invisible to `tests/test_backend_columns_exist_pg`; the same scan
  counts **a table reached through a variable** (`sb.table(table)`) and **an
  insert whose payload is a name** (`insert(party)`) as unreadable too, and
  its budget is EXACT with no headroom. Tidying the customer and vendor
  branches into one `sb.table(table)` took the count from 459 to 460; binding
  the shared dict instead took it to 461. Either way these two writes stop
  being schema-checked at all, which is the opposite of what a door handling
  identifiers wants. Seven duplicated keys is the price, and it is the right
  one. **Raising the budget would have been the wrong fix** — the guard's own
  message invites it, and here it would buy an exemption where the coverage
  was recoverable.

- **THE FIRM'S OWN GSTIN LIVES IN TWO COLUMNS AND ONLY ONE IS READ.**
  `public.firms` carries `gst_number` (migration 003) AND `gstin` (014, given
  its CHECK by 112/316), nothing has ever synced them, and the two sides of the
  product picked different ones: BOTH screens that edit the firm profile wrote
  `gst_number` **straight over PostgREST** — Settings and the onboarding
  wizard's UPDATE step — while every backend reader read `gstin`. So a CA who
  typed their GSTIN into Settings got a fee invoice with **no supplier GSTIN**
  on it (CGST Rule 46(a)) and, because `_state_code(None)` is None, the whole
  tax on a LOCAL supply landed in **IGST** instead of splitting CGST+SGST.
  `POST /api/onboarding/firm` has always written `gstin` correctly; it is only
  the screens' own update path that did not, so which route a firm came in
  through decided whether its own GSTIN was readable at all.
  **Measured before acting, because the severity turns on it**: on 17-09-2026
  production held 2 firms with BOTH columns NULL — latent, and live the moment
  anybody typed one in. The `capital_wip` shape: built, reachable, structurally
  nil.
  `domain/firm/identity.py` is the authority: **`gstin` is the column,
  `gst_number` is READ as a fallback and never written**, and `gstin_of` is the
  only reader. One writer, `PATCH /api/firms/profile` (Partner-only), which is
  also where the **CHECK DIGIT** is tested — `firms_gstin_format` is a shape
  regex and accepts a transposition, and that GSTIN goes on every fee invoice
  the practice raises with nothing downstream to re-check it. Writing BOTH
  columns was rejected: it would make `gst_number` a cache with two writers,
  the shape this file records going wrong on `clients.gstin` and on the retired
  supplier table. **A narrow `select()` that names one column and not the other
  makes the fallback a silent no-op** — `routers/practice.py` did exactly that
  — so every read names BOTH, the same trap
  `domain/accounting/opening_documents` records for `is_opening`.
  **AND EACH OF THE THREE PROJECTIONS IS WRITTEN OUT AT ITS CALL SITE rather
  than shared through `identity.COLUMNS`**, which reads like the thing to
  factor out and is not: `tests/test_backend_columns_exist_pg.py` checks every
  `.select()` in `apps/api` against the real schema AS A STRING, and a
  projection reached through a name — a `", ".join(...)`, a module constant —
  is invisible to it; so is the guard written for this very feature, which
  passed having looked at NOTHING until the three became literals. That guard
  reads the **AST** now, not a regex, because the literal these fifteen columns
  produce spans three adjacent strings and a regex sees only the first — it was
  vacuous twice, for two different reasons, and carries a floor saying how many
  projections it must find.
  **Migration 399 back-fills `gstin` from `gst_number`** where the first is
  empty and comments both columns, so the fallback is inert for every existing
  row. It deliberately does NOT drop `gst_number` (that moves both sides of the
  production-fixture comparison at once and needs the refresh in
  `docs/schema-drift.md` — migration 371's decision about
  `public.tds_section_limits`), does not `SET NOT NULL`, and **leaves a row
  whose `gstin` is malformed but not empty alone**: `firms_gstin_format` is NOT
  VALID, so such a row can exist, and preferring the superseded column over a
  value somebody recorded in the canonical one would be a guess about the
  firm's own legal identity. ⚠️ The shape carries over; the CHECK DIGIT does
  not, and the migration says so.

- **THE SEVEN ITR FORMS ARE `domain/income_tax/itr_json.ITR_FORMS`, derived
  from the `ITRForm` Literal the field mappings and the committed Department
  schemas are keyed on** (IT-23). The filing screen held its own list of four
  and `itr_workflow`'s docstring agreed with it, so a SALARIED client
  (ITR-1/ITR-2) or a PRESUMPTIVE one (ITR-4) could not have a filing record
  created at all — most of a practice's ITR volume — while verified paths and
  a schema for all seven sat unused. `itr_workflow.validated_form` is the one
  place that decides (canonicalising as it goes, because the value is stored
  and then filtered on), `GET /api/itr/forms` serves the list, and
  `apps/web/.../tax/filing/page.tsx` keeps a fallback array for the redeploy
  window only — the Schedule III caption shape. A test forbids a third copy.
  **`record_filing_acknowledgement` is part of the state machine**: it wrote
  `status = "filed"` with no read of the current status, so a draft could be
  marked filed past the review and partner review the tax screen promises are
  mandatory. The permitted states are derived from `_TRANSITIONS`, and an
  already-filed return is REFUSED rather than silently re-acknowledged — the
  acknowledgement number is a fact about what the portal did. The §139(5)
  revised and §139(8A) updated return are built since (migration 381,
  `domain/income_tax/return_type.py`, `GET /api/itr/return-kinds`): see the
  IT-23 return-kinds bullet above.

- **A REQUIRED YEAR PARAMETER IS DECLARED WITH NO DEFAULT, AND `= ...` IS NOT A WAY TO SAY REQUIRED** (19-10-2026). `Annotated[FYLabel, Query()] = ...` was the spelling the FY-label rule gave for "argument order needs a default", and 26 routes used it (statement analysis, GSTR-4 annual, GSTR-9 and 9C, Rule 37A, regime election, advance tax, self-assessment, the 24Q payroll sources, the bonus register, the TDS projection, ITC-04 and the portal report share). Under FastAPI 0.109.2, which the lock pins, the parameter is published as `required: false`, the year validator never runs on an absent value, and the handler is called with the literal `Ellipsis`: `'ellipsis' object has no attribute 'split'`, "Internal server error" and an error report, instead of a 422. The Form variant on the report-share route would have put the workbook into storage before its insert failed on the same object. Found by running the demo seeder over a migrated database and calling every read route for a seeded client (`walk/sweep.py`, not committed); every test passed the year, so none could see it. All 26 are now keyword-only with no default (a `*,` before the first of them where an earlier parameter has one; where none precedes it, simply no default), and the rule is held over the route table the app serves, not over a list of spellings: no routed parameter defaults to `...` unless it is a Pydantic body model (FastAPI does read `body: Model = ...` as required, proven in the same file), every parameter typed as a required year label is `required: true` in the published OpenAPI document whether it is a query string or a form field, and leaving the year out of each of them is a 422 that names it (`tests/test_a_required_parameter_is_required.py`; against the previous routers 28 of its 49 tests fail). This was also breakage 1 of 2 in the held-back fastapi 0.141.1 bump (POST-A-171): that line of the CI bullet is amended and not re-measured.

- **A DATE ON A REQUEST MODEL IS A TYPE, THE WAY A FINANCIAL-YEAR LABEL IS, AND THE FIELDS NOT YET CONVERTED ARE A LIST THAT ONLY SHRINKS** (POST-A-380, 13-11-2026; no migration). Twenty request-model fields that carry the date of a document the books are made from were a bare `str` or `Optional[str]` with no validator: the date of a sales invoice, a purchase bill, a receipt, a vendor payment, a credit note, a debit note, a purchase credit note, a sales debit note, a journal reversal and an e-invoice, with the due dates and the edit models beside them. Each reaches the period check, `fy_code` (which numbers the document in a financial year), a date parser or a DATE column, so a caller that was not the screen (a script, an import, a hand-made request) that sent a blank or `2026-02-30` got a 500 with no sentence (the vendor payment's blank date raised in the period check before the route's own `try`), and a text with something after the day was read by its first ten characters. `models/iso_date` now holds the date as a TYPE in the shape of `models/fy.FYLabel`, in three because a date is asked three ways: `IsoDate` (must be there; a blank is refused), `OptionalIsoDate` (a new document may leave it out; a blank is no date, which is what the credit terms and the near-duplicate probe already treated it as) and `PatchIsoDate` (an edit may leave it out; absent keeps the stored one, and a BLANK IS REFUSED, because the route reads an edit without what was not sent and would drop a blank as "nothing to change" and report a success for a date that was not cleared). All three accept a `str` only (a before-validator runs AHEAD of Pydantic's own `str` check and `a_real_date` takes `str(value)`, so without that an integer such as 20261101 would be read as the compact date; at a plain `str` field Pydantic already refused a number), keep the canonical `YYYY-MM-DD` (a padded or compact `20261101` is stored as the day), and name the field in the sentence. **What none of them judges is whether the day may be in the future, before a period or outside a year**: that is the door's own rule (the period lock, `clean_filed_date`), asked after this, and no statutory reading is assumed. **A text with a time after the day is now a 422 at these 20 doors**; no screen sends one (the web editors send `<input type="date">` values and the recurring, late-interest and billing builders pass `isoformat()`), and the two bulk importers build the model per row, so a bad row is that row's sentence and not the batch's (without Pydantic's own "Value error, " label in front of it: `core.exceptions.validation_sentence`, which the web importers' digit-shape check makes reachable for `2026-02-30`). **The rule over the whole API is a test and a list that only shrinks**: `tests/test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list.py` reads every Pydantic model it can resolve (a `BaseModel` subclass, also under an alias such as `from pydantic import BaseModel as _BaseModel`, or a subclass of one in the same module or imported from `models`, `routers` or `services`; a dataclass in `domain/` and a class named `...Out`, `...Response` or `...Record` are not request models; the annotation is read in its common spellings, and the NAME rule is a heuristic that does not match a date called `valid_from` or `dob`) and fails a field named like a date (`..._date`, `..._on`, `..._dt`, `date_...`, `as_at`, `valid_until`, `effective_from`, ...) that is annotated `str` or `Optional[str]`, named by no `field_validator` (the decorator or the `x = field_validator("f")(fn)` form: the first scan missed the second and counted two journal fields that were already judged) and not on `tests/fixtures/bare_date_fields.txt`, and fails a line on the list that no longer names a bare field, so a fixed entry cannot be put back unseen. The list holds the other 105 after the second slice (13-11-2026: a quotation's date and validity, a sales order's three dates, a purchase order's two and a goods receipt's four, on the create and the edit models, 21 fields; the services drop a `None` on an edit, so `PatchIsoDate` is the right kind, and a blank on a create reached a DATE column), including the near-duplicate probe's bill date, which stays bare ON PURPOSE (a read-only advisory probe that never refuses: an unreadable date still gives advice by number and amount), and (the rest being the recurring journals, the relationships, the DSC, compliance and engagement records, the fixed-asset and opening-document rows, the opening-balance dates on the masters and so on), each to be read against its callers before it is narrowed: some hold a due-date phrase and some are judged row by row by a bulk import, which is why they are a list and not a sweep. One door the types cannot see is closed by hand: `POST /api/purchase-bills/from-document` carries the bill date inside a free `extracted_data` dict, so its handler now judges `invoice_date` (a reading is a proposal: a 422 with the sentence, and not a bill dated `soon`; it has no web caller). **Dates carried inside other free dict bodies are outside both the types and the list, and the scan cannot find them.** Against the previous models 40 of the new tests fail, and against the previous `from-document` handler 4 of its 5 do (the fifth is the real date getting past the date check). `POST-A-094` (`core.ist_clock._as_ist_date` reads a timestamp string as its UTC date) stays open: its prerequisite named these document doors and they are now closed, but the same hazard stands at the doors still on the list, so the string reading is not changed here. **The same rule in a query string (the third slice, 13-11-2026).** A day named in a query string reached the date parser or a comparison of text at nine doors. Four handed it to the parser, so `?as_of=soon` was a 500 with no sentence for a script: the recurring purchase bills' manual runs (`/run`, `/{id}/run`) and the recurring journals' (`/run`, `/{id}/generate`, whose day is `occurrence`). The fee billing's two (`/api/billing/preview-run` and `/run`) never reached a parser: the service compared the raw text with each schedule's stored day, so text that sorts after a digit (`soon`, `30/09/2026`) made EVERY schedule due and `/run` drafted invoices for schedules not due for months, with a 200, which is worse than a 500. The late-interest preview carried a shape-only `pattern`, which admits `2026-02-30`, and answered 500. The screens send a real day or nothing, so no screen met any of it. `core/query_day.query_day` is the one rule beside the models' (nothing or a blank is no day, so the service's own default applies: today for the runs and previews, and for the journal's one occurrence the template's own next day; a real day reaches the service in its canonical form; anything else is a 422 naming the parameter). **A day with a time after it (`2026-07-01T10:00:00`), which the recurrence reader and the billing comparison used to take by its first ten characters, is now refused too**, as the recurring invoices' pair already did; nothing in the repository sends one. A door that acts on a template asks the caller's access to it FIRST, and a door that takes a `client_id` asks access to that client first, so a template or client that is not theirs is a 404 before any day is judged (held for the recurring invoices by `tests/test_recurring_client_scope.py`, and for the purchase bills, the journals and the late-interest preview by the new door tests). The recurring invoices' pair, which had a private copy of those few lines, now calls it. **The rule over every route is a test and a second list that only shrinks**: `tests/test_a_date_in_a_query_string_is_a_real_day_or_is_on_the_frozen_list.py` reads every route's query parameters (a parameter not named in the route's path and not a `Body`, `Form`, `File`, `Header`, `Cookie`, `Depends` or `Path`, with or without `Query(...)`: a first version read only the ones spelled `Query(...)` and could not see seven) and fails one named like a day that is annotated as a bare string and is not passed to `query_day`, `a_real_date` or `real_day_problem` (directly, by `value=`, through a module-level helper that does so, or as one element of a literal tuple the handler loops over and judges), unless it is on `tests/fixtures/bare_date_query_params.txt` (87 left). **A `pattern=` alone is not judging, and a helper is judged by what it does, not by its name**: both were accepted at first and the late-interest preview passed as judged while answering 500. A day type (`IsoDate` and its two kinds) is accepted only as `Annotated[<type>, Query(...)]`, because `x: OptionalIsoDate = Query(None)` makes FastAPI discard its validator, and that spelling fails. A listed line that no longer names an unjudged parameter fails too, so a fixed entry cannot be put back unseen. The list is mostly filters and report windows, where a malformed day answers an empty list or the handler's own sentence, and a few inputs to a calculation or a delete; each is read against its callers before it is narrowed, so a window that is blank on purpose must not become a 422 by a sweep. The order in which a handler judges is not read by the scan, and the name rule is a heuristic (`since` and `fy_start` are not matched). No statutory reading is assumed: whether a run may be for a future day is the service's own rule, asked after this. **The request half finished (14-11-2026; no migration).** 91 more fields in 28 files carry the type, and the list holds 12. Which of the three kinds a field takes was read off the door it reaches, not off its name: a field the request must carry is `IsoDate`; a field a new record may leave out, a field a renewal may leave out (a DSC renewal's issue date, an engagement renewal's date) and an edit field whose null CLEARS the stored value (a fixed asset's put-to-use date, a DSC's issue and expiry dates, a recurring journal template's end date: their routes write what was sent, so a blank must stay "no date") is `OptionalIsoDate`; an edit field the route drops when it is null (`exclude_none` or an `is not None` filter: the masters' opening-balance dates, an employee's birth and joining dates, a bill of entry's date, a compliance record's three dates, an engagement's, a lead's, a relationship entity's, a recurring task's and a TDS deduction's dates and the rest) is `PatchIsoDate`, because a blank there reached the DATE column as `''` and failed in the database. **Every column the edit fields write was checked in production to be a DATE column**, so a blank there was already refused, by the database and without a sentence; it is now a 422 naming the field. On a create, a blank optional date is now no date rather than `''`. What is newly refused everywhere is text that is not a real `YYYY-MM-DD` day, and that matters more than a 500: **the production database's `DateStyle` is `ISO, MDY`, so `'01/02/2026'::date` is 2 January** (read there on 14-11-2026), and a script or import that sent an Indian slash date to one of these fields had the wrong day stored with no error. No screen sends one (the date boxes send `<input type="date">` values), and the one door shaped for a script, the parsed-rows bank statement import (`POST /api/banking/statements/import`), has no screen caller. The 12 left are bare ON PURPOSE, each with its reason in a `#:` comment at the field, and the first full run of the suite is what found four of them: a door that judges the date by its own rule in its own sentence (a GST return's filed date, which `_filed_date_or_refusal` judges against the return's period ONLY when the status files it, so a date sent with a status that files nothing is not judged, as a test pins; an MCA filing's date, refused by `_judged_filing_date` with "Nothing was changed."; a notice reading's two dates, judged by `extraction_schemas.correct_notice`, where a blank clears; the §80EE/80EEA sanction date, where an unreadable date is read as not given and allows NOTHING, the direction that cannot over-deduct), a date read as a spreadsheet cell, day first (a ledger import leg, the opening documents' and the opening register's rows, read row by row so a bad date is that row's numbered error, and the opening register's as-at day, which `opening_register.position_problem` reads and words for the whole file, a blank and `31-03-2026` included), and the near-duplicate probe. Three tests that built a model with a malformed date and expected the route to refuse it (a DSC's expiry, a settlement's leaving date, a salary revision's effective date) now assert the model's refusal: over HTTP it is the same 422, naming the field, and the route is never reached. Two unused query models in the invoices router (`InvoiceListQuery`, `GenerateFromTimeQuery`) were deleted rather than typed: nothing read either. **Not done here**: the 87 query parameters on `tests/fixtures/bare_date_query_params.txt`, and `POST-A-094`, which waits for them.
