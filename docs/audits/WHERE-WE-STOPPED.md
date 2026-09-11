# Where the phase work stopped — 11 September 2026

**Written at the owner's request, mid-Phase 11h, so the thread survives a break
of any length.** Read this first when picking the work back up; then
`docs/audits/2026-09-08c-the-phase-plan.md` for the plan and
`docs/audits/OPEN-QUESTIONS.md` for everything waiting on a human.

## Merged, on `main`

| Phase | Finding | What it did | PR |
|---|---|---|---|
| 11a | PUR-10 | an advance to a contractor withholds | #476 |
| 11b | TDS-06, TDS-09 | the challan a deductee sits under, and the 27Q builder | #477 |
| 11c | PUR-07 ≡ TDS-13 | a §197 certificate is a rate, a number, a period AND an amount | #478 |
| 12a | ACC-21, ACC-27, ACC-12 | one answer to "is this period closed" (migrations 360, 361) | #479 |
| 12b | ACC-17, GST-09 | a report is scoped to its caller; an early GSTR-9 shuts the window | #480 |
| 11d | PUR-09, SALES-05, PAY-09 | the number is already right; stop recomputing it | #481 |
| 11e | INV-06, PAY-14 | a §17(5)(h) reversal reaches GSTR-3B; a leaver's TDS reaches 24Q (migration 362) | #482 |
| 11f | INV-01 | closing stock as at a date; the ledger balance foots (migration 363) | #483 |
| 11g | SALES-11 | invoice discounts under §15(3)(a) (migration 364) | #484 |

## In flight — Phase 11h (ACC-10), committed but NOT merged

One source for Schedule III classification. **The code is green** — 11,890
backend mock tests, the frontend suite, and the PG column guards all pass — and
it is committed on `claude/ca-platform-audit-roadmap-yuoad3`. It has no PR yet.

### What is done

* **`domain/reporting/schedule_iii.py`** — the caption VOCABULARY
  (`BALANCE_SHEET_CAPTIONS`, `PROFIT_LOSS_CAPTIONS`, `CAPTIONS`,
  `RESIDUAL_CAPTIONS`) and `classify()`, which returns the caption AND the basis
  (`"mapping"` | `"subtype"` | `"residual"`).
* **The CA's own `chart_of_accounts.schedule_iii_mapping` is now read**, and
  outranks the free-text subtype scan — it was previously written by the CSV
  importer, shown on a read-only screen, and read by no computation at all.
  Honoured only on the statement the account belongs to.
* **It travels**: `Account` carries it, the reporting source selects it, both
  statement builders resolve the caption through `classify`, and
  `bucket_amounts` groups by the caption the builder put on the line instead of
  re-deriving it from the subtype.
* **The account PATCH accepts it** (`AccountUpdateIn.schedule_iii_mapping`),
  validated against `CAPTIONS` — so a mapping can be corrected without
  re-importing the whole chart of accounts. `""` clears it.
* **A real defect found and fixed**: `pl_bucket` returns
  `"Cost of Materials Consumed"` while `_CAPTION_TO_SCHEDULE_LINE`'s key said
  `"Cost of Materials"`, and the lookup's fallback was
  `"other_current_assets"` — so on a trading or manufacturing client the single
  largest expense on the P&L was classified as a CURRENT ASSET in the year-end
  financial statements. Profit overstated by the whole cost of materials and a
  phantom asset of the same amount. Nothing failed and nothing warned.
* **A second one**: `routers/year_end_mappings` read the `accounts` VIEW, which
  migration 016 created as `SELECT * FROM chart_of_accounts`. Postgres freezes a
  view's `*` at creation, so it carries only the columns that existed then —
  `schedule_iii_mapping` (migration 057) is not among them. Now reads the table.
* **Guards**: `tests/test_one_schedule_iii_vocabulary.py` (420 cases) asserts
  the buckets return only declared captions, every declared caption is
  reachable, and every translation table is TOTAL over the vocabulary — which is
  what would have caught the cost-of-materials defect.
  `tests/test_the_mapping_screen_moves_the_balance_sheet.py` walks the whole
  chain and asserts the RUPEES land on the caption the CA chose.

### What is NOT done, and is what to pick up

1. **No migration.** None is needed for the above — but see (3).
2. **The Schedule III Mapping screen is still read-only.** The backend now
   accepts a mapping on `PATCH /api/accounting/accounts/{id}`; the screen has to
   call it. That is the remaining visible half of ACC-10.
3. **`schedule_iii_mapping` has no CHECK constraint.** The Pydantic validator
   refuses a non-caption on the API path, and the classifier ignores one, but
   the CSV importer writes the column directly. A CHECK would make the column
   honest at rest; it needs a migration and a look at what production already
   holds in it.
