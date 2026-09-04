# GST — filing, e-invoicing, e-way bill

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 1. The gate: there is no direct route, and a GSP is mandatory

GSTN's architecture is three-tier and has not changed:

```
Taxpayer / CA  →  ASP (your application)  →  GSP (licensed gateway)  →  GSTN
```

The API **specifications** are public at `developer.gst.gov.in/apiportal/`.
**Access is not.** Production credentials are a licence key issued by GSTN only
to an empanelled GSP under contract; a GSP may issue **sub-licence keys** to
ASPs, and that sub-licence is the mechanism the whole ASP market runs on. `[P/S]`

**For the returns APIs — GSTR-1/3B/9, 2A/2B, ledgers — there is no
direct-to-GSTN route at any turnover.** `[S]` This is worth stating flatly
because it differs from e-invoicing and e-way bill, where a direct route *does*
exist above a threshold (§5, §6). There is no version of this where PracticeSync
talks to GSTN directly without a GSP.

### Becoming a GSP is probably not the play, and may not even be open

Eligibility has loosened dramatically across five batches — batch 1 wanted ₹5
crore paid-up capital and ₹10 crore average turnover; **batch 5 reportedly asks
only ₹50 lakh average turnover over FY 2020-21 to 2022-23**, with MSME
relaxations. `[P, unverified — from a search snippet of GSTN's own PDF, unread]`

If that ₹50 lakh figure is right it changes the build-vs-buy calculus
materially, which is exactly why it must be verified rather than believed.

Non-financial criteria are the harder ones, and are consistent across batches
`[P/S]`: Indian registration in IT/ITeS/BFSI/insurance; **backend infrastructure
located in India**; capacity for **≥ 1 lakh GST transactions/month**;
**ISO/IEC 27001** or equivalent; documented privacy policy; three years of
audited accounts.

⚠️ **Whether applications are open is genuinely unclear.** `[U]` ClearTax states
GSTN has stopped accepting new GSP registrations. A batch-5 registration form
URL exists. No batch 6 was found. Batch 5's financial-year window dates it to
~2023-24. Treat "become a GSP" as requiring a direct enquiry to GSTN, not as a
documented open process.

**The ASP route needs no empanelment at all** — you contract with a GSP and ride
their licence. `[S]` Many vendors are both: ClearTax, IRIS, Cygnet and Masters
India each hold a GSP licence and sell an ASP product on top of it. Note that
several of them are also **direct competitors** to a CA practice product.

## 2. The taxpayer's switch, and why it is a product surface

Nothing works until the *client* enables it, per GSTIN:

> GST portal → **My Profile → Manage API Access → Yes**, then choose a duration.

Session duration is **minimum 6 hours, maximum 30 days**; within the window the
taxpayer does not re-enter an OTP. The taxpayer can terminate early. `[P/S]`

For a firm with hundreds of clients that is hundreds of toggles, each expiring.

**And since a GSTN advisory of mid-2025 it is visible and revocable.** `[P/S]`
Every successful OTP consent now triggers an automated email and SMS to the
taxpayer's authorised signatory **naming the ASP and the GSP behind it**, and a
portal dashboard lets the taxpayer view and revoke active ASP consents.

Two consequences: being an ASP is no longer anonymous to the taxpayer, and **any
client can revoke your access at any time without telling you**. Consent is
expiring, client-owned, revocable state the product does not control — model it
that way, and degrade gracefully rather than erroring.

## 3. Signing — and why the static-export frontend cannot do it

**Rule 26, CGST Rules 2017.** A registered person **registered under the
Companies Act 2013** — and, per every secondary source, **LLPs** — must
authenticate by **DSC**. Everyone else (individuals, proprietorships,
partnerships, HUFs, trusts) may use DSC, e-Sign, or **EVC**. `[P/S]`

Rule 26 carried temporary provisos letting companies use EVC during COVID; the
last ran **27 April – 31 October 2021**.

⚠️ **Sources actively conflict on whether that ever became permanent, and this
is the single highest-priority item to verify in this whole document.** `[U]`
Several sources say the provisos lapsed and DSC is again mandatory for companies
and LLPs; others assert companies can now file with EVC, citing nothing. The
extracted rule text reads as date-bounded and expired. **It decides whether an
EVC-only product can serve corporate clients at all.**

### The DSC chain, and the architectural consequence

