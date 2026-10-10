# Design record: Sales and purchase documents and cycles, templates, supplier master, ledger drill-through

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **THE DEMO SEEDER HAS BEEN RUN OVER A REAL DATABASE, AND EVERY DEFECT IT EXPOSED IS A RULE NOW** (PRE-A-004, 9-10-2026). Migrated Postgres, PostgREST and the real app, 8 clients, 1,770 calls, 137 s: Verify Books reports no critical finding, Schedule III balances for all eight, GSTR-1 builds with no validation error in 84 client-periods, and the construction client shows two projects under construction in both MCA schedules (`from_bill` tranches, Dr CWIP / Cr Purchases, services only so no stock moves). What it exposed, each fixed with a test: the receivables sub-ledger check ignored a part-paid invoice; the orphan-money-journal check judged payroll and bank-queue journals it cannot tie to a document table (it judges a money journal only when it knows the table its document would be in); the GSTR-1 validator demanded CGST = SGST although `compute_line_gst` halves a line's tax with CGST the floor and SGST the remainder, so a document's SGST sits up to one paisa per LINE above its CGST (CGST Act s.9(1): the same rate on each half), and the validator now allows exactly that gap, `ODD_PAISA_PER_LINE` times the lines the figures were summed over, and nothing wider (`[S]`: whether the portal accepts unequal halves could not be confirmed here, and if it does not it is the engine's split that must change and not the validator); `POST /api/clients` and `POST /api/banking/rules` sent a null over a column the database defaults; generating the obligations of an ITR, TDS or payroll engagement deleted the client's GST rows; and the Schedule III balance sheet dropped the Capital Work-in-Progress caption. The seeder now writes stock that never goes below nil, tax actually withheld under a TAN, an engagement per client with the obligations of the books' year, and a matching rule per bank-queue line. Not done, and named in PRE-A-004: TDS challans, PF/ESIC codes, practice and ITR data, partner remuneration and a composition or GSTR-8 client are not seeded; the seeded returns are never saved or filed; the books are FY 2025-26, so every seeded obligation is overdue on 1 November 2026 (owner decision); bank ledgers are negative on 6 of 8 clients at 31-03-2026 (owner-gated); no screen was opened in a browser; live seeding was not run.

- **A TEMPLATE CHANGES THE LAYOUT AND NEVER THE PARTICULARS, AND THE
  PRACTICE'S TEMPLATE REACHES THE PRACTICE'S OWN DOCUMENT ONLY** (SALES-13).
  `invoice_templates` and `email_templates` (migration 126) have been written
  by two full Settings screens since the module was built and **nothing in
  `apps/api` read a single column of either** — a Partner set the logo centred
  and the signature left, marked it default, and every PDF came out logo-left
  signature-right; rewrote the engagement email and the product sent the stock
  one. `domain/branding/invoice_layout.py` and
  `domain/branding/email_template.py` are the authorities.
  **CGST Rule 46 lists what a tax invoice must CONTAIN**, so a layout picker
  that could remove one would let a CA issue a document that is not a tax
  invoice. Every field moves where something sits or how much room it takes;
  the tagline is the only thing a header style removes and the `detailed`
  footer only ADDS. `signature_placement = 'none'` looks like the exception
  and is not — **Rule 46's FIRST PROVISO** dispenses with the signature for an
  invoice digitally signed under the IT Act 2000 — so it is honoured and
  `RULE_46_Q_NOTE` travels with the template to the screen, beside
  `LAYOUT_NEVER_CHANGES_PARTICULARS`, which is on EVERY layout because a CA
  choosing `minimal` needs to know it is not dropping the HSN. An unknown
  value falls back to migration 126's own default rather than raising: the row
  came through a validating door behind a CHECK, so an unknown value means the
  vocabulary MOVED, and refusing to produce an invoice over a layout
  preference is the wrong direction. **`build_sales_invoice_pdf` takes no
  `layout` and no `branding`** — the practice's signature placement on a
  document its client issues to a stranger is the confusion its own docstring
  already refuses the UPI id for.
  **THE EMAIL CONTRACT IS MEASURED AT THE SENDER, AND ONLY ONE OF THE FOUR
  KINDS HAS A LIVE MAIL.** `engagement` is wired (the practice IS the sender);
  `invoice` has no fee-invoice email path at all, `reminder`'s
  `send_compliance_due_soon` is written and has NO CALLER, and a document
  request sends nothing — three DIFFERENT reasons, served as
  `status_by_kind` and rendered where the CA types, because four kinds offered
  as equals with three inert is the `BrowserOnlyNotice` shape. `FIELDS_BY_KIND`
  holds only the live kind: **`{{financial_year}}` is NOT available on an
  engagement mail** because `public.engagements` (migration 115) has no such
  column, and the shipped default lost it — a default a CA presses Reset for
  must be one the door accepts. **An unfillable field is refused where it is
  TYPED, never blanked where it is SENT**, because by then there is nobody to
  tell; an unknown field and an unfillable one get different sentences; and
  `render` REFUSES rather than leaving a hole, so the built-in wording goes out
  instead. A kind with no live mail refuses no field — there is nothing to be
  unfilled by a mail nobody sends.
  **THE TWO CUSTOMER-FACING MAILS NAME THE CLIENT** (no finding; found here).
  The sales-invoice send and the payment reminder both carry a CLIENT's
  invoice to that client's own customer and both signed with the PRACTICE's
  name — "Invoice INV/001 from Sharma & Co" to somebody who bought goods from
  Acme Traders. They read the client's `legal_name` then `client_name`, the
  same preference `_client_party(legal_name_first=True)` applies to the very
  document attached, falling back to a neutral word and never to the
  practice's. ⚠️ The headline test was VACUOUS at first: reportlab stamps a
  creation date and document id on every render, so two identical PDFs differ
  — `rl_config.invariant` pins it and a premise test asserts two identical
  renders are byte-identical.

- **THE SALES CYCLE BEGINS BEFORE THE TAX INVOICE, AND ONLY ONE OF THE FOUR
  DOCUMENTS IS THE ACT'S** (SALES-21, migration 392). A client quotes, takes an
  order, delivers against it and bills afterwards; the product started at the
  invoice, so a CA either raised it EARLY — declaring a supply that had not
  happened and paying tax on it a month before the money arrived — or kept the
  quotation in a spreadsheet and re-typed every line when it converted.
  `domain/sales/order_cycle.py` is the commercial chain and
  `domain/gst/delivery_challan.py` is CGST Rule 55; the service, the router and
  the screen decide nothing either of them decides.
  **A quotation, a proforma invoice and a sales order are COMMERCIAL papers the
  Act does not know** — CGST §7 charges a SUPPLY and an offer is not one — so
  none of the six tables carries a `journal_entry_id`, nothing posts, nothing
  moves stock, and a test asserts no return builder reads any of them. **The
  proforma is the trap**: it looks like an invoice, is often numbered like one,
  and a GSTR-1 that picked one up would declare a supply that never happened.
  **It is never numbered from the tax-invoice series** — Rule 46(b) requires
  that series to be CONSECUTIVE and unique for the FY, so consuming a number
  for a document that may never become a supply puts a permanent gap in it and
  reusing the number later puts two documents on one. `series_kind_of` gives
  each kind its own; uniqueness is per client PER KIND, so a quotation and a
  proforma may share a number and two quotations may not.
  **A DELIVERY CHALLAN IS THE ACT'S, AND TWO OF ITS REASONS START A CLOCK
  WHOSE EXPIRY IS A DEEMED SUPPLY.** §143(3) deems inputs not received back
  within ONE YEAR to have been supplied to the job worker **on the day they
  were sent out** — so the tax falls due in a return already filed, with
  §50(1) interest from that return's own due date — and §143(4) is the same at
  THREE years for capital goods; §31(7) gives goods sent on approval SIX
  MONTHS from removal. Neither clock is visible in any ledger (the goods left,
  nothing was billed, no journal moved), so the challan is the only document
  either can be computed from, which is the point of the module rather than a
  convenience. **`goods_kind` is nullable with NO default and is REFUSED,
  never guessed**: defaulting to inputs reports a deemed supply two years
  early and defaulting to capital goods hides one for two years, and moulds,
  dies, jigs, fixtures and tools are outside both (second proviso to §143(1)) —
  named as its own answer, because "no clock" and "a clock nobody computed"
  must not look the same on a screen. An extension under the proviso is
  RECORDED and honoured only where it is LATER than the statutory date. A
  month-end deadline walks BACK to the month's last day (31 August plus six
  months is 28 February), never forward, because forward is a day late on a
  deemed supply.
  **Rule 55(1)'s nine clauses are checked and TWO ARE CONDITIONAL**: (vii) tax
  rate and amount only "where the transportation is for supply to the
  consignee" — so a job-work despatch carries none, and the service zeroes the
  rate rather than asking the caller to remember — and (viii) place of supply
  only on an inter-State movement. Rule 55(2)'s three legends are printed
  verbatim because the rule prescribes the WORDS. **What an order still has
  open is DERIVED, never stored** (migration 278's reasoning applied to a
  quantity), from challan lines read `.in_` over THIS order's line ids and
  their parents' statuses — a cancelled challan has delivered nothing.
  Over-delivery is REFUSED, never clamped. Three things are named rather than
  guessed: **ITC-04's periodicity** (Rule 45(3) turns on the principal's own
  preceding-year turnover, which no column holds, so both readings are shown
  and neither chosen), **what has been INVOICED against an order** (an invoice
  line carries no link back to an order line, so the figure is honestly zero
  rather than a description match), and Rule 55(5)'s four steps, whose gaps
  are reported. ⚠️ Every period and every clause of Rule 55 is `[S]`-graded and
  pinned by a test — egress is refused here — and `compute_line_gst` MOVED to
  `domain/sales/line_tax.py` with `routers/sales_invoices` re-exporting it, so
  `shared/gst-parity-vectors.json` still pins the one implementation.

