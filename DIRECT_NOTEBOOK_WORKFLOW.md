# Direct exported-notebook workflow

The app imports `server/deep_agent_v1.py` and calls its `chat()` function inside
its existing Python backend process. The notebook does not have to be running.
No notebook URL, Databricks Job, subprocess, or `%run` is involved.

## Call path

```text
React message
  -> server/app.py (authenticate user; load owned conversation)
  -> server/notebook_bridge.py :: NotebookChatAgent.answer()
  -> asyncio.to_thread -> server/deep_agent_v1.py :: chat()
  -> _chat() (fresh/follow-up resolution using supplied history)
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
requires one `search_contracts` call for contract questions. There is no second
outer router. The notebook's prompts, metadata rules, follow-up interpretation,
Genie SSE parsing, reranking and source grouping are kept in the exported file.

## File responsibilities

| File | Responsibility |
| --- | --- |
| `server/deep_agent_v1.py` | Exported notebook workflow functions and prompts; public `chat()` entry point. |
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
