"""One-time admin script: ingest KISNA_KNOWLEDGE_BASE into Chroma kisna_kb.

Does not wire retrieval into GeneralAgent — prompt injection is v1.
Run from kisna-chatbot/: python scripts/ingest_knowledge_base.py
"""

import os
import sys

os.environ.setdefault("ENV_MODE", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kisna_chatbot.database.chroma.utils import chunk_kb_text, kb_add_chunks
from kisna_chatbot.prompts.kisna_knowledge_base import KISNA_KNOWLEDGE_BASE

_SOURCE_FILE = "kisna_knowledge_base.py"


def main() -> None:
    chunks = chunk_kb_text(KISNA_KNOWLEDGE_BASE)
    if not chunks:
        print("No chunks generated from knowledge base.")
        sys.exit(1)

    ids = kb_add_chunks(chunks=chunks, source_file=_SOURCE_FILE, file_type="manual")
    print(f"Ingested {len(ids)} chunk(s) from {_SOURCE_FILE} into kisna_kb.")
    print("IDs:", ", ".join(ids))


if __name__ == "__main__":
    main()
