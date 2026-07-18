-- Manual verification for migration 228's passbook triggers. NOT auto-run.
-- It is fully self-undoing: it posts test entries, checks the buckets updated
-- correctly, then RAISEs to roll the whole transaction back — nothing persists.
-- Run it (with DML approval) against a client whose buckets you know, e.g. the
-- empty client below, and read the values in the raised message.
--
-- Expected: after_direct+draftlines dr=1000 (trigger A adds the DIRECT-posted
-- entry's line but SKIPS the still-draft entry's lines), then after_post dr=1500
-- cr=0 (trigger B folds the draft entry's lines in when it flips to posted).
--
-- Replace the firm/client/account UUIDs with real, active ones for your DB.
DO $$
DECLARE d1 bigint; d2 bigint; c2 bigint;
  v_firm   uuid := 'ec7d5a0d-70d1-441d-a407-68b714a692d7';   -- firm
  v_client uuid := '43e8b5c7-00ad-4be1-b732-0b4c082f4c40';   -- an empty client
  v_acc1   uuid := '50436f62-d89d-43e1-97f0-fd799566d1ee';   -- any two active accounts
  v_acc2   uuid := '25664137-1dc4-4123-ba5e-0eb5f7d9ebfd';
BEGIN
  -- Trigger A: entry posted at insert, then its lines added.
  INSERT INTO journal_entries(id, firm_id, client_id, entry_date, narration, entry_type, is_posted)
    VALUES ('11111111-1111-1111-1111-111111111111', v_firm, v_client, '2026-05-15', 'apb test A', 'Payment', true);
  INSERT INTO journal_lines(journal_entry_id, account_id, debit_paise, credit_paise) VALUES
    ('11111111-1111-1111-1111-111111111111', v_acc1, 1000, 0),
    ('11111111-1111-1111-1111-111111111111', v_acc2, 0, 1000);

  -- Trigger A must SKIP these (parent still a draft); trigger B adds them on post.
  INSERT INTO journal_entries(id, firm_id, client_id, entry_date, narration, entry_type, is_posted)
    VALUES ('22222222-2222-2222-2222-222222222222', v_firm, v_client, '2026-05-20', 'apb test B', 'Payment', false);
  INSERT INTO journal_lines(journal_entry_id, account_id, debit_paise, credit_paise) VALUES
    ('22222222-2222-2222-2222-222222222222', v_acc1, 500, 0),
    ('22222222-2222-2222-2222-222222222222', v_acc2, 0, 500);

  SELECT debit_paise INTO d1 FROM account_period_balances
    WHERE client_id = v_client AND account_id = v_acc1 AND period_month = '2026-05-01';

  UPDATE journal_entries SET is_posted = true WHERE id = '22222222-2222-2222-2222-222222222222';

  SELECT debit_paise, credit_paise INTO d2, c2 FROM account_period_balances
    WHERE client_id = v_client AND account_id = v_acc1 AND period_month = '2026-05-01';

  RAISE EXCEPTION 'APB_TRIGGER_TEST >> after_direct+draftlines dr=% (expect 1000) | after_post dr=% cr=% (expect 1500, 0)', d1, d2, c2;
END $$;
