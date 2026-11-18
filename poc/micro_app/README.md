# Koantek Micro App POC

## Result — updated 17 November 2026

**Python + FastAPI + React can run on the Micro App runtime in this Koantek workspace.**
The deployed POC uses real Bike Store Genie, project-document retrieval and AI Gateway,
with the signed-in user's Databricks identity. An AppKit/Node rewrite was **not required**
for the deployment we tested.

**This is a session-only chat POC, not a complete migration of the production AIA app.**
The user approved this narrower scope after Lakebase attachment was rejected. Refreshing
the page clears its chat. Nothing is silently saved to local disk, localStorage, or the
old Lakebase chat database.

- [Open POC](https://aia-micro-poc-7474654589961519.aws.databricksapps.com)
- [Koantek app overview](https://dbc-f2d0e557-3d47.cloud.databricks.com/apps-v2/app/aia-micro-poc/overview)
- App: `aia-micro-poc`; App Space: `demo`; API-reported compute: `LIQUID`.
- Git branch: `poc/micro-app`; production changes merged through `99145ac` (Genie tables and charts).
- Use Koantek Databricks sign-in. Access is authenticated; an anonymous API request returned HTTP 401.

## What the live POC does

```mermaid
flowchart LR
    U[Signed-in browser] --> A[Databricks app ingress]
    A --> R[React session-only chat]
    R --> F[FastAPI in Micro App]
    F --> Q[Notebook follow-up understanding]
    Q --> G[Notebook query_genie function]
    Q --> P[POC project retrieval adapter]
    G --> GS[Bike Store Genie]
    P --> VS[Project Vector Search index]
    GS --> M[AI Gateway answer with source IDs]
    VS --> M
    M --> F
    F --> R
```

`web.py` verifies the forwarded user token against the Koantek workspace on each API
request. It sends that same user token to the agent; there is no app-owner fallback.
The browser sends up to six prior messages as context. The notebook's `understand_query()`
resolves a follow-up to its subject. A new chat has an empty history.

The POC's `KoantekPocAgent` directly calls the Python export's `query_genie()`; it does
not run a notebook job or call a notebook URL. The POC has a separate project-record
adapter because Koantek's index has `pk` and `full_text`, while AIA's contract workflow
expects contract chunks and page metadata. This difference is about the available data,
not a Micro App requirement. The AIA `contract_assistant()` workflow remains the default
in the production entry point.

SQL is returned from Genie and shown through the existing React source renderer.
Project references use retrieved record IDs and a link to the real index. Project
records have no verified PDF/page locations, so the POC does not invent them. At most
five project records are retrieved; the answer explicitly discloses that the result is
not a complete inventory. Source IDs are checked against retrieved evidence; this does
not prove every generated sentence is correct.

The current release streams actual workflow milestones to React: queued, understanding,
searching, composing and preparing sources. The shared thinking component animates and
changes its wording while each stage runs. A Stop button aborts the browser request and
signals cancellation to the backend; an already-running provider call may still finish
before its worker is released. The answer arrives as one completed response, not token
by token. Only references marked as cited are shown in the collapsible **Sources** section;
there is no separate "Retrieved references" section.

## Verification

The first full live deployment passed these authenticated API checks. Timings are single
observations, not a benchmark or a cold-start SLA:

| Check | Result | App processing time |
|---|---|---:|
| Distinct bike-category count | 7; Genie selected; SQL source returned | 19.74 s |
| Project time period | Project retrieval selected; document source returned | 4.64 s |
| Project follow-up | Previous subject retained; document source returned | 5.46 s |
| Mixed bike + project question | Both tools; separate SQL and document references | 15.21 s |
| Auth and frontend assets | Verified identity; HTML/JS HTTP 200; anonymous HTTP 401 | — |

See `live-results.json` for sanitized metrics. Raw answers, retrieved text, SQL contents,
credentials and private chat history are not included in that file.

The final `session-v2` deployment (`01f1e1e917d0152dac11296b479ea1d8`) also passed a
live mixed-question check: HTTP 200, category count 7, both source types, no failed tools
and an explicit project-retrieval limit. App processing took 14.05 seconds. Sanitized
evidence is in `final-verification.json`.

### Streaming release: session-v3

Deployment `01f1e246d81c1fb19b2918ec9a6dba99` succeeded and switched traffic on
17 November 2026 at 05:25 UTC (16 November in Pacific time). Source snapshot:
`/Workspace/Users/badal.tomar@koantek.com/aia-micro-poc/session-v3`.

The new live streaming tests all passed:

| Scenario | Verified result | App processing | Client wall time |
|---|---|---:|---:|
| Bike category count | 7, one cited Genie SQL source | 15.95 s | 18.06 s |
| Edward Jones period | Project retrieval, cited document record | 5.25 s | 7.60 s |
| Project follow-up | Previous subject retained, cited document record | 18.60 s | 20.74 s |
| Mixed bike/project question | Both tools, one SQL and five document sources | 13.82 s | 15.88 s |

All four delivered the five progress stages in order, before the final response. For
example, the mixed request delivered queued at 2.05 s, understanding at 2.11 s,
searching at 3.90 s, composing at 12.60 s and sources at 15.86 s. This verifies progress
was delivered incrementally through the deployed ingress, rather than buffered until
completion. Timings are single observations, not a performance benchmark.

Sanitized evidence is in `stream-results.json`. It also verifies authenticated identity,
anonymous API rejection (401), and successful React HTML/bundle delivery (200).

### Previous live release: session-v4 — browser verification

Deployment `01f1e2648bf3131bb0799e25012380a8` switched traffic successfully at
08:58:17 UTC on 17 November 2026. Its source is
`/Workspace/Users/badal.tomar@koantek.com/aia-micro-poc/session-v4`.

After the user completed sign-in and explicitly approved the App Space permissions,
browser testing exposed a React crash on the first question. The auto-scroll effect
implicitly returned the scrolling method's result; React treated it as an effect
cleanup function and crashed on the next update. A block-bodied effect now performs
the scroll without returning that value. TypeScript checking and the POC production
build passed, and the crash did not recur in three live browser questions.

| Browser check | Observed result |
|---|---|
| Identity | Badal Tomar and the initial B displayed |
| Progress | Getting started changed to Putting the answer together; the orbit/dots indicator and Stop control rendered |
| Bike count | 7; Sources expanded and View SQL exposed the actual distinct-count query; 12.5 s shown |
| Document period | Answer returned; Sources expanded to the Edward Jones project-record link; 6.3 s shown |
| Mixed question | Both domains answered; six cited references, with SQL and grouped document links; 13.8 s shown |
| Source wording | Only Sources was shown; no Retrieved references section |

The document link points to Koantek's project index, not a PDF: this dataset provides
project records rather than AIA contract files. The first browser navigation after
authorization returned HTTP 502; a normal reload loaded the running app. The cause of
that transient 502 is not established. Visual testing proves the displayed states and
source controls; it does not measure animation frame rate or prove a production SLA.

The final screenshot-capture tool timed out after these checks. Earlier SQL/document
and thinking screenshots were saved locally and are excluded from Git. Only sanitized
browser outcomes are committed in `browser-verification.json`.

The POC branch also includes the later `fb006af` notebook tracing metadata change from
`main`. It does not change this live POC's execution: the Koantek adapter does not call
the contract `embed_query()` / `generate_answer()` functions, and MLflow is disabled.
That production notebook update is verified separately by 31 targeted backend tests.

### Current live release: session-v5 — Genie result data and measured wake-up

Deployment `01f1e31350d21bca947452b619bed8ea` switched traffic successfully at
05:48:40 UTC on 18 November 2026 (17 November in Pacific time). Its source is
`/Workspace/Users/badal.tomar@koantek.com/aia-micro-poc/session-v5`.

The POC now passes captured Genie rows through the completed chat event to the shared
React table/bar/pie renderer. Only tables tied to cited SQL sources are included.
The notebook export is unchanged by this POC integration. Numeric values come from
Genie results; the chart is not reconstructed from generated prose. Incomplete or
unsuitable results remain tables instead of misleading charts.

All six authenticated live API cases passed:

| Scenario | Verified result | App processing | Client wall time |
|---|---|---:|---:|
| Bike category count | 7; one result row and cited SQL | 20.16 s | 23.21 s |
| Project period | One cited document record | 5.38 s | 8.64 s |
| Project follow-up | Subject retained; cited document record | 5.46 s | 7.34 s |
| Mixed question | Both tools; SQL and five document references | 11.65 s | 14.41 s |
| Products by category | Seven rows, numeric counts, distinct labels and cited SQL; suitable for charts | 11.72 s | 13.73 s |
| Greeting | No retrieval tools or sources; queued/understanding only | 0.42 s | 2.46 s |

Retrieval cases streamed all five progress stages in order. Identity verification,
anonymous rejection (401), and HTML/JavaScript delivery (200) passed again. These are
single observations, not performance guarantees. Sanitized evidence is in
`session-v5-verification.json`; raw answers, SQL and individual row values are omitted.

Before this deployment, `wake_probe.py` measured the existing app waking from
`STOPPED / App scaled to zero` without an explicit start command. Authenticated
`/api/me` returned 202, then transient 502 responses, then 200 after **30.33 seconds**.
`wake-verification.json` records that single cold-start observation. It is not an SLA
and does not establish whether every request will be retried automatically by a client.

For this update, 57 targeted backend tests and 17 frontend tests passed; the POC
TypeScript check and Vite build passed. The API verifies real chart input, while the
shared renderer tests cover table/bar/pie behavior. **Session-v5 browser interaction
checks passed after Koantek sign-in on 17 November (Pacific time).**

| Browser check | Observed result |
|---|---|
| Identity | Signed-in user's name and initial displayed |
| Table | Seven category/count rows; 1–7 of 7 shown; response processing 14.9 s |
| Bar view | Switching from Table displayed labeled horizontal bars with counts |
| Pie view | Switching to Pie displayed a donut, total, seven categories and percentages |
| Sources | One source expanded; View SQL exposed the actual aggregation query |
| Stop | Clicking Stop on a new request displayed Response stopped and restored input controls |
| New chat | Cleared the conversation and the stopped-response message |
| Recovery | A fresh greeting returned successfully afterward; 0.7 s app processing |

Sanitized observations are saved in `session-v5-browser-verification.json`. The chart
screenshot is retained locally rather than committed with business values or SQL.
The Stop check verifies browser cancellation and recovery; it does not establish that
an already-running Genie/model request stops executing or stops incurring usage.

Additional checks:

- Minimal Python/FastAPI deployment succeeded; runtime reported Python 3.11.17.
- Runtime probe received a forwarded user token and injected app credentials (only
  presence booleans were inspected).
- The initial diagnostic probe streamed responses about one second apart; session-v3
  additionally verifies real chat workflow progress, as described above.
- The Micro App automatically entered `STOPPED / App scaled to zero` while idle. An
  authenticated request returned an HTTP 202 HTML startup page; a later request returned
  HTTP 200 without an explicit `apps start` command. Automatic wake-up is verified, but
  exact cold-start latency was not measured at that time. A later continuously polled
  check measured 30.33 seconds, as recorded for session-v5 above.
- 174 existing backend tests and 8 POC adapter tests passed; the POC TypeScript/Vite build passed.
- For session-v3, 39 targeted backend tests and all 31 frontend tests passed. These cover
  the new endpoint, streamed parsing, source metadata, latest notebook adapter and direct
  calls. POC TypeScript checking and Vite build also passed.
- A separate offline probe restarted the existing API in a new Python process and verified
  history, sources, feedback, bookmarks, notes, follow-up context and owner checks. It used
  synthetic identities and disposable SQLite. **That is not a live Lakebase or SSO test.**

Browser verification is complete for the scenarios above. Two real users, load
tests, MLflow ingestion and full production-workflow parity
remain unverified. Backend cancellation is covered by the existing automated tests.

## Lakebase limitation observed here

The POC created an empty database `aia_micro_poc` under the existing Koantek project
`atlas-chat-badal`, branch `production`. It did not create a new compute endpoint, copy
history, create chat tables or modify the existing `databricks_postgres` tables.

The attempted attachment failed:

1. Legacy `apps update` was rejected for an app inside an App Space; the platform required
   `apps create-update` with a field mask.
2. The correct update API rejected the database resource:
   `Apps in space 'demo' cannot declare a resource of this type on the app. Allowed resource types: [].`
3. Creating a separate resource-bearing App Space was also rejected:
   `Space 'aia-micro-poc' has no principal to grant shared resources to, so resources and data cannot be configured for it.`

No direct grants, static secrets or alternate credentials were used to bypass this
restriction. This is evidence about **this workspace's present App Space capabilities**,
not a claim that Lakebase is universally unsupported by Micro Apps. Confirm the supported
resource setup with the workspace administrator/Databricks before migrating durable chat
history. Request payloads are retained here for that review.

The project search index was queryable but reported `ONLINE_PIPELINE_FAILED` for its last
refresh. Retrieval worked; data freshness was not established. That is a source-index
maintenance issue, separate from Micro App hosting.

## Advantages, disadvantages and required changes

| Area | Benefit | Trade-off / change for our app |
|---|---|---|
| Idle compute | Scale-to-zero was observed | Cold starts; memory and local files cannot be durable history |
| Existing stack | Python/FastAPI and the React build deployed successfully | Validate the full AIA workflow and resources before migration; this POC uses a different data adapter |
| Authentication | User-token forwarding and workspace verification work | App Space governs scopes; API access still depends on each user's data permissions |
| Governance | App Space provides a common access boundary | Resource setup is less independent; our Lakebase attachment is currently blocked |
| Capacity | Managed on-demand runtime | Documented maximum is one instance; our notebook worker limit is two concurrent calls, with no load/SLA proof |
| Network | Workspace calls worked | No general public internet egress; package installs use managed proxies; external integrations need separate validation |
| Operations | No VM/container management for us | Beta limitations, fewer diagnostics; HTTP access logs are unavailable |
| Cost | Idle runtime can stop consuming active compute | Current Beta pricing can change; model, Genie warehouse, search and Lakebase services must be budgeted separately |

The scaling, network and Beta limitations above follow the
[Databricks runtime documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie-app-builder).
Identity and shared-resource governance are described in
[App Spaces](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/app-spaces).
AppKit offers a Node/React framework, but that does not imply our tested Python deployment
needed to use it: [AppKit architecture](https://developers.databricks.com/docs/appkit/v0/architecture).

If we later adopt AppKit, do not expose chat tables through its default generated CRUD.
The database plugin does not implement per-user row authorization; retain custom owner
checks: [Database plugin](https://developers.databricks.com/docs/appkit/v0/plugins/database).

For a full migration:

1. Resolve supported Lakebase resource attachment in the target App Space.
2. Configure target-workspace Genie/index/model IDs; retain user authorization for data access.
3. Attach the correct history database and give the new app identity only required privileges.
   Decide explicitly whether production history is being reused or copied.
4. Use the production React/API entry point after those resources work. Preserve ownership,
   rename/delete, saved answers, notes, feedback and interrupted-generation recovery.
5. Validate glossary startup access and optional MLflow experiment authorization separately.
6. Test two real users, idle wake-up, long calls, concurrent requests and the complete AIA
   notebook workflow before moving production traffic.

**Recommendation:** keep the current standard Databricks App for the complete production
chat experience. Use this Micro App POC for experimentation while resource support and
production parity are resolved. The runtime proof is positive; the storage migration is incomplete.

## Code map

| File | Responsibility |
|---|---|
| `poc/micro_app/web.py` | Actual session-only POC server: verified identity, CSRF boundary, bounded context, JSON/NDJSON chat and static UI |
| `poc/micro_app/koantek_agent.py` | Koantek routing, direct notebook Genie/follow-up calls, project retrieval and validated source metadata |
| `poc/micro_app/ui/main.tsx`, `ui/poc.css` | POC chat screen, profile initial, thinking animation, session reset and copy |
| `poc/micro_app/ui/stream.ts` | Incremental NDJSON parsing, stage validation, completed answer/source delivery and interrupted-stream errors |
| `src/Thinking.tsx` | Shared animated progress labels, with a Koantek-specific search label |
| `src/Answer.tsx`, `src/GenieResult.tsx`, `src/genieData.ts`, `src/genie.css` | Shared Markdown, sources/SQL, result tables and eligible bar/pie charts |
| `server/genie_results.py` | Captures bounded Genie query rows and keeps only result tables tied to cited SQL |
| `server/notebook_bridge.py` | Extracted `call_chat()` hook so a POC subclass can reuse existing cancellation and worker limits |
| `server/app.py` | Optional server-selected notebook factory for future full-UI POC; production default stays unchanged |
| `session-app.yaml` | Manifest actually deployed for the approved session-only scope |
| `app.yaml`, `run.py` | Full Lakebase POC entry point, **not deployed or verified**; guarded against using the old database |
| `stage.py` | Allowlisted deployment packaging; excludes credentials, notebooks, tests and private data |
| `runtime_probe/` | First minimal Python/streaming diagnostic deployment |
| `restart_probe.py`, `test_poc.py`, `test_web.py`, `ui/stream.test.ts`, `live_probe.py` | Offline restart, adapter/API/parser tests and live streaming checks |
| `wake_probe.py` | Measures authenticated automatic wake-up without an explicit app-start command |
| `app-resource.json`, `lakebase-database.json`, `space.json` | Resource requests and attempted configuration for the Lakebase investigation |

This branch includes production code through `99145ac`, including updates to the
existing `server/deep_agent_v1.py`. The later AIA help-panel commit `f6dc9a5` is on
`main`; it is not part of this standalone POC screen. The POC uses its own session manifest and
entry point; it does not deploy the production React screen or change the Azure AIA app.
Do not copy `session-app.yaml` into the AIA production deployment.

## Reproduce this POC

From the repository root, using an environment with the project requirements installed:

```powershell
npx tsc -p poc/micro_app/tsconfig.json
npx vite build --config poc/micro_app/vite.config.ts
python -m pytest poc/micro_app/test_poc.py poc/micro_app/test_web.py server/test_latest_notebook.py server/test_direct_notebook.py -q
npm test
python poc/micro_app/restart_probe.py
python poc/micro_app/stage.py C:\path\to\a-new-poc-bundle
```

`stage.py` refuses to overwrite an existing directory. Upload that bundle to a new
workspace release folder. If the Micro App is scaled down, start it and wait for
`ACTIVE` before deploying the snapshot:

```powershell
databricks workspace import-dir C:\path\to\a-new-poc-bundle /Workspace/Users/YOUR_USER/aia-micro-poc/RELEASE -p genie-react-workspace
databricks apps start aia-micro-poc -p genie-react-workspace
databricks apps deploy aia-micro-poc --source-code-path /Workspace/Users/YOUR_USER/aia-micro-poc/RELEASE -p genie-react-workspace
python poc/micro_app/live_probe.py --stream --visualizations --output C:\path\to\sanitized-results.json
python poc/micro_app/wake_probe.py --output C:\path\to\wake-results.json
```

This setup uses no copied PAT or service-principal secret. Sign in with Databricks CLI;
set `DATABRICKS_CLI_PATH` only if the installed CLI is not on PATH. Keep raw deployment
logs and business records out of Git. The prepared Git branch is separate from `main`.
