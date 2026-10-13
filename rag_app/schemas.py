from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PageRecord(BaseModel):
    pdf_page: int
    printed_page: int
    text: str


class Chunk(BaseModel):
    chunk_id: str
    text: str
    pdf_pages: list[int]
    printed_pages: list[int]
    char_start: int
    char_end: int
    token_count: int
    section: str | None = None


class Hit(Chunk):
    rank: int
    score: float


class Evidence(BaseModel):
    chunk_id: str
    quote: str = Field(min_length=1, max_length=1200)


class Claim(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    evidence: list[Evidence] = Field(min_length=1, max_length=3)


class ModelAnswer(BaseModel):
    status: Literal["answered", "partial", "insufficient"]
    claims: list[Claim] = Field(max_length=8)
    missing_information: list[str] = Field(max_length=8)

    @model_validator(mode="before")
    @classmethod
    def conservative_status(cls, data):
        # Never upgrade completeness or alter factual content. Some local models
        # explicitly list missing facts but leave status at "answered".
        if isinstance(data, dict) and data.get("status") == "answered" and data.get("missing_information"):
            data = dict(data)
            data["status"] = "partial" if data.get("claims") else "insufficient"
        return data

    @model_validator(mode="after")
    def consistent_status(self) -> "ModelAnswer":
        if self.status == "answered" and (not self.claims or self.missing_information):
            raise ValueError("answered 必须有 claims 且 missing_information 为空")
        if self.status == "partial" and (not self.claims or not self.missing_information):
            raise ValueError("partial 必须同时有 claims 和 missing_information")
        if self.status == "insufficient" and (self.claims or not self.missing_information):
            raise ValueError("insufficient 必须无 claims 且说明缺失信息")
        return self


class BaselineAnswer(BaseModel):
    answer: str = Field(min_length=1)


class ValidationResult(BaseModel):
    passed: bool
    errors: list[str] = []
