-- ============================================================================
-- 293 — reconcile the 17 column types that differ from the live database
--
-- WHY
--     scripts/db/schema_drift.py found 17 columns whose TYPE differs between
--     the migrations and production. Unlike the 35 nullability differences
--     migration 292 closed, these do not split into one safe direction and one
--     dangerous one — each needed its own judgement, and they resolve four
--     different ways. Row counts and every stored value were read from the
--     live database first, because "is this safe to convert" is a question
--     about data, not about files.
--
-- GROUP A — production is right, the migration was wrong  (tables are EMPTY)
--     account_group_mappings.account_id and year_end_adjustments'
--     credit/debit_account_id are declared TEXT and are UUID in production.
--     They hold chart-of-accounts ids, so uuid is correct and the declaration
--     was the error. This is a no-op in production and fixes the template.
--
--     This was the DANGEROUS direction: production stricter than the
--     migrations. Code written from the migrations could put a non-uuid string
--     in one of these, pass every check here, and be rejected there.
--
-- GROUP B — the migration is right, production was wrong  (tables are EMPTY)
--     tally_migration_jobs.source_file_size_bytes is BIGINT in the migration
--     and INTEGER in production, which overflows at 2,147,483,647 bytes — a
--     Tally export over ~2.1 GB would fail on the live database and pass here.
--     Widened to bigint.
--
--     The three financial_year columns are varchar(7) in the migrations and
--     unbounded text in production. "2025-26" is exactly 7 characters, so the
--     limit is right; production simply never got it.
--
-- GROUP C — both should be uuid, production stores text  (tables HAVE DATA)
--     audit_log.actor_id, four columns on client_timeline_events, and
--     pending_invites.invited_by are uuid in the migrations and text in
--     production. Verified against the live data before converting: 45,893
--     audit_log rows and 8,027 client_timeline_events rows, and every one of
--     the 68,592 non-null values across the six columns is a well-formed UUID
--     — zero exceptions. The code paths that write them pass user ids, never a
--     sentinel string. (services/escalation_service.py does pass
--     actor_id="system", but to task_extras_repo, a different table, which is
--     not touched here.)
--
-- GROUP D — the ENUM is wrong, and production being text is what keeps the
--           app working. The migrations are relaxed to match.
--     client_timeline_events.actor_type/category/severity/visibility are
--     Postgres enums in the migrations and text in production.
--
--     Converting production to those enums would BREAK LIVE CODE. The enums
--     are event_category = {accounting, compliance, payroll, tax, document,
--     work, ai, portal, team} and event_severity = {info, success, warning,
--     critical}, but the code writes category "gst", "tds", "mca" and
--     "lifecycle" (routers/lifecycle.py passes it positionally), and severity
--     "high", "low" and "medium". Production already holds a row with
--     category='lifecycle'.
--
--     So the closed vocabulary is not what this codebase does. Widening the
--     enums instead would make every new category a migration, and would fail
--     the first time someone forgot. Whether the set SHOULD be closed is a
--     design decision for the owner; until it is taken, the declaration should
--     describe what the database actually is.
--
-- THE RLS POLICIES HAVE TO COME OFF FIRST, AND THIS IS WHY IT IS ONE DO BLOCK
--     Postgres refuses ALTER COLUMN ... TYPE on a column named in a policy
--     expression: "cannot alter type of a column used in a policy definition".
--     Two RESTRICTIVE policies on client_timeline_events name client_id —
--     _assignment_scope and _internal_partner_only. Reproduced against a
--     production-shaped database, this file without the drop/recreate fails on
--     the fourth conversion with exit 3. Because the loop is one statement, the
--     failure aborts ALL of it, the runner never records 293, and every later
--     push to main retries and fails again — which is exactly how migration 291
--     stalled.
--
--     Nothing else is in the way: of the 26 policies on the nine tables touched
--     here, only those two reference a converted column, and there are no
--     dependent views, rules or generated columns on any of them.
--
--     The recreated policies are NOT invented for this file. They are the exact
--     text migrations 084 and 074 already declare, cast with client_id::text so
--     the same policy fits a uuid or a text column — 074 says so in a comment,
--     naming client_timeline_events as the reason. Production's copies lack the
--     cast because they were created before it was added, and 074/084 are
--     already recorded so they never re-ran. AS RESTRICTIVE is carried across
--     deliberately: recreating a restrictive policy as the default permissive
--     one would turn a security check into an access grant.
--
--     All of it is one DO block because a DO block is one transaction. Three
--     statements under psql's autocommit would leave client_timeline_events —
--     8,027 rows, many firms — with its two restrictive policies dropped if the
--     middle one failed. Here a failure rolls the drops back with everything
--     else.
--
-- EVERY CONVERSION IS GUARDED on the column's current type, so each is a no-op
-- where it has already been applied and re-running the file changes nothing.
-- The casts are the plain ones, which ERROR on a value that does not fit: an
-- earlier draft used left(financial_year, 7) and would have silently turned a
-- mis-entered '2025-2026' into '2025-20'. A migration should stop, not corrupt
-- a financial year label.
-- ============================================================================