4. **The residual count is computed but not surfaced.** `classify` returns the
   basis and the builders put `schedule_iii_basis` on every line — nothing yet
   reports "N balances are on an Other line because nobody decided", which is
   what would make the mapping screen's green count mean something.
5. **No negative control run yet** for 11h, and no PR.

## Phase 11's remaining features, after 11h

`ACC-06` (recurring journals, budgets and retainers out of browser
localStorage), `PUR-15` (§43B(h) MSME tracker), `GST-11` (QRMP), `GST-10`
(GSTR-9), `IT-19` (§54 reinvestment exemptions), then the two months-sized ones:
`IT-11` (Form 3CD) and `GST-20` (multi-GSTIN).

## The two things waiting on the owner

* **E1** — Render deploys fail on a health-check timeout, DIAGNOSED. The fix
  (move the boot work out of module import into a lifespan hook) touches how a
  live service boots and is the owner's call. `OPEN-QUESTIONS.md` §E1.
* **The backend is behind `main`** until somebody clicks Manual Deploy on Render.
  Migrations apply regardless, through a separate GitHub Actions job.

---

## Added 11 September 2026 — what production says, and the root cause 11h missed

Read against the live database rather than against memory, which changed the
shape of the remaining work.

### There are THREE Schedule III vocabularies, not two

11h built one source in `apps/api/domain/reporting/schedule_iii.py` and fixed
the computation. It did not look at where the CA actually chooses:

| # | Where | What it is |
|---|---|---|
| 1 | `apps/api/domain/reporting/schedule_iii.py` | the backend vocabulary — 23 captions. What 11h built |
| 2 | `apps/web/app/accounting/schedule-iii-mapping/page.tsx` lines 20–22 | **a hardcoded menu the screen OFFERS**, with different spellings and five captions the backend has never heard of |
| 3 | `apps/web/lib/accounting/scheduleIiiCaptions.ts` | **a browser-side classifier** — business logic in the frontend, against the standing rule |

**The consequence, measured.** Of 50 accounts carrying a
`schedule_iii_mapping` in production, **nine hold a value the backend
classifier silently discards** — the CA made a choice, the screen recorded it,
and the financial statements ignore it and fall back to the subtype scan:

| What the CA chose | What the backend knows |
|---|---|
| `Fixed Assets` (3 accounts) | `Tangible Fixed Assets` / `Intangible Fixed Assets` |
| `Employee Benefits Expense` (2) | `Employee Benefit Expense` — singular |
| `Short-term Loans & Advances` (2) | `Short Term Loans & Advances` — no hyphen |
| `Long-term Investments` (1) | `Long Term Investments` |
| `Short-term Borrowings` (1) | `Short Term Borrowings` |

The screen also offers five captions with no backend equivalent at all —
Capital Work in Progress, Goodwill & Intangibles, Long-term Provisions,
Short-term Provisions, Deferred Tax Asset. **A menu the engine cannot honour.**

### What that makes the remaining work

1. **The screen serves the backend's vocabulary** instead of a hardcoded list.
   One list, fetched, not copied. This is the visible half of ACC-10 and it is
   now the main item, not the PATCH wiring.
2. **Reconcile the spellings.** The screen's are hyphenated and plural, and are
   what production holds, so the backend should adopt them — three things then
   agree.
   ⚠️ **But this changes captions PRINTED on a statutory financial statement,
   and the exact Schedule III wording is NOT verified.** `icai.org` and every
   `.gov.in` are refused at the egress proxy. Adopting the screen's spellings is
   defensible on convergence — the screen, the data and the classifier's memory
   all agree — and it is still not a reading of the statute. **Logged as a new
   open question; the alias table means nothing breaks either way.**
3. **An alias table** maps the loose spellings onto canonical captions so a
   mapping already made is honoured whichever way it was spelled. `Fixed Assets`
   is the one that is genuinely ambiguous rather than merely spelled
   differently — all three live accounts are tangible by name and subtype, but
   a future intangible would be wrong, so it resolves through the account's own
   subtype rather than being aliased flat.
4. **Then** the CHECK constraint (it would fail on nine rows today), the
   read-only screen's PATCH wiring, the residual count, the negative control
   and the PR.
5. **`scheduleIiiCaptions.ts` should go**, or become display-only. A classifier
   in the browser is the thing ACC-10 exists to remove.

### Production, for sequencing

`fixed_assets` **= 0**. So **FA-02's free window is still open**: fix it before
the first register is migrated in and it is a code change; after, it is a
data-repair job. That moves it up the order.

Also: 7 clients, 12,899 journal entries, 1 payroll run and none finalised — so
the ESI rounding fix needs no back-fill.

---

## 11 September 2026, later — ACC-10's backend and mapping screen are done

