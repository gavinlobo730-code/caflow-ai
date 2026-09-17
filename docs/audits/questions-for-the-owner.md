# Questions for the owner — and what was decided

**Your instruction, 17 September 2026:** *"any compliance question please you
research and take those decisions, and code questions you take those
decisions."*

So this file changed shape twice in one day. **Fifteen questions were open;
twelve were compliance or code and became mine; you answered the last three that
evening. Nothing is waiting on you.**

Every decision appears below with its reasoning, so you can overrule any of them
by saying so — a decision you cannot find is a decision nobody can revisit. Two
places where I did NOT do exactly what you asked are called out as such, in §2
(roles are kept as a template rather than deleted) and §3 (a gap you did not ask
about, not started).

---

## ONE THING CHANGED TODAY THAT AFFECTS THE WHOLE FILE

I can **search** the web from here. I could not, and this file was written
believing I could not.

That is a real upgrade and a limited one, and the limit matters:

| | |
|---|---|
| `curl https://cbic-gst.gov.in` | **refused** at the egress proxy |
| fetching a page — `.gov.in` or `taxguru.in` alike | **refused** |
| **searching**, and reading the result summaries | **works** |

So evidence here moved from *"written from knowledge"* to *"corroborated
across several independent secondary sources that agree"*. It did **not**
reach *"read off the notification"*. In this codebase's own grading that is
still `[S]`, not `[P]`.

**What that changes:** §7 (the §50(3) rate) is now answered, and §2's late-fee
slabs are answerable. **What it does not change:** §10's reading list still
matters for anything where a partial answer is worse than none — the
professional-tax slabs being the clearest case, because a half-right slab
table is a wrong deduction in somebody's pay, and a wrong deduction is worse
than a flagged gap. Search gives me fragments of those tables, not tables.

---

# NOTHING IS WAITING ON YOU

All three were answered on **17 September 2026** and all three are built. They
are recorded below with what was built and what I decided inside them, because a
decision you cannot find is a decision nobody can revisit.

---

## 1. Design reference implementation — **"the redesign like the functions and features won't change right its just the design then yes go for the banking module"**  *(was §6)*

**Banking Entries.** Presentational only, confirmed: same endpoints, same
posting paths, same `entry_state`, same Pass verb, same trusted-rule behaviour.

**What the work turned out to be, which was not what the question assumed.** The
question read as "invent a look". The palette was already designed —
`tailwind.config.ts` and `app/globals.css` have carried deep blue `#182350`,
powder `#AFD2FA`, premium gold `#B9915E`, a type scale and three named shadows
since the app was built. **Nothing read it.** 10,283 colours were spelled as
Tailwind arbitrary values across 263 files, banking used the tokens **zero**
times in 5,783 lines, and three different "primary" colours were live at once.

So the redesign is APPLYING the brand rather than choosing one, and the reason
it had gone unapplied was that the token set could not say what a screen needed:
no ink scale, no state colours, no single primary. Three decisions were mine
inside that:

* **Ink is named by ROLE, not numbered** (ink / body / label / hint / disabled),
  and has **four** steps rather than three — the app ran two hover conventions
  side by side (104 sites hint→label, 67 label→body) and a three-step scale
  collapsed one so the hover silently stopped changing anything. The first pass
  did exactly that; the check caught it.
* **State is a first-class token** (ready / attention / problem / done). A CA
  reads a bank screen for state before they read it for text.
* **Money direction is NOT state.** The first pass mapped "Deposits" to the
  ready green and "Withdrawals" to the problem red, because those were the
  colours that file held. Both are false signals — a withdrawal is half of what
  a bank account does. `money.in` / `money.out` / `money.negative` are their own
  scale and a test asserts they are not aliases.

Held by `apps/web/scripts/a-screen-reads-the-palette-it-was-given.test.ts`:
converted directories at zero, the rest of the app a measured ratchet.

