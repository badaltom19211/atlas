# Package preparation

Prepared 2026-11-01 from the current Atlas app source. The existing deployment was
not changed. Target-specific resource defaults were removed from the portable
copy; they must be supplied using app.yaml or the optional local environment.
Unfilled deployment placeholders fail validation instead of contacting old resources.
The configuration test fixture uses explicit fake resource names.

SQL schema was generated from the application's SQLAlchemy models for the five
active chat tables. The legacy login-session table is not created or granted.
The scripts have not been executed against the destination workspace.

Verification on 2026-11-01: all 28 portable backend tests passed using isolated
fixture data. React source files match the previously built and deployed UI.
The ZIP was checked for corruption, excluded files, and original workspace/user
identifiers. Destination resource availability and live integration remain untested.

Updated 2026-11-02 for GitHub publication with the authenticated account header
and simplified text-only composer. Frontend build and all five frontend tests
passed; the matching UI release was deployed and its assets verified. Resource
settings remain placeholders so this repository can be configured for a new
workspace. The original workspace deployment is maintained separately.
