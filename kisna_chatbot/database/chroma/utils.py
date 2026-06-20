import time
import uuid

from kisna_chatbot.constants import EMBEDDING_MODEL
from kisna_chatbot.utils.env_load import chroma_api, chroma_tenant, openai_api_key
from kisna_chatbot.utils.logger_config import logger

_chroma_client = None
_embedding_fn = None
_product_collection = None
_kb_collection = None

_KB_CHUNK_SIZE = 1000
_KB_CHUNK_OVERLAP = 150


def chunk_kb_text(
    text: str,
    *,
    chunk_size: int = _KB_CHUNK_SIZE,
    chunk_overlap: int = _KB_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into semantically clean chunks for kisna_kb ingestion.
    Snaps to sentence boundaries and overlaps chunks for cross-boundary context.
    """
    sentence_endings = {".", "?", "!", "\n"}
    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)

        if end < length:
            snap = end
            while snap < length and snap < end + 200:
                if text[snap] in sentence_endings:
                    end = snap + 1
                    break
                snap += 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        overlap_start = max(end - chunk_overlap, start + 1)
        while overlap_start < end and text[overlap_start - 1] not in sentence_endings:
            overlap_start += 1

        start = overlap_start if overlap_start < end else end

    return chunks


def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb

        _chroma_client = chromadb.CloudClient(
            tenant=chroma_tenant,
            database="Kisna_Chatbot",
            api_key=chroma_api,
        )
    return _chroma_client


def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is None:
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

        _embedding_fn = OpenAIEmbeddingFunction(
            api_key=openai_api_key,
            model_name=EMBEDDING_MODEL,
        )
    return _embedding_fn


def _get_product_collection():
    global _product_collection
    if _product_collection is None:
        _product_collection = _get_chroma_client().get_or_create_collection(
            name="product",
            embedding_function=_get_embedding_fn(),
        )
    return _product_collection


def _get_kb_collection():
    global _kb_collection
    if _kb_collection is None:
        _kb_collection = _get_chroma_client().get_or_create_collection(
            name="kisna_kb",
            embedding_function=_get_embedding_fn(),
        )
    return _kb_collection


def kb_add_chunks(chunks: list[str], source_file: str, file_type: str) -> list[str]:
    """Embed and store text chunks into kisna_kb. Returns the list of generated IDs."""
    try:
        ids = [f"{uuid.uuid4().hex[:12]}" for _ in chunks]
        metadatas = [
            {
                "source_file": source_file,
                "file_type": file_type,
                "chunk_index": i,
                "created_at": int(time.time()),
            }
            for i, _ in enumerate(chunks)
        ]
        _get_kb_collection().add(ids=ids, documents=chunks, metadatas=metadatas)
        logger.info(
            "KB chunks added",
            extra={"source_file": source_file, "count": len(ids)},
        )
        return ids
    except Exception as e:
        logger.error(
            "Failed to add KB chunks",
            extra={"source_file": source_file, "error": e},
        )
        raise


def kb_search(query: str, n_results: int = 5) -> list[dict]:
    """Semantic search over kisna_kb."""
    try:
        response = _get_kb_collection().query(query_texts=[query], n_results=n_results)
        results = []
        if response and response.get("ids"):
            for idx, kb_id in enumerate(response["ids"][0]):
                results.append(
                    {
                        "id": kb_id,
                        "text": response["documents"][0][idx],
                        "metadata": response["metadatas"][0][idx],
                        "distance": response["distances"][0][idx],
                    }
                )
        logger.info("KB search completed", extra={"query": query, "hits": len(results)})
        return results
    except Exception as e:
        logger.error("KB search failed", extra={"query": query, "error": e})
        raise


def kb_list(limit: int = 20, offset: int = 0) -> dict:
    """List KB records with pagination."""
    try:
        result = _get_kb_collection().get(
            limit=limit, offset=offset, include=["documents", "metadatas"]
        )
        records = [
            {"id": kb_id, "text": doc, "metadata": meta}
            for kb_id, doc, meta in zip(
                result["ids"], result["documents"], result["metadatas"]
            )
        ]
        total = _get_kb_collection().count()
        logger.info(
            "KB list fetched",
            extra={"total": total, "limit": limit, "offset": offset},
        )
        return {"total": total, "limit": limit, "offset": offset, "records": records}
    except Exception as e:
        logger.error("Failed to list KB records", extra={"error": e})
        raise


def kb_update(kb_id: str, text: str) -> None:
    """Replace the text for a specific KB chunk."""
    try:
        _get_kb_collection().update(ids=[kb_id], documents=[text])
        logger.info("KB record updated", extra={"kb_id": kb_id})
    except Exception as e:
        logger.error("Failed to update KB record", extra={"kb_id": kb_id, "error": e})
        raise


def kb_delete(kb_id: str) -> None:
    """Delete a specific KB chunk by ID."""
    try:
        _get_kb_collection().delete(ids=[kb_id])
        logger.info("KB record deleted", extra={"kb_id": kb_id})
    except Exception as e:
        logger.error("Failed to delete KB record", extra={"kb_id": kb_id, "error": e})
        raise


def generate_id() -> str:
    """Generate a short unique ID."""
    return f"{uuid.uuid4().hex[:8]}"


def add_product(product_id: str, description: str, brand_id: str, category: str):
    """Add a product description to the vector collection."""
    try:
        _get_product_collection().add(
            ids=[product_id],
            documents=[description],
            metadatas=[
                {
                    "brand_id": brand_id,
                    "category": category,
                    "product_id": product_id,
                }
            ],
        )
        logger.info(
            "Product added to vector DB",
            extra={"product_id": product_id, "brand_id": brand_id},
        )
    except Exception as e:
        logger.error(
            "Error adding product to vector DB",
            extra={"product_id": product_id, "error": e},
        )
        raise


def semantic_search(
    query: str,
    brand_ids: list | None = None,
    exclude_ids: list | None = None,
    n_results: int = 3,
):
    """Search products by semantic similarity."""
    try:
        where_clause = {"brand_id": {"$in": brand_ids}} if brand_ids else None
        response = _get_product_collection().query(
            query_texts=[query],
            where=where_clause,
            n_results=n_results,
        )
        product_ids = []
        if response and response.get("ids"):
            for pid in response["ids"][0]:
                if exclude_ids and pid in exclude_ids:
                    continue
                product_ids.append(pid)
        logger.info(
            "Semantic search completed",
            extra={"query": query, "brand_ids": brand_ids, "results": product_ids},
        )
        return product_ids
    except Exception as e:
        logger.error(
            "Error during semantic search",
            extra={"query": query, "brand_ids": brand_ids, "error": e},
        )
        raise


def delete_brand_products(brand_id: str):
    """Delete all product vectors for a brand."""
    try:
        _get_product_collection().delete(where={"brand_id": brand_id})
        logger.info("Deleted brand products from vector DB", extra={"brand_id": brand_id})
    except Exception as e:
        logger.error(
            "Error deleting brand products from vector DB",
            extra={"brand_id": brand_id, "error": e},
        )
        raise


def delete_product(product_id: str):
    """Delete a single product from vector DB."""
    try:
        _get_product_collection().delete(ids=[product_id])
        logger.info("Deleted product from vector DB", extra={"product_id": product_id})
    except Exception as e:
        logger.error(
            "Error deleting product from vector DB",
            extra={"product_id": product_id, "error": e},
        )
        raise
