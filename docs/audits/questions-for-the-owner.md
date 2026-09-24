# Questions for the owner — and what was decided

**Your instruction, 17 September 2026:** *"any compliance question please you
research and take those decisions, and code questions you take those
decisions."*

So this file changed shape twice on 17 September. **Fifteen questions were
open; twelve were compliance or code and became mine; you answered the last
three that evening.** Four things have accumulated since — the block below says
what they are, and none of them is a preference.

Every decision appears below with its reasoning, so you can overrule any of them
by saying so — a decision you cannot find is a decision nobody can revisit. Two
places where I did NOT do exactly what you asked are called out as such, in §2
(roles are kept as a template rather than deleted) and §3 (a gap you did not ask
about, not started).

---

## G3 — **Five of the hub's fifteen tiles have no firm-level screen to open** · 🤝 needs you

**Not blocking.** The hub's domain authority is built and this is modelled
honestly; I am asking because the answer changes how the firm hub LOOKS, and
you have said you care about that.

D1 fixes the hub at fifteen tiles. Writing the guard that checks each tile's
destination — rather than trusting the path I had typed — found that **five
modules have no firm-level screen at all**:

| tile | firm-level screen |
|---|---|
| Banking | **none** |
| Purchases | **none** (`/accounting/payables` does not exist) |
| Fixed Assets | **a tombstone** — `/accounting/fixed-assets` renders `MovedToClientWorkspace` |
| Inventory | **none** |
| Year-End | **none** |

The tombstone is the one worth pausing on: it is *worse* than a missing route.
A 404 is obvious. A page that exists, renders, and says "this feature moved to
the client workspace" looks like a working destination right up until the CA
reads it — and a tile showing a real number above it is the exact stub 2.2
exists to forbid. `/accounting/invoices` is the same shape.

The ten others are real screens and open properly.

**What I would do, if you would rather not think about it: build the five.**
A firm-level roll-up is a STATIC route, so — and this is the part that makes
it cheap — **it costs none of D10's dynamic redirect rules.** The constraint
that forbids new routes under `/clients/[id]`, the one that 404'd the whole
client workspace once, does not reach these at all. Each is a list of clients
with that module's outstanding figure beside each, which is the same query the
tile already needs.

**The alternative** is that those five tiles show their firm-wide figure and
link to the client list, so the CA picks a client first. Cheaper, and honest,
but five of fifteen tiles landing on the same page is a worse hub than the
other ten deserve.

Either way the code change is one line per tile: `firm_href` is `None` today
and `MODULES_WITH_NO_FIRM_SCREEN` names all five, with a test that fails if a
tile claims a firm screen it does not have — or points at a tombstone.

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

# WHAT IS WAITING ON YOU — as at 24 September 2026, 14:05 IST

**THREE THINGS, all raised during the afternoon's work and none of them urgent.**
(A fourth, B, was raised and then decided — it is struck through below with the reason.)
Each is here because it is a decision about SCOPE or about reaching real people,
which your instruction of 17 September does not hand to me. Nothing is blocked
on any of them — I have kept working around all four.

| # | the question | why it is yours and not mine | what I would do |
|---|---|---|---|
| **A** | **Should the nightly sweep EMAIL a client's customers a payment reminder?** SALES-23's remaining half. The manual bulk Remind is built and the sweep flags overdue invoices internally; what it does not do is send anything. Migration 405 deliberately stopped it advancing the "reminder sent" counter, because it sends nothing | It is the product sending mail, unprompted, to somebody who is not our user and did not sign up — a client's customer. That is a posture decision, not a code one, and it is the one thing in the sales module that reaches a stranger | Build it **opt-in per client**, with a cadence the CA sets and a first run that shows exactly what would go out and to whom. Not on by default, ever |
| ~~**B**~~ | ~~A customer credit limit — warn, or block?~~ **BUILT the same afternoon — see D20 below.** I raised it and then took it back: your instruction of 17 September hands me code decisions, the finding already specifies the default, and nothing is refused unless a firm deliberately switches it on | — | Migration 414 landed. Overrule it by saying so |
| **C** | **Cost centres.** ACC-13's remaining half — a dimension column on `journal_lines` and a picker on every posting path | Structural. The finding itself says it "belongs in a planned phase, not a side effect of another task", and it touches the posting kernel's own table | Not now. It is a Phase 3 (analytics) item, and it wants the redesign's navigation first |
| **D** | **Extra-shift depreciation.** FA-11's remaining half, and it is BLOCKED ON A DOCUMENT rather than on you: Schedule II Part C in `domain/fixed_assets/schedule_ii.py` holds the useful LIVES and **not the NESD markings**, and extra-shift depreciation applies only to classes that are not marked NESD | Not a decision — a fact nobody here holds. Reading it from memory would charge 50% or 100% extra depreciation on asset classes the Schedule exempts | Add it to the reading list as **document #9**, beside the ITR schemas and the PT slabs |

Everything else that had accumulated before today was put to you this morning
and answered. The answers are recorded as **D10–D21** in
`docs/plan/THE-PLAN.md` — that file is the authority; this one keeps the
reasoning behind each.

