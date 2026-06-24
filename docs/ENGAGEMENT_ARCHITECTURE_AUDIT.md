# Engagement Architecture Audit

Status: **documentation only** — no migration performed in this sprint (per Objective 6).
Date: 2026-06-24. Scope: the two "engagement" tables and how they relate after the
Workflow Integrity Sprint.

## The two tables

| | `engagements` | `fee_engagements` |
|---|---|---|
| Introduced | migration `115_engagement_letter_management.sql` | migration `014_complete_missing_tables.sql` (extended by `108`) |
| Router | `routers/engagement_letters.py` (`/api/engagement-letters`) | `routers/engagements.py` (`/api/engagements`) via `engagement_repository.py` |
| Purpose | The **engagement LETTER** — the signed legal document that opens a mandate (CGST Act §31). Pre-conversion artefact tied to a `lead_id`. | The **service / billing ENGAGEMENT** — the ongoing fee relationship with an existing client. Post-conversion artefact tied to a `client_id`. |
| Key columns | `lead_id`, `client_id`, `template_id`, `title`, `fee_amount_paise`, `status`, `signed_at`, `signed_pdf_url` | `client_id`, `service_type`, `fee_paise`, `billing_cycle`, `status`, `assigned_to/reviewer_id/partner_id`, `due_date` |
| Status values | `Draft / Generated / Sent / Viewed / Signed / Rejected / Expired` | `Draft / Active / In Progress / Review / Completed / Closed / Inactive` |
| Lifecycle stage | Lead pipeline (Lead → … → Engagement Signed) | Client delivery lifecycle |

## Overlaps and duplicated data

1. **Fee is stored twice.** `engagements.fee_amount_paise` (the agreed fee on the
   signed letter) and `fee_engagements.fee_paise` (the billed fee). Before this
   sprint the `fee_engagements` row was created with `fee_paise = 0` and never
   reconciled. **Fixed in this sprint**: `convert_lead` now copies the signed
   letter's fee into the `fee_engagements` row at creation time.

2. **Service type is split.** The letter has no `service_type` column; it lives on
   `engagement_templates.service_type` (referenced via `engagements.template_id`).
   `fee_engagements.service_type` is a required free-text column. The conversion
   now resolves it from the template (fallback: letter title, then `"General"`).

3. **Client linkage.** Both tables carry `client_id`. The letter is `lead_id`-first
   and gets stamped with `client_id` at conversion (`convert_lead`). The fee
   engagement is `client_id`-only. There is **no foreign key between the two
   tables** — they are correlated only by `client_id` and by timing.

4. **Naming collision.** Both are called "engagement" in the UI. `engagement_repo`
   (used by `clients.py`, `search.py`, `compliance_obligation_service.py`,
   `invoice_generation_service.py`) points at `fee_engagements`; the engagements
   *page* (`/engagements`) shows `engagements` (letters). This is the single
   biggest source of human confusion.

## Risks

- **No referential link** between a signed letter and the fee engagement it
  produced. If a CA edits the fee engagement, the letter's `fee_amount_paise`
  silently diverges (the letter is the legal record; the fee engagement is what
  gets billed). Mitigated for *creation* by copying real data + a traceability
  note (`Auto-created from signed engagement EL-YYYY-NNNN`), but ongoing edits are
  still independent.
- **Status-machine confusion**: a letter can be `Signed` while its fee engagement
  is `Closed`, or vice-versa. They answer different questions and should not be
  conflated.
- **Deletion semantics differ**: letters soft-delete via terminal statuses
  (`Rejected`/`Expired`); fee engagements via `status = 'Inactive'`.

## Recommended future consolidation plan (NOT done here)

Do **not** merge the tables — they model genuinely different stages. Instead:

1. Add `fee_engagements.engagement_letter_id UUID REFERENCES engagements(id)` so the
   billing record points back to the legal document that authorised it (a real FK,
   replacing the current implicit correlation and the `notes` reference string).
2. Rename in the UI/API for clarity: "Engagement Letters" vs "Service Engagements"
   (or "Fee Engagements"). Keep table names; change labels and route copy.
3. Add a reconciliation check (or DB trigger / scheduled job) that flags when a
   live fee engagement's `fee_paise` diverges from its source letter's
   `fee_amount_paise` beyond an allowed tolerance.
4. Consider a single read-model/view (`v_client_engagements`) that joins both for
   the client detail page, so the UI stops querying two tables ad hoc.

Each of the above is additive and can ship independently; none requires a
destructive migration.
