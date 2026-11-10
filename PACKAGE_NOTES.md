# AIA deep-agent workflow package

Updated 2026-11-10. This release includes AIA branding, improved chat/search,
SQL/PDF sources, and the updates from deep_agent_v1 (1).ipynb.

Each contract request calls Genie and metadata-aware document search once in
parallel. Document search requests HYBRID retrieval, Databricks reranking and
20 chunks by default. The final answer combines supported facts with [G#]/[D#]
citations internally; new answers hide the tags and display cited SQL queries and
the three most cited PDFs below the answer. Known volume-folder links target the
actual PDF filename when available. Follow-ups use owner-checked persisted chat context. There is no shared
notebook token/session and no additional outer Genie router.

No database schema change is needed. Existing users, chats, feedback and notes are
preserved. Request metadata and source references use atlas_tool_runs. The source
contains no notebook outputs, private chat data or credentials. Public GitHub
configuration keeps workspace resource placeholders; a private handoff can contain
resource names only. See UPGRADE_DEEP_AGENT.md before deploying.

The notebook's LLM metadata extractor is integrated. The separate Spark ai_extract
notebook and document-ingestion pipeline remain outside the app. Editing a notebook
does not automatically update deployed code. MLflow experiment setup is not copied;
request provenance is persisted in app history instead.

Optional glossary enrichment calls the team's existing loader/enrichment functions.
ATLAS_GLOSSARY_WORKSPACE_DIR enables automatic startup download from their existing
Workspace folder, using the app service principal with folder read access. Restart
the app to refresh glossary-only changes; no manual copying is needed. The three
external glossary assets are not bundled in this public repository. The alternative
ATLAS_GLOSSARY_DIR still supports packaged files; configure only one of these settings.
See UPGRADE_DEEP_AGENT.md for setup, function mapping and failure behavior.

Validation: 154 backend tests passed, including 20 Workspace glossary/startup tests.
The unchanged UI previously passed 26 frontend tests and the TypeScript/Vite
production build. Browser checks against a local fixture backend verified
the merged answer, grouped source display, SQL disclosure and references after reload;
no browser console errors were observed.

Tests use synthetic HTTP/model responses. Target Azure resources, permissions,
answer quality and index freshness require live checks after deployment. Publishing
source does not deploy or change workspace resources.
