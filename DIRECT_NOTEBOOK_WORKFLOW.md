# 17 November latest notebook integration

The workflow from `deep_agent_v1 (6).ipynb` is integrated in the existing
`server/deep_agent_v1.py`. The separate `server/app_scope.py` classifier is removed.
The bridge calls the notebook's `contract_assistant()` directly. Future business
rules belong in the developer's notebook; the app keeps authentication,
owned history, cancellation, tracing and UI result formatting.

- `rule_based_message_type()` recognizes whole-message greetings, thanks,
  goodbyes and help requests. These return the notebook's fixed replies with
  zero model calls and no Deep Agent, metadata extraction, Genie or RAG.
- Other messages use `understand_query()` for scope, follow-up resolution and
  glossary enrichment together. Successful classification uses one model call;
  the notebook retries classification once on errors or invalid output.
- `in_scope=False` returns `out_of_scope_result()` before the contract pipeline.
  A successfully classified unrelated question gets the notebook's exact
  contract-only reply and no data lookup.
- Contract questions enter `_chat()` with the precomputed understanding, then
  `ask()` and the Deep Agent. There is no second app classifier.
- `HII` then a valid contract question works in the same conversation. Non-contract
  turns remain visible in Lakebase history but do not replace contract context.
  Persisted `notebook_query` retains the resolved subject for subsequent follow-ups.
- Optional traces contain the notebook's root `contract_assistant` and
  `query_understanding` spans. Fixed replies have no retrieval spans, sources or
  search progress. There is no separate `app_scope` trace.

**Latest notebook correction:** after two classification failures or invalid outputs,
`understand_query()` returns `in_scope=False`, `message_type=unclassified` and
`classification_status=failed`. The notebook's fixed retry/rephrase reply is
returned with `status=error`; no contract agent, metadata extraction, Genie or RAG
is called. The root MLflow span and status tag are marked error. Authentication,
cancellation and sanitized provider errors remain handled by the app runtime.

The error reply, classification metadata and trace ID are persisted. The final
stream event delivers that reply with the saved message's error status, rather
than replacing it with a generic exception. Previous valid contract context is
preserved; the next valid question can still run normally. This also works with
MLflow tracing disabled.

**Remaining notebook limitation:** the prompt still treats uncertain classification
as in-scope ("If unsure, use true"). This is different from a failed classification;
the latest correction only stops failed/invalid classification.

Deploy these seven runtime files together:

- `server/deep_agent_v1.py`
- `server/agent_runtime.py`
- `server/notebook_bridge.py`
- `server/notebook_agent.py`
- `server/notebook_output.py`
- `server/app.py`
- `server/database.py`

When upgrading from before the wrapper removal, also use the current
`server/databricks_errors.py` and delete `server/app_scope.py` (no runtime import).

No app.yaml change, new scope, dependency or database migration is required.
Old wrapper metadata is read only for history compatibility. New answers store
`in_scope`, `message_type` and classification status in existing answer metadata.
Raw provider error bodies are not exposed; classification errors retain exception
type and HTTP status. Existing typed SQL/PDF references and validation remain.

After redeployment, test `HII`, a valid contract question, an unrelated question,
`Thanks!`, and a follow-up to the contract question. Automated fixture tests cover
failed/invalid classification, retry recovery, no downstream calls, tracing,
persisted failure metadata and follow-ups after an error. Live model classification
and permissions must still be verified in AIA.

## Follow-ups for the notebook developer

These are recommendations, not additional business-rule changes in this release:

1. **`QUERY_UNDERSTANDING_PROMPT`:** decide how to handle uncertain and mixed-topic
   messages; remove "If unsure, use true" if strict scope is required. The previous
   failure fallback is now fixed in notebook v6 and covered by app regression tests.
2. **`rule_based_message_type()`:** preserve Unicode text. Its current `[^a-z\s]`
   cleanup turns `HII, अनुबंध की समाप्ति कब है?` into `hii`, incorrectly discarding
   the contract question. Only match small talk when the entire original message
   is small talk; test Hindi/English mixed questions, punctuation and numbers.
3. **`_load_history()` / `_is_contract_turn()`:** persist and restore the resolved
   standalone question and intent fields. Do not depend on exact fixed-answer
   text to identify non-contract turns. The app already retains `notebook_query`
   and scope metadata; give the notebook the same history contract.
4. **`contract_assistant()` / `chat()`:** provide an importable entry point with
   explicit credentials/clients and owned history. Move installation, notebook
   setup, global credentials, global session memory and demo calls out of import
   execution. These remain app runtime adaptations until the export supports it.
