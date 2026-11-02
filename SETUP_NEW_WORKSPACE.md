# Deploy Atlas in a different Databricks workspace

Citrix is the desktop/browser used to access Databricks. The hosted React and
FastAPI application runs in the target Databricks workspace. Its URL, service
principal, resources, and permissions are set up there. No frontend rewrite is
needed for the move, provided the target supports the APIs used by this app.

## 1. Get the source

Clone this repository in the environment where you prepare deployments:

```sh
git clone https://github.com/badaltom19211/atlas.git
cd atlas
```

Alternatively, download the repository ZIP and extract it in Citrix. The folder
containing `app.yaml`, `package.json`, `requirements.txt`, `src`, and `server` is
the app root. Deploy that folder, not the ZIP itself. The repository contains no
credentials, chat history, or installed Node/Python dependencies. Exclude `.git`,
local `.env`, caches, and installed dependencies when uploading source.

## 2. Prepare the target resources

Ask the target workspace owner to confirm Databricks Apps, Lakebase Autoscaling,
user authorization, the AI Gateway, and the required agent/model APIs are enabled.
The original workspace's resource IDs and permissions are not transferred with code.

You need:

- A Genie Agent in the target workspace, connected to the intended tables and SQL
  warehouse. This implementation calls `/api/2.0/genie/agents/{id}/responses` and
  expects Responses-style SSE events. A classic Genie Space ID with only the
  Conversation API is not an interchangeable replacement; that requires changing
  the adapter in `server/notebook_agent.py`.
- A model accessible through `/ai-gateway/mlflow/v1` that supports the Responses
  API and tool calling. `DATABRICKS_AGENT_MODEL` is the model identifier accepted
  by that gateway. If the workspace only offers a different model API, an adapter
  change is required in `server/notebook_agent.py`.
- A queryable Vector Search index with `full_text` and `pk` columns and support
  for the app's HYBRID search. The index must contain the desired project records.
  An index with different columns needs corresponding changes in the RAG code.
- A chat model-serving endpoint for summarizing project results. It must accept
  chat `messages` through `/serving-endpoints/{name}/invocations` and return
  `choices[].message.content`.
- A Lakebase Autoscaling project, branch, compute endpoint, and PostgreSQL database.
  A newly created project normally includes a `production` branch and
  `databricks_postgres` database. Record its endpoint resource name.

The app's system prompt routes bike-store questions to Genie and project-document
questions to RAG. If the destination uses different subjects, update the prompt
and tool descriptions as well as configuring the resources.

## 3. Fill in app.yaml

Replace every `REPLACE_WITH_...` value. The portable app refuses to start with
unfilled placeholders.

| Setting | Value from the target workspace |
|---|---|
| `DATABRICKS_GENIE_AGENT_ID` | The target Genie Agent ID |
| `DATABRICKS_PROJECT_INDEX` | Fully qualified `catalog.schema.index` |
| `DATABRICKS_AGENT_MODEL` | A compatible AI Gateway model identifier |
| `DATABRICKS_RAG_ENDPOINT` | The project-summary chat serving endpoint name |
| `LAKEBASE_ENDPOINT` | `projects/<project>/branches/<branch>/endpoints/<endpoint>` |

Keep `ATLAS_AUTH_MODE=databricks-app`, `ATLAS_HISTORY_BACKEND=lakebase`, and
`command: ['python', '-m', 'server.run']`.

Hosted Databricks Apps supplies the workspace host and app OAuth credentials.
The attached Lakebase resource supplies `PGHOST`, `PGPORT`, `PGDATABASE`, and
`PGUSER`. Do not copy the original workspace host, database host, service principal,
or credentials into this app. No secret or token belongs in a `VITE_*` variable.
The `.env.example` file is for optional local development only; hosted setup uses
`app.yaml`. Do not create/upload a real `.env` for hosted deployment.

## 4. Create the new Databricks App

In the target workspace, use the app switcher to open Databricks Apps and create
a custom app with your chosen name, such as `atlas-chat`. Databricks creates a
new dedicated service principal and a new app URL. Copy its service principal
**client/application ID** from the Authorization tab; this is not the numeric
principal ID or the app's separate OAuth integration client ID.

Enable user authorization and request these scopes:

```text
ai-gateway
genie
vector-search
model-serving
```

The standard current-user and access-control read scopes are normally added by
the platform. If the required scopes are unavailable or blocked by workspace
policy, the workspace administrator must enable the needed capabilities before
this version can work there. Do not substitute broad permissions silently.

## 5. Connect Lakebase and initialize chat tables

