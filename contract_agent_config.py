"""Shared non-secret defaults from the supplied contact_agent_config.py.

Canonical name matches the notebook import: contract_agent_config.
The app reads these defaults through server.config.Settings; app.yaml/env override
individual settings. No clients, credentials, environment writes or network calls
run on import. Databricks ingestion loads the same file alongside the repository.
"""
LLM_MODEL = "system.ai.gpt-oss-120b"

REASONING_EFFORT = "medium"

EMBEDDING_MODEL = "system.ai.gte-large-en"

AGENT_TEMPERATURE = 0.1

RAG_TEMPERATURE = 0.1

RAG_MAX_TOKENS = 1200

JSON_TEMPERATURE = 0

JSON_MAX_TOKENS = 500

GENIE_SPACE_ID = "01f1d81ddaa11ae6b540fe5ab726e28e"

GENIE_TIMEOUT_S = 300

USE_GENIE = True

USE_RAG = True

CATALOG = "dev_diamonddaas"

SCHEMA = "aia_contract_chatbot"

TABLES = {
    "parsed_document": f"{CATALOG}.{SCHEMA}.brz_parsed_document",
    "document_metadata": f"{CATALOG}.{SCHEMA}.document_ai_metadata",
    "document_chunk": f"{CATALOG}.{SCHEMA}.document_chunk",
    "contextualized_chunk": f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk",
    "chunk_embedding": f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk_embedding",   # source of the VS index
}

VS_ENDPOINT = "aia_contract_search"

VS_INDEX = f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk_index"

RAG_COLUMNS = ["chunk_id", "document_title", "section_title", "page_start", "page_end", "contextualized_text", "citation"]

RAG_TOP_K = 20

RAG_QUERY_TYPE = "HYBRID"

RERANK_COLUMNS = ["contextualized_text", "document_title", "section_title"]

APP_NAME, APP_VERSION = "contract_assistant", "deep_agent_v1"

GLOSSARY_DIR = "/Workspace/Users/samriddhi.mishra@aia.com/AIA_Contract_Koantek/Samridhhi/business_glossary"

GLOSSARY_FILE = f"{GLOSSARY_DIR}/business_glossary.json"

SOURCE_PATH = "/Volumes/dev_diamonddaas/raw/aia/AIAIMSG/MO_Contract_Mgt/Input/"

PIPELINE_EMBEDDING_ENDPOINT = "databricks-gte-large-en"

EMBEDDING_DIM = 1024

INDEX_COLUMNS = [
    "chunk_id", "file_path", "file_name", "chunk_index", "section_title", "page_start", "page_end",
    "document_title", "document_type", "contract_reference", "vendor_name", "aia_entity",
    "effective_date", "expiry_date", "chunk_text", "contextualized_text",
    "doc_uri", "source_uri", "source_url", "citation",
]
