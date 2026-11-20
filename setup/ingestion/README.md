# Contract ingestion workflow

`Data_Ingestion_full_pipline.ipynb` packages the supplied notebook as a separate
Databricks Job. It is not imported or invoked by the web app. The chat backend
reads its resulting Vector Search index.

The repository root's `contract_agent_config.py` is the canonical, non-secret
configuration shared by this Job and `server/config.py`. The uploaded filename
was `contact_agent_config.py`; the canonical name matches both notebooks' import.
Notebook-global tokens, environment writes and automatic experiment creation are
excluded. The ingestion Job authenticates with its own `WorkspaceClient()`;
chat retrieval continues to use the signed-in user's token.

## Included workflow

PDF validation → content-hash deduplication → `ai_parse_document` → `ai_extract`
metadata → section-aware chunks → contextualization and validated links →
incremental embeddings → triggered Vector Search sync.

Configured output index:
`dev_diamonddaas.aia_contract_chatbot.ai_contextualized_chunk_index`

Configured endpoint: `aia_contract_search`. The source folder is the existing
`/Volumes/dev_diamonddaas/raw/aia/AIAIMSG/MO_Contract_Mgt/Input/`.

## Deploy and run separately

1. Import the repository into the target Databricks workspace, including the root
   `contract_agent_config.py` and this folder. Use compute that supports the
   supplied Spark SQL AI functions, Unity Catalog volumes and Vector Search SDK.
2. Confirm the five destination tables in `contract_agent_config.TABLES` exist
   with the developer's schemas. The attachment does not contain their DDL.
   The packaged notebook stops before writing if any table is missing. The
   embedding source table must already be configured for the Delta sync index.
3. Copy `dedup_config.example.json` to `dedup_config.json` and review the source
   folder/catalog/schema. It is an example, not a copy of the missing workspace
   dedup settings. Keep `file_extensions` as `["pdf"]` for this downstream
   pipeline. Keep the dedup source folder equal to `SOURCE_PATH`.
4. Create a notebook Job for `Data_Ingestion_full_pipline`. Set `config_dir` to
   the absolute workspace repository root and `config_path` to the reviewed
   dedup JSON. Configure **one concurrent run** because staging/output tables
   use shared names. The Job identity needs read access to the source volume,
   write access to the pipeline tables, and access to the AI functions/embedding
   endpoint and Vector Search endpoint/index.
5. Run the Job for a reviewed input set, inspect parsing/extraction errors and
   the sync summary, then verify the index is ready before switching the app.
6. Deploy the app with the same config. Remove old `DATABRICKS_CONTRACT_INDEX`
   overrides or set them to the new index; `app.yaml`/environment values override
   shared defaults. Existing Lakebase and MLflow resources remain separate.

## Changes made to the supplied notebook

- Outputs, execution counts and transient notebook metadata were removed.
- Config loading uses the explicit `config_dir`, avoiding a stale cached module.
- SDK authentication and workspace URL/ID are initialized in the Job, not on
  import of the shared configuration file.
- The dedup JSON path is configurable and defaults to this repository folder.
- A missing-table check runs before any pipeline mutations.
- Parsing, extraction, chunking, dedup rules and index-sync functions are retained.

## Limitations to give the notebook developer

- `files_to_remove` is only queued in `files_pending_removal`. Documents are
  **not deleted** from the downstream tables or index. `record_handoff()` clears
  their processed marker after queuing. A removal worker with completion tracking
  and index synchronization is still needed to stop stale documents appearing.
- The five pipeline table schemas and the team's actual `dedup_config.json`
  were not included. Existing schemas must match the positional inserts.
- Subfolder PDFs are rejected by the handoff. Put input PDFs directly in Input.
- `sync_vector_index()` prints when its wait expires instead of failing the Job.
  Before marking handoff complete, the developer should require confirmed sync
  or return a distinct pending status.
- `simulate_handoff` is not a dry run here: `DOWNSTREAM_FN` is already set, so
  the real pipeline branch executes. Do not use that option as a preview switch.
- Deletes followed by inserts are separate operations. Keep runs serialized;
  the developer should address transactional retries and stale-output cleanup.

Validation here covers Python syntax, configuration wiring and app regressions.
No live ingestion, table creation, data deletion or Vector Search sync was run.
