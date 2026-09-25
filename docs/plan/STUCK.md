# STUCK — what I could not finish alone

Opened **25 September 2026** on the owner's instruction: *"complete all the
three tracks and then let me know if in between you are stuck then write it
down — after completing the three tracks we can go together on it."*

**The rule for this file.** An entry goes here only when I have *tried* and the
remaining step is genuinely not mine — a decision that changes what the product
claims, a credential I do not hold, a document this environment cannot fetch,
or a change to how the live site is served. Anything I could decide under the
standing instruction that code decisions are mine is **decided and recorded in
THE-PLAN.md as a D-number**, not parked here.

Each entry says: what I did, exactly where I stopped, what I would do, and what
it costs to be wrong.

---

## 1 · Cross-client TAX benchmarking — **ANSWERED, built 25 Sep (D30)**

**Plan rows 3c-1, 3c-2, 3c-4, and the tax half of 3c-5.**

**What was blocked, and it was not a judgement call.** A client's effective tax
rate, ITC as a proportion of purchases, or GST-to-turnover ratio is derived
from that client's whole ledger for the period. Computing it for ONE client is
already a read proportional to transaction volume; computing it for every
client so the one can be compared against them multiplies that by the client
count — CLAUDE.md's reporting rule broken twice over, on an endpoint a Partner
would leave open. The measured comparison is the cash-flow case: 12,836 entries
took 54.34s unaggregated against 2.15s off `account_period_balances`.

**The one thing I could not decide** was WHICH FIGURES the table holds, because
a column added later cannot be back-filled for a period whose books have since
been locked. The owner chose twelve (**D30**): turnover, profit before tax, tax
expense, output tax, ITC availed, ITC reversed, GST cash paid, purchases, TDS
deducted, TDS deposited, payroll cost, employee count.

**What was built.**

* **Migration 417**, `client_period_metrics`, one row per (client, financial
  year), on the `account_period_balances` shape. Firm-isolated AND
  assignment-scoped at creation — the row carries a client's turnover, profit
  and tax, so migration 084's RESTRICTIVE policy is applied here rather than
  left for a sweep that has not run since 2024.
* **The 06:00 IST sweep fills it**, beside `balance_cache_audit` and
  `reconciliation_audit`, which already pay the per-client read. It RE-DERIVES
  and replaces rather than accumulating — a back-dated journal or a revised
  return moves a figure already written — and covers two financial years,
  because a year's books keep moving until the return is filed.
* **`domain/practice/client_metrics.py`** is the authority for what each figure
  MEANS and which source may answer it. Two could plausibly be derived twice —
  output tax off the GST Output account as well as off the return, ITC off the
  purchase register as well — and the RETURN wins, because a benchmark of tax
  positions compares what was FILED.
* **`GET /api/analytics/benchmark`** and **`/practice/benchmark`**, beside
  Profitability: the fee and tax halves of "where does this client sit".

**The load-bearing decision is that every figure is NULLABLE with no default.**
`DEFAULT 0` would make "this client had no output tax" and "nobody could derive
this client's output tax" the same row. In a DISTRIBUTION that is not cosmetic:
a nil meaning "not derived" drags every median and mean it is counted in
towards zero, AND makes the client it belongs to read as the firm's best
performer on a ratio it has no figures for. `None` is excluded, `n` says how
many clients answered, and the answer NAMES the rest.

**What it refuses.** No threshold, no band, no verdict — an effective tax rate
above the firm's median is a fact and "high" is an opinion about a client's
affairs. No year-on-year growth column (a year of rows is the trend). No
industry comparison: nothing here records what business a client is in, so the
distribution is the firm's own and says so.

**One thing moved to make it possible.** `_PAYROLL_RELEASED` and
`_PAYROLL_UNRELEASED` were in `routers/payroll.py`, so a service needing
PAY-04's rule could only reach them by importing a router — the wrong
direction. They are `domain/payroll/run_status.py` now and the router
re-exports both, so every existing importer is untouched.

---

## 2 · The five §C partials still blocked on a document

Unchanged from the plan's Track 1 §C, restated here so this file is the one
place to look. None of these is something I can settle:

| item | what it needs |
|---|---|
| **IT-11** Form 3CD clause workspace | document #4 (the ICAI/CBDT 3CD form) |
| **TDS-22** the §194I(a) / §194J(a) rates | document #4 — the module deliberately withholds rather than over-deducting |
| **FA-11** shift working, NESD markings | document #9 |
| **TDS-16** the FVU/RPU file writer | document #3 (the TDS file layouts) |
| **GST-25** composition, GSTR-8 TCS, GSTR-9C | document #5 |