```
Browser ⇄ WebSocket localhost:1585 ⇄ emSigner (local Windows service)
                                       ⇄ PKCS#11 middleware
                                           ⇄ USB token (non-exportable key)
```

Class-3 DSC private keys live in FIPS-rated hardware tokens and **are not
exportable by design**. There is no lawful way to hold a client's signing key on
a server. API filing with DSC uses a **detached signature computed at the
client** (`JSON → Base64 → SHA-256 → SHA256withRSA → PKCS#7 → Base64`). The
market's answer is a browser extension or a local helper — TaxPro ships exactly
that. `[S]`

> **`apps/web` is a static export. It cannot sign with a DSC.** No architecture
> recovers from that; it is a hardware constraint, not plumbing.

Three options, and they are the whole option set: **EVC only** (viable for
proprietorships, partnerships, HUFs — and for companies only if the Rule 26
question above resolves favourably); ship a **browser extension or desktop
helper** (a Windows dependency inside a cloud product); or **hand off to the
portal** for the signature, which is what the product does today.

**EVC needs no client software** — an OTP to the authorised signatory's
registered mobile and email — and is what most GSP-based flows use.

### Who signs — the statutory shape matches what the code already does

The signature belongs to the **authorised signatory registered for that
GSTIN**. A CA signs only if appointed as an authorised signatory themselves
(which carries real liability), or acts as a **GST Practitioner** under Rule 83,
authorised by the client in **FORM GST PCT-05** — and even then the taxpayer's
confirmation is structurally required. `[P/S]`

> CLAUDE.md's "CA prepares → taxpayer or authorised signatory signs" is not
> self-imposed caution. It is Rule 26 plus Rule 83.

## 4. What can be filed via API

| Capability | API? | Grade |
|---|---|---|
| GSTR-1 / IFF — save, submit, file | Yes | `[P/S]` |
| GSTR-3B — save, file | Yes | `[P/S]` |
| GSTR-2A / 2B — download | Yes | `[P/S]` — needs the **file-based bulk path**; the row API breaks past ~1,000 invoices |
| GSTR-9 | GET confirmed, FILE probable | `[S]` — **ask the GSP** |
| GSTR-9C | Unknown | `[U]` — assume portal-only |
| IMS (accept/reject/pending) | Yes | `[S]` |
| Ledgers, return status, taxpayer search | Yes | `[P/S]` |
| Registration, refunds, payments | Unknown | `[U]` |

⚠️ **API versions are per-endpoint and move.** Fragments found span `v0.2` to
`v4.0` on different endpoints. Do not write a version matrix from this research;
get it from the GSP under NDA. `[U]`

⚠️ GSTN's authentication uses **AES-256 in ECB mode with PKCS#5 padding**, which
is a genuinely weak choice and has been publicly criticised. No evidence it has
changed. `[U]`

### Three portal changes that constrain any filing design

1. **GSTR-3B hard-locking, from the July 2025 period.** Outward liability
   auto-populated into **Tables 3.1 and 3.2 is non-editable**; corrections go
   through **GSTR-1A** before 3B is filed. `[P/S]` (Originally announced for
   April 2025 and deferred — GSTN dates slip.)
2. **Three-year filing bar.** Proviso to §§37, 39, 44, 52 CGST (Finance Act
   2023, Notification 28/2023-CT). Portal enforcement from the **September 2025
   period**. `[P/S]` — reported advisory dates conflict; substance consistent.
3. **Rate structure changed 22 September 2025** to broadly two slabs (5%, 18%)
   plus a 40% demerit rate. `[S]`, widely reported, notification unread. This
   touches the product's rate handling, not the filing rails.

⚠️ Vendor blogs claim "January 2026 hard ITC validations" and "April 2026
mandatory e-invoicing". **Neither confirmed; one looks like a conflation.** `[U]`

## 5. e-invoicing — the useful asymmetry

**Threshold: ₹5 crore AATO, from 1 August 2023** (Notification 10/2023-CT). The
test is turnover exceeding ₹5 crore in *any* FY from 2017-18 onward, and once
crossed you stay in. `[P/S]`

Six authorised IRPs, `einvoice1`–`einvoice6`: NIC runs 1 and 2 (free); ClearTax,
Cygnet, EY and IRIS run 3–6. `[P/S]`

**Here is where the model diverges from returns, and it is the most actionable
finding in this file:**

