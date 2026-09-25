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

## 1 · Cross-client TAX benchmarking needs stored per-client aggregates

**Plan rows 3c-1, 3c-2, 3c-4, and the tax half of 3c-5.** Effective tax rate
trend, ITC leakage trend, the GST/TDS/payroll ratio trends, and benchmarking a
client's tax position against the firm's other clients.

**What I did.** Built the commercial half — `domain/practice/concentration.py`
and `GET /api/analytics/concentration` — because fee revenue and cost per
client are already aggregated by `invoice_repo.get_revenue_by_client` and
`time_tracking_analytics_repo.get_cost_by_client`, one read each. That answers
fee dependence and where a client sits in the firm's own distribution.

**Where I stopped, and it is not a judgement call.** A client's effective tax
rate, ITC as a proportion of purchases, or GST-to-turnover ratio is derived
from that client's whole ledger for the period. Computing it for ONE client is
already a read proportional to transaction volume; computing it for every
client so the one can be compared against them multiplies that by the client
count. That is the rule in CLAUDE.md — *"No report may fetch rows proportional
to transaction volume"* — broken twice over, on a firm with fifty clients, on
an endpoint a partner would leave open. The measured comparison is the
cash-flow case: 12,836 entries took 54.34s unaggregated against 2.15s off
`account_period_balances`.

**What I would do.** A `client_period_metrics` table on the
`account_period_balances` shape — one row per (client, financial year) holding
the handful of figures a benchmark needs, maintained by the nightly sweep that
already runs `run_reconciliation_for_firm` and `audit_and_heal_firm` per
client. Then the benchmark is one read of ~50 rows and the trends are free,
because a year of rows IS the trend. That is a migration and a scheduled-job
change, and **which figures it should hold is the part I want you on**: each
column is a claim about what a CA compares clients on, and a column added later
cannot be back-filled for a period whose books have since been locked.

**What it costs to be wrong.** Nothing yet — the feature does not exist either
way. Getting the column list wrong costs a second migration and a year of
history the first one did not capture.

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
