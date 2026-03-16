"""
RAG con ChromaDB — almacena y busca fragmentos de la guía nutricional.
Usa Gemini text-embedding-004 para embeddings.
"""
import logging
import os
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import CHROMA_PERSIST_DIR, RAG_TOP_K
from llm.llm_client import embed

logger = logging.getLogger(__name__)

COLLECTION_NAME = "nutrition_guide"


def _get_client() -> chromadb.ClientAPI:
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    return chromadb.PersistentClient(
        path=CHROMA_PERSIST_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _embed(texts: list[str]) -> list[list[float]]:
    """Genera embeddings usando Gemini text-embedding-004."""
    return embed(texts)


def is_populated() -> bool:
    """Verifica si ya hay documentos indexados."""
    try:
        client = _get_client()
        col = client.get_collection(COLLECTION_NAME)
        return col.count() > 0
    except Exception:
        return False


def get_count() -> int:
    """Retorna la cantidad de chunks indexados en ChromaDB."""
    try:
        client = _get_client()
        col = client.get_collection(COLLECTION_NAME)
        return col.count()
    except Exception:
        return 0


def ingest_chunks(chunks: list[str], metadatas: list[dict] = None):
    """Indexa chunks en ChromaDB con embeddings de Gemini."""
    client = _get_client()

    # Eliminar colección existente si hay
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    col = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        ids = [f"chunk_{i + j}" for j in range(len(batch))]
        metas = metadatas[i : i + batch_size] if metadatas else None
        embeddings = _embed(batch)
        col.add(documents=batch, embeddings=embeddings, ids=ids, metadatas=metas)

    logger.info(f"Ingesta completa: {col.count()} chunks con Gemini text-embedding-004")
    return col.count()


def index_user_context(chat_id: int, context_text: str) -> None:
    """Indexa el contexto del usuario en una colección separada."""
    collection_name = f"user_context_{chat_id}"
    client = _get_client()
    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Limpiar y re-indexar
    if col.count() > 0:
        col.delete(ids=col.get()["ids"])

    chunks = [context_text[i:i + 400]
              for i in range(0, len(context_text), 350)]

    embeddings = _embed(chunks)
    col.add(
        documents=chunks,
        embeddings=embeddings,
        ids=[f"ctx_{i}" for i in range(len(chunks))],
    )
    logger.info("Contexto indexado para chat_id %d: %d chunks", chat_id, len(chunks))


def query_user_context(chat_id: int, query: str) -> str:
    """Busca en el contexto personal del usuario."""
    try:
        collection_name = f"user_context_{chat_id}"
        client = _get_client()
        col = client.get_or_create_collection(name=collection_name)
        if col.count() == 0:
            return ""
        query_embedding = _embed([query])[0]
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=min(2, col.count()),
        )
        docs = results.get("documents", [[]])[0]
        return "\n".join(docs)
    except Exception:
        return ""


def retrieve(query: str, k: int = None) -> str:
    """
    Busca los fragmentos más relevantes para la query.
    Retorna string concatenado listo para insertar en el prompt.
    """
    k = k or RAG_TOP_K
    try:
        client = _get_client()
        col = client.get_collection(COLLECTION_NAME)
        query_embedding = _embed([query])[0]
        results = col.query(query_embeddings=[query_embedding], n_results=k)

        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        return "\n---\n".join(docs)
    except Exception:
        return ""
