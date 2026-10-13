> **Conda 选择版更新：双击一键部署后，按编号选择已有的非 base Conda 环境，或输入 N 新建。** 全部安装与启动通过所选环境的 `conda run` 执行，不再使用 venv 或猜测 Python 路径。旧的 -Python/-UseExistingEnvironment 部署参数不再使用，详见 一键部署说明.md。

> **同事一键部署入口：完整解压后双击 `一键部署.cmd`。** 脚本会准备 Python、项目独立环境、Ollama、模型和索引，再打开页面。具体行为及失败处理见 [一键部署说明](一键部署说明.md)。下面的手动步骤保留用于排错。

> 当前默认模型为 `qwen3.5:9b`，本机文件约 6.6 GB，已在 16 GB 显存电脑验收。低配置机器可选择 `evaluation/config-lightweight.json`，但需重新评估答案质量。下文关于旧运行目录和旧测试次数是历史记录，本次结果以 `planning/产品验收-2026-09-10.md` 为准。

> **2026-09-10 更新：日常使用已有浏览器界面。** 完成本教程的 Python、依赖和 Ollama 配置后，在项目目录执行 `python -m rag_app serve`，或双击 `启动.cmd`。页面内完成提问、三题填写、逐题核对与 JSON 导出，不必再手动准备问题 JSON、复制 run 路径或执行三条 review 命令。原命令行步骤保留用于实验复现与排错。
>
> 默认 `embedding_device` 现为 `auto`，自动选显卡或 CPU。新版网页记录支持重试未完成题目；CLI 的 `--resume` 仍未实现。打包时新增保留 `rag_app/static/`、`启动.ps1`、`启动.cmd`。

# 中文论文 RAG 作业：打包后从零配置的保姆级教程

本文专门给“拿到项目压缩包、准备在另一台 Windows 电脑上运行的人”。教程不假设对方拥有作者的 Python 环境、Ollama、Embedding 缓存、`data/index` 或 `outputs`。请从第 0 节开始，不要直接复制作者机器的绝对路径。

本文假设使用 Windows PowerShell。建议把压缩包解压到一个不含特殊符号的目录，例如：

```text
C:\rag_homework
```

系统只把 `作业一/文献.pdf` 作为检索来源，不会把 PRD、交接文档、验收参考、题目文件或历史输出加入论文库。默认生成模型为本机 Ollama 的 `qwen3.5:9b`。

## 0. 打包者和接收者先确认项目内容

### 打包者必须包含

```text
作业一/文献.pdf
rag_app/
tests/
evaluation/questions.sample.json
config.example.json
requirements.txt
requirements-lock.txt
README.md
tutor.md
PRD.md
实现交接提示词.md
MODEL_COMPARISON.md
```

`data/index/` 和 `outputs/` 可以一起打包，作为作者的运行证据；接收者也可以删除后重新生成。不要把作者电脑的 `config.json`、`.venv`、`__pycache__`、`.pytest_cache` 或 Hugging Face/Ollama 模型缓存当作环境配置的一部分。尤其不要改名、移动或替换 `作业一/文献.pdf`。

### 接收者解压后先设置项目变量

在 PowerShell 中执行：

```powershell
chcp 65001
$Project = "C:\rag_homework"
Set-Location $Project
Get-ChildItem
Test-Path .\作业一\文献.pdf
```

最后一条必须输出 `True`。如果输出 `False`，说明压缩包多套了一层目录，先进入真正包含 `rag_app` 和 `作业一` 的那一层。

教程后面的命令都使用 `$Project` 和 `$Py`，所以换电脑时只需要修改这两个变量。

## 1. 你最终会得到什么

完整流程是：

```text
原始 PDF
  → 读取 18 页并清洗页眉、页脚、乱码和水印
  → 按 BGE tokenizer 切成带 C0001、页码和字符范围的 chunks
  → 生成并缓存 BGE 文档向量
  → 对问题生成查询向量并做 NumPy 余弦 Top-K 检索
  → 把问题和本次证据交给本地 Ollama
  → 校验 JSON、引用 ID 和 quote 是否来自原始切片
  → 保存 trace、RAG/baseline 对比和三题 submission.json
```

