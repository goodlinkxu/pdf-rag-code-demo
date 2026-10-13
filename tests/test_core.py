from pathlib import Path

import numpy as np
import pytest

from rag_app.chunking import make_chunks
from rag_app.document import clean_page
from rag_app.export import export_submission
from rag_app.schemas import Chunk, Evidence, Claim, Hit, ModelAnswer, PageRecord
from rag_app.validation import canonicalize_quote_whitespace, validate_answer


class CharTokenizer:
    model_max_length = 512
    def __call__(self, text, **kwargs):
        return {"input_ids": [0] + list(range(len(text))) + [1]}


def test_cleaning_preserves_models_and_numbers():
    page = PageRecord(pdf_page=6, printed_page=156,
        text="5.2 输 输 输入 入 入数 数 数据 据 据过 过 过滤 滤 滤\nBERT 与 T5-Large，包含1,271个问题。\nCCL 2024\n156")
    result = clean_page(page).text
    assert "5.2 输入数据过滤" in result
    assert "BERT" in result and "T5-Large" in result and "1,271" in result
    assert "CCL 2024" not in result


def test_chunking_covers_text_and_respects_limit():
    pages = [PageRecord(pdf_page=1, printed_page=151, text="甲" * 30 + "。" + "乙" * 30 + "。")]
    chunks = make_chunks(pages, CharTokenizer(), max_tokens=22, overlap_tokens=5)
    assert chunks[-1].char_end == len(pages[0].text)
    assert all(c.token_count <= 22 and c.text == pages[0].text[c.char_start:c.char_end] for c in chunks)
    assert all(any(c.char_start <= i < c.char_end for c in chunks) for i in range(len(pages[0].text)))


def test_validation_rejects_fake_quote_and_id():
    chunk = Chunk(chunk_id="C0001", text="原文证据", pdf_pages=[1], printed_pages=[151],
                  char_start=0, char_end=4, token_count=4)
    hit = Hit(**chunk.model_dump(), rank=1, score=.9)
    good = ModelAnswer(status="answered", claims=[Claim(text="事实", evidence=[Evidence(chunk_id="C0001", quote="原文")])], missing_information=[])
    bad = ModelAnswer(status="answered", claims=[Claim(text="事实", evidence=[Evidence(chunk_id="C9999", quote="伪造")])], missing_information=[])
    assert validate_answer(good, [hit]).passed
    assert not validate_answer(bad, [hit]).passed


def test_quote_whitespace_is_canonicalized_but_characters_are_not():
    chunk = Chunk(chunk_id="C0001", text="(Jia et al.,2018) 包含1,271 个问题", pdf_pages=[8],
                  printed_pages=[158], char_start=0, char_end=30, token_count=20)
    hit = Hit(**chunk.model_dump(), rank=1, score=.9)
    answer = ModelAnswer(status="answered", claims=[Claim(text="事实", evidence=[
        Evidence(chunk_id="C0001", quote="(Jia et al., 2018)包含1,271 个问题")])], missing_information=[])
    canonicalize_quote_whitespace(answer, [hit])
    assert validate_answer(answer, [hit]).passed


def test_quote_trailing_ascii_punctuation_is_restored_to_source():
    chunk = Chunk(chunk_id="C0001", text="训练 BERT，使用 ChatGPT 生成数据。", pdf_pages=[1],
                  printed_pages=[151], char_start=0, char_end=28, token_count=20)
    hit = Hit(**chunk.model_dump(), rank=1, score=.9)
    answer = ModelAnswer(status="answered", claims=[Claim(text="事实", evidence=[
        Evidence(chunk_id="C0001", quote="训练 BERT，使用 ChatGPT 生成数据.")])], missing_information=[])
    canonicalize_quote_whitespace(answer, [hit])
    assert answer.claims[0].evidence[0].quote == "训练 BERT，使用 ChatGPT 生成数据"
    assert validate_answer(answer, [hit]).passed


def test_export_requires_three_reviewed(tmp_path: Path):
    path = tmp_path / "run.json"
    path.write_text('{"results": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        export_submission(path)
