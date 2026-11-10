# AIA

React + FastAPI contract chat with Databricks authentication and Lakebase history.
The backend now runs the updated deep_agent_v1 workflow: optional shared-glossary
enrichment, query metadata,
parallel Genie and hybrid document retrieval with reranking, and a single merged
answer with SQL and document sources. The app schedules each data source once;
there is no second outer source-selection router.

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

server/deep_agent.py implements the combined workflow. server/query_metadata.py
handles the notebook's LLM metadata extraction and follow-up interpretation.
server/genie.py calls the Genie Agent Responses API; server/citations.py validates
and bounds references. React renders these references without executing notebook HTML.
server/glossary.py adapts the shared glossary files when packaged and configured.
server/app.py uses DeepContractAgent, not the legacy RoutedAgent.
The old adapter modules remain for compatibility/regression coverage.

Genie, search, embeddings and answer models use the signed-in user's forwarded
access token. Lakebase uses the app service principal, with API ownership checks
for every chat operation. No global notebook token or shared chat session is used.
Source metadata is saved in the existing atlas_tool_runs table and survives reload.

This is an app-native port with deterministic orchestration, not notebook execution
or a Deep Agents framework deployment. Editing the workspace notebook does not
synchronize this code. The ingestion/chunking notebook stays outside the request
path; the separate ai_extract metadata notebook is not invoked. MLflow tracing
setup is not ported; the app persists bounded request provenance instead.

## Configuration

The public app.yaml is a template: fill the Genie ID, fully qualified contract
index name and Lakebase endpoint. It defaults to AI Gateway models matching the
notebook. Read UPGRADE_DEEP_AGENT.md for scopes, optional serving-endpoint transport,
user permissions and deployment checks. Optional ATLAS_GLOSSARY_DIR points to a
packaged copy of the team's glossary folder; the notebook alone does not include
those files. No tokens belong in app.yaml or VITE_*.

## Local development

Use Python 3.11+ and Node.js 20.19+ (or a supported newer LTS). Install
requirements-dev.txt, run npm ci, copy .env.example to .env and configure the target
workspace. Authenticate the Databricks CLI using the target-workspace profile.
Run python -m server.run and npm run dev in separate terminals. Never upload .env,
.venv or node_modules. For a UI-only local preview use VITE_APP_MODE=preview.

Checks: python -m pytest server -q, npm test, npm run build.
Automated checks use synthetic responses. Test the real Azure resources and
permissions after deployment; they are not validated by an offline build.
