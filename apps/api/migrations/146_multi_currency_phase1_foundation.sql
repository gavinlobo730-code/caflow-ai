-- Migration 146: Multi-Currency — Phase 1 (Foundation). ADDITIVE ONLY.
--
-- Implements the frozen Phase 0 architecture (docs/architecture/06-multi-currency-phase0.md),
-- Phase 1 slice: the currency master, the fx_rates table, and the three-level
-- feature-gating flags. NOTHING here changes accounting behaviour — every flag
-- defaults to the INR-only, feature-OFF state, so the engine is byte-for-byte
-- identical to today until later phases wire foreign transactions in.
--
-- Explicitly NOT in this migration (later phases): journal_lines / journal_entries
-- FX columns, master default_currency columns, FX gain/loss/rounding COA accounts.
-- No existing column is removed or altered; no reporting or posting logic changes.

-- ── G1: Currency master (ISO 4217) — no hardcoded currency lists in code ───────
-- minor_unit is the ISO 4217 exponent (JPY = 0, INR = 2, KWD = 3) so a JPY amount
-- uses 0 decimals, never "paise". Unlimited currencies: any ISO code may be added.
CREATE TABLE IF NOT EXISTS public.currencies (
  code         CHAR(3) PRIMARY KEY,              -- ISO 4217 alphabetic code, e.g. INR
  symbol       TEXT NOT NULL,                    -- display symbol, e.g. ₹
  display_name TEXT NOT NULL,                    -- e.g. Indian Rupee
  minor_unit   SMALLINT NOT NULL DEFAULT 2 CHECK (minor_unit >= 0 AND minor_unit <= 6),
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the ISO 4217 master (idempotent) BEFORE any FK references it (the clients
-- FK below defaults to 'INR', which must therefore already exist). Covers the
-- majors plus every non-2-decimal exception so minor_unit is correct out of the
-- box; more codes can be inserted anytime — the master is the source of truth.
INSERT INTO public.currencies (code, symbol, display_name, minor_unit) VALUES
  ('INR', '₹',  'Indian Rupee',                 2),
  ('USD', '$',  'US Dollar',                    2),
  ('EUR', '€',  'Euro',                         2),
  ('GBP', '£',  'Pound Sterling',               2),
  ('JPY', '¥',  'Japanese Yen',                 0),
  ('CNY', '¥',  'Chinese Yuan Renminbi',        2),
  ('AUD', 'A$', 'Australian Dollar',            2),
  ('CAD', 'C$', 'Canadian Dollar',              2),
  ('CHF', 'CHF','Swiss Franc',                  2),
  ('HKD', 'HK$','Hong Kong Dollar',             2),
  ('SGD', 'S$', 'Singapore Dollar',             2),
  ('AED', 'AED','UAE Dirham',                   2),
  ('SAR', 'SAR','Saudi Riyal',                  2),
  ('QAR', 'QAR','Qatari Riyal',                 2),
  ('ZAR', 'R',  'South African Rand',           2),
  ('NZD', 'NZ$','New Zealand Dollar',           2),
  ('SEK', 'kr', 'Swedish Krona',                2),
  ('NOK', 'kr', 'Norwegian Krone',              2),
  ('DKK', 'kr', 'Danish Krone',                 2),
  ('THB', '฿',  'Thai Baht',                    2),
  ('MYR', 'RM', 'Malaysian Ringgit',            2),
  ('IDR', 'Rp', 'Indonesian Rupiah',            2),
  ('PHP', '₱',  'Philippine Peso',              2),
  ('KRW', '₩',  'South Korean Won',             0),
  ('VND', '₫',  'Vietnamese Dong',              0),
  ('RUB', '₽',  'Russian Ruble',                2),
  ('BRL', 'R$', 'Brazilian Real',               2),
  ('MXN', 'MX$','Mexican Peso',                 2),
  ('TRY', '₺',  'Turkish Lira',                 2),
  ('PLN', 'zł', 'Polish Zloty',                 2),
  ('CZK', 'Kč', 'Czech Koruna',                 2),
  ('HUF', 'Ft', 'Hungarian Forint',             2),
  ('RON', 'lei','Romanian Leu',                 2),
  ('BGN', 'лв', 'Bulgarian Lev',                2),
  ('UAH', '₴',  'Ukrainian Hryvnia',            2),
  ('ILS', '₪',  'Israeli New Shekel',           2),
  ('LKR', 'Rs', 'Sri Lankan Rupee',             2),
  ('BDT', '৳',  'Bangladeshi Taka',             2),
  ('NPR', 'Rs', 'Nepalese Rupee',               2),
  ('PKR', 'Rs', 'Pakistani Rupee',              2),
  ('MMK', 'K',  'Myanmar Kyat',                 2),
  ('KHR', '៛',  'Cambodian Riel',               2),
  ('TWD', 'NT$','New Taiwan Dollar',            2),
  ('MOP', 'MOP$','Macanese Pataca',             2),
  ('MUR', '₨',  'Mauritian Rupee',              2),
  ('EGP', 'E£', 'Egyptian Pound',               2),
  ('MAD', 'MAD','Moroccan Dirham',              2),
  ('KES', 'KSh','Kenyan Shilling',              2),
  ('NGN', '₦',  'Nigerian Naira',               2),
  ('GHS', '₵',  'Ghanaian Cedi',                2),
  ('TZS', 'TSh','Tanzanian Shilling',           2),
  ('COP', 'COL$','Colombian Peso',              2),
  ('ARS', 'AR$','Argentine Peso',               2),
  ('PEN', 'S/', 'Peruvian Sol',                 2),
  -- 3-decimal currencies (minor_unit = 3)
  ('KWD', 'KD', 'Kuwaiti Dinar',                3),
  ('BHD', 'BD', 'Bahraini Dinar',               3),
  ('OMR', 'OMR','Omani Rial',                   3),
  ('JOD', 'JD', 'Jordanian Dinar',              3),
  ('TND', 'DT', 'Tunisian Dinar',               3),
  ('IQD', 'IQD','Iraqi Dinar',                  3),
  ('LYD', 'LD', 'Libyan Dinar',                 3),
  -- 0-decimal currencies (minor_unit = 0)
  ('ISK', 'kr', 'Icelandic Króna',              0),
  ('CLP', 'CLP$','Chilean Peso',                0),
  ('XAF', 'FCFA','Central African CFA Franc',   0),
  ('XOF', 'CFA','West African CFA Franc',       0),
  ('XPF', '₣',  'CFP Franc',                    0)
ON CONFLICT (code) DO NOTHING;

-- ── fx_rates: exact rates, one per (base, quote, date, type, source). ──────────
-- Created now (part of the abstraction the ManualRateProvider reads); no rate is
-- fetched automatically in Phase 1. rate is NUMERIC(18,8) — exact, never float.
CREATE TABLE IF NOT EXISTS public.fx_rates (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  base       CHAR(3) NOT NULL REFERENCES public.currencies(code),
  quote      CHAR(3) NOT NULL REFERENCES public.currencies(code),
  rate_date  DATE NOT NULL,
  rate_type  TEXT NOT NULL DEFAULT 'booking'
               CHECK (rate_type IN ('booking', 'gst_notified', 'customs', 'closing')),
  rate       NUMERIC(18,8) NOT NULL CHECK (rate > 0),
  source     TEXT NOT NULL DEFAULT 'manual',    -- provider: manual / rbi / ecb / …
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID,
  UNIQUE (base, quote, rate_date, rate_type, source)
);
CREATE INDEX IF NOT EXISTS idx_fx_rates_lookup
  ON public.fx_rates (base, quote, rate_type, rate_date DESC);

-- ── Feature-gating flags (safe, behaviour-inert defaults) ─────────────────────
-- L2 Firm entitlement.
ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS multi_currency_entitled BOOLEAN NOT NULL DEFAULT FALSE;

-- L3 Client: functional currency (Capability A = INR-functional books) + enable flag.
-- FK to currencies(code); default 'INR' is already seeded above.
ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS functional_currency CHAR(3) NOT NULL DEFAULT 'INR'
    REFERENCES public.currencies(code),
  ADD COLUMN IF NOT EXISTS multi_currency_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- (L1 Platform kill switch is the env var MULTI_CURRENCY_ENABLED — no DB dependency.)

-- ── RLS: currencies & fx_rates are global reference data — readable by any ─────
-- authenticated user; writes go through the service role (which bypasses RLS),
-- consistent with the Phase 4 posture that every table has RLS enabled.
ALTER TABLE public.currencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fx_rates   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS read_currencies ON public.currencies;
CREATE POLICY read_currencies ON public.currencies FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS read_fx_rates ON public.fx_rates;
CREATE POLICY read_fx_rates ON public.fx_rates FOR SELECT TO authenticated USING (true);
