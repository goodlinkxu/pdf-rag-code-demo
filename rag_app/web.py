"""Loopback-only browser UI. Uses the same retrieval, validation and export as the CLI."""
from __future__ import annotations

import json
import re
import secrets
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .config import ROOT
from .export import save_run, mark_review, export_submission
from .index import validate_index, build_index
from .llm import list_models
from .service import RagService


class Workspace:
    def __init__(self, config, output=None):
        self.config = config
        self.output = output or ROOT / "outputs"
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = {"state": "idle", "message": ""}
        self.service = None

    def path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
            raise ValueError("运行记录编号无效")
        return self.output / run_id / "run.json"

    def read(self, run_id):
        return json.loads(self.path(run_id).read_text(encoding="utf-8"))

    def health(self):
        checks = []
        checks.append({"name": "论文", "ok": self.config.pdf_path.is_file(), "detail": self.config.pdf_path.name})
        try:
            m = validate_index(self.config)
            checks.append({"name": "检索资料", "ok": True, "detail": f"{m['page_count']} 页 · {m['chunk_count']} 个片段 · {m['embedding_dimension']} 维向量"})
        except Exception as exc:
            checks.append({"name": "检索资料", "ok": False, "detail": str(exc)})
        try:
            models = list_models(self.config)
            present = self.config.generation_model in models
            checks.append({"name": "回答模型", "ok": present, "detail": self.config.generation_model if present else f"请在终端执行 ollama pull {self.config.generation_model}"})
        except Exception:
            checks.append({"name": "回答模型", "ok": False, "detail": "请启动 Ollama，然后点击重新检查。"})
        return {"checks": checks, "ready": all(c["ok"] for c in checks)}

    def history(self):
        rows = []
        for path in sorted(self.output.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
                rows.append({"run_id": path.parent.name, "count": len(r["results"]),
                             "title": r["results"][0]["question"] if r["results"] else "尚未完成的提问"})
            except (ValueError, KeyError):
                continue
        return rows

    def start(self, action, data):
        # Validate before accepting work, including retries after a server restart.
        if action == "answer":
            questions = data.get("questions")
            if not isinstance(questions, list) or not 1 <= len(questions) <= 3:
                raise ValueError("请输入一个问题，或填写完整的三道提交题目")
            if any(not isinstance(q, str) or not q.strip() or len(q) > 600 for q in questions):
                raise ValueError("问题不能为空，且每题不能超过 600 字")
            data = {"questions": [q.strip() for q in questions], "compare": bool(data.get("compare"))}
        elif action == "retry":
            run = self.read(data.get("run_id"))
            if not run.get("questions"):
                raise ValueError("这份旧记录没有待办题目清单，请重新填写问题")
            if run.get("config") != self.config.model_dump(mode="json"):
                raise ValueError("配置已变化，请重新提问，避免混用不同模型的结果")
            if run.get("index_fingerprint") != validate_index(self.config)["index_fingerprint"]:
                raise ValueError("论文或索引已变化，请重新提问")
        elif action != "index":
            raise ValueError("未知操作")
        if not self.lock.acquire(blocking=False):
            raise ValueError("上一项操作还在进行，请等待完成后再试")
        self.job = {"state": "running", "message": "正在准备…", "run_id": data.get("run_id")}
        threading.Thread(target=self.work, args=(action, data), daemon=True).start()
        return self.job.copy()

    def work(self, action, data):
        try:
            if action == "index":
                self.job["message"] = "正在读取论文并准备检索资料，首次运行需要下载模型…"
                build_index(self.config, force=True)
                self.service = None
            else:
                if action == "retry":
                    run = self.read(data["run_id"])
                else:
                    from .__main__ import new_run
                    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
                    run = new_run(self.config, run_id)
                    run.update(questions=data["questions"], compare=data["compare"])
                run_id = run["run_id"]
                path = self.path(run_id)
                self.job["run_id"] = run_id
                run["state"] = "running"
                save_run(run, path)
                self.job["message"] = "正在加载检索模型，首次加载可能需要一些时间…"
                if self.service is None:
                    self.service = RagService(self.config)
                for i, question in enumerate(run["questions"], 1):
                    qid = f"q{i}"
                    previous = next((r for r in run["results"] if r["id"] == qid), None)
                    if previous and not previous.get("error") and previous.get("citation_check") == "passed":
                        continue
                    self.job["message"] = f"正在回答第 {i} / {len(run['questions'])} 题，并核对引用…"
                    result = self.service.answer(question, run["compare"], path.parent / f"trace_{i:02d}.json")
                    result["id"] = qid
                    run["results"] = [r for r in run["results"] if r["id"] != qid] + [result]
                    run["results"].sort(key=lambda r: r["id"])
                    save_run(run, path)
                failed = any(r.get("error") or r.get("citation_check") != "passed" for r in run["results"])
                run["state"] = "needs_retry" if failed else "complete"
                save_run(run, path)
                if failed:
                    self.job.update(state="error", message="部分题目未完成。已保存其他答案，可重试未完成题目。")
                    return
            self.job.update(state="done", message="已完成")
        except Exception as exc:
            self.job.update(state="error", message=f"未能完成：{exc}。已保存的答案仍可在历史记录中查看。")
        finally:
            self.lock.release()

    def mutate(self, action, data):
        if not self.lock.acquire(blocking=False):
            raise ValueError("请等待当前操作完成后再核对或导出")
        try:
            path = self.path(data.get("run_id"))
            if action == "review":
                mark_review(path, data.get("id"), data.get("result"), str(data.get("note", ""))[:2000])
                return {"ok": True}
            export_submission(path)
            return {"url": f"/download?run={path.parent.name}&file=submission.json"}
        finally:
            self.lock.release()


def handler_for(workspace):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, content_type="application/json; charset=utf-8", status=200, attachment=None):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.host_ok():
                return self.send({"error": "请通过本机地址打开页面"}, status=403)
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path in ("/", "/app.js", "/style.css"):
                    name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[u.path]
                    mime = {"/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8", "/style.css": "text/css; charset=utf-8"}[u.path]
                    return self.send((Path(__file__).parent / "static" / name).read_bytes(), mime)
                if u.path == "/api/state":
                    return self.send({"token": workspace.token, "job": workspace.job.copy(), "history": workspace.history()})
                if u.path == "/api/health": return self.send(workspace.health())
                if u.path == "/api/run": return self.send(workspace.read(q.get("id", [None])[0]))
                if u.path == "/paper": return self.send(workspace.config.pdf_path.read_bytes(), "application/pdf")
                if u.path == "/download":
                    name = q.get("file", [""])[0]
                    if name not in {"submission.json", "run.json", "trace_01.json", "trace_02.json", "trace_03.json"}:
                        raise ValueError("文件不可下载")
                    path = workspace.path(q.get("run", [None])[0]).with_name(name)
                    return self.send(path.read_bytes(), attachment=name)
                self.send({"error": "页面不存在"}, status=404)
            except (ValueError, FileNotFoundError, KeyError) as exc:
                self.send({"error": str(exc)}, status=400)

        def do_POST(self):
            if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Workspace-Token", ""), workspace.token):
                return self.send({"error": "页面已过期，请刷新后重试"}, status=403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16000: raise ValueError("请求大小无效")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict): raise ValueError("请求格式无效")
                action = self.path.removeprefix("/api/")
                if action in {"answer", "retry", "index"}:
                    return self.send(workspace.start(action, data))
                if action in {"review", "export"}:
                    return self.send(workspace.mutate(action, data))
                raise ValueError("未知操作")
            except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
                self.send({"error": str(exc)}, status=400)
    return Handler


def serve(config, port=8765, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(Workspace(config)))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"论文问答已启动：{url}\n关闭此终端会停止服务。")
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
