-- Migration 336: keep the identifier OUT of the audit snapshot, not out of the log.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 111 put a generic audit trigger on every firm-scoped table with an
-- `id` column and wrote `to_jsonb(NEW)` / `to_jsonb(OLD)` — COMPLETE ROW
-- SNAPSHOTS, every column — into public.audit_log. audit_log blocks UPDATE and
-- DELETE by trigger (migration 082), so nothing written there can ever be
-- edited or removed.
--
-- The consequence was not visible until somebody counted. Measured on
-- production 2026-09-05: 46,311 audit rows since 19-06-2026, of which 1,470
-- already carried a `pan`, `uan`, `aadhaar_last4`, `bank_account_no`,
-- `date_of_birth` or a sibling — roughly 7,000 a year at a usage level where
-- payroll has barely been touched. DPDP Rule 8 (erasure) and Rule 14
-- (data-principal rights) commence 13-05-2027, and none of it can be reached.
--
-- It also cannot be fixed backwards. Those rows are immutable by design. The
-- only thing that can be changed is what gets written from here, which is why
-- this is worth doing 20 months before the deadline rather than near it: every
-- month of delay is permanent residue.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY REDACT THE VALUE AND KEEP THE KEY
-- ═══════════════════════════════════════════════════════════════════════════
-- The obvious move — drop the key — is worse than it looks. The audit log
-- exists to answer WHO CHANGED WHAT, AND WHEN. Dropping `pan` from the
-- snapshot loses the fact that the PAN changed at all; the row would look
-- identical to one where it did not.
--
-- So the key stays and only the value is replaced. `bank_account_no` still
-- appears in old_data and new_data on the row where it changed, both carrying
-- the marker, and the log still shows that this actor changed that field on
-- that record at that time. What is given up is the before/after VALUE of one
-- field — which is exactly the part DPDP objects to holding for ever and the
-- part an audit trail needs least.
--
-- NULL is left as NULL. "This field was empty" is information, and replacing it
-- with a marker would assert that something was there.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THIS DOES NOT WEAKEN THE EDIT LOG
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md treats the audit trail as load-bearing, and it is right to: the
-- proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires an EDIT
-- LOG, and the log is what is immutable, not the entry. That rule is about
-- accounting entries — who altered a voucher, when, and what moved. A PAN, a
-- UAN, an Aadhaar fragment and a bank account number are none of those. No
-- money moves when one changes, and no accounting record depends on the
-- previous value being recoverable from the log.
--
-- The figures that Rule 3(1) is about are untouched: nothing in the list below
-- appears on journal_entries, journal_lines, or any amount column anywhere.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS DELIBERATELY *NOT* REDACTED
-- ═══════════════════════════════════════════════════════════════════════════
-- The line is drawn at GOVERNMENT AND FINANCIAL IDENTIFIERS OF A PERSON.
-- Over-redaction is the failure that turns an audit log into a list of
-- timestamps, so four near-misses are excluded on purpose:
--
--   gstin, supplier_gstin  A GST registration is a BUSINESS identifier, public
--                          on the GST portal, and it is the key a CA reads to
--                          know which registration a change touched. (It embeds
--                          a proprietor's PAN, which is the argument the other
--                          way; the audit cost is judged higher.)
--   ifsc, ifsc_code,       A branch code identifies a BRANCH, not a person —
--   bank_ifsc              thousands share one. Harmless once the account
--                          number beside it is redacted.
--   bank_account_id        A uuid FOREIGN KEY, not an account number. Redacting
--                          it would break the join the audit is read through.
--   esic_employer_code     The EMPLOYER's registration, not an employee's.
--
-- Names, emails and phone numbers are also NOT redacted. They are personal
-- data, but they are how a human reads an audit row at all, and removing them
-- would leave a log nobody can use. That is a deliberate line, and it is the
-- one to revisit first if the position ever needs to be stricter — the list
-- below is a single ARRAY constant precisely so moving it is a one-line
-- migration.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SCOPE: ONE WRITER, BECAUSE ONLY ONE WRITER DOES THIS
-- ═══════════════════════════════════════════════════════════════════════════
-- audit_log has two writers: this trigger (browser writes, auth.uid() present)
-- and services/audit_service.log_event (backend, service-role). Measured on
-- production: of 893 service-role rows, ZERO carry an identifier — that path is
-- called with small hand-built intent dicts, not row snapshots. All 1,470
-- identifier-bearing rows came through this trigger.
--
-- So the redaction lives here and nowhere else. A Python twin would be a second
-- implementation of one rule, built for a case that does not occur.
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