- **AN IMPORT OF GOODS IS PAID FOR TWICE AND ONLY ONE OF THEM IS THE SUPPLIER'S**
  (PUR-18, migration 389). IGST on imported goods is not charged by the
  supplier: IGST §5(1)'s proviso puts the levy under Customs Tariff Act §3(7),
  collected under the Customs Act, so it is paid to CUSTOMS against a **Bill of
  Entry** — often the largest single ITC item of an importer's month. This
  product had no such document, so putting it on the vendor's bill overstated
  Trade Payables by the whole of it and leaving it off lost the credit, while
  GSTR-3B Table **4(A)(1) filed NIL** against a GSTR-2B whose own `impg`
  section shows the document. `domain/gst/bill_of_entry.py` is the rule.
  **THE ASSESSMENT IS NOT ONE FIGURE.** CGST §2(62)(a) puts "the integrated
  goods and services tax charged on import of goods" in INPUT TAX and Rule
  36(1)(d) makes the bill of entry the document it rests on; **basic customs
  duty and the social welfare surcharge are recoverable from nobody**, so AS-2
  paragraph 6 makes them COST — the same sentence that keeps blocked §17(5) GST
  in the cost of goods (INV-05a), and the blocked part of the import's own tax
  goes the same way. Treating the assessment as one figure claims credit that
  does not exist. **`ImportOfGoods` IS ITS OWN TYPE, NOT A FLAG ON
  `PurchaseTransaction`**, and it has no `is_reverse_charge` and no CGST or
  SGST field: reverse-charge tax is SELF-assessed and creates a Table 3.1(d)
  liability, this tax was collected by customs and creates none, and IGST §7(2)
  makes an import inter-state so no other head can arise. A flag beside
  `is_import_of_services` would invite the next reader to set
  `is_reverse_charge` too — every other import is — and declare a liability the
  client does not owe. **The journal touches NO accounts payable**: customs is
  owed, not the supplier. **IMPG is capped LAST** of the five 4(A) rows, because
  the two reverse-charge rows carry tax already paid in cash that Rule 36(4)
  cannot reach, while import credit rides inside the cap (2B communicates it in
  its own section). Only `status = 'posted'` documents reach the return — a
  draft has no journal, and that gap is the books-vs-ledger difference the
  reconciliation exists to catch. **4(A)(4) ISD is now the ONLY named 4(A)
  gap.** Four refusals are recorded rather than guessed: deferred payment of
  duty (Customs Act §47(2) proviso), a §27 refund, the duty is **not
  apportioned into stock cost** (the basis is INV-05's open half and an owner
  decision), and Rule 46(h)'s UQC has no line detail to come from. The seeded
  `Customs Duty` account is code **5022** with subtype `Cost of Materials` —
  both load-bearing: 5021 is Depreciation Expense and `ON CONFLICT DO NOTHING`
  would have skipped the insert silently, and `schedule_iii.pl_bucket` has no
  entry for `Direct Expense`, which is why migration 197 moved 5000 and 5001
  off it.

