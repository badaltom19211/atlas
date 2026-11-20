
import os
from databricks.sdk import WorkspaceClient

# ======================================================================================
# 1. Credentials / workspace
# ======================================================================================
SECRET_SCOPE = None            # e.g. "aia_contract_chatbot"  -> token read from a secret instead of the user's auth
SECRET_KEY_TOKEN = None        # e.g. "databricks_token"

w = WorkspaceClient()
HOST = w.config.host.rstrip("/")

def _get_token() -> str:
    if SECRET_SCOPE and SECRET_KEY_TOKEN:
        return w.dbutils.secrets.get(scope=SECRET_SCOPE, key=SECRET_KEY_TOKEN)
    return w.config.authenticate()["Authorization"].split(" ", 1)[1]

TOKEN = _get_token()
WORKSPACE_ID = w.get_workspace_id()
USER = w.current_user.me().user_name

# Expose credentials to background threads (MLflow async trace export, widget callbacks)
os.environ["DATABRICKS_HOST"] = HOST
os.environ["DATABRICKS_TOKEN"] = TOKEN

# ======================================================================================
# 2. LLMs 
# ======================================================================================
GATEWAY_URL = f"{HOST}/ai-gateway/mlflow/v1"

LLM_MODEL = "system.ai.gpt-oss-120b"           # agent, RAG answer, metadata + query understanding
REASONING_EFFORT = "medium"                    # low | medium | high (medium = complete answers)
EMBEDDING_MODEL = "system.ai.gte-large-en"     # same model used to embed the chunks

AGENT_TEMPERATURE = 0.1                        # Deep Agent (orchestrator)
RAG_TEMPERATURE = 0.1                          # RAG answer generation
RAG_MAX_TOKENS = 1200
JSON_TEMPERATURE = 0                           # metadata extraction / query understanding (JSON output)
JSON_MAX_TOKENS = 500

# ======================================================================================
# 3. Genie (structured contract data)
# ======================================================================================
GENIE_SPACE_ID = "01f1d81ddaa11ae6b540fe5ab726e28e"   # "Contract Lifecycle Management"
GENIE_RESPONSES_URL = f"{HOST}/api/2.0/genie/agents/{GENIE_SPACE_ID}/responses"
GENIE_TIMEOUT_S = 300

# ======================================================================================
# 3b. Answer sources (on/off switches; can also be overridden per call with use_genie= / use_rag=)
#     USE_GENIE=False, USE_RAG=True  -> answers from contract documents (RAG) only, Genie never called
#     USE_GENIE=True,  USE_RAG=False -> answers from structured contract data (Genie) only
#     At least one must be True.
# ======================================================================================
USE_GENIE = True
USE_RAG = True

# ======================================================================================
# 4. Tables (Unity Catalog)
# ======================================================================================
CATALOG = "dev_diamonddaas"
SCHEMA = "aia_contract_chatbot"
TABLES = {
    "parsed_document": f"{CATALOG}.{SCHEMA}.brz_parsed_document",
    "document_metadata": f"{CATALOG}.{SCHEMA}.document_ai_metadata",
    "document_chunk": f"{CATALOG}.{SCHEMA}.document_chunk",
    "contextualized_chunk": f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk",
    "chunk_embedding": f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk_embedding",   # source of the VS index
}

# ======================================================================================
# 5. Vector Search (RAG over contract documents)
# ======================================================================================
VS_ENDPOINT = "aia_contract_search"
VS_INDEX = f"{CATALOG}.{SCHEMA}.ai_contextualized_chunk_index"
RAG_COLUMNS = ["chunk_id", "document_title", "section_title", "page_start", "page_end", "contextualized_text", "citation"]
RAG_TOP_K = 20                                 # chunks passed to the LLM for the answer
RAG_QUERY_TYPE = "HYBRID"
RERANK_COLUMNS = ["contextualized_text", "document_title", "section_title"]

# ======================================================================================
# 6. MLflow tracing
# ======================================================================================
MLFLOW_EXPERIMENT = f"/Users/{USER}/AIA_chatbot"
APP_NAME, APP_VERSION = "contract_assistant", "deep_agent_v1"

# ======================================================================================
# 7. Business glossary 
# ======================================================================================
GLOSSARY_DIR = "/Workspace/Users/samriddhi.mishra@aia.com/AIA_Contract_Koantek/Samridhhi/business_glossary"
GLOSSARY_FILE = f"{GLOSSARY_DIR}/business_glossary.json"

# ======================================================================================
# 8. Ingestion pipeline (parse -> metadata -> chunk -> embed -> index)
#    Used by Data_Ingestion_full_pipline / Parsing and Indexing Pipeline. Tables, VS endpoint and index come from
#    sections 4 and 5 above, so the pipeline writes exactly what the agent reads.
# ======================================================================================
SOURCE_PATH = "/Volumes/dev_diamonddaas/raw/aia/AIAIMSG/MO_Contract_Mgt/Input/"   # trailing slash required

PIPELINE_EMBEDDING_ENDPOINT = "databricks-gte-large-en"   # serving endpoint for ai_query (same model as EMBEDDING_MODEL)
EMBEDDING_DIM = 1024                                       # gte-large-en: 1024-dim, 8192-token context
INDEX_COLUMNS = [
    "chunk_id", "file_path", "file_name", "chunk_index", "section_title", "page_start", "page_end",
    "document_title", "document_type", "contract_reference", "vendor_name", "aia_entity",
    "effective_date", "expiry_date", "chunk_text", "contextualized_text",
    "doc_uri", "source_uri", "source_url", "citation",
]

DOC_LINK_BASE_URL = f"{HOST}/explore/data/volumes"         # one link per PDF (Catalog Explorer)