Landed: the caption vocabulary reconciled to the screen's spellings (owner
decision A4, option (a)), an alias table so nothing already stored is lost,
`GET /api/accounting/schedule-iii/captions` serving the one list, and the
mapping screen rewritten to fetch it and to SAVE — it was read-only, so the
only way to set a mapping was to re-import the whole chart of accounts.

**The rename was wider than it looked.** The first pass used a hand-written file
list and missed five modules — `ratios.py`, `trend.py`,
`financial_analysis_service.py`, `xbrl_service.py` and two tests. The backend
suite caught every one. The second pass grepped instead of guessing, which is
what the first should have done.

### What is left of ACC-10, measured

**`apps/web/lib/accounting/scheduleIiiCaptions.ts` — the third classifier — is
still live**, and it is business logic in the browser against the standing rule.
Its blast radius is now precise:

- **The Profit & Loss is nearly clear.** `app/clients/[id]/accounting/page.tsx`
  line 1781 reads `b.schedule_iii_caption ?? plBucket(...)` — the backend
  caption wins and the browser function is a fallback for the window before it
  arrives.
- **The Balance Sheet is not.** Lines 2108–2110 call `bsBucket(...)`
  unconditionally. There is no backend caption on that path at all.
- **And the two disagree on wording.** Compared mechanically, the browser
  classifier emits captions the backend does not know: `Employee Benefit
  Expense` (the spelling just retired), `Tangible Assets` / `Intangible Assets`
  (vs `Tangible Fixed Assets`), `Non-Current Investments` (vs `Long-term
  Investments`), `Cost of Materials` (vs `Cost of Materials Consumed`) and
  `Tax Liabilities` (no backend equivalent).

So a CA reading the client accounting screen's Balance Sheet sees **different
line names** from the ones on the year-end statements. That is the remaining
half of ACC-10 and it is a well-scoped piece: put a caption on the balance-sheet
API rows the way the P&L already has one, then delete the browser classifier.

**Deliberately not started in the same change.** `page.tsx` is 3,476 lines and
this commit already moves the vocabulary under every consumer.

### Also outstanding, unchanged

The CHECK constraint on `schedule_iii_mapping` (it would fail on the nine
production rows until they are normalised — the alias makes them WORK, it does
not rewrite them), and surfacing the residual count on the mapping screen.

### The five captions the screen used to offer and the engine does not present

Capital Work in Progress, Goodwill & Intangibles, Long-term Provisions,
Short-term Provisions, Deferred Tax Asset. All real Schedule III lines. They are
**absent from the menu rather than added to the engine**, because adding one
means teaching the statement builders, the year-end translation and the PDF
about it. Nothing in production is mapped to any of them, so removing them cost
nothing — but a CA who wanted one now cannot ask for it, which is the honest
trade and worth revisiting.


---

## Track F2 — ESIC and PT can record a remittance (migration 365)

**And the plan's shape was wrong, so it changed.** F2 said "one
`statutory_filings` record, for everything". Reading what already exists says
otherwise:

- `public.filings` is the GST/ITR record and **drives the period lock** through
  `journal_period_lock_reason`. Migrating it would risk the one thing that works
  to tidy the ones that do not.
- `public.epfo_ecr_filings` (335) carries `return_type`, a submitted-vs-approved
  state, and a sequence rule where an unapproved month **blocks the next**. That
  is EPFO's own machinery, not a generic lifecycle, and flattening it loses it.
- MCA filings hang off a company and an SRN, and an SRN is not a filing.

So 365 closes the actual hole — **ESI and PT, which had no record at all** — in
the shape 335 proved, rather than unifying four things that are not the same
thing. They do share a shape: monthly, per client, settled by a challan. They
differ in two ways the columns carry: **PT is per STATE**, so one client with
staff in two states files twice for one month; and **ESI has a contribution
period** (H1/H2) the portal shows the remittance under.

22 `_pg` tests, because the frontend reaches ~83 tables directly over PostgREST
where no `rbac()` runs — a rule enforced in Python is a rule the second write
path does not have.

### Still to do on Track F

**F1 (the ESIC `.xls`) is blocked on a dependency decision, not on work.** The
portal wants Excel 97-2003 (BIFF8). This backend has only `openpyxl`, which
reads and writes `.xlsx` and cannot do BIFF8 — filling the CA's own downloaded
template needs `xlrd` + `xlwt` + `xlutils`, all three unmaintained. Adding three
unmaintained dependencies to a financial backend is an owner call, and it rests
on a fact this environment cannot check: whether the portal still refuses
`.xlsx` in 2026. The manual that says `.xls` is of unknown vintage.

### F4's shape was wrong, and 365 carries the correction

F4 said *"the challan is money — it has to reach the GL"*, meaning post
`Dr ESI Payable / Cr Bank` when a remittance is recorded. **That would have
double-counted.** `services/bank_posting_service.post` already posts exactly
that entry when the CA passes the bank statement line against the liability
account, and it is the one path for money movement. `public.epfo_ecr_filings` —
the table 365 is modelled on — deliberately carries no journal reference for
the same reason.

