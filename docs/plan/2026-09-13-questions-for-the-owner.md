# Questions waiting for the owner

Written overnight on 12–13 September 2026, while the owner was asleep, at their
request: *"if you have questions please write them down."*

Nothing here blocks tonight's work — everything blocked on an answer has been
set aside and everything else is being done. This is the list to work through
in the morning, in the order the answers are needed.

**Nothing on this list has been guessed at in code.** Where a question has a
safe default, the default is stated and has been taken; where it does not, the
code refuses and names the gap, which is this codebase's standing rule.

---

## 1. Needed before Track 4 (the navigation change)

### 1a. What does a CA reach for first?

The module hub shows fourteen tiles. Their ORDER is the one thing about the hub
I cannot derive from the code — it is a fact about how the owner's CAs work, not
about the product. My guess, to argue with rather than accept:

> Compliance calendar · GST · Banking · Accounting · Sales · Purchases · TDS ·
> Payroll · Income tax · Fixed assets · Inventory · Year-end · Reports ·
> Documents

The reasoning: a practice's day starts at "what is due", and the two modules
with daily traffic are GST and Banking. Everything after Payroll is periodic.

### 1b. Which module gets converted first, after the reference module?

Track 2 converts **Banking Entries** as the reference, because it is the densest
screen in the product and a design system that survives it survives everything.
After that, the order is a business call: convert what a CA sees most (GST), or
convert what looks worst today?

---

## 2. Needed before a CA test run

### 2a. Is the test run on real client data or a seeded demo firm?

This changes what has to be ready. On a demo firm I can seed a full year of
plausible transactions and every screen has something in it. On real data the
CA sees their own numbers — far more convincing, and it means the Tally
migration path has to work first for that client.

### 2b. How many CAs, and are any of them outside the four states whose
professional-tax slabs are modelled?

`domain/payroll/professional_tax.py` records 22 states as levying PT and
`routers/payroll.py` implements 4 (Maharashtra, Tamil Nadu, Karnataka, West
Bengal). A CA in Gujarat or Andhra running payroll in the test would get a
`statutory_gaps` warning rather than a deduction — correct behaviour, and a bad
first impression. If any tester is outside those four, tell me which state and
I will read that state's notification and add the table before they see it.

---

## 3. Statutory data only a human can supply

These are the items where the code REFUSES rather than guessing, and the
refusal comes back as a named gap. Each needs a document read by a person; none
can be derived from anything in the repository, and writing any of them from
memory would put a wrong number in somebody's pay or somebody's return.

| what | who has to supply it | what it blocks today |
|---|---|---|
| professional-tax slabs for the other 18 states | the state's own PT notification | payroll in those states reports a gap instead of deducting |
| Labour Welfare Fund amounts (16 states) | each state's LWF notification | same |
| minimum wage per state / scheduled employment / skill grade | state labour notifications, revised twice yearly | §12 Bonus Act computes on the HIGHER of ₹7,000 and the minimum wage; without it the ceiling is wrong |
| SBI's Rule 3(7)(i) lending rate | published by the bank on 1 April | the concessional-loan perquisite |
| ESIC reason codes | ESIC's own list | the ESIC return's exit reasons |
| DTAA rates per country × nature of income | the treaty text, read once per pair | §195 withholding falls back to the Act rate and over-deducts where a TRC exists |
| the seven ITR JSON schemas for the new AY | incometax.gov.in → Downloads | ITR JSON for AY 2027-28 when it opens |
| a vendor's MSMED classification | the supplier's Udyam registration | Schedule III payables ageing rows (i)/(iii), and §43B(h) |

**Question:** do you want me to build a small screen for each of these — a
"statutory data" settings area where a CA pastes a state's slab table once and
it applies for every client in that state — or keep them as code the developer
edits? A screen is roughly two days and turns eight permanent developer
dependencies into a CA-serviceable one.

---

## 4. Things I decided myself, that you can overrule

Recorded so they are visible rather than buried in a diff.

1. **The hub is not the only way to move.** A persistent module switcher and a
   ⌘K palette sit alongside it, because a CA moves bank line → invoice → GST →
   TDS in ninety seconds and routing every hop through a full-screen hub trades
   a cramped sidebar for a slow one. Hub to *enter* a client, switcher to
   *move* inside one.
2. **A data table takes the full width; prose keeps a reading measure.** See
   the plan document — the white space you noticed is real, and the fix is
   two-tier rather than "make everything wide".
3. **No dark mode at all**, rather than "later". Carrying an unused second
   palette costs every component for ever.
