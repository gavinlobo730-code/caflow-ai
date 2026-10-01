-- The monthly database review: what to read, in what order (ops-32).
--
-- READ-ONLY. Every statement is a SELECT over catalogs and statistics views; nothing here writes, and
-- nothing reads a business table's rows (only its size and its statistics). It is safe to run against
-- production and is meant to be.
--
-- HOW TO RUN IT
--   * Supabase dashboard -> SQL Editor: paste ONE numbered block at a time. The editor shows the result
--     of the last statement only, so pasting the whole file shows you block 12 and nothing else.
--   * Or, with a connection string in hand (Project Settings -> Database):
--       psql "$DATABASE_URL" -f apps/api/scripts/db/monthly_review.sql
--     psql prints every result in turn.
--   Then write the date, what you saw and what you did about it in docs/operations/database-review-log.md.
--   docs/operations/database-monitoring.md says what each number means and where it becomes a problem.
--
-- WHAT IS NOT HERE: Supabase's own Performance and Security Advisors (Dashboard -> Advisors). They run
-- on Supabase's side and are not SQL; the runbook puts them in the same monthly review.
--
-- BLOCK 4 READS `extensions.pg_stat_statements`, where Supabase installs the extension. If block 3 shows
-- it in another schema, change the schema name in block 4; if block 3 shows nothing, enable it first
-- (Dashboard -> Database -> Extensions) and come back after a few days of traffic.
--
-- tests/test_the_database_review_queries_run_pg.py runs every block against a real Postgres (with the
-- extension in an `extensions` schema, as on Supabase) and fails if one stops being valid SQL.

-- [1] How big is the database, and what is it made of? ---------------------------------------------
-- The ledger is the growth driver (render.yaml records the largest measured client at 12,836 entries and
-- 32,936 lines). "total" is table + indexes + TOAST; a table whose indexes outweigh it is worth a look.
select n.nspname                                   as schema,
       c.relname                                   as relation,
       c.reltuples::bigint                         as row_estimate,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total,
       pg_size_pretty(pg_relation_size(c.oid))     as table_only,
       pg_size_pretty(pg_indexes_size(c.oid))      as indexes,
       pg_total_relation_size(c.oid)               as total_bytes
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where c.relkind = 'r'
   and n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast')
 order by pg_total_relation_size(c.oid) desc
 limit 25;

-- [2] The whole database, against the plan's disk allowance. ---------------------------------------
select current_database()                                  as database,
       pg_size_pretty(pg_database_size(current_database())) as size,
       pg_database_size(current_database())                 as size_bytes;

-- [3] Is pg_stat_statements installed, and where? --------------------------------------------------
select e.extname, e.extversion, n.nspname as schema
  from pg_extension e
  join pg_namespace n on n.oid = e.extnamespace
 where e.extname = 'pg_stat_statements';

-- [4] The slowest statements: by total time spent (what the database is busy with) ------------------
-- then read the same list by mean_ms (what a single user waits for). The query text is the
-- normalised statement, with literals replaced by $1, $2 — it does not contain client data.
select calls,
       round(total_exec_time::numeric, 0)   as total_ms,
       round(mean_exec_time::numeric, 1)    as mean_ms,
       round(max_exec_time::numeric, 0)     as max_ms,
       rows,
       left(regexp_replace(query, '\s+', ' ', 'g'), 160) as statement
  from extensions.pg_stat_statements
 where dbid = (select oid from pg_database where datname = current_database())
 order by total_exec_time desc
 limit 20;

-- [5] Connections now, against the ceiling. --------------------------------------------------------
-- Saturation is what turns a slow moment into an outage: new connections are refused, and the API
-- (one gunicorn worker on Render) shows it as errors, not as slowness. PostgREST and the auth service
-- hold connections of their own, so the "api" share is not the whole of it.
select current_setting('max_connections')::int                                   as max_connections,
       count(*)                                                                  as in_use,
       count(*) filter (where state = 'active')                                  as active,
       count(*) filter (where state = 'idle')                                    as idle,
       count(*) filter (where state = 'idle in transaction')                     as idle_in_transaction
  from pg_stat_activity
 where datname = current_database();

