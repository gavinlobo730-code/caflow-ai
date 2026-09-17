# Questions waiting on you

Written down rather than asked, because they arrived while you were asleep and
none of them blocks work that could go on without an answer. Each says what I
did in the meantime, so nothing is stalled — these change what happens NEXT,
not what has already shipped.

Answer them in any order. Where I have a recommendation it is marked.

---

## 1. A purchase return after the tax was already withheld  *(PUR-23 ≡ TDS-32 — shipped, half of it is yours)*

A ₹5,00,000 §194J bill is booked, ₹50,000 is withheld and deposited, and the
vendor then issues a credit note for ₹2,00,000. There are two lawful answers
and the statute does not choose:

- **§194C(3)/§194J(1) charge on "the aggregate of the amounts of such sums
  credited or paid".** A return reverses part of the credit, so the aggregate
  is now smaller and the deduction should be recomputed. Right where the note
  is in the SAME quarter and the challan has not gone.
- **§200 required the tax to be paid over and §199 then gives the deductee
  credit for it.** Once deposited the deduction stands, and the deductor
  carries an EXCESS DEPOSIT to set against a later liability.

Which applies turns on when the challan went — which the books do not record.

**What I did:** the software now states the divergence in one sentence on the
26Q/27Q build and on the purchase screen, and changes no figure. That is safe
in both readings.

**What I need from you:** do you want either branch automated? If yes, the
software has to start recording the challan date against each deduction, which
is a migration.

---

## 2. §50 interest and §47 late fee  *(GST-21 — SHIPPED as (b), and one row of the table below turned out to be wrong)*

> **Update, later the same night.** Built as option (b) below. Then, going back
> over it, I found that one of the rows I marked "high confidence" is not:
> **§50(3)'s 24% is now a NAMED GAP too.** See question 7.

Every late GSTR-3B the product prepares carries nil interest and nil late fee,
and the CA computes both by hand. ClearTax, IRIS and Tally all show them.

The ENGINE is arithmetic I can write tonight. The problem is the NUMBERS:

| figure | where it comes from | how confident I can be here |
|---|---|---|
| §50(1) 18% p.a. | the Act, notified by 13/2017-CT | high — it is in the section |
| §50(3) 24% on wrongly availed credit | the Act as substituted | ~~high~~ — **wrong, see question 7** |
| Rule 88B's net-cash-ledger restriction | textual, not a number | high |
| §47 late fee — ₹50/day, ₹20/day nil | Notifications 4/2018 and 76/2018 | **`[S]` — I believe these, I cannot verify them** |
| the turnover caps (₹500 / ₹2,000 / ₹5,000 / ₹10,000) | Notifications 19/2021 and 20/2021 | **`[S]`** |

This environment's proxy refuses every `.gov.in`, so nothing above the line can
be confirmed against a primary source.

**Three options, and I recommend (b):**

- **(a)** Build it with the notified figures, `[S]`-graded, in an FY-versioned
  registry with a `LATEST_VERIFIED` anchor, so the annual sweep catches them.
  Fastest and gives a CA the number they actually pay. Risk: if I have a slab
  wrong, the fee shown is wrong.
- **(b) *(recommended)*** Build the engine and the §50 side in full, and hold
  the §47 daily rates and caps as a NAMED GAP — the same shape as the state
  professional-tax slabs, where the code refuses and says what to go and read.
  A CA fills the table once. Nothing wrong is ever shown.
- **(c)** Wait until you can check the notifications, and build nothing.

---

## 3. The migration queue — how do you want to review it?

Twenty-odd open findings need a schema change, and **merging a migration to
`main` applies it to the live Supabase project with no manual step in
between**. So I have not written any of them.

Do you want:

- **one PR per migration**, reviewed and merged as you go — slowest, safest; or
- **one PR carrying several**, with the SQL laid out for you to read first; or
- **a plan document first** listing every column each finding needs, so you
  approve the shape before I write any SQL?

I lean towards the third, then the second.

---

## 4. Two changes to money paths I have deliberately not made

Both are small and both post to the general ledger, which is why they waited.

- **PUR-22** — `POST /api/purchase-payments` (what the Purchases screen calls)
  cannot settle more than one bill, while `create_payment_core` (what the bank
  match calls) can. The fix is to route the router through the engine with a
  one-element allocation. No migration — `purchase_payment_allocations` has
  existed since 226. It IS a change to how a payment posts.
