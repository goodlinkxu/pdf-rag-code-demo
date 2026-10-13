# 论文问答

围绕《浅谈大模型时代下的检索增强：发展趋势、挑战与展望》提问，查看答案对应的原文，并完成课程要求的三题 JSON 提交。

**同事首次安装或迁移：完整解压后双击 `一键部署.cmd`，按编号选择已有的非 base Conda 环境（或输入 N 新建）。** 见 [一键部署说明](一键部署说明.md)，需要逐步排错时查看 [从零配置教程](tutor.md)。已经配置好环境，可双击 `启动.cmd`，或在项目目录运行：

```powershell
python -m rag_app serve
```

浏览器将打开本机页面。默认地址是 `http://127.0.0.1:8765`。关闭启动窗口会停止服务；已完成的问答保存在 `outputs`，再次启动后仍可查看。

## 页面怎么用

1. 查看左侧环境检查。Ollama 未连接时，先启动它，再点“重新检查”；缺少检索资料时，点“准备检索资料”。
2. 在“自由提问”中输入问题，点击“查找并回答”。每道题独立检索，不沿用之前的对话。
3. 阅读答案及其引用，点击页码打开论文。“检索过程”可以展开全部命中片段、页码和相似度；“实验中间结果”可以下载完整提示词及模型原始输出。
4. 需要交作业时，切换到“三题提交”，填入助教现场的三个问题。可勾选“不查论文的回答”进行对比。
5. 三题完成后逐题对照论文检查，勾选核对项并保存。全部通过后，点击“导出三题 JSON”。

引用匹配只证明引文出现在检索结果里，不能证明它支持答案。内容错误时应标记有误，不能为了导出直接确认。无依据的问题应说明资料不足；部分可答的问题应同时列出无法确定的部分。

## 配置与恢复

复制 `config.example.json` 为 `config.json` 后可修改配置。默认使用本地 Ollama `qwen3.5:9b` 与 BGE 检索模型。本轮优先保证答案与拒答质量，因此默认改为 9B。该模型本机文件约 6.6 GB，已在 16 GB 显存电脑验证；CPU 可以使用但速度未验收。轻量配置 `evaluation/config-lightweight.json` 保留 1.7B，实测有混淆事实的情况，不能沿用默认配置的验收结论。设备自动选择可用显卡或 CPU。第一次准备检索资料可能下载 BGE 模型；之后复用向量。

如果使用已有 Conda 环境，可在对应终端运行上面的启动命令，或在部署时指定 Conda 环境名：

```powershell
.\一键部署.ps1 -EnvName '你的Conda环境名'
```

- 页面无响应：确认启动窗口还开着，刷新页面。输入草稿保存在当前浏览器中。
- 某题失败或服务中途退出：重新启动后在“最近记录”找到该次提问，点击“重试未完成题目”。已成功的答案及其核对记录保留。此功能适用于新版网页创建的记录；旧版记录没有待办清单。
- 答案内容有误：标记有误，修改问题或模型配置后重新提问。重试按钮针对运行或引用失败，不自动重写已经成功生成的答案。
- 论文或切块配置变化：重建检索资料。历史问答仍对应当时的论文，正式提交请创建新记录。
- 缺少模型：在终端运行 `ollama pull qwen3.5:9b`。
- 端口被占用：运行 `python -m rag_app serve --port 8766`。

网页供本机单人使用，同一时间执行一项生成或索引任务，不提供公网多用户服务。模型下载需要网络；生成默认走本机 Ollama。修改 `ollama_base_url` 会改变数据发送位置。

## 命令行与验收

```powershell
python -m rag_app doctor
python -m rag_app index
python -m rag_app ask --question "TempQuestions 包含多少个时间问题？分成哪四类？" --compare
python -m rag_app chat
python -m rag_app batch --questions evaluation/questions.sample.json --compare
python -m pytest -q
```

`chat` 每输入一题立即回答和保存。CLI 的 review/export 参数见 [tutor.md](tutor.md)。CLI 批处理仍没有 `--resume`，恢复入口在网页。

本次逐项核查与运行证据见 [验收报告](planning/产品验收-2026-09-10.md)。原始要求在 `作业一/作业一作业要求.doc`。旧模型对比记录见 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)，其结论只对应当时参数。

## 打包给别人

保留 `一键部署.cmd`、`一键部署.ps1`、`一键部署说明.md`、`scripts/`、`作业一/`、`rag_app/`（含 `static/`）、`evaluation/`、`tests/`、`requirements*.txt`、`config.example.json`、`启动.cmd`、`启动.ps1`、`README.md` 和 `tutor.md`。可附 `planning/` 供验收，但它不会参与检索。已有 `data/index/` 可选打包，程序会验证论文与配置指纹。

不要发送个人 `config.json`、模型缓存、嵌套的旧压缩包或全部历史 `outputs/`。本目录原有 ZIP/RAR 没有随本次代码修改自动更新。
