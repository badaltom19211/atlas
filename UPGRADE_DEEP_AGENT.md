# Upgrade to the deep_agent_v1 contract workflow

This release runs an app-native port of the updated deep_agent_v1 (1).ipynb inside
FastAPI. React, user authentication and the existing Lakebase database remain in
place. No table migration, notebook job, iframe or separate agent deployment is
needed. Download the complete latest source; changing app.yaml alone is not enough.

## 1. Update app.yaml

Keep your working Genie ID, contract index and Lakebase endpoint. Fill those three
placeholders in the GitHub template. The model settings now default to the notebook's
AI Gateway model services:

```yaml
  - name: DATABRICKS_GENIE_AGENT_ID
    value: "YOUR_32_CHARACTER_GENIE_ID"
  - name: DATABRICKS_CONTRACT_INDEX
    value: "YOUR_CATALOG.YOUR_SCHEMA.YOUR_INDEX"
  - name: DATABRICKS_MODEL_API
    value: gateway
  - name: DATABRICKS_AGENT_MODEL
    value: system.ai.meta-llama-3-3-70b-instruct
  - name: DATABRICKS_EMBEDDING_MODEL
    value: system.ai.gte-large-en
  - name: ATLAS_RAG_TOP_K
    value: '20'
  - name: LAKEBASE_ENDPOINT
    value: "projects/YOUR_PROJECT/branches/YOUR_BRANCH/endpoints/YOUR_ENDPOINT"
```

Keep `ATLAS_AUTH_MODE=databricks-app`, `ATLAS_HISTORY_BACKEND=lakebase` and
`command: ['python', '-m', 'server.run']`. Databricks supplies the host and app
credentials; the attached database supplies the PostgreSQL connection settings.
Never put user tokens, client secrets or a real .env file in the source upload.

Use models available in your workspace. The embedding model must match the model
and dimensions used to create the indexed vectors. Model service identifiers
(`system.ai.*`) and serving endpoint names (`databricks-*`) are different settings.

If your workspace only supports the existing serving endpoints, use
`DATABRICKS_MODEL_API=serving` and set `DATABRICKS_EMBEDDING_ENDPOINT` and
`DATABRICKS_ANSWER_ENDPOINT` to their existing names. The new combined workflow,
metadata extraction, reranking and citations still run. Model calls must accept
OpenAI-style embeddings/chat payloads; function calling is no longer required.
There is no automatic fallback to a different API or principal after an error.

## 2. Access and deployment

1. Open the existing Databricks App -> Settings -> User authorization.
2. For gateway mode, include `ai-gateway`, `genie` and `vector-search`; retain
   `model-serving` if using serving endpoints or other existing app resources.
   Keep the platform's standard identity scopes. Save and sign in/consent again
   if Databricks requests the additional scope.
3. Users need access to the configured Genie agent and its data, the contract
   index, and the configured models. OAuth scopes do not grant data permissions.
   Reranking must be available for the index/workspace. The query requests it;
   a Databricks reranker warning is recorded in the response metadata.
4. Keep the existing Lakebase database attachment and table grants. Do NOT rerun
   `setup/01_create_tables.sql` against your existing chat database.
5. Upload the full source and select the directory directly containing app.yaml
   as the app deployment source. The app service principal needs read access.
6. Deploy, open the app, and run the checks below.

## Request flow

The owner-checked conversation supplies up to six prior messages. Follow-ups are
classified and resolved using that history; subject metadata comes from context
and requested fields/topics come from the latest question. Self-contained questions
do not inherit another topic. There is no global CHAT_SESSIONS dictionary.

