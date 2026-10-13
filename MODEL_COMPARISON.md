# 本地生成模型对比记录

日期：2026-09-05。三种模型都使用同一份 `data/index`、同一个 BGE 查询编码器、`top_k=5`、同一套 RAG 提示词和 `evaluation/questions.sample.json`。每次运行都同时生成 RAG 与纯模型 baseline；模型响应、提示词、检索结果和耗时保存在对应的 `outputs/<run_id>/`。

## 实测结果

| 模型 | Ollama 体积 | 三题 RAG 结果 | 引用检查 | 总耗时（每题） | 结论 |
| --- | ---: | --- | --- | ---: | --- |
| `qwen3:1.7b` | 1.4 GB | 3/3 `answered` | 3/3 passed | 2.51 s / 4.73 s / 5.42 s | 当前默认，速度和结构化输出最稳定 |
| `qwen3.5:0.8b` | 1.0 GB | 0/3 可提交；q1/q3 生成失败，q2 错误拒答 | 失败或无效 | 12.07 s / 4.73 s / 1.02 s | 太小，不能满足本作业的 JSON 与引用约束 |
| `qwen3.5:9b` | 6.6 GB | 1/3 `answered`；q2/q3 被长度上限截断 | q1 passed，其他失败 | 20.21 s / 41.12 s / 48.16 s | 当前参数下不适合作业现场；体量大但没有稳定收益 |

对应记录：

- `qwen3:1.7b`：[`outputs/20260905-184415-181dfd/run.json`](outputs/20260905-184415-181dfd/run.json)
- `qwen3.5:0.8b`：[`outputs/20260905-183558-31a161/run.json`](outputs/20260905-183558-31a161/run.json)
- `qwen3.5:9b`：[`outputs/20260905-183318-08fb6e/run.json`](outputs/20260905-183318-08fb6e/run.json)

这里的“通过”只表示程序结构检查和本次人工核对结果通过，不能推导出未知问题上的准确率。`qwen3:1.7b` 的三题结果已人工对照论文登记为 passed；现场新问题仍必须逐题核对。

## 推荐与复现

默认配置保留为 `qwen3:1.7b`，原因是它在这台机器上真实完成三题、返回合法结构、引用能回指 Top-K，且单题耗时较短。模型只影响生成，不影响论文索引；切换模型时不需要重建 `data/index`。

```powershell
# 默认推荐
D:\miniconda\envs\qwen\python.exe -m rag_app batch --questions evaluation/questions.sample.json --compare

# 对比 0.8B
D:\miniconda\envs\qwen\python.exe -m rag_app --config evaluation/config-qwen35-08b.json batch --questions evaluation/questions.sample.json --compare

# 对比 9B
D:\miniconda\envs\qwen\python.exe -m rag_app --config evaluation/config-qwen35-9b.json batch --questions evaluation/questions.sample.json --compare
```

如果以后要重新评估 `qwen3.5:9b`，应先单独调大 `num_predict` 并重新跑三题，不能把本记录直接当成该模型的绝对上限。无论换成什么模型，都要检查 `status`、`citation_check`、`error` 和人工 `content_review`，不能只看答案文本。

模型标签和体积以本机 `ollama list` 及 [Ollama 的 Qwen3 标签页](https://ollama.com/library/qwen3/tags)、[Qwen3.5 标签页](https://ollama.com/library/qwen3.5/tags) 为准；不同量化、Ollama 版本或显卡可能得到不同耗时和输出。
