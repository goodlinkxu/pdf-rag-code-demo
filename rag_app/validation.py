from __future__ import annotations

from .schemas import Hit, ModelAnswer, ValidationResult


def canonicalize_quote_whitespace(answer: ModelAnswer, hits: list[Hit]) -> None:
    """把模型轻微格式漂移恢复为原文；不接受内容改写。

    允许的修复只有两种：空白差异，以及模型额外附加在 quote 末尾、且去掉后
    能在原切片中逐字找到的 ASCII 标点。最终写回的 quote 始终是原切片中的
    连续原文；数字、词语和中间标点不同仍会校验失败。
    """
    by_id = {hit.chunk_id: hit for hit in hits}
    for claim in answer.claims:
        for evidence in claim.evidence:
            hit = by_id.get(evidence.chunk_id)
            if hit is None or evidence.quote in hit.text:
                continue
            wanted = "".join(evidence.quote.split())
            compact_chars = []
            original_positions = []
            for pos, char in enumerate(hit.text):
                if not char.isspace():
                    compact_chars.append(char)
                    original_positions.append(pos)
            compact = "".join(compact_chars)
            at = compact.find(wanted)
            if at >= 0 and wanted:
                start = original_positions[at]
                end = original_positions[at + len(wanted) - 1] + 1
                evidence.quote = hit.text[start:end]
                continue
            # 小型模型常把中文句末标点改成 ASCII 句号，或在 quote 后多加一个
            # 标点。只尝试删除末尾 ASCII 标点，并且必须回到原文连续子串。
            candidate = evidence.quote
            while candidate and candidate[-1] in ".,!?;:)]}" + "'":
                candidate = candidate[:-1]
                if candidate and candidate in hit.text:
                    evidence.quote = candidate
                    break


def validate_answer(answer: ModelAnswer, hits: list[Hit]) -> ValidationResult:
    by_id = {hit.chunk_id: hit for hit in hits}
    errors: list[str] = []
    for ci, claim in enumerate(answer.claims, start=1):
        for ei, evidence in enumerate(claim.evidence, start=1):
            hit = by_id.get(evidence.chunk_id)
            if hit is None:
                errors.append(f"claim {ci} evidence {ei}: {evidence.chunk_id} 不在本次 Top-K")
            elif not evidence.quote.strip():
                errors.append(f"claim {ci} evidence {ei}: quote 为空")
            elif evidence.quote not in hit.text:
                errors.append(f"claim {ci} evidence {ei}: quote 不是切片连续原文")
    return ValidationResult(passed=not errors, errors=errors)


def render_answer(answer: ModelAnswer) -> str:
    parts = []
    for claim in answer.claims:
        ids = list(dict.fromkeys(e.chunk_id for e in claim.evidence))
        parts.append(f"{claim.text} {' '.join(f'[{i}]' for i in ids)}")
        # 将经过程序核验的逐字证据紧跟答案展示，防止小模型省略限定词。
        for evidence in claim.evidence:
            parts.append(f"证据原文 [{evidence.chunk_id}]：{evidence.quote}")
    if answer.missing_information:
        parts.append("无法从论文确定：" + "；".join(answer.missing_information))
    return "\n".join(parts)