What was actually missing is the **link**: without it there is no way to tell a
liability nobody has paid from one that was paid and never tied back, so the
statutory accounts look uncleared either way at year end. `journal_entry_id` is
on 365, nullable, `ON DELETE SET NULL` — reversing the payment unlinks the
remittance without erasing the evidence that the return was filed.

So F4 becomes a **reconciliation**, not a posting: match a remittance to the
entry that paid it, and report the ones that are not matched.

**F3 (the handoff screen) is unblocked** — 365 is the record it needed.

---

## Track F3 — the handoff screen (done)

The Payroll module of a client now has a **File** tab: every statutory
settlement the month raises, in the order its portal asks for it.

**The gap it closes** is step 4 of the seven between books that are right and an
obligation that is closed — compute, emit the artefact, pre-flight, **hand off**,
file, capture the acknowledgement, reconcile. Exactly one of the seven belongs
to the government. Six are ours and this was the one nothing did. Settling one
client-month meant the register for the figures, Setup for the establishment
code, Outputs for the file, three portals, and a spreadsheet to remember which
of them were done — then typing numbers from one into another with nowhere to
put the challan number that came back.

### What it shows, per obligation

Identifier → period → the figures the portal will ask you to confirm → the file
→ one field for the reference that comes back. EPF, ESI, and **one panel per
state** for professional tax.

### Three things it deliberately refuses, asserted rather than promised

- **No credential field, no OTP field, no embedded portal frame** — for EPFO,
  for ESIC, for any state. `apps/web/scripts/no-screen-takes-a-portal-credential.test.ts`
  states the rule tree-wide with an allowlist of our OWN sign-in screens, and
  `apps/api/tests/test_the_handoff_says_what_goes_in_which_box.py` asserts the
  same over the panels the server builds. Both carry negative controls.
- **No due date for professional tax.** Each state fixes its own and there is no
  rule to derive; `compliance_engine.payroll_deposit_due_dates` already refuses
  for that reason. The panel SAYS why rather than leaving a blank, because
  silence reads as "nothing is due".
- **No professional-tax file**, because none is produced for any state yet
  (F5). The panel says so rather than offering a button that is not there.

### What it moved rather than copied

The ECR and ESIC downloads and the record-what-you-filed form LEFT the Outputs
shelf. They were never shelf items — a CA downloading the ECR is mid-way through
a filing, not collecting a document. Two copies of one filing flow would drift,
so Outputs now points at the File tab.

The filing form also gained the thing it was missing: the **return type now
defaults to what EPFO is expecting**, which `ecr_sequence.decide_returns`
already decides. The old form asked from scratch and defaulted to Regular
whatever the month needed — and a Supplementary recorded as a Regular leaves the
real Regular outstanding, which blocks the next month.

### One defect found on the way, and it was nearly shipped

`ecr_sequence`'s return types are **lowercase** (`REGULAR = "regular"`). The
first draft compared against `"Regular"`, so the "upload this as a Supplementary"
warning would have fired on every ordinary month — which is how a real warning
becomes invisible. A test now pins the comparison.

The screen's challan date also read a calendar date out of a UTC instant, which
in IST is yesterday between midnight and 05:30 — so a CA filing at 1 a.m. would
have dated the challan a day before the money moved. Caught by the existing
`a-calendar-date-is-never-read-back-in-utc` guard, which is the guard working.

### Track F after this

| | Phase | State |
|---|---|---|
| F1 | the ESIC `.xls` the portal accepts | **blocked on an owner decision** — filling the CA's own downloaded template needs `xlrd` + `xlwt` + `xlutils`, all three unmaintained |  ← SUPERSEDED, see "Track F, after this tranche"
| F2 | a record for ESI and PT remittances | done — migration 365 |
| F3 | the handoff screen | **done** |
| F4 | the challan is money | **done** — as a RECONCILIATION, not a posting |
| F5 | professional tax: the artefact | not started — and it needs the state slabs a human must supply first |  ← WRONG, the slab half was already built
| F6 | the never-do list, as code | **half done** — the credential/OTP/frame rule is now a test. The other two rules are still prose |
| F7 | the DSC register | not started |

---

## Track F4 — which entry paid this remittance (done)

`GET /api/payroll/clients/{id}/remittance-reconciliation` lists every ESI and
professional-tax remittance recorded as PAID with no journal entry tied to it,
each with the entries that could be its payment. A panel at the top of the
Payroll **File** tab renders it, client-wide, and links with one click.

**The question it answers.** On the ledger, a statutory liability **nobody has
paid** and one that was **paid and never tied back** look identical — both sit
uncleared on ESI Payable at year end, and telling them apart meant opening the
bank statement one account at a time.