**Two more were taken by me later the same day under the 17 September
instruction, and both are written up in full as decisions rather than buried
in a commit, so you can overrule either in one sentence:** **D20**, the
customer credit limit (warn by default, refuse only where a firm switches it
on, never on an opening document — migration 414), and **D21**, a dead API
endpoint that duplicates a live one. D21 is the one worth a glance, because it
is a DELETION: `PATCH /api/team/{user_id}/role` and `PATCH
/api/identity/users/{user_id}/role` both changed a member's role, the Team
screen has always called the second, nothing anywhere called the first, and
the two validated against different role lists. Restoring it is a revert. The
other three unreachable endpoints found in the same pass were wired up rather
than removed, because each was the only way to do something a CA needs.

---

## The morning's four — answered

**NOTHING is outstanding from these.** All four were put to the owner on the
morning of 24 September and answered the same session.

This block is regenerated whenever an item is added or answered. A status line
nobody re-reads is worse than no status line, because it is believed.

| § | the question | the answer, 24 Sep | what it changed |
|---|---|---|---|
| **N** | Does a Cloudflare preview serve `/clients/anything/bank` by directory-index lookup? | **No — it 404s or bounces to the trailing-slash form.** The owner opened the URL | The 41 bare-path rules are LOAD-BEARING and cannot be collapsed. **98 of 100, two rules of headroom, against a cap that fails silently.** Binding on the whole redesign: no new route under `/clients/[id]`, query parameters only. D10 |
| **M** | A font licence posture, so a PDF can print ₹ | **Keep `Rs.` for now** | Nothing changes. CGST Rule 46 prescribes no currency symbol, so this is cosmetic, and both candidate fonts cost something real — FreeSans is a metric drop-in but GPLv3 *in this repo*, DejaVu is permissive but 1.13–1.26× wider and re-breaks the invoice columns T5a-4b just fixed. Reversible in one commit. D13 |
| **L** | Where a CA is told a posting fell back to the generic Bank ledger | **The entry row AND the posting confirmation** | Phase 1.4. The row so it is visible while scanning the ledger, the confirmation so it is caught when it is cheapest to fix. D14 |
| **#164** | Six documents this environment cannot fetch | **The owner will get all six, later. Tracked, not blocking** | Nothing stalls. Every one is already a NAMED gap in the product rather than a wrong number. D18 |

### Four more were answered in the same session, and they were not on this list

Each had been recorded below as a design question with a default taken. The
owner took them properly instead.

| § | the question | the answer | what it changed |
|---|---|---|---|
| **H** | The type scale's leading — 379 hand-written sizes, 244 of which re-flow on conversion | **Convert all of them — module by module, with a before/after screenshot check on each.** The 135 off-scale first | The owner's own reasoning decided the method: *"one would be good for one screen but not for the other."* There is no single correct line height, so it cannot be a codemod. The smoke walk already renders all 160 screens, which makes "before" and "after" observable rather than discovered later. D12, Phase 1.1 |
| **J** | One content width, or width by content | **Width by content type** | Tables full-width to the ~1600px cap; prose and forms keep their measure. D11, Phase 1.2 |
| — | Order of the remaining tracks | **Navigation → analytics → portals → demo firm** | D15. The analytics screens and the portal both need somewhere to live |
| — | Filing to the portals | **Stay prepare-only. Keep the simulation, sharpen its wording professionally, say real filing is coming.** The owner starts the registrations once a CA demo happens | D17, Phase 1.5 and Phase 7. GSP/ERI/NIC are months of commercial lead time; the demo is what justifies starting them |

### And the one judgement call was answered too — D19

BANK-11 step 3: may a *trusted* matching rule — one that posts with nobody
watching — decide a **TDS treatment**? Split legs and a party were already
built.

**Answer: no. It posts the payment and FLAGS the line for a TDS decision.**

The owner took the middle option, and it is the right shape. The case FOR
deciding it was real: rent (§194I), professional fees (§194J) and contractor
payments (§194C) are exactly the recurring lines a trusted rule exists for, so
a rule that posts the payment and skips the withholding sends the CA back to
every one of them anyway. The case against is the asymmetry — an
under-deduction **disallows the whole expenditure** under §40(a)(ia), puts the
tax on the client under §201(1) with §201(1A) interest, and is **invisible**:
the entry posts, the books balance, the P&L reads fine, and it surfaces in an
assessment order two years later. A rule that picks the wrong ACCOUNT shows up
on a statement somebody reads every month; a rule that picks the wrong TDS
shows up in a notice.

A flagged line is visible. A wrong deduction is not. The CA gets a short
worklist instead of either a silent exposure or a full re-check.

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

## The bank exception rules get a "Worth a look" list  *(was §12a)*  **— BUILT 17-09-2026**

`services/bank_exception_service.py` — the collaborator the module's own
docstring named and which did not exist — plus
`GET /api/banking/worth-a-look` and a fourth Bank tab. Read-only: it holds no
threshold, no severity order and no message, and a test asserts it never calls
`blocks_posting` and issues no write of any kind.