- **ACC-16** — journal lines display in arbitrary order because there is no
  ordering column. Needs a migration AND a backfill, and the probe pass warns
  that migration 251's immutability trigger will refuse the backfill outright.
  That needs designing, not just writing.

---

## 5. A finding I think is wrong, and want to close rather than build

**ACC-19** says multi-currency "is fully built across five phases but cannot be
switched on for any firm or client". The switch is
`core/feature_flags.multi_currency_platform_enabled`, which reads the
`MULTI_CURRENCY_ENABLED` **environment variable** and whose own docstring says
"No DB dependency". A settings screen in a static-export frontend cannot set an
env var, and `render.yaml` must declare every variable the backend reads.

So the L1 kill switch working the way it does is a DESIGN, not a defect. What
might genuinely be missing is a screen for the **firm and client** level flags
underneath it.

**Do you want me to** (a) close ACC-19 as not-a-defect and note the env var in
the deploy docs, or (b) build the firm/client toggle screen under it?

---

## 6. Design — two of your three answers landed, one is still open

You answered density ("depends on the CA") and dark mode ("no, the current one
is good"). Both are recorded and I am working to them: no darker theme, and a
layout that uses the horizontal space without cramping, which does not need you
to pick a pixel width.

The one still open: **which module should be the reference implementation?** I
suggested Banking Entries because it is the densest screen in the product, so
whatever survives there survives everywhere. Sales Invoices is the alternative —
fewer states, but it is what a CA shows a client.

---

## 7. §50(3): 24% or 18%?  *(a correction to my own work, made overnight)*

I wrote `SECTION_50_3_RATE_BPS = 2400` and stated 24% as a fact — in the
docstring, in the refusal sentence, in the computed basis, and in a test that
pinned it. That rests on **Notification 13/2017-Central Tax**, which notified
24% against §50(3) **as it then stood**.

The **Finance Act 2022 SUBSTITUTED §50(3)**, retrospectively from 01-07-2017 —
and the rate for the substituted sub-section appears to have been notified
separately, by **Notification 09/2022-Central Tax**, at **18%**.

I cannot read either notification from here. What decided the treatment is not
the doubt but its DIRECTION: the two differ by a third of the charge, and §50(3)
interest is a sum a CA pays over on the client's behalf, so an over-stated rate
takes money from somebody who does not owe it. That is the opposite of the ESI
rounding, where rounding up protects the employee and the employer absorbs any
excess.

**What I did:** the rate is now a named gap, like the §47 fee. The Act's own
ceiling (24%, "not exceeding twenty-four per cent") is kept because it is in the
Act. The refusal names both notifications. The engine works the moment somebody
writes the figure in, and a test proves that.

**What I need from you:** which notification governs. It is one line to record.

Worth noting: this is now the **sixth** thing held as a gap because
`.gov.in` is unreachable from this environment (the §47 slabs, the §50(3)
rate, the §44AB figures, the e-way distance slabs, the §206AB omission date,
the §201(1A) month convention). If you have a CCH / Taxmann / ClearTax Pro
subscription or anything that would let this machine read a notification, that
one change would close more open items than any code I could write.

---

## 8. I removed a control on the Team screen. Was it meant to be real?

The Team page had a **per-member module access grid** — a checkbox per person
per module, headed "Changes are saved instantly. Overrides the role default for
that individual."

It did nothing. The ticks went into browser localStorage; `core/permissions.py`
has no per-member override concept; and `rbac()` decides every request from the
ROLE alone. A Partner who unticked Payroll for an Executive believed they had
removed access, and had not — not for that user, not on that machine, not for
one request.

**What I did:** made the grid read-only and served it from the real matrix, so
it now shows what each member's role actually grants. I did not wait to ask,
because a control that misstates who can see payroll is worse left running for
a night than removed. It is one commit to revert if you disagree.

**What I need from you:** was per-person override ever intended? If yes it is a
real build — a table, a change to `rbac()`, and a decision about whether an
override may GRANT as well as deny. If no, the read-only grid is the finished
answer and nothing more is needed.

While I was there I found the browser's copy of the permission matrix was
wrong in a way worth knowing about: it told a Partner that an **Executive**
could reach Clients and Tasks only, when the backend gives them Accounting,
GST, Income Tax, MCA, Reports and TDS as well.

---

## 9. Two screens I would like to delete, and will not without you

- **`/accounting/suppliers`** (PUR-16) writes `public.suppliers`, which no
  purchase path reads — every one of them reads `public.vendors`. The TDS
  section and credit limit a CA records there reach nothing. The finding says
  "remove the route, or redirect it to the client's Vendors tab".
- **`/accounting/msme-tracker`** (PUR-15) wrote a hand-keyed `msme_payments`
  side table. **UPDATE, 13 September:** the screen is now a rendering of
  `GET /api/income-tax/msme-43bh`, which derives §43B(h) from `purchase_bills`,
  their payment allocations and `vendors.msme_status`. It reads and writes
  `msme_payments` no longer — but the TABLE is still there, with whatever rows
  a CA typed into it, and DROPPING it is a migration and your call. The screen
  itself I would now keep: it is the right place for the figure, it just
  needed to stop inventing it.

I have not deleted either screen. `/gst/reconciliation` was deleted on your
decision and I am treating these the same way. What is left here is two DROPs
— `public.suppliers` and `public.msme_payments` — and one repoint
(`/accounting/suppliers` → the client's Vendors tab, which needs
`credit_limit_paise` on `vendors` first).

---

## 10. The reading list — eight things blocked on a page I cannot open

**UPDATE, 14 September 2026, 22:20 IST.** This section used to say "nothing
else is waiting on you", and that was true when it was written. It is not now:
everything I could build without you is built, and what is left is almost
entirely documents.

**`docs/audits/what-to-fetch-for-me.md` is the list**, and it is written as one
trip per website rather than as eight scattered asks, because you offered to go
and get them. Each section says what page, exactly what I need off it, and what
it unblocks. Nothing in it is broken — every gap is already a named refusal in
the code with a sentence pointing at the document to read, and each engine
works the moment the figure is written in.

The order there is by value, and the top three are:

1. **cbic-gst.gov.in** — six late-fee notifications, and the §50(3) rate that
   is question 7 above. One sitting settles both halves of GST-21.
2. **einvoice1.gst.gov.in** — the INV-01 schema. The highest-value item in the
   file, because e-invoice IRN is one of only **two** statutory outputs
   software can complete end to end with no GSP or ERI registration.
3. **protean-tinpan.com** — the TDS statement file layout, so a CA stops
   re-keying the whole quarter into the RPU.

§8 of that file is a long tail worth knowing about even if you never fetch it,
and its first item is the largest single improvement available anywhere: 18
states levy professional tax whose slabs the product does not hold, so an
employee in Gujarat, Telangana, Andhra Pradesh or Kerala has it named as a gap
on the payroll run and a CA works it out by hand every month.

**One thing on this page is still a decision rather than a document**: BANK-11
step 3, below. It is the only item in the whole backlog waiting on your
judgement rather than on a page.

---

## 11. BANK-11 step 3 — how much a *trusted* rule may do unattended

This follows on from the conversation we had about bank rules, where I think I
explained it badly the first time. The short version of what is already true:

- **The product ships zero rules.** Every one is written by the CA, per client.
  That was your instinct and it is already how it works.
- A rule on its own only **proposes** — it fills in the draft and a human still
  clicks Pass.
- Auto-posting needs a **second, separate tick**: a Manager or Partner marks
  that rule *trusted*, and only then do its lines pass with no click.

So there are two gates, and the CA controls both. Steps 1 and 2 of BANK-11 are
shipped: a rule can now say which field it reads, which way it matches, and
which rule wins — previously a broad rule written in April permanently shadowed
a narrow one written in July, and the only remedy was to delete and re-create
the broad rule, which lost its trusted flag.

**Step 3 is the open question: should a rule be able to propose more than one
line?** Today a rule proposes a single account. It cannot say "this ₹11,800 is
₹10,000 rent and ₹1,800 GST", and it cannot tag the party.

- **Matching wider was safe to build** — a CA types every pattern, and the
  widest case was always reachable anyway (an empty pattern matches
  everything).
- **Proposing wider is different in kind**, because a trusted rule posts with
  nobody watching, and a split it gets wrong is a wrong journal in the ledger.

I said I would build **split legs and a party tag, and never a TDS treatment**
(that one decides a statutory withholding and belongs in front of a human). I
have **not** built it, because your answer read to me as "keep the CA in
control" and I would rather have you say so explicitly than assume it.

Three ways to go, and I recommend the first:

- **(a) Build split legs + party, leave TDS out.** A trusted rule can post
  rent-plus-GST in one go. This is what the CAs will ask for first, and it is
  where the repetitive typing actually is.
- **(b) Build them, but only for UNtrusted rules** — a split rule always stops
  for a click, however trusted. Safest, and still removes the typing.
- **(c) Leave it.** A rule proposes one account, full stop. Nothing is lost
  that exists today.

A guard currently asserts `RuleSuggestion` gained no field, so whichever way
you go it is a deliberate change rather than a drift.

---

## 12. Two modules that hold a rule nothing applies  *(found 14-09-2026)*

A sweep for "what under `domain/` does nothing import?" found five modules.
Three are now wired up and shipped — the UQC list, the AS 11 year-end
revaluation and the §115BAC(6) regime election. Two are left, and neither is a
bug I should quietly decide:

### 12a. The bank exception rules — 315 lines nobody asks

`domain/banking/exceptions.py` decides **what a partner should look at** on a
bank transaction: an unfamiliar payee, a round-sum amount, a duplicate shape, a
weekend date. It is careful, well argued and well tested, and its only importer
is its own test. Its docstring says the context is gathered by
`services/bank_exception_service.py` — **that file does not exist.** So no flag
is raised and no partner ever sees one.

The module itself says that nothing here GATING a posting is a product
decision, not an oversight, and I agree with that part: a platform should not
hold a CA's books hostage to a threshold it invented. But *raising* a flag and
*blocking* a posting are different things, and today it does neither.

**What I need from you: do you want a partner review surface at all?** Options:

- **(a) A "Worth a look" list** on the banking screen — the transactions the
  rules flagged, with the reason, and nothing blocked. This is what the module
  was written for and it is a few hours.
- **(b) Nothing.** A firm reviews how it reviews; the rules stay as reference.
  I would then say so in the module rather than leave it reading as unfinished.
- **(c) Something else** you have in mind from how your firm actually reviews
  junior work.

I have not guessed. It is named in
`tests/test_a_domain_module_has_a_reader.py` so it cannot be forgotten.

### 12b. A duplicate notification service

`domain/notification_service.py` is an older copy of
`services/notification_service.py` whose store is a hardcoded
`MOCK_NOTIFICATIONS` list. The live one is what `routers/tasks.py` calls;
nothing in the production tree imports the copy.

It is harmless today and the hazard is the `public.suppliers` shape: a future
reader reaches for the name, gets the mock, and writes notifications nobody
receives. **Deleting it is the right end state and is your call**, like the two
DROPs in §9 above.

---

# ANSWERED — 13 September 2026, evening

Six things were put to the owner after PR #523 went green. All six came back
in one message. Recorded here verbatim in substance, with what each one
settles, because a decision that lives only in a chat log is a decision nobody
can find later.

## 13. A rate master for foreign currency — one decision inside it  *(found 15-09-2026)*

**Not urgent, and not broken.** Recording it because the sweep that found it is
exactly the sweep that found ACC-19, and because the decision inside it is
yours rather than mine.

`fx_rates` (migration 146) exists to hold operator-entered exchange rates.
`ManualRateProvider` reads it — latest rate on or before the document's date —
and **nothing has ever written a row.** When a foreign document is created
without an explicit rate the lookup finds nothing and the API answers:

> *No exchange rate available for USD→INR on 2026-09-15. **Record the rate
> first** or enter it manually.*

There is no way to record it first.

**Why this is not a live defect today:** both screens that create a foreign
document — Sales and Purchases — *require* the CA to type the rate, so every
document takes the manual-override branch and the lookup is never reached. The
feature works; what is missing is recording the day's rate ONCE instead of on
every document. ACC-19 made multi-currency switchable on 13-09-2026, so this
became reachable two days ago and has never been exercised.

**The decision I will not make alone.** Migration 146 declares `fx_rates` as
**global reference data** — no `firm_id` column, readable by every
authenticated user, "writes go through the service role". That is defensible:
USD→INR on a date is a fact about the world, not about a firm, and RBI
publishes one. But it means one firm's typo silently moves another firm's
books, and this codebase's tenancy rule is otherwise absolute — every query
carries `.eq("firm_id", …)`. A firm-scoped rate table is a different design
and a migration.

So: **(a)** build it global, Partner-only to write, with the screen saying
plainly that a rate is shared across the platform; **(b)** make it firm-scoped
first, which is a migration and changes the provider's lookup; or **(c)** leave
it, and change the refusal message so it stops promising a screen that does not
exist. (c) is an hour and is the honest floor. I lean **(a)** if you expect
several clients with foreign business and **(c)** if you do not.

---

## A. Merge #523 — **"Merge all of them"**

Merged as `523ad02e`, squash, on a green head. Migrations **374–381** applied
to production by the `apply pending migrations — production` job.

## B. ACC-19, multi-currency — **"did not understand the question, but I have always trusted you"**

The question restated: the whole multi-currency feature is BUILT — foreign
documents, realised and unrealised FX, five report endpoints, foreign bank
accounts — and cannot be switched on, because `resolve_currency_policy` ANDs
three flags and two of them (`firms.multi_currency_entitled`,
`clients.multi_currency_enabled`) are written by **nothing**: no endpoint, no
model field, no screen, no seed. Only a hand-written SQL UPDATE activates it.
The open question was whether the FIRM-level one is a self-serve setting or a
commercial entitlement you sell.

**Decided: a self-serve Partner setting, plus the per-client opt-in.** There
is no billing, plan or entitlement machinery anywhere in this product, so
"commercial entitlement" has nothing to hang off — gating one checkbox would
mean inventing an entitlement system first, which is a larger and less useful
build than the feature it gates. A CA firm either has foreign-currency clients
or it does not; it is not a flag anyone games. If it is ever sold, the column
does not move: a plan check goes in front of the endpoint that sets it.
`MULTI_CURRENCY_ENABLED` stays an environment kill switch and must NOT get a
settings toggle — `core/feature_flags` says "No DB dependency" and means it.

## C. BANK-24, GST on bank charges — **"keep it general … they upload the transactions and the CAs only select on which transaction GST is there; we shouldn't presume, let the CAs do it, give them the modal where they can select"**

**This overrides the shape the finding proposed, and it is the right call.**
The finding wanted a monthly consolidated bank GST invoice modelled as a
document, matched against one GSTR-2B row. That presumes both the bank's
invoicing practice — `[S]`-graded, unconfirmable from here — and *which* lines
of a statement carry GST, which is exactly the guessing this codebase refuses
everywhere else.

**Decided: the CA marks the transaction.** A bank-charge line gets a control
where the CA says "this carries GST", at what rate, and whether it is
inter-state. `bank_matching_rules` already carries `suggested_gst_rate_bps`
and `suggested_is_interstate` (migration 254) as the per-bank DEFAULT, so the
rule proposes and the CA disposes — the same division of labour the rest of
the bank module uses. No bank-invoice document, no GSTIN on a bank table, no
inference from a narration.

## D. FA-08b, output tax on an asset disposal — **"I really am not aware of this, so you take the decision; if you need anything from somewhere you can't reach, tell me and I'll provide it"**

**Decided: build it, computing CGST §18(6) as the statute states it** — on a
supply of capital goods on which input tax credit has been taken, the amount
payable is the HIGHER of (a) the credit taken reduced by five percentage
points per quarter or part of a quarter from the invoice date (Rule 44(6)) and
(b) the tax on the transaction value. Both are computed and the higher is
taken, with the working shown, because "whichever is higher" is the operative
words and picking one silently is how a disposal under-declares.

**One thing I may come back to you for:** whether a particular disposal is a
"supply" at all — a scrapping with no consideration, or a transfer to a
related party — turns on facts the ledger does not hold. Those are named on
the answer rather than assumed, in the shape `vendors.msme_status` uses.

## E. ACC-16, journal line order — **"again did not understand, but I trust you"**

The question restated: open a voucher and its debit and credit lines come back
in whatever order the database happens to return. There is no "line 1, line 2"
column. The finding's fix — add the column and backfill every line already
posted — runs into migration 251, whose trigger **forbids touching a posted
journal line at all**, so the backfill would need the trigger disabled against
production, run, and re-enabled. That is a rare and reviewable act, and I was
not going to do it unattended for a presentational fix.

**Decided: no trigger is disabled and nothing is rewritten.** The column is
added for lines written FROM NOW ON, and the order for lines already posted is
DERIVED at read time — debits before credits, then creation order, then id, so
an old voucher displays the conventional way round and displays the SAME way
round every time. That is the same visible outcome as the backfill, with none
of the risk. Scheduled, not yet built.

## F. PUR-27, expense claims — **"we don't do the accounting, the CAs do, so it's their responsibility … we have given the attachment, if they want they can attach it, it's their call"**

**Decided: not building an expense-claim document.** The banking voucher path
plus `domain/banking/attachments` is the answer, and the CA confirms the claim
with their client as part of their own engagement. Recorded as
`not_a_defect_as_stated` rather than left open, so nobody re-opens it as a
gap: it is a scope decision, not a hole.

## G. PUR-32, a duplicate supplier with no GSTIN and no PAN — **not yet asked**

**Not blocking anything, and nothing has been built either way.** Raised here so
the decision is yours rather than mine by default.

`routers/vendors._match_existing_vendor` blocks a duplicate on GSTIN first and
PAN second, and all three call sites are wrapped in `if gstin or pan`. An
UNREGISTERED supplier — a local hardware shop, a courier, a one-man contractor —
usually has neither, so re-uploading a vendor CSV or typing the name twice
creates two vendor rows for one supplier. Neither guard sees it:
`_near_duplicates`, which catches a bill entered twice, filters on
`vendor_id`, so the second bill is under the second vendor and looks like a
first.

The obvious fix is to match on the NAME as well, and that is what I did not want
to do unasked. The create endpoint does not REFUSE a duplicate — it returns the
EXISTING vendor with `duplicate: true` — so a name match would silently attach
the new bill to a vendor somebody else created, and two genuinely different
suppliers can share a name ("Sharma Traders" in two cities). Merging two real
suppliers is worse than the duplicate row, because it is invisible and it moves
money: their ledgers, their ageing and their §43B(h) position all become one.

**Two ways to go, and it is a product call:**

1. **Warn, never merge.** Create the vendor as asked, and return
   `possible_duplicates` naming the active vendors with the same normalised
   name, so the screen can say "you already have a Sharma Traders". Nothing is
   merged, nothing is refused, and the CA decides. This is the shape the
   three-way match takes (report, never block), and it is what I would build.
2. **Match on the name like GSTIN and PAN.** Cheaper, consistent with the two
   existing branches, and it will occasionally attach a bill to the wrong
   supplier with nothing to say it happened.

Either way it is a small change; what it needs is your answer to "is a same-name
supplier the same supplier?".

## H. SALES-23, automated payment reminders to your clients' customers — **not yet asked**

**Nothing is built and nothing is half-built.** This is the ONE finding still
marked `open` that is not blocked on a document I cannot fetch — the other four
wait on the NSDL FVU spec, the IRP schema, three more statutory forms and a
bank's NEFT layout. This one waits on you.

The finding asks for an automated reminder CADENCE: the product decides a
receivable is overdue and emails the customer, on a schedule, without anybody
pressing anything. A manual "send reminder" already exists and works.

**Why I stopped rather than built it.** The recipient is not your user and not
your client. It is your client's CUSTOMER — a third party who never signed up
for anything here, whose email address arrived in a CSV, and who will read the
message as coming from the client's business. Three things follow:

1. **It is outbound mail nobody in the loop authorised per message.** The CA
   configures a cadence once; the tenth reminder goes out months later to a
   customer who may have paid, disputed the invoice, or gone elsewhere. The
   product's standing rule everywhere else — never auto-submit, always an
   explicit confirmation click — exists for exactly this shape.
2. **DPDP.** `docs/compliance/06-data-protection-dpdp.md` already treats
   counterparty data as the largest population of third-party data principals
   in the product. Sending them mail is processing of a different order from
   storing a name off an invoice, and it needs a notice and a basis.
3. **It is the client's commercial relationship, not ours.** A reminder that
   annoys a customer costs the CLIENT the customer, and the CA carries the
   complaint. Every other product in this tier makes this opt-in per customer
   for that reason.

**Three ways to go:**

1. **Leave it manual.** The CA presses send, one customer at a time, as today.
   Costs nothing, decides nothing, and the finding closes as "not a defect as
   stated".
2. **A cadence the CA arms per CLIENT, with a per-customer opt-out and a
   preview of every message before the first one goes.** Automated after that.
   This is what I would build if you want it.
3. **A queue, not a sender.** The product proposes the reminders due today and
   the CA sends the batch with one click. No unattended outbound mail at all,
   and it removes most of the manual labour the finding is really about. This
   is the cheapest honest answer and it is the `Pass N ready` shape the bank
   queue already uses.

I have built none of them. Tell me which, or tell me to leave it.