- **A REVERSE-CHARGE PURCHASE OWES TWO DOCUMENTS AND THEY ARE NOT ONE RULE WITH
  TWO NAMES** (PUR-19, migration 388). The reverse-charge ACCOUNTING was
  complete — the tax kept out of what the vendor is owed, the liability
  self-accounted, GSTR-3B declaring it — and the product produced neither
  document the CGST Act makes the RECIPIENT issue. **§31(3)(f) reaches only a
  supply received from a supplier who is NOT REGISTERED; §31(3)(g) reaches
  EVERY §9(3)/(4) payment**, registered supplier or not — so a payment to a
  registered goods transport agency owes a voucher and owes no self-invoice,
  and asking the registration question in `payment_voucher_due` would import
  (f)'s limb into a section that does not carry it. The self-invoice is not
  paperwork: it is the document the input credit RESTS on (Rule 36(1)(b) with
  §16(2)(a)). `domain/gst/rcm_documents.py` is the authority and decides all of
  it; the router and the screen decide nothing.
  **REGISTRATION HAS THREE STATES AND THE THIRD IS REFUSED, NOT GUESSED.** A
  valid GSTIN on the vendor IS the registration — read through
  `domain/gst/gstin.problem_with`, so a malformed one reports itself instead of
  being read as registered — `vendors.gst_registration_status` answers it where
  there is no GSTIN, and NULL is *unrecorded*, named as a gap: one guess mints
  a document the Act does not ask for and the other withholds the one the
  credit rests on. The column is nullable with **no default** and CHECKed to
  the two settled answers, so `unrecorded` cannot be STORED as a string; both
  API doors (`VendorIn` and `VendorUpdateIn`) normalise case and refuse it with
  a sentence saying it is the ABSENCE of a value, and both screens that record
  it — the client Vendors tab and the firm-level Supplier Master — serve the
  picker from `GET /api/rcm-documents/registration-states` rather than
  spelling the pair. A `Decision`'s **`reasons` and `gaps` are different
  things** and the panel renders them differently: reasons mean the Act does
  not ask for the document (settled), gaps mean nobody can yet tell
  (actionable). The particulars are built in the domain module rather than in
  the PDF, so what the endpoint serves and what the CA prints are one object.
  Four refusals are recorded rather than guessed: **no consolidated month-end
  self-invoice** (`[S]`, tied to the withdrawn Notification 8/2017-CT(R)),
  whether §9(4) applies is the bill's own `is_reverse_charge` and is the CA's
  answer, a cancelled registration is not modelled, and **Rule 46(h)'s UQC is
  absent because `purchase_bill_lines` has no unit column** — named, never
  invented. Numbering goes through the one `domain/gst/invoice_series`
  authority, and uniqueness is per client **per kind**, because Rule 46(b)
  allows "one or multiple series" and these are two.

