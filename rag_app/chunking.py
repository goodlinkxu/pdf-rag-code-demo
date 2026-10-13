from __future__ import annotations

import re
from typing import Any

from .document import join_pages
from .schemas import Chunk, PageRecord


def _token_count(tokenizer: Any, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=True, truncation=False, verbose=False)["input_ids"])


def _max_end(tokenizer: Any, text: str, start: int, hard_end: int, max_tokens: int) -> int:
    lo, hi, best = start + 1, hard_end, start + 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if _token_count(tokenizer, text[start:mid]) <= max_tokens:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def _overlap_start(tokenizer: Any, text: str, start: int, end: int, overlap: int) -> int:
    if overlap <= 0:
        return end
    lo, hi, best = start, end, end
    while lo <= hi:
        mid = (lo + hi) // 2
        count = _token_count(tokenizer, text[mid:end])
        if count <= overlap:
            best, hi = mid, mid - 1
        else:
            lo = mid + 1
    return best


def _section_for(text: str, start: int) -> str | None:
    prefix = text[:start]
    matches = list(re.finditer(r"(?m)^(\d+(?:\.\d+)*\s*[^\n]{1,24})$", prefix))
    return matches[-1].group(1).strip() if matches else None


def make_chunks(
    pages: list[PageRecord], tokenizer: Any, max_tokens: int = 400, overlap_tokens: int = 60
) -> list[Chunk]:
    text, page_ranges = join_pages(pages)
    if not text:
        raise ValueError("没有可切分文本")
    boundaries = [m.end() for m in re.finditer(r"[。！？；]\s*|\n\n+", text)]
    if not boundaries or boundaries[-1] != len(text):
        boundaries.append(len(text))
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        candidates = []
        for boundary in boundaries:
            if boundary <= start:
                continue
            if _token_count(tokenizer, text[start:boundary]) <= max_tokens:
                candidates.append(boundary)
            else:
                break
        next_boundary = next((b for b in boundaries if b > start), len(text))
        end = max(candidates) if candidates else _max_end(tokenizer, text, start, next_boundary, max_tokens)
        if end <= start:
            raise RuntimeError("切块未推进")
        chunk_text = text[start:end]
        pdf_pages = [p.pdf_page for a, b, p in page_ranges if start < b and end > a]
        printed_pages = [p.printed_page for a, b, p in page_ranges if start < b and end > a]
        chunks.append(Chunk(
            chunk_id=f"C{len(chunks)+1:04d}", text=chunk_text,
            pdf_pages=pdf_pages, printed_pages=printed_pages,
            char_start=start, char_end=end,
            token_count=_token_count(tokenizer, chunk_text), section=_section_for(text, start),
        ))
        if end == len(text):
            break
        next_start = _overlap_start(tokenizer, text, start, end, overlap_tokens)
        start = next_start if next_start > start else end
    if any(c.token_count > max_tokens for c in chunks):
        raise AssertionError("存在超过 token 上限的切片")
    return chunks
