"""Knowledge-base text chunking helpers.

Vector/Chroma storage was removed; GeneralAgent injects the prompt KB directly.
``chunk_kb_text`` remains for offline/docs tooling that still wants to split KB copy.
"""


_KB_CHUNK_SIZE = 1000
_KB_CHUNK_OVERLAP = 150


def chunk_kb_text(
    text: str,
    *,
    chunk_size: int = _KB_CHUNK_SIZE,
    chunk_overlap: int = _KB_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into semantically clean chunks.
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
