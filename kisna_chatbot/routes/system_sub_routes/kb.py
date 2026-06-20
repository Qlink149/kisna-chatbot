import io

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from kisna_chatbot.database.chroma.utils import (
    chunk_kb_text,
    kb_add_chunks,
    kb_delete,
    kb_list,
    kb_search,
    kb_update,
)
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/kb", tags=["System - Knowledge Base"])

_SUPPORTED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text(content: bytes, content_type: str, filename: str) -> str:
    if content_type == "application/pdf" or filename.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if (
        content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or filename.endswith(".docx")
    ):
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)

    # plain text
    return content.decode("utf-8", errors="replace")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_kb(file: UploadFile):
    """Upload a PDF, DOCX, or TXT file — chunks it and stores embeddings in kisna_kb."""
    content_type = file.content_type or ""
    filename = file.filename or ""

    if not (
        content_type in _SUPPORTED_TYPES
        or filename.endswith((".pdf", ".docx", ".txt"))
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{content_type}'. Use PDF, DOCX, or TXT.",
        )

    try:
        content = await file.read()
        text = _extract_text(content, content_type, filename)
        if not text.strip():
            raise HTTPException(status_code=422, detail="Could not extract any text from the file.")

        chunks = chunk_kb_text(text)
        file_type = "pdf" if filename.endswith(".pdf") else ("docx" if filename.endswith(".docx") else "txt")
        ids = kb_add_chunks(chunks=chunks, source_file=filename, file_type=file_type)

        logger.info("KB file uploaded", extra={"source_file": filename, "chunks": len(ids)})
        return {"success": True, "source_file": filename, "chunks_added": len(ids), "ids": ids}

    except HTTPException:
        raise
    except Exception:
        logger.exception("KB upload failed", extra={"source_file": filename})
        raise HTTPException(status_code=500, detail="Failed to process and store file")


@router.get("/search")
def search_kb(
    q: str = Query(..., description="Search query"),
    n: int = Query(5, ge=1, le=20, description="Number of results to return"),
):
    """Semantic search over the knowledge base. Returns top-n matching chunks."""
    try:
        results = kb_search(query=q, n_results=n)
        return {"query": q, "n": n, "results": results}
    except Exception:
        logger.exception("KB search failed", extra={"query": q})
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("")
def list_kb(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all KB records with pagination."""
    try:
        return kb_list(limit=limit, offset=offset)
    except Exception:
        logger.exception("KB list failed")
        raise HTTPException(status_code=500, detail="Failed to fetch KB records")


class AddKBRecordRequest(BaseModel):
    text: str
    source_file: str = "manual"


@router.post("")
def add_kb_record(body: AddKBRecordRequest):
    """Manually add a single text record to the knowledge base."""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text cannot be empty")
    try:
        ids = kb_add_chunks(chunks=[body.text], source_file=body.source_file, file_type="manual")
        return {"success": True, "kb_id": ids[0]}
    except Exception:
        logger.exception("KB manual add failed")
        raise HTTPException(status_code=500, detail="Failed to add KB record")


class UpdateKBRequest(BaseModel):
    text: str


@router.put("/{kb_id}")
def update_kb(kb_id: str, body: UpdateKBRequest):
    """Replace the text for a specific KB chunk (re-embeds automatically)."""
    try:
        kb_update(kb_id=kb_id, text=body.text)
        return {"success": True, "kb_id": kb_id}
    except Exception:
        logger.exception("KB update failed", extra={"kb_id": kb_id})
        raise HTTPException(status_code=500, detail="Failed to update KB record")


@router.delete("/{kb_id}")
def delete_kb(kb_id: str):
    """Delete a specific KB chunk by ID."""
    try:
        kb_delete(kb_id=kb_id)
        return {"success": True, "kb_id": kb_id}
    except Exception:
        logger.exception("KB delete failed", extra={"kb_id": kb_id})
        raise HTTPException(status_code=500, detail="Failed to delete KB record")
