-- Migration 228: keep account_period_balances current as journal entries post.
--
-- A posted journal entry is IMMUTABLE (migrations 055 / 058 block any UPDATE or
-- DELETE of a posted entry or its lines; the one carve-out, is_reversed
-- FALSE->TRUE in migration 213, changes no amount/date/account). So a bucket's
-- value can only ever change when an entry BECOMES posted — never afterwards.
-- That single event is captured here by two AFTER triggers, so the passbook is
-- maintained no matter which code path posts (direct insert, the
-- settle_receipt_atomic RPC, a bulk import, or a reversal's new entry). An
-- application-level hook would miss the in-database RPC path; a trigger cannot.
--
-- These are ADDITIVE (they increment the bucket). The nightly auditor
-- (services/balance_cache_service.audit_client) re-derives every bucket from
-- scratch and is the arbiter — any drift is logged and self-healed by a
-- recompute, so an increment bug can never silently corrupt a report.

-- Shared upsert: fold one posted line's amounts into its (client, account, month) bucket.
CREATE OR REPLACE FUNCTION apb_apply_posted_line(
  p_firm uuid, p_client uuid, p_account uuid, p_month date, p_debit bigint, p_credit bigint
) RETURNS void LANGUAGE sql SET search_path = public, pg_catalog AS $$
  INSERT INTO public.account_period_balances
    (firm_id, client_id, account_id, period_month, debit_paise, credit_paise, updated_at)
  VALUES (p_firm, p_client, p_account, p_month, p_debit, p_credit, now())
  ON CONFLICT (firm_id, client_id, account_id, period_month)
  DO UPDATE SET debit_paise  = account_period_balances.debit_paise  + EXCLUDED.debit_paise,
                credit_paise = account_period_balances.credit_paise + EXCLUDED.credit_paise,
                updated_at   = now();
$$;

-- (A) A line inserted into an ALREADY-posted, non-deleted entry — the direct
--     "insert entry (posted) then insert its lines" path, and the atomic RPC.
CREATE OR REPLACE FUNCTION apb_on_line_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_catalog AS $$
DECLARE e RECORD;
BEGIN
  SELECT firm_id, client_id, entry_date, is_posted, deleted_at
    INTO e FROM public.journal_entries WHERE id = NEW.journal_entry_id;
  IF FOUND AND e.is_posted IS TRUE AND e.deleted_at IS NULL THEN
    PERFORM apb_apply_posted_line(
      e.firm_id, e.client_id, NEW.account_id,
      date_trunc('month', e.entry_date)::date,
      COALESCE(NEW.debit_paise, 0), COALESCE(NEW.credit_paise, 0));
  END IF;
  RETURN NULL;
END; $$;

DROP TRIGGER IF EXISTS trg_apb_on_line_insert ON public.journal_lines;
CREATE TRIGGER trg_apb_on_line_insert
  AFTER INSERT ON public.journal_lines
  FOR EACH ROW EXECUTE FUNCTION apb_on_line_insert();

-- (B) An entry transitioning draft -> posted — the draft workflow, whose lines
--     were inserted while the parent was still a draft (so trigger A skipped
--     them). Fold in all of them now, pre-aggregated per account so two lines to
--     the same account don't collide on the ON CONFLICT within one statement.
CREATE OR REPLACE FUNCTION apb_on_entry_post() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_catalog AS $$
BEGIN
  IF NEW.is_posted IS TRUE AND COALESCE(OLD.is_posted, false) IS FALSE
     AND NEW.deleted_at IS NULL THEN
    INSERT INTO public.account_period_balances
      (firm_id, client_id, account_id, period_month, debit_paise, credit_paise, updated_at)
    SELECT NEW.firm_id, NEW.client_id, jl.account_id,
           date_trunc('month', NEW.entry_date)::date,
           sum(COALESCE(jl.debit_paise, 0)), sum(COALESCE(jl.credit_paise, 0)), now()
    FROM public.journal_lines jl
    WHERE jl.journal_entry_id = NEW.id
    GROUP BY jl.account_id
    ON CONFLICT (firm_id, client_id, account_id, period_month)
    DO UPDATE SET debit_paise  = account_period_balances.debit_paise  + EXCLUDED.debit_paise,
                  credit_paise = account_period_balances.credit_paise + EXCLUDED.credit_paise,
                  updated_at   = now();
  END IF;
  RETURN NULL;
END; $$;

DROP TRIGGER IF EXISTS trg_apb_on_entry_post ON public.journal_entries;
CREATE TRIGGER trg_apb_on_entry_post
  AFTER UPDATE ON public.journal_entries
  FOR EACH ROW EXECUTE FUNCTION apb_on_entry_post();