1. In the app's resources, add **Database → Lakebase Autoscaling**. Choose the
   target project, branch, and database. Use the default resource key `postgres`
   and **Can connect and create**. Adding this resource creates the app's
   PostgreSQL role, named after the new service principal client ID.
2. As the target database owner, open the **Lakebase SQL editor**, select the
   correct branch/database, and run `setup/01_create_tables.sql`. Use a fresh
   database; this script refuses to run if any active Atlas table already exists.
   Run it in PostgreSQL, not a Databricks Spark SQL warehouse.
3. In `setup/02_grant_app.sql`, replace the `app_role` placeholder with the new
   app service principal client ID. Run it in the same Lakebase database. It
   grants schema usage and SELECT/INSERT/UPDATE/DELETE only on the five Atlas tables.

Tables: `public.atlas_users`, `public.atlas_conversations`, `public.atlas_messages`,
`public.atlas_comments`, and `public.atlas_tool_runs`. App startup does not create
these production tables automatically. The legacy sessions table is not needed.

## 6. Upload and deploy

Upload the clean, extracted source to a new workspace folder, preserving file
names and directory structure. The selected deployment folder must directly
contain `app.yaml`; do not select its parent folder. Give the new app service
principal **CAN READ** on that source folder.

If the Databricks CLI is available in Citrix, these commands are an alternative
to uploading through the UI. Replace the example values and run from the clean
extracted `atlas-chat` folder, before creating any local `.env` or dependencies:

```powershell
databricks auth login --host "https://<target-workspace-host>" --profile target-workspace
databricks workspace import-dir . "/Workspace/Users/<target-user>/atlas-chat" --profile target-workspace
```

In Databricks Apps, start the app compute if stopped, click **Deploy**, select
the uploaded app root, and deploy. The platform installs Python and Node
dependencies, runs `npm run build`, and starts `python -m server.run`. FastAPI
serves the built React UI and `/api` on the same URL. No separate Vite server or
Genie iframe is used in the hosted app.

Alternatively, after starting compute:

```powershell
databricks apps deploy <new-app-name> --source-code-path "/Workspace/Users/<target-user>/atlas-chat" --mode SNAPSHOT --profile target-workspace
```

## 7. Give users access and verify

Use the app Overview's **Share** action to grant users or a group **CAN USE**.
Users sign in with the target organization's Databricks identity/SSO and consent
to the requested scopes. Genie, the model gateway, the project index, and the
summary endpoint use each signed-in user's permissions. Give those users access
to the required resources, including the Genie tables and SQL warehouse.
Lakebase uses the app service principal; normal chat users do not need personal
database roles. Conversation ownership is enforced by the backend.

Verify in order:

1. App build succeeds and `/api/health` reports `{"status":"ok"}` when authenticated
   through the Databricks app gateway.
2. Sign in, create a conversation, reload, and confirm it persists in Lakebase.
3. Ask a Genie question with a known answer. If the same bike data was migrated,
   the distinct-category count should be 7; do not expect that number for different data.
4. Ask a project question, then a mixed Genie/project question; inspect Tools used.
5. Check feedback and notes persist. Sign in as a second user and confirm that
   user's history is separate.

New Lakebase storage starts with empty history. The source ZIP does not move old
chats, tables, Genie configuration, indexes, source documents, models, or access
grants. Migrating existing chat rows needs a separate export/import with user-ID
mapping because user IDs include the workspace host and identity.

## Troubleshooting

| Symptom | Check |
|---|---|
| Placeholder/configuration error | Fill all five `app.yaml` settings |
| Missing PGHOST/PGUSER | Attach the target Lakebase database resource |
| `relation atlas_users does not exist` | Run the table script in the correct database/branch |
| Database permission denied | Run the grant script with the new app's SP client ID |
| Sign-in/authorization failure | Enable user authorization and required scopes; check workspace identity access |
| Genie unavailable or 404 | Use a real target Genie Agent ID and confirm the Responses API is available |
| RAG unavailable | Check index name, `full_text`/`pk`, HYBRID readiness, and the user's model/index permissions |
| Model API error | Confirm gateway route, model name, Responses API/tool-calling support, and user access |
| Source download error | Give the new app SP CAN READ on the uploaded folder |
| Build cannot install packages | Check target workspace package-registry/network policy with its administrator |

The destination workspace has not been accessed or tested as part of preparing
this package. Its service availability and resource permissions must be checked there.

Official references: [deploy an app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/deploy),
[app authorization](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth),
[Lakebase app resource](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase),
[app sharing](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions).
These are the AWS documentation links; use the cloud selector for the target workspace if needed.