- **A JOURNAL'S SUPPORTING DOCUMENTS ARE A DRAFT-ONLY EDIT, AND THE SCREEN SAYS
  SO** (ACC-25). `JournalEntryIn` has taken validated attachments since the
  first half of this finding; `JournalEntryUpdateIn` had none, so the editor
  rendered the control on an entry being corrected, the CA typed a link, and
  the PATCH sent everything except it. Both doors now validate through the same
  `domain/attachments` parser — a validator on one door only is one PATCH from
  being none, and this is the door reached SECOND, after the entry already
  looks legitimate. `None` means unchanged; an **empty list removes them**,
  which the service's header filter keeps and the `None` case drops.
  **A POSTED entry is REFUSED rather than ignored**, because
  `prevent_posted_journal_modification` (last defined in migration 274) lets a
  posted header change only inside `journal_edit_in_progress()`, and the one
  thing that sets it is `edit_posted_journal` — which rewrites LINES and
  carries no attachments. Teaching it attachments means replacing the posting
  kernel's own edit RPC, an owner decision rather than a convenience. The
  editor gates on `attachmentsReadOnly = readOnly || isPosted`, a STRICTER
  state than `readOnly` (a locked year or a filed return), so a CA is never
  invited to type something the server will refuse.

- **A LEDGER ROW NAMES THE DOCUMENT BEHIND IT, AND THREE FILES HAVE TO AGREE
  ABOUT WHAT THAT MEANS** (ACC-22, migration 400).
  `journal_entries.source_type` / `source_id` have existed since migration 104
  and have been filled in by all twenty-six posting paths since commit
  99ac94b5 — whose own message says *"This commit is the missing premise; the
  drill-through itself is a separate change."* The ledger was the half that
  never READ them, so a CA looking at "Trade Receivables 1,18,000 Dr" had a
  narration, a reference and nothing to open, which is the one keystroke Tally
  has trained them to expect and the only quick way to find WHICH document
  drifted when the GL and a sub-ledger disagree.
  **The two keys are ALWAYS PRESENT and null where the entry carries none.**
  An absent key and a null key read the same to `line.source_type ?? null` and
  are different bugs: null is "this entry has no document", absent is "this
  build did not send it" — the screen renders the first and cannot detect the
  second. Both `builders.ledger` and migration 400's `account_ledger_page`
  emit them unconditionally, and 400 is derived from **283**, still the last
  definer, because `CREATE OR REPLACE` replaces the whole body.
  **The ROUTE map is the browser's and the VOCABULARY is Python's.**
  `apps/web/lib/accounting/sourceDocument.ts` says which screen and which
  sub-tab each source opens — a fact about Next.js routes the backend cannot
  hold — and is pinned from the Python side by
  `tests/test_the_browser_can_open_the_document_the_ledger_names.py`: every
  member of `journal_source.ALL_SOURCES` is routed, is one of the three in
  `ENTRY_IS_THE_RECORD`, or is REFUSED with its own sentence. A guard written
  in `apps/web` would assert that file against a copy of itself, the Schedule
  III caption lesson. **Two sources are refused and the reasons are not
  interchangeable**: a `settlement`'s screen is keyed on the EMPLOYEE and the
  row carries the settlement id, and a `year_end_adjustment` lives under its
  ENGAGEMENT and the row carries the adjustment id. Sending a CA to a list that
  cannot show the document is worse than an unclickable row, because it reads
  as "this is the document".
  **One deep-link convention — `?tab=<id>&doc=<uuid>` — and one highlight.**
  A param per kind (`?invoice=`, `?bill=`, `?run=`) would be a second
  vocabulary; `DataTable`'s `highlightRowId` rings the row and scrolls it into
  view in ONE place rather than teaching five screens their own idea of
  "open". A row that is filtered or paged out is simply not found: nothing is
  forced into view and no filter is cleared, because a deep link must not
  silently change what the reader is looking at. The tab is validated against
  each screen's own `TABS` and read from `window.location.search` inside an
  effect — `apps/web` is a static export, so nothing may touch `window` during
  render.
  **Two guards that named a LOCATION broke on a move that did not break their
  rule**, and both were restated: `test_a_journal_source_reads_as_english`
  asserted `function sourceLabel` lived in the accounting page (it now finds
  the single definition by searching `apps/web`), and
  `the-book-can-be-read-not-only-posted-to` asserted the same spelling (it now
  asserts the page IMPORTS it). That is the third time this pattern has been
  fixed in this file's history; write the rule, not a spelling of it.