The backend schedules one Genie request and one document search concurrently.
The document branch extracts query metadata, adds it to the retrieval text, embeds
the query, requests HYBRID retrieval with the Databricks reranker and up to 20
chunks, then writes a cited document summary. One final model call combines the
structured results and document evidence into a single answer with internal [G#]/[D#]
IDs. These are validated, counted and removed from the displayed answer. Source
metadata retains which evidence was cited and how often it was cited.
Basic greetings are handled without querying data.

When enabled, business glossary enrichment runs after follow-up resolution. Its
terminology context accompanies the question to Genie and document search. Metadata
extraction still uses the question without glossary definitions, so glossary text
cannot introduce vendor/date restrictions. Glossary definitions are not sources.

The notebook's required `search_contracts` tool call is enforced directly in code,
rather than through an open-ended Deep Agents tool loop. The old source-selecting
router is not used by the app. A citation repair can repeat final synthesis once;
it does not call Genie or document retrieval again. This port does not import the
Deep Agents framework, IPython display code, or MLflow experiment setup/autologging.
Bounded provenance and source status are persisted in atlas_tool_runs instead.

Genie, models and document search use the verified signed-in user's forwarded token.
Lakebase uses the app service principal; API ownership checks protect each user's
chats. Each request starts a fresh Genie conversation; the app's history resolves
follow-ups. Stop propagates to both branches and attempts remote Genie cancellation
when response/conversation IDs are known. The overall request budget remains 150s.

## Sources and failure behavior

New messages show a separate Sources list, matching the updated notebook:

- Genie: unique cited SQL queries whose result tables contain rows. Expand View SQL
  to see the query; no Genie chat link is shown. A zero in a COUNT result is a row,
  while a table with only headers is empty. SQL exceeding 4,000 characters is marked
  as an excerpt. Missing/failed SQL is never replaced with a fabricated query source.
- Documents: group cited passages by PDF and link, combine their known page ranges,
  and display the three most cited files. All cited references remain in history;
  the UI indicates when it shows only the top three. Ties preserve citation order.
- Known `volumePath` folder links are extended with the actual PDF filename from
  the index/citation. Existing file links stay intact. File access still depends on
  Databricks permissions; page labels do not imply automatic PDF page navigation.

The current retrieval uses the notebook's seven columns: chunk_id, document_title,
section_title, page_start, page_end, contextualized_text, citation. Optional file_name
and vendor_name fields are used when present, but are not required by this workflow.
Source links must be HTTPS on the configured workspace. Missing/unsafe links are
shown as text. No model reasoning is stored or displayed. Reload restores the new
source display from existing tool records, with no database migration. Older chats
retain their original inline citations. Unlike the notebook's text cleanup helper,
the app does not erase statements about failed sources or missing information.

An unavailable source is explicitly reported while the other can still answer.
Both sources failing returns an error; no results returns a no-evidence answer.
Metadata extraction failure falls back to the original question for fresh queries.
Follow-up interpretation failure stops the request instead of selecting a guessed
contract. Unknown citations are rejected; a failed repair produces an error.
Citation-ID validation verifies membership in retrieved evidence, not semantic
support of every sentence. Check important answers against their source.

## What remains outside the app

- Document Parsing and Contextual Chunking stays a Databricks ingestion/sync job.
  Its triggered index needs to be synced after document updates.
- The separate Query Metadata Extraction with ai_extract notebook is not invoked.
  This release uses the LLM extractor from deep_agent_v1, including follow-up
  handling. Metadata enriches query text; it is not a strict retrieval filter.
- Editing the original notebook does not automatically update this deployed code.
  Port changes to the app repository and redeploy.

## Optional business glossary

The notebook imports three separate assets that were not included in the notebook:
`glossary_loader.py`, `enrichment.py`, and `business_glossary.json`. The adapter calls
their existing `load_glossary(path)` and `enrich_question(query, glossary)` functions;
it does not substitute invented definitions or a different matching algorithm.

1. Copy the complete shared business_glossary folder from the workspace into your
   app deployment source as `app_assets/business_glossary/`. Include any sibling
   modules needed by those two Python files, and their dependencies in requirements.txt.
2. In your deployment's app.yaml, enable the commented setting:

   ```yaml
   - name: ATLAS_GLOSSARY_DIR
     value: app_assets/business_glossary
   ```

3. Upload the full app source and redeploy. A workspace notebook path is not
   automatically an application-local directory; the files must be packaged with
   the app. The private glossary folder is gitignored, so do not rely on a public
   GitHub checkout to supply your company's glossary.
4. Successful enrichment records `glossary_status=completed` and matched terms in
   the response metadata. Unconfigured enrichment is `disabled`; no matches leaves
   the question unchanged; import or enrichment failures are `unavailable` and
   fall back to the question with a safe log message. Redeploy after changing assets.

The actual shared files were not supplied for local verification. Automated tests
exercise the adapter with synthetic modules; enable and test your real files after
packaging them. Existing Genie/model/index/Lakebase settings do not need changing.

## Verify after deployment

1. Ask a structured contract count and compare with the selected Genie agent.
2. Ask for a clause in a known indexed document. Open its PDF link under Sources.
3. Ask a question needing both counts/status and clause text. Check the SQL and
   PDF sources, and that contradictory dates are described rather than combined.
4. Ask a follow-up such as "Also the end date?"; then ask a fresh question about a
   different vendor. Confirm the subject and requested fields are correct.
5. Ask for absent information; verify no values/dates are invented.
6. Reload, check saved references/feedback/notes, and sign in as a second user to
   confirm chat isolation. Stop a request and verify a new message can be sent.

Local automated tests use synthetic HTTP responses. They cannot establish live
Azure permissions, model quality, reranker availability or index freshness.

## If a response fails after adding scopes

Confirm the saved scopes on the existing app's Authorization page. To test with a
fresh browser session, open Edge InPrivate inside the approved company network,
sign in to the workspace, then open the app and approve any access prompt. A missing
prompt alone does not prove which scopes the forwarded token contains. Adding a
scope does not grant the user permission to the configured model, index or Genie.

The chat now keeps a safe error naming the failing API and HTTP status. App logs
also identify its scope and configuration key, for example:

```text
Databricks request failed: operation=AI Gateway chat model; HTTP=403; scope=ai-gateway; setting=DATABRICKS_AGENT_MODEL
```

Check the named service: 401 indicates authentication, 403 denied access (scope,
consent or resource permissions), 404 an unavailable resource/API or incorrect
configuration, and 429 throttling. Do not switch to an app principal to bypass a
user's denial. The diagnostic does not print credentials, provider bodies, prompts
or resource values. An HTTP 200 for `/messages` only means the response stream
opened; its final `error` or `done` event determines the outcome. Re-upload and
redeploy this release to receive these diagnostics; no database change is needed.

References:
- [Genie response API](https://docs.databricks.com/api/genie/v1/agent-mode-create-response)
- [Vector index query and reranker](https://docs.databricks.com/api/vector-search/v1/query-vector-index)
- [App authentication](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/auth)
- [Query embedding models](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/model-serving/query-embedding-models)
