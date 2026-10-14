STAGE SCOUT 3.2 - FILTER UPDATE FOR EXISTING 3.1 REPOSITORY

Install from GitHub Desktop:
1. Show your repository in Explorer.
2. Extract this ZIP and open the stage-scout-v3.2-update folder.
3. Copy its CONTENTS (not its enclosing directory) to the repository root.
4. Allow scout.py, run_safe.py and requirements.txt to be replaced.
5. Leave config.json and the entire data/ folder in place: custom company
   watchlists, previous findings, and application statuses will be preserved.
6. In GitHub Desktop: Commit to main; Push origin.
7. GitHub website: Actions > Daily stage scout > Run workflow (new run).

Filtering enabled by DEFAULT; no edits to config.json are required:
- Summer internships of any year: excluded.
- Positions clearly starting June-August 2027: excluded.
- Jobs explicitly outside geographic Europe: excluded.
- Swiss, UK, Norwegian, and other European roles: retained.
- Unknown or mixed location: retained with a verification warning.
- German language exclusion from v3.1: unchanged.
- JobSpy searches aimed outside Europe: removed from rotation automatically.
- data/jobs.csv: old out-of-scope rows cleaned on next successful run.

The source gathering logic is unchanged and still uses bounded timeouts.
All old tests plus 15 new tests have passed offline with the original 3.1
config.json. Live providers are not covered by those offline tests.

New counters in data/last_run.json:
 excluded_by_summer
 excluded_outside_europe
 location_unknown_or_mixed
 history_removed

Optional fine-tuning (insert at top level within your config.json):
 "geography_filter": {
   "enabled": true,
   "keep_unknown_locations": true,
   "keep_mixed_locations": true
 },
 "season_filter": {
   "exclude_summer_internships": true,
   "excluded_summer_years": [2027]
 }

If you choose to hide offers with unverified locations too, set
"keep_unknown_locations" to false. This may discard valid European jobs.
