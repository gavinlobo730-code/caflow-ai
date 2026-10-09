"""THE CLAIMS LEDGER — every capability and security sentence on the marketing site,
what fact it asserts, and the test that proves the fact (market_and_trust-09).

`apps/marketing` has no test runner, and the guard that already existed
(`test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`) is a list of
sentences somebody had ALREADY found false: a FORBIDDEN regex per past mistake. That is
a record of drift, not protection from the next one — SSO on the Firm plan, "audit logs"
meaning every table, "collected in the portal" for a portal that cannot receive a file
and "a file that is ready to submit" for an ITR that is refused are all sentences no
pattern had been written for. This is the other half: a sentence that matches the
vocabulary in `_marketing_vocabulary.py` and is not written down here FAILS
`test_every_capability_sentence_on_the_marketing_site_is_in_the_claims_ledger.py`, the
day it is written, in the required backend check.

HOW TO READ AN ENTRY.

  A CLAIM is one fact. Its `says` are the exact sentences on the site that assert it,
  each with the files it appears in — a sentence may support several claims (the hosting
  sentence asserts three: the database, the servers and the AI providers), and a claim
  usually has several sentences. `fact` is the claim in the words the CODE would use,
  which is the thing a reviewer compares the sentence against.

  STATUS says how the fact is held, and the three are not interchangeable:

    proven      a test fails if the fact stops being true. `proofs` are `file::test`
                node ids and the guard checks each one still exists, so a renamed or
                deleted test cannot leave the claim pointing at nothing. `not_proved`
                names what the tests do NOT reach — the ledger is not a certificate
                that the sentence is complete, only of what is pinned.

    commitment  not behaviour of the code at all: where a hosted database is, how a
                support desk is staffed. No test can prove it, so `commitment` says who
                keeps it true and where it is recorded. It is visible and it is not
                hidden inside "proven".

    unproven    the sentence promises a capability or a protection and nothing backs it
                up — and it may simply be false. These are held in a FROZEN LIST in the
                guard, asserted as an equality, so a new one cannot be added quietly and
                a fixed one has to be taken off the list in the same commit. `decision`
                is what the owner has to decide, because every one of them is a
                commercial or product choice rather than something to quietly reword.

WRITE THE SENTENCE WHOLE, and word it as the code would. The extractor sees string
literals and JSX text; a sentence assembled at run time is read as the fragments around
the join and is invisible to this whole mechanism (see `_marketing_copy.py`).

WHAT THIS DOES NOT DO. It does not judge whether a proof is the RIGHT test: a reviewer
who adds an entry is making that judgement, and the reviewer after them can read it in
one place. It does not cover images or PDFs. And it covers claims by VOCABULARY, so a
capability sentence using words nobody listed is the next gap — the answer is to add the
word to `_marketing_vocabulary.py`, not to loosen anything here.
"""
from __future__ import annotations

from dataclasses import dataclass

PROVEN = "proven"
COMMITMENT = "commitment"
UNPROVEN = "unproven"
STATUSES = (PROVEN, COMMITMENT, UNPROVEN)


@dataclass(frozen=True)
class SaysEntry:
    text: str
    where: tuple[str, ...]


def Says(text: str, *where: str) -> SaysEntry:  # noqa: N802 - reads as a table row
    return SaysEntry(text, tuple(sorted(where)))


@dataclass(frozen=True)
class Claim:
    id: str
    status: str
    fact: str
    says: tuple[SaysEntry, ...]
    proofs: tuple[str, ...] = ()
    not_proved: str = ""
    commitment: str = ""
    decision: str = ""

    def __post_init__(self):
        assert self.status in STATUSES, f"{self.id}: status must be one of {STATUSES}"
        assert self.says, f"{self.id}: a claim with no sentence is not a claim on the site"
        if self.status == PROVEN:
            assert self.proofs, f"{self.id}: 'proven' needs at least one test"
        if self.status == COMMITMENT:
            assert self.commitment and not self.proofs, (
                f"{self.id}: a commitment says who keeps it true and carries no test — "
                "a test would make it 'proven'")
        if self.status == UNPROVEN:
            assert self.decision and not self.proofs, (
                f"{self.id}: an unproven claim names the decision the owner owes")


# Where a sentence is, named once so the table below stays readable.
HOME = "app/(site)/page.tsx"
PRICING = "app/(site)/pricing/page.tsx"
PRODUCTS = "app/(site)/products/page.tsx"
SUPPORT = "app/(site)/support/page.tsx"
RESOURCES = "app/(site)/resources/page.tsx"
DEMO = "app/(site)/demo/page.tsx"
ACCESS = "app/access/page.tsx"
HERO = "components/home/Hero.tsx"
ECOSYSTEM = "components/home/Ecosystem.tsx"
AI_IN_ACTION = "components/home/AiInAction.tsx"
BEFORE_AFTER = "components/home/BeforeAfter.tsx"
SHOWCASE = "components/home/ProductShowcase.tsx"


