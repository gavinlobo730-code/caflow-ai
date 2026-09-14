-- 386 — a company credit card is a bank account, and it is a liability
-- (BANK-21).
--
-- WHAT WAS WRONG
--     `bank_accounts.account_type` has admitted Current, Savings, Cash Credit
--     and Overdraft since migration 054, and migration 093 recreated the table
--     with the same four. So a company credit card could not be created at
--     all: its statement could not be imported, its spend could not be coded
--     through the bank workflow, and the monthly payment out of the current
--     account posted to whatever ledger somebody picked — with the underlying
--     expenses never recorded from the card statement at all. A card is
--     ordinary for any SME with travel or online spend.
--
-- WHY THIS IS ONE CHECK AND NOT A NEW TABLE
--     A card IS a bank account for everything this product does with one: it
--     has a statement with dates, narrations and amounts, its lines are coded
--     to ledgers, it reconciles, and money moves between it and the current
--     account. `posting_map.build_lines` is direction-driven — money OUT
--     debits the counter and credits the account's own ledger — so with a
--     LIABILITY ledger the double entry is already right, both ways round:
--
--         a purchase on the card   Dr Expense  / Cr Card
--         a payment to the card    Dr Card     / Cr Bank
--
--     Nothing in the posting map, the settlement or the reversal moves. What
--     differs is the SIGN OF THE BALANCE, and that is handled in
--     `domain/banking/account_kind.py` at the two boundaries where a figure is
--     read off a statement or shown back — never in the store.
--
-- THE CONSTRAINT IS DROPPED AND RECREATED BY NAME rather than widened in
-- place, because Postgres has no ALTER ... MODIFY CHECK. The name is the one
-- Postgres itself generated for 093's inline CHECK; both spellings are dropped
-- so this applies to a database built either way.

ALTER TABLE public.bank_accounts
  DROP CONSTRAINT IF EXISTS bank_accounts_account_type_check;

ALTER TABLE public.bank_accounts
  ADD CONSTRAINT bank_accounts_account_type_check
  CHECK (account_type IN ('Current', 'Savings', 'Cash Credit', 'Overdraft', 'Credit Card'));

COMMENT ON COLUMN public.bank_accounts.account_type IS
  'Current | Savings | Cash Credit | Overdraft | Credit Card. The last three '
  'are money OWED to the bank and carry a Liability ledger '
  '(domain/banking/account_kind.ledger_shape_for). A CREDIT CARD is the one '
  'whose STATEMENT states its balance the other way up — as an amount owed, '
  'positive — so opening_balance_paise and bank_transactions.balance_paise are '
  'stored in LEDGER sign (negative for a card) and translated at the boundary '
  'by account_kind.to_ledger_sign / to_statement_sign.';