- **THE SUPPLIER MASTER IS `public.vendors`, AND `public.suppliers` IS RETIRED**
  (PUR-16). Migration 030 created a second one and `/accounting/suppliers` was
  its only writer, straight over PostgREST; every purchase path — bill
  creation, TDS withholding, AP ageing, the Schedule III payables note, GSTR-2B
  matching, §43B(h) — reads `vendors`. The credit limit was the harmless half
  (nothing anywhere reads one, on a vendor OR a client, and migration 378's
  column comment says `RECORDED, NOT ENFORCED` rather than implying a control
  that does not exist). **The TDS SECTION was not**: a CA who picked 194J on
  that screen wrote `suppliers.tds_section`, the bill read
  `vendors.tds_section`, found NULL and withheld nothing — and §40(a)(ia)
  disallows the WHOLE expenditure for an under-deduction, with §201(1) putting
  the tax on the deductor and §201(1A) interest on top. The screen goes through
  `/api/vendors` now, so `rbac()` runs. **Three field names differ and one is a
  different UNIT** — `supplier_name`→`name`, `payment_terms_days`→`credit_days`,
  `tds_rate_percent`→**`tds_rate_bps`**, so a percentage written into the
  basis-points column stores 10 where 1000 is meant and withholds 0.1% instead
  of 10%. **No data was migrated and that is a measurement, not a decision**:
  `public.suppliers` held ZERO rows in production on 13-09-2026. Marked dead in
  the database rather than DROPped, the same shape as migration 371 — a DROP
  moves both sides of the production-fixture comparison at once and needs the
  refresh in `docs/schema-drift.md`.

