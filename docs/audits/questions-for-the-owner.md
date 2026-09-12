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

## 2. §50 interest and §47 late fee  *(GST-21 — not started, and this is the one I most want an answer on)*

Every late GSTR-3B the product prepares carries nil interest and nil late fee,
and the CA computes both by hand. ClearTax, IRIS and Tally all show them.

The ENGINE is arithmetic I can write tonight. The problem is the NUMBERS:

| figure | where it comes from | how confident I can be here |
|---|---|---|
| §50(1) 18% p.a. | the Act, notified by 13/2017-CT | high — it is in the section |
| §50(3) 24% on wrongly availed credit | the Act as substituted | high |
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

## 7. Nothing else is waiting on you

Everything not on this list either needed no permission or needed no migration,
and is either shipped or scheduled. `docs/audits/findings-status.md` is the
count.