5. **`render_citations()` / error handling:** validate unknown citation IDs and
   return structured SQL/PDF references; avoid returning raw provider errors.
   The app already retains its reference validation and sanitized error handling.

Replacing or editing the workspace notebook alone does not update a deployed app.
Synchronize its reviewed workflow into the app-compatible export and redeploy.

# 13 November workflow update

The app bridge now calls `contract_assistant()` in `server/deep_agent_v1.py`.
It wraps the existing explicit-token `chat()` boundary in one root MLflow span.
`understand_query()` combines follow-up classification, standalone rewriting and
glossary clarification in one LLM call. Follow-up metadata extraction still has
its own calls; this does not mean one model call for the entire answer.
The standalone question is persisted as notebook_query for the next turn.
Trace ID, latency and standalone question are stored with answer metadata.
Thumbs-up/down changes on owned answers also submit human feedback to MLflow
when a trace ID and configured tracing are present. Feedback remains saved in
Lakebase if MLflow submission fails; there is currently no retry queue.
Clearing a vote only clears Lakebase feedback; it does not delete prior MLflow
assessments. Notes stay private in Lakebase and are not sent as feedback rationale.
Existing typed SQL/PDF references are retained instead of parsing notebook HTML.
The global notebook credentials/session dictionary and demo calls remain excluded.
No new app.yaml values or database migration are required beyond the existing
optional MLFLOW_EXPERIMENT_ID. Deploy all changed backend files together.

# Direct exported-notebook workflow

The app imports `server/deep_agent_v1.py` and calls its `chat()` function inside
its existing Python backend process. The notebook does not have to be running.
No notebook URL, Databricks Job, subprocess, or `%run` is involved.

## Call path

```text
React message
  -> server/app.py (authenticate user; load owned conversation)
  -> server/notebook_bridge.py :: NotebookChatAgent.answer()
  -> asyncio.to_thread -> server/deep_agent_v1.py :: contract_assistant() -> chat()
  -> understand_query() (rules or model; scope + follow-up + glossary)
       -> non-contract: out_of_scope_result() -> fixed notebook reply
       -> contract: _chat(understanding=...) using supplied history
  -> ask() -> build_contract_agent()'s Deep Agent graph.invoke()
  -> search_contracts()
  -> search_genie_and_rag()
       -> query_genie()                     [parallel]
       -> metadata_aware_rag() -> query_rag()
            -> retrieve() -> embed_query() -> hybrid search + reranker
            -> generate_answer()
  -> merged answer -> render_citations()
  -> notebook_output.py :: format_result()
  -> React + Lakebase history/source metadata
```

The Deep Agent chooses tool calls according to the notebook's prompt. That prompt
requires one `search_contracts` call for contract questions. Notebook query
understanding checks scope; there is no app-only router. The notebook's prompts, metadata rules, follow-up interpretation,
Genie SSE parsing, reranking and source grouping are kept in the exported file.

## File responsibilities

| File | Responsibility |
| --- | --- |
| `server/deep_agent_v1.py` | Notebook workflow, scope rules, prompts and fixed replies; public `contract_assistant()` and `chat()` entry points. |
| `server/agent_runtime.py` | Per-request clients, token, cancellation and optional tracing context. |
| `server/notebook_bridge.py` | Async API adapter; direct function call in a thread so the web event loop stays responsive. |
| `server/notebook_output.py` | Normalize SQL/PDF references and bound response metadata for React/Lakebase. |
| `server/app.py` | Authentication, conversation ownership, stored history, streaming protocol and persistence. |
| `server/glossary_assets.py`, `server/glossary.py` | Load configured glossary assets at startup; call their existing enrichment function. |

`server/deep_agent.py` remains only for rollback with `ATLAS_AGENT_WORKFLOW=adapted`.
The default notebook mode does not call that older orchestrator.

## Entry-point contract

```python
from server.deep_agent_v1 import chat

result = chat(
    question,
    token=user_token,          # verified signed-in user's forwarded token
    history=previous_turns,    # owned, completed user/assistant messages
    settings=settings,
    user_id=user_id,
    session_id=f"{user_id}:{conversation_id}",
    glossary=glossary,         # optional loaded glossary adapter
    tracing=tracing,           # optional startup-configured MLflow client
    cancel=cancel_event,       # optional threading.Event
)
# result = {"answer": "...", "custom_outputs": {...}}
```

