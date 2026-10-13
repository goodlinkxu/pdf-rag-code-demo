from __future__ import annotations

import argparse
import json
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, load_config
from .export import export_submission, mark_review, save_run
from .index import build_index, validate_index
from .llm import list_models
from .service import RagService


def output_dir(run_id: str) -> Path:
    return ROOT / "outputs" / run_id


def new_run(config, run_id: str) -> dict:
    manifest = validate_index(config)
    return {
        "schema_version": "1.0", "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "index_fingerprint": manifest["index_fingerprint"],
        "config": config.model_dump(mode="json"), "results": [],
    }


def show_result(result: dict) -> None:
    print("\n回答：\n" + (result["answer"] or "暂未生成答案，请查看下方原因。"))
    print("\n参考片段：")
    for hit in result["retrieved_chunks"][:3]:
        preview = hit["text"].replace("\n", " ")[:180]
        if len(hit["text"]) > 180:
            preview += "…"
        print(f"#{hit['rank']} {hit['chunk_id']} PDF页{hit['pdf_pages']} score={hit['score']:.4f}\n  {preview}")
    if len(result["retrieved_chunks"]) > 3:
        print(f"（另有 {len(result['retrieved_chunks']) - 3} 条证据已保存到 trace）")
    print("引用检查：" + {"passed": "已匹配原文", "failed": "未通过"}.get(result["citation_check"], result["citation_check"]) + "；内容核对：" + {"pending": "待核对", "passed": "已确认", "failed": "有误"}.get(result["content_review"], result["content_review"]))
    if result.get("baseline_answer"):
        print("\n纯模型答案：\n" + result["baseline_answer"])
    if result.get("error"):
        print("错误：" + result["error"]["message"], file=sys.stderr)


def doctor(config) -> int:
    healthy = config.pdf_path.exists()
    print(f"Python：{platform.python_version()} ({sys.executable})")
    print(f"论文：{'存在' if config.pdf_path.exists() else '缺失'} {config.pdf_path}")
    try:
        manifest = validate_index(config)
        print(f"索引：有效，{manifest['chunk_count']} chunks / {manifest['embedding_dimension']} 维")
    except Exception as exc:
        healthy = False
        print(f"索引：不可用（{exc}）")
    try:
        models = list_models(config)
        healthy = healthy and config.generation_model in models
        print("Ollama：已连接；模型：" + (", ".join(models) or "无"))
        print(f"生成模型：{'可用' if config.generation_model in models else '缺失'} {config.generation_model}")
    except Exception as exc:
        healthy = False
        print(f"Ollama：不可用（{exc}）")
    return 0 if healthy else 1


def run_questions(config, questions: list[dict], compare: bool, run_id: str | None = None) -> Path:
    if not isinstance(questions, list) or any(not isinstance(q, dict) for q in questions):
        raise ValueError("题目文件必须是包含 id 和 question 的 JSON 数组")
    ids = [str(q.get("id", "")).strip() for q in questions]
    texts = [str(q.get("question", "")).strip() for q in questions]
    if not questions or any(not x for x in ids + texts) or len(set(ids)) != len(ids):
        raise ValueError("问题列表必须含非空且唯一的 id，以及非空 question")
    questions = [{"id": i, "question": q} for i, q in zip(ids, texts)]
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    directory = output_dir(run_id)
    directory.mkdir(parents=True, exist_ok=False)
    run = new_run(config, run_id)
    run_path = directory / "run.json"
    save_run(run, run_path)
    service = RagService(config)
    for i, item in enumerate(questions, start=1):
        result = service.answer(item["question"], compare, directory / f"trace_{i:02d}.json")
        result["id"] = item["id"]
        run["results"].append(result)
        save_run(run, run_path)
        show_result(result)
    if compare:
        lines = ["# 纯模型与 RAG 对比\n"]
        for r in run["results"]:
            lines += [f"## {r['id']} {r['question']}\n", "### 纯模型\n", (r.get("baseline_answer") or "生成失败") + "\n",
                      "### RAG\n", (r.get("answer") or "生成失败") + "\n",
                      "### 人工核对\n", "- 内容正确性：待核对\n- 子问题覆盖：待核对\n- 可追溯性：待核对\n"]
        (directory / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n运行记录：{run_path}")
    return run_path


def run_exit_code(path: Path) -> int:
    results = json.loads(path.read_text(encoding="utf-8"))["results"]
    return 1 if any(r.get("error") or r.get("citation_check") != "passed" for r in results) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="中文论文 RAG 问答系统")
    parser.add_argument("--config", help="配置 JSON 路径")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p_serve = sub.add_parser("serve", help="打开本地问答页面")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--no-browser", action="store_true")
    p_index = sub.add_parser("index"); p_index.add_argument("--force", action="store_true")
    p_ask = sub.add_parser("ask"); p_ask.add_argument("--question", required=True); p_ask.add_argument("--compare", action="store_true")
    p_chat = sub.add_parser("chat"); p_chat.add_argument("--compare", action="store_true")
    p_batch = sub.add_parser("batch"); p_batch.add_argument("--questions", required=True); p_batch.add_argument("--compare", action="store_true")
    p_review = sub.add_parser("review"); p_review.add_argument("--run", required=True); p_review.add_argument("--id", required=True); p_review.add_argument("--result", choices=["passed", "failed"], required=True); p_review.add_argument("--note", default="")
    p_export = sub.add_parser("export"); p_export.add_argument("--run", required=True); p_export.add_argument("--output")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "serve":
        from .web import serve
        serve(config, args.port, not args.no_browser)
        return 0
    if args.command == "doctor": return doctor(config)
    if args.command == "index": build_index(config, args.force); return 0
    if args.command == "ask": return run_exit_code(run_questions(config, [{"id": "q1", "question": args.question}], args.compare))
    if args.command == "chat":
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run = new_run(config, run_id)
        directory = output_dir(run_id)
        directory.mkdir(parents=True, exist_ok=False)
        run_path = directory / "run.json"
        service = RagService(config)
        print("输入问题后按回车即可回答。输入 :quit 结束；每题单独检索，不沿用上一题对话。")
        while True:
            try:
                question = input("\n你的问题：").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question == ":quit": break
            if not question: continue
            i = len(run["results"]) + 1
            try:
                result = service.answer(question, args.compare, directory / f"trace_{i:02d}.json")
            except ValueError as exc:
                print(str(exc))
                continue
            result["id"] = f"q{i}"
            run["results"].append(result)
            save_run(run, run_path)
            show_result(result)
            print(f"已保存：{run_path}")
        return 0
    if args.command == "batch":
        path = Path(args.questions).resolve()
        return run_exit_code(run_questions(config, json.loads(path.read_text(encoding="utf-8-sig")), args.compare))
    if args.command == "review": mark_review(Path(args.run).resolve(), args.id, args.result, args.note); print("人工核对结果已保存"); return 0
    if args.command == "export":
        output = Path(args.output).resolve() if args.output else None
        path = export_submission(Path(args.run).resolve(), output); print(f"已导出并重新解析验证：{path}"); return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
