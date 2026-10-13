from __future__ import annotations

import json
import time
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .config import Config

T = TypeVar("T", bound=BaseModel)


class OllamaError(RuntimeError):
    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


def list_models(config: Config) -> list[str]:
    try:
        response = requests.get(config.ollama_base_url.rstrip("/") + "/api/tags", timeout=5)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except requests.RequestException as exc:
        raise OllamaError(f"无法连接 Ollama：{exc}") from exc


def generate(messages: list[dict[str, str]], config: Config, response_model: type[T]) -> tuple[T, dict]:
    schema = response_model.model_json_schema()
    payload = {
        "model": config.generation_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {
            "temperature": config.temperature,
            "num_ctx": config.num_ctx,
            "num_predict": config.num_predict,
        },
    }
    last_error: Exception | None = None
    attempt_records: list[dict] = []
    for attempt in range(2):
        try:
            response = requests.post(
                config.ollama_base_url.rstrip("/") + "/api/chat",
                json=payload, timeout=config.request_timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
            if raw.get("done_reason") == "length":
                raise OllamaError("回答超出长度限制，请缩小问题范围后重试", [{"response": raw}])
            content = raw.get("message", {}).get("content", "").strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            elif content.startswith("```") and content.endswith("```"):
                content = content[3:-3].strip()
            attempt_records.append({"response": raw, "content": content})
            try:
                parsed = response_model.model_validate_json(content)
                return parsed, {"final_response": raw, "attempts": attempt_records}
            except ValidationError as exc:
                last_error = exc
                if attempt == 0:
                    payload["messages"] = messages + [{
                        "role": "user",
                        "content": "上一次输出不符合要求。请只输出以下 JSON Schema 定义的字段，"
                                   "不得使用其他字段，不要加 Markdown 围栏：\n" +
                                   json.dumps(schema, ensure_ascii=False) +
                                   "\n校验错误：" + str(exc),
                    }]
                    continue
                raise OllamaError(f"模型两次返回的 JSON 均不符合结构：{exc}", attempt_records) from exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1)
                continue
        except requests.HTTPError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            raise OllamaError(f"Ollama 请求失败：{detail}") from exc
        except json.JSONDecodeError as exc:
            last_error = exc
    raise OllamaError(f"Ollama 生成失败：{last_error}", attempt_records)