History excludes the new question. The notebook's follow-up algorithm uses the
last complete question/answer, not the full transcript. `notebook_query` preserves
the resolved subject for the next follow-up. New conversations have no prior turn.
Resetting a conversation means passing empty history; there is no global
`CHAT_SESSIONS` to clear.

## Authentication, isolation and cancellation

- User token, OpenAI client, search client, Deep Agent instance and failures belong
  to one call. A ContextVar makes that context available to the notebook helpers;
  the parallel search branches explicitly copy the current context.
- No user token is written into environment variables or assigned to a module
  global. No provider/user state is monkeypatched into the exported module.
- Genie, Vector Search, embeddings and chat inference use the signed-in user.
  Hosted mode fails if that token is missing; it does not fall back to the app SP.
- Lakebase and startup glossary downloads retain app service-principal auth.
  Chat ownership remains enforced by the API.
- Two calls run concurrently per backend process. Cancelling signals the running
  call; it stops at the next cancellation checkpoint. An in-flight synchronous
  SDK/network call cannot be forcibly killed. Its capacity slot stays held until
  it finishes, and the cancelled result is not saved as a successful answer.
  A hung SDK call may require restarting the app. This is different from killing
  a subprocess. OpenAI/Genie have network timeouts; search SDK retries are disabled.
- The API still sends progress events and then the completed answer; this is not
  token-by-token LLM streaming.

## Sources

Genie sources retain the actual returned SQL, title and conversation link.
Document sources retain the retrieved document name, permitted workspace link
and known page. Unknown IDs are rejected before citation markers are removed.
React receives typed references, not notebook-generated HTML. Its existing
collapsible Sources UI shows cited SQL and up to three grouped PDFs.
A failed source produces an explicit partial-answer warning. Both sources failing
rejects the answer. HTTP/provider bodies are not sent to the model or browser.
Citation validation checks IDs; it does not prove that every sentence is true.

## Deploy this update

Upload the complete updated project on this first upgrade, including the new
Python files and `requirements.txt`, and redeploy. Keep your target workspace
values in `app.yaml`. Set:

```yaml
- name: ATLAS_AGENT_WORKFLOW
  value: notebook
- name: DATABRICKS_MODEL_API
  value: gateway
```

Keep Genie ID, contract index, models, RAG top-k, auth mode and Lakebase settings.
No new database tables or migration are required. Keep existing `genie`,
`vector-search`, `ai-gateway` user scopes, consent and underlying resource access.
Keep either glossary workspace directory or packaged directory, if configured.

## Optional MLflow

No experiment ID means the exported workflow emits no MLflow spans and creates
no experiment. To enable tracing, attach an existing experiment as an app resource
with Can edit and key `experiment`, then set:

```yaml
- name: MLFLOW_EXPERIMENT_ID
  valueFrom: experiment
```

Tracing is configured once at app startup, using tracking URI `databricks` and
injected app OAuth credentials in hosted mode. Explicit notebook spans record
questions, answers, tool results and retrieved context. User tokens/runtime
objects are not trace inputs. Auto-instrumentation is not enabled by this code.
Trace permissions are controlled by the experiment/trace-storage permissions,
independently of chat history ownership. Each request has a separate trace ID.
`tracing=configured` does not confirm successful ingestion; verify a real trace
in the target experiment after deployment.

## Future notebook changes

The supplied `deepagentv11.ipynb` was a text export with Markdown/install cells and
Python. `server/deep_agent_v1.py` is its **app-compatible Python export**, not an
unchanged raw copy. One-time adaptations exclude `%pip`, `dbutils`, credential
initialization, default agent creation, global session memory and demo calls.
They replace shared globals with the request runtime and add the public contract.

For prompt/tool/metadata changes, update those functions in this file and replace
it in your app source folder, then redeploy. Keep the app-safe imports, runtime
access and public `chat()` signature/return shape. A raw export that reintroduces
notebook-only setup is not a drop-in replacement. If dependencies, function
signatures or result schema change, update the requirements/adapter too.
No change to the original notebook automatically updates a deployed app.
The notebook itself does not need to import or call this module for the app to work.

## Verification

Fixture tests cover fresh and follow-up questions, concurrent user isolation,
real Deep Agent graph/tool execution, source validation, partial failures,
cancellation capacity and API history round-trips. No live workspace is called.
After deploying, test structured SQL, a document clause, a follow-up, a new chat,
reload, and a second user. Check MLflow ingestion separately if enabled.
