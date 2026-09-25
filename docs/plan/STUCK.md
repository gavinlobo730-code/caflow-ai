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

## 2 · The four §C partials still blocked on a document or a decision

Unchanged from the plan's Track 1 §C, restated here so this file is the one
place to look. None of these is something I can settle:

| item | what it needs |
|---|---|
| **IT-11** Form 3CD clause workspace | document #4 (the ICAI/CBDT 3CD form) |
| **TDS-22** the §194I(a) / §194J(a) rates | document #4 — the module deliberately withholds rather than over-deducting |
| **FA-11** shift working, NESD markings | document #9 |
| **TDS-16** the FVU/RPU file writer | document #3 (the TDS file layouts) |
| **GST-25** composition, GSTR-8 TCS, GSTR-9C | document #5 |
| **SALES-23** may the nightly sweep EMAIL a client's own customers | **your call** — it sends mail outward on the client's behalf |
| **ACC-13** cost centres as a dimension on `journal_lines` | **your call** — a migration on the hottest table in the schema |

---

## 3 · What a client screen should render when the client id resolves to nothing

**Track 4, gate 2.** `pnpm smoke` renders all 166 screens with **0 per-screen
problems** and then **fails its own duplicate-body check**, exit 1. Six routes
share one body:

    /clients/_placeholder/overview
    /clients/_placeholder/sales
    /clients/_placeholder/purchases
    /clients/_placeholder/inventory
    /clients/_placeholder/relationships
    /clients/_placeholder/accounting/journal/_placeholder/edit

**What I did.** Read the guard rather than the number. `MAX_ROUTES_PER_DIGEST`
is 5 and the script's own comment names this exact group as the headroom,
sitting exactly on the limit, and says a sixth *should* trip it — *"six screens
showing a CA nothing but navigation is the finding, not the false alarm."* The
sixth is `relationships`, from the related-party work. So the guard is behaving
as designed and **I did not raise the threshold**: softening a check because it
fired is the move this repository keeps recording as the mistake.

**Where I stopped.** The comment also says *"a seeded demo firm (T2) is what
fixes that"*, and **that is not true** — I checked. The walk feeds every `:id`
the literal string `_placeholder`, which resolves to no client whatever is
seeded; `--real-client` swaps in a fixed UUID that no seeded firm will own
either. So seeding the demo, which I have now built, does not close this gate.

**What I would do, and it is a decision about what a CA sees.** Two defensible
answers and they are not the same product:

* **Give the screens a named not-found state.** A client route whose id
  resolves to nothing currently shows navigation and nothing else — which is
  also what a CA gets from a stale bookmark or a deleted client. Each section
  saying *"Sales — no such client"* is better UX AND makes the six bodies
  distinct, so the gate closes as a side effect rather than by exemption. It
  is six screens' empty states, and the risk is conflating *still loading*
  with *not found*.
* **Exclude the placeholder group from the digest check.** State the rule —
  a screen that cannot resolve its subject renders its shell, and that is not
  the duplication this check is for — and keep the check live everywhere else.
  Cheaper, and it removes those six screens from the guard's reach, which is
  precisely what its author did not want.

I lean to the first. It is the one that changes what a person sees rather than
what a test counts.

**What it costs to be wrong.** Picking the second and being wrong means six
client screens can go blank again with nothing failing. Picking the first and
being wrong means a screen briefly says "no such client" while it is still
loading, which is a visible bug and would be caught immediately.

---

*This file is updated in the same commit as the work that hit the blocker,
never afterwards from memory — the rule that keeps `findings-status.json`
honest, applied to this.*
