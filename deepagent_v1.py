RAG_PROMPT = """You are a contract assistant. Answer the user's question using ONLY the provided contract context.
- If the context does not contain the answer, say you could not find it in the contracts.
- Each context passage starts with a source ID such as [D1]. Right after every fact, add the ID of the single passage that states it most directly, e.g. [D2] (at most 2 IDs; if several passages say the same, cite one).
- Refer to contracts by a short natural name (e.g. 'the MSCI order form TOF_00359608.0'), not by file names.
- Be concise and factual."""

from databricks.vector_search.reranker import DatabricksReranker

RAG_TOP_K = 20                                              # chunks passed to the LLM for the answer
# Databricks reranker re-scores the hybrid (vector + keyword) candidates on these columns
RERANK_COLUMNS = ["contextualized_text", "document_title", "section_title"]
RERANKER = DatabricksReranker(columns_to_rerank=RERANK_COLUMNS)

@mlflow.trace(name="embed_query", span_type=SpanType.EMBEDDING, attributes={"model": EMBEDDING_MODEL})
def embed_query(query: str) -> list[float]:
    return oai.embeddings.create(model=EMBEDDING_MODEL, input=[query]).data[0].embedding

def retrieve(query: str, k: int = RAG_TOP_K, rerank: bool = True) -> list[dict]:
    """Hybrid (vector + keyword) search over the contract chunk index, reranked, top k chunks."""
    with mlflow.start_span(name="vector_search_retrieve", span_type=SpanType.RETRIEVER) as span:
        span.set_inputs({"query": query, "k": k, "index": VS_INDEX, "query_type": "HYBRID",
                         "reranker": RERANK_COLUMNS if rerank else None})
        vec = embed_query(query)
        res = vs_index.similarity_search(query_text=query, query_vector=vec, columns=RAG_COLUMNS,
                                         num_results=k, query_type="HYBRID",
                                         reranker=RERANKER if rerank else None, disable_notice=True)
        cols = [c["name"] for c in res["manifest"]["columns"]]
        rows = [dict(zip(cols, row)) for row in res.get("result", {}).get("data_array", [])]
        # Document format so the MLflow UI renders retrieved chunks
        span.set_outputs([{"id": r.get("chunk_id"), "page_content": r.get("contextualized_text"),
                           "metadata": {c: v for c, v in r.items() if c != "contextualized_text"}} for r in rows])
    return rows

@mlflow.trace(name="rag_llm_answer", span_type=SpanType.CHAT_MODEL, attributes={"model": LLM_MODEL})
def generate_answer(messages: list[dict]) -> str:
    resp = oai.chat.completions.create(model=LLM_MODEL, temperature=0.1, max_tokens=1200, messages=messages,
                                       extra_body={"reasoning_effort": REASONING_EFFORT})
    return resp.choices[0].message.content

CITATION_RE = re.compile(r"^\[(.*?)\]\((.*)\)$", re.DOTALL)
SECTION_RE = re.compile(r"^((?:\d+(?:\.\d+)*\.?\s+)?[^.:;\n]{1,80})")

def _short_doc(name: str) -> str:
    """'MSCI - Schedule-TOF_00359608.0 - signed.pdf' -> 'MSCI - Schedule-TOF_00359608.0'"""
    name = re.sub(r"\.pdf$", "", (name or "").strip(), flags=re.IGNORECASE)
    name = re.sub(r"(\s*-\s*signed)+$", "", name, flags=re.IGNORECASE)
    return name.strip(" -_")

def _short_section(section: str) -> str:
    """'4.6 Coterminous Order Form. This Order Form will ...' -> '4.6 Coterminous Order Form'"""
    s = " ".join((section or "").split())
    m = SECTION_RE.match(s)
    s = (m.group(1) if m else s).strip()
    return s if len(s) <= 60 else s[:57].rsplit(" ", 1)[0] + "..."

from urllib.parse import quote

def _file_link(folder_link: str | None, doc: str) -> str | None:
    """Citation link points to the volume folder (volumePath=.../Input/); append the PDF name so it opens the file itself."""
    if not folder_link:
        return None
    return folder_link + quote(doc, safe="") if folder_link.endswith("%2F") else folder_link

@mlflow.trace(name="rag_query", span_type=SpanType.CHAIN)
def query_rag(query: str, k: int = RAG_TOP_K):
    """Retrieve the top k reranked contract chunks (hybrid search) and answer from them.
    Returns (text_for_agent, sources): sources = unique document citations (label + link)."""
    chunks = retrieve(query, k)
    if not chunks:
        return "No relevant contract document passages were retrieved.", []
    # One source ID per unique document + section + page, with a short, clean label
    sources, ids = [], {}
    for c in chunks:
        m = CITATION_RE.match(c.get("citation") or "")
        doc = m.group(1).split(" | ")[0] if m else c["document_title"]
        link = _file_link(m.group(2) if m else None, doc.strip())
        label = f"{_short_doc(doc)}, {_short_section(c['section_title'])}, p. {c['page_start']}"
        if label not in ids:
            ids[label] = f"D{len(ids) + 1}"
            sources.append({"id": ids[label], "label": label, "link": link,
                            "document": doc.strip(), "page": c["page_start"]})
        c["_sid"] = ids[label]
    context = "\n\n---\n\n".join(f"[{c['_sid']}] {c['contextualized_text']}" for c in chunks)
    answer = generate_answer([{"role": "system", "content": RAG_PROMPT},
                              {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}])
    catalog = "\n".join(f"[{s['id']}] {s['label']}" for s in sources)
    return f"Document answer (IDs show the supporting passage):\n{answer}\n\nDocument source IDs:\n{catalog}", sources

print(f"RAG tool ready: query_rag() / retrieve() -> index {VS_INDEX} (top {RAG_TOP_K}, reranked)")