正式提交文件只有在以下条件同时满足时才会生成：恰好三题、每题没有运行错误、引用检查通过、人工内容核对为 `passed`。

## 2. 第一次配置：准备 Python

推荐 Python 3.11—3.13 的 64 位版本；本项目已在 Python 3.13.5 上验证。可从 [Python Windows 下载页](https://www.python.org/downloads/windows/) 安装，也可以使用 [Anaconda](https://www.anaconda.com/download)。安装 Python 时勾选 **Add Python to PATH**；如果使用 Conda，则不需要勾选这个选项。

### 方案 A：已有 Conda

```powershell
conda create -n rag-homework python=3.13 -y
conda activate rag-homework
$Py = (Get-Command python).Source
```

### 方案 B：已有普通 Python

```powershell
$Py = (Get-Command python).Source
```

确认 `$Py` 指向的是刚刚准备的解释器：

```text
Python 3.13.5
```

不要把上面 `Python 3.13.5` 当作命令输入；它只是预期输出。

实际检查命令：

```powershell
& $Py --version
& $Py -c "import sys; print(sys.executable)"
```

安装已经验证过的直接依赖：

```powershell
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements-lock.txt
```

如果锁定版本在你的 Python 或 CUDA 环境中无法安装，再改用：

```powershell
& $Py -m pip install -r requirements.txt
```

检查关键库是否可导入：

```powershell
& $Py -c "import numpy,pydantic,pypdf,requests,sentence_transformers; print('Python dependencies: OK')"
```

Embedding 默认使用 CUDA。若你的电脑没有可用 NVIDIA CUDA，把配置中的：

```json
"embedding_device": "cuda"
```

改成：

```json
"embedding_device": "cpu"
```

CPU 只会更慢，不改变结果结构；改设备不会改变向量语义，但建议在新机器上重新建立索引。

如果第一次 `pip install` 在 `torch`、`sentence-transformers` 或 CUDA 相关依赖处失败，先确认使用的是 64 位 Python，再用未锁版本安装：

```powershell
& $Py -m pip install -r requirements.txt
```

如果仍失败，把完整错误保留给维护者；不要用随机向量或删掉 Embedding 步骤代替。

## 3. 第二次配置：准备 Ollama 和生成模型

安装 Ollama 后，确保 Ollama 服务正在运行。可从 [Ollama Windows 下载页](https://ollama.com/download/windows) 安装。先检查：

```powershell
ollama --version
ollama list
```

如果服务没有运行，可以单独打开一个 PowerShell 窗口执行：

```powershell
ollama serve
```

在另一个窗口下载默认模型：

```powershell
ollama pull qwen3.5:9b
```

本项目也实测过两个候选模型。接收者不需要下载它们，只有想复现实验对比时才执行：

```powershell
ollama pull qwen3.5:0.8b
ollama pull qwen3.5:9b
```

推荐仍使用 `qwen3.5:9b`。具体三模型结果、耗时和失败边界见 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)。切换生成模型只需要改配置，不需要重新建立论文向量索引。

## 4. 第三次配置：检查配置文件

程序默认寻找根目录下的 `config.json`；如果没有，就自动使用 `config.example.json`。建议复制一份自己的配置：

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

默认配置如下，第一次不要改动：

```json
{
  "source_pdf": "作业一/文献.pdf",
  "index_dir": "data/index",
  "embedding_model": "BAAI/bge-small-zh-v1.5",
  "embedding_device": "cuda",
  "query_prefix": "为这个句子生成表示以用于检索相关文章：",
  "chunk_max_tokens": 400,
  "chunk_overlap_tokens": 60,
  "embedding_batch_size": 16,
  "top_k": 5,
  "ollama_base_url": "http://127.0.0.1:11434",
  "generation_model": "qwen3.5:9b",
  "temperature": 0,
  "num_ctx": 8192,
  "num_predict": 1500,
  "request_timeout_seconds": 300
}
```

注意：

- `source_pdf` 必须仍然是 `作业一/文献.pdf`，不要改成整个文件夹扫描。
- `top_k` 当前推荐为 5，允许范围是 1—8。
- 改了论文、Embedding 模型、query prefix 或切块参数后，必须重新运行 `index --force`。
- 只改 `generation_model`、温度或生成长度，不需要重建 BGE 文档向量。

## 5. 第一次启动检查：doctor

在项目根目录执行：

```powershell
& $Py -m rag_app doctor
```

正常结果应包含：

```text
论文：存在 .../作业一/文献.pdf
索引：有效，83 chunks / 512 维
Ollama：已连接
生成模型：可用 qwen3.5:9b
```

如果显示“索引不存在”，先执行下一节；如果显示 Ollama 不可用，先启动 Ollama；如果显示模型缺失，执行 `ollama pull qwen3.5:9b`。

## 6. 建立论文索引

第一次建立索引：

```powershell
& $Py -m rag_app index
```

第一次运行会下载或加载 `BAAI/bge-small-zh-v1.5`，读取 18 页 PDF，生成 `data/index/` 下的文件：

```text
pages_raw.jsonl       原始页文本
pages_clean.jsonl     清洗后页文本
chunks.jsonl          切片、页码、字符范围和 token 数
embeddings.npy        归一化文档向量
manifest.json         PDF SHA、索引指纹、模型和依赖版本
```

这一步需要能访问 Hugging Face 或已经存在本地模型缓存。模型信息可在 [BGE 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) 查看。若目标电脑不能联网，可以在另一台机器下载完整模型目录，再把目录复制到目标电脑，并把 `config.json` 中的 `embedding_model` 改成该目录的绝对路径，例如：

```json
"embedding_model": "D:/models/bge-small-zh-v1.5"
```

路径下必须有完整的 Sentence Transformers 模型文件；不能只复制一个配置文件，也不能用随机向量代替。改成本地路径后，执行：

```powershell
& $Py -m rag_app index --force
```

如果压缩包已经包含与当前 PDF、切块参数和 Embedding 模型完全匹配的 `data/index/`，可以直接复用；`doctor` 和 `index` 会通过 manifest 指纹检查，发现不匹配时会要求重建。

之后重复执行：

```powershell
& $Py -m rag_app index
```

如果看到 `cache_hit=true`，说明没有重复编码论文。只有在来源或索引参数真的改变时才执行：

```powershell
& $Py -m rag_app index --force
```

## 7. 先试一条问题

单题命令：

```powershell
& $Py -m rag_app ask --question "TempQuestions 包含多少个时间问题？分成哪四类？" --compare
```

控制台会显示：

1. Top-K chunk ID；
2. PDF 页码和相似度；
3. RAG 答案；
4. `citation_check`；
5. 纯模型 baseline 答案；
6. 输出目录。

完整内容不只在屏幕上显示，还会保存到：

```text
outputs/<run_id>/run.json
outputs/<run_id>/trace_01.json
outputs/<run_id>/comparison.md
```

其中 `trace_01.json` 保存本次问题、完整 Top-K、完整 RAG prompt、原始模型响应、baseline prompt 和校验结果。

如果你想连续提问而不提前写 JSON，可以使用交互模式：

```powershell
& $Py -m rag_app chat --compare
```

输入问题后回车；输入 `:quit` 结束并保存本次交互记录。

## 8. 用三道题批处理

题目文件必须是 UTF-8 JSON 数组，每题有唯一 `id` 和非空 `question`：

```json
[
  {"id": "q1", "question": "第一个问题"},
  {"id": "q2", "question": "第二个问题"},
  {"id": "q3", "question": "第三个问题"}
]
```

运行样例题：

```powershell
& $Py -m rag_app batch --questions evaluation/questions.sample.json --compare
```

助教现场给出新题后，复制文件再编辑：

```powershell
Copy-Item evaluation/questions.sample.json evaluation/questions.live.json
notepad evaluation/questions.live.json
& $Py -m rag_app batch --questions evaluation/questions.live.json --compare
```

每完成一道题，程序都会立即写回 `run.json`。如果后续题目生成失败，前面已经完成的题目仍保留。当前 CLI 没有自动 `--resume` 参数；需要重跑时重新执行同一题目文件，并以新的 run 目录为准。

## 9. 人工核对与正式导出

自动 `citation_check=passed` 只表示：引用 ID 属于当前 Top-K，quote 是对应切片的连续原文。它不能代替人工判断事实是否真的被证据支持。

先打开 `run.json` 和对应 `trace_*.json`，再对照原始 PDF 检查：

- 数字是否正确；
- 每个子问题是否都回答；
- 引用是否直接支持该事实；
- 资料不足时是否明确说明，而不是猜测。

确认一题后登记：

```powershell
& $Py -m rag_app review --run outputs\<run_id>\run.json --id q1 --result passed --note "已对照论文逐字核对"
& $Py -m rag_app review --run outputs\<run_id>\run.json --id q2 --result passed --note "已对照论文逐字核对"
& $Py -m rag_app review --run outputs\<run_id>\run.json --id q3 --result passed --note "已对照论文逐字核对"
```

三题都通过后导出：

```powershell
& $Py -m rag_app export --run outputs\<run_id>\run.json
```

默认会在同一目录生成：

```text
outputs/<run_id>/submission.json
```

导出后再检查 JSON 是否可解析：

```powershell
Get-Content outputs\<run_id>\submission.json -Raw | ConvertFrom-Json | Select-Object id,status
```

## 10. 本次已完成的真实演示

本次检查实际执行了：

```powershell
& $Py -m rag_app doctor
& $Py -m rag_app index
& $Py -m rag_app batch --questions evaluation/questions.sample.json --compare
& $Py -m rag_app review --run outputs\20260905-184415-181dfd\run.json --id q1 --result passed --note "已对照文献PDF第8页及C0041逐字核对"
& $Py -m rag_app review --run outputs\20260905-184415-181dfd\run.json --id q2 --result passed --note "已对照文献PDF第8页及C0038逐字核对"
& $Py -m rag_app review --run outputs\20260905-184415-181dfd\run.json --id q3 --result passed --note "已对照文献PDF第6页及C0032逐字核对"
& $Py -m rag_app export --run outputs\20260905-184415-181dfd\run.json
```

最终结果：

```text
q1 answered / citation_check=passed / content_review=passed
q2 answered / citation_check=passed / content_review=passed
q3 answered / citation_check=passed / content_review=passed
submission.json：生成成功并重新解析验证
```

可直接查看：

- `outputs/20260905-184415-181dfd/run.json`
- `outputs/20260905-184415-181dfd/trace_01.json`
- `outputs/20260905-184415-181dfd/trace_02.json`
- `outputs/20260905-184415-181dfd/trace_03.json`
- `outputs/20260905-184415-181dfd/comparison.md`
- `outputs/20260905-184415-181dfd/submission.json`

演示过程中还保留了两次被系统拒绝的运行：模型把中文句号改成 ASCII 句号，引用不是原文连续片段，因此 `citation_check` 失败，没有被导出。修复后程序只恢复“模型额外添加的末尾 ASCII 标点”，最终 quote 仍从原始切片精确取得；数字、词语和中间标点改变仍会失败。

## 11. 自动测试和完整性检查

运行：

```powershell
& $Py -m pytest -q
```

当前结果为 6 passed，覆盖：

- 清洗不损坏 BERT、T5-Large 和 1,271 等关键数字；
- 切块 token 上限、尾部覆盖和字符范围；
- 伪造 chunk ID 和伪造 quote 会被拒绝；
- 空白差异和额外末尾 ASCII 标点的安全恢复；
- 未满三题时禁止导出。

## 12. 常见问题

### `索引不存在`

```powershell
& $Py -m rag_app index
```

### `论文或索引配置已变化`

确认变更后执行：

```powershell
& $Py -m rag_app index --force
```

### `Ollama 不可用`

检查 Ollama 是否启动：

```powershell
ollama list
```

必要时另开窗口执行 `ollama serve`。

### `生成模型缺失`

```powershell
ollama pull qwen3.5:9b
```

或者在配置中填写 `ollama list` 里真实存在的模型名称。

### 终端中文显示成乱码

这通常是 PowerShell 代码页问题，不一定是文件内容损坏。先执行：

```powershell
chcp 65001
```

然后用 VS Code、记事本或 PowerShell 的 UTF-8 读取 `run.json` 和 `submission.json`。

### `citation_check=failed`

不要直接把答案复制进提交文件。查看同目录 `trace_*.json`，确认模型是否改写了 quote、引用了非 Top-K chunk，或漏答了子问题。重新运行可以生成新 run；只有引用和内容都人工确认后才能 `review passed`。

### 生成超时或因长度上限截断

先保留失败 run 作为证据，再降低 `top_k` 或换用默认的 `qwen3.5:9b`。不要把失败结果手工改成成功答案。

## 13. 交接时的最终检查清单

- [ ] `作业一/文献.pdf` 仍存在且没有替换；
- [ ] `config.json` 的 `source_pdf` 指向唯一论文；
- [ ] `doctor` 显示索引有效、Ollama 已连接、模型可用；
- [ ] `index` 显示 `cache_hit=true` 或完成真实重建；
- [ ] `pytest -q` 全部通过；
- [ ] 三题 `status` 正确且没有 `error`；
- [ ] 三题 `citation_check=passed`；
- [ ] 三题已逐题人工 `review passed`；
- [ ] `export` 成功生成 UTF-8 `submission.json`；
- [ ] 不把 `planning/验收参考.md`、PRD 或历史输出当作检索来源；
- [ ] 需要换模型时，记录真实模型名和新 run 路径。

## 14. 对原作业要求逐条验收

| 原作业要求 | 当前实现 | 证据 | 状态 |
| --- | --- | --- | --- |
| 读取并清洗论文 | `pypdf` 读取 18 页，清除页脚、水印和重复字符 | `data/index/manifest.json`、`test_cleaning_preserves_models_and_numbers` | 已完成 |
| 文档切块 | BGE tokenizer 控制 400 token，60 token overlap，保留 chunk ID、页码和字符范围 | `data/index/chunks.jsonl`、切块测试 | 已完成 |
| 文档向量与问题向量 | `sentence-transformers` 的 BGE，归一化向量，NumPy 余弦相似度 | `data/index/embeddings.npy`、`retrieval.py` | 已完成 |
| 更换问题复用文档向量 | 索引落盘并通过 fingerprint 校验，未变化时 `cache_hit=true` | `index` 演示、`manifest.json` | 已完成 |
| Top-K 检索和中间结果展示 | 输出 chunk ID、PDF 页码、score、原文预览，完整命中保存在 trace | `run.json`、`trace_*.json` | 已完成 |
| 组合证据生成答案 | 请求只含当前问题和当前 Top-K 证据，使用本地 Ollama | `trace_*.json` 的 `rag_messages` | 已完成 |
| 资料不足时不编造 | `answered/partial/insufficient` 结构约束，缺资料必须填写缺失信息 | `schemas.py`、Pydantic 校验 | 已完成 |
| 引用和内容分别核对 | 自动 `citation_check` 与人工 `content_review` 分开保存 | 最新 `run.json` 三题均 passed | 已完成 |
| 纯模型和 RAG 对比 | `--compare` 发起隔离 baseline 请求，不携带论文或历史答案 | `comparison.md`、baseline trace | 已完成 |
| 三题 JSON 提交 | `review` 后 `export`，严格检查三题、错误、引用和人工核对 | 最新 `submission.json` 可重新解析 | 已完成 |
| 代码和依赖可复现 | README、tutor、PRD、锁定依赖、pytest | `6 passed` | 已完成 |

因此，原始作业要求的核心功能已经完整实现并实际演示。自动 `--resume` 属于 PRD 的额外规划项，不是原始作业必需功能；断网后的首次 Embedding 下载也没有被虚假宣称为已验证。

## 15. 当前边界

原始作业要求的核心功能已经实现并完成真实演示：论文读取、清洗、切块、Embedding、缓存、Top-K 检索、RAG、baseline、引用检查、人工核对、三题 JSON 导出和模型对比均可运行。

PRD 额外规划的自动 `--resume` 尚未作为 CLI 参数实现；当前策略是每题完成后立即保存 `run.json`。权重和索引准备好后的完整断网演练也没有宣称通过，因为首次 Embedding 下载需要网络。除此之外，不要把自动引用匹配称为事实正确率；未知问题仍必须人工检查。
