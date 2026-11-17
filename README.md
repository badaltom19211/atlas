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

The backend imports `server/deep_agent_v1.py` and directly calls its `contract_assistant()`
entry point, which calls `chat()` in the existing app process. `server/notebook_bridge.py` keeps that
synchronous work off the web event loop; no subprocess or notebook Job runs.
The exported notebook owns prompts, follow-up resolution, metadata, Genie and RAG.
`server/agent_runtime.py` provides request-scoped credentials/clients and tracing.
`server/notebook_output.py` shapes references for the existing React UI.

The 16 November `deepagent.py` update adds GPT-OSS reasoning configuration and
normalizes `【D1】` / `［G1］` citations before validation, source counting and display.
`DATABRICKS_AGENT_MODEL=system.ai.gpt-oss-120b` and
`DATABRICKS_REASONING_EFFORT=medium` match that notebook. If retaining a different
model, leave reasoning effort empty unless the model supports it. The supplied
export includes Markdown, `%pip`, notebook credentials and demo calls, so it is
not copied over the importable app module verbatim. App identity isolation,
owned history, cancellation and optional app-principal tracing are preserved.

The 17 November `deepagent_v1.py` attachment contains only the RAG cell. Its prompt,
hybrid reranking, short document/section labels and direct PDF links already match
`server/deep_agent_v1.py`. The remaining trace metadata is now synchronized: embedding
and RAG answer spans record their configured model names per request. No additional
notebook file, configuration change or database migration is needed. MLflow still
requires an existing configured experiment; this update does not enable it by itself.

The backend now sends fixed progress events while the notebook runs:
`queued → understanding → searching → composing → sources`. `src/Thinking.tsx`
shows an animated indicator and changes text every 4.5 seconds within the current
stage. It advances stages only on backend events, never on a simulated timer.
These are workflow statuses, not model reasoning or token streaming.

The latest `deep_agent_v1 (6).ipynb` scope handling is integrated in `server/deep_agent_v1.py`;
the separate `server/app_scope.py` wrapper is removed. The notebook recognizes
simple greetings/thanks/help without model calls and combines other scope checks
with query understanding. Non-contract replies skip the Deep Agent and retrieval;
they remain in saved history without replacing contract context. Contract questions
use the same notebook pipeline and signed-in user. Two failed/invalid classifications
now return the notebook's retry reply with error status and no agent/Genie/RAG calls.
The app persists the reply and failure metadata, marks the optional root MLflow
trace as error, and preserves the previous valid contract context. Uncertain-scope
prompt behavior and Unicode small-talk cleanup remain developer follow-ups.
See [integration and developer follow-ups](DIRECT_NOTEBOOK_WORKFLOW.md#17-november-latest-notebook-integration).
No app.yaml or schema change is required.

Source references are still stored with the answer in Lakebase. The UI displays
only cited evidence under **Sources**; uncited references do not add another
section or explanatory text. Existing answers with no stored reference metadata cannot gain sources
retroactively; ask the question again after redeployment.

Deploy the frontend and backend together to use these changes. Keep your existing
workspace IDs, Lakebase and glossary/MLflow configuration when updating `app.yaml`;
the repository file remains a template. Rebuild/redeploy, refresh the browser and
test with a new question. No database schema migration is required.

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
