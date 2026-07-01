-- Migration 148: Multi-Currency — Phase 3 (Foreign-Currency Documents). ADDITIVE ONLY.
--
-- Adds transaction-currency metadata + foreign amounts to the four operational
-- documents (sales invoices, purchase bills, receipts, purchase payments). The
-- existing *_paise columns remain the authoritative BASE (INR) amounts that post
-- to the GL and feed every report — unchanged. Every new column defaults to the
-- INR / rate=1 state, so INR documents are byte-for-byte identical and the feature
-- stays dormant until all gates open.
--
-- NOT here (later phases): realized/unrealized FX, revaluation, translation,
-- presentation currency, foreign TB/BS/P&L. No existing column removed/altered.

-- Shared shape: txn_currency + frozen exchange_rate + rate provenance (G6), plus
-- the document's foreign amount(s) in the txn currency's MINOR units (not paise).

-- ── Sales invoices ────────────────────────────────────────────────────────────
ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS txn_currency     CHAR(3)      NOT NULL DEFAULT 'INR' REFERENCES public.currencies(code),
  ADD COLUMN IF NOT EXISTS exchange_rate    NUMERIC(18,8) NOT NULL DEFAULT 1 CHECK (exchange_rate > 0),
  ADD COLUMN IF NOT EXISTS txn_taxable      BIGINT,       -- foreign taxable (minor units)
  ADD COLUMN IF NOT EXISTS txn_total_gst    BIGINT,       -- foreign GST total
  ADD COLUMN IF NOT EXISTS txn_total        BIGINT,       -- foreign grand total
  ADD COLUMN IF NOT EXISTS rate_source      TEXT,
  ADD COLUMN IF NOT EXISTS rate_type        TEXT NOT NULL DEFAULT 'booking'
                                              CHECK (rate_type IN ('booking','gst_notified','customs','closing')),
  ADD COLUMN IF NOT EXISTS rate_date        DATE,
  ADD COLUMN IF NOT EXISTS rate_selected_by UUID,
  ADD COLUMN IF NOT EXISTS rate_overridden  BOOLEAN NOT NULL DEFAULT FALSE;

-- ── Purchase bills ────────────────────────────────────────────────────────────
ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS txn_currency     CHAR(3)      NOT NULL DEFAULT 'INR' REFERENCES public.currencies(code),
  ADD COLUMN IF NOT EXISTS exchange_rate    NUMERIC(18,8) NOT NULL DEFAULT 1 CHECK (exchange_rate > 0),
  ADD COLUMN IF NOT EXISTS txn_taxable      BIGINT,
  ADD COLUMN IF NOT EXISTS txn_total_gst    BIGINT,
  ADD COLUMN IF NOT EXISTS txn_total        BIGINT,
  ADD COLUMN IF NOT EXISTS txn_net_payable  BIGINT,       -- foreign net payable (total − TDS)
  ADD COLUMN IF NOT EXISTS rate_source      TEXT,
  ADD COLUMN IF NOT EXISTS rate_type        TEXT NOT NULL DEFAULT 'booking'
                                              CHECK (rate_type IN ('booking','gst_notified','customs','closing')),
  ADD COLUMN IF NOT EXISTS rate_date        DATE,
  ADD COLUMN IF NOT EXISTS rate_selected_by UUID,
  ADD COLUMN IF NOT EXISTS rate_overridden  BOOLEAN NOT NULL DEFAULT FALSE;

-- ── Receipts (customer) ───────────────────────────────────────────────────────
ALTER TABLE public.receipts
  ADD COLUMN IF NOT EXISTS txn_currency     CHAR(3)      NOT NULL DEFAULT 'INR' REFERENCES public.currencies(code),
  ADD COLUMN IF NOT EXISTS exchange_rate    NUMERIC(18,8) NOT NULL DEFAULT 1 CHECK (exchange_rate > 0),
  ADD COLUMN IF NOT EXISTS txn_amount       BIGINT,       -- foreign cash amount (minor units)
  ADD COLUMN IF NOT EXISTS rate_source      TEXT,
  ADD COLUMN IF NOT EXISTS rate_type        TEXT NOT NULL DEFAULT 'booking'
                                              CHECK (rate_type IN ('booking','gst_notified','customs','closing')),
  ADD COLUMN IF NOT EXISTS rate_date        DATE,
  ADD COLUMN IF NOT EXISTS rate_selected_by UUID,
  ADD COLUMN IF NOT EXISTS rate_overridden  BOOLEAN NOT NULL DEFAULT FALSE;

-- ── Purchase payments (vendor) ────────────────────────────────────────────────
ALTER TABLE public.purchase_payments
  ADD COLUMN IF NOT EXISTS txn_currency     CHAR(3)      NOT NULL DEFAULT 'INR' REFERENCES public.currencies(code),
  ADD COLUMN IF NOT EXISTS exchange_rate    NUMERIC(18,8) NOT NULL DEFAULT 1 CHECK (exchange_rate > 0),
  ADD COLUMN IF NOT EXISTS txn_amount       BIGINT,
  ADD COLUMN IF NOT EXISTS rate_source      TEXT,
  ADD COLUMN IF NOT EXISTS rate_type        TEXT NOT NULL DEFAULT 'booking'
                                              CHECK (rate_type IN ('booking','gst_notified','customs','closing')),
  ADD COLUMN IF NOT EXISTS rate_date        DATE,
  ADD COLUMN IF NOT EXISTS rate_selected_by UUID,
  ADD COLUMN IF NOT EXISTS rate_overridden  BOOLEAN NOT NULL DEFAULT FALSE;

-- Immutability: a posted document's currency metadata is frozen by the same
-- mechanism as its base amounts (documents are not edited after issue/receive;
-- corrections go through cancel/reverse + re-post). The GL provenance is frozen by
-- the journal immutability triggers (migrations 055/058). No trigger is added here.