**Still not a posting.** The PATCH behind the button writes a reference and
nothing else. `services/bank_posting_service.post` already wrote
`Dr <liability> / Cr Bank` when the CA passed the bank statement line, and it is
the one path for money movement; posting from here as well would debit the
statutory liability twice. That was F4's original shape and it was wrong — see
the section above.

### The rule that makes the matcher work, and it is easy to get backwards

**Match on what LEFT THE BANK, not on what the entry took off the liability.**

`statutory_remittances.amount_paise` is the CHALLAN's figure — migration 365
says so — and a challan can carry more than the liability. Interest and damages
under ESI Act s.39(5) are added at the portal and are an EXPENSE, not a
reduction of the payable:

```
Dr  ESI Payable                      10,000
Dr  Interest on Statutory Dues          500
  Cr  Bank                                     10,500
```

Matching the challan against the debit to ESI Payable would fail on **every
late remittance** — which is the entire population a reconciliation exists to
find. The entry TOTAL is what left the bank, and a balanced entry's total is
its credit side, so no account has to be classified as a bank for this to work.
The panel names the difference rather than leaving a CA to derive it from two
numbers.

### What it refuses

- **Nothing is ever linked automatically.** A candidate carries a grade —
  `exact` or `near` — and a reason SENTENCE, never a score. A CA who paid two
  identical challans in one week gets two exact candidates and is the only one
  who can say which is which. Same rule as the bank-entry drafts
  (`docs/architecture/09`).
- **A remittance with no `paid_on` gets nothing**, not everything. Without a
  date there is no window, and offering every entry that ever touched ESI
  Payable is not a shortlist — it is the ledger, re-presented as a suggestion.
- **±7 days**, and the number is a judgement written down rather than a rule:
  net banking debits the same day, a cheque clears over a few, and a CA
  recording the challan date may be a day out. Wider would start offering next
  month's remittance as a candidate for this one.

### One defect found on the way, in this change's own first draft

The money formatter used Python's `f"{n:,}"`, which groups in **threes** — so
₹1,25,000 came out as "₹125,000", a figure no Indian document uses and one the
browser renders correctly two lines away on the same screen.
`domain/reporting/amount_words.indian_digits` already existed for exactly this,
with the same reasoning on it. Delegated, not re-implemented.

### Track F after this

| | Phase | State |
|---|---|---|
| F1 | the ESIC `.xls` the portal accepts | **blocked on an owner decision** — three unmaintained dependencies |  ← SUPERSEDED
| F2 | a record for ESI and PT remittances | done — migration 365 |
| F3 | the handoff screen | done |
| F4 | the challan is money | **done**, as a reconciliation |
| F5 | professional tax: the artefact | not started — needs the state slabs a human must supply |  ← WRONG, the slab half was already built
| F6 | the never-do list, as code | **done** — all three rules |
| F7 | the DSC register | **already built** — the plan's premise was wrong, see below |

---

## Track F6 — the never-do list, as code (done)

Three product rules that protect the whole filing position, now tests:

1. **No field anywhere collects a government-portal password, PIN or OTP** —
   `apps/web/scripts/no-screen-takes-a-portal-credential.test.ts`, from F3.
2. **No column anywhere stores a portal credential or token** —
   `apps/api/tests/test_the_never_do_list.py`.
3. **Nothing transmits to a government host** — same file.

**All three were already true. That is the point.** None of these tests fixed
anything; what they do is make the day somebody adds the first one a deliberate
decision with a review attached, rather than a line in a large diff nobody reads
as a policy change — which is how this class of thing actually gets in.

### Rule 2 is matched on a name's SEGMENTS, not its letters

