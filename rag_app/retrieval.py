from __future__ import annotations

import numpy as np

from .config import Config
from .index import LoadedIndex
from .schemas import Hit


def retrieve(question: str, index: LoadedIndex, embedder, config: Config) -> list[Hit]:
    question = question.strip()
    if not question:
        raise ValueError("问题不能为空")
    query = config.query_prefix + question
    token_count = len(embedder.tokenizer(query, add_special_tokens=True, truncation=False)["input_ids"])
    max_length = getattr(embedder.tokenizer, "model_max_length", 512)
    if token_count > max_length:
        raise ValueError(f"问题过长：{token_count} tokens，模型上限为 {max_length}")
    vector = embedder.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)
    scores = index.embeddings @ vector
    indices = np.argsort(-scores, kind="stable")[:min(config.top_k, len(index.chunks))]
    return [Hit(**index.chunks[int(i)].model_dump(), rank=rank, score=float(scores[int(i)]))
            for rank, i in enumerate(indices, start=1)]