## 2. Per-person module access — **"remove the role wise access and only keep person wise … they also have which clients have which access its per person right"**  *(was §8)*

**Built, as per-person permissions with the role kept as the template.** Your
observation was right and it is the precedent: `user_client_assignments` is
already per person, and a role is five buckets a practice is not staffed in.

**Where I did not do exactly what you asked, and why.** You asked to remove
roles entirely. I measured first: `public.get_my_role()` is asked at **61 sites
across 32 migrations**, and those RLS policies are what protect the ~83 tables
the browser reads directly over PostgREST, where `rbac()` never runs at all.
Rewriting them per-person is a migration touching ~50 tables whose failure mode
is a **silent cross-client read** — no error, no log, nothing that surfaces.

So the role keeps three jobs and loses the one that mattered:

| | |
|---|---|
| **Lost** | it no longer decides access — `user_permissions` does, and a row wins |
| Kept | answering those 61 SQL policies |
| Kept | `_FIRMWIDE_ROLES` — "every client, or only my assigned book" is about SCOPE, a different question this grid deliberately does not answer |
| Kept | the template a new hire's grid is pre-filled from, so onboarding is one choice rather than thirty silent toggles |

`rbac()` is the seam, so all **1037** of its call sites are unchanged. Three
states, not two — Role / Allow / Block — because a two-state control could never
hand a permission back to the role. **No backfill**, so nobody's access moved on
the day it landed. A Partner cannot be denied the four pairs that reach the
screen, or the grid becomes unrepairable.

**Say the word if you still want roles gone entirely** — the grid is already the
authority, so what remains is the 61-policy rewrite, and it is the part I would
want to do slowly.

## 3. Emailing your clients' customers — **"Yes ofc that is a feature right not auto email … there is a send button right from there"**  *(was §H, SALES-23)*

**Confirmed and already correct — nothing was built, because nothing needed to
be.** The sales-invoice send is manual, goes through the backend, runs
`rbac("invoice","write")`, stamps a delivery row, and is honest about failure:
`success: false`, the row marked `failed`, the real provider reason in the
server log only, and the screen checks `result.success` rather than showing a
false "sent". No auto-send exists anywhere. An unverified Resend domain
therefore surfaces as a visible error, which is the right behaviour.

**One gap you did not ask about.** There are exactly **three** send buttons in
the product — engagement letter, payment link, sales invoice. Purchase has none
and should not (a bill comes *from* the vendor). But a **purchase order** is a
document your client sends *to* a vendor and has no send path, and nor do
quotations or proforma invoices. Each needs its own PDF service (there are six
today, one per document kind), so it is a real build rather than the wiring I
first said it was. **Not started — say if you want it.**

---

# DECIDED — compliance

## §50(3) is 18%, not 24%  *(was §7 — the one I most wanted answered)*

**Searched and corroborated.** Section 111 of the Finance Act 2022 substituted
§50(3) retrospectively from 01-07-2017, and **section 116 of the same Act read
with the Sixth Schedule** retrospectively amended the 28-06-2017 rate
notifications from 24% to **18%**, brought into force by **Notification
9/2022-Central Tax dated 05-07-2022**.

That is a correction to my own earlier note, which had the mechanism as
"Notification 09/2022 notified 18%". 9/2022 brought the provisions into force;
the rate change was s.116 + the Sixth Schedule.

**Decided: 18%. BUILT** — `SECTION_50_3_NOTIFIED_RATE_BPS = 1800`,
`SECTION_50_3_RATE_VERIFIED = False`, the source on every charge as a caveat,
the Act's own 24% ceiling still recorded as the ceiling it is, and the constant
left `Optional` with a test exercising the withdrawal branch so it cannot rot.

**Why I am comfortable deciding this:** the direction of the doubt was what
made me refuse before — 24% takes a third more money from a taxpayer who does
not owe it. Several independent sources now agree on 18% and none argues for
24% post-2022. Holding out for a figure I cannot fetch would keep a working
engine switched off over a doubt the evidence no longer supports.