-- The marker. A distinct sentinel rather than an empty string, so a reader can
-- tell "withheld" from "was blank" — those mean different things on an audit row.
CREATE OR REPLACE FUNCTION public.audit_redact(payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
DECLARE
  -- Government and financial identifiers OF A PERSON. Derived from the live
  -- schema on 2026-09-05, not written from memory. See the header for the four
  -- near-misses left out on purpose.
  k_redact CONSTANT text[] := ARRAY[
    'pan', 'deductee_pan', 'deductor_pan', 'landlord_pan', 'lender_pan', 'vendor_pan',
    'aadhaar_last4',
    'uan',
    'bank_account_no', 'account_number',
    'date_of_birth',
    'deductee_tin', 'tax_identification_number'
  ];
  k text;
  out_payload jsonb := payload;
BEGIN
  IF payload IS NULL THEN
    RETURN NULL;
  END IF;

  -- Short-circuit on the common case. Most audited tables carry none of these,
  -- and this fires on every browser write, so the cheap `?|` existence test
  -- comes before any per-key work.
  IF NOT (payload ?| k_redact) THEN
    RETURN payload;
  END IF;

  FOREACH k IN ARRAY k_redact LOOP
    -- Only where the key is present AND holds something. A NULL stays NULL:
    -- "this was empty" is a fact worth keeping, and a marker would deny it.
    IF (out_payload ? k) AND jsonb_typeof(out_payload -> k) <> 'null' THEN
      out_payload := jsonb_set(out_payload, ARRAY[k], '"[redacted]"'::jsonb);
    END IF;
  END LOOP;

  RETURN out_payload;
END;
$$;

COMMENT ON FUNCTION public.audit_redact(jsonb) IS
  'Replaces the VALUE of a person''s government/financial identifiers in an '
  'audit snapshot with "[redacted]", keeping the KEY so the log still shows '
  'which field changed. Migration 336; see that file for the list and for the '
  'four near-misses (gstin, ifsc, bank_account_id, esic_employer_code) that are '
  'deliberately not redacted.';

-- Same function as migration 111 in every other respect. Reproduced in full
-- rather than patched, because CREATE OR REPLACE takes the whole body and a
-- partial copy would silently drop the parts left out — the actor guard, the
-- firm-less skip, the entity-type normalisation, and the non-fatal EXCEPTION
-- block that keeps auditing from ever breaking a user's write.
CREATE OR REPLACE FUNCTION public.audit_capture()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor  uuid := auth.uid();
  v_email  text;
  v_firm   uuid;
  v_entity text;
  v_etype  text;
  v_action text;
  v_old    jsonb;
  v_new    jsonb;
BEGIN
  -- Only capture end-user (browser) writes. Service-role backend writes have a
  -- NULL auth.uid() and are audited in-app by audit_service.log_event.
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  -- THE ONLY CHANGE FROM MIGRATION 111: the snapshots go through audit_redact.
  -- firm_id and id are read from the redacted payload below, and neither is on
  -- the redaction list, so the routing still works exactly as it did.
  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := public.audit_redact(to_jsonb(NEW));
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update';
    v_new := public.audit_redact(to_jsonb(NEW));
    v_old := public.audit_redact(to_jsonb(OLD));
  ELSE
    v_action := 'delete'; v_old := public.audit_redact(to_jsonb(OLD));
  END IF;

  -- audit_log.firm_id is NOT NULL — skip any firm-less row.
  v_firm := nullif(coalesce(v_new->>'firm_id', v_old->>'firm_id'), '')::uuid;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  v_entity := coalesce(v_new->>'id', v_old->>'id');

  -- Normalise the table name to the app's singular entity vocabulary so events
  -- from triggers and from log_event share one set of filter values.
  v_etype := CASE TG_TABLE_NAME
    WHEN 'chart_of_accounts'   THEN 'account'
    WHEN 'accounts'            THEN 'account'
    WHEN 'compliance_calendar' THEN 'compliance'
    ELSE CASE
      WHEN TG_TABLE_NAME LIKE '%ies' THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 3) || 'y'
      WHEN TG_TABLE_NAME LIKE '%s'   THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 1)
      ELSE TG_TABLE_NAME
    END
  END;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, v_etype, v_entity, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  -- Auditing must never break the user's write.
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.audit_capture() IS
  'Module 9.0/M1: generic audit trigger. Logs end-user (auth.uid() present) writes '
  'to public.audit_log, with a person''s government/financial identifiers redacted '
  'by audit_redact (migration 336). Backend service-role writes are skipped '
  '(covered by audit_service.log_event). Non-fatal, SECURITY DEFINER, append-only.';

COMMIT;
