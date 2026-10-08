# Watching the database itself

Written 30-09-2026 for ops-32. Observability used to stop at the API: nothing recorded Postgres CPU,
connections, disk growth or slow statements, and nothing made anyone look at Supabase's own advisors on
a schedule. This is the routine, the queries that support it and the alerts to set.

**What is and is not done.** The routine and the review queries are in the repository and the queries
are tested against a real Postgres. The alerts, the first review and the compute-size decision are
**not done** — each is a dashboard or an account the repository cannot reach — and are listed in §5.
`docs/operations/database-review-log.md` is where a review is written down; it records none yet, and says so.

The dashboard labels below are from memory of Supabase's product; egress is refused where this was
written, so none was checked against Supabase's documentation. The intent of each step is what matters.

## 1. The monthly review

One sitting, in the first week of the month, by whoever owns operations. About twenty minutes.

1. **Run the advisors** — Dashboard → Advisors → *Security* and *Performance*. Both. Read every finding
   once and write down, for each, *fix*, *intentional (why)* or *not now (why)*.
   Some findings are known and intentional (`docs/BETA_OPERATIONS.md` §3 records which) — a finding that
   appears there needs no new decision, a finding that does not needs one. The advisors have been run
   before, by hand, after migrations (the early deployment readiness audit, deleted on 8 October 2026; see `docs/audits/README.md`); what was missing was a
   routine and a record.
2. **Run the review queries**, `apps/api/scripts/db/monthly_review.sql`, one numbered block at a time in
   the SQL editor (or all of it with `psql "$DATABASE_URL" -f …`). They are read-only and read no
   business row. §2 says what each number means.
3. **Read the dashboard's own reports** — Database → Reports (CPU, memory, disk I/O, connections), for
   the month. A peak is the point; an average hides it.
4. **Write it down** in `database-review-log.md`: the date, the figures that matter, what you decided.
   A review that leaves no record is one nobody can tell was held.

## 2. What the queries tell you and where each becomes a problem

The thresholds are **starting points chosen here, not measurements**: there is no load test to take
them from (ops-22 is the place a compute size should come from), so treat a crossing as "look", and
replace the figure with a measured one the first time a review has a month of data behind it.

| block | reads | look when |
|---|---|---|
| 1, 2 size | the largest tables with their indexes, and the whole database | the database passes **70%** of the plan's disk allowance, or grows by more than a fifth in a month. The ledger (`journal_lines`, `journal_entries`, the stock ledger) is what grows; the largest client measured so far holds 12,836 entries and 32,936 lines. **A table whose indexes outweigh its rows** is worth a look |
| 3, 4 slow statements | `pg_stat_statements`: by total time (what the database is busy with), then by mean (what one user waits for) | a statement in the top five by total time that is not one you expect; a mean above **a second**; any statement whose `max_ms` is tens of seconds. The text is normalised — it holds no client data |
| 5, 6 connections | in use against `max_connections`, and who holds them | in use above **70%** of the ceiling, or any `idle in transaction`. Saturation does not show up as slowness; it shows up as the API failing. PostgREST and the auth service hold connections of their own, so the API's share is not the whole |
| 7 open transactions | anything open for over a minute | anything. A transaction left open blocks vacuum and can block a migration |
| 8 unused indexes | indexes nothing has read since the statistics began (unique and primary-key indexes excluded) | they are **candidates, not verdicts**: a year-end report may use an index that shows zero in a quiet month. Read block 12 first. Drop through a migration after a full year's statistics, never from the editor |
| 9 broken indexes | an index left invalid by a failed `CREATE INDEX CONCURRENTLY` | any row: it costs every write and helps no read |
| 10 dead rows | tables autovacuum is behind on | a dead-row share above about 20% on a table of any size |
| 11 cache | table and index cache hit ratio | either under **99%** for the month: reads are going to disk, which is the signal to look at compute size |
| 12 statistics age | when the statistics were last reset | always read first: every "since" above is since this moment, and a restart empties them |
| 13 whole-table reads | large tables read mostly by sequential scan | a table of hundreds of thousands of rows with `seq_tup_read` in the tens of millions is a report that should read a pre-aggregated table (CLAUDE.md, *Reporting performance*), or a missing index |

**`pg_stat_statements`.** Block 3 says whether it is installed and in which schema. Supabase installs it
in `extensions`, which is where block 4 reads it; if block 3 shows it elsewhere, change the schema name
in block 4; if it shows nothing, enable it (Database → Extensions) and review again after a few days of
traffic. I could not confirm its state on the live project from here.

## 3. Alerts to set (dashboard — a person must do this)

Alerts that reach a person are the half of monitoring the review cannot replace: the review is monthly
and saturation takes an afternoon. Set these, to the channel the owner agrees, as far as the plan allows
(some plans offer fewer alert types; say in the log which were possible):

- **CPU** sustained above 80% for 15 minutes.
- **Disk** above 70% of the allowance, and again at 85%.
- **Connections** above 70% of `max_connections` for 5 minutes.
- **Memory / swap** if the plan reports it: sustained high memory with swap in use is a compute-size signal.

## 4. Choosing the compute size

Not decided here. The finding ties it to the load test in ops-22; until that exists, the review's blocks
5 and 11 and the dashboard's CPU graph are the evidence. A rule to start with, to be replaced by a measured
one: move up a size when two of these hold for two consecutive months — CPU peaks above 80%, cache hit
below 99%, connections above 70%. One of them alone is a fluctuation.

## 5. Steps that need a person

1. Run the first review now and write it in the log (§1).
2. Set the dashboard alerts (§3) and record which the plan allowed.
3. Confirm block 3 shows `pg_stat_statements`; enable it if not.
4. Put the next review in a calendar. This repository does not schedule it: a scheduled job would need a
   production database credential in CI, which is the owner's decision (`deploy-migrations` holds one
   already, for migrations only), and a monthly human read is what the routine is for.