CLAIMS: tuple[Claim, ...] = (
    Claim(
        id="mfa-two-roles",
        status=PROVEN,
        fact="A TOTP second factor is required of a Partner or Manager on the routers that carry mfa_guard — firm profile, assignments, identity, practice, billing and payroll — and on approving or rejecting a request. An Executive or Reviewer is not asked for one.",
        proofs=(
            "tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py::test_the_mfa_sentence_names_who_is_asked",
            "tests/test_mfa_guards_the_data_not_only_the_admin.py::test_payroll_is_behind_the_mfa_guard",
            "tests/test_mfa_guards_the_data_not_only_the_admin.py::test_the_firm_administration_routers_keep_the_guard",
            "tests/test_the_security_posture_is_visible_and_fails_closed.py::test_in_production_an_unset_or_unreadable_switch_means_on",
            "tests/test_the_facts_behind_the_marketing_claims.py::test_approving_and_rejecting_a_request_each_ask_for_a_second_factor",
        ),
        not_proved="Whether a given person has enrolled an authenticator: the guard refuses an unenrolled Partner or Manager, and the copy claims only that a factor is REQUIRED. REQUIRE_MFA defaults on in production and an explicit false still turns it off.",
        says=(
            Says("TOTP, not an SMS code, is required of Partners and Managers on firm administration, billing, payroll and approvals.", HOME),
            Says("Two-factor where the firm is run", HOME),
            Says("Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, and everyone works under role-based access, so only your team sees your clients' information.", PRICING),
            Says("TOTP two-factor for Partners and Managers on firm administration, billing, payroll and approvals, and role-based access on every account.", PRICING),
            Says("Two-factor authentication", PRICING, PRODUCTS),
            Says("TOTP-based MFA is required of Partners and Managers on firm administration, billing, payroll and approvals.", PRODUCTS),
            Says("Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, access is by role and by client assignment, and the audit log records who created, changed or deleted a client, invoice, bill, receipt or ledger entry — it records changes, not views.", SUPPORT),
            Says("Email & password sign-in, with two-factor for Partners and Managers", ACCESS),
            Says("Two-factor sign-in for Partners and Managers · Database in Mumbai", ACCESS),
        ),
    ),
    Claim(
        id="access-by-role-and-assignment",
        status=PROVEN,
        fact="Every route is behind a role check (Partner > Manager > Executive > Reviewer > Client), and a Manager or Executive reaches only the clients they are assigned to; firm-wide reports mean the caller's own clients.",
        proofs=(
            "tests/test_write_requires_write_permission.py::test_no_mutating_route_is_guarded_by_a_read_level_action",
            "tests/test_rbac_coverage.py::test_every_rbac_resource_action_is_defined",
            "tests/test_router_client_scope.py::test_every_endpoint_in_an_audited_router_consults_client_scope",
        ),
        not_proved="The roughly 83 tables the browser reads straight over PostgREST are protected by row-level security and not by rbac(); CLAUDE.md records which of them are not yet assignment-scoped.",
        says=(
            Says("Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, and everyone works under role-based access, so only your team sees your clients' information.", PRICING),
            Says("TOTP two-factor for Partners and Managers on firm administration, billing, payroll and approvals, and role-based access on every account.", PRICING),
            Says("PracticeSync is built around how Indian CA firms actually work: the database is in Mumbai, access is by role and by client assignment, every change to a client, invoice, bill, receipt or ledger entry is written to an audit log, and no filing ever leaves your hands without your confirmation.", PRODUCTS),
            Says("Role-based access", PRODUCTS),
            Says("Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, access is by role and by client assignment, and the audit log records who created, changed or deleted a client, invoice, bill, receipt or ledger entry — it records changes, not views.", SUPPORT),
        ),
    ),
    Claim(
        id="tenant-isolation",
        status=PROVEN,
        fact="Every firm-scoped row carries firm_id, queries filter on it in the application, and row-level security enforces it again in the database.",
        proofs=(
            "tests/test_rls_covers_every_granted_table_pg.py::test_no_table_granted_to_authenticated_has_rls_disabled",
            "tests/test_r230_cross_tenant_isolation.py::test_create_schedule_rejects_another_firms_client",
            "tests/test_tenancy_backstop.py::test_get_run_slips_cross_firm_is_404",
        ),
        not_proved="The API runs on the service-role key, which bypasses RLS, unless USE_USER_JWT is on; the application-layer filter is the primary control and the cross-tenant tests cover the routers they name, not every query.",
        says=(
            Says("Every row carries the firm it belongs to, filtered in the application and enforced again by row-level security in the database.", HOME),
        ),
    ),
    Claim(
        id="portal-principals-separate",
        status=PROVEN,
        fact="A client and an employee are separate principals from staff: the employee API is read-only and takes no identifying parameter, and neither principal holds an RBAC role.",
        proofs=(
            "tests/test_an_employee_can_see_their_own_withholding.py::test_no_employee_route_takes_an_identifying_parameter",
            "tests/test_an_employee_can_see_their_own_withholding.py::test_the_employee_api_is_read_only",
            "tests/test_an_employee_can_see_their_own_withholding.py::test_every_employee_route_resolves_the_principal",
        ),
        says=(
            Says("The client portal and the employee portal are separate principals with their own, narrower access.", HOME),
        ),
    ),
    Claim(
        id="employee-portal",
        status=PROVEN,
        fact="An employee signs in to their own portal and can download their own released payslip, see their leave balance, file their Form 12BB declaration and see the tax their employer will deduct.",
        proofs=(
            "tests/test_an_employee_can_download_their_own_payslip.py::test_an_employee_downloads_their_own_released_payslip",
            "tests/test_262_employee_portal_rls_pg.py::test_employee_sees_own_leave_balance",
            "tests/test_297_employee_declaration_rls_pg.py::test_employee_can_file_their_own_declaration",
            "tests/test_an_employee_can_see_their_own_withholding.py::test_the_employee_sees_exactly_what_the_CA_sees",
            "tests/test_employee_portal_provisioning.py::test_invite_then_activate_grants_access",
        ),
        says=(
            Says("Employees get their own secure login for payslips, leave and their tax declaration, so nobody emails HR for a salary slip again.", PRODUCTS),
            Says("Download your payslips, check your leave balance and file your own tax declaration.", ACCESS),
            Says("A payroll run with PF, ESI and §192 TDS, and the employee portal your client's staff would use", DEMO),
            Says("Employee portal — payslips, leave balance, the tax declaration and a projection of the tax to be deducted", PRODUCTS),
            Says("Payroll & the employee portal", PRODUCTS),
            Says("Salary runs with the statutory built in — and a portal your client's staff use themselves", PRODUCTS),
            Says("Sign in to PracticeSync — choose the firm workspace or the client portal.", ACCESS),
            Says("Employee portal: payslips, leave, Form 12BB and tax deducted", ECOSYSTEM),
            Says("The monthly cycle, the leaver and the statutory registers — with an employee portal your client's staff use themselves, so nobody emails HR for a payslip.", ECOSYSTEM),
        ),
    ),
    Claim(
        id="client-portal",
        status=PROVEN,
        fact="A client invited by their firm signs in to a portal that shows the documents and reports the firm shares, what the firm has asked for, their invoices, and a message thread. A client cannot upload to it.",
        proofs=(
            "tests/test_portal_data_surfaces.py::test_list_invoices_scoped_and_isolated",
            "tests/test_r440_portal_client_can_post_a_message_pg.py::test_a_portal_client_can_post_to_their_own_thread",
            "tests/test_sharing_a_report_to_a_portal_is_decided_once.py::test_a_report_nobody_named_is_refused_rather_than_written_through",
            "tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py::test_the_site_does_not_make_this_claim",
        ),
        not_proved="That a client can fulfil a document request by uploading: that is deliberately not built (apps/web/app/portal/dashboard says so), which is why no sentence may claim it.",
        says=(
            Says("Every entity, relationship and engagement in a single place, with health scoring and a secure portal to share documents and updates with your client.", PRODUCTS),
            Says("Every entity, relationship and engagement together, with a secure portal for sharing documents and what you have done.", ECOSYSTEM),
            Says("Secure client portal — the documents you share, what you have asked for, and messages", PRODUCTS),
            Says("Sign in to PracticeSync — choose the firm workspace or the client portal.", ACCESS),
            Says("Client portal for documents, invoices and updates", ECOSYSTEM),
        ),
    ),
    Claim(
        id="database-in-mumbai",
        status=COMMITMENT,
        fact="The firm's and clients' records are stored in a Supabase Postgres database in the ap-south-1 (Mumbai) region.",
        commitment="A fact about where a hosted database is, which no test can read. It is recorded in CLAUDE.md and in the comment above the region in render.yaml. The owner confirms it against the Supabase dashboard before each pricing or security review; if the project is ever moved, every sentence under this claim is wrong at once.",
        says=(
            Says("PracticeSync is built around how Indian CA firms actually work: the database is in Mumbai, access is by role and by client assignment, every change to a client, invoice, bill, receipt or ledger entry is written to an audit log, and no filing ever leaves your hands without your confirmation.", PRODUCTS),
            Says("Two-factor sign-in for Partners and Managers · Database in Mumbai", ACCESS),
            Says("The database is in the Mumbai region; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", PRICING),
            Says("Your records sit in a database in Mumbai; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", SUPPORT),
            Says("Your firm's and your clients' records sit in a database in the Mumbai region.", HOME),
            Says("Records sit in a Mumbai database.", PRICING),
            Says("Your firm's and your clients' records are stored in a database in the Mumbai region.", PRODUCTS),
        ),
    ),
    Claim(
        id="app-servers-singapore",
        status=PROVEN,
        fact="The API runs on Render in the Singapore region.",
        proofs=(
            "tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py::test_the_render_region_the_site_names_is_the_one_render_uses",
            "tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py::test_the_hosting_sentence_names_the_database_and_the_rest",
        ),
        says=(
            Says("The application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", HOME, PRODUCTS),
            Says("The database is in the Mumbai region; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", PRICING),
            Says("The servers that run the application are in Singapore, and the AI features call providers outside India.", PRICING),
            Says("Your records sit in a database in Mumbai; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", SUPPORT),
        ),
    ),
    Claim(
        id="ai-leaves-india",
        status=PROVEN,
        fact="Document text and images are sent to AI providers outside India — Groq for text and Google (Gemini) for pictures — after PAN and GSTIN shapes are replaced in chat requests.",
        proofs=(
            "tests/test_the_facts_behind_the_marketing_claims.py::test_a_model_call_leaves_for_a_provider_outside_india",
            "tests/test_no_model_call_site_sends_an_identifier.py::test_a_gstin_and_a_pan_are_replaced",
        ),
        not_proved="Names are not pseudonymised, and document extraction is exempt from the redaction by name (the supplier's GSTIN is printed on the invoice being read).",
        says=(
            Says("The application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", HOME, PRODUCTS),
            Says("The database is in the Mumbai region; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", PRICING),
            Says("The servers that run the application are in Singapore, and the AI features call providers outside India.", PRICING),
            Says("Your records sit in a database in Mumbai; the application servers run in Singapore, and the AI features send the text or image of a document to an AI provider outside India.", SUPPORT),
        ),
    ),
    Claim(
        id="dpdp-bank-retention",
        status=PROVEN,
        fact="An uploaded bank statement is a retention category of its own in the DPDP position, with the Companies Act s. 128(5) period deciding it and the client as the duty holder.",
        proofs=(
            "tests/test_bank_data_retention_names_the_statute.py::test_bank_data_is_in_the_retention_position_at_all",
            "tests/test_bank_data_retention_names_the_statute.py::test_the_companies_act_is_the_period_that_decides",
        ),
        says=(
            Says("Bank statements are handled as their own retention category under the DPDP Act.", HOME),
        ),
    ),
    Claim(
        id="no-ai-key-in-the-browser",
        status=PROVEN,
        fact="No AI provider key is read, named or shipped by apps/web or apps/marketing; every model call is made by apps/api.",
        proofs=(
            "tests/test_the_facts_behind_the_marketing_claims.py::test_no_ai_key_is_named_in_either_browser_app",
        ),
        says=(
            Says("No AI key ever reaches the browser — every model call is made server-side.", HOME),
        ),
    ),
    Claim(
        id="ai-proposes-never-files",
        status=PROVEN,
        fact="Extraction and insight arrive as drafts a person confirms: an extracted bill goes through the one create path as a draft, and nothing in the product transmits a return.",
        proofs=(
            "tests/test_an_extracted_bill_goes_through_the_one_create_path.py::test_a_matched_extraction_still_creates_a_draft_bill",
            "tests/test_filing_simulation_never_files.py::test_the_real_filing_path_still_demands_an_explicit_ca_confirmation",
        ),
        says=(
            Says("AI that proposes, never files", HOME),
        ),
    ),
    Claim(
        id="ai-reads-pictures-and-text-separately",
        status=PROVEN,
        fact="A photographed bill goes to a vision model, a typed PDF goes to the text model, and a PDF with no text layer is read as pictures and never sent to the text model.",
        proofs=(
            "tests/test_a_scanned_pdf_is_read_as_a_picture_or_refused.py::test_a_scanned_pdf_goes_to_the_image_path_and_never_the_text_model",
            "tests/test_a_scanned_pdf_is_read_as_a_picture_or_refused.py::test_a_digital_pdf_still_takes_the_text_path",
            "tests/test_r2_8_ai_extraction.py::test_image_upload_routes_through_the_vision_extractor_not_text",
        ),
        says=(
            Says("A photographed bill goes to a vision model; a typed PDF goes to the text one.", AI_IN_ACTION),
        ),
    ),
    Claim(
        id="ai-document-extraction",
        status=PROVEN,
        fact="A photo or PDF uploaded against a client is read by an AI model into a draft purchase bill whose figures are checked to add up.",
        proofs=(
            "tests/test_r2_8_ai_extraction.py::test_successful_extraction_returns_real_data",
            "tests/test_an_extracted_invoice_has_to_add_up.py::test_a_misread_digit_is_reported_with_the_amount",
        ),
        says=(
            Says("A photo of a purchase bill is uploaded against the client", AI_IN_ACTION),
            Says("Your team uploads the photo or PDF a client sends, against that client's books — one upload, straight into the reader below.", AI_IN_ACTION),
        ),
    ),
    Claim(
        id="support-service",
        status=COMMITMENT,
        fact="The vendor answers by email and phone, Monday to Saturday 9am-7pm IST, with priority support on the Practice and Firm plans.",
        commitment="A service the owner runs, not behaviour of the code, so no test can prove it. It exists only as copy on the Support and Pricing pages; the owner is the one who can keep it true (staffing, the phone line, the hours). If the hours or the channels change, this entry and the Support page change together.",
        says=(
            Says("Email support", PRICING, SUPPORT),
            Says("Priority support", PRICING),
            Says("Every PracticeSync plan includes real support from people who understand CA workflows.", SUPPORT),
            Says("Get help with PracticeSync — guides, email and phone support, plus hands-on onboarding and data migration for Indian CA firms moving from Tally, ClearTax or Winman.", SUPPORT),
            Says("Our support team is available Monday to Saturday, 9am–7pm IST.", SUPPORT),
            Says("Phone support", SUPPORT),
            Says("Reach our support line during working hours for a quick hand with anything that needs a conversation.", SUPPORT),
            Says("Speak to our support team during working hours, Monday to Saturday, 9am–7pm IST.", SUPPORT),
        ),
    ),
    Claim(
        id="onboarding-service",
        status=COMMITMENT,
        fact="The Firm plan includes dedicated onboarding and data migration, Practice and Firm get a dedicated onboarding specialist, and the team will help import client masters and opening balances on any plan.",
        commitment="A service the owner runs. The product side of it is real and pinned elsewhere (customer and vendor masters import from Tally, opening balances load bill by bill — see tally-masters-only); the staffing and the plan boundary are the owner's.",
        says=(
            Says("Dedicated onboarding & migration", PRICING),
            Says("The Firm plan includes dedicated onboarding and data migration, and our team can help import client masters and opening balances on any plan.", PRICING),
            Says("Get help with PracticeSync — guides, email and phone support, plus hands-on onboarding and data migration for Indian CA firms moving from Tally, ClearTax or Winman.", SUPPORT),
            Says("Practice and Firm plans also get a dedicated onboarding specialist to set up your team, templates and compliance calendar.", SUPPORT),
        ),
    ),
    Claim(
        id="posted-documents-are-immutable",
        status=PROVEN,
        fact="A posted ledger entry that came from a document cannot be deleted or edited in place: the database refuses it, and a correction is a reversal.",
        proofs=(
            "tests/test_r251_journal_line_immutability_pg.py::test_cannot_change_a_posted_line_amount",
            "tests/test_r251_journal_line_immutability_pg.py::test_cannot_delete_a_posted_line",
            "tests/test_r266_journal_edit_until_locked_pg.py::test_a_posted_entry_still_cannot_be_deleted",
            "tests/test_discard_manual_journal_pg.py::test_an_auto_posted_entry_is_refused",
        ),
        says=(
            Says("A posted entry that came from a document — an invoice, a bill, a receipt — is never deleted or edited in place; a correction is an append-only reversal.", HOME),
        ),
    ),
    Claim(
        id="manual-journal-edit-is-bounded-and-logged",
        status=PROVEN,
        fact="A manual journal may be edited or soft-deleted only while its period is open, and every deletion writes the whole entry, its lines and their account names to the audit log in the same transaction.",
        proofs=(
            "tests/test_discard_manual_journal_pg.py::test_a_manual_entry_in_an_open_period_is_discarded",
            "tests/test_discard_manual_journal_pg.py::test_a_locked_financial_year_refuses_the_discard",
            "tests/test_discard_manual_journal_pg.py::test_the_deletion_writes_an_audit_row",
            "tests/test_discard_manual_journal_pg.py::test_the_audit_row_holds_every_line",
        ),
        says=(
            Says("A manual journal can be edited or discarded only while its period is open, and every deletion writes the whole entry and its lines to the audit log in the same transaction.", HOME),
        ),
    ),
    Claim(
        id="corrections-are-reversals",
        status=PROVEN,
        fact="A correction to a posted document is an append-only reversal that posts the balanced opposite and leaves the original unchanged.",
        proofs=(
            "tests/test_journal_reversal_kernel.py::test_reversal_posts_balanced_opposite_via_kernel",
            "tests/test_journal_reversal_kernel.py::test_original_entry_is_not_modified",
        ),
        says=(
            Says("Corrections to posted documents are append-only reversals, so the audit trail always foots", PRODUCTS, ECOSYSTEM),
        ),
    ),
    Claim(
        id="audit-log-named-records",
        status=PROVEN,
        fact="The audit trigger writes who created, changed or deleted a client, invoice, bill, receipt, ledger entry or payroll record; it records changes and not views.",
        proofs=(
            "tests/test_the_database_facts_the_marketing_site_states_pg.py::test_the_records_the_site_names_carry_the_audit_trigger",
            "tests/test_the_database_facts_the_marketing_site_states_pg.py::test_a_signed_in_users_write_to_a_named_record_lands_in_the_audit_log",
            "tests/test_the_audit_log_names_one_kind_of_actor.py::test_no_audit_event_is_attributed_with_the_internal_user_id",
        ),
        not_proved="'Audit logs' and 'Audit log of changes' name the feature, not every table: on a freshly migrated database 120 of 288 firm-scoped tables carry the trigger (measured 2026-10-01 IST). The 168 created after migration 111's one-shot loop do not — among them client_year_locks, user_permissions, itr_filings, payroll_settlements and the credit and debit note tables. The trigger records a write only when auth.uid() is present — the browser, and the API while USE_USER_JWT is on (the production default since 2026-09-30); a service-role write is covered only by an explicit audit_service.log_event. No sentence may say 'each record' or 'everything is logged'.",
        says=(
            Says("PracticeSync is built around how Indian CA firms actually work: the database is in Mumbai, access is by role and by client assignment, every change to a client, invoice, bill, receipt or ledger entry is written to an audit log, and no filing ever leaves your hands without your confirmation.", PRODUCTS),
            Says("Partners and Managers use two-factor authentication on firm administration, billing, payroll and approvals, access is by role and by client assignment, and the audit log records who created, changed or deleted a client, invoice, bill, receipt or ledger entry — it records changes, not views.", SUPPORT),
            Says("Audit logs", PRICING),
            Says("Audit log of changes", PRODUCTS),
        ),
    ),
    Claim(
        id="nothing-is-transmitted",
        status=PROVEN,
        fact="The software never transmits anything to a government portal: GST, income-tax, TDS and MCA outputs are prepared and the CA files them; the filing demo writes nothing and its reference says it was not filed.",
        proofs=(
            "tests/test_filing_simulation_never_files.py::test_the_real_filing_path_still_demands_an_explicit_ca_confirmation",
            "tests/test_filing_simulation_never_files.py::test_every_flows_reference_says_not_filed",
            "tests/test_filing_simulation_never_files.py::test_the_demo_cannot_move_a_returns_status",
            "tests/test_the_facts_behind_the_marketing_claims.py::test_no_server_code_addresses_a_government_portal",
        ),
        says=(
            Says("PracticeSync is built around how Indian CA firms actually work: the database is in Mumbai, access is by role and by client assignment, every change to a client, invoice, bill, receipt or ledger entry is written to an audit log, and no filing ever leaves your hands without your confirmation.", PRODUCTS),
            Says("AI that proposes, never files", HOME),
            Says("Every GST return, income-tax return, TDS statement and MCA form waits for an explicit confirmation from a Chartered Accountant — and even then, it is that CA who files it on the portal.", HOME),
            Says("Returns the software files for you — you sign every one", HOME, HERO),
            Says("You file it.", HOME),
            Says("Nothing auto-submitted", PRICING),
            Says("PracticeSync prepares the return; a CA files it on the portal.", PRICING),
            Says("The software never transmits anything to a government portal.", PRICING),
            Says("The software never transmits anything to a portal, for GST, ITR, TDS or MCA.", PRICING),
            Says("No return is ever transmitted by the software.", PRODUCTS),
            Says("PracticeSync also never transmits anything to a government portal — it prepares the return and a CA files it themselves.", SUPPORT),
            Says("PracticeSync computes the return, reconciles it and hands you the GST file to upload or the figures to key in — a Chartered Accountant signs and files it on the government portal, and records it back here.", AI_IN_ACTION),
            Says("The software never transmits a return, for any tax, ever.", AI_IN_ACTION),
            Says("Surfaces what needs attention; never acts on a filing by itself", ECOSYSTEM),
            Says("Nothing filed without your click", HERO),
        ),
    ),
    Claim(
        id="portal-filing-recorded-here",
        status=PROVEN,
        fact="The CA uploads and signs on the government portal and then records the ARN in the product, which writes the filings row that locks the period.",
        proofs=(
            "tests/test_documents_locked_by_filed_return.py::test_a_filed_return_names_itself_and_the_date_it_was_filed",
            "tests/test_filing_simulation_never_files.py::test_the_demo_cannot_move_a_returns_status",
        ),
        says=(
            Says("You upload and sign on the government portal, then record the ARN here and the period locks.", HOME),
            Says("You upload and sign it on the government portal yourself, then record it back here, which is what locks the period.", PRICING),
            Says("A Chartered Accountant uploads and signs it on the government portal — and then records it here, which is what locks the period.", PRODUCTS),
            Says("You file and sign on the portal, then record the ARN here — and the period locks", PRODUCTS),
            Says("a CA signs off; you file on the portal", BEFORE_AFTER),
        ),
    ),
    Claim(
        id="return-outputs-are-prepared",
        status=PROVEN,
        fact="GSTR-1 and GSTR-3B are produced as the JSON the GSTN utility reads; the income-tax return and the TDS statements are laid out as keying sheets — no ITR JSON and no FVU file is produced.",
        proofs=(
            "tests/test_gstr1_payload_matches_gstn_utility.py::test_b2cs_declares_the_supply_type_under_sply_ty",
            "tests/test_gstr3b_payload_matches_gstn_utility.py::test_itc_avl_has_the_five_rows_the_form_has_in_the_utilitys_order",
            "tests/test_itr_json.py::test_generating_a_file_is_still_refused",
            "tests/test_the_tds_keying_sheet_groups_what_was_already_computed.py::test_no_fvu_file_is_produced_is_always_present",
        ),
        says=(
            Says("PracticeSync computes the return, reconciles it and hands you the GST file to upload or the figures to key in — a Chartered Accountant signs and files it on the government portal, and records it back here.", AI_IN_ACTION),
            Says("PracticeSync reads your books and computes the return — GSTR-1 and GSTR-3B as the JSON you upload to the GST portal; GSTR-9, the income-tax return, 24Q and 26Q worked out and laid out for you to key into the government's own utilities.", HOME),
            Says("For GSTR-1 and GSTR-3B it produces the JSON file you upload; for the income-tax return and the TDS statements it lays the figures out for you to key into the government's own utility.", PRICING),
            Says("A client's GST month — GSTR-1, GSTR-3B and the 2B reconciliation against the purchase register", DEMO),
        ),
    ),
    Claim(
        id="tally-masters-only",
        status=PROVEN,
        fact="The Tally importer writes customer and vendor masters only, withholding a malformed GSTIN or PAN; ledgers, journals and opening balances are not imported through it.",
        proofs=(
            "tests/test_the_migration_screen_says_what_the_importer_writes.py::test_the_browser_lists_exactly_the_kinds_the_importer_writes",
            "tests/test_a_tally_import_does_not_carry_a_wrong_gstin_into_the_masters.py::test_a_transposed_gstin_is_withheld_and_named",
            "tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py::test_the_site_does_not_make_this_claim",
        ),
        not_proved="Opening balances are loaded by hand, bill by bill or from a trial balance (migration 391), which is a separate path from the importer.",
        says=(
            Says("Customer and vendor masters, written from a Tally XML export", PRODUCTS),
            Says("Export ledgers, masters and the trial balance from Tally", RESOURCES),
            Says("Import the customer and vendor masters, then map account groups", RESOURCES),
        ),
    ),
    Claim(
        id="tally-staged-import",
        status=PROVEN,
        fact="A Tally import is parsed, validated and previewed before anything is written; a dry run writes nothing, and a completed import can be rolled back across every record it created.",
        proofs=(
            "tests/test_tally_import_at_scale.py::test_a_dry_run_writes_nothing",
            "tests/test_tally_import_at_scale.py::test_rollback_reaches_every_created_record",
            "tests/test_a_tally_migration_job_can_be_discarded.py::test_a_non_terminal_job_can_be_discarded",
        ),
        says=(
            Says("A staged import that parses, validates and shows you a preview before anything is written — and rolls the whole batch back if the preview is wrong.", PRODUCTS),
            Says("Parse → validate → preview → import, with the preview before the write", PRODUCTS),
        ),
    ),
    Claim(
        id="statement-import-csv-xlsx",
        status=PROVEN,
        fact="A bank statement in CSV or XLSX is parsed and normalised on the server, in integer paise.",
        proofs=(
            "tests/test_bank_feed_import.py::test_xlsx_parse",
            "tests/test_bank_feed_import.py::test_csv_generic_parse",
            "tests/test_bank_feed_import.py::test_csv_integer_paise_no_float_drift",
        ),
        says=(
            Says("CSV and XLSX statement import, parsed and normalised on the server", PRODUCTS),
            Says("CSV and XLSX, parsed and normalised on the server", ECOSYSTEM),
        ),
    ),
    Claim(
        id="statement-lines-arrive-proposed",
        status=PROVEN,
        fact="Every imported statement line is given a proposed entry, and its kind — Receipt, Payment or Contra — is decided by direction and by whether it is a transfer between the client's own accounts.",
        proofs=(
            "tests/test_bank_entry.py::test_money_in_is_a_receipt_and_money_out_a_payment",
            "tests/test_bank_entry.py::test_a_transfer_is_a_contra_whichever_way_the_money_moved",
            "tests/test_bank_entries_router.py::test_the_screen_flow_redraft_counts_list_pass_ready",
        ),
        says=(
            Says("Upload a statement and every line arrives with a proposed entry already on it — Receipt, Payment or Contra, decided by direction.", PRODUCTS),
            Says("Upload a statement and each line comes back with a proposed entry already on it — Receipt, Payment or Contra, decided by direction rather than chosen.", ECOSYSTEM),
        ),
    ),
    Claim(
        id="bank-pass-ready-in-bulk",
        status=PROVEN,
        fact="The ready lines are passed in chunks that report what remains, and a proposed line is never passed in bulk.",
        proofs=(
            "tests/test_bank_entry_service.py::test_pass_ready_passes_only_ready_lines_in_chunks_and_never_a_proposed_one",
        ),
        says=(
            Says("Pass the ready ones in bulk — chunked and resumable", PRODUCTS, ECOSYSTEM),
        ),
    ),
    Claim(
        id="integer-paise",
        status=PROVEN,
        fact="Money is stored as integer paise: every *_paise column is an integer type and no money-named column is floating point.",
        proofs=(
            "tests/test_the_database_facts_the_marketing_site_states_pg.py::test_every_paise_column_is_an_integer_and_no_money_is_floating_point",
            "tests/test_bank_feed_import.py::test_csv_integer_paise_no_float_drift",
        ),
        not_proved="The Python arithmetic is covered by the per-module tests and by the browser's one-parser rule, not by a single guard over every calculation; GSTR-1 carries two-decimal rupees at the statutory boundary by design.",
        says=(
            Says("Raise invoices, record bills and issue credit and debit notes — with GST computed per line, in integer paise, so the books and the return agree by construction rather than by reconciliation.", PRODUCTS),
            Says("Expense, input tax, TDS withheld and the payable, in integer paise, asserted to balance before the entry is written.", AI_IN_ACTION),
            Says("Every rupee in integer paise — never floating point", ECOSYSTEM),
            Says("Invoices, bills, credit and debit notes, and the stock they move — with GST computed per line so the books and the return agree by construction rather than by reconciliation.", ECOSYSTEM),
        ),
    ),
    Claim(
        id="posting-kernel-balances",
        status=PROVEN,
        fact="Every ledger entry is asserted to balance before it is written, and the posting kernel refuses an unbalanced or zero-value entry.",
        proofs=(
            "tests/test_a_voucher_keeps_its_line_order_pg.py::test_the_posting_kernel_still_refuses_an_unbalanced_entry",
            "tests/test_accounting_completion.py::test_cannot_post_unbalanced_entry",
        ),
        says=(
            Says("Expense, input tax, TDS withheld and the payable, in integer paise, asserted to balance before the entry is written.", AI_IN_ACTION),
        ),
    ),
    Claim(
        id="return-computed-from-books",
        status=PROVEN,
        fact="GST returns are computed from the posted documents and the ledger, and the GSTR-3B output and input credit reconcile to the ledger.",
        proofs=(
            "tests/test_gst_return_reconciliation.py::test_gstr3b_output_and_itc_reconcile_to_ledger",
            "tests/test_gstr3b_detail_matches_the_summary.py::test_the_4a_detail_sums_to_table_4a",
        ),
        not_proved="Income-tax and TDS figures are computed from the same books by their own engines (each with its own tests); this entry pins the GST side the copy is most specific about.",
        says=(
            Says("PracticeSync reads your books and computes the return — GSTR-1 and GSTR-3B as the JSON you upload to the GST portal; GSTR-9, the income-tax return, 24Q and 26Q worked out and laid out for you to key into the government's own utilities.", HOME),
            Says("Raise invoices, record bills and issue credit and debit notes — with GST computed per line, in integer paise, so the books and the return agree by construction rather than by reconciliation.", PRODUCTS),
            Says("Invoices, bills, credit and debit notes, and the stock they move — with GST computed per line so the books and the return agree by construction rather than by reconciliation.", ECOSYSTEM),
            Says("PracticeSync runs alongside Tally and brings compliance, accounting, banking, payroll, clients and documents into one workspace on one ledger — where every return is computed from the books rather than assembled beside them.", HOME),
            Says("PracticeSync computes the return from your books.", PRICING),
            Says("Every return computed from the books, and every deadline tracked", PRODUCTS),
            Says("GST returns — GSTR-1 (due the 11th), GSTR-3B (due the 20th) and the GSTR-9 annual return (due 31 December), computed from your ledgers", PRODUCTS),
            Says("The return is computed from the books rather than assembled beside them.", BEFORE_AFTER),
            Says("returns computed from those books", BEFORE_AFTER),
            Says("Every return, computed from the books", ECOSYSTEM),
        ),
    ),
    Claim(
        id="gstr2b-reconciliation",
        status=PROVEN,
        fact="A GSTR-2B file is reconciled against the purchase register the product holds, naming which bills the supplier has not filed and how much input credit to hold back under Rule 36(4) and section 16(2)(aa).",
        proofs=(
            "tests/test_the_2b_reconciliation_reads_the_books.py::test_the_tax_is_on_the_rate_lines_not_the_invoice_header",
            "tests/test_a_2b_reconciliation_replaces_atomically_pg.py::test_a_re_upload_replaces_rather_than_accumulating",
            "tests/test_the_rule_36_4_working_reaches_the_screen.py::test_the_service_still_serves_the_whole_working",
        ),
        says=(
            Says("Then the portal file says the supplier has not filed it", AI_IN_ACTION),
            Says("A client's GST month — GSTR-1, GSTR-3B and the 2B reconciliation against the purchase register", DEMO),
            Says("GSTR-2B reconciliation — which bills your supplier has not filed, and how much input credit to hold back", PRODUCTS),
            Says("GSTR-2B reconciliation against the purchase register", ECOSYSTEM),
        ),
    ),
    Claim(
        id="einvoice-eway-prepared",
        status=PROVEN,
        fact="E-invoice IRN and e-way bill records are prepared for a CA to take to the portal; an IRN is printed only where the portal generated one.",
        proofs=(
            "tests/test_einvoice_eway_workflow.py::test_irn_full_lifecycle_with_treatment",
            "tests/test_the_invoice_prints_a_real_irn_and_never_a_made_up_one.py::test_a_recorded_irn_is_carried_through",
        ),
        says=(
            Says("E-invoice IRN and e-way bill records, prepared for the IRP", PRODUCTS, ECOSYSTEM),
        ),
    ),
    Claim(
        id="itr-schema-preparation",
        status=PROVEN,
        fact="Income-tax figures are mapped to the Department's own committed JSON schemas for all seven forms; generating the file itself is refused.",
        proofs=(
            "tests/test_itr_schema_paths.py::test_every_form_has_a_committed_schema",
            "tests/test_itr_schema_paths.py::test_every_mapped_path_exists_and_is_an_integer_field",
            "tests/test_itr_json.py::test_generating_a_file_is_still_refused",
        ),
        says=(
            Says("Income Tax — ITR preparation against the department's own JSON schemas, tax computation and advance-tax scheduling", PRODUCTS),
            Says("ITR preparation against the department's own JSON schemas", ECOSYSTEM),
        ),
    ),
    Claim(
        id="tds-statements-2026-vocabulary",
        status=PROVEN,
        fact="Quarterly 24Q, 26Q and 27Q statements are prepared, with the 2026 Act's renumbered form numbers and section codes translated at the boundary beside the 1961 ones.",
        proofs=(
            "tests/test_tds_returns_speak_the_statement_vocabulary_and_gate_nonsense.py::test_list_returns_translates_the_2026_fork",
        ),
        says=(
            Says("TDS — quarterly 24Q, 26Q and 27Q statements, with the 2026 Act's renumbered forms handled alongside the old ones", PRODUCTS),
            Says("Quarterly 24Q, 26Q and 27Q, with the 2026 Act's renumbered forms handled beside the old ones", ECOSYSTEM),
        ),
    ),
    Claim(
        id="gstr3b-setoff-and-rcm",
        status=PROVEN,
        fact="GSTR-3B Table 6 sets credit off in the four statutory steps and keeps reverse-charge tax out of it, because credit cannot pay it.",
        proofs=(
            "tests/test_gstr3b_setoff_and_rcm.py::test_one_period_carrying_all_three",
        ),
        says=(
            Says("Computed from the books, with the §49(5) set-off worked in order — and reverse charge kept out of it, because credit cannot pay it.", SHOWCASE),
        ),
    ),
    Claim(
        id="platform-overview",
        status=PROVEN,
        fact="The modules the overview names are the ones the product has, described the same way on every page.",
        proofs=(
            "tests/test_the_marketing_site_says_what_the_product_does.py::test_the_product_is_described_the_same_way_everywhere",
        ),
        not_proved="That every module is equally finished; the overview names what exists, and CLAUDE.md's Scope section is the record of how far each goes.",
        says=(
            Says("Explore the PracticeSync platform — compliance, accounting, sales & purchases, banking, inventory, payroll and the employee portal, clients & CRM, an AI assistant, workflow automation and practice analytics in one workspace built for Indian CA firms.", PRODUCTS),
        ),
    ),
)