Two rows left this table on 25 September, both answered by the owner: **SALES-23**
(may the nightly sweep email a client's own customers — *no, the CA presses
send*, now **D27**) and **ACC-13** (cost centres on `journal_lines` — *build
it*, now **D29**). Neither was ever a research question; both were the owner's
to take, which is why they sat here rather than in a phase.

**Both are now built, and ACC-13 is CLOSED** — D27 in the same commit as §3's
gate, D29 as migration 418, and ACC-13's other half as migration 419: a
party-wise ledger DERIVED from `journal_entries.source_type`/`source_id`, with
no column added, whose unattributed rows are exactly the difference between a
control account and the per-party statements.

**So this file is now only §2, and every row in it is blocked on a document.**
Nothing here is waiting on work; six findings are waiting on five documents.

---

## 3 · What a client screen renders when the client id resolves to nothing — **ANSWERED, built 25 Sep (D28)**

**Track 4, gate 2 — now passing.** `pnpm smoke` reported *166 screens walked, 0
with a problem* and then failed its own duplicate-body check, exit 1, because
six routes shared one body:

    /clients/_placeholder/overview
    /clients/_placeholder/sales
    /clients/_placeholder/purchases
    /clients/_placeholder/inventory
    /clients/_placeholder/relationships
    /clients/_placeholder/accounting/journal/_placeholder/edit

**What I did NOT do.** `MAX_ROUTES_PER_DIGEST` is 5, the script's own comment
names this exact group as the headroom and says a sixth *should* trip it —
*"six screens showing a CA nothing but navigation is the finding, not the false
alarm."* The threshold was not raised and the group was not exempted.

**What the cause turned out to be.** Not the walk. Every one of the forty routes
under `app/clients/[id]/**` opens its loader with some spelling of
`if (!clientId || clientId === "_placeholder") return;` **inside a
`useEffect`** — the early return skips `setLoading(false)`, so the page holds
its skeleton for ever. That is what a CA gets from a stale bookmark or a
deleted client too, which is why the answer is a product change rather than a
test change. The comment's claim that *"a seeded demo firm (T2) is what fixes
that"* is false and was checked: the walk feeds every `:id` the literal
`_placeholder`, which resolves to no client whatever is seeded.

**What was built.** The owner chose the named not-found state over the
exemption: *"Each section says 'Sales — no such client' instead of spinning.
Better for a real CA hitting a dead bookmark, and the gate closes as a side
effect rather than by exemption."*

* **One gate**, `ClientResolutionGate`, in `app/clients/[id]/layout.tsx` — the
  layout all forty routes share. Not forty empty states that would then have to
  be kept in step.
* **One lookup.** `ClientTopBar` used to run the `clients` query itself and keep
  the answer private, which is exactly how the bar could know a client did not
  exist while every screen beneath it spun. The lookup is hoisted into
  `ClientNavProvider`; the bar and the gate read the same answer.
* **`.maybeSingle()`, not `.single()`.** `single` answers an ERROR for zero
  rows, so "this client does not exist" and "the request failed" arrive down one
  channel. `maybeSingle` answers `data: null, error: null`, which is what makes
  `absent` and `unavailable` two states rather than a guess.
* **Six resolution states**, and the risk this file named — *"conflating still
  loading with not found"* — is a state of its own: `resolving` RENDERS the
  screen. So is `off-route`, which is what the static export pre-renders, so a
  real client's screens behave exactly as they did.
* **The refusal names the screen and the address.** The first draft named only
  the MODULE, and turned six identical bodies into five smaller groups of
  identical bodies (reports 5, tax 4, sales 4, purchases 4, compliance 4) —
  which passes the check with zero headroom, and is the exemption wearing a
  different hat. Reports is five routes; "Reports — no client selected" five
  times says less than the address the visitor actually asked for.

**The result.** *166 screens walked, 0 with a problem · 160 distinct bodies
across the 160 routes that stayed put.* No duplicate group at all, where the
check tolerates up to five. `/clients/_placeholder` keeps its redirect to the
list — the front door already answers an unnamed id, and the gate leaves it
alone; only a real id naming no client is refused there too.

**What could still be wrong.** The gate fires on `absent`, and under
`--real-client` the smoke stub answers every `clients` lookup with `null`, so
that mode will now show the refusal on every client screen. That is the stub
being honest rather than a defect, but it makes `--real-client` less useful for
looking at the workspace until the stub carries a client row.

---

*This file is updated in the same commit as the work that hit the blocker,
never afterwards from memory — the rule that keeps `findings-status.json`
honest, applied to this.*
