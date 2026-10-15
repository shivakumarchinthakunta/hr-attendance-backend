# DECISIONS.md — Part C

1. **Indexes.** A unique index on `employees.emp_code` enforces stable business identity. A unique compound
index on `(emp_code, date)` makes an employee's daily attendance unique and makes punch-in race-safe.
Additional employee department/join-date and attendance date/status/employee indexes support filtered
listing and analytics. Index selection must be confirmed with executionStats on the supplied dataset.

2. **Identical concurrent punch-ins.** Both requests may initially observe no record, but the unique compound
index allows only one insert. The successful request returns 201; the duplicate-key request becomes 409.
This relies on MongoDB's uniqueness constraint rather than a vulnerable read-then-write check.

3. **Leaderboard cutoff ties.** The pipeline groups lateness by employee, ranks total late minutes with
`$rank`, and sorts by rank then `emp_code`. The limit is applied after ranking. Therefore tied employees
share a rank and later rank numbers are skipped (1, 2, 2, 4), though a tie at the cutoff may be split by
the requested limit, as the endpoint contract's exact cutoff behavior must be checked against OpenAPI.

4. **Employees with no logs.** Department summary starts from employees whose `joined_on` is before the
next month, then `$lookup`s attendance for the requested month and preserves empty arrays during unwind.
This keeps no-log employees in headcount while excluding employees who joined after the period.

5. **100x data.** Re-check compound-index order with representative filters and explain plans, partition the
workload by date if operationally appropriate, consider a replica set/sharding only after measuring, and
pre-aggregate frequently requested summaries. Keep raw attendance as the source of truth and validate
all changes against concurrency and correctness tests.
