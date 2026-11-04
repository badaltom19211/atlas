# Contract workflow package

Prepared 2026-11-03 from the Atlas source and the supplied ContractRAGAgent notebook.

The backend now uses explicit embedding, hybrid contract search and a chat answer
model. It no longer imports Deep Agents/LangChain or calls Genie/AI Gateway.
The app uses its existing authenticated request and Lakebase persistence path;
no separate MLflow deployment or new database schema is required.

Source metadata is preserved separately from the visible answer and survives
chat reloads. Missing/invalid source IDs remain unknown instead of marking all
retrieved sources used. This is model-reported attribution, not claim verification.

The repository copy has configuration placeholders. The Citrix handoff ZIP is
prepared separately with the notebook's resource values and the previously
provided Lakebase endpoint. It contains no credentials or existing chat history.
The original workspace deployment is not changed by this package.

Validation uses fixture model/search responses and an isolated test database.
A real query in the target Azure workspace is still required before claiming
successful deployment or live resource integration.

Validation on 2026-11-03: 54 backend tests and seven frontend tests passed.
The TypeScript check and production Vite build passed. Tests cover ordered
embedding/search/answer calls, source parsing, empty results, upstream failures,
six-message history, metadata persistence, user isolation and per-user credentials.