Three things the build decided, each written down where it happened:
**the period is required and has no default** (an optional one is how a report
comes to read the whole ledger — BANK-07's shape); **"have we seen this payee
before" is asked the other way round**, `.in_()` over the PERIOD's own payees
rather than reading the history, stopping as soon as each is answered; and
**the history has THREE states, not two** — complete, truncated, and EMPTY.
The third was found by writing the test: on a client's earliest period every
payee is a first payee and every account one not used before, so both rules
fire on every row and the review list is the statement back again. Truncated
and empty each withhold those two rules, under their own sentence, because
"there is nothing to have seen" is a different thing to tell a partner from
"we could not tell".


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

## `fx_rates` stays global, Partner-only to write  *(was §13)*  **— BUILT 17-09-2026**

`GET /api/currencies/rates`, `GET /api/currencies/rate-types` and a
Partner-only `PUT /api/currencies/rates`, with the panel on
`/settings/multi-currency`.

**The table was read by the booking path and written by NOTHING.**
`ManualRateProvider` is what every foreign invoice, bill, receipt and payment
resolves its rate through, and no endpoint, field, screen or seed ever put a
row in `fx_rates` — so ACC-19's switchable gates let a Partner turn
multi-currency on and then find the one thing it needs could not be recorded.
The `capital_wip` and `fx_revaluations` shape a third time.

**The rate is TEXT all the way down.** The column is `NUMERIC(18,8)` precisely
so a rate is exact and `RateQuote` reads it back through `Decimal(str(...))`,
so it is typed, sent, stored and rendered as text; a JSON number would put a
float round trip in front of a column chosen to avoid one. **`source` is not
settable** — it is the provider identifier the reader matches on AND half the
unique key, so a settable one would write a rate nothing reads and turn a
correction into a second rate for the same day. **An existing rate for that day
is REPLACED** and the response says which happened; nothing reaches back into
documents already booked at the old rate, because a posted journal is immutable.

**The four rate types are served, not spelled on the screen**, and they are not
interchangeable — `gst_notified` is CGST Rule 34's rate notified under s.14 of
the Customs Act rather than the day's market rate, so one figure typed for all
four declares a different taxable value from the one the Act fixes.

**Decided: option (a).** USD→INR on a date is a fact about the world, not
about a firm — RBI publishes one. A firm-scoped table would have every firm
re-typing the same number.

The tenancy objection is real and is answered by the WRITE side rather than the
schema: **Partner-only**, and the screen says plainly that a rate is shared
across the platform. If a typo ever does move another firm's books, the answer
is an audit trail on the write, not a per-firm copy of a public fact.

## A duplicate supplier: warn, never merge  *(was §G, PUR-32)*  **— BUILT 17-09-2026**

`domain/party_duplicates.py` is the rule and it is on BOTH create doors —
vendors and customers, which have mirrored each other since they were written,
so guarding only one is one PATCH from guarding neither. One component,
`components/parties/PossibleDuplicatesNotice.tsx`, renders it on all three
screens that create a party.

Two limbs, reported separately because they mean different things: an exact
match of the normalised name, and the same BASE name under a different entity
form (`Sharma Traders` against `Sharma Traders Pvt Ltd`) — which is at once the
commonest real duplicate and a real pattern of its own, since a proprietorship
and the company that succeeded it are two parties. **The entity form is
canonicalised, never removed**: `Pvt Ltd` / `Private Limited` / `P Ltd` fold
together, and an **LLP does not fold into them**, because the LLP Act 2008
makes it a different legal person with its own PAN and its own return.
Dropping the form altogether is the obvious simplification and would report
those two as one party.

**Decided: option 1.** Create the vendor as asked and return
`possible_duplicates` naming active vendors with the same normalised name, so
the screen can say "you already have a Sharma Traders".

Name-matching like GSTIN and PAN was the cheaper option and is wrong: two
genuine suppliers share a name ("Sharma Traders" in two cities), and silently
merging them is invisible and moves money — their ledgers, their ageing and
their §43B(h) position all become one. Report, never block, is the shape the
three-way match already takes.

## A trusted rule may propose split legs and a party — never a TDS treatment  *(was §11, BANK-11 step 3)*  **— PARTY BUILT 17-09-2026; the split half was already there, and the rest is a different question**

**The worked example in the decision was ALREADY BUILT.** "₹11,800 = ₹10,000
rent + ₹1,800 GST" is `bank_matching_rules.suggested_gst_rate_bps` +
`suggested_is_interstate` (migration 254), which travel through
`draft_gst_rate_bps` into `bank_posting_service.build_inclusive_lines` and have
posted unattended for months. Checking that before building is the fifth time a
recorded premise has turned out to be wrong.

So what needed building was the PARTY, and migration 404 is only that:
`payee_type` / `payee_id` on the rule, `draft_payee_*` on the transaction, and
`bank_payee_service.apply_rule_party` — which goes through `set_payee`, the
human door, so the firm-and-client check on a polymorphic id still runs.
**What the line already says wins**: a rule saying "this is vendor X" does not
rewrite what the statement called the counterparty.

**A GENERAL SPLIT LEG IS STILL OUT, because the decision does not settle its
shape.** A rule cannot know a future amount, so fixed amounts fire only on
identical totals and PERCENTAGES are the only form that generalises — 60%
factory / 40% office on a bill that differs every month. That is a different
feature from the example above and is worth having; it needs its own decision.
**TDS stays out** and the guard asserts both by name.

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

---

# What the redesign work surfaced — 19 September 2026

Five slices landed overnight (PRs #560–#563). Each is described in its own
commit; these are the **decisions left for you**, and nothing below is blocking
— the work went round them.

## G2. TWO AUTHORITIES DISAGREE BY A ROLE TIER ABOUT A FEE ENGAGEMENT, AND ITS STATE MACHINE HAS NO CALLER AT ALL  *(new, 24-09-2026)*

> ### ✅ ANSWERED 24-09-2026 — *"I thought we were going to change the control from position to per individual right?"*
>
> That reframes the question rather than picking one of its two options, and it
> is the right reframing: **the control is the per-person grid, and the tier is
> only the template it falls back to.** Three things followed.
>
> **1. The two authorities now name the same resource — `billing`.** The row
> carries the fee; migration 260's RLS read it that way and its comment says
> so. **This removes nothing anybody can do today**, which is what made it
> decidable rather than a second question: `apps/web` mentioned
> `/api/engagements` NOWHERE, and the billing screen's own PostgREST insert was
> already refused for a Manager by that RLS. No journey existed in which a
> Manager created a fee engagement. Pointing the router at `engagement` was
> pointing the grid at the wrong checkbox for this row.
>
> **2. The screen goes through the API and the state machine has a door.**
> `lib/api` has an `engagements` namespace; six of the router's seven endpoints
> now have a caller (the seventh is `generate-obligations`, which is
> `compliance:write` and belongs on a compliance screen). Every step goes
> through `POST /{id}/transition`, which validates and writes `audit_log` and
> the client timeline.
>
> **3. A status the database cannot hold is gone.** The screen's own type said
> `status: "Active" | "Paused"`, and **"Paused" is not one of the seven
> migration 108's CHECK allows**. Building a Pause button would have written a
> row Postgres rejects. The screen now offers exactly what the state machine
> allows from the current status, and a test pins the browser's copy of that
> map to the router's and both to the CHECK.
>
> ### ✅ AND THE STEP THAT MAKES THE GRID REAL — migration 415, approved and landed
>
> Migration 260's policies asked `my_role_at_least(...)` and nothing else, so a
> Partner who granted one Manager `billing:write` on the Team screen got a
> person who **passed `rbac()` and was then refused by Postgres** — the grid
> vetoed by the control it replaced, arriving as a save failure with no reason.
> `public.my_permission(resource, action, minimum_role)` is the SQL twin of
> `resolve_permission` and those nine policies now ask it.
>
> **No table's minimum ROLE moved**, which is what makes it safe: 403 wrote no
> backfill, so against an empty `user_permissions` it reproduces today's
> behaviour exactly, and that branch is the first thing the test file proves.
>
> **The guard found a lockout before it shipped.** The first draft asked
> `billing:delete` for the DELETE policies on `fee_invoices` and
> `fee_engagements` — and PERMISSIONS defines no such pair, which
> `resolve_permission` treats as INERT and falls through to `can`, which fails
> closed. Every fee invoice and fee engagement would have become permanently
> undeletable, **for a Partner too**. The delete-action set is now asserted
> against PERMISSIONS rather than trusted.
>
> **A second thing the real database settled**: a grant is a MODULE, not a
> SCOPE. Migration 084's `<table>_assignment_scope` is an orthogonal
> RESTRICTIVE policy, so granting a Manager `billing:write` does not hand them
> a client they are not assigned to — which is exactly why 403 left the role
> answering the SQL policies and left scope alone. Both directions are pinned.
>
> ⚠️ **One test in this file was vacuous on its first run and is worth
> knowing**: a RESTRICTIVE policy's `USING` clause FILTERS the rows an UPDATE
> can see, so a refused UPDATE is `UPDATE 0` and psql exits **0**. The
> "a grant is one pair, not a tier" test asserted on the exit code and passed
> whether the policy worked or not. It measures the row now.


**The backlog item that led here said "fee engagements are created over
PostgREST, so `rbac()` and the state machine never run". Both halves are true
and neither is the defect.** Re-reading the code found something sharper under
each.

### 1. The same row is Partner-only in the database and Manager+ at the API

A fee engagement is a row in `fee_engagements` carrying `fee_paise` — what the
practice charges that client. Four facts, each read off the code today:

| | says | tier |
|---|---|---|
| `core/permissions.py` | `billing:write` | **Partner only** — its own comment: *"exposes fee economics"* |
| `core/permissions.py` | `engagement:write` | **Manager+** |
| migration 260 | RLS on `fee_engagements` | **Partner**, and its comment cites `billing` |
| `POST /api/engagements` | `rbac("engagement", "write")` | **Manager+** — and it inserts into `fee_engagements` |

This is not two write paths for one fact, which is the shape this codebase
usually finds. It is **two answers to "which permission governs this row"**,
one whole tier apart.

A Manager therefore passes the API's guard and is refused by Postgres.

> ⚠️ **This paragraph said the opposite when it was written, and the owner
> caught it.** It read *"with the service-role key the API path bypasses RLS
> entirely, so nothing catches it"*. **`USE_USER_JWT` is TRUE in production** —
> `render.yaml` records it in its own comment, `sync: false`, so no test can
> see the value — which means the backend queries as `authenticated` and **RLS
> is enforced on the API path too**. The disagreement is real and it resolves
> the other way: the stricter authority wins everywhere, so a Manager cannot
> create a fee engagement by any route.

And because the per-person grid (migration 403) resolves through `rbac()`, a
firm can grant or deny `engagement:write` on this row and never
`billing:write` — the grid is the authority and for this row it was pointed at
the wrong resource.

> **The question:** is a fee engagement **billing** (Partner) or **engagement**
> (Manager+)?
>
> My reading is **billing** — the row carries the fee, and the matrix says
> Partner *because of* that. That means tightening `POST /api/engagements` to
> `billing:write`, which **removes** access Managers have today; "who may work"
> is the area you already decided person-wise, so it is yours. The alternative,
> loosening migration 260 to Manager, widens who can see and set fee economics,
> and I would not do that without you saying so.

### 2. The state machine is not bypassed — nothing can reach it

`lib/api/index.ts` has **no `engagements` namespace at all**, and no file under
`apps/web` mentions `/api/engagements`. The whole router — seven endpoints — is
unreachable from the browser. The billing screen only INSERTs and SELECTs.

So `POST /api/engagements/{id}/transition`, which validates against
`ENGAGEMENT_TRANSITIONS` and writes both `audit_log` and the client timeline,
**has never been called.** An engagement is created `Active` and can never
change: there is no Pause, no Complete, no Cancel. The screen's own type says
`status: "Active" | "Paused"` and nothing in the product can produce `"Paused"`.

That is the `capital_wip` shape again — a built, guarded, audited path with no
door — and it is why the status-change audit entries do not exist.

### What I have NOT done, and why

Pointing the screen at the API is the small half. I have not done it, because
until the tier above is settled it would hard-code the wrong answer into a
screen, and because adding Pause/Complete is a real (small) build rather than a
rewire. Say the word on the tier and both halves go in together.

## G1. THE STATE VOCABULARY IS MISSING A STEP, AND THAT IS WHY BLUE IS EVERYWHERE  *(new, 24-09-2026)*

> ### ✅ ANSWERED 24-09-2026 — *"You decide"*, so: both, at the values already on screen.
>
> `state.working` (#1D4ED8, the `blue-700` the product was writing) and a
> five-step `sev` ladder (`ok / low / medium / high / critical`) are in
> `tailwind.config.ts`, and **186 class-lists across 56 files** now speak one
> of the two. **44 of those change hue** and the rest are the same colour at
> the token's own shade — the list is in the PR.
>
> **Three things turned up that the measurement above had not seen**, and two
> of them were live defects rather than tidying:
>
> 1. **A severity ladder that borrows two steps from the state set collapses
>    its own middle.** `app/risks` painted `critical` and `high` BOTH
>    `state-problem`; `app/work` and `app/tasks/templates` painted `high` and
>    `medium` BOTH `state-attention`. Two ranked steps rendering identically
>    is the one thing a severity chip may not do, and it is invisible in
>    review because each line reads fine on its own. It happened because
>    `sev.ok` and `sev.critical` deliberately share their hex values with
>    `state.ready` and `state.problem` — so the mixture looks right.
>    `a map paints with the severity ladder or the state set, never both` is
>    now a guard.
> 2. **Two screens disagreed about what `finalized` means.** The firm-level
>    payroll screen carried a note reading *"The accrual is posted. Still to
>    disburse"* with `needsWork: true`, and painted the chip GREEN; the client
>    payroll screen painted it green too. Both are `working` now, which is
>    what their own note says.
> 3. **A cancelled payment was called a failure by one pass and settled by the
>    next** — `bg-state-problem-surface text-state-done`, a red pill with grey
>    type, both halves tokenised so every rule written so far read it as
>    clean. `a tokenised surface and a tokenised ink name the same state` is
>    now a guard too.
>
> **And the vocabulary is still short of two words, which is recorded rather
> than guessed at:** *waiting on somebody OUTSIDE the firm* (five sites, all
> purple, `waiting_client`) and *queued, nobody on it yet* (one site,
> `app/workflows`' `pending`). Both were left exactly as they were. A fifth
> and sixth state invented to make a codemod tidy is how a vocabulary stops
> meaning anything.


**This reframes T4-b from ~5,840 judgements into two decisions and a codemod,
so it is worth reading before scheduling any more colour work.**

`tailwind.config.ts` has four state tokens: **ready** (nothing left to do),
**attention** (a person has to answer something), **problem** (it failed) and
**done** (settled, kept for the record). I measured what survives *inside the
67 maps that already speak that vocabulary* — maps whose author had already
decided this is a status, so the vocabulary should have covered them. **191 raw
colours are still there**, and they sort almost perfectly into three groups:

| hue | sites | the keys wearing it | is it determined? |
|---|---|---|---|
| green + emerald | **66** | `filed`, `paid`, `completed`, `approved`, `active`, `signed` | **YES** — this is `state.ready`, exactly |
| **blue** | **51** | `in_progress`, `received`, `prepared`, `running`, `sending`, `info` | **NO — there is no token for it** |
| orange + yellow | **27** | `high`, `medium`, `low`, `at_risk`, `needs_attention`, `fair` | **NO — a graded LADDER, and the set has three unranked severities** |
| purple, indigo, violet, sky, slate, gray, red | 47 | `waiting_client`, `viewed`, `refunded`, `cancelled`, `draft` | mixed — some genuinely categorical |

**The blue row is the finding.** A CA screen asks four questions — is it ready,
does it need me, did it go wrong, is it settled — and there is a fifth the
product asks constantly and cannot say: **somebody is on it.** A task
in_progress, a return prepared but not filed, a statement importing, a
reconciliation running. None of the four fits, so every screen reached for
blue. That is also why `blue` is the single largest colour in the codebase
(**2,101 utilities**) and why it collides with G0's primary question.

**The ladder row is the second one.** `critical / high / medium / low` is four
RANKED steps; `Healthy / Good / Needs Attention / At Risk / Critical` is five.
The state set has three severities and they are not a ladder — `ready` is not
"better than" `attention`. Painting a five-step health grade in three tokens
either collapses steps a CA is meant to tell apart, or forces raw colours back
in, which is where we came in.

> **The question, two parts:**
>
> **(1)** Add a fifth state token — call it `working` — for "somebody is on
> it"? My recommendation: **yes**, at the blue already in use, which is the
> same method that gave us `problem-hover` and `attention-hover` (name the
> value that is there, so nothing looks different).
>
> **(2)** A severity LADDER — four ranked steps — as its own small scale
> beside the states? My recommendation: **yes**, and it is the honest home for
> `critical/high/medium/low` and the health grades, which are not states at
> all.

**I have deliberately NOT converted the 66 determined green entries yet**, and
the reason is the point of this note: they are perhaps 40 minutes of work, and
doing them now means touching the same 67 maps twice — once for the greens, and
again when the two tokens above land and the blues and the ladders can go with
them. **One pass over those maps, after the decision, is cheaper and safer than
two.** If you would rather I did the green half immediately, say so and it goes
in on its own.

## G0. THE PRODUCT HAS THREE PRIMARY COLOURS AND THE BRAND IS THE SMALLEST — 547 sites  *(new, 24-09-2026)*

> ### ✅ ANSWERED 24-09-2026 — **"Navy"**. Done: 1,193 utilities across 162 files.
>
> **It was not three primaries. It was five.** Writing the guard for this —
> rather than converting the list the table below had counted — found two more
> that no measurement had: the **HSN library** screen's buttons and focus rings
> were **violet**, and the **treaty-rates** screen's were **sky**. Neither
> colour is in any palette; neither screen appears in the table. A list can only
> hold what somebody already counted.
>
> What moved, by role:
>
> | role | sites | from → to |
> |---|---|---|
> | the fill of a primary control | 313 | `bg-blue-600/700`, `bg-indigo-600`, `bg-violet-600`, `bg-sky-600` → `bg-brand` |
> | its hover | 251 | → `hover:bg-brand-dark` |
> | the focus ring | 387 | `focus:ring-blue-500` → `focus:ring-brand` |
> | the focus border | 148 | `focus:border-blue-*` → `focus:border-brand` |
> | the soft focus halo | 35 | → `focus:ring-brand-light` |
> | a border dressing a converted fill | 30 | → `border-brand` |
> | the disabled fill | 4 | → `disabled:bg-ps-disabled` |
> | selection rails, progress bars, wizard steps, the unread dot | 25 | → `bg-brand` |
>
> **The focus ring is the part that is an accessibility fix, not a brand
> change.** `focus:ring-brand` is **15.05:1** on white; `ring-blue-500` was
> **3.68:1**, which only just clears WCAG 1.4.11's 3:1 for a non-text
> indicator. White-on-navy is **15.05:1** against white-on-`blue-600`'s 5.17.
> `components/ui/field.tsx` had already written the rule down in its own
> docstring — *"THE FOCUS RING IS THE BRAND, NOT A STRAY TAILWIND BLUE …
> the fourth primary in a product that already had three"* — and it was true of
> that one component and of nothing else.
>
> **One thing is worse and it is recorded rather than papered over:** the
> hover step. `brand` → `brand-dark` is **1.18:1**, against `blue-600` →
> `blue-700`'s **1.30:1**. Both are subtle; navy's is subtler. It is about 6.7
> L\* units, which is above the just-noticeable threshold for a button-sized
> area, and I used the pair **already in use** on the 22 sites that were
> painting brand buttons rather than inventing a third navy for the hover —
> naming a value that is there is the method every other slice this week used.
> **If you want a stronger step, say so and it is one token.**
>
> **What is deliberately NOT navy**, each for its own reason: `text-blue-*`
> (a LINK — #182350 on white reads as body text, not as a link, so that is its
> own question); `bg-blue-50` / `bg-blue-100` panels and their hairlines (a
> TINT is a different role); the opacity-modified tints (`bg-blue-500/[0.08]`
> column shades, the dark hero's `/20`); `app/calendar`'s map keyed by
> COMPLIANCE AREA (a category — painting GST the brand would say GST is the
> primary area); and the `relationships` entity screen, which is DARK-ground,
> where navy is invisible and so is the wrong answer rather than the
> unconverted one. Both exceptions are allowlisted **with their reason**, and a
> second test fails if an allowlisted file stops holding one.


**This is G's question at ten times the size, and it was found by measuring
rather than by reading.** `tailwind.config.ts` says, in its own comment:

> *"there was no single primary, so three were in use at once — brand navy
> here, indigo #4338CA in banking, blue-700 on the Team screen. **What follows
> closes all three.**"*

It did not. The token was added; the sites were never converted. Measured on
24 September:

| what paints a primary button | sites |
|---|---|
| `bg-blue-600` | **303** |
| `bg-blue-700` | **244** |
| `bg-brand` + `bg-brand-dark` (the navy, #182350) | 200 |
| indigo (`bg-indigo-600` and its family) | 92 |

So **Tailwind blue is the product's de-facto primary, 547 to 200**, and the
brand navy the token file calls "the brand" is in the minority. A CA moving
between two screens sees the Save button in two different colours.

**I have NOT touched this and will not without you.** Every other colour slice
this week has been a tokenisation — naming a value already in use, so nothing
looks different (`state.problem-hover` is literally the `red-100` the code was
already writing). This one cannot be: whichever way it goes, **hundreds of
buttons change colour**, which is precisely the risk you named — *"there might
be a risk of some screens looking odd."* And D15 puts the redesign after
navigation, so it is not this phase's to decide alone.

> **The question, and it is one word:**
>
> **(a) NAVY** — the brand wins. 547 blue sites become `bg-brand`. The product
> looks like PracticeSync everywhere. Biggest visible change in the codebase,
> and the one most likely to need a screen-by-screen read afterwards.
>
> **(b) BLUE** — name what is in use. `blue-600` becomes the primary action
> token, the navy stays for the logo, the masthead and the marketing site.
> Nothing looks different; the vocabulary closes; the token file's claim
> becomes true.
>
> **(c) LATER** — leave it to Phase 2's redesign, where the whole screen is
> being looked at anyway.

**My recommendation is (b) or (c), not (a).** (a) is a rebrand dressed as a
refactor. (b) is the same method that has worked three times this week and
carries no visual risk. (c) costs nothing now and is the safest if the
navigation work is going to move these screens anyway.

Either way **the indigo (G, below) folds into whichever wins** — it is nobody's
brand and has no argument for it.

## G. The rival indigo — one decision, 55 sites

`#4338CA` (18), `#C7D2FE` (12), `#EEF2FF` (8), `#3730A3` (7), `#E0E7FF` (5),
`#6366F1` (5) — **55 sites across 7 files** on an indigo that is not `brand`.
The plan has called this "~40 sites" since T3-a; it was 55, measured 19 Sep —
and **92 on 24 Sep**, counted as Tailwind `indigo-*` utilities rather than as
hex literals, which is the same drift in a second spelling. See G0 above: this
is the small half of a 547-site question.

Folding them into `brand` (`#182350`) changes what the **executive dashboard,
copilot and workflows** screens look like. That is a visible change on three
screens, so it is yours.

> **The question:** is the indigo a second brand colour you want, or a drift to
> be folded into the navy?

## H. The type scale's leading — 317 sites

`text-[12px]` (189), `text-[13px]` (88), `text-[14px]` (40). The first and
third are *exactly* Tailwind's `text-xs` and `text-sm` — but those also set a
**line-height** (16px and 20px), so the substitution changes leading on 242
sites and is not a rename. `text-[13px]` has no name at all.

> **The question:** pin a line-height on the two new steps (and accept that
> every nested site re-flows once), or keep the bare pixel sizes?

## I. A band lighter than `ps.bg`

`#FCFDFE` and `#FCFCFD` were left alone in the colour sweep. They are a zebra
band **lighter** than `ps.bg`, and on GSTR-3B one sits on a row whose own hover
is `bg-ps-bg` — collapsing it would make the row identical to its own hover
state. The token file has no name for that step.

> **The question:** add a `ps.surface-alt` step between white and `ps.bg`, or
> let those rows take `ps.bg` and lose the band?

## J. The global width rule (T3-d)

The periodic Trial Balance now takes `max-w-6xl` when it renders nine columns
and keeps `max-w-4xl` at five — the shape the cash-flow view in the same file
already uses. **A global rule was not written**: that one page carries
**fourteen different `max-w-*` containers**, and picking one is a design
decision across the product.

> **The question:** one content width for every screen, or width by column
> count as the two views now do?

## K. The year-end pack still says "PracticeSync AI"  *(BUILT 19 Sep — answered as "the practice's name alone"; say the word and the second line goes back in)*

Its cover reads **"Prepared by: PracticeSync AI — Practice Management
Platform"**, on a set of financial statements a CA signs. The practice's name
belongs there. T5a-8 in the plan.

Not built yet because the firm's name is not in the data the PDF service is
given — it takes an engagement, which carries `firm_id` and no name — so it
needs a fetch threaded through three routers. Small, but it changes what the
document says, so it is worth one line from you:

> **The question:** the practice's name alone, or the practice's name with a
> small "prepared using PracticeSync" line?

## L. What a CA is told when a posting falls back to the generic Bank ledger

Pre-existing and recorded in CLAUDE.md: `PaymentAccount.is_fallback` and
`.reason` are computed and reach no caller, so when a payment posts to the
firm's generic `%Bank%` ledger rather than the client's own account, nothing
says so. The resolver runs inside eight journal-line builders, so surfacing it
is a refactor through the posting kernel's callers.

> **The question:** WHERE should a CA be told — on the entry row, in the
> posting confirmation, or only in a report?

## M. The rupee sign on a PDF — a licence choice, not a technical one

Every document this product prints spells money `Rs. 12,34,567.89`. Every
other Indian product — TallyPrime, Zoho Books — prints `₹`. It is not wrong,
just dated: ReportLab's built-in Helvetica is WinAnsiEncoded and has no glyph
for U+20B9, so printing the sign needs a font file embedded in the PDF, which
means a font file committed to this repo.

Measured 19 September against the 48 fonts on the build image. Twenty carry
the glyph, and the shortlist is two, because the trade-off is entirely about
the licence:

| | metrics vs Helvetica | licence | what it costs |
|---|---|---|---|
| **GNU FreeSans** | **0.977–1.013×** both weights — a drop-in, no column moves | **GPLv3** with the font exception | the exception covers a DOCUMENT that embeds the font; shipping the font **in this repo** is GPLv3 redistribution, with its source-availability duty |
| **DejaVu Sans** | 1.13× regular, 1.26× bold | **Bitstream Vera** — permissive, no copyleft | re-breaks the columns T5a-4b has just fixed; every table needs re-measuring, and some will not fit |

**Liberation Sans would have been the obvious answer** — it is metrically
compatible with Arial and therefore with Helvetica, and it is OFL. This
build's copy has **no rupee glyph at all**. Checked, not assumed.

Nothing is blocked on this: "Rs." is correct on a tax invoice and CGST Rule 46
prescribes no currency symbol. It is a question about how the document *looks*
and what obligations the repo takes on.

> **The question:** are you willing to carry a GPLv3 font file in this repo
> (FreeSans, and the documents do not change shape), or would you rather stay
> on permissive licensing — in which case it is DejaVu plus a re-measure of
> every table, or "Rs." for now?

My own read: **stay on "Rs." until you say otherwise.** It is the only item in
T5 whose blocker is legal rather than technical, and the cost of being wrong
about a licence is much larger than the cost of a dated currency marker.

---

## N. One request against a Cloudflare preview would reclaim 41 redirect rules  *(raised 24-09-2026, during the overnight run)*

**This is not a decision — it is an observation this environment cannot make.**
Egress is refused at the proxy here, and a Cloudflare Pages preview already
deploys on every PR, so it costs you one click and one URL.

`apps/web/public/_redirects` holds **98** dynamic rules against Cloudflare
Pages' hard cap of **100**. Rules past position 100 are ignored **silently** —
`scripts/generate-redirects.js` carries a comment recording the production
incident where that made *"the whole client workspace 404"*, and
`generate-redirects.test.ts` records that a ≤90 budget was tried and had to be
abandoned. So there are two rules of headroom, and the next two dynamic pages
under `/clients/[id]` spend them.

82 of the 98 are one group: `/clients/:id`'s 41 pages × 2 shapes, the bare path
and the bare `.txt` RSC payload. The generator says those two need a transform a
wildcard cannot express.

**The question is whether the bare-path half is needed at all.** If Cloudflare
Pages resolves a request for `/clients/x/bank` to
`clients/_placeholder/bank/index.html` by ordinary directory-index lookup, then
41 of those rules are doing nothing and the count drops to about 57 — years of
headroom.

**How to answer it in one request.** A preview is already deployed — Cloudflare
comments the URL on every PR. From #570:

```
https://claude-ca-platform-audit-roa.practicesync.pages.dev/clients/anything/bank
```

with **no trailing slash**. (I tried it from here on 24-09-2026 and the proxy
refused the CONNECT with a 403, which is what makes this yours rather than
mine.)

- renders the client Bank screen → the 41 bare-path rules are unnecessary;
  tell me and I will collapse them and re-pin the budget.
- 404s, or redirects to the trailing-slash form → they are load-bearing, the
  current shape is right, and the real fix is reducing dynamic pages. Also worth
  knowing, and it closes the question for good.

⚠️ I have NOT guessed at this. A wrong splat reproduces the incident above and
**would not fail CI**, because the failure is silent truncation rather than an
error.

*Checked and ruled out first, so nobody repeats it: the `.txt` RSC payloads are
real — the static export emits 163 of them — so that half cannot simply be
dropped.*
