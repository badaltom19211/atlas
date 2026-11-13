# AIA

React + FastAPI contract chat with Databricks authentication and Lakebase history.
The backend now runs the updated deep_agent_v1 workflow: optional shared-glossary
enrichment, query metadata,
parallel Genie and hybrid document retrieval with reranking, and a single merged
answer with SQL and document sources. The notebook Deep Agent invokes the combined search tool; there is no second
outer source-selection router.

Start with [UPGRADE_DEEP_AGENT.md](UPGRADE_DEEP_AGENT.md) for existing installations,
or [SETUP_NEW_WORKSPACE.md](SETUP_NEW_WORKSPACE.md) for a fresh workspace.
[UPGRADE_AIA_UI.md](UPGRADE_AIA_UI.md) describes branding and conversation search.

The red-and-white interface includes private history, feedback, notes, saved
responses, user name/initial, and title/message search with highlighted results.
New answers show cited Genie SQL under View SQL and up to three grouped PDF links
with known page ranges under Sources. Internal citation tags are validated before
being removed from the displayed answer. Older chats keep their inline references.
Existing chats, database tables and authentication remain compatible.

## Runtime

The backend imports `server/deep_agent_v1.py` and directly calls its `chat()`
function in the existing app process. `server/notebook_bridge.py` keeps that
synchronous work off the web event loop; no subprocess or notebook Job runs.
The exported notebook owns prompts, follow-up resolution, metadata, Genie and RAG.
`server/agent_runtime.py` provides request-scoped credentials/clients and tracing.
`server/notebook_output.py` shapes references for the existing React UI.

Genie, search, embeddings and models use the signed-in user's forwarded token.
Lakebase and startup glossary downloads use the app service principal. Ownership
checks protect every chat operation. There are no shared credentials or global
chat sessions. Follow-ups use the last complete owned turn, with its resolved
subject saved in Lakebase. Optional MLflow tracing uses the app identity and an
explicit experiment; no experiment means no workflow tracing.

See [Direct notebook workflow](DIRECT_NOTEBOOK_WORKFLOW.md) for exact function
calls, the exported-file update contract, deployment and cancellation limits.
Editing the workspace notebook alone does not change deployed code. The old
`server/deep_agent.py` remains only for `ATLAS_AGENT_WORKFLOW=adapted` rollback.

## Configuration

The public app.yaml is a template: fill the Genie ID, fully qualified contract
index name and Lakebase endpoint. It defaults to AI Gateway models matching the
notebook. Read UPGRADE_DEEP_AGENT.md for scopes, optional serving-endpoint transport,
user permissions and deployment checks. Optional ATLAS_GLOSSARY_WORKSPACE_DIR points
to the team's existing Workspace glossary folder. Grant the app service principal
read access there; startup fetches its Python/JSON files, so no manual copying is
needed. Alternatively, ATLAS_GLOSSARY_DIR points to a packaged app-local folder.
Set only one. No tokens belong in app.yaml or VITE_*.

## Local development

Use Python 3.11+ and Node.js 20.19+ (or a supported newer LTS). Install
requirements-dev.txt, run npm ci, copy .env.example to .env and configure the target
workspace. Authenticate the Databricks CLI using the target-workspace profile.
Run python -m server.run and npm run dev in separate terminals. Never upload .env,
.venv or node_modules. For a UI-only local preview use VITE_APP_MODE=preview.

Checks: python -m pytest server -q, npm test, npm run build.
Automated checks use synthetic responses. Test the real Azure resources and
permissions after deployment; they are not validated by an offline build.