`pincode`, `mapping`, `shipping_bill_no` and `is_pinned` all contain "pin". A
guard that fires on those is one somebody silences rather than reads. Eight
columns genuinely match the vocabulary and every one is OURS, each with its
reason: `lock_pin` (the firm's own year-lock PIN), `token_no` (the serial
printed on a DSC's USB crypto token — an inventory label for a physical object),
the three invite tokens and the engagement `sign_token` (links this product
mints), and two AI usage counters.

### Rule 3's FIRST SHAPE WAS WRONG, and how is the part worth keeping

It began as "no backend file may name a government host" — and **23 files failed
it**, every module whose docstring says the ECR is uploaded at
`unifiedportal-emp.epfindia.gov.in`. Those are the right thing to write: the
whole product is built on telling a CA exactly where to go. An exemption list
with 23 entries of "this is a comment" is not a policy, it is paperwork.

Naming a portal is not the risk; TRANSMITTING to one is. So the rule is stated
over the thing that can actually transmit — **the modules that can make an
outbound request at all**. There are eleven, and a test now pins each with its
destination:

| destination | modules |
|---|---|
| Groq | `ai_copilot` (router + domain), `assistant`, `financial_analysis_service`, `document_intelligence_v2` |
| Gemini | `document_intelligence_v1`, `statement_vision` |
| Resend | `email_service` |
| Razorpay | `payments/razorpay` |
| our own deployed API | `scripts/smoke_api` (a smoke test, not the service) |
| **a firm-supplied URL** | `invoice_pdf_service` — the branding logo. The only destination not fixed in code, bounded by a timeout and a byte cap |

A grep for `^import httpx` found four of those eleven. The AST scan found all
eleven, including `google.genai` imported lazily inside a function — which is
why the check reads imports properly rather than matching line starts.

A separate test asserts the opposite direction too: that naming a portal in
prose **is** allowed and common (more than ten modules do it), and that no
module both reaches the network and names a government host. That combination
is the entire rule.

### Verified

Four mutations, each applied and reverted: a new module calling `gst.gov.in`
(2 failed), a new module reaching the network undeclared (1), a
`gst_portal_password` column (1), a `portal_otp` column (1).

---

## Track F7 — the DSC register: ALREADY BUILT, and the plan was wrong

The plan says *"Nothing anywhere tracks a digital signature certificate."*
**That is false**, and was false when it was written. What exists:

- **`public.dsc_records`** (migration **014**) — holder, PAN, Class 2/3,
  purpose, issued and expiry dates, issuer, the crypto token's serial, notes.
- **`routers/dsc.py`** — list, create, patch, **renew**, delete, under its own
  `dsc` RBAC resource, with a duplicate guard on (PAN, type, expiry) and a
  refusal when `issued_date` is after `expiry_date`.
- **`apps/web/app/settings/dsc-tracker/page.tsx`**, linked from `SettingsPanel`
  and — the part F7's rationale actually wanted — from **`DeadlinesPanel`**, so
  it sits beside the filing deadlines.
- **Expiry within 60 days surfaced on `/risks`**, per holder.

So F7 is closed as **already done**, not implemented again. The finding stands
as a reminder that the 7 September audit's "nothing does X" claims are worth
checking before building: this is the third one this session that turned out to
be stale (FA-10's edit path, the workflow repository's join, and now F7).

### The one thing F7 pointed at that is genuinely NOT built

"An expired or unassociated DSC is the most common cause of a stalled MCA
filing" — and nothing connects the two. `mca_directors` exists and
`dsc_records` carries a PAN, so a join is possible; what is missing is the fact
nobody holds: **which director signs which form**. That is a human decision, of
the same shape as the MSMED classification and the DTAA rate, and it would need
a place to record it before any warning could be honest. Scoped, not started.

---

## Track F7b — what the DSC screen could NOT do, and now can

F7 was closed above as "already built", and the register is. **The SCREEN was
not**, and that was an overclaim in the paragraph above rather than a fact about
the code: `routers/dsc.py` has list, create, **patch**, **renew** and delete;
`app/settings/dsc-tracker/page.tsx` called only the first two. So a certificate
could be added and listed, and then never corrected or renewed — the two things
that actually happen to a DSC. A holder whose name was typed wrong stayed wrong,
and a renewed token was added as a SECOND row beside the expired one, which is
the register telling a CA a client has two certificates.

* **Renew** — `POST /api/dsc/{id}/renew`, which the router already implemented:
  it supersedes the old row rather than editing it, so the history of which
  certificate signed what survives.
* **Correct** — `PATCH /api/dsc/{id}`, for the typo case. Deliberately separate
  from renew, because they are different acts: a correction says the row was
  always meant to read this way, a renewal says a new certificate exists.
* **Delete is deliberately NOT surfaced.** `DELETE /api/dsc/{id}` is a hard
  delete and `dsc_records` has no soft-delete column, so a click would destroy
  the record that a certificate ever existed. Retiring a DSC is what renew
  already does. Adding a screen button for an irreversible delete of a
  compliance record is not a gap being left open; it is the one action that
  should not be one click away.

### A day count that was wrong, and it is a family

`getDaysRemaining` read `new Date(expiryDate).getTime() - TODAY.getTime()`, with
`TODAY` captured **at module load**. Two defects in one line:

1. `new Date("2026-09-30")` is parsed as **UTC midnight**, while `new Date()` is
   a local instant. In IST the two are 5:30 apart, so between 00:00 and 05:30
   every such count is **one day too high** — the same window the existing
   `a-calendar-date-is-never-read-back-in-utc` guard's header describes.
2. A `TODAY` frozen at module load never advances. A tab left open overnight —
   which is what a dashboard tab is — reports yesterday's day count all day.

Fixed here to `daysBetweenLocalISO(todayLocalISO(), expiry)`, which
`lib/dateMath.ts` has had all along and whose docstring names this exact
mistake: *"never mix a date-only string with a live `new Date()` instant"*.

**This is not one site.** A tree scan for a millisecond difference divided by a
day constant finds **13 more**, in 12 files:

| verdict | sites |
|---|---|
| wrong today — a date-only STRING against a live instant or a local-midnight Date | `engagements`, `risks` ×3, `clients/[id]/overview`, `clients/documents`, `reports` — **7** |
| a `TODAY` frozen at module load | `mca` — **1** |
| correct but hand-rolled (both operands built locally, or both date-only strings) | `DashboardContent`, `calendar`, `payroll`, `payroll/reports`, `accounting/loans` — **5** |

Reported, not fixed here: it is the money-parser and `toISOString` lesson a third
time — the correct helper exists, its own docstring says to use it, and nothing
checks — so it wants the same treatment, a sweep plus a guard stating the RULE
(nothing outside `lib/dateMath.ts` divides by a day-in-milliseconds constant),
not a fourth paragraph of prose. Two of the five "correct" ones were only
established by reading them; a guard removes that reading from the next person's
job. Scoped as its own tranche so this one stays reviewable.

### The same defect, one screen over — a remittance recorded in error

Found by looking for callers of what F4 added: `retractRemittance` and
`remittances` were two typed API-client methods with **no caller anywhere**. A
typed wrapper nothing calls is the frontend twin of the unreachable endpoint
this tranche's ratchet measures on the backend, so both were resolved rather
than left.

* **Retract is now on the handoff screen**, beside "Recorded as filed", for ESI
  and professional tax. It closes the F7b defect one screen over: recording a
  remittance is how PracticeSync learns a statutory liability was settled, so
  the wrong month or the wrong scheme leaves a **real liability looking paid**,
  and there was no way to take it back. The server's DELETE is a SOFT delete —
  the challan number, the date and the amount that left the bank are held
  nowhere else — and the confirmation says what it destroys and what it does
  NOT touch: the portal, and the ledger entry that actually paid the money.
* **EPF is deliberately excluded.** Its record is `epfo_ecr_filings`, which
  carries EPFO's month-wise sequence, and retracting there unblocks the next
  month. Different act, different consequence, its own path.
* **`remittances` (the client-wide GET) was deleted, not wired.** The handoff
  endpoint already returns the month's recorded row on each obligation, and the
  question anyone asks of a client-wide list — what is paid and never tied back
  — is `remittanceReconciliation`. The ROUTE stays; nothing calls the wrapper.

---

## Track F1 — DECIDED, and the half worth building is built

F1 sat as "blocked on an owner decision" through two status tables above. The
owner delegated the decision. **It is decided: no BIFF8 dependencies.** Three
grounds, in the order that settles it:

1. **`xlwt` and `xlutils` have had no release since 2017.** `xlrd` is
   maintained but dropped `.xls` support's companions long ago.
2. **`xlrd` would be parsing an UNTRUSTED UPLOAD inside the service that holds
   every client's general ledger.** The CA's own downloaded template is a file
   from a third party; a parser on that path is attack surface, and this is the
   one process where that matters most.
3. **The requirement driving it cannot be checked from here.** The manual saying
   Excel 97-2003 is of unknown vintage and this environment's egress is blocked,
   so whether the portal still refuses `.xlsx` in 2026 is unknown. Taking on
   three unmaintained parsers on an unverified premise is the wrong trade in
   that direction.

### What was built instead, and why it is the half that matters

ESIC's filing manual makes the monthly upload **all or nothing**:

> "successful transaction only when all the Employees' (who are currently mapped
> in the system) details are entered perfectly"