- **Direct API access is activated for GSTINs with turnover above ₹500 crore.** `[P]`
- ₹100–500 crore: GSP route only. `[S]`
- **The sandbox is self-service, at any turnover.** `einv-apisandbox.nic.in` —
  register, pick a category, give PAN/GSTIN plus the mobile and email registered
  on the GST portal, verify OTP, receive **Client Id and Client Secret**. No IP
  whitelisting for sandbox. `[P]`

> **GSP is a hard gate for returns. It is not a gate for building and testing
> e-invoice rails.** That path is open today with any GSTIN, which is different
> sequencing from "GSP first, everything after".

**The 30-day reporting limit.** From **1 April 2025**, taxpayers with **AATO ≥
₹10 crore** cannot report an e-invoice more than **30 days after the document
date** — invoices, credit notes and debit notes alike. It is an **IRP
validation**, not advice: past 30 days, IRN generation is refused. Previously
₹100 crore from 1 Nov 2023. `[P/S]` No restriction below ₹10 crore "as of now" —
phrasing in the advisory itself that signals this will drop again.

## 6. e-way bill

Run by **NIC**, not GSTN, with its own developer portal at
`docs.ewaybillgst.gov.in/apidocs/`. `[P]` Same ₹500 crore direct-access
threshold; ₹100–500 crore is GSP-only. `[S]` **API enablement is self-service on
the EWB portal** (API Registration → Create API User → OTP). `[S]`

The same GSP typically serves all three — every GSP examined bundles GSTN
returns, NIC e-way bill and IRP e-invoice under one contract. `[S]`

## 7. Costs and timelines — all weak

**There are no public price lists.** Every full-suite GSP sells behind a sales
conversation.

| Item | Figure | Grade |
|---|---|---|
| GSP → ASP per API call | **10 paise – ₹1** | `[S]` single undated source. Sanity-check it: one GSTR-1 filing is many calls (auth, chunked save, submit, summary, file, status), so per-return cost is a multiple |
| GSTN → GSP | cost-recovery; free in year 1 | `[P/S]` but describes 2017-18, almost certainly stale `[U]` |
| Integration timeline | 15–25 business days | `[S]` vendor marketing. **Optimistic** — excludes GSP contracting and legal, usually the long pole |
| GSP licence fee | not found | `[U]` |
| Security audit cost | not found | `[U]` |

⚠️ **No evidence GSTN mandates a CERT-In empanelled VAPT for GSPs.** Some
advertise it voluntarily. Do not assume either way. `[U]`

## 8. One free source worth reading before designing anything

GSTN runs a **public GSP discussion group** on Google Groups
(`gst-suvidha-provider-gsp-discussion-group`) where it posts API release notes
and GSPs raise bugs. `[P]` It is publicly readable and is the best free source of
ground truth on actual API behaviour, including real failure modes — submit
errors, summary-API failures, the GSTR-2B download breaking past 1,000 invoices.

## 9. Verify before relying on any of this

1. **Rule 26 — is DSC still mandatory for companies and LLPs?** Highest
   priority; decides the addressable market for an EVC-only design.
2. Whether GSP applications are open, and the batch-5 ₹50 lakh criterion.
3. Whether GSTR-9 can be *filed* (not just fetched) via API. GSTR-9C at all.
4. The current API version matrix.
5. Whether GSTN still uses AES-ECB.
6. GSP licence fees and current GSTN cost-recovery rates.
7. The claimed Jan-2026 ITC validation and Apr-2026 e-invoicing changes.

## 10. What this means for the code

- `domain/gst/gstr1_builder.py` targets **GSTN API Specification v1.3 (July
  2023)**. Given that live endpoints were observed at v2.2 and v4.0, **treat
  that as likely stale** and re-check against the GSP's current spec before
  relying on the payload shape.
- `domain/gst/portal_service.py` is the seam. Its `get_provider(provider_name)`
  takes a name and ignores it — wire the switch in the same commit that adds a
  second provider, not after.
- A filing integration is **long-running, chunked and resumable by nature** —
  closer in shape to "Pass N ready" bank entries than to a report request. Note
  that `lib/api` aborts at 45 seconds and the abort is deliberately never
  retried.
- Per-GSTIN API consent is a **first-class product surface**, not an
  implementation detail: expiring (6h–30d), client-owned, revocable without
  notice, and now announced to the client by SMS naming this product.
