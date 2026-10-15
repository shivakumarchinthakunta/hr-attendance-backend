# REVIEW.md — Part A

**Scope limitation:** the starter `app/main.py` was not supplied. The items below are review
checks derived from the assignment's stated requirements, not claims about defects observed in
the missing starter file. Replace these with concrete line-by-line findings after reviewing it.

| Area to inspect | Failure case / symptom | Required fix |
|---|---|---|
| Environment configuration | Injected `MONGO_URI`/`MONGO_DB` ignored | Read environment variables; never hard-code deployment credentials |
| Startup indexes | Existing database has only `_id` indexes; list/analytics become slow | Create named indexes idempotently at startup |
| Timestamp validation | Seconds, float, string, or bool accepted as milliseconds | Accept integer epoch milliseconds only; reject invalid values with 422 |
| Timestamp precision | Milliseconds remain in calculations or response | Truncate instants to whole seconds before calculation and storage |
| Time zone | UTC date used for attendance day | Derive attendance date using IST (UTC+05:30) |
| Overnight shift | Early-morning punch assigned to wrong shift date | Resolve previous shift day when shift end is not after shift start |
| Late grace period | Exactly 10 minutes late counted as late | Only count late when strictly greater than 10 minutes; floor minutes from shift start |
| Overtime | Any positive overtime counted | Count only when overtime is at least 30 whole minutes |
| Work-hours rounding | Python's default bankers' rounding used | Decimal half-up to two decimals |
| Half-day | Calculated before rounding or from raw duration | Use rounded work_hours; half-day when less than 4.50 |
| Concurrency | Simultaneous punch-ins create duplicate records | Unique `(emp_code, date)` index and handle duplicate-key as 409 |
| Punch-out race | Concurrent requests overwrite each other | Conditional atomic update where `punch_out` is null |
| Correction audit | History entries overwritten under concurrent PATCH | Atomic update pipeline appending history |
| Pagination | Page zero or page size above 100 accepted | Page starts at 1; default 20; maximum 100; total uses filters |
| Analytics | Aggregations computed by Python loops | Perform analytics in MongoDB aggregation pipelines |
| Department headcount | Employees without attendance logs excluded | Start department summary from employees and preserve empty lookups |
| Leaderboard ties | Array index used as rank | Use `$rank` after grouping; sort ties by employee code; limit after ranking |
| Trend gaps | Missing dates omitted | Use MongoDB `$densify`/`$fill`, then compute 7-day window |
| Explain | Query plan not exposed or uses different filters | Return executionStats for the endpoint's main query/pipeline |

Items examined and deemed correct: **not assessable**, because the starter file was not provided.