A file missing ONE insured person is not partially imported — the **whole file
is rejected**, after the CA has assembled it, uploaded it and waited. The
portal's own list of mapped IPs is the authority for who must be in it, and
nothing in this product had ever compared the two. That is the failure F1 set
out to stop, and it needs no Excel writer.

* **`domain/payroll/esic_mapped_ips.py`** — `normalise()` takes the DIGIT RUNS
  out of whatever the CA pasted (the portal's screen copies as columns, as
  newline-separated text, or with names beside the numbers), so nobody has to
  reformat a list before the product will read it. `reconcile()` returns the two
  directions **separately**, because they are opposite problems: `missing_from_file`
  fails the whole upload and is fixed by adding a row with a reason code;
  `not_mapped_at_esic` means the portal does not know that person and is fixed at
  ESIC. One combined "differences" figure would send the CA to the wrong place.
* **`POST /api/payroll/runs/{run_id}/esic/mapped-ips`** — compares the pasted
  list against the members of the run's own ESIC return, built by the same
  read-only `_build_run_esic` the download uses. **Nothing is transmitted and
  nothing is stored**: it is the portal's data about the client's own staff, the
  answer is wanted now rather than next month, and keeping a copy would make this
  product the second place it lives for no reason. A test reads the module's own
  source and asserts it names no HTTP client, no database and no file write.
