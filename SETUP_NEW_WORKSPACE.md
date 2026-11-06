# Set up AIA contract chat in a new Databricks workspace

If the app and chat tables already exist, use [UPGRADE_DEEP_AGENT.md](UPGRADE_DEEP_AGENT.md).

## 1. Prepare the contract resources

This app requires:
- A Genie Agent configured with the desired structured contract tables and SQL warehouse.
- An AI Search/Vector Search index supporting HYBRID search with these columns:
  chunk_id, file_name, document_title, vendor_name, section_title, page_start,
  page_end, contextualized_text, citation.
- AI Gateway embedding and chat model services compatible with the supplied notebook.
  Embeddings must match the model/dimensions used to create the index. Alternatively,
  explicitly select serving mode as described in UPGRADE_DEEP_AGENT.md.
- Databricks reranking available for the HYBRID document query.
- A Lakebase project, branch, compute endpoint and PostgreSQL database.

Creating the app or Lakebase does not create the index, document corpus or models.
Default configuration uses AI Gateway. Serving mode is an explicit alternative.

## 2. Configure app.yaml

Replace the three REPLACE_WITH_ placeholders and verify the model settings:

| Setting | Target workspace value |
|---|---|
| DATABRICKS_GENIE_AGENT_ID | The 32-character ID after /genie/rooms/ in the URL |
| DATABRICKS_CONTRACT_INDEX | catalog.schema.index |
| DATABRICKS_MODEL_API | gateway (default) or serving |
| DATABRICKS_AGENT_MODEL | AI Gateway chat model identifier |
| DATABRICKS_EMBEDDING_MODEL | AI Gateway embedding model identifier |
| LAKEBASE_ENDPOINT | projects/<project>/branches/<branch>/endpoints/<endpoint> |

Keep ATLAS_AUTH_MODE=databricks-app, ATLAS_HISTORY_BACKEND=lakebase, and
command: ['python', '-m', 'server.run'].

Databricks Apps supplies the workspace host and app OAuth credentials.
The attached database supplies PGHOST, PGPORT, PGDATABASE and PGUSER.
Do not upload a real .env file or place tokens in React/VITE_* settings.

## 3. Create or configure the app

Use the nine-dot app switcher → Databricks Apps → create a custom app.
Record the app's service principal client/application UUID from Authorization.
This is not its numeric principal ID or OAuth integration client ID.

In Settings → User authorization, add ai-gateway, genie and vector-search.
Retain model-serving if using serving endpoints.
Keep the standard identity scopes. A workspace administrator may need to enable
these scopes. In Resources, attach Database with the intended Lakebase project,
branch and database, resource key postgres, and Can connect and create.

Attaching the database requires CAN MANAGE on the Lakebase project and creates
the app's database role. Resource and data permissions are separate from scopes.

## 4. Initialize a fresh database only

As the database owner, run setup/01_create_tables.sql against the selected
Lakebase PostgreSQL database (normally databricks_postgres), not a Spark warehouse.
It refuses to run if Atlas tables already exist.

If the Lakebase SQL Editor says Limited SQL Editor / transactions unsupported,
use a direct PostgreSQL client that supports transactions for this script.
It uses BEGIN, SET LOCAL and COMMIT; do not run it piecemeal in the limited editor.
If any Atlas tables exist, inspect them before retrying; do not drop them.

Then replace REPLACE_WITH_NEW_APP_SERVICE_PRINCIPAL_CLIENT_ID in
setup/02_grant_app.sql with the new app's service principal UUID and run it.
The role must already exist from the database attachment.

Tables: public.atlas_users, public.atlas_conversations, public.atlas_messages,
public.atlas_comments, public.atlas_tool_runs. There is no new source table or
schema migration for the contract workflow.

## 5. Upload and deploy

Upload the clean source to a workspace folder preserving the directory structure.
Select the folder that directly contains app.yaml. Give the app service principal
CAN READ on it. In the app, click Deploy, select that source folder and deploy.

The platform installs Python/Node dependencies, builds React and runs
python -m server.run. FastAPI serves the React UI and /api on the same app URL.

If using the Databricks CLI instead of the upload UI, run from the clean source
root (before creating .env or dependencies), replacing these examples:

    databricks auth login --host "https://<target-host>" --profile target-workspace
    databricks workspace import-dir . "/Workspace/Users/<target-user>/atlas-contract-chat" --profile target-workspace
    databricks apps deploy <app-name> --source-code-path "/Workspace/Users/<target-user>/atlas-contract-chat" --mode SNAPSHOT --profile target-workspace

## 6. Share and verify

Grant users or a group CAN USE on the app. Users also need USE CATALOG, USE SCHEMA
and SELECT on the index, and permission to invoke the configured models. Retrieval
and model calls use the signed-in user's permissions. Lakebase uses the app service
principal; chat ownership is enforced by the backend.
Genie users also need CAN RUN on the selected agent and access to its underlying
data. Its configured warehouse credentials must be valid; Genie can use embedded
author credentials for compute. Scopes alone do not grant data permissions.

Follow the test steps in UPGRADE_DEEP_AGENT.md. New storage starts empty; this
package does not migrate chats from another workspace or copy source documents.
Existing history migration requires separate user identity mapping.

Troubleshooting:
- Missing configuration: fill all resource placeholders and verify model settings.
- Genie errors: check the ID, Agent-mode API availability, genie scope, and user
  access to the agent, SQL warehouse and its tables.
- Model errors: check gateway/serving mode, model names, user access and scopes.
- Missing PGHOST/PGUSER: attach the intended database in Resources.
- Missing tables: initialize the intended database once.
- Database permission error: check the attached app role and table grants.
- Contract search failure: check endpoint names, model/index readiness, required
  columns, embedding compatibility, user scopes and data permissions.
- Source download error: give the app service principal CAN READ on the source.
- Package install error: check company package registry/network policies.

References:
- [Deploy an app](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/deploy)
- [App authorization](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/auth)
- [Lakebase app resource](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/lakebase)
- [Lakebase SQL Editor limitations](https://learn.microsoft.com/en-us/azure/databricks/oltp/projects/sql-editor)
