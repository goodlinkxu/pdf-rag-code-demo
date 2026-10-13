from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]


class Config(BaseModel):
    source_pdf: str = "作业一/文献.pdf"
    index_dir: str = "data/index"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "auto"
    query_prefix: str = "为这个句子生成表示以用于检索相关文章："
    chunk_max_tokens: int = Field(default=400, ge=32)
    chunk_overlap_tokens: int = Field(default=60, ge=0)
    embedding_batch_size: int = Field(default=16, ge=1)
    top_k: int = Field(default=5, ge=1, le=8)
    ollama_base_url: str = "http://127.0.0.1:11434"
    generation_model: str = "qwen3.5:9b"
    temperature: float = 0
    num_ctx: int = Field(default=8192, ge=1024)
    num_predict: int = Field(default=3000, ge=128)
    request_timeout_seconds: int = Field(default=300, ge=10)

    @model_validator(mode="after")
    def validate_overlap(self) -> "Config":
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_tokens 必须小于 chunk_max_tokens")
        return self

    @property
    def pdf_path(self) -> Path:
        p = Path(self.source_pdf)
        return p.resolve() if p.is_absolute() else (ROOT / p).resolve()

    @property
    def index_path(self) -> Path:
        p = Path(self.index_dir)
        return p.resolve() if p.is_absolute() else (ROOT / p).resolve()


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path).resolve() if path else ROOT / "config.json"
    if path and not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    if not config_path.exists():
        config_path = ROOT / "config.example.json"
    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8-sig"))
    return Config.model_validate(data)
