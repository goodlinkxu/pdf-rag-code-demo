from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .schemas import PageRecord

FOOTER_PATTERNS = (
    "第二十三届中国计算语言学大会论文集",
    "卷2：前沿综述",
    "卷2:前沿综述",
    "中国中文信息学会计算语言学专业委员会",
    "Creative Commons Attribution 4.0 International License",
)


def read_pages(pdf_path: Path) -> list[PageRecord]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"找不到论文：{pdf_path}")
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            raise ValueError(f"PDF 第 {i} 页无法提取文本")
        pages.append(PageRecord(pdf_page=i, printed_page=i + 150, text=text))
    return pages


def _dedupe_title(line: str) -> str:
    compact = re.sub(r"\s+", "", line)
    repeated_named_title = re.match(r"^(?:摘{3}要{3}|关{3}键{3}词{3}|参{3}考{3}文{3}献{3})", compact)
    if len(compact) > 40 or not (re.match(r"^\d+(?:\.\d+)*", compact) or repeated_named_title or
                                re.match(r"^(?:摘要|关键词|参考文献)", compact)):
        return line
    # PDF 粗体字形常被提取三次：检检检索索索增强强强。
    deduped = re.sub(r"(.)\1\1", r"\1", compact)
    deduped = re.sub(r"^(\d+(?:\.\d+)*)(?=[^\d.])", r"\1 ", deduped)
    return deduped


def clean_page(page: PageRecord) -> PageRecord:
    text = page.text.replace("\x00", "")
    raw_lines = [line.strip() for line in text.splitlines()]
    kept: list[str] = []
    for line in raw_lines:
        if not line:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        compact = re.sub(r"\s+", "", line)
        if compact in {"CCL2024", str(page.printed_page)}:
            continue
        if any(pattern in line for pattern in FOOTER_PATTERNS):
            continue
        line = _dedupe_title(line)
        line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        kept.append(line)
    # 保留段落边界；普通换行合并，并修复英文排版断词。
    paragraphs: list[str] = []
    current = ""
    for line in kept + [""]:
        if not line:
            if current:
                paragraphs.append(current.strip())
                current = ""
            continue
        if not current:
            current = line
        elif len(current) <= 40 and re.match(r"^(?:\d+(?:\.\d+)*\s*|摘要|关键词|参考文献)", current):
            paragraphs.append(current.strip())
            current = line
        elif re.search(r"[A-Za-z]-$", current) and re.match(r"^[A-Za-z]", line):
            current = current[:-1] + line
        else:
            sep = " " if re.search(r"[A-Za-z0-9)]$", current) and re.match(r"^[A-Za-z0-9(]", line) else ""
            current += sep + line
    cleaned = "\n\n".join(paragraphs).strip()
    return PageRecord(pdf_page=page.pdf_page, printed_page=page.printed_page, text=cleaned)


def clean_pages(pages: list[PageRecord]) -> list[PageRecord]:
    cleaned = [clean_page(page) for page in pages]
    for page in cleaned:
        if len(page.text) < 100:
            raise ValueError(f"清洗后 PDF 第 {page.pdf_page} 页异常短，仅 {len(page.text)} 字符")
    return cleaned


def join_pages(pages: list[PageRecord]) -> tuple[str, list[tuple[int, int, PageRecord]]]:
    text = ""
    ranges: list[tuple[int, int, PageRecord]] = []
    for i, page in enumerate(pages):
        if i:
            text += "\n\n"
        start = len(text)
        text += page.text
        ranges.append((start, len(text), page))
    return text, ranges