## §47 late fee — write the slabs in, flagged  *(was §2, the remaining half)*

**Searched and corroborated**, and they match exactly what this file had
recorded as unverified belief: **₹50/day** (₹25 CGST + ₹25 SGST), **₹20/day**
for a nil return (₹10 + ₹10), nil capped at **₹500**, and the turnover caps
**₹2,000** (AATO ≤ ₹1.5cr), **₹5,000** (₹1.5cr–₹5cr), **₹10,000** (> ₹5cr) —
Notification **19/2021-Central Tax dated 01-06-2021**, on the 43rd Council's
recommendation.

**Decided: option (a), which I had previously recommended against.** The
ground for refusing was *"a late fee written from memory is a number a CA
would pay over"*. That ground was about MEMORY, and it is weaker now. The
figures go into an FY-versioned registry, `[S]`-graded, `verified=False`, each
pinned by a test, and **the screen says the figure is unverified and names the
notification** — because a CA who currently gets nothing computes it by hand,
which is not obviously safer.

## A purchase return after the tax was withheld  *(was §1, PUR-23 ≡ TDS-32)*

**Decided: record the challan date and automate both branches.** The statute
does not choose between recomputing the aggregate (§194J(1)) and letting the
deduction stand with an excess deposit (§200/§199) — but which applies turns
entirely on **whether the challan has gone**, and that is a fact the books can
hold and currently do not.

So the answer is not to pick a branch. It is to record the one fact that makes
the question answerable, and then each case answers itself. That needs a
migration on `tds_deductions`.

Until it ships, the current behaviour is unchanged and correct: state the
divergence, change no figure.

## The professional-tax slabs stay a gap — for now, and per state

**Not decided by research, because the research is not good enough.** Search
gives me fragments: *Gujarat abolished its four-band schedule, nil below
₹12,000; Telangana and Andhra Pradesh nil to ₹15,000 then ₹150/₹200; Kerala is
HALF-yearly, capped ₹1,250 per half.* Those are shapes, not tables.

**A wrong PT slab is money out of an employee's salary**, and the employer
still owes the right figure — so a half-right table is worse than the named
gap the product shows today.

**Decided: add states ONE AT A TIME, only where the full table corroborates,
and never a partial one.** Kerala's half-yearly period alone means it cannot
share the monthly shape the four existing states use. This is now incremental
work rather than a blocked item.

---

# DECIDED — code

## Delete both dead modules and both dead tables  *(was §9 and §12b)*

- **`domain/notification_service.py`** — an older copy whose store is a
  hardcoded `MOCK_NOTIFICATIONS` list. **Done 17-09-2026, and NOT by deleting
  it: the premise "imported by nothing" was false.**
  `repositories/notifications_repository.py` imports `MOCK_NOTIFICATIONS` and
  `_notif_index` from it inside an `if _USE_MOCK:` block, so it is the fixture
  store the entire ~15,800-test mock suite runs against; the delete this
  section authorised would have broken every test in it. The hazard was real
  and is what got fixed — the file is **renamed to
  `domain/notification_fixtures.py`** so its name stops competing with
  `services/notification_service.py`, and the six module-level functions that
  read as an API (`create_notification`, `get_notifications`, `mark_read`,
  `mark_all_read`, `get_unread_count`, `get_notification_stats`) are deleted,
  each verified at zero callers first — every apparent reference was the
  router's own endpoint function or the repository's own method sharing the
  name.

  **Why nobody caught it:** `tests/test_a_domain_module_has_a_reader.py`
  listed the production roots by hand and `repositories` was not among them,
  so twenty-seven modules the routers import all day were invisible to the
  scan and the entry's "nothing in the production tree imports it" passed.
  The roots are **derived from the tree** now, which is the rule rather than a
  spelling of it.
- **`/accounting/suppliers`** — repoint to the client's Vendors tab. Needs
  `credit_limit_paise` on `vendors` first, so it carries a migration.
