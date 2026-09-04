# What exists today

**Read this before believing any claim that the product "does" a filing.**
It prepares. Every last mile is a human on a portal.

This file is derived from the code, not from memory. Where it names a symbol,
that symbol is the authority and this prose gets fixed when they disagree.

---

## 1. The one-line answer

PracticeSync makes **zero outbound calls to any government system.** Not to
GSTN, not to the Income Tax Department, not to TRACES, NIC, MCA21, EPFO or
ESIC. Every reference to a portal in `apps/api` is *text addressed to a human* —
a sentence telling a CA where to go — never an endpoint.

You can verify that claim in one command, and it is worth re-running whenever
somebody says filing "works":

```
grep -rnE 'gst\.gov\.in|incometax\.gov\.in|ewaybillgst|mca\.gov\.in|esic\.in|epfindia\.gov\.in|tdscpc\.gov\.in' \
  --include=*.py apps/api | grep -v /tests/
```

32 hits at the time of writing, across 15 files, and every one is either a
docstring, a `# CA REVIEW REQUIRED` comment, or a sentence shown to a CA telling
them where to go. **Two are neither, and are worth knowing about so nobody
mistakes them for an integration**: `domain/income_tax/xbrl_service.py` uses
`http://www.mca.gov.in/taxonomy/2023/in-bse-fin` and `http://www.mca.gov.in` as
XML **namespace URIs**. A namespace URI is an identifier, not an address — it is
never dereferenced, and the XBRL spec requires those exact strings. They are not
network calls and removing them would break the instance document.

Nothing anywhere constructs a request to a government host.

## 2. The complete external-service inventory

`render.yaml` must declare every environment variable the backend reads, and
`tests/test_render_manifest_matches_code.py` enforces that in both directions —
so the declared env keys ARE the integration surface. There is nowhere for an
undeclared one to hide.

| Service | What for | Key |
|---|---|---|
| Supabase | Postgres, auth, storage | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` |
| Groq | chat/text AI, PDF (text) invoice extraction | `GROQ_API_KEY` |
| Gemini | image-based invoice extraction only | `GEMINI_API_KEY` |
| Resend | transactional email | `RESEND_API_KEY`, `EMAIL_FROM` |
| Razorpay | payment links (practice billing) | `PAYMENT_PROVIDER` |
| Sentry | error reporting | `SENTRY_DSN` |

Six services. **None of them is a government system**, and none of them files
anything. `ITR_SOFTWARE_PROVIDER_ID` is also declared, and is the exception that
proves the rule — see §5.

## 3. What the product produces

Each row is a real artifact a CA can download or read, computed from the ledger.
The last column is the honest last mile.

| Artifact | Where | Last mile |
|---|---|---|
| GSTR-1 JSON | `domain/gst/gstr1_builder.py` | CA uploads at gst.gov.in, signs with DSC/EVC |
| GSTR-3B figures | `domain/gst/gstr3b_computer.py` | CA prepares online at gst.gov.in, signs |
| GSTR-9 | `routers/gst_workspace.py` | CA files at gst.gov.in |
| GSTR-2A/2B recon | `POST /gstr2b/upload` | CA **downloads** 2B from the portal and uploads it here |
| ITR JSON | `domain/income_tax/itr_json.py` | refuses to emit — see §5 |
| Form 24Q source + Annexure II | `GET /24q-source`, `/24q-annexure-ii` | working paper; RPU/FVU and the portal are outside |
| Form 26Q / 24Q computation | `routers/tds.py` | same |
| EPFO ECR | `GET /runs/{id}/ecr` | CA uploads at the EPFO Unified Portal |
| ESIC return | `GET /runs/{id}/esic` | CA uploads at esic.gov.in |
| XBRL package | `routers/xbrl_engine.py` | CA validates and files at MCA21 |
| e-invoice IRN | `routers/einvoice.py` | **records** an IRN a human got from an IRP |
| e-way bill | `routers/eway_bill.py` | **records** an EWB a human generated |
| MCA forms (AOC-4, MGT-7, ADT-1, DIR-12) | `routers/mca_workspace.py` | CA files at MCA21 V3 |

Note the shape of the last two: `POST /records/{id}/irn-generated` does not
*generate* an IRN. It writes down that somebody else did. That is a deliberate
design, not an unfinished one.

## 4. Every rail already says so, in the code

Four routers carry the mandated comment from CLAUDE.md's "Code rules"
(*Before any government API call, add comment: `# CA REVIEW REQUIRED — DO NOT
AUTO-SUBMIT`*):

- `routers/einvoice.py` — "DO NOT AUTO-SUBMIT to IRP"
- `routers/eway_bill.py` — "DO NOT AUTO-SUBMIT to NIC portal"
- `routers/xbrl_engine.py` — "DO NOT AUTO-FILE XBRL to MCA portal"
- `routers/mca_workspace.py` — "DO NOT AUTO-SUBMIT to MCA21 or any government portal"

`domain/gst/portal_service.py` goes further and is worth reading before any
integration work, because it is **the seam**: an abstract `GSTPortalProvider`
with exactly one implementation, `ManualGSTProvider`, and READ-ONLY in capitals
at the top.

There is a live sharp edge there. `get_provider(provider_name: str = "manual")`
takes a name **and ignores it** — it returns `ManualGSTProvider()`
unconditionally. Today that is harmless because there is nothing else to return.
The day a second provider is added, a caller asking for it by name gets manual
data and no error, which is the silent-wrong-answer failure this codebase keeps
having to unpick. Wire the switch in the same commit that adds the provider.

## 5. The one place the product already refuses for a registration reason

`domain/income_tax/itr_json.py` computes a complete, correct ITR payload and
then **declines to write a file**, for two separate reasons. The second is the
one that matters here:

> `CreationInfo.JSONCreatedBy` must match `SW########`, a number the Income Tax
> Department issues to registered providers — a file without one is rejected at
> upload whatever else it contains. Obtaining it is a registration step, not a
> coding one, in the same way GSP registration gates GST filing.

