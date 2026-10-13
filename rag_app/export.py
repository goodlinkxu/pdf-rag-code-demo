from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def save_run(run: dict, path: Path) -> None:
    atomic_json(path, run)


def mark_review(run_path: Path, question_id: str, result: str, note: str) -> None:
    if result not in {"passed", "failed"}:
        raise ValueError("核对结果只能为 passed 或 failed")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    matches = [item for item in run["results"] if item["id"] == question_id]
    if len(matches) != 1:
        raise ValueError(f"找不到唯一题目 id：{question_id}")
    if result == "passed" and (matches[0].get("error") or matches[0].get("citation_check") != "passed"):
        raise ValueError("本题存在运行或引用错误，请先修复再确认内容")
    matches[0]["content_review"] = result
    matches[0]["review_note"] = note
    matches[0]["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    save_run(run, run_path)


def export_submission(run_path: Path, output_path: Path | None = None) -> Path:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    results = run.get("results", [])
    if len(results) != 3 or len({r.get("id") for r in results}) != 3:
        raise ValueError("正式提交必须恰好包含三个不同 id 的问题")
    from .schemas import ModelAnswer, Hit
    from .validation import validate_answer
    blockers = []
    for r in results:
        try:
            answer = ModelAnswer.model_validate(r)
            validation = validate_answer(answer, [Hit.model_validate(h) for h in r["retrieved_chunks"]])
            if not validation.passed:
                blockers.append(f"{r['id']} 引用重新校验失败")
        except (ValueError, KeyError, TypeError):
            blockers.append(f"{r.get('id')} 答案结构无效")
        if r.get("error"):
            blockers.append(f"{r['id']} 存在运行错误")
        if r.get("citation_check") != "passed":
            blockers.append(f"{r['id']} 引用检查未通过")
        if r.get("content_review") != "passed":
            blockers.append(f"{r['id']} 尚未完成人工内容核对")
        if not r.get("answer", "").strip():
            blockers.append(f"{r['id']} 答案为空")
    if blockers:
        raise ValueError("无法导出：" + "；".join(blockers))
    submission = []
    for r in results:
        hits = {h["chunk_id"]: h for h in r["retrieved_chunks"]}
        citations, seen = [], set()
        for claim in r["claims"]:
            for evidence in claim["evidence"]:
                key = (evidence["chunk_id"], evidence["quote"])
                if key in seen:
                    continue
                seen.add(key)
                citations.append({
                    "chunk_id": evidence["chunk_id"],
                    "pdf_pages": hits[evidence["chunk_id"]]["pdf_pages"],
                    "quote": evidence["quote"],
                })
        submission.append({
            "id": r["id"], "question": r["question"], "answer": r["answer"],
            "status": r["status"], "citations": citations,
        })
    output_path = output_path or run_path.with_name("submission.json")
    atomic_json(output_path, submission)
    json.loads(output_path.read_text(encoding="utf-8"))
    return output_path