- **`public.suppliers` and `public.msme_payments`** — both DROP. `suppliers`
  held **zero rows in production** when measured on 13-09-2026; `msme_payments`
  holds whatever a CA typed before §43B(h) started deriving the figure, and
  nothing reads it. Both DROPs need the production-fixture refresh in
  `docs/schema-drift.md`, which is why they are one change and not four.

## The bank exception rules get a "Worth a look" list  *(was §12a)*

`domain/banking/exceptions.py` — 315 careful lines deciding what a partner
should look at, whose only importer is its own test, and whose stated
collaborator `services/bank_exception_service.py` **does not exist**.

**Decided: option (a).** A read-only list on the banking screen showing what
the rules flagged and why. **Nothing is blocked** — the module's own argument
that a platform should not hold a CA's books hostage to a threshold it
invented is right, and raising a flag is not blocking a posting.

Building the surface rather than deleting the module, because the module is
good and the alternative is writing "this is reference only" on 315 lines of
working logic.

## `fx_rates` stays global, Partner-only to write  *(was §13)*

**Decided: option (a).** USD→INR on a date is a fact about the world, not
about a firm — RBI publishes one. A firm-scoped table would have every firm
re-typing the same number.

The tenancy objection is real and is answered by the WRITE side rather than the
schema: **Partner-only**, and the screen says plainly that a rate is shared
across the platform. If a typo ever does move another firm's books, the answer
is an audit trail on the write, not a per-firm copy of a public fact.

## A duplicate supplier: warn, never merge  *(was §G, PUR-32)*

**Decided: option 1.** Create the vendor as asked and return
`possible_duplicates` naming active vendors with the same normalised name, so
the screen can say "you already have a Sharma Traders".

Name-matching like GSTIN and PAN was the cheaper option and is wrong: two
genuine suppliers share a name ("Sharma Traders" in two cities), and silently
merging them is invisible and moves money — their ledgers, their ageing and
their §43B(h) position all become one. Report, never block, is the shape the
three-way match already takes.

## A trusted rule may propose split legs and a party — never a TDS treatment  *(was §11, BANK-11 step 3)*

**Decided: option (a).** A trusted rule can post "₹11,800 = ₹10,000 rent +
₹1,800 GST" in one go, and can tag the party. That is where the repetitive
typing actually is.

**TDS stays out**, and that is the whole safety argument: a withholding
decides a statutory liability under §201, and it belongs in front of a human
however trusted the rule. The two existing gates are untouched — the CA writes
every rule, and a Manager or Partner separately marks it trusted.

The guard asserting `RuleSuggestion` gained no field is updated deliberately
rather than deleted, so a third field later is still a decision.

## Three that were already shipped  *(were §3, §4, §5)*

- **§3 the migration queue** — you answered this: *"Merge them, no special
  treatment."* Followed since.
- **§4 PUR-22 and ACC-16** — both shipped.
- **§5 ACC-19** — shipped; multi-currency's firm and client gates are
  writable, with a Partner-only screen.

---

# STILL WORTH FETCHING — but no longer blocking

`docs/audits/what-to-fetch-for-me.md` stands, with its order changed now that
search works. What search **cannot** substitute for:

1. **einvoice1.gst.gov.in — the INV-01 schema.** A JSON schema is not
   summarisable; I need the file. Highest value in the list, because e-invoice
   IRN is one of only **two** statutory outputs software can complete end to
   end with no GSP or ERI registration.
2. **protean-tinpan.com — the TDS statement file layout.** Same: a binary
   file format, not a fact.
3. **The professional-tax slabs**, per state, as complete tables.


---

# ANSWERED — 13 September 2026, evening

Six things were put to the owner after PR #523 went green. All six came back
in one message. Recorded here verbatim in substance, with what each one
settles, because a decision that lives only in a chat log is a decision nobody
can find later.

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