DO $do$
DECLARE
  target        RECORD;
  current_type  TEXT;
  dropped_scope   BOOLEAN := FALSE;
  dropped_partner BOOLEAN := FALSE;
BEGIN

  -- ── 1. take off the policies that name a column about to change type ──────
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'client_timeline_events'
               AND column_name = 'client_id' AND data_type = 'text')
  THEN
    IF EXISTS (SELECT 1 FROM pg_policies
               WHERE schemaname = 'public' AND tablename = 'client_timeline_events'
                 AND policyname = 'client_timeline_events_assignment_scope') THEN
      DROP POLICY client_timeline_events_assignment_scope ON public.client_timeline_events;
      dropped_scope := TRUE;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_policies
               WHERE schemaname = 'public' AND tablename = 'client_timeline_events'
                 AND policyname = 'client_timeline_events_internal_partner_only') THEN
      DROP POLICY client_timeline_events_internal_partner_only ON public.client_timeline_events;
      dropped_partner := TRUE;
    END IF;
  END IF;

  -- ── 2. the conversions ────────────────────────────────────────────────────
  FOR target IN
    SELECT * FROM (VALUES
      -- table,                        column,                  from,           to,           using-expression
      ('account_group_mappings',       'account_id',            'text',         'uuid',       '%2$I::uuid'),
      ('year_end_adjustments',         'credit_account_id',     'text',         'uuid',       '%2$I::uuid'),
      ('year_end_adjustments',         'debit_account_id',      'text',         'uuid',       '%2$I::uuid'),

      ('tally_migration_jobs',         'source_file_size_bytes','integer',      'bigint',     '%2$I::bigint'),
      ('financial_statement_versions', 'financial_year',        'text',         'varchar(7)', '%2$I'),
      ('year_end_engagements',         'financial_year',        'text',         'varchar(7)', '%2$I'),
      ('year_end_exports',             'financial_year',        'text',         'varchar(7)', '%2$I'),

      ('audit_log',                    'actor_id',              'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),
      ('client_timeline_events',       'actor_id',              'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),
      ('client_timeline_events',       'client_id',             'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),
      ('client_timeline_events',       'entity_id',             'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),
      ('client_timeline_events',       'deleted_by',            'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),
      ('pending_invites',              'invited_by',            'text',         'uuid',       'NULLIF(%2$I, '''')::uuid'),

      ('client_timeline_events',       'actor_type',            'USER-DEFINED', 'text',       '%2$I::text'),
      ('client_timeline_events',       'category',              'USER-DEFINED', 'text',       '%2$I::text'),
      ('client_timeline_events',       'severity',              'USER-DEFINED', 'text',       '%2$I::text'),
      ('client_timeline_events',       'visibility',            'USER-DEFINED', 'text',       '%2$I::text')
    ) AS t(tbl, col, from_type, to_type, using_expr)
  LOOP
    SELECT data_type INTO current_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = target.tbl
      AND column_name = target.col;

    -- Absent column: an earlier migration never applied here (ten sit on
    -- EXPECTED_MIGRATION_FAILURES). Skip rather than fail the whole file.
    IF current_type IS NULL THEN
      CONTINUE;
    END IF;

    -- Already the target type, or not the type this row expects to convert
    -- FROM: leave it alone. That makes re-running a no-op and stops this
    -- migration fighting a future one that changed the same column.
    IF current_type <> target.from_type THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'ALTER TABLE public.%1$I ALTER COLUMN %2$I TYPE %3$s USING ' || target.using_expr,
      target.tbl, target.col, target.to_type);
    RAISE NOTICE 'converted %.% : % -> %',
      target.tbl, target.col, target.from_type, target.to_type;
  END LOOP;

  -- ── 3. put back exactly what was taken off, in migration 084/074's form ───
  IF dropped_scope THEN
    CREATE POLICY client_timeline_events_assignment_scope
      ON public.client_timeline_events AS RESTRICTIVE FOR ALL
      USING (public.can_access_client(client_id::text))
      WITH CHECK (public.can_access_client(client_id::text));
    RAISE NOTICE 'restored policy client_timeline_events_assignment_scope';
  END IF;

  IF dropped_partner THEN
    CREATE POLICY client_timeline_events_internal_partner_only
      ON public.client_timeline_events AS RESTRICTIVE FOR ALL
      USING (get_my_role() = 'Partner'
             OR client_id::text IS DISTINCT FROM my_internal_client_id()::text)
      WITH CHECK (get_my_role() = 'Partner'
             OR client_id::text IS DISTINCT FROM my_internal_client_id()::text);
    RAISE NOTICE 'restored policy client_timeline_events_internal_partner_only';
  END IF;

END
$do$;

-- The four enum types are deliberately NOT dropped. Nothing this file changed
-- still uses them, but a type is cheap to keep and dropping one that another
-- object references would fail the migration for no gain.
