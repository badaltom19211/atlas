# Enable Genie alongside contract document search

Updated 2026-11-04. This release adds structured contract analytics to the
contract-document workflow. Lakebase tables, authentication, feedback and notes
stay in place. No SQL migration or notebook job is needed.

## Update the app source and configuration

Use the complete latest source, including server/genie.py and server/routed_agent.py.
Adding an environment variable to an older build does not add Genie support.

Add this entry under env in app.yaml, replacing the placeholder:

```yaml
  - name: DATABRICKS_GENIE_AGENT_ID
    value: "REPLACE_WITH_TARGET_GENIE_AGENT_ID"
```

Copy the 32-character ID after /genie/rooms/ and before ? in the Genie page URL.
Keep your existing DATABRICKS_CONTRACT_INDEX, DATABRICKS_EMBEDDING_ENDPOINT,
DATABRICKS_ANSWER_ENDPOINT and LAKEBASE_ENDPOINT values. The private handoff ZIP
already has the supplied resource values; public GitHub keeps placeholders.

The DATABRICKS_ANSWER_ENDPOINT now handles source selection as well as document
answers. It must support function calling (tools and tool_choice). No new model
or AI Gateway setting is needed for the supplied Llama 3.3 70B endpoint.

## Configure access and deploy

1. Open the existing app → Settings → User authorization. Add genie; retain
   vector-search, model-serving, and the platform's standard identity scopes.
2. Save. Users may need to sign in and consent again for the new scope.
3. Give intended users CAN RUN on the Genie Agent and access to its underlying
   data, as well as the existing contract index and model endpoints. Ensure the
   agent's configured warehouse credentials are valid. Genie can use embedded
   author credentials for compute; data access remains user-specific. The app
   calls all data/model APIs with each signed-in user's forwarded token.
4. Keep the Lakebase database resource and existing app role/table grants.
5. Upload the updated source to a workspace folder, ensure the app service
   principal can read it, then Deploy using that folder. Select the directory
   directly containing app.yaml, package.json and server/.

The public-access rejection shown previously is a separate network issue.
The Citrix browser still needs approved Private Link/DNS routing to the app URL.
Adding Genie does not resolve that network restriction.

## What happens per question

- Structured questions (counts, distributions, table relationships) go to Genie.
- Document questions (clauses, notice periods, obligations) go to contract search.
- Mixed questions go to both. Their answers have separate source labels.
- If one source fails, only the successful source's supported answer is shown,
  alongside an explicit statement that the other source is unavailable.
- If routing fails or all selected sources fail, the app returns a safe error;
  it does not substitute guessed data or silently switch sources.

The router uses up to six prior individual messages from the current user's chat
to form standalone questions. Each Genie call starts a fresh Genie conversation;
there is no shared Genie conversation state between users or chats. The Genie
conversation and response IDs are retained as metadata. Stop/timeout attempts to
cancel the remote response when those IDs are available; disconnect alone does
not cancel Genie, and cancellation may only take effect at the next agent boundary.

The router has a 30-second budget. Selected sources run concurrently with up to
100 seconds each within the existing 150-second app request budget. A slow source
is reported unavailable without discarding the other successful answer.

## Sources and history

Answers remain clean prose, with source labels on mixed answers. Internal source
IDs and raw tool metadata are not shown in the chat. The authenticated API returns
assistant.custom_outputs with document sources, route, per-source status and
Genie response/conversation IDs. SQL is retained when supplied in execute_sql
arguments, bounded to four queries of 2,000 characters. No reasoning is exposed.

Metadata is saved in the existing atlas_tool_runs table and returned on reload.
Document source usage remains model-reported; missing or invalid IDs are unknown,
not assumed to mean every retrieved document was used.

Omit or set DATABRICKS_GENIE_AGENT_ID to an empty value to retain contract-only
behavior. An unfilled REPLACE_WITH_ placeholder is rejected at startup.

## Test after deployment

1. Ask: "What is the monthly count of contracts started?" Verify against Genie.
2. Ask a document question naming a real indexed contract and clause.
3. Ask a mixed structured-data and document question. Check both source labels.
4. Ask a follow-up that depends on the previous question.
5. Reload and check history/feedback/notes; verify another user sees only their chats.

Offline tests use fixture model and Genie responses. Routing quality, actual
answers, permissions and the Azure resources must be verified after deployment.

References:
- [Genie Agent-mode response API](https://docs.databricks.com/api/genie/v1/agent-mode-create-response)
- [Genie cancellation API](https://docs.databricks.com/api/genie/v1/genie-cancel-response)
- [Serving function calling](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/model-serving/function-calling)
- [Apps private networking](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/networking)
