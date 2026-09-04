# Compliance: the integrations, the filings, and what gates each one

**Status: in progress.** `01-what-exists-today.md` is complete and is derived
from the code. The per-integration sections are being researched and are not
here yet; the list at the bottom says which. Do not read the absence of a
section as "nothing gates that" — read it as "not written down yet".

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

## Where the code will mark this

Once the per-integration sections land, every place where a registration or
commercial step gates the work gets a greppable marker naming its section:

```
grep -rn 'TODO(compliance)' apps/api apps/web
```

**Not yet added — that grep returns nothing today.** The convention is
deliberately scoped rather than a bare `TODO`, because the codebase has zero
`TODO`/`FIXME` markers anywhere and prefers prose comments; a scoped marker that
must name a real doc section cannot decay into undifferentiated TODO sludge.

## Contents

| | |
|---|---|
| `01-what-exists-today.md` | The code-derived inventory: every external service, every artifact produced, every last mile. **Start here.** |

Still to be written, one file each:

- GST — the GSP/ASP route, e-invoicing, e-way bill, DSC vs EVC
- Income tax and TDS — ERI registration, ITR JSON, TRACES, the RPU/FVU chain
- MCA, EPFO and ESIC — and whether programmatic filing is possible at all
- Bank data — the Account Aggregator, FIU registration, TSPs
- Data protection — DPDP Act obligations for holding clients' financial data

## What is deliberately NOT duplicated here

CLAUDE.md's table of **statutory data a human has to supply** — minimum wages
for the Bonus Act, SBI's Rule 3(7)(i) rate, ESIC reason codes, DTAA treaty
rates, MSMED classification, unbilled-dues account markings. That table is
maintained there and pointing at it is correct; copying it here would create two
copies of one rule, which is the fault this codebase keeps having to remove.

Same for the annual financial-year maintenance checklist. It lives in CLAUDE.md
under "What has to be updated every financial year".
