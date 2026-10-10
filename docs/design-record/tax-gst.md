# Design record: GST: returns, e-invoice and e-way, ITC and the 2B reconciliation, late fees, HSN and UQC, registrations

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **A CLIENT IS ONE LEGAL PERSON AND MAY HOLD SEVERAL GSTINs, and until
  migration 390 the return tables forbade it** (GST-20). CGST §25(1) requires
  registration in EVERY State or Union territory a taxable supply is made from,
  and §25(2)'s proviso allows a separate registration per place of business
  within one state — so a depot, a second office, a warehouse-state e-commerce
  registration are all the same legal person with several GSTINs and several
  sets of returns. `clients.gstin` held exactly one, and **both
  `gstr1_returns` and `gstr3b_returns` were `UNIQUE (client_id, period)`**, so a
  second registration could not have had its own June GSTR-1 whatever the code
  did; the CA's only route was a second fake "client" per GSTIN, which then
  splits the ACCOUNTING of one entity across two ledgers and breaks every
  client-scoped report. 390 narrows both keys to `(client_id, period, gstin)`.
  `domain/gst/registrations.py` is the authority.
  **`clients.gstin` IS NOT REPLACED and that is the part to read before
  "tidying" it.** It stays the PRIMARY and remains the only place the primary is
  stored; `client_gst_registrations` holds the ADDITIONAL ones ONLY, and
  `all_registrations` presents the union. The obvious alternative — move every
  registration into the table and leave `clients.gstin` as a cache — was
  rejected because a cache needs ONE write path and that column already has
  several (onboarding, the client edit screen, migration 073's seed), so it
  would drift the first time somebody edited a client and surface as a return
  filed under the wrong registration. **There is deliberately NO backfill**, for
  the same reason.
  **A GSTIN THE CLIENT DOES NOT HOLD IS REFUSED, NEVER DEFAULTED TO THE
  PRIMARY** — in the domain module and again as a 422 in
  `services/client_gst_registration_service.resolve` — because filing one
  registration's return under another's number is the exact failure this
  feature exists to prevent, and it is invisible until the portal rejects it or,
  worse, accepts it. The PRIMARY COMES FIRST in the list for the mirror-image
  reason: a screen opens on `[0]`, and that has to be the registration every
  existing document already carries.
  **The narrowed key made `_existing_return` load-bearing**: a save path still
  matching on (client, period) alone now finds the OTHER registration's return
  and revises it, silently replacing one state's figures with another's, so the
  GSTIN is a required parameter there with no default.
  ⚠️ **THE TWO `gstin` COLUMNS ARE NOT THE SAME SHAPE, and the difference
  decides whether narrowing constrains anything.** `gstr1_returns.gstin` is NOT
  NULL from migration 036; `gstr3b_returns.gstin` is NULLABLE, because 036's
  CREATE TABLE omitted it and **migration 234 added it as a bare `TEXT`** with
  nothing to back-fill from. Postgres treats NULLs as DISTINCT in a unique
  index, so `(client_id, period, gstin)` enforces NOTHING on a row saved
  without one — narrowing the key would have REMOVED what `UNIQUE (client_id,
  period)` gave those rows rather than refining it. 390 closes it twice: it
  **back-fills both tables' NULL gstin from `clients.gstin` BEFORE dropping the
  old constraint** (that constraint guarantees at most one row per (client,
  period), so the update cannot collide — and before 390 a client held exactly
  one registration, so `clients.gstin` IS what such a row was prepared under: a
  repair of 234's omission, not a guess), and keys both indexes on
  **`coalesce(gstin, '')`**, which is a no-op on `gstr1_returns` today and is
  written anyway because these two columns have already drifted apart once.
  **No `SET NOT NULL`**: merging applies this to production with no review step
  in front of it, and one unbackfillable row would abort the deploy and block
  every later migration behind it.
  **`files_gstr1_and_3b` exists so no caller tests the type by name** — a
  composition dealer files CMP-08 and GSTR-4 under §10, an ISD files GSTR-6, a
  §51 deductor GSTR-7 and a §52 operator GSTR-8, and `OTHER_RETURN_FORMS` holds
  the sentence so the refusal names the form that registration actually owes
  rather than saying only that this one is unavailable. An SEZ unit, an SEZ
  developer, a casual and a non-resident taxable person DO file the ordinary
  pair. **`state_code` is DERIVED from the GSTIN's first two characters**, never
  taken from the caller (the column CHECKs `state_code = left(gstin, 2)`), and
  the prefix is taken rather than `gstin.state_code` for `place_of_supply`'s
  reason — the question is which state, not whether the check digit is right.
  **Closing is not deleting**: §29 cancellation sets `effective_to`, because the
  returns for every period the registration was live are still owed and the rows
  already filed under it are keyed on its GSTIN; `withdraw` is for a
  registration recorded in ERROR and is refused once any return exists under it.

- **FOUR RETURNS A REGULAR REGISTRATION NEVER FILES NOW HAVE A BUILDER, AND
  THREE OF THEM CHECK WHAT A CA RECORDS RATHER THAN COMPUTING IT** (GST-25,
  migrations 420-423). `files_gstr1_and_3b` has refused a composition dealer
  and an e-commerce operator the GSTR-1/3B screens since GST-20; the returns
  they owe instead are `domain/gst/composition.py` (CMP-08),
  `domain/gst/gstr8.py`, `domain/gst/gstr4_annual.py` and
  `domain/gst/gstr9c.py`. All four are prepare-only, `VERIFIED = False` with
  every rate and window `[S]` and pinned exactly, and transcribed from the
  GSTN offline utilities' own VBA under
  `docs/compliance/sources/gst-offline-utilities/`, which fixes the form and
  not the rate or the law. **CMP-08 is the one the books answer**
  (`gst_return_service.cmp08_statement`, `GET /api/gst-workspace/cmp08/compute`):
  row 1 is the quarter's WHOLE turnover, exempt included, from the
  `outward_turnover` GSTR-3B already reads, at the §10 rate and split CGST/SGST
  because §10(2)(c) bars an inter-State outward supply; row 2 is the posted
  reverse-charge bills; row 3 their sum; row 4 (interest) is the caller's
  figure and zero here. Which rate applies (1%, 5% or 6%; the restaurant limb
  is the least certain) is a fact about the dealer, so `composition_category`
  (migration 420, on `clients` and `client_gst_registrations`) is nullable with
  NO default and a missing one is REFUSED, while `clients.gst_registration_type`
  defaults to `regular` because every earlier client was filed as one. It is
  resolved QUARTERLY (Rule 62) whatever the QRMP field says.
  **GSTR-8** (`ecommerce_operator_supplies` and the Table 3.1 twin, 421),
  **GSTR-4 Annual Tables 4A-4D** (422) and **GSTR-9C** (three tables, 423) hold
  facts no ledger of the client carries, so a CA RECORDS them and the module
  VALIDATES, the utility's own posture: findings are reported beside the figures
  and the statement is not refused. CGST must equal SGST; tax is collected
  exactly when the net is positive; GSTR-8's rate band forks on July 2024
  (exactly 1% before, 0.5% to 1% from); a GSTR-4 row's place of supply is the
  filer's own State. GSTR-4's Table 5 is the one derived figure (four quarterly
  CMP-08s summed; a quarter that fails is named, never read as nil). GSTR-9C
  derives only a table's own total and plain subtractions, reads the declared
  side from the GSTR-9 already built, and never derives Table 5P or 7E (a
  signed sum whose signs the VBA does not carry), the 26 expense heads or a
  multi-GSTIN apportionment; its two bindings to GSTR-9 (12E to Table 6O,
  Table 9 to row 9d) are `[S]`, and `THRESHOLD_TABLE` is display data that never
  places a client in a band. **Not built**: GSTR-6 and GSTR-7, GSTR-8 Tables
  4/4.1, GSTR-4 Table 7 and the outward summary, the GSTR-9C Part B
  certification, and a due date for any of the four
  (`compliance_obligation_service._gst_obligations` takes no registration type,
  so a composition client still sees GSTR-1/3B/9 and none of these);
  `late_filing.late_fee` refuses all four forms. What is left is in
  `docs/open-items/`.

- **A PLACE OF SUPPLY HAS FOUR SOURCES AND ONE RESOLVER**, and the invoice
  declares the field TWICE. `domain/gst/place_of_supply.recipient_place_of_supply`
  is the chain — what the caller stated (CGST Rule 46(n) makes it the
  document's own particular), then the customer's recorded state, then the
  first two characters of the customer's GSTIN (CGST §25), then the SUPPLIER's
  own state (IGST §12(2)(b)(ii), the unregistered walk-in, and it must be last)
  — and `("", "unknown")` where even that is absent, because `clients.gstin` is
  nullable. **The GSTIN branch takes the PREFIX, not `gstin.state_code`**: the
  question is which state, not whether the registration number is well-formed,
  and falling through on a bad check digit would silently turn an inter-state
  supply intra-state. `SalesInvoiceIn` carries BOTH `supply_state_code` and
  `place_of_supply`; until SALES-31 the real create path read only the first
  while the mock branch read both, so a caller filling in the second had it
  honoured under test and discarded in production. Both are validated against
  the state list now (as `ReceiptIn.place_of_supply` has been since GST-15),
  the edit path too, and a request whose two disagree is refused rather than
  silently resolved one way.

- **WHAT KIND OF SUPPLY AN INVOICE IS HAS ONE AUTHORITY, AND THE E-INVOICE
  RECORD MAY NOT CONTRADICT IT** (SALES-19). `domain/gst/treatment.
  treatment_for_invoice` derives the treatment — regular, export or SEZ, with
  or without payment, deemed export — from the invoice's own `supply_type` and
  `invoice_type`, the pair GSTR-1 is actually built from, reading the EXPORT
  ROUTE off the tax actually charged (IGST §16(3): (b) on payment of IGST,
  refunded under §54, against (a) under an LUT or bond with nothing charged —
  Table 6A's `exp_typ` turns on exactly that, and asking for the wrong one asks
  for the wrong refund under the wrong rule). `einvoice_records.gst_treatment`
  is a SECOND record of the same fact, captured when a CA prepares an IRN, and
  `POST /api/einvoice/records` stored whatever was sent while the picker seeded
  itself `"regular"` and was never told what the invoice said — so a record
  could contradict its own invoice and the compliance panel rendered both
  labels at once. `treatment_for_record` is the rule and the door **422s a
  disagreement rather than resolving it**: taking the caller's value keeps the
  wrong export route on the document a human keys the IRP from, and taking the
  derived value silently discards what somebody just chose on a screen that
  offered them the choice — `SalesInvoiceIn`'s shape where the two state fields
  disagree. **A record naming no invoice this product holds is NOT refused**:
  `sales_invoice_id` is optional (a record may be prepared for an invoice
  raised elsewhere), so there is nothing to reconcile and refusing would make
  the link mandatory by accident. The picker is READ-ONLY where the server
  decided one, because a screen must never invite a CA to type something the
  server will refuse — the `attachmentsReadOnly` discipline.

- **WHICH SUPPLIES MUST CARRY AN IRN IS `domain/gst/irn_scope.py`, AND THE RULE
  HAS TWO INDEPENDENT LIMBS** (SALES-18). `apps/web/lib/invoices/compliance.
  irnEligibility` was the ONLY implementation of CGST Rule 48(4)'s scope test
  in the repository — the same defect SALES-17 was, a statutory rule with no
  Python twin and no parity vector, which is exactly how the e-way threshold
  came to be measured on the pre-GST taxable value and stay that way. The
  e-way half was closed by MOVING the rule and keeping the browser copy as a
  pinned mirror; this is the IRN half in the same shape, pinned by
  `shared/irn-parity-vectors.json`.
  **THE PERSON LIMB AND THE SUPPLY LIMB ARE FACTS ABOUT DIFFERENT THINGS** —
  aggregate turnover above the notified threshold, and a supply to a
  REGISTERED person or an export or an SEZ — so they are computed separately
  and ANDed once. The supply limb BLOCKS (an IRN record for a B2C invoice is
  meaningless and the IRP rejects it) and is asked FIRST and short-circuits;
  the person limb only WARNS, because refusing on a figure nobody has recorded
  would stop the CA doing the one thing the screen is for.
  **THE PERSON LIMB IS A RATCHET AND THAT IS THE EASY THING TO GET WRONG.**
  Notification 78/2020 — the HSN digit rule in `hsn_digits.py` — reads on the
  turnover "in the PRECEDING Financial Year", so a client who shrinks falls
  back a band. Rule 48(4) reads on "ANY PRECEDING FINANCIAL YEAR FROM 2017-18
  ONWARDS", so e-invoicing LATCHES: a client who crossed ₹20 crore in FY
  2022-23 and has turned over ₹4 crore since is still inside it.
  `client_gst_turnover_service.highest_turnover_within_rule_48_4` takes the
  MAXIMUM across `qualifying_financial_years`, and reusing the preceding-year
  hop would let them out. **That limb is the half the browser cannot answer at
  all** — CGST §2(6) turnover is PAN-level and all-India (migration 401) and
  no screen holds it — which is why the answer is SERVED as `irn_assessment`
  on `GET /api/sales-invoices/{id}` rather than left mirrored; the panel used
  to decline the whole limb with a fixed sentence on every invoice.
  **THE THRESHOLD FORKED SIX TIMES and the INVOICE'S OWN DATE decides**
  (₹500cr → ₹100cr → ₹50cr → ₹20cr → ₹10cr → ₹5cr), the fork shape again — a
  2021 invoice keeps ₹50 crore for ever. **An ABSENT date is NOT a
  pre-commencement date**: both would answer "no threshold" if they shared a
  branch, so an undated invoice would read as owing no IRN; it takes the
  STRICTEST threshold and says so. **Registration has THREE states** and a
  malformed GSTIN is read as B2B and NAMED (`rcm_documents`' shape) — reading
  it as unregistered takes the invoice out of the rule, and **Rule 48(5) makes
  an invoice this sub-rule reaches, issued without an IRN, not an invoice at
  all**, so the recipient's credit goes with it. That asymmetry is why every
  unknown here resolves strict and flagged, and why there is deliberately no
  `undetermined` verdict (`eway.assess` has one because Rule 138(14) can flip
  its answer either way; nothing here can). The treatment is TAKEN from
  `domain/gst/treatment`, never re-derived, and the GSTIN test is SHAPE ONLY —
  a checksum would put the two implementations in disagreement on a
  transposition, which says nothing about who the customer is. The first
  proviso's EXEMPTED CLASSES are named on every "required" answer and on no
  other (an exemption can only REMOVE a requirement), with the SEZ trap stated:
  an SEZ **unit** is exempt as the SUPPLIER while a supply **to** an SEZ is in
  scope. ⚠️ Every threshold and date is `[S]`-graded, `VERIFIED` is False and
  each is pinned exactly by
  `tests/test_which_supplies_must_carry_an_irn.py`. Prepare-only: it decides
  eligibility and reaches no portal.

- **AND WHAT THE PORTAL WOULD ACCEPT IS A SECOND AUTHORITY, STRICTER THAN THE
  ACT** (GST-32). Rule 48(4) says WHICH supplies need an IRN; the IRP is
  software with its own published acceptance rules, and a document that
  satisfies the Act and fails them comes back as an error code with nothing a
  CA can act on. `domain/gst/irp_validations.py` is that second authority.
  **THE ONE THAT PROVES IT IS THE DOCUMENT NUMBER AND IT IS LIVE.** Rule 46(b)
  allows hyphen, slash, letters and numerals in any combination; the IRP's
  `Document_Num` expression is `^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$` and its
  FIRST character class is not its second — a letter or a digit **1-9**, never
  `0`, `-` or `/`. So `0001` is a lawful invoice number the portal refuses, and
  `sales_numbering_service.suggest` hands exactly that to a firm with an empty
  prefix and the FY switched off. **IT REPORTS AND NEVER REFUSES**:
  `invoice_series` is untouched and still refuses against the Act at every
  door, because a client below the threshold may number their invoices `0001`
  for ever. **Asked only where the SUPPLY limb is in scope** — `irn_scope`'s
  own short-circuit — since a B2C invoice never reaches an IRP; the turnover
  limb is deliberately not a gate, because a client about to cross it wants
  the series fixed before they do. Served as `irn_assessment.irp_findings` and
  rendered by `CompliancePanel`, with **no browser mirror**: whether a portal
  accepts a value is a fact about the portal, so `assessIrnScope`'s fallback
  answers an empty list rather than inventing one.
  **GST-32's REFUSAL OF THE PAYLOAD STANDS AND IS NARROWED, NOT REVERSED** — a
  wrong field NAME fails visibly at the portal while a misremembered field
  MEANING generates a real document with wrong figures — so this checks VALUES
  in named fields and builds no JSON. Four things are NAMED as not held
  (`irp_validations.NOT_HELD`, pinned at four), each with its own reason: the
  HSN master behind error 2176, `IsServc` against the HSN class (refused on
  the MASTER and not on the flag: migration 411 gave the line an `is_service`
  and `goods_unit_finding` now asks the goods-only quantity and UQC rule), the
  payload's own field expressions, and the arithmetic the IRP recomputes.
  **`VERIFIED` is True here and it is a claim about PROVENANCE** — every
  expression is transcribed character for character from
  `docs/compliance/sources/e-invoice/`, fetched by hand on 18-09-2026, and a
  test asserts each against that file. Two rules that look like one another are
  pinned APART: Sr. 10.3's transport document number admits a leading `0` and
  caps no length, and harmonising it is the tempting mistake.

- **A LINE SAYS GOODS OR SERVICES, THE CODE USUALLY ANSWERS, AND THE COLUMN IS
  THE OVERRIDE** (migration 411). `models/invoices.InvoiceLineIn.is_service`
  was declared, validated and DROPPED: `client_sales_invoice_lines` had no such
  column, so a caller set it and the INSERT never mentioned it. It matters
  because the e-invoice portal makes **quantity and UQC mandatory for GOODS and
  optional for services**, and CGST Rule 46(h) asks for them on goods — so
  without it a service line with no unit and a goods line missing one were the
  same row and `irp_validations` could not ask at all.
  **`domain/gst/goods_or_services.py` IS THE RULE AND IT HAD NO PYTHON TWIN.**
  A Service Accounting Code is Chapter **99** of the tariff and the HSN of goods
  runs Chapters 1-98, so a well-formed code answers by itself —
  `apps/web/lib/invoices/compliance.isServiceCode` has done exactly that since
  the e-way split was built, as the ONLY implementation in the repository, the
  same defect SALES-17 and SALES-18 were. `tests/fixtures/goods_or_services.json`
  pins the two, from the Python side.
  **THE RECORDED VALUE WINS, THEN THE CODE, THEN `None`** — the
  `place_of_supply` chain shape. The reverse order would make the column
  unwritable in practice, since every line carrying an HSN would ignore it; and
  reading the COLUMN alone (which the router did for one commit, and a negative
  control caught) reports "nobody said" against a line whose own code reads
  `998313`. The browser folds the third state into `false` and that is right
  for ITS caller — the e-way split counts unclassified lines on the HSN being
  absent — so the fixture records the difference rather than bending either
  side.
  **NULLABLE, NO DEFAULT, NO BACKFILL, and the model default moved from `False`
  to `None`.** Migration 392's sibling columns ARE `NOT NULL DEFAULT false` and
  that is not an inconsistency: those tables were new, so every row in them was
  written by a door that sets the value, while every row already in
  `client_sales_invoice_lines` predates the column — `false` there would assert
  that every line ever raised was goods. `PurchaseBillLineIn` keeps its `False`
  default for the same reason in reverse. **Nothing computes money from it**: a
  test asserts `domain/sales/line_tax` and `gstr1_builder` never mention it,
  because goods-or-services changes the PLACE OF SUPPLY rules (IGST §§10-13),
  which is a question about the transaction and not a label on a line.

- **A NIL ON A GSTR-3B SAYS WHICH KIND OF NIL IT IS.** Four rows of this
  product's GSTR-3B are nil because nothing here can DERIVE them, and on a
  filed return that is indistinguishable from a client who had none: **3.1.1(i)
  and 3.1.1(ii)** (§9(5) e-commerce — nothing marks a supply as made through an
  operator, so an aggregator's sales are counted in 3.1(a) like any other
  outward supply), **Table 5** (exempt / nil-rated / non-GST INWARD supplies — a
  purchase bill is not classified that way here) and **4(D)(2)** (§16(4) and the
  place-of-supply rules, neither tracked). Each carried its reason in a source
  COMMENT beside the literal zero, which is the right place for the next
  programmer and no place at all for the CA about to file. `_undeclarable_rows`
  in `services/gst_return_service.py` is the one list and it CALLS
  `_table_4a_gaps` rather than restating it, so the 4(A) rows keep one
  definition. **`table_4a_gaps` itself was served since GST-24 and rendered by
  nothing**, so even the ISD sentence reached nobody. No figure changes — what
  an underivable row needs is a document this product does not model, not a
  number from memory — and a test asserts no reason states a rate or an amount.
  **BOTH GSTR-3B SCREENS RENDER IT, FROM ONE COMPONENT** (GST-22).
  `components/gst/Gstr3bFindings.tsx` carries this panel, Table 5.1 and the
  bank-line note; the per-client tab spelled all three out inline and
  `computeGSTR3B` dropped the four keys on the way through, so the FIRM-LEVEL
  screen showed none of them and the two disagreed about how much of the return
  they show. Three older guards had that page's PATH written into them and
  failed on a move that did not break their rule — `scripts/panelSource.ts`
  resolves a panel by a phrase only it contains and asserts there is exactly
  one, which is the same rule stated once instead of three times.

- **GSTR-3B TABLE 4(A) HAS FIVE ROWS, AN IMPORT OF SERVICES OWNS ONE OF THEM,
  AND TWO ARE STRUCTURALLY NIL** (GST-24). `itc_avl_rows` emits all five in the
  GSTN utility's order and used to put the WHOLE reverse-charge credit on
  4(A)(3) ISRC — the DOMESTIC §9(3)/(4) line. An import of services is
  reverse-charged too (Notification 10/2017-IT(R) entry 1), so on the books it
  is indistinguishable from a GTA or advocate bill, and it went out on the
  wrong line. IGST §2(11) defines it — supplier outside India, recipient in
  India — and the only fact separating them is
  `vendors.residential_status`, read through
  `domain/tds/residency.is_non_resident` rather than compared as a string,
  because **NULL is a real third state and must not move a figure**: an
  unclassified vendor stays exactly where every vendor already is.
  **The split touches the ROW and nothing else** — the 3.1(d) liability, the
  4(A) total, 4(C) and the challan are pinned unchanged by a parametrised
  test, because `imps_*` is a SUBSET of `rcm_*` accumulated inside the same
  branch and never added to it. **The two capped rows are capped IN ORDER**:
  IMPS takes the ceiling first and ISRC takes what is left, since capping each
  independently against the same ceiling lets them together exceed it and file
  a 4(A) that does not reconcile with its own 4(C). **4(A)(4) ISD stays nil and NAMES why**
  (`table_4a_gaps`): an ISD invoice is not modelled. A nil meaning "we cannot
  see it" is not a nil meaning "there was none". **4(A)(1) IMPG left that list
  on 2026-09-14** — migration 389 gave the Bill of Entry a document, see the
  PUR-18 bullet above — and it is still not a reverse-charge row: the tax is
  collected at customs, not self-assessed, so it never touches 3.1(d).

- **A BANK LINE THE CA MARKED AS CARRYING GST IS A DOCUMENT, AND THE
  DOCUMENT IS THE TRANSACTION** (BANK-24). The posting drawer has always let a
  CA say "there is 18% GST inside this ₹590", and `bank_posting_service` then
  posts a real Dr GST Input leg (CGST §16 — a bank charge is an input service
  received in the course or furtherance of business). GSTR-3B is built from
  DOCUMENTS, and a bank line is not a purchase bill, so the credit the CA
  declared never reached Table 4(A) — while `_gl_gst_movements` DOES read the
  GST Input account, so the same rupees came back as an unexplained
  books-vs-ledger ITC difference every month, on a return about to be filed.
  Money IN was the same defect and worse: `build_inclusive_lines(is_credit=
  True)` credits GST Output, so an outward supply's liability sat in the ledger
  and no return declared it. Migration 382 records the rate that was POSTED on
  `bank_transactions` — `draft_gst_rate_bps` (322) cannot serve, because the
  caller may override it and a line posted with no draft carries NULL — and
  **that is what keeps the reconciliation's two sides independently derived**:
  reading the tax back out of `journal_lines` would make this slice compare the
  ledger with itself, the same reason Table 4(B) is built from documents.
  `domain/gst/bank_charge_gst.py` is the rule; the inward side goes to
  **4(A)(5) "All other ITC"** (not 4(A)(3) — the bank charges the tax and pays
  it over, and the reverse-charge row would also create a 3.1(d) liability that
  does not exist) and the outward side to **3.1(a)** through the one
  `_outward_transactions` Rule 43's turnover also reads. Three refusals are
  deliberate: **a recorded ZERO declares nothing** (it posts identically to an
  unmarked line, so nothing says whether a receipt is nil-rated, exempt,
  outside the levy — or not a supply at all), **never Table 3.2** (no recipient
  state, no recipient class; the `SalesTransaction` defaults keep it out by
  construction — do not helpfully fill them in), and **no §17(5) split**. What
  cannot be computed is NAMED on every answer that carries one: §16(2)(aa)
  wants a supplier document a bank line does not hold, and an outward supply
  with no tax invoice will not be in the GSTR-1 the portal compares this return
  against (Rule 46). **No GSTIN is invented** — the finding's own suggested fix
  would have put one on a bank table so the 2B match passed, which is claiming
  a document exists.

- **THE ANNUAL RETURN CONSOLIDATES THE YEAR'S OWN RETURNS, AND NOTHING ADDED
  THEM UP** (GST-10). CGST §44 with Rule 80(1): GSTR-9 consolidates the
  financial year's GSTR-1 and GSTR-3B, and the portal opens it once every one
  of them is furnished and auto-populates from them. The GSTR-9 tab loaded a
  saved draft and **nothing created one** — every figure was already in the
  product and nothing totalled them. `domain/gst/gstr9_builder.py` is the
  authority for Tables 4, 5, 6, 7, 8, 9 and 17; `services/gstr9_service.py`
  fetches; `GET /api/gst-workspace/gstr9/compute` serves; the screen decides
  nothing, saves nothing and files nothing.
  **IT READS `payload_json`, NOT `gstr3b_returns`' OWN PER-HEAD PAISE COLUMNS.**
  Migration 036 declared them and **`save_gstr3b` has never written one** — it
  stores `tax_liability_paise`, `itc_claimed_paise`, `net_tax_paise`,
  `rcm_cash_paise`, `cash_payable_paise` and the two JSON blobs, and every other
  column keeps its `DEFAULT 0`. Reading them would give a confident nil for
  every month of every client, which is the worst possible answer on an annual
  return. Twenty-four header rows and their payloads for a year — proportional
  to the ANSWER.
  **A STORED RUPEE FIGURE COMES BACK THROUGH `Decimal(str(v))`, NEVER
  `int(v * 100)`.** GSTR-1's payload is 2-decimal rupees and GSTR-3B's is whole
  rupees, and in binary floating point `0.29 * 100` is 28.999999999999996 — a
  paisa lost, on some values only, twelve months over, on a return that has to
  foot. That is not a precision loss overall: the annual return consolidates
  what was DECLARED, and what was declared was those rupees.
  **TABLE 4(A)'s FIVE ROWS ARE TABLE 6's ROWS.** GST-24 split imports of
  services out of the domestic reverse-charge line and PUR-18 gave imports of
  goods a document, so IMPG→6E, IMPS→6F, ISRC→6C+6D and OTH→6B are already told
  apart in the return being consolidated; there is nothing to apportion. And
  the `b2b` section carries Tables **4B, 4D, 4E and 5B** at once, told apart
  only by `inv_typ` — a test reads `gstr1_builder._INV_TYP` so a value added
  there without a home here fails rather than falling into 4B and declaring a
  deemed export as an ordinary B2B supply.
  **TABLE 7 IS THE ONE GSTR-3B CANNOT ANSWER.** Its Table 4(B) has two boxes,
  permanent and reclaimable, and Rules 38, 42, 43 and §17(5) share one;
  `itc_reversal_register` records the statutory GROUND (migration 362), which
  is exactly what Table 7 asks for. A ground with no row is NAMED and kept OUT
  of the total rather than folded into "other reversals". **The year is
  selected by `period`, the register's own MMYYYY of the GSTR-3B the row was
  declared in** — there is no reversal DATE column, and §44 with Rule 80(1)
  consolidates the returns FURNISHED for the year, so the period is the right
  key as well as the only one. `.in_` over the twelve named periods and never
  a range: MMYYYY is TEXT, so `'042025' > '032026'` and a `gte`/`lte` would
  drop the first nine months of every year and keep three belonging to the
  next. The first draft filtered on an invented `reversal_date` and the mock
  suite agreed, because the FIXTURE invented it too — which is why that test
  module now asserts every fixture key against the production snapshot.
  **A NIL ON AN ANNUAL RETURN DECLARES THAT NOTHING WAS OWED, so a row nobody
  can derive carries a NOTE and renders as a dash.** Six are refused and named:
  Table **6B's three-way split** (inputs / capital goods / input services — no
  column records it and it is a judgement about USE; the TOTAL is derived, only
  the apportionment is not), **6C against 6D** (recorded on
  `vendors.gst_registration_status` but not carried by the monthly 3B being
  consolidated), **Rule 39 / 6G** (no ISD invoice is modelled), **TRAN-I and
  TRAN-II**, **8C** (a fact about the NEXT year's returns), and **8A** (the
  portal auto-populates it; totalling a year of `gstr2a_records` is a read
  proportional to transaction volume for a four-number answer — a stored
  per-period total is the right next step and is a migration). **A month FILED
  but whose payload this product never held** is named too: its tax is in the
  3B row and its Table 4 breakdown is not.
  **Tables 10–14, 15, 16, 18 and 19 are NOT built and each says why** —
  §47(2)'s ANNUAL-return fee is not held in `domain/gst/late_filing.py` — a
  different figure from the monthly ladder that module now carries — so Table
  19 must not invent one. Its guard used to assert `LATE_FEE_RATES == {}`,
  which was a spelling and broke the day the monthly figures were written in;
  it asks for a `gstr9` fee and requires a refusal. ⚠️ The FORM's own numbering and row labels
  are `[S]`, written from knowledge because every `.gov.in` is refused at this
  environment's proxy; the FIGURES are not affected, each being a total of
  figures this product computed and the CA filed.

- **A RETURN PERIOD IS NOT ALWAYS A MONTH, AND THE QUARTER'S KEY WAS ALREADY
  CHOSEN** (GST-11). Rule 61A with the proviso to §39(1) — Notifications 82,
  84 and 85/2020-Central Tax — lets a registered person whose preceding-year
  aggregate turnover was up to ₹5 crore furnish GSTR-1 and GSTR-3B QUARTERLY
  while paying monthly (QRMP), which is a large share of a small practice's
  book. The DUE DATES were fully QRMP-aware and the return could not be built
  at all: `gst_return_service._period_bounds` raised on anything but MMYYYY
  and returned one calendar month, so the CA was quoted the 13th and the
  22nd/24th and then had to add three monthly GSTR-3Bs by hand.
  `domain/gst/return_period.py` is the authority; the quarter is READ OFF
  `core.ist_clock.fy_quarters` rather than restated, because "which months are
  in this quarter" already exists twice.
  **THE KEY IS THE QUARTER'S FIRST MONTH AND THAT IS NOT A NEW DECISION**:
  `routers/compliance.py::mark_compliance_filed` already writes the `filings`
  row for a quarterly obligation as `f"{start[5:7]}{start[0:4]}"` off the
  calendar's own period_start, and `_unsubmitted_workspace_return` looks the
  prepared return up under it — keying on the quarter END would have left both
  reading a key nothing writes. It stays six digits, so migration 390's
  `(client_id, period, gstin)` still constrains and nothing stored collides.
  **ANY month of the quarter resolves to it** and the answer always reports the
  canonical key, so the browser saves `result.period` and never the month it
  asked for.
  **EVERY PERIOD-KEYED READ IS ASKED FOR EVERY MONTH THE WINDOW COVERS**, which
  is the half that is easy to get wrong: a GSTR-2B is generated MONTHLY for a
  quarterly filer too, so Rule 36(4) reads three of them (`.in_` over the named
  months, never a range — MMYYYY sorts wrong), the reversal register reads
  three periods, and Table 11 takes the window's bounds. `have_2b` is now "all
  three on file", and the months with none are NAMED rather than left to read
  as a supplier's fault. **The §50(1) clock takes the registration's own due
  date** — the 22nd or 24th after the QUARTER — because the monthly date would
  demand interest from a taxpayer who is not late; an unknown state keeps
  `gstr3b_due_date`'s earlier-of-the-two rule and SAYS it did.
  **The FREQUENCY is a fact about the REGISTRATION**, carried on
  `domain/gst/registrations.Registration` since GST-20 and thrown away by the
  engine until now; a caller may state it, because `filing_frequency` is the
  position TODAY and a return may be rebuilt for a year the client was on the
  other regime. Two things are REPORTED, not resolved: the form's own `fp` for
  a quarter carries the first month and whether the offline utility wants that
  or the last could not be checked here (`[S]`), and **Rule 59(2)'s Invoice
  Furnishing Facility is built apart from the return** (`domain/gst/iff.py`,
  `GET /api/gst-workspace/iff/compute`, `IffPanel`) and is NAMED as available
  on every quarterly GSTR-1 (`return_period.IFF_AVAILABLE`), because without it
  the RECIPIENT's credit waits for the quarter. Rule 43's own working stays
  MONTHLY and says why: whether 43(1)(c)'s one-sixtieth tax period is the
  quarter was not settled here.

- **THE INVOICE FURNISHING FACILITY IS ONE CALENDAR MONTH AT A TIME, FOR
  REGISTERED RECIPIENTS ONLY, AND STORES NOTHING** (Rule 59(2) with Rule 61A).
  `gst_return_service.iff_from_books` resolves the period MONTHLY however the
  registration files, because widening a QRMP client's March to the quarter is
  the one thing the facility exists to avoid; it serves months 1 and 2 only
  (the third is in the quarterly return, and furnishing it too would declare it
  twice) and answers the third month with a sentence rather than a 500. The
  rule's own words, "to a registered person", decide every section: B2B
  including SEZ and deemed export (`B2B_SECTION_CATEGORIES` already groups
  them) and CDNR; B2CS, B2CL, CDNUR, exports, nil, HSN and the document series
  are NAMED in `SECTIONS_NOT_IN_IFF` with a reason each, so an absence is never
  a defect to a CA comparing it against the sales register. It reads the same
  `_classified_sales_documents` the quarterly return does, so a document
  furnished early and the same document declared in the quarter cannot be
  classified differently. The Rs 50 lakh monthly cap is REPORTED and never
  truncated to; amendments are NAMED (`AMENDMENTS_NOT_BUILT`) and not
  produced; nothing is stored, because `gstr1_returns` is keyed on (client,
  period, gstin) and a month of a quarter is not a return period. It is
  optional, so it raises no deadline in the calendar
  (`compliance_engine.iff_due_date` is the 13th and only reports it).
  `VERIFIED` is False: the window, the cap and the two-month scope are `[S]`
  and pinned exactly. Prepare-only, with GST-32's refusal of the payload's own
  envelope unchanged.

- **GSTR-3B Table 3.1(a) carries GSTR-1 TABLE 11, and the ledger cannot.**
  §13(2) puts the time of supply for SERVICES at the earlier of invoice or
  payment, so tax on an advance received for services falls due on receipt,
  before any invoice exists; Notification 66/2017-Central Tax removed the
  charge for GOODS (§12(2) proviso), which is why the whole of Table 11 is
  gated on the client's own `gst_advance_tax_applicable` and why it is off by
  default. `gst_advance_service.table_11_sections` builds the GSTR-1 rows AND
  totals the same buckets in paise for 3.1(a) — one `split_inclusive_charge`
  per bucket, because two independent computations of one figure is how the
  two returns came to disagree: 3B had no advances input at all, so a client
  with the flag on filed a GSTR-1 declaring a liability and a GSTR-3B that
  discharged none of it (GST-15). **11A less 11B, and both halves are
  required** — the invoice that consumes an earlier period's advance is in
  this period's sales and carries its whole value again, so 11A alone would
  replace an under-declaration with a double charge. The net is deliberately
  NOT clamped. **It is not in Table 3.2**: a receipt records no recipient
  class, so a 3.2 bucket would assert a fact the books do not hold. And it is
  **declared but not posted** — a receipt journal is Bank Dr / Trade
  Receivable Cr with no output-tax leg — so `gst_return_service` holds it out
  of the books-to-ledger comparison and NAMES the amount
  (`advance_tax_excluded_paise`) rather than reporting every advance-bearing
  client as permanently unreconciled.

- **GSTR-3B Table 6 — the set-off has FOUR steps, and the total is not the
  challan.** §49(5)(a) spends IGST credit on IGST and then, with Rule 88A, on
  CGST and SGST; §49(5)(b) then lets CGST credit pay CGST **and then IGST**, and
  §49(5)(c) lets SGST credit pay SGST and then IGST. CGST is worked before SGST
  because the proviso to §49(5)(c) allows SGST credit against IGST only where
  CGST credit is not available for it. §49(5)(e)/(f) bar CGST↔SGST entirely.
  Implementing only the IGST limb left local credit stranded and demanded cash
  the client did not owe. **Reverse-charge tax is never part of that**: §49(4)
  allows the credit ledger to pay only "output tax", and §2(82) defines output
  tax as EXCLUDING "tax payable by him on reverse charge basis" — so §9(3)/(4)
  tax is always cash, always on top, and `cash_payable_paise` rather than
  `net_*` is the challan figure. **A zero-rated supply carries tax when it is
  made on payment of tax** (§16(3)(b), refunded under §54); nil only under an
  LUT or bond (§16(3)(a)). `domain/gst/gstr3b_computer.py` is the authority for
  all three, and the callers carry them — a figure the computer gets right and
  no screen shows is not a fixed bug.

- **THE SET-OFF RUNS AGAINST THE LEDGER'S BALANCE, NOT JUST THIS RETURN'S 4(C)**
  (gst-06, migration 474). `compute_gstr3b` spent Table 4(C) of ONE return and
  nothing else, and the electronic credit ledger is a RUNNING balance: credit
  an earlier return left unspent is still in it, and §49(4) lets the whole of
  it pay output tax. Apex's April 2026 closed holding Rs 36,54,961.65 of IGST
  credit and the next month, with Rs 1,00,000 of output tax, showed Rs
  1,00,000 payable in CASH — which under Rule 88B(1) is also the base late
  interest is charged on. `domain/gst/credit_ledger.py` is the authority,
  `services/gst_credit_ledger_service.py` the reads and the one write,
  `routers/gst_credit_ledger.py` the door, and
  `components/gst/Gstr3bCreditLedger.tsx` renders the server's block.
  **THE OPENING HAS THREE SOURCES AND ONE ORDER**: a balance a CA KEYED from the
  portal for this exact window (`gst_credit_ledger_openings`) wins; else the
  closing of the return whose `credit_closing_as_of` is the day BEFORE this
  window starts; else it is NOT KNOWN. The chain is an EXACT date match and
  never "the latest earlier period", so a registration that moves between
  monthly and quarterly filing cannot skip or repeat a month and a missing
  month is not silently chained across. **A recorded figure beats the chain
  because the portal is what a return is paid from and the chain is only an
  estimate of it** (a refund, an ITC-02 transfer or a return filed elsewhere
  all move the real ledger and none reaches a return saved here); where they
  differ the difference is REPORTED per head, never absorbed.
  **NOT KNOWN IS TREATED AS NIL FOR THE ARITHMETIC AND SAYS SO, IN ITS OWN
  WORDS.** Assuming an empty ledger can only OVER-state the cash a client pays
  (the credit they hold is simply unused and carries), while assuming credit
  that is not there would leave tax unpaid with interest running — so the
  balance is zero, `known` is false, and a sentence travels with it, rendered
  in the attention palette and not as an ordinary zero. `unreadable` (the read
  failed) is a FOURTH state from `not_recorded` (nobody has said) because one
  sends a CA to key a balance and the other to compute again; `opening_for`
  never raises, so a failed read cannot stop a return being prepared and
  cannot read as a clean nil. **A chained opening from a return that is saved
  but not marked filed is provisional and says so**, because the portal's
  ledger moves only when a return is FILED.
  **THE POOL, NOT TABLE 4**: each head's pool is 4(C) plus the opening, and the
  §49(5) order runs over it unchanged (IGST credit first under Rule 88A,
  whichever return it came from). 4(C), the payload's `itc_net` and every
  declared table are NOT touched — adding last month's credit to this month's
  form would declare credit twice. Cess credit pays cess only, and
  reverse-charge tax is still cash whatever the opening. `itc_available_paise`
  is now opening plus 4(C) and `itc_carried_forward_paise` equals the sum of the
  per-head `closing_*`, asserted for every opening in a matrix; with no opening
  every figure is what it was before. Rule 88B interest is charged on the cash
  figure and that is the one that fell, so a late return the opening covered in
  full owes none.
  **THE GSTR-3B IS SAVED BY FOUR DOORS AND THE CHAIN NEEDS ALL OF THEM**: the
  API's save and its recompute (both store the ten `credit_*` columns; recompute
  rewrites them, or a recomputed draft would chain the balance it had BEFORE),
  the firm-level screen's `saveGSTR3BReturn` (straight over PostgREST, so
  `rbac()` and the API never run and the columns are named in its literal
  payload) and the client page (which sends the served `credit_ledger` block and
  would otherwise have it dropped by Pydantic without a word). A save that
  states no statement leaves what the row records, and is never written as a nil
  ledger; a statement that is not whole, or dated other than the window's end, is
  a 422 — a wrong date would orphan or mis-chain every return after it. NULL in
  all ten columns (every return saved before 474) means nobody recorded it and is
  never chained, with NO backfill: a closing depends on an opening nobody stated.
  **Keying is refused for a window whose GSTR-3B is already filed** (the filed
  return recorded the opening it was computed with; a correction belongs in the
  NEXT window's opening); deleting a keyed balance hands the window back to the
  chain and does NOT mean the ledger was nil (key a nil balance for that). The
  table's writes are service-role only and `authenticated` reads under the
  RESTRICTIVE assignment policy. **Deliberately NOT done**: nothing reads the
  portal (the ledger is a portal figure and this product cannot see it — every
  number is keyed by a person or carried from a return computed here); the
  cash ledger and its balance are not modelled; the opening is not split by
  registration documents (the not-split caveat still applies to which documents
  a return holds); and no existing return is back-filled, so a client's first
  return after this lands opens with a keyed balance or says it assumed nil.

- **A RULE 37 REVERSAL CARRIES §50(1) INTEREST, AND THE CLOCK IS NO LONGER IN
  THE RULE** (GST-28). Rule 37(1) with the second proviso to §16(2) requires
  credit on a bill 180 days unpaid to be paid back "along with interest payable
  thereon under section 50", and `rule37_report` stated the tax and stopped.
  The RATE is settled: §50(3) reaches credit "wrongly availed AND UTILISED",
  which Rule 37 credit is not — it was validly availed and the consideration
  went unpaid — so §50(1)'s 18% applies, and that also matters because §50(3)'s
  own notified rate is a named gap here. ⚠️ **The PERIOD is not settled**:
  Notification 19/2022-Central Tax substituted the whole of Rule 37 from
  01-10-2022 and its sub-rule (3), which ran the clock "from the date of
  availing credit on such supplies", did not survive the substitution. So
  `interest_on_rule_37_reversal` takes the window rather than choosing it, and
  the report shows BOTH readings — from availment and from the 180th day — with
  the caveat naming what was omitted. Picking one silently would over- or
  under-state a sum the client pays over. The panel sums over the bills THIS
  return carries, never every overdue bill: Rule 37(1) puts each reversal in
  one specific return, and an earlier one's interest belongs to a return
  already filed. **A one-click "Post this reversal" is deliberately NOT built**
  — `itc_register_service` records why, and a guard asserts no such button
  appeared.

- **RULE 37A IS THE SUPPLIER'S DEFAULT AND RULE 37 IS THE RECIPIENT'S; THEY
  SHARE A BOX AND NOTHING ELSE** (GST-28, second half). `itc_reversal_register`
  has accepted a `rule_37a` ground since migration 362 and GSTR-3B Table
  4(B)(2) has a slot for it, and nothing produced a figure. Rule 37A
  (Notification 26/2022-Central Tax): where a supplier DECLARED the invoice in
  GSTR-1 but has not furnished the GSTR-3B for that period by the **30th of
  September** following the end of the FY the credit was availed in, the
  recipient reverses it by the **30th of November** following — and an
  unreversed credit is payable with §50 interest. `domain/gst/rule_37a.py` is
  the rule and `services/rule_37a_service.py` fetches.
  **BOTH DATES HANG OFF THE END OF THE AVAILMENT YEAR**, which is the part that
  is easy to get wrong twice over: the FY's own September and November would be
  a year early, and "sixty days after the supplier's date" two months late.
  **THE ONE FACT THIS PRODUCT CANNOT HOLD IS WHETHER THE SUPPLIER FILED**, and
  it is NAMED on every answer rather than guessed — GSTR-2B is generated FROM
  filed GSTR-1s, so a document appearing in it proves the GSTR-1 and says
  nothing about the 3B, and `gstr2a_records.supplier_filed_on` is the trap
  (it is the GSTR-1's date, so reading it would report every supplier as
  compliant). Guessing "filed" leaves a reversal undone with interest running;
  guessing "not filed" reverses credit the client is entitled to.
  `supplier_filed_gstr3b` is typed `null` in the browser so a screen cannot
  fill it in.
  **THE POPULATION IS THE MATCHED DOCUMENTS**, read from `gstr2a_records`
  rather than from `purchase_bills`: the rule reaches a supply whose invoice
  the supplier DID declare in GSTR-1, which is exactly what a 2B match proves,
  and a bill missing from 2B is §16(2)(aa) and belongs in the reconciliation.
  An empty answer is a NAMED gap, not a clean bill of health. **The §50
  interest is deliberately NOT computed** — the rule does not say which date it
  runs from, and `late_filing.interest_on_rule_37_reversal` already shows two
  readings for the same silence in Rule 37; a single figure here would be a
  third answer to an open question. Nothing is posted: the CA raises the
  journal and registers it with ground `rule_37a`, which is RECLAIMABLE
  (4(B)(2), released into 4(D)(1)) because the rule lets the credit be
  re-availed once the supplier files. ⚠️ Every date is `[S]`-graded and pinned.

- **WHAT BEING LATE COSTS IS `domain/gst/late_filing.py`, and half of it is a
  REFUSAL.** §50(1) interest is COMPUTED — 18% (Notification 13/2017-Central
  Tax), and Rule 88B(1) is the load-bearing part: where the supplies are
  declared in a return furnished after the due date, interest runs only on
  "that portion of the tax which is paid by debiting the electronic CASH
  ledger", so a head the credit ledger discharged in full bears NONE however
  late the return is, and charging on the gross output tax demands several
  times what is due. `cash_payable_*` is that base and is the same figure Table
  6 pays the challan with. Rule 88B(2) is the other case — tax NOT declared in
  the return, found in a §73/§74 proceeding — and there it IS the whole tax
  from the date it fell due, so a caller that used the cash figure would
  understate it. **§50(3) REFUSES TWICE OVER.** Its base is credit wrongly
  availed **AND UTILISED** (Rule 88B(3)), never the availed figure — credit
  availed and never utilised bears nothing, so the substitution would charge a
  taxpayer who owes nothing. That refusal STANDS and is not about a rate.
  **ITS RATE IS 24%, READ OFF THE PRIMARY DOCUMENTS, AND WAS WRONG HERE THREE
  TIMES BEFORE THAT.** The module stated 24% (13/2017-CT against the ORIGINAL
  sub-section), then refused entirely because the Finance Act 2022 substituted
  §50(3) retrospectively from 01-07-2017, then stated **18%** on several
  independent secondary sources that agreed with each other and with a chain
  reading s.111 → s.116 with the Sixth Schedule → Notification 9/2022-CT.
  **THE SECOND AND THIRD LINKS OF THAT CHAIN ARE FALSE**, and all three
  documents were read on 18-09-2026: FA 2022 **s.111** (Gazette p.65)
  substitutes §50(3) and **DELEGATES** the rate — "at such rate **not
  exceeding twenty-four per cent. as may be notified**" — fixing no figure, so
  there is no 18% in the Act at all; **Notification 9/2022-CT** appoints
  05-07-2022 for "clause (c) of section 110 and **section 111**" alone, never
  reaching s.116, carrying no Schedule and stating no percentage; and
  **Notification 13/2017-CT**, made under sub-sections (1) **and (3)** of
  section 50, fixes §50(1) at 18% and **§50(3) at 24%**, with CBIC's own
  amendment history recording four amendments (31/2020, 51/2020, 08/2021,
  18/2021 — all COVID-period concessions) and **nothing after July 2022**. So
  the delegation was never exercised again; the substitution takes effect from
  the very date 13/2017 came into force, so no window exists in which the
  notification lacked a parent provision, and General Clauses Act s.24 carries
  it forward. **THE CEILING AND THE RATE ARE THEREFORE THE SAME NUMBER**, and
  the test asserting they must DIFFER — "collapsing them is how the module got
  it wrong the first time" — was an invariant inferred from a bug rather than
  from the sub-section; it now asserts the equality and says why. **THE ERROR
  RAN THE UNSAFE WAY**: 18% UNDER-states the charge by a quarter, so the engine
  was telling a CA their client owed less than they do on credit wrongly
  availed and utilised, leaving a residual demand with the clock still running
  — the original refusal reasoned about the right risk and misjudged which
  direction it lay in. `SECTION_50_3_RATE_VERIFIED` is now **True**, which is a
  claim about **PROVENANCE** (a primary document was read) and not about
  confidence — the first constant in the module for which that holds. The
  constant stays `Optional` so a later notification can move it or a later
  reader withdraw it to a refusal, and a test exercises that branch. ⚠️ The
  2020/2021 concessional notifications are still **not held**, so a tax period
  they covered is charged at 24% and the caveat on every charge says so.
  **THE §47 LATE FEE IS NOW COMPUTED FOR EVERY PERIOD THE CHARGE HAS EXISTED,
  AND §47(2) IS A DIFFERENT SUB-SECTION WITH A DIFFERENT SHAPE.** Four
  notifications were read on 18-09-2026; what each settled is recorded in
  `docs/compliance/sources/gst-notifications/README.md` (the notification texts
  themselves are not committed). **THE PER-DAY RATE HAS NEVER
  MOVED** — 4/2018 (GSTR-1) and 76/2018 (GSTR-3B) both waive above ₹25 a day
  central tax and ₹10 for a nil return, exactly what 19/2021 and 20/2021 kept;
  what 2021 ADDED was the turnover-banded ceiling (**₹2,000** to ₹1.5 crore,
  **₹5,000** to ₹5 crore, **₹10,000** above) and the **₹500** nil cap. So the
  fork is entirely in the CAP, and FY 2017-18 to 2020-21 take §47(1)'s own
  ₹5,000 under each Act because neither 2018 notification sets one.
  **A LADDER WITH ONE BAND ASSUMES NOTHING**: `turnover_band_assumed` is gated
  on `len(turnover_caps) > 1`, because flagging it on a 2019 answer would
  attach a caveat naming ₹1.5 crore and ₹5 crore thresholds that did not exist
  that year — a sentence about the wrong notification on a figure that is
  exactly right.
  ⚠️ **APRIL AND MAY 2021 ARE INSIDE FY 2021-22 AND OUTSIDE 19/2021 AND
  20/2021**, which run from the tax period JUNE 2021. The table is keyed on a
  financial year, so those two months are the one place the key is coarser than
  the notification. `late_fee` takes an optional `tax_period_start` and resolves
  them exactly; a caller who omits it gets the banded cap and a caveat NAMING
  the two months. The direction is deliberate — the banded cap is the SMALLER
  for every taxpayer below ₹5 crore, so the assumption understates.
  **§47(2)'s ANNUAL fee is `_annual_late_fee` and could not have been a fourth
  row of that table**, because its ceiling is a **PERCENTAGE** and not a figure.
  Notification 7/2023-CT, FY 2022-23 onwards: **₹50 a day** to ₹5 crore of
  aggregate turnover and **₹100 a day** to ₹20 crore, each capped at **0.04%**
  of turnover in the State; above ₹20 crore the notification gives no reduction
  and §47(2)'s own ₹200 a day capped at 0.5% applies — written as the ladder's
  third BAND rather than as a fallback, so a rate resolved by walking a table
  cannot silently find nothing. **THE CAP NEEDS A DIFFERENT TURNOVER FROM THE
  BAND**: the band is CGST §2(6) aggregate turnover, PAN-level and all-India,
  which `client_gst_turnover` (migration 401) holds; the cap is "turnover in the
  STATE or Union territory", which nothing here holds and which differs per
  registration. So `cap_gap` names it and the answer is the **UNCAPPED**
  accrual — the one figure in this module that errs HIGH, and it says so,
  because the alternative is no figure at all and a CA told what is missing
  knows both their maximum and what to record. The **amnesty proviso** (FY
  2017-18 to 2021-22 furnished 1 Apr – 30 Jun 2023, capped ₹20,000) is asked
  FIRST because it REPLACES the bands and needs no turnover at all; that window
  has closed, so the branch can only describe a return already on the record.
  **GSTR-9 Table 19 stays unbuilt** and its sentence now names the half that
  cannot be answered: what is PAYABLE is computed, what is PAID is a fact about
  a challan this product does not record, and a return declaring the fee paid
  when it has not been is a false declaration rather than a rounding. An unknown
  return type — GSTR-4, GSTR-7, GSTR-8, CMP-08 — is still REFUSED.
  Two conventions
  are stated rather than assumed: **DAYS, not months** (due 20 July, paid 21
  July is one day — NOT the §201(1A) "month or part of a month" arithmetic,
  which would be thirty times wrong here), and **rounded UP**, because interest
  is a sum the taxpayer OWES and understating it leaves a residual demand —
  the same direction ESI takes and the opposite of the GST discount, which
  floors because there understating cannot under-declare tax. ⚠️ Two `[S]`
  points, both failing generous: the divisor is 365 even in a leap year, and
  the 2020 concessional-rate notifications are NOT held, so a period they
  covered is charged at 18% and SAYS SO in its caveats.
  **`filed_on` is OPTIONAL everywhere it appears** — a return being prepared
  has no filing date, and defaulting to today would put a figure on Table 5.1
  that changes every day the return is not filed.

- **COMPENSATION CESS HAS TWO LIMBS, ITS OWN LEDGERS, AND IS NEVER PART OF
  `total_gst_paise`.** GST (Compensation to States) Act 2017 §8(2) levies "on
  the basis of VALUE, QUANTITY or on such basis", and real Schedule entries use
  each: aerated waters and motor vehicles ad valorem, coal at so much per
  tonne, cigarettes a percentage PLUS a figure per thousand. So a line carries
  `cess_rate_bps` AND `cess_specific_paise_per_unit` (migration 374, the second
  named to match `firm_hsn_rate_history`'s column from migration 181) and the
  charge is their SUM — a single percentage column silently under-charges coal
  and tobacco. `domain/gst/compensation_cess.py` is the authority and
  `apps/web/lib/money/cessLine.ts` the keystroke mirror, pinned by
  `shared/gst-parity-vectors.json`. **The AMOUNT is derived, never typed**, for
  the reason cgst/sgst/igst are derived from `gst_rate_percent`. **Both
  roundings match the GST heads** — floor the ad valorem limb, truncate the
  per-unit one — because §11(2) applies the CGST Act mutatis mutandis and a
  cess rounding the other way would disagree with the GST on its own line.
  **§11(2)'s proviso is what keeps it separate all the way down**: credit of
  this cess "shall be utilised only towards payment of cess", so it has its own
  asset (`Compensation Cess Input Credit`) and its own liability
  (`Compensation Cess Payable`) rather than the GST Input/Output ledgers,
  `gstr3b_computer` keeps the head out of the §49(5) set-off ladder, and it is
  in `total_paise` (the customer owes it) and NOT in `total_gst_paise` (what
  Table 6 sets off). **The two ledger NAMES avoid the substrings "GST Input"
  and "GST Output" deliberately** — those are `_find_account`'s ILIKE
  fallbacks, matched `.limit(1)` with no ordering, so a cess account matching
  one could be returned for a CGST lookup on any chart without per-head
  accounts, which is every chart this product seeds. The per-unit figure is per
  the LINE'S OWN UQC; nothing converts tonnes to kilograms. **No rate table is
  held**: which cess reaches which HSN is Schedule data that moves by Council
  notification, the same human step as the state PT slabs. Three things are
  named rather than modelled — a "whichever is HIGHER" Schedule entry (record
  the limb that applies), the four §34 NOTE tables (they have no cess column,
  so a note against a cess-bearing invoice is reported in the return's
  `cess_gaps` rather than silently declaring nil), and no upper bound on the
  rate, because Schedule column (4) carries entries above 100%.

- **A discount on the invoice reduces the value of supply; a discount after it
  does not, and the two are different sections.** §15(3)(a) excludes a discount
  "given before or at the time of the supply if such discount has been **duly
  recorded in the invoice**" — so the tax is charged on the NET and the relief
  is conditional on the document showing it, which is why the discount is a
  column of its own rather than a smaller rate, and why the PDF prints gross,
  deduction and net. §15(3)(b) reaches a POST-supply discount only where it was
  established in an agreement at or before the time of supply, is specifically
  linked to the invoices, AND the recipient has **reversed the attributable
  ITC** — that is the §34 credit note, not a field on one, and
  `models.invoices.InvoiceLineIn` (which the note routes use) deliberately has
  no discount field while `SalesInvoiceLineIn` does. `domain/gst/discount.py`
  is the rule; a **document-level** discount is allocated pro-rata across the
  lines BEFORE tax, because GST is charged per line at the line's own rate and
  a bill-level deduction could not otherwise be taxed on an invoice with mixed
  rates. Line discount first, then the document one on what is left. Every
  rounding floors — a larger discount is less tax, so flooring is the direction
  that cannot under-declare — and the pro-rata split uses largest-remainder so
  the parts sum to the whole exactly. `apps/web/lib/money/gstLine.ts` mirrors
  all of it and `shared/gst-parity-vectors.json` pins the two.

- **A TAX INVOICE'S NUMBER IS A STATUTORY FIELD WITH FOUR LIMBS, and the product
  used to enforce two.** CGST Rule 46(b) requires "a CONSECUTIVE SERIAL NUMBER not
  exceeding SIXTEEN CHARACTERS ... containing alphabets or numerals or special
  characters hyphen or dash and slash ... UNIQUE FOR A FINANCIAL YEAR".
  `domain/gst/invoice_series.py` is the authority for all four.
  **Length and the character set REFUSE** — at create, at edit, at bulk import and
  at issue; no legitimate series needs seventeen characters or a `#`, and both the
  GSTR-1 schema and the IRP reject them anyway. **A break in the SEQUENCE only
  WARNS**, because a gap has legitimate causes — a client arriving mid-year with a
  series already running, a cancelled invoice, or a second series, which the rule
  expressly allows ("one or multiple series"). **Uniqueness is enforced stricter
  than the rule** — per client full stop, not per FY (migrations 151/209).
  **Numbering is no longer "fully manual"**: that decision was recorded in three
  places and is reversed as of 2026-09-12 (SALES-12). `invoice_settings`
  (migration 126) has always held the firm's prefix, FY flag, padding and starting
  number; nothing read them. `services/sales_numbering_service.py` now does, and
  `GET /api/sales-invoices/next-number` suggests the next number for the form to
  pre-fill. The box stays editable and what is written is still whatever the
  request carries — Tally's "Automatic (Manual Override)", which is the mode a
  practice actually runs. **The rule has exactly two implementations**, the Python
  authority and `apps/web/lib/invoices/gst.ts`'s keystroke mirror, pinned by
  `tests/fixtures/invoice_number.json` which both suites read; `models/invoices.py`
  delegates rather than carrying a third. **A series with the FY switched OFF does
  not restart each April** — the client-wide unique index would reject the
  collision — so the sequence keeps climbing, and that falls out of matching on the
  series head rather than being special-cased.

- **HOW MANY DIGITS OF HSN A RETURN MUST CARRY IS `domain/gst/hsn_digits`, AND
  THE TABLE THAT USED TO LIVE IN THE BUILDER WAS A HYBRID OF TWO
  NOTIFICATIONS** (GST-17, migration 401). `_required_hsn_digits` returned 6
  above ₹5 crore, 4 above ₹1.5 crore and 0 below — the ₹1.5 crore rung is the
  PRE-2021 table's and the digit counts beside it are the POST-2021 table's,
  so it existed in no notification at all. **Notification 78/2020-Central Tax**
  (15-10-2020, in force 01-04-2021) is 6 digits above ₹5 crore on every supply
  and **4 digits on B2B at or below it**, optional only on B2C — so a client
  with ₹1 crore of turnover was told HSN was optional when four digits are
  required on every B2B supply however small the turnover. Both tables are
  held and the PERIOD decides, because a belated GSTR-1 for a 2019 period is
  filed under the rule in force then: the fork shape again.
  **NOTHING TRUNCATES, AND NOTHING EVER DID.** The requirement's one consumer
  was `code = (line.hsn_sac_code or "")[:max(required, len(code))]`, a slice
  whose length is the LARGER of the requirement and the code's own length — so
  it can never shorten anything. A 2-digit HSN at ₹10 crore came back as `99`,
  was filed as `99`, and appeared in no gap list. The code is filed exactly as
  recorded now (the notification sets a FLOOR, so a longer code is already
  compliant and truncating for real would file a number the client never
  issued) and the shortfall is REPORTED in `payload_gaps`, beside Table 12's
  unit gaps and for GST-29's reasons. **The digit check runs BEFORE the walk's
  `continue`**, which is the one place it must differ from the UQC gap: a line
  with no HSN is exactly what the requirement is about and is the line Table 12
  drops, so checking after the skip would report every shortfall except the
  complete absence.
  **AND THE COUNT WAS A CHARACTER COUNT.** `problem_with` answered `len(clean)`
  to a question about DIGITS with no numeric test anywhere in the module, so
  `'SAC998'` satisfied a six-digit requirement and `'ABCD'` a four-digit one —
  the gap list was silent about exactly the codes the portal refuses.
  `hsn_digits.is_a_code` is the rule, from two primary sources now committed
  under `docs/compliance/sources/e-invoice/`: the IRP states the field's own
  expression as `HSN_Code ^[0-9]*$` and refuses anything else as error
  **2176**. **The regex, never `str.isdigit`** — Python calls `'²'` and the
  fullwidth digits digits and `^[0-9]*$` does not. **ASKED FIRST AND ASKED
  WHATEVER THE REQUIREMENT IS**: first because a code that is not a number
  cannot be counted (and once past it, `len` IS the digit count, which is why
  nothing counts them a second way), and unconditionally because a nil
  requirement makes the code OPTIONAL and does not make a wrong one
  acceptable — Table 12 files what is recorded, so a junk code on a B2C line
  still comes back as 2176. An ABSENT code under a nil requirement is what the
  notification permits and is the one thing that stays silent.
  The IRP's own limb is DIFFERENT and lives in `domain/gst/irp_validations`:
  at least FOUR digits on every item of every document it registers, whatever
  the notification's own requirement is. Two rules about one field, and neither
  is the other.
  **`GAP_HSN_NOT_A_CODE` is its own kind**, not a long `GAP_HSN_DIGITS`,
  because a screen filtering on the kind would title an eight-character
  non-code "below requirement". Nothing refuses at the API DOOR, the `uqc`
  carve-out: a line may carry a code typed before there was anything to check
  it, and a 422 there makes the row un-editable for any unrelated change.
  **THE SPLIT IS PER SUPPLY, NOT PER RETURN** — resolved inside the loop from
  the invoice's own category against `classifier.B2B_SECTION_CATEGORIES`
  (derived, not listed, because B2C is the side where the requirement falls
  away and a miss would UNDER-report).
  **AGGREGATE TURNOVER IS THE PRECEDING YEAR'S, IS RECORDED, AND `None` IS A
  THIRD STATE.** CGST §2(6) is computed on the PAN, ALL-INDIA, and includes
  exempt supplies, exports and inter-State supplies between distinct persons —
  a second registration's supplies count toward it — so it cannot be derived
  from one client's books, and it is NOT `tax_audits.turnover_paise` (§44AB
  turnover, different figure, different year). Migration 401's
  `client_gst_turnover` holds it per financial year (a single column on
  `clients` would be overwritten each April and re-tier every belated return),
  keyed on the year the figure MEASURES with the preceding-year hop in
  `governing_financial_year`. `lib/data/gst.ts` used to send
  `aggregate_turnover_paise: 0`, which is a REAL turnover meaning "below every
  threshold" — so every client was silently told HSN was optional and no gap
  was ever reported. It sends nothing now and the service resolves it; `None`
  takes the STRICTEST reading and says so, because under-reporting the
  requirement files a return the portal rejects while over-reporting costs a
  glance. The unrecorded sentence is emitted ONCE and only where a shortfall
  was actually found — a client whose codes are all six digits owes nothing
  whatever their turnover was. ⚠️ Both tables are `[S]`-graded (egress is
  refused here) and every threshold and digit count is pinned exactly by
  `tests/test_how_many_hsn_digits_a_return_must_carry.py`.

- **TABLE 13 DECLARES SERIAL RANGES, AND THE BUILDER EMITTED A COUNT WITH NO
  RANGE AT ALL** (GST-18). `_build_doc_summary` put `{"num": count, "cancel":
  0, "net_issue": count}` on every nature, and three of those four were wrong:
  **`num` is the ROW'S INDEX** within the nature (Table 13 allows several
  ranges per nature and numbers them 1, 2, 3), the COUNT is `totnum` and
  `grep totnum apps/api` was EMPTY, **`from` and `to` were absent entirely** —
  they are the point of the table, which is how CGST Rule 46(b)'s "consecutive
  serial number ... unique for a financial year" is checked against the
  invoices actually filed — and **`cancel` was a literal 0** for every client
  and every period, so a cancelled invoice, exactly what this table exists to
  declare, never appeared. `domain/gst/document_series.py` is the authority.
  **ONE ROW PER CONTIGUOUS RUN, WHICH IS WHAT MAKES THE FIGURES AGREE.** Rule
  46(b) expressly allows "one or multiple series", so a client running
  INV/2026-27/nnn beside EXP/2026-27/nnn in one month has two ranges and a
  single row spanning lowest to highest would contain documents from neither
  and a `totnum` that does not match its own span. Documents are grouped by
  SERIES HEAD (`invoice_series.split_number`, the same split the numbering
  suggestion and the sequence-break warning use) and then by contiguous run, so
  **`totnum == to - from + 1` is an INVARIANT rather than a hope** and a gap
  becomes two rows — honest about a number nobody issued, and the several-rows
  shape is what Table 13 is for. The number travels **AS WRITTEN**: a series
  padded to four digits writes `0007`, and rejoining head + `str(seq)` would
  declare a number appearing on no document. A number `split_number` cannot
  read is its own range of one, `from == to`, rather than being given a
  position in somebody's series.
  **CANCELLED DOCUMENTS ARE AN INPUT, NOT A DERIVATION**, which is why `cancel`
  was hard-coded in the first place: `gst_return_service._posted_sales` feeds
  the builder posted invoices and issued notes, and a cancelled one is by
  construction neither. `_cancelled_sales` reads them (`status = 'cancelled'`,
  through `_opening.without_carried_over` like every other return reader), and
  a caller supplying NONE gets `cancel = 0` with the return NAMING that nobody
  looked — `GAP_CANCELLED_NOT_READ`. A nil meaning "we did not look" is not a
  nil meaning "there were none", the `table_4a_gaps` discipline.
  **`REPORTED_NOT_WITHHELD` / `withheld_gaps` is the builder's own
  distinction**, and it exists because three test modules were each about to
  keep a private list of "gap kinds that are not my question". A gap naming a
  document held OUT of the payload is a different thing from one REPORTING a
  particular the payload still carries (the HSN digits, the UQC, this
  cancelled count), and the module that owns the vocabulary is the only place
  that can stay right when a kind is added.

- **A UNIT QUANTITY CODE IS A CODE, NOT A WORD, and the one module that knew
  which codes exist had ZERO IMPORTERS.** `models/uqc.py` held CBIC's fixed
  44-code list and named, in its own docstring, every place it was meant to be
  used; three validators cited `VALID_UQC_CODES` in their COMMENTS and none
  imported it. So `gstr1_builder` put `line.unit` straight into Table 12's
  `uqc` and three things reached a return unremarked: **`'PIECES'`** where the
  code is `PCS`, **`None`** — a JSON null where the schema wants a string — and
  **10 BOX + 5 PCS summed to 15 and filed as BOX**, a quantity that is not a
  quantity of either. The same `public.tds_section_limits` shape: a module
  whose name reads like the authority and which nothing reads.
  `domain/gst/uqc.py` is the authority now, with the RULE over the list —
  `problem_with` is shaped like `gstin.problem_with` deliberately, one shape
  for "what is wrong with this identifier". It moved out of `models/` because
  that is the API boundary and a domain module importing from it is the wrong
  direction, the same reasoning that moved Schedule II Part C out of
  `routers/fixed_assets.py`; `models/uqc.py` re-exports.
  **NOTHING REFUSES, AND THAT IS GST-29's SPLIT APPLIED TO A DIFFERENT
  IDENTIFIER.** The carve-out the old validators recorded is still right — a
  product or a line may carry a pre-dropdown free-text unit (`HRS` for service
  hours), and refusing at the API boundary would make that row un-editable for
  any unrelated change. What was wrong was the conclusion drawn from it, *"the
  dropdown only offers valid UQC codes, so new data is compliant by
  construction"*, which is a claim about EVERY write door — and this codebase
  has found that claim false twice already. So the document is never refused
  and the RETURN reports, as `payload_gaps`, which the GSTR-1 screen already
  renders. The three answers are **NOT interchangeable** and a test says so:
  an absent unit cites Rule 46(h), a wrong one names the code it probably
  meant (`closest_code` is a suggestion and never a substitution, matched on
  the LABEL rather than by edit distance, which would pair `TON` with `TUB`),
  and a mixture names both units and says the quantity below is their sum.
  **THE FILED FIGURE IS NOT CHANGED.** Whether Table 12 may carry two rows for
  one HSN under different UQCs could not be checked — every `.gov.in` is
  refused at this environment's proxy — so the mixed case is REPORTED and the
  aggregation left alone, the `interest_on_rule_37_reversal` discipline: state
  the open question rather than answer it from memory. The real fix is the
  CA's anyway, since one HSN should have one unit.
  **AND NO FEEDER MAY INVENT A UNIT.** `GAP_UQC_NOT_RECORDED` was written,
  tested and UNREACHABLE from production: `gst_return_service` passed
  `r.get("unit") or "OTH"` and `routers/gst` `or "NOS"`, both valid codes, so
  an unrecorded unit arrived at the builder indistinguishable from a recorded
  one — and "NOS" is the worse invention, asserting the goods were counted in
  NUMBERS. Table 12's `uqc` is a string in the schema so something must be
  filed, and `OTH` (OTHERS) still is; what MOVED is where, to the one place
  the row is built, beside the gap naming the absence. The FILED value is
  unchanged. **And the mixed-unit sentence named the wrong unit**:
  `one_unit_for` returns them SORTED and the sentence interpolated `mixed[0]`
  while the row files the first unit SEEN, so it told the CA which unit was
  filed and was right only by coincidence — the fixture that pinned it built
  the two units in alphabetical order.
  **A GAP HAS TWO KINDS AND THE SERVER SAYS WHICH.** `REPORTED_NOT_WITHHELD`
  has been the builder's vocabulary since GST-18 and nothing carried it across
  the wire, so `Gstr1Findings` headed the whole list "Not declared in this
  return" — which the reported kinds' own reasons contradict ("Table 12 files
  the code exactly as recorded"). `stamp_withheld` answers per gap and the
  panel renders two groups; the browser keeps NO list of kinds, the Schedule
  III caption lesson, and an ABSENT `withheld` reads as withheld so a frontend
  ahead of its backend renders exactly as before. `gst_return_service`'s two
  quarterly caveats used to carry the literal kind `"REPORTED_NOT_WITHHELD"` —
  the NAME of the set, which is not a member of it, so `withheld_gaps`
  classified them as documents held out; they carry `GAP_RETURN_CAVEAT` now.
  **ALL SIX DOORS ASK THE AUTHORITY** — `ServiceCatalogueIn`/`UpdateIn`,
  `InvoiceLineIn`, `PurchaseBillLineIn`, `FirmHsnLibraryIn`/`UpdateIn` — and
  the last pair had **no validator at all**, which mattered most because
  `routers/hsn.py` serves that `uqc` as a HINT that pre-fills an invoice line,
  so a value typed there propagates. The guard derives the door list from the
  AST and checks PER CLASS, because a module-level walk passes when only one of
  a create/PATCH pair is guarded. **`apps/web/lib/constants/uqc.ts` is the
  keystroke mirror** — seven editors render their dropdown from it — pinned
  from the PYTHON side, the Schedule III caption lesson: a guard in `apps/web`
  asserting the browser against a copy of itself passes whenever both drift
  together. There is deliberately **no endpoint**: a 44-entry constant that
  moves by CBIC notification would be a Singapore-to-Mumbai round trip, and the
  parity test already prevents the drift an endpoint would.

- **An e-way bill's validity is arithmetic on the distance, and the distance is a
  field nobody used to ask for.** Rule 138(10) as amended by Notification
  94/2020-CT: one day per **200 km or part thereof**, or per **20 km** for Over
  Dimensional Cargo — and "one day" is **midnight** of the day following
  generation, per the Explanation, not a rolling 24 hours, so a bill raised at
  23:55 has five minutes of its first day left. `domain/gst/eway_validity.py`
  computes it; the Prepare screen now asks for distance, vehicle type and transport
  mode; `GET /api/eway-bill/records/{id}/validity` pre-fills the expiry, which used
  to default to TODAY. **The portal stays authoritative** — every answer carries
  `source`, a recorded date that disagrees is reported and never refused, and a
  missing distance returns a named gap rather than a guess. ⚠️ **The slabs are
  `[S]`-graded**, written from knowledge because this environment's proxy refuses
  every `.gov.in`; the pre-2021 slab was 100 km, so a misreading fails generous.
  Two deliberate refusals: the **20 km slab keys only on `vehicle_type =
  'over_dimensional'`** (the value the CHECK actually allows), and a
  `transport_mode = 'ship'` row takes the ordinary slab with a caveat, because the
  row cannot distinguish a multimodal ship LEG from a movement wholly by ship and
  the generous reading is the one that shows an expired bill as live.

## From CLAUDE.md section: Reporting performance — the rule, not a preference

**A LIVE E-WAY BILL SAYS WHEN IT LAPSES, AND THAT IS NOT A COMPLIANCE ROW**
(SALES-28's other half). `eway_validity` has computed Rule 138(10)'s answer
since SALES-28's first half and `/records/{id}/validity` served it — to somebody
who had already opened that one record. A bill that lapses while the lorry is
moving exposes the consignment to detention and seizure under CGST §129, and the
extension path (the proviso to Rule 138(10)) existed the whole time with nothing
to prompt it. `domain/gst/eway_expiry.py` is the rule and
`GET /api/eway-bill/expiring` serves it FIRM-WIDE through `effective_client_ids`
— None means firm-wide and an EMPTY set means nothing, never "no filter".
**NOTHING IS FILED FOR AN E-WAY BILL**, so it is its own panel above the
deadlines table rather than a `ComplianceEntry` in it: that shape carries a
`filing_status` and a Mark Filed action, and folding this in would mean
inventing a `compliance_type` and offering a button that means nothing. The same
reasoning that keeps the filing demo off the deadline list.
**THE RECORDED DATE WINS AND THE ANSWER SAYS WHICH IT USED** — NIC may know what
this cannot, a leg by ship or an extension already granted — and a computed date
is used only where the record carries none.
**MIDNIGHT, NOT A ROLLING DAY**: the Explanation to Rule 138(10) expires a day at
midnight, so a bill valid upto the 20th is good all of the 20th and
`expires_today` is its OWN bucket — the one a naive `<` reads as fine, and the
last chance to extend. A bill whose expiry cannot be told at all is LISTED as
undeterminable rather than dropped, the `table_4a_gaps` discipline. **The IRP and
EWB JSON payloads stay REFUSED with GST-32**, for the same document: a wrong
field NAME fails visibly at the portal, a misremembered field MEANING generates a
real document with wrong figures.

## From CLAUDE.md section: GSTR-2B reconciliation — the books are read in `apps/api`, and the answer is kept

- **§16(2)(aa) IS ASKED OF EACH DOCUMENT, AND RULE 36(4) WAS APPLIED TO A
  PER-HEAD SUM** (GST-19). `_apply_rule_36_4_cap` compared book IGST against 2B
  IGST and trimmed one to the other, so a month with one ₹18,000 bill the
  supplier never filed and another where 2B carried ₹18,000 MORE than the books
  **netted to zero, the cap never fired, and the return claimed credit on an
  invoice nobody furnished**. `domain/gst/rule_36_4.py` is the rule.
  **BOTH TESTS APPLY AND THE LOWER SURVIVES** — they are two conditions, not
  one rule with two implementations — so the pass can only ever withhold MORE,
  never release credit the aggregate cap held back. **It matches nothing**: the
  2B reconciliation (migration 340) has written `purchase_bill_id`,
  `match_status`, `itc_available` and `itc_unavailable_reason_code` on every
  row it matched since it was built and the return read none of them, and a
  second matcher would disagree with the reconciliation the CA is looking at.
  Rule 36(4)'s provisional buffer (20%, then 10%, then 5%) was withdrawn by
  Notification 40/2021-Central Tax w.e.f. 01-01-2022, when §16(2)(aa) came in —
  so there is no grace and the question stopped being "how much more than 2B"
  and became "which documents are in it".
  **SIX VERDICTS, AND NONE COLLAPSES INTO ANOTHER, because what the CA does
  next differs per verdict.** `not_in_2b` means chase the SUPPLIER;
  `blocked_by_2b` means the portal has ALREADY refused it (2B's `rsn` "P" is
  the place of supply, "C" a return furnished after §16(4)'s cut-off) so the
  action is to read the DOCUMENT — reading the second as the first sends a CA
  to phone somebody who has done nothing wrong, which is why the blocked rows
  had to stop being dropped in the query and are filtered a step later by
  `_2a_counting_towards_the_cap` instead. `self_assessed` is reverse charge,
  allowed in full and NAMED — §16(2)(aa) conditions the credit on a SUPPLIER's
  furnished invoice, and this tax is self-assessed and paid in cash, so 2B
  structurally cannot carry it and withholding it takes back credit already
  paid over; it is asked FIRST, before the key, because a §9(4) supply from an
  unregistered supplier has no 2B row by construction. `more_than_2b` caps PER
  HEAD and never on the total (a bill booked as IGST that the supplier filed as
  CGST+SGST is not a matching total, it is two wrong heads) and never caps a
  negative note UP: the rule withholds, it never grants.
  **`not_assessed` IS THE VERDICT THAT KEEPS THE OTHERS HONEST.**
  `purchase_bill_id` is written ONCE, at upload, against the bills that existed
  THEN — `read_book_bills` reads exactly that period's — so a bill entered on
  the 20th, after the month's 2B was reconciled on the 14th, carries no keyed
  row and is indistinguishable by the map alone from one the supplier never
  filed. The DIRECTION of the error decides it: withholding wrongly costs the
  client real money on a return they are about to file and is invisible, while
  allowing wrongly leaves the aggregate cap doing what it did before with a
  sentence saying to re-reconcile. The test is the bill's **`created_at`** against
  its period's own `reconciled_at` — `created_at` deliberately, because a
  payment allocation, a TDS correction and a status change all move
  `updated_at` without touching anything §16(2)(aa) matches on and would report
  most of a busy register as unexamined. `_header_row` **stamps
  `reconciled_at` itself** rather than leaving it to migration 341's `DEFAULT
  now()`, which fires against a real Postgres and against nothing else: without
  that, mock mode treats every bill as unexamined and the pass is inert there
  while it fires in production, which is a statutory figure differing between
  the two.
  **A DOCUMENT WITH NO CREDIT LEFT IS NOT A RULE 36(4) QUESTION**: §17(5)
  blocked tax is subtracted before a document reaches the module, so a bill
  whose whole tax is blocked has nothing to withhold and must not appear in the
  withheld list with ₹0 against it — the one screen whose value is that every
  row needs an action. An **import of goods** and a **bank charge carrying GST**
  keep the aggregate treatment and are NAMED: neither has a supplier invoice to
  key a 2B row on (2B communicates an import in its own `impg` section), and the
  import figure is added back before the two answers are compared or the
  per-document total would be lower every time simply by being short of it.
  **Only the WITHHELD documents travel** on the payload — a month's whole
  purchase register for an answer that is a handful of rows would be a read
  proportional to transaction volume — and the GSTR-3B screen renders them with
  the served sentence rather than composing its own.

- **RULE 43 IS BUILT AND RULE 42 IS NOT, and the missing input was never the
  arithmetic** (FA-19). A client making both taxable and exempt supplies
  reverses one-sixtieth of the credit on each COMMON capital good every month
  for five years, apportioned by exempt turnover — Tc, Tm, Tr, Te, per head
  because Rule 43(2) says so. `domain/gst/rule_43.py` is the authority,
  `services/gst_rule_43_service.py` fetches its two inputs, and
  `GET /api/gst-workspace/itc/rule-43` serves the working beside the return.
  **The one fact nobody held was which of Rule 43(1)'s three uses an asset is
  put to** — the tax split has been on `fixed_assets` since migration 343 —
  so migration 372 adds `rule_43_use`, nullable, no default, CHECKed to
  `common | exclusively_exempt | exclusively_taxable`. **A NULL is REFUSED and
  NAMED, never assumed**, because guessing is unsafe in both directions:
  assuming common reverses credit §16(1) gives, assuming exclusively taxable
  leaves Te undeclared with Rule 43(1)(h) interest running on it. Same shape as
  `vendors.msme_status`. **E and F come from
  `gst_return_service.outward_turnover`**, which builds the outward side
  through the same `_outward_transactions` `gstr3b_from_books` uses — extracted
  rather than copied, so a working and its return cannot disagree about what
  was supplied. E is nil-rated + exempt + non-GST (§2(47) reading in §2(78)) and
  **deliberately NOT zero-rated** (IGST §16(1) allows that credit and 43(1)(b)
  names such supplies as other than exempted); F is all four (§2(112)).
  ⚠️ **An OUTWARD supply the RECIPIENT pays tax on is missing from F**, because
  `compute_gstr3b` accumulates a taxable supply only `if not
  s.is_reverse_charge` — right for Table 3.1(a) and wrong for §2(112), which
  excludes only INWARD reverse-charge supplies. A GTA's or an advocate's own
  outward supplies are their turnover. A smaller F makes Te LARGER, which is
  the safe direction, and the answer SAYS so for the period rather than being
  silently generous. **Te
  rounds UP** — it is added to output tax and 43(1)(h) charges interest, so
  understating it is a shortfall that grows; the division happens ONCE on the
  aggregate, not per asset. **It POSTS NOTHING**: the CA raises the reversal
  journal and registers it with ground `rule_43`, which
  `itc_register_service` has accepted since migration 362 and nothing could
  produce a figure for. Three things are named as not modelled rather than
  approximated: the (a)→(c) and (b)→(c) transitions (the provisos' five
  percentage points per quarter need a HISTORY of the classification, which is
  a second table), the Explanation to 43(1)(g)'s excise exclusions, and Rule 42
  itself — the inputs-and-input-services twin, still absent.

- **THE MAIN GSTR-1 BUILD CARRIES THE AMENDMENTS THE PERIOD OWES, AND THE DEDUPE IS WHAT MAKES DEFAULT-ON SAFE** (gst-33). CGST s.37: a filed GSTR-1 is never revised, so a correction to an earlier period is declared in a LATER return's Tables 9A (b2ba/b2cla/expa), 9C (cdnra/cdnura) and 10 (b2csa). They came from a second route into a second file, so the file the GSTR-1 screen produced by default was the one WITHOUT them. The audit's fix, "include them by default", is unsound alone: `outstanding_amendments` diffs earlier filed returns against the books and nothing records a correction declared in a later return, so default-on re-proposes the same correction every month (a scratch test proved it before any code). `gst_amendment_service.declared_entries` (the inverse of `group_amendments`) and `split_already_declared` read what SUBMITTED later returns already declared and remove it, reported as `already_declared`. `POST /api/gst/gstr1/from-books` takes `include_amendments` (default true) and shares `_with_outstanding_amendments` with the with-amendments route; the payload carries an `amendments` block. **A failure computing them is an HTTP 500 naming the switch, never a silent plain build**, because a file quietly lacking the corrections is the defect. Both screens render `components/gst/Gstr1Amendments.tsx` (one component, like `Gstr1Findings`); an absent block renders nothing and an absent count is never shown as 0. A document cancelled after filing has no single right correction and is listed as a decision, not put in the file. Nothing is sent to a portal.

- **A GSTR-2B FILE SAYS WHICH MONTH IT IS FOR AND WHOSE IT IS, AND THE UPLOAD BELIEVES THE FILE** (gst-09). The 2B tab asked for a typed MMYYYY and a pasted JSON although `data.rtnprd` and `data.gstin` were both parsed and used for nothing. Worse, a typed month that disagreed with the file was WARNED about and the documents were then written under the TYPED month, replacing that month's correct reconciliation with another month's documents matched against the wrong month's bills (the Rule 36(4) working and the s.16(2)(aa) credit then came from the wrong file); and the GSTIN was compared with nothing. `domain/gst/gstr2b_intake.assess` is the rule: the file decides the month and a typed one is only a check, a disagreement refuses the file and picks NEITHER (`SalesInvoiceIn`'s shape), the file's GSTIN must be one the client holds (`registrations.resolve`'s refusal, never the primary), a file with no GSTIN or no month is refused, and with no registrations supplied (mock mode) the answer says 'not checked' and never 'matched'. `POST /gstr2b/upload` 422s before any read or write and **keeps no copy of a refused file** (it is another taxpayer's supplier list); `POST /gstr2b/inspect` (gst:compute, writes nothing) asks the same question through the same `_2b_intake` so the screen can say it beside the file name, and a test asserts the two agree. The writing service asks the period half again, because a check on one door is one caller from being none. The screen is a file chooser with drag and drop: no period box, no textarea, the upload enabled only for a file the server cleared, the request carrying no period. The page's own `apiFetch` read `res.json()` for every status, so every 422 on it showed 'Upload failed'; it goes through `errorMessage` and joins that guard's list. **Deliberately not done**: the portal's Excel download (its layout could not be read here); splitting bills by registration (open work: attributing each document to a registration), so a client with several registrations keeps ONE reconciliation per month and a second registration's 2B matches against all the client's bills and REPLACES the first's, named on every answer as `registration_caveat` rather than refused, since refusing would make such a client impossible to reconcile. The 2B tab was driven once in Chromium against the real API on 8-9 October 2026 (same, newer and older download, PRE-A-001); the rest is held by source guards.

- **A 2B FILE IS ROUTED BY THE GSTIN INSIDE IT, A PROBABLE MATCH IS ONLY EVER A SUGGESTION, A DRAFT BILL IS ADDRESSED BY KEY AND RATED FROM THE FILE, AND THE s.16(4) RADAR NEVER RESTATES THE DATE** (gst-10, gst-12, gst-13, gst-15). Four things sat on the GSTR-2B reconciliation and each was a place a CA had to do by hand what the file or the books already said.
  **Routing (gst-10).** A 2B was reconciled one client at a time with the CA choosing the client BEFORE the file, although `data.gstin` says whose it is. `POST /api/gst-workspace/gstr2b/bulk` takes files and nothing else - no client, no month - and answers one row per file (`reconciled`, `unmatched_gstin`, `ambiguous_gstin`, `refused`, `unreadable`, `failed`). `domain/gst/gstr2b_routing.route` matches the GSTIN against `clients.gstin` and `client_gst_registrations` of the CALLER'S FIRM, narrowed to `effective_client_ids` (None every client, a set exactly those, an EMPTY set nothing and never 'no filter'). **Nothing defaults**: a GSTIN no client holds is reported and not stored even where the firm has one client; a GSTIN two clients hold is ambiguous and goes to neither; a client outside the caller's book reads in the SAME words as a GSTIN nobody holds, because a different sentence would be an oracle for another person's client (`assert_client_access` answers 404 for the same reason); and `can_access_client` is asked again per routed client. It is the single upload repeated, not a second reconciler - `gstr2b_intake.assess`, `reconcile_2b`, and `keep_upload` / `log_discrepancies`, extracted from the single route so the kept file has one writer. Two files for one client and month in one request reconcile the first and REFUSE the second naming it; across requests every result carries `replaced_earlier`, so a stale download among sixty cannot overwrite a newer one without a word. The answer is a summary per file, never the matches. A request takes five files and the screen sends one at a time (`lib/api` aborts at 45 seconds and never retries; there is no background job to lose on a restart). **Not done**: no job queue, no cross-request refusal of a replace, no Excel, no per-registration split of the client's bills (the `registration_caveat` still applies), and no read-back of what a drop did after the screen is closed.
  **Probable matches (gst-12).** A bill under a GSTIN with one character wrong came back as two unrelated rows and nothing said they were one invoice. `domain/gst/itc_probable.suggest` reads the two leftover lists and offers pairs of three kinds - same folded number under a different or absent GSTIN, same GSTIN with a number a typing slip away, same supplier/day/exact amounts with an unrelated number - each needing a second and usually a third fact (INV-41 and INV-42 are one digit apart and are not the same invoice), graded `strong` or `possible` with the sentences that earned it, never a percentage. **It is computed AFTER the rows are written and persisted nowhere**: `reconcile` is untouched and still has no tolerance (a test asserts the matcher neither imports the module nor mentions its band), the stored row keeps `purchase_bill_id` empty, and `rule_36_4` goes on withholding the credit until the CA corrects the bill and re-runs. The finding's 'off by Rs 1' case is deliberately not a kind: same GSTIN and number is already ONE `amount_mismatch` row. **Not done**: no one-to-one assignment (picking a winner is the guess this exists to avoid), no re-run from stored rows, and no suggestion on a reopened tab.
  **Draft bill from a 2B document (gst-13).** `POST /api/purchase-bills/from-2b` takes the document's ADDRESS (client, period, section, type, supplier GSTIN, number) and no figure; the figures come off the stored `gstr2a_records` row and the rates off the kept uploaded file, whose document must reproduce the stored totals to the paisa or the draft is refused with 'upload the file again'. The parser now keeps each rate line (`RateLine`) and 2B's `rev` flag because tax divided by taxable would give 11.5% for a 5% line and an 18% line. The lines go through the ONE bill engine, so the result is `draft`: no journal, no credit, and `read_book_bills` counts only received bills, so the row stays `missing_in_books` until the CA receives the bill and the next reconciliation matches it BY KEY. **There is deliberately no stored link** - writing `purchase_bill_id` at draft time would make a bill nobody has received read as matched to `status_for_bills` and `rule_36_4`. `bill_no` is the supplier's own number exactly as filed. Refused, each with its own sentence: reverse charge (whether s.9(3)/(4) applies is the CA's answer), amendment, credit note, debit note, import, a line with no stated rate, no vendor with that GSTIN, two live vendors with it, a document already matched. `agrees_with_2b` names every head where the engine's arithmetic differs from the supplier's (a paisa of rounding, or a vendor recorded in another State) and adjusts neither. **Not done**: no vendor is created, no HSN/unit/product or s.17(5) decision is invented, and the receive path is untouched.
  **The s.16(4) radar (gst-15).** `correction_window` had answered 'when does this year close' since GST-09 and nothing laid it against the credit. `GET /api/gst-workspace/itc/time-bar` lists, nearest lapse first, the bills the per-document s.16(2)(aa) pass WITHHOLDS (`not_in_2b`, or the excess of `more_than_2b`, net of s.17(5)) and the 2B documents the books have no bill for, each with the date from `correction_window.window_for` - **the date is never restated** (a test asserts the module calls neither `november_30_cutoff` nor `date(y, 11, 30)`, because `november_30_cutoff` alone tells a CA a window is open when an early GSTR-9 has shut it) - and **the year is the INVOICE'S**, so a 31 March bill and a 1 April bill lapse a year apart. What is not a deadline is said, not hidden: a bill the portal itself marked ITC-unavailable is counted with no date, a bill recorded after its month's reconciliation is named as needing a re-run, and a month with no 2B reconciled is listed as a MONTH with its own date and is not judged - an empty list is never a clean bill of health. A closed window is still reported. Verdicts come from the same `rule_36_4.assess` and the return's own helpers, asked per reconciled month. **Not done**: the read is bounded by the window (financial years closed within sixty days, at most two, months whose 2B exists) but is still proportional to those months' bills - a SQL function is the reporting rule's preferred shape and would put s.16(2)(aa) in two languages, so it is the next step, not this one; matching stays per month (a late-filed April invoice can read as two rows, and the answer says so); the 14th-of-the-next-month 2B generation day is `[S]`.

- **THE GSTR-3B IS TIED OUT AGAINST THE GSTR-1 THAT WAS FILED, AND A NIL THERE SAYS WHICH KIND** (GST-07). From the July 2025 tax period the portal fills Table 3.1 from the period's GSTR-1 and locks it (GSTN advisory 606), so an invoice raised after the GSTR-1 was filed makes the books-built 3B differ from the one the portal will show. `domain/gst/gstr1_3b_tie_out.py` compares the two in exact paise and attributes a difference to a cause (documents changed since filing, via the same `gst_exception_service` read the Amendments tab uses; bank receipts and asset disposals no GSTR-1 can carry; builder classification). **It reports and adjusts neither return.** 3.1(a) and 3.1(b) are compared TOGETHER because a note carries no parent-treatment marker and the portal's deemed-export routing could not be confirmed. **NOT FILED is its own state and carries no figures**: a period with nothing filed (or only a draft) has nothing to be equal to, which is not the same as agreeing. The filed return's rupee figures come back through `gstr9_builder.paise_of`, never `int(v * 100)`. Named as not compared: outward reverse-charge, amendment tables in the filed payload, GSTR-1A/IFF. The July 2025 lock is a `[S]` named constant, `VERIFIED` False. It rides on `gstr3b_from_books` as `gstr1_tie_out` and both GSTR-3B screens render it through `Gstr3bFindings`.

- **FORM GST ITC-04 IS DERIVED FROM THE JOB-WORK CHALLANS, GOODS COME BACK IN LOTS, AND THE PERIOD IS NOT CHOSEN** (GST-30, migration 462). `itc_04_period` used to return a refusal and stop, and a challan held ONE date, `received_back_on`, for the whole of its goods coming back, so 'one challan sent, part returned' could not be recorded. `delivery_challan_returns` holds one row per lot against the challan LINE (quantity returned, date, the job worker's own challan and nature of work as nullable no-default columns, quantity lost or wasted) and **stores no balance** (what is outstanding is the line's quantity less its returns, derived on every read, migration 278's reasoning). `domain/gst/itc_04.py` is the authority for Table 4, Table 5A (one row per return against the ORIGINAL challan, which may belong to an earlier period) and per-line balances. **THE s.143 CLOCK IS THE CHALLAN'S OWN**: a part return reduces what is left to be deemed supplied and never moves the day the goods left, which is the day s.143(3) deems them supplied; the figure at stake is the balance's share, rounded UP. **THE CADENCE IS NOT CHOSEN**: Rule 45(3) turns on the principal's own preceding-year turnover and a limit this environment could not confirm, so `windows_for` lists every reading's windows (quarterly, half-yearly, annual) with their own due dates and none is `chosen`; a turnover on record is context only; all `[S]`, `VERIFIED` False. **Lost or wasted quantity is recorded and NEVER subtracted from the balance** (the larger balance cannot hide a deemed supply), so a challan with waste never stamps itself received back. Tables 5B/5C, the tax on a deemed supply, the moulds-and-dies type and the form's numbering are NAMED on every answer. `POST /api/sales-cycle/challans/{id}/returns` refuses (never clamps) more than was sent, an impossible date, a draft/cancelled/non-job-work/already-received-back challan, and a line this client does not hold (one fixed 404; the path's challan must be the line's own); the last lot stamps `received_back_on` through the ONE existing write, `record_goods_back`. Migration 462's rollback REFUSES while a challan is part returned. **392's rollback test now rolls 462 back first**, because 462's table holds foreign keys into both of 392's. Nothing is filed and nothing is posted.
