from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from .chunking import make_chunks
from .config import Config
from .document import clean_pages, read_pages
from .schemas import Chunk, PageRecord

CLEANING_VERSION = "2"
CHUNKING_VERSION = "1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _jsonl(path: Path, records: list[Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            data = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def _fingerprint_payload(config: Config, pdf_sha: str) -> dict[str, Any]:
    return {
        "pdf_sha256": pdf_sha,
        "embedding_model": config.embedding_model,
        "query_prefix": config.query_prefix,
        "cleaning_version": CLEANING_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "chunk_max_tokens": config.chunk_max_tokens,
        "chunk_overlap_tokens": config.chunk_overlap_tokens,
    }


def expected_fingerprint(config: Config) -> str:
    payload = _fingerprint_payload(config, sha256_file(config.pdf_path))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_embedder(config: Config) -> SentenceTransformer:
    try:
        device = config.embedding_device
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        return SentenceTransformer(config.embedding_model, device=device)
    except Exception as exc:
        raise RuntimeError(f"Embedding 模型加载失败：{config.embedding_model}（{exc}）") from exc


def validate_index(config: Config) -> dict[str, Any]:
    directory = config.index_path
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("索引不存在，请先运行：python -m rag_app index")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("index_fingerprint") != expected_fingerprint(config):
        raise ValueError("论文或索引配置已变化，请运行：python -m rag_app index --force")
    for name in ("chunks.jsonl", "embeddings.npy"):
        path = directory / name
        if not path.exists() or sha256_file(path) != manifest["file_sha256"][name]:
            raise ValueError(f"索引文件损坏：{name}，请使用 --force 重建")
    return manifest


def build_index(config: Config, force: bool = False) -> dict[str, Any]:
    directory = config.index_path
    if not force:
        try:
            manifest = validate_index(config)
            print(f"索引有效，复用缓存：{directory}\ncache_hit=true")
            return manifest
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, json.JSONDecodeError):
            raise
    directory.mkdir(parents=True, exist_ok=True)
    pages_raw = read_pages(config.pdf_path)
    pages_clean = clean_pages(pages_raw)
    print(f"读取 PDF：{len(pages_raw)} 页")
    print("清洗后各页字符数：", [len(p.text) for p in pages_clean])
    embedder = load_embedder(config)
    chunks = make_chunks(
        pages_clean, embedder.tokenizer,
        config.chunk_max_tokens, config.chunk_overlap_tokens,
    )
    token_counts = sorted(c.token_count for c in chunks)
    print(f"切片：{len(chunks)} 个；token 最小/中位/最大 = "
          f"{token_counts[0]}/{token_counts[len(token_counts)//2]}/{token_counts[-1]}")
    embeddings = embedder.encode(
        [c.text for c in chunks], batch_size=config.embedding_batch_size,
        normalize_embeddings=True, convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)
    if embeddings.shape[0] != len(chunks) or not np.isfinite(embeddings).all():
        raise ValueError("Embedding 输出无效")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1, atol=1e-3):
        raise ValueError("Embedding 未正确归一化")

    temp_paths = {name: directory / f".{name}.tmp" for name in
                  ("pages_raw.jsonl", "pages_clean.jsonl", "chunks.jsonl", "embeddings.npy")}
    _jsonl(temp_paths["pages_raw.jsonl"], pages_raw)
    _jsonl(temp_paths["pages_clean.jsonl"], pages_clean)
    _jsonl(temp_paths["chunks.jsonl"], chunks)
    with temp_paths["embeddings.npy"].open("wb") as f:
        np.save(f, embeddings, allow_pickle=False)
    for name, temp in temp_paths.items():
        os.replace(temp, directory / name)
    fingerprint = expected_fingerprint(config)
    manifest = {
        "schema_version": "1.0", "index_fingerprint": fingerprint,
        "source_pdf": str(config.pdf_path), "source_pdf_sha256": sha256_file(config.pdf_path),
        "page_count": len(pages_raw), "printed_page_offset": 150,
        "cleaning_version": CLEANING_VERSION, "chunking_version": CHUNKING_VERSION,
        "chunk_max_tokens": config.chunk_max_tokens,
        "chunk_overlap_tokens": config.chunk_overlap_tokens,
        "embedding_model": config.embedding_model, "embedding_device": config.embedding_device,
        "query_prefix": config.query_prefix, "normalized": True,
        "chunk_count": len(chunks), "embedding_dimension": int(embeddings.shape[1]),
        "file_sha256": {name: sha256_file(directory / name) for name in ("chunks.jsonl", "embeddings.npy")},
        "built_at": datetime.now(timezone.utc).isoformat(),
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("numpy", "pypdf", "sentence-transformers")},
    }
    temp_manifest = directory / ".manifest.json.tmp"
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_manifest, directory / "manifest.json")
    print(f"向量形状：{embeddings.shape}；保存至 {directory}\ncache_hit=false")
    return manifest


class LoadedIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, manifest: dict[str, Any]):
        self.chunks = chunks
        self.embeddings = embeddings
        self.manifest = manifest


def load_index(config: Config) -> LoadedIndex:
    manifest = validate_index(config)
    chunks = [Chunk.model_validate_json(line) for line in
              (config.index_path / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
    embeddings = np.load(config.index_path / "embeddings.npy", allow_pickle=False)
    if embeddings.shape != (len(chunks), manifest["embedding_dimension"]):
        raise ValueError("切片与向量形状不一致，请重建索引")
    return LoadedIndex(chunks, embeddings, manifest)
