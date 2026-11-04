# Upgrade an existing Atlas app to the contract notebook

This version replaces the bike/project Deep Agent with the supplied contract Q&A
workflow. It does not call Genie. Existing chat history, notes and feedback remain
in the same Lakebase tables; no database migration is required.

## 1. Use the complete updated source

Extract the new ZIP into a new folder in Citrix. Replace the deployed app source
with this complete version, including server/, src/, requirements.txt and app.yaml.
Changing only app.yaml in the previous version is not enough.

The notebook's code now runs as ContractRAGAgent in server/notebook_agent.py.
It is an app-native port, not a remotely executed notebook or a new serving endpoint.
It calls the existing embedding and answer model endpoints.

## 2. Check app.yaml

The prepared Citrix ZIP has the resource values from the supplied notebook.
For a generic repository checkout, replace these four placeholders:

| New setting | Value |
|---|---|
| DATABRICKS_CONTRACT_INDEX | Exact three-part contract index name |
| DATABRICKS_EMBEDDING_ENDPOINT | Embedding serving endpoint used by the notebook |
| DATABRICKS_ANSWER_ENDPOINT | Answer/chat serving endpoint used by the notebook |
| LAKEBASE_ENDPOINT | Existing Lakebase compute resource name |

Remove the obsolete DATABRICKS_GENIE_AGENT_ID, DATABRICKS_AGENT_MODEL,
DATABRICKS_PROJECT_INDEX and DATABRICKS_RAG_ENDPOINT entries. They are not read
by this version. Keep ATLAS_AUTH_MODE=databricks-app and
ATLAS_HISTORY_BACKEND=lakebase.

Optional settings: ATLAS_RAG_TOP_K defaults to 5 (allowed 1-10);
ATLAS_RAG_HISTORY_MESSAGES defaults to 6 (allowed 0-20). Six means six individual
previous user/assistant messages, typically three exchanges, not six exchanges.

The embedding endpoint must produce the same type/dimension of vectors used to
build the index. Do not replace it with an arbitrary embedding model.

## 3. Check app authorization and access

In your existing Databricks App, open Settings and find User authorization.
Keep/add vector-search and model-serving. Keep the platform's identity scopes.
The extra genie and ai-gateway scopes are no longer needed by this workflow.
After changing scopes, save and sign in/consent again if prompted.

Each signed-in user needs USE CATALOG, USE SCHEMA and SELECT on the contract index,
plus CAN QUERY on both serving endpoints. Check that both endpoints and the
index are ready. App access alone does not grant access to the contract data.

Keep the existing Resources → Database attachment and the app's database role
and table grants. If the five Atlas tables already exist, do not run the create
tables script again. The app service principal continues to handle Lakebase;
retrieval and model calls use the signed-in user's forwarded Databricks token.

## 4. Upload and redeploy

Upload the extracted source to a new folder in your Azure Databricks Workspace,
preserving the directory structure. The selected folder must contain app.yaml
directly. Give the app service principal CAN READ on the source folder.

Open your existing app → Deploy → choose that source folder → Deploy.
The platform installs dependencies and builds React from this source.
Do not deploy the old public repository revision with placeholders by mistake.
No change is made to any other workspace deployment by preparing this package.

## 5. Test

1. Open the app, sign in and create a new chat.
2. Ask a question with a known answer in your indexed contracts, naming the contract.
3. Ask a follow-up. The answer model receives up to six earlier messages from this
   chat. Retrieval uses the latest question only, matching the notebook; mention
   the contract again if a vague follow-up retrieves unrelated clauses.
4. Ask about information absent from the contracts. Expect an explicit inability
   to find the answer, not an invented clause or date.
5. Reload and confirm the conversation, thumbs feedback and notes persist.
6. Sign in as another user and confirm chat histories are separate.

## Source references and implementation differences

The chat displays only the answer. It does not display bracketed source IDs, the
SOURCES_USED line, or a contract tool-result panel. Metadata is available in the
authenticated API's assistant.custom_outputs and saved in atlas_tool_runs.output.

Metadata includes file, document title, vendor, section, pages, citation, chunk ID,
and used_in_answer. true/false reflects the model's valid selection of retrieved
IDs; null means missing or invalid source selection. This does not prove that
every sentence is supported. We never mark all documents used just because the
model omitted its source list.

The app fixes the pasted code's indentation, broken newlines/regular expressions,
and page-number handling. Metadata is preserved for streamed app responses and
history reloads. Excerpts are capped at 12,000 characters each and flagged when
truncated. Citation metadata is bounded to fit the existing database record.

As in the notebook, generation completes before the answer is emitted; this is
not token-by-token model streaming. MLflow model registration and tracing decorators
are not needed for the app-native workflow and are not installed in the app.

No real Azure model/index request was made during offline validation. Confirm
endpoint availability, embedding compatibility and user access in your workspace.

References:
- [Query AI Search and permissions](https://learn.microsoft.com/en-us/azure/databricks/ai-search/query-ai-search)
- [Serving request formats](https://docs.databricks.com/api/model-serving-query/v1)
- [Databricks Apps authorization](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/auth)
