-- 371 — the table that looks like the TDS rate master, and is not
--
-- WHAT IS WRONG (TDS-27)
--
--   public.tds_section_limits (migration 037:114-141) is seeded with
--   pre-Finance-Act-2025 thresholds and pre-2024 rates: §194J at ₹30,000 where
--   the limit is now ₹50,000, §194I at ₹2,40,000 a year where it is ₹50,000 a
--   month, §194A at ₹4,000, and §194D/§194G/§194H at 5% where the rate is 2%.
--   Worse, its primary key is `section` and migration 037 inserts TWO '194C'
--   rows — the ₹30,000 single-payment limit and the ₹1,00,000 aggregate — under
--   `ON CONFLICT (section) DO NOTHING`, so the aggregate row has never landed
--   in any database this migration has ever run against.
--
--   Nothing reads it. That is exactly what makes it dangerous rather than
--   merely wrong: it is the one table in the schema whose name and columns
--   read as the authoritative TDS rate master, and the next person to write a
--   report or a dropdown against it would ship FY 2019-era thresholds with no
--   test failing anywhere.
--
-- WHY A COMMENT AND NOT A DROP
--
--   A DROP is the right end state and it is not free: `tests/fixtures/`
--   carries point-in-time production snapshots that
--   test_schema_matches_production_pg.py and test_guards_match_production_pg.py
--   compare a migration-built database against, and removing a live table
--   moves both sides of that comparison at once. docs/schema-drift.md says how
--   to refresh them; doing it in the same change as a statutory fix would mean
--   a fixture refresh nobody could review separately from the deletion.
--
--   So this migration does the part that removes the trap today — the table
--   says, in the database, that it is not the authority and what is — and
--   tests/test_the_dead_tds_rate_master_has_no_readers.py holds the "nothing
--   reads it" half so a first reader has to notice. The figures are
--   deliberately NOT corrected in place: doing that would create the second
--   source of truth that CLAUDE.md's one-posting-kernel rule exists to prevent,
--   and `domain/tds/section_rates.py` is already the one that is maintained.
--
-- No table, column, constraint or policy changes. Comments only.

COMMENT ON TABLE public.tds_section_limits IS
  'NOT THE AUTHORITY, AND NOT MAINTAINED. Reference data seeded once by '
  'migration 037 with pre-Finance-Act-2025 thresholds and pre-2024 rates; the '
  'second 194C row (the ₹1,00,000 aggregate) never landed because `section` is '
  'the primary key and the insert used ON CONFLICT DO NOTHING. Nothing in '
  'apps/api or apps/web reads it and nothing should: TDS rates, thresholds and '
  'the per-section aggregate limb live in apps/api/domain/tds/section_rates.py, '
  'FY-versioned with a LATEST_VERIFIED_TDS_FY a human moves against the Finance '
  'Act. Do not correct these figures in place — that makes a second source of '
  'truth. TDS-27.';

COMMENT ON COLUMN public.tds_section_limits.threshold_paise IS
  'Stale. See the table comment; domain/tds/section_rates.py is the authority.';
COMMENT ON COLUMN public.tds_section_limits.rate_individual IS
  'Stale. See the table comment; domain/tds/section_rates.py is the authority.';
COMMENT ON COLUMN public.tds_section_limits.rate_company IS
  'Stale. See the table comment; domain/tds/section_rates.py is the authority.';

-- While here: migration 037 labels tds_challans.minor_head
-- "200=TDS on company, 400=regular", and the company/non-company split is the
-- challan's MAJOR head (0020 vs 0021), not its minor head. The minor head says
-- who initiated the payment. TDS-30 made this column settable from the API for
-- the first time, so the wrong gloss would now reach a form label.
COMMENT ON COLUMN public.tds_challans.minor_head IS
  'Challan 281 minor head. 200 = TDS/TCS payable by the taxpayer, paid over of '
  'the deductor''s own motion. 400 = TDS/TCS regular assessment, a deposit '
  'against a demand raised by the department. The company / non-company '
  'distinction is the MAJOR head (0020 / 0021) and is not this column — '
  'migration 037''s inline comment said otherwise. Migration 371.';

COMMENT ON COLUMN public.tds_challans.interest_paise IS
  'IT Act §201(1A) interest included in this challan: 1% per month or part '
  'from the date tax was deductible to the date deducted, 1.5% from the date '
  'deducted to the date paid over. apps/api/domain/tds/interest.py computes '
  'it; this column records what was actually paid. Migration 371.';
COMMENT ON COLUMN public.tds_challans.penalty_paise IS
  'The §234E late-filing fee (₹200 a day, capped at the tax) and any §271H '
  'penalty included in this challan. apps/api/domain/tds/interest.py computes '
  'the §234E half. Migration 371.';
COMMENT ON COLUMN public.tds_challans.tds_paise IS
  'The TAX part of the challan only — total_paise less surcharge, interest and '
  'penalty. Until TDS-30 the API booked the whole amount here, so a challan '
  'that paid interest read as over-depositing the section. Migration 371.';