- **THE PURCHASE CYCLE BEGINS BEFORE THE BILL, AND THE GOODS RECEIPT IS A
  STATUTORY FACT** (PUR-25, migration 393). A client raises a purchase order,
  receives the goods against it and only then books the supplier's invoice;
  neither of the first two documents existed, so there was nothing to check
  the bill against — and no record at all of WHEN the goods arrived. That
  second absence is statutory twice over. **CGST §16(2)(b)** allows the input
  tax credit only where the recipient "has received the goods or services",
  and a March invoice for goods that arrive in April carries credit belonging
  to April. **MSMED §15 runs its fifteen days from ACCEPTANCE**, and the
  Explanation to §2(b) makes acceptance the day of ACTUAL DELIVERY — so
  `domain/income_tax/section_43b_h.py` had to use the bill date as a proxy and
  carried `ACCEPTANCE_DATE_NOT_HELD` on **every** answer. The proxy is the
  EARLIER date and therefore manufactures disallowances on bills paid in time;
  a goods receipt is the real one, and the caveat is now emitted only for the
  bills that actually fell back.
  `domain/purchases/order_cycle.py` is the commercial chain and
  `domain/purchases/three_way_match.py` is the comparison and the two statutes
  it settles.
  **IT REPORTS; IT NEVER BLOCKS A BILL.** A supplier who short-ships or
  over-charges has still sent one and the CA still has to book what arrived —
  refusing would push the entry outside the system, which is worse than a
  mismatch nobody looked at. The one thing refused is an over-RECEIPT against
  the order, because goods on the premises in excess of what was ordered mean
  the ORDER is wrong. **NO TOLERANCE IS APPLIED AND NONE IS INVENTED**: "within
  2%" is a firm's procurement policy rather than a rule, and every answer says
  so. **NO PRICE VARIANCE IS POSTED** — INV-05a costs a receipt at the BILL's
  own taxable value plus its §17(5)-blocked tax, so the bill IS the cost and a
  variance account would double-count. **A BILL WITH NO ORDER IS NOT A
  FINDING**: most purchases a practice sees — fees, rent, utilities — are never
  ordered.
  **NEITHER DOCUMENT POSTS OR MOVES STOCK.** The expense, the credit and the
  payable all arise when the bill is received. Goods received and not invoiced
  are a real accrual and building one needs a GRNI account and a reversal path
  — an owner decision, named rather than half-built.
  **`rejected_qty` IS ITS OWN FIGURE, not a smaller quantity**, because
  §16(2)(b) asks what was RECEIVED and §2(b) asks what was ACCEPTED and one
  number cannot answer both; what the order still owes is measured on what was
  KEPT. **The ACCEPTANCE date is the LAST receipt, not the first** — a
  part-shipped order is accepted when the goods the bill covers have all
  arrived — and an **objection removed** (§2(b)'s second limb) displaces it,
  which is LATER and so can only remove a disallowance, never create one.
  **The YEAR of the add-back is still the BILL's**: §43B(h) disallows a
  deduction claimed in the year the expense ACCRUED in, so only the fifteen-day
  clock moves. **`purchase_bill_lines` carries no `firm_id`** and is scoped
  through its parent bill — naming the column would be PGRST204 and no read at
  all, so the tenant check happens at the parent and a test pins both halves.

- **A VENDOR PAYMENT RECORDS WHICH BILLS IT SETTLED IN TWO SHAPES, AND EVERY
  READER MUST KNOW BOTH** (PUR-22). `purchase_payments.purchase_bill_id` is the
  legacy single-bill FK, written with NO allocation row;
  `purchase_payment_allocations` (migration 226) is the multi-bill shape,
  written with that column NULL. **The column says which SHAPE a payment is,
  not merely which bill it happened to pay** — `reversal_service.reverse_payment`
  branches on it, rolling the bill back by the payment's whole AP relief where
  it is set and by each allocation's own amount where it is NULL, so writing it
  from the allocation path would send a PARTLY allocated payment down the legacy
  branch and roll back more than it settled. That is why both shapes survive,
  why `POST /api/purchase-payments` refuses a request carrying both, and why the
  single-bill path was left exactly as it was when the endpoint learned to take
  `allocations` and hand them to `purchase_payment_service.create_payment_core`
  — the multi-bill engine whose only caller had been the bank match queue, so
  one NEFT against six bills meant six payments, six fabricated references and
  six journal entries. **A reader that knows one shape is silently wrong about
  the other**, and one was: `msme_43bh_service._payments` read only the bridge
  table, so §43B(h) saw every bill paid from the Purchases screen as NEVER PAID
  and added a timely payment back to taxable income — invisibly, because "no
  payment found" and "paid late" produce the same disallowance. Each shape has
  its own not-undone test: `is_voided` on the allocation row, `is_reversed` on
  the payment row, both filtered in PYTHON so a row lacking the key reads as
  live. `GET /api/purchase-payments?purchase_bill_id=` unions the two and
  stamps `allocated_to_bill_paise`, because `amount_paise` stops being the
  bill's figure the moment one payment settles several.