-- [6] Who holds them. ------------------------------------------------------------------------------
select coalesce(nullif(application_name, ''), '(none)') as application,
       usename                                          as role,
       state,
       count(*)                                         as connections
  from pg_stat_activity
 where datname = current_database()
 group by 1, 2, 3
 order by connections desc
 limit 20;

-- [7] Transactions that have been open a while — the ones that block vacuum and migrations. -------------
select pid,
       usename                                   as role,
       state,
       now() - xact_start                        as open_for,
       left(regexp_replace(query, '\s+', ' ', 'g'), 120) as last_statement
  from pg_stat_activity
 where datname = current_database()
   and xact_start is not null
   and now() - xact_start > interval '1 minute'
   and pid <> pg_backend_pid()
 order by xact_start
 limit 20;

-- [8] Indexes nothing has used since statistics were last reset — candidates, NOT verdicts. -----------
-- A unique or primary-key index enforces something whether or not it is read, so they are excluded; an
-- index a monthly or year-end report uses may show zero scans in a quiet month. Read idx_scan against
-- how long the statistics have been accumulating (block 12) before dropping anything, and drop through
-- a migration, never from here.
select s.schemaname                               as schema,
       s.relname                                  as table_name,
       s.indexrelname                             as index_name,
       s.idx_scan                                 as scans,
       pg_size_pretty(pg_relation_size(s.indexrelid)) as size,
       pg_relation_size(s.indexrelid)             as size_bytes
  from pg_stat_user_indexes s
  join pg_index i on i.indexrelid = s.indexrelid
 where s.idx_scan = 0
   and not i.indisunique
   and not i.indisprimary
   and s.schemaname not in ('pg_catalog', 'information_schema')
 order by pg_relation_size(s.indexrelid) desc
 limit 25;

-- [9] Indexes that are broken: a failed CREATE INDEX CONCURRENTLY leaves one behind, and it costs writes --
-- while helping no read.
select n.nspname as schema, c.relname as index_name, t.relname as table_name
  from pg_index i
  join pg_class c on c.oid = i.indexrelid
  join pg_class t on t.oid = i.indrelid
  join pg_namespace n on n.oid = c.relnamespace
 where not i.indisvalid
   and n.nspname not in ('pg_catalog', 'information_schema');

-- [10] Tables carrying a lot of dead rows: autovacuum is behind, or something is holding it off. ----------
select schemaname                                  as schema,
       relname                                     as table_name,
       n_live_tup                                  as live_rows,
       n_dead_tup                                  as dead_rows,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) as dead_pct,
       last_autovacuum,
       last_autoanalyze
  from pg_stat_user_tables
 where n_dead_tup > 1000
 order by n_dead_tup desc
 limit 20;

-- [11] Is the working set in memory? ----------------------------------------------------------------
-- Below about 99% on a database this size means reads are going to disk. One number; read it over months.
select round(100.0 * sum(heap_blks_hit) / nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0), 2) as table_cache_hit_pct,
       (select round(100.0 * sum(idx_blks_hit) / nullif(sum(idx_blks_hit) + sum(idx_blks_read), 0), 2)
          from pg_statio_user_indexes)                                                           as index_cache_hit_pct
  from pg_statio_user_tables;

-- [12] How long have these statistics been accumulating? -------------------------------------------------
-- Every "since" above is since this moment. A restart or a stats reset empties them, and a number read
-- the day after one means nothing.
select stats_reset, now() - stats_reset as accumulating_for
  from pg_stat_database
 where datname = current_database();

-- [13] Large tables that are read by scanning them whole. -----------------------------------------------
-- seq_scan on a table of hundreds of thousands of rows is either a report that should read a
-- pre-aggregated table (CLAUDE.md, "Reporting performance") or a missing index.
select schemaname                                  as schema,
       relname                                     as table_name,
       n_live_tup                                  as live_rows,
       seq_scan,
       seq_tup_read,
       coalesce(idx_scan, 0)                       as idx_scan
  from pg_stat_user_tables
 where n_live_tup > 50000
   and seq_scan > coalesce(idx_scan, 0)
 order by seq_tup_read desc
 limit 20;
