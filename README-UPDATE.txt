STAGE SCOUT 3.3 - GLOBAL ATS LOCATION CODE FIX

This is a SMALL UPDATE for an existing, working Stage Scout 3.2 installation.
No new GitHub repository is needed, and no search settings need to be changed.

ROOT CAUSE
The previous geography filter parsed country suffixes only when written in
UPPERCASE. ATS rows such as 'Ho Chi Minh City, vn' and 'Rayong, th' were
marked as unknown locations and therefore preserved.

FIX
- Recognize two-letter ISO country codes regardless of case: vn, TH, jp, etc.
- Recognize three-letter ISO country codes: VNM, THA, USA, CHE, FRA, etc.
- Add fallback recognition of frequently used Asian city names.
- Preserve European country codes and the current treatment of genuinely
  unknown and mixed locations.
- Continue to apply the same filters to historical data/jobs.csv rows on
  every successful Daily stage scout run. Existing statuses are preserved.

INSTALLATION (WINDOWS / GITHUB DESKTOP)
1. GitHub Desktop: Fetch origin, then Pull origin if available.
2. Repository > Show in Explorer.
3. Extract this ZIP and open the stage-scout-v3.3-update folder.
4. Copy its CONTENTS into the EXISTING repository's root folder.
   Replace selection_filters.py and add tests/test_v33_geo.py.
5. DO NOT replace config.json, data/, .git/, or the Actions workflow.
6. GitHub Desktop: Commit to main, then Push origin.
7. GitHub website: Actions > Daily stage scout > Run workflow.
   IMPORTANT: Start a NEW run instead of re-running an old workflow run.
8. After success, inspect data/last_run.json and data/jobs.csv.
   The 'history_removed.geography' counter shows old rows removed.

NO NEW OFFERS NEEDED: historical cleanup happens even when new is zero.

TESTING
The complete v3.2 + v3.3 test suite passed offline (53 tests). The fix has
not been run against your private live jobs.csv or third-party APIs.

CAUTION
Unrecognized geographic locations (e.g. 'Remote' or a tiny village with no
country code) still remain flagged, to avoid losing valid European jobs.
If you prefer strict rejection of every unknown location, add to config.json:

"geography_filter": {
  "enabled": true,
  "keep_unknown_locations": false,
  "keep_mixed_locations": true
}

That stricter setting WILL discard some potentially relevant European jobs.
Existing GitHub Issues are not deleted when history is cleaned.