* **The ESIC panel on the handoff screen** carries it, and only that panel —
  EPFO takes its members from the ECR itself and PT has no mapped list, so the
  check has no meaning there.

If the `.xls` requirement is ever confirmed, none of this is wasted: it compares
people, not file formats.

### Verified

20 tests; seven mutations applied and reverted, each caught: both directions
reporting one list (2 failed), `would_be_rejected` over-firing on the
not-mapped side (2), `normalise` demanding one number per line (2), duplicates
not collapsed (2), and three separate re-sortings of a list the CA reads against
the screen it came from (1 each). **The ordering claim was the module's docstring
and nothing tested it** — the re-sort mutation passed on the first run, which is
how it was found.

---

## Every mounted endpoint has a way in — the second ratchet

`tests/test_every_mounted_endpoint_has_a_way_in.py` walks every route FastAPI
has mounted and every fetch the frontend makes, and fails when the unreachable
count rises. **137 of 904 endpoints have no caller** — too many to explain in one
sitting and too many to leave unmeasured, which is exactly the shape the
unreadable-column budget took: a per-module `BUDGET`, a `TOTAL_BUDGET` that may
only go DOWN, and a test that fails a budget entry left behind after its module
reaches zero.

Two things it does not claim, written into the docstring rather than discovered
later:

* **It matches PATHS, not (method, path) pairs.** `/api/dsc` was at 0 while the
  screen made only GET and POST calls against a router with five verbs — which
  is how F7b's gap was found, and is also the limit of what this guard proves.
* **An endpoint with a caller is not thereby correct.** Reachability is the
  floor, not the ceiling.

Negative control: an orphan endpoint added to a router at budget — 2 failed
(the module budget and the total).

---

## Track F, after this tranche

| | Phase | State |
|---|---|---|
| F1 | the ESIC upload the portal accepts | **done, as a RECONCILIATION** — the BIFF8 template is a decided NO, not a gap |
| F2 | a record for ESI and PT remittances | done — migration 365 |
| F3 | the handoff screen | done |
| F4 | the challan is money | done, as a reconciliation |
| F5 | professional tax: the artefact | **half of it was already built** — see below |
| F6 | the never-do list, as code | done — all three rules |
| F7 | the DSC register | done — register already existed; the screen's renew and correct built here |

### F5 re-read: the slab half is built, the artefact half is not

F5 is recorded twice above as *"not started — and it needs the state slabs a
human must supply first"*. **The slab half exists and has since migration 327.**

* **`public.firm_pt_slabs`** (migration 327) — firm-scoped, per state, monthly
  or half-yearly basis, `from_paise`/`to_paise`/`amount_paise`, a `months[]`
  array for Maharashtra's February differential, and `notification_reference`
  and `notification_date` **NOT NULL on purpose**: the whole argument for letting
  a hand-entered figure drive a statutory deduction is that a named person read
  a named notification on a named date.
* **`GET` / `PUT` / `DELETE /api/payroll/statutory-values`** — validated, and a
  firm slab **fills a gap without overriding a modelled state**: Maharashtra,
  Tamil Nadu, Karnataka and West Bengal stay on the code that is pinned to the
  state Acts by tests.
* **`app/settings/statutory-values/page.tsx`** — 460 lines, already shipped.

So what remains of F5 is only the **artefact**: the per-state return a CA files
with the collected tax. That is not one build — the format is per state, the
same twenty-two-way fan the slabs are, and it needs a state's actual return
layout in hand before any of it can be written. Unstarted, and correctly so.

---

## The 7 September audit's "nothing does X" claims: FIVE of five checked were stale

Recorded because it is now a pattern with a measurement behind it, not an
impression. Every claim of the form *"nothing anywhere does X"* that this
session went to build found the thing already existing, in whole or in part:

| claim | what was actually there |
|---|---|
| FA-10 — no edit path for a fixed asset | the edit path existed |
| the workflow repository has no join | the join existed |
| F7 — "nothing anywhere tracks a digital signature certificate" | `dsc_records` since migration **014**, a full router, a screen, and a 60-day warning on `/risks` |
| F5 — PT needs state slabs a human must supply first | `firm_pt_slabs`, three endpoints and a 460-line screen since migration **327** |
| `/api/dsc` has no caller (this session's own new ratchet) | it had two — the ratchet matches paths, not verbs |

**The rule this earns: read the code before building against an audit claim,
including this session's own.** The last row is the one that makes the point —
a guard written this week produced a stale-looking claim within hours, because
it measured something adjacent to what it appeared to measure. Four of the five
would have shipped a second implementation of something that already worked,
which is the specific harm CLAUDE.md's "one implementation, or two pinned by a
parity test" rule exists to prevent.
