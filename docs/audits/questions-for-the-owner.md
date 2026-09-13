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
- **`/accounting/msme-tracker`** (PUR-15) writes a hand-keyed `msme_payments`
  side table, while §43B(h) is derivable from `purchase_bills` +
  `purchase_payments` for vendors whose `msme_status` is micro or small.

I have not touched either. `/gst/reconciliation` was deleted on your decision
and I am treating these the same way. Deriving the §43B(h) figure needs no
migration and I can do it whenever you say; DROPPING either table does.

---

## 10. Nothing else is waiting on you

Everything not on this list either needed no permission or needed no migration,
and is either shipped or scheduled. `docs/audits/findings-status.md` is the
count.
