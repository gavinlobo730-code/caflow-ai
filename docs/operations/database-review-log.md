# Database review log

One entry per monthly review, newest first, as `docs/operations/database-monitoring.md` §1 describes.
An entry says **when**, **what was read**, **what was found** and **what was decided** — including
"nothing, because…". A month with no entry is a month nobody can show the review was held.

**Findings recorded here must not name a table, policy or function the advisors flagged as a security
weakness**: this repository is public. Record the count and the decision ("3 security findings, all
intentional, see BETA_OPERATIONS §3"), and keep the detail in the private tracker.

## Entries

*No review has been held. The routine, the queries and the alert list were written on 30-09-2026; the
first review is the first step in `database-monitoring.md` §5.*

<!--
Template

### DD-MM-YYYY — reviewed by <name>

- Advisors: security <n> findings (<n> new), performance <n> (<n> new). Decisions: ...
- Size: <x> GB of <allowance> (<pct>%), <+/-pct> on last month. Largest: ...
- Connections: peak <n> of <max>. Idle in transaction: <n>.
- Slow statements: top by total time ...; any mean above a second ...
- Indexes: unused candidates ...; broken: none.
- Cache: table <pct>%, index <pct>%.
- Dashboard alerts in place: CPU / disk / connections / memory (which the plan allowed).
- Decided: ...
-->
