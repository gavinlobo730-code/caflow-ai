-- PracticeSync — Migration 286: GST details on an advance receipt
--
-- WHY
--   GSTR-1 Table 11A declares an advance on which tax is payable and no
--   invoice has been issued; 11B declares it being adjusted later. A row needs
--   the place of supply and the RATE of a supply that has not happened yet.
--   `receipts` held an amount, a customer and a date, so Table 11 could not be
--   computed at all — and services/gst_advance_service says so in its own
--   response rather than filing a silent zero.
--
--   These columns are that missing information, and nothing more.
--
-- WHY THE SWITCH DEFAULTS TO FALSE
--   Notification 66/2017-Central Tax (15 November 2017) removed the charge on
--   an advance received for a supply of GOODS — the liability arises at the
--   invoice instead (CGST Act §12(2) proviso). It survives only for SERVICES,
--   where §13(2) puts the time of supply at the earlier of invoice or payment.
--
--   So for most registered persons there is no Table 11 liability at all, and
--   demanding a tax rate on every receipt would be data entry in exchange for
--   nothing. TallyPrime makes the same call: "Enable tax liability on advance
--   receipts" is disabled by default and switched on per company.
--
--   A client who supplies services turns it on. A client who does not never
--   sees the field.
--
-- WHAT DOES NOT DEPEND ON THE SWITCH
--   The advances REPORT does not. Unadjusted receipts are listed for every
--   client whether or not Table 11 is enabled, so a service supplier who has
--   not turned it on still sees the advances rather than a silent nothing.
--   Defaulting off may cost a CA a switch; it must never cost them the sight
--   of the money.
--
-- Additive and idempotent. All three receipt columns are NULLable — an advance
-- recorded before this migration has no rate, and guessing one would invent a
-- liability. The client switch defaults to the behaviour every client has had
-- until now, so no existing figure moves.

ALTER TABLE public.clients
    ADD COLUMN IF NOT EXISTS gst_advance_tax_applicable BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.clients.gst_advance_tax_applicable IS
  'Does GST arise on advances this client receives? TRUE for suppliers of '
  'SERVICES (CGST Act section 13(2)). FALSE — the default — for suppliers of '
  'goods, where Notification 66/2017-Central Tax moved the liability to the '
  'invoice. Only when TRUE does GSTR-1 Table 11A/11B get computed.';

ALTER TABLE public.receipts
    ADD COLUMN IF NOT EXISTS gst_rate_bps  INTEGER
        CHECK (gst_rate_bps IS NULL OR (gst_rate_bps >= 0 AND gst_rate_bps <= 10000)),
    ADD COLUMN IF NOT EXISTS place_of_supply TEXT
        CHECK (place_of_supply IS NULL OR place_of_supply ~ '^[0-9]{2}$'),
    ADD COLUMN IF NOT EXISTS is_interstate BOOLEAN;

COMMENT ON COLUMN public.receipts.gst_rate_bps IS
  'GST rate on the supply this advance relates to, in BASIS POINTS (1800 = '
  '18%), matching bank_transactions.gst_rate_bps. NULL means not stated: the '
  'advance is listed in the report but cannot enter Table 11A, because a '
  'guessed rate is a guessed tax liability on a filed return.';

COMMENT ON COLUMN public.receipts.place_of_supply IS
  '2-digit state code of the place of supply for the advance. Defaults from '
  'the customer state when captured; NULL means not stated.';
