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
