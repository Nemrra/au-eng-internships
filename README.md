# au-eng-internships

Automated tracker for engineering internships, vacation programs, cadetships, studentships and other student roles across Australia.

- `collector/` — runs every 2 hours in GitHub Actions. Reads ~680 employers' job boards directly (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, SuccessFactors, PageUp, Oracle, Workable, LiveHire, BambooHR and more), their student-program pages, GradConnection, Talent.com, VC portfolio boards and community GitHub lists. Filters to Australian student/graduate technical roles, dedupes, and tracks when each listing first appeared and when it disappears.
- `registry/employers.json` — the employer/source registry. `registry/discovered.json` — job boards found automatically for employers whose careers page didn't name one.
- `data/` — collector output: `jobs.json` (open listings), `descriptions.json`, `state.json` (first/last seen, closures), `expected.json` (programs expected to reopen), `last_run.json` and `sources_status.json` (health of every source).
- `tools/tracker_sync.py` — used by the scheduled Claude run that analyses new listings and updates the private dashboard.

LinkedIn, SEEK, Indeed and Prosple block automated collection, so those are covered by web searches during the scheduled Claude runs instead.
