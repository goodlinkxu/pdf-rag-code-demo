"""Small deployment checks; dependencies check itself needs only Python stdlib."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def dependency_issues(requirements: Path) -> list[str]:
    issues = []
    for line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "未安装"
        if actual != version:
            issues.append(f"{name}: 需要 {version}，当前 {actual}")
    try:
        importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        issues.append("torch: 未安装")
    return issues


def record_runtime(root: Path = ROOT, conda: str | None = None) -> None:
    directory = root / ".runtime"
    directory.mkdir(exist_ok=True)
    data = {"root": str(root.resolve()), "python": sys.executable,
            "python_version": sys.version.split()[0],
            "environment_kind": "conda" if conda else "legacy",
            "environment_path": sys.prefix, "conda": conda}
    target = directory / "current.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, target)
    installed = sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions() if d.metadata.get("Name"))
    (directory / "installed-packages.txt").write_text("\n".join(installed), encoding="utf-8")


def prepare() -> None:
    from rag_app.config import load_config
    from rag_app.index import load_embedder, validate_index, build_index
    config = load_config()
    if not config.pdf_path.is_file():
        raise FileNotFoundError(f"找不到论文：{config.pdf_path}。请确认材料完整；迁移时配置应使用相对路径。")
    # Even a cached vector index still needs the model for new question vectors.
    print("检查检索模型。首次使用会下载 BGE 权重；已有模型则复用。", flush=True)
    embedder = load_embedder(config)
    probe = embedder.encode([config.query_prefix + "检索模型自检"], normalize_embeddings=True)
    if len(probe) != 1:
        raise RuntimeError("检索模型自检失败")
    del embedder
    try:
        manifest = validate_index(config)
        print(f"论文索引有效，复用 {manifest['chunk_count']} 个片段。cache_hit=true")
    except (ValueError, FileNotFoundError, KeyError):
        print("索引缺失或与当前论文/参数不匹配，正在重建。", flush=True)
        build_index(config, force=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["dependencies", "prepare", "record"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--conda")
    args = parser.parse_args()
    if args.action == "dependencies":
        issues = dependency_issues(ROOT / "requirements-lock.txt")
        print("\n".join(issues) if issues else "Python 依赖版本检查通过。")
        return 1 if issues else 0
    if args.action == "prepare":
        prepare()
    else:
        record_runtime(conda=args.conda)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"部署检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
