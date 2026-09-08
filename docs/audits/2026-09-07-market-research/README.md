# Market and statutory research, 7 September 2026

Three researchers, one per area, asked to work **against primary sources** at the
owner's request. Written up in full here because the conclusions in
`../2026-09-07-where-we-are-against-the-one-platform-goal.md` §13 are compressed.

## Read this first: no primary source was obtainable

Every researcher tested the network themselves rather than trusting the earlier
note in `docs/compliance/00-how-to-read-this.md`, and all three reached the same
result. Direct egress is refused at the proxy:

```
curl https://example.com  →  CONNECT tunnel failed, response 403
```

The proxy logs it as a policy denial. It is **not** a gov.in block — `github.com`
and the package registries succeed while `en.wikipedia.org` and `anthropic.com`
fail — so it is this remote environment's network policy, which the owner can
change. `WebSearch` works (server-side); `WebFetch` and `curl` do not.

Consequently **no claim in these files carries a `[P]` grade.** The grading used is:

| Grade | Means |
|---|---|
| `[S-gov]` | the search engine summarised a document at an **official** URL, which is recorded. The best available here. |
| `[S+]` | several independent professional publishers agree |
| `[S]` | trade press, vendor blog, or a professional firm's note |
| `[U]` | unconfirmed, contradicted, or asserted only by weak sources |

Each file ends with a **ranked re-verify list** — ordered by how load-bearing the
fact is against how weakly it is sourced. Those lists are the most useful part of
this directory: they are the shortest path from here to a `[P]` answer.

## The files

| File | Covers |
|---|---|
| `gst-primary.md` | IMS, GSTR-1A, due dates, 9C thresholds, the three-year filing bar, e-invoicing and the 30-day limit, Rule 36(4), §49(5)/Rule 88A set-off order |
| `income-tax-tds-primary.md` | slabs and rebate both regimes, entity rates, MAT/AMT, §44AD/ADA/AE, §44AB, capital gains and the CII, TDS thresholds, the Income-tax Act 2025 renumbering, Form 16 Part B |
| `payroll-primary.md` | EPF/EPS/EDLI, the Social Security Code wage base, ESI, the revamped ECR, professional tax, bonus, gratuity, §192 |

## The findings that touch this codebase directly

1. **`CII_BY_FY["2025-26"] = 380` is wrong; six sources say 376.** FY 2026-27 has
   since been notified at 384. `cii_for()` falls back to `LATEST_CII_FY`, so every
   indexed computation today uses 380. Correct the value and add 2026-27 — but do
   **not** move `LATEST_CII_FY` on secondary evidence.
2. **The Income-tax Act 2025 renumbering is corroborated in full**, with nothing
   contradicting it. A corrigendum (G.S.R. 286(E), 16-04-2026) exists and could not
   be read, which is the residual risk on any specific form number.
3. **GST 2.0 (22-09-2025) collapsed the slabs to 5% and 18% with a 40% demerit
   rate.** `apps/web/lib/invoices/gst.ts:16` has no 40% option.
4. **The three-year filing bar has been live since the July 2025 tax period** and
   rolls monthly.
5. **The EPF/EPS/EDLI Schemes 2026** were notified 29-06-2026 with a transition
   reportedly ending 20-11-2026.
6. **The wage provision is Social Security Code s.2(88)**, not Code on Wages
   s.2(y) — same substance, imprecise citation in `wage_base.py` and CLAUDE.md.
7. **The 50% wage rule may reach ESI, gratuity and bonus.** Sources conflict;
   graded `[U]`; **change nothing** until a human reads the MoLE FAQ, because gross
   is the direction that cannot under-deduct.
8. **CLAUDE.md's "twenty-two states levy PT" is probably wrong** (20–21; Odisha
   reportedly repealed from 01-04-2026; Punjab's is a Development Tax).
9. **Fixed-term employees earn gratuity pro rata after one year**, not five.

None of these has been acted on. They are findings, not changes.