That is the model for everything in this document. The code is ahead of the
paperwork, it knows it, and it says so at the point of refusal rather than
emitting something that looks right and fails at a portal.

`ITR_SOFTWARE_PROVIDER_ID` exists in `render.yaml` so the day the number is
issued is a config change.

## 6. The filing demos

`services/filing_demo/` — eight flows: `gstr1`, `gstr3b`, `gstr9`, `itr`,
`tds_return`, `pf_ecr`, `esi`, `mca`. Served by
`POST /api/filing-demo/{flow}/preview`, rendered by
`components/FilingDemoWizard.tsx`, wired into five screens.

They are portal-faithful in *sequence*, transmit nothing, write nothing, and
every response carries an honest `SIM-NOT-FILED` reference.
`ENABLE_FILING_SIMULATION` defaults on and **is the kill switch** — set it to
`false` on any deployment that records real filings.

> **When real filing is built it is a NEW endpoint and the simulation is
> deleted.** Never repointed at a live portal. Everything that makes it safe is
> the fact that it cannot file.

### A second implementation is still live

CLAUDE.md states there is exactly one filing-demo implementation. As of
2026-09-04 that is **not true**. `components/DemoFilingModal.tsx` is still wired
into `app/deadlines/page.tsx` and carries its own everything: its own reference
generator (`lib/filing/demoFiling.ts`, `DEMO-`/`SIM-` prefixes rather than
`SIM-NOT-FILED`), its own `validateForDemo`, and its own persistence to the
`demo_filings` table (migration 087) through a **direct PostgREST write**, so
`rbac()` never runs on it and RLS is the only check.

`docs/DEMO_FILING.md` documents that older path and only that one, which is why
the discrepancy survived.

Neither implementation can file anything, so this is not a safety incident. It
is a correctness-of-the-map problem, and it is exactly the fault pattern the
rest of this codebase has spent months removing: one rule, two implementations,
one of them documented. Tracked as its own task; resolve it before any real
filing work starts, because the safety argument should have to be made once.
