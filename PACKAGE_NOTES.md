# Genie and contract workflow package

Updated 2026-11-04. The app now combines Genie structured-data answers with the
supplied contract-document RAG workflow. A single function call to the existing
answer model selects Genie, contract search, or both; no AI Gateway service or
Deep Agents/LangChain dependency is required.

Genie uses the documented Agent-mode Responses API. Requests use each signed-in
user's credentials. Up to six prior messages inform standalone question routing.
Each Genie request creates a fresh conversation, avoiding shared remote history.
Cancellation is attempted when a stopped or timed-out response has known IDs.

Mixed answers keep the sources separate and preserve the available source when
the other fails. Genie reasoning and raw provider errors are never shown.
Provenance is saved through the existing Lakebase tool records without a schema
migration. Internal metadata is returned separately from the visible answer.

Repository settings are placeholders. The private ZIP uses the supplied index,
model endpoint names, latest Genie ID and existing Lakebase resource name.
It contains no credentials or chat history. Workspace resources and hosted
deployments are not modified by packaging or publishing this source.

Validation on 2026-11-04: 83 backend tests and seven frontend tests passed.
TypeScript and production Vite build passed. Tests cover source selection,
mixed-source failures, no-answer failures, bounded context, Genie cancellation,
timeouts, metadata persistence, and user/credential isolation.

All model, search and Genie responses in these checks are fixtures. Actual
routing quality, permissions, Azure resource availability, and the reported
private-network access issue require verification in the target workspace.
