# Compliance: the integrations, the filings, and what gates each one

**Read `00-how-to-read-this.md` first.** It carries the sourcing caveat, and
that caveat is not a formality: no primary source could be read directly in the
session that produced these files, so every external fact is graded and several
load-bearing ones are open questions rather than findings.

## Why this exists

PracticeSync **prepares** statutory filings and does not submit them. That is a
deliberate design, and the reasons are spread across a dozen docstrings, a
CLAUDE.md section, and several people's heads. This directory is the one place
that says, for every statutory output:

- what the product computes today,
- what the last mile actually is,
- and **what gates closing it** — which is almost never code.

That last point is the whole reason for the document. Every one of these
integrations is blocked on a registration, an empanelment, a commercial
agreement or a licence, not on engineering. Somebody who does not know that will
estimate "GST filing" as a sprint.

## The rule that does not move

> **Never auto-submit anything to any government portal — always require
> explicit CA confirmation click.**

This is a "Code rules" entry in CLAUDE.md and it gets *stronger* when real
filing is built, not weaker. Real filing means an explicit confirmation per
return, every time — never a batch, never a scheduler, never a retry that
resubmits.

Two corollaries, both already true in the code:

1. **The signature is the taxpayer's, not the firm's.** Every filing flow ends
   "CA prepares → taxpayer or authorised signatory signs". That is a different
   shape from every other screen in the app, where the CA acts alone.
2. **The filing demos are safe because they cannot file.** When real filing is
   built it is a NEW endpoint and the simulation is **deleted** — never
   repointed at a live portal. `ENABLE_FILING_SIMULATION=false` is the kill
   switch for any deployment that records real filings.

## Where the code marks this

Every place where a registration or commercial step gates the work carries a
greppable marker naming the section that explains it:

```
grep -rn 'TODO(compliance)' apps/api apps/web
```

Eleven markers today, in `domain/gst/portal_service.py`,
`domain/income_tax/itr_json.py`, `domain/payroll/{ecr,esic,statutory,form24q}.py`,
`domain/banking/normalizer.py`, and the four prepare-only rails
(`routers/{einvoice,eway_bill,xbrl_engine,mca_workspace}.py`).

The convention is **new** and deliberately scoped. The codebase had zero
`TODO`/`FIXME` markers anywhere before this — it prefers prose comments beside
the code — so a bare `TODO` would have been against the grain and would have
decayed into the usual sludge. A marker that must name a real doc section
cannot. `tests/test_compliance_markers_point_somewhere_real.py` enforces it:
a marker with no doc path, or one pointing at a file that does not exist,
fails the suite. Rename a doc and the markers fail rather than silently
orphaning.

## Contents

| | |
|---|---|
| `00-how-to-read-this.md` | The sourcing caveat and the confidence grades. **Read first.** |
| `01-what-exists-today.md` | Code-derived: every external service, every artifact produced, every last mile. |
| `02-gst.md` | The GSP gate, the taxpayer's API switch, DSC vs EVC, e-invoicing, e-way bill. |
| `03-income-tax-and-tds.md` | ERI registration, the 4-IP whitelist, ITR schemas, TRACES, the RPU/FVU chain — and the 2025 Act renumbering. |
| `04-mca-epfo-esic.md` | The three with no API at all, the revamped ECR, and the Labour Codes. |
| `05-bank-data-and-the-account-aggregator.md` | Why the FIU step may be unachievable, and why upload stays the base case. |
| `06-data-protection-dpdp.md` | The only section with a real deadline: 13 May 2027. |

### If you read only three things

1. **`00`** — how much to trust the rest.
2. **`05` §0** — `CLAUDE.md:404` tells you to register as an FIU, and research
   says that is not a thing a SaaS company can do.
3. **`03` §0** — the Income-tax Act 2025 may have renumbered every TDS form the
   product emits, and 25 files carry the old vocabulary.

## What is deliberately NOT duplicated here

CLAUDE.md's table of **statutory data a human has to supply** — minimum wages
for the Bonus Act, SBI's Rule 3(7)(i) rate, ESIC reason codes, DTAA treaty
rates, MSMED classification, unbilled-dues account markings. That table is
maintained there and pointing at it is correct; copying it here would create two
copies of one rule, which is the fault this codebase keeps having to remove.

Same for the annual financial-year maintenance checklist. It lives in CLAUDE.md
under "What has to be updated every financial year".
