from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import Config
from .export import atomic_json
from .index import load_embedder, load_index
from .llm import OllamaError, generate
from .prompts import build_baseline_messages, build_rag_messages
from .retrieval import retrieve
from .schemas import BaselineAnswer, ModelAnswer
from .validation import canonicalize_quote_whitespace, render_answer, validate_answer


class RagService:
    def __init__(self, config: Config):
        self.config = config
        self.index = load_index(config)
        self.embedder = load_embedder(config)

    def answer(self, question: str, compare: bool = False, trace_path: Path | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        t = time.perf_counter()
        hits = retrieve(question, self.index, self.embedder, self.config)
        retrieval_ms = round((time.perf_counter() - t) * 1000, 2)
        messages = build_rag_messages(question, hits)
        trace: dict[str, Any] = {"question": question, "hits": [h.model_dump() for h in hits], "rag_messages": messages}
        result: dict[str, Any] = {
            "question": question, "status": "generation_error", "answer": "", "claims": [],
            "missing_information": [], "retrieved_chunks": [h.model_dump() for h in hits],
            "citation_check": "failed", "content_review": "pending",
            "baseline_answer": None, "timings_ms": {"retrieval": retrieval_ms}, "error": None,
        }
        try:
            print("正在生成 RAG 答案……")
            t = time.perf_counter()
            parsed, raw = generate(messages, self.config, ModelAnswer)
            result["timings_ms"]["rag_generation"] = round((time.perf_counter() - t) * 1000, 2)
            trace["rag_raw_response"] = raw
            canonicalize_quote_whitespace(parsed, hits)
            validation = validate_answer(parsed, hits)
            if not validation.passed:
                repair_messages = messages + [{"role": "assistant", "content": parsed.model_dump_json()}, {
                    "role": "user",
                    "content": "引用校验失败：" + "；".join(validation.errors) +
                               "。答案事实保持不变，只修正 evidence.quote；quote 必须从对应切片逐字复制，"
                               "连空格和标点也完全一致。返回同一 JSON 结构。",
                }]
                repaired, repair_raw = generate(repair_messages, self.config, ModelAnswer)
                canonicalize_quote_whitespace(repaired, hits)
                repaired_validation = validate_answer(repaired, hits)
                trace["citation_repair_raw_response"] = repair_raw
                same_content = (parsed.status == repaired.status
                                and parsed.missing_information == repaired.missing_information
                                and [c.text for c in parsed.claims] == [c.text for c in repaired.claims])
                if not same_content:
                    repaired_validation.passed = False
                    repaired_validation.errors.append("引用修复改变了答案内容，已拒绝；请重新生成")
                if repaired_validation.passed:
                    parsed, validation = repaired, repaired_validation
                else:
                    validation = repaired_validation
            result.update(parsed.model_dump())
            result["answer"] = render_answer(parsed)
            result["citation_check"] = "passed" if validation.passed else "failed"
            if not validation.passed:
                result["error"] = {"type": "validation_failed", "message": "；".join(validation.errors)}
            if compare:
                baseline_messages = build_baseline_messages(question)
                trace["baseline_messages"] = baseline_messages
                t = time.perf_counter()
                try:
                    baseline, baseline_raw = generate(baseline_messages, self.config, BaselineAnswer)
                    result["baseline_answer"] = baseline.answer
                    trace["baseline_raw_response"] = baseline_raw
                except Exception as exc:
                    result["baseline_error"] = str(exc)
                    trace["baseline_error"] = str(exc)
                result["timings_ms"]["baseline_generation"] = round((time.perf_counter() - t) * 1000, 2)
        except Exception as exc:
            if isinstance(exc, OllamaError):
                trace["failed_generation_attempts"] = exc.attempts
            result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000, 2)
        if trace_path:
            trace["result"] = result
            atomic_json(trace_path, trace)
        return result
