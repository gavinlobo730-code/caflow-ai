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

60 hits across 27 files on 8 October 2026, and every one is either a docstring,
a `# CA REVIEW REQUIRED` comment, or a sentence shown to a CA telling them where
to go. That figure is a dated snapshot and drifts every time a comment is added,
so do not quote it as a promise: the claim itself is pinned by
`tests/test_the_facts_behind_the_marketing_claims.py::test_no_server_code_addresses_a_government_portal`,
which reads the string literals (not docstrings or comments) for a scheme-bearing
portal URL and fails on one. **Two are neither, and are worth knowing about so nobody
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

**Sentry is a sub-processor, and this table is where that is recorded** (SECURITY-
PRIVACY-36). What leaves today is the API's error events, from `apps/api/main.py`
when `SENTRY_DSN` is set: `send_default_pii=False`, `traces_sample_rate` 0 unless
`SENTRY_TRACES_SAMPLE_RATE` says otherwise. **The browser SDK is wired in code and
starts only where `NEXT_PUBLIC_SENTRY_DSN` was built in** (`apps/web/lib/monitoring/`,
started from the root layout); with no DSN nothing starts and nothing leaves the
browser. What it may send is fixed to what a practice's screens warrant: errors
only, scrubbed by shape before sending (`scrub.ts`), no default PII, no tracing
and **no session replay at all** — a recording of a payroll or bank screen is a
decision for the owner, not a default, and enabling it means naming the routes
that must be blocked. That is pinned by
`apps/web/scripts/the-browser-reports-crashes-without-recording-screens.test.ts`,
so that turning replay on is a decision and not a regression.
**The region is NOT recorded here, and that is a human step**: Sentry hosts a
project in the US or the EU, chosen when the organisation is created, and it is
visible in the DSN's host (`…ingest.us.sentry.io` or `…ingest.de.sentry.io`) and
in the organisation settings. Neither is readable from this repository. Nobody
should write a region in from memory — it decides whether an error event
containing a client's identifiers (an exception message can carry a GSTIN, a PAN
or a party name) leaves India, and `06-data-protection-dpdp.md` §5 already names
Render (Singapore), Groq and Gemini on that footing (Rule 15: permitted by
default today, a policy risk to monitor). Sentry belongs on the same list once
somebody has read the region off the DSN.

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

The sharp edge that used to be there is closed. `get_provider(provider_name: str =
"manual")` once took a name and ignored it, so the day a second provider existed a
caller asking for it by name would have got manual data and no error, which is the
silent-wrong-answer failure this codebase keeps having to unpick. It now **refuses
any name but `manual` with a `ValueError`**, pinned by
`tests/test_provider_factories_refuse_a_name_they_lack.py`, so the switch has to be
wired in the same commit that adds a provider. The e-invoice factory,
`domain/income_tax/einvoice_service.get_provider`, behaves differently: it logs a
warning and falls back to its manual provider.

## 5. The one place the product already refuses for a registration reason

`domain/income_tax/itr_json.py` computes a complete, correct ITR payload and
then **declines to write a file**, for two separate reasons. The second is the
one that matters here:

> `CreationInfo.JSONCreatedBy` must match `SW########`, a number the Income Tax
> Department issues to registered providers — a file without one is rejected at
> upload whatever else it contains. Obtaining it is a registration step, not a
> coding one, in the same way GSP registration gates GST filing.

**Which registration issues that number is not settled.** `07` §3.4 argues it is the
Third Party Software Utility Developer registration and probably separate from ERI,
and `08` Email 1 asks the Department; treat any statement that it comes with ERI as
unconfirmed.

That is the model for everything in this document. The code is ahead of the
paperwork, it knows it, and it says so at the point of refusal rather than
emitting something that looks right and fails at a portal.

`ITR_SOFTWARE_PROVIDER_ID` exists in `render.yaml` so the day the number is
issued is a config change.

## 6. The filing demos

`services/filing_demo/` — eight flows, under the keys the API serves them by:
`gstr1`, `gstr3b`, `gstr9`, `tds`, `itr`, `pf`, `esi`, `mca`. Served by
`POST /api/filing-demo/{flow}/preview`, rendered by
`components/FilingDemoWizard.tsx`, wired into five screens.

They are portal-faithful in *sequence*, transmit nothing, write nothing, and
every response carries an honest `SIM-NOT-FILED` reference.
`ENABLE_FILING_SIMULATION` defaults on and **is the kill switch** — set it to
`false` on any deployment that records real filings.

> **When real filing is built it is a NEW endpoint and the simulation is
> deleted.** Never repointed at a live portal. Everything that makes it safe is
> the fact that it cannot file.

### The second implementation is gone (was: "still live")

**Resolved in commit #433, verified again 2026-09-08.** This section used to
record a live second filing demo. It no longer exists:
`components/DemoFilingModal.tsx`, `lib/filing/demoFiling.ts` and
`lib/data/demoFilings.ts` are all deleted, `app/deadlines/page.tsx` carries a
comment where the button was, and nothing writes `demo_filings` from the
browser.

What it was, kept because the failure is the instructive part: it generated the
reference and ran the validation IN THE BROWSER, wrote the result straight to
`demo_filings` (migration 087) over PostgREST so `rbac()` never ran, and — the
part that mattered — **never called the server, so `ENABLE_FILING_SIMULATION`
did not reach it**. Turning the kill switch off left it simulating filings
anyway. A demo also belongs on the screen where the RETURN lives; a deadline row
is not a return.

`apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts` now
holds the line — it fails if any of those files come back, if anything writes
`demo_filings` from the browser, or if a screen offers the wizard without first
probing `fetchFilingDemoCapabilities`.

`docs/DEMO_FILING.md` is the description of the shared framework: the one
implementation, what each of the eight flows is there to teach, the two rivals that
were deleted and the kill switch. It used to describe only the deleted path, which
is how the discrepancy survived unnoticed for as long as it did, and no longer does.

