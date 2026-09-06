# How to read this, and how much to trust it

## The sourcing caveat, which is not a formality

Every external fact in files `02`–`06` was gathered in a session where
**outbound HTTPS to every relevant government and tax-commentary domain was
blocked by the environment's network policy.** The gateway returned `403` to
`CONNECT` for `incometax.gov.in`, `tin-nsdl.com`, `protean-tinpan.com`,
`tdscpc.gov.in`, `rbi.org.in`, `sahamati.org.in`, `specifications.rebit.org.in`,
`meity.gov.in`, `mca.gov.in`, `epfindia.gov.in`, `esic.gov.in`, `cleartax.in`,
`taxguru.in` and others.

**So not one primary source was read directly.** Everything is triangulated from
search-engine summaries *of* those pages. That is a materially weaker guarantee
than having read the instrument, and it fails in a specific way: search snippets
preserve the sentence and lose the date, the amendment history and the proviso.

Consequences, stated plainly:

- **Every claim carries a confidence grade.** `[P]` = the official body's own
  page, read via summary. `[S]` = secondary — law firm, trade press, vendor
  documentation. `[U]` = could not confirm; a question, not a finding.
- **Nothing here is a substitute for reading the instrument** before money or
  code is committed. Each section ends with a "verify first" list.
- **Re-running this research against an unrestricted network would settle
  several conflicts these files have to leave open.** That is the cheapest
  available improvement to this document.

### All five open findings are now verified

Between 4 and 5 September 2026 every finding this document originally carried as
an ungraded open question was verified by targeted search, each including
deliberate attempts to DISPROVE it:

| Finding | Outcome |
|---|---|
| Income-tax Act 2025 renumbered the TDS forms | **Confirmed**, and the SECTIONS moved too — which the first pass missed |
| The 50% wage rule changes the EPF base | **Confirmed and in force**; a live under-computation below the ceiling |
| PracticeSync cannot be an FIU | **Confirmed**; CLAUDE.md's bank-data section, step one, is not achievable |
| DPDP substantive duties 13 May 2027 | **Confirmed**; one overstatement in this document corrected |
| Revamped ECR changed the workflow | **Confirmed**; format unchanged, but filing now blocks out of order |

Two of those corrected a claim rather than merely confirming one — s. 195 moved
to s. 393(2) and not s. 400, and this document's own "the Board can already take
complaints" overstated the DPDP position. **The verification was worth doing on
the strength of those two alone.**

Sourcing did not improve: the network policy still blocks every primary host, so
these remain triangulated rather than read. What changed is breadth and
adversarial pressure, not access.

Where two sources disagreed, both are recorded. Where a fact was wanted and not
found, that is written down as not found, rather than filled in from a plausible
memory — because a confidently wrong regulatory fact in a codebase document is
worse than a gap. The gap sends somebody to look it up. The wrong fact does not.

## What this document is for, and what it is not

It answers: *what would it actually take to close each last mile?*

It is **not** a licence to start any of it. CLAUDE.md is explicit that the
unbuilt capabilities are "known, deliberate, and not to be quietly started", and
that neither is in scope until asked for by name. Nothing here changes that.
The document exists so that when somebody *is* asked, they do not re-derive all
of this from scratch — and so that nobody estimates "GST filing" as a sprint.

## The one finding that changes an existing plan

`CLAUDE.md` → **"Bank data — the Account Aggregator is the only way in"** instructed, as step one of the Account Aggregator work:

> **Register as an FIU** (Financial Information User). … Go via a TSP … rather
> than building FIU plumbing directly.

**Research indicates this is not achievable as written.** An FIU is *defined* as
an entity already "registered with and regulated by any financial sector
regulator" — RBI, SEBI, IRDAI, PFRDA, or the Department of Revenue. There is no
FIU licence to apply for and no unregulated-FIU tier; eligibility is derivative
of a registration you already hold. A TSP cannot confer it, because a TSP is
itself unregulated and merely builds the FIU module *for* a regulated FIU.

This is `[S]`, consistent across several independent restatements. **What
happened next is worth reading before relying on the paragraph above**, because
the finding turned out not to be the decisive one.

Eligibility is solvable with money — partner with a regulated FIU, or acquire a
registration. **Purpose is not**, and purpose sits upstream of it: the consent
artefact carries a `Purpose`, the FIP validates every fetch against it, and the
published taxonomy (codes 101–105) names the class of licensee each purpose
serves — SEBI RIAs, stock brokers, PFRDA Retirement Advisors, lenders, insurers.
None describes an agent keeping the customer's own books, so a fully licensed
FIU still could not pull this data for this use.

So the line of work was **closed on purpose-fit, not on eligibility**, and closed
without the legal opinion this paragraph asked for — because the opinion would
have priced a route that purpose already forecloses. See
`05-bank-data-and-the-account-aggregator.md` §§0a, 2, 2b and **§7 (the closure)**,
and tasks #102, #104, #130. CLAUDE.md has since been edited to match.

## The shape every section shares

Read three or four of these and the pattern stops being a coincidence:

1. The product's computation is finished and correct.
2. The last mile is a **human on a portal with a hardware token**.
3. What separates the two is a **registration, an empanelment, or a licence** —
   not engineering.
4. Where the software *could* run ahead, it **refuses instead**, and names the
   missing registration at the point of refusal.

`domain/income_tax/itr_json.py` is the worked example and is worth reading
before anything else here: it computes a complete ITR payload and then declines
to write the file, partly because `CreationInfo.JSONCreatedBy` needs an
`SW########` the Income Tax Department issues to registered providers.

That refusal is the house style for this whole area. Prefer it to a plausible
guess, everywhere.
