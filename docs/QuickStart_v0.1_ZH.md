# v0.1 快速开始（Agentic CLI）

本文档面向 `data_juicer_agents` v0.1 新命令面：`djx plan/apply/trace/evaluate`。

## 1. 环境准备

- Python `3.10+`
- 已安装 Data-Juicer（确保 `dj-process` 可用）
- DashScope API Key（使用 LLM 规划时需要）
- v0.1 默认规划模型：`qwen3-max-2026-01-23`（开启 thinking）

```bash
export DASHSCOPE_API_KEY="<your-key>"
```

可选：配置 OpenAI 兼容接口参数（默认是 DashScope 兼容地址 + thinking 开启）：

```bash
export DJA_OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export DJA_LLM_THINKING="true"
```

可选：当默认模型在当前账号下不可用时，可配置回退模型列表（按顺序尝试）：

```bash
export DJA_MODEL_FALLBACKS="qwen-max,qwen-plus,qwen-turbo"
```

安装：

```bash
uv pip install -e .
```

验证 CLI：

```bash
djx --help
```

## 2. 数据路径规范

v0.1 约定评测与示例数据统一放在 `data/` 目录：

- `data/demo-dataset.jsonl`
- `data/demo-dataset-images.jsonl`

`eval_cases/*.jsonl` 中的 `dataset_path` 建议统一使用 `data/...` 相对路径。

## 3. 生成执行计划

```bash
djx plan "clean rag corpus for retrieval" \
  --dataset data/demo-dataset.jsonl \
  --export data/out-rag.jsonl \
  --output plans/plan-rag.yaml
```

默认模式是“模板优先 + LLM 补丁”：先选中内置 workflow 模板，再由 LLM 微调算子参数。

如果想禁用 LLM 规划补丁：

```bash
djx plan "clean rag corpus for retrieval" \
  --dataset data/demo-dataset.jsonl \
  --export data/out-rag.jsonl \
  --output plans/plan-rag.yaml \
  --no-llm
```

如果希望完全不参考模板、直接由 LLM 生成整个计划结构：

```bash
djx plan "clean rag corpus for retrieval" \
  --dataset data/demo-dataset.jsonl \
  --export data/out-rag.jsonl \
  --output plans/plan-rag-full-llm.yaml \
  --llm-full-plan
```

注意：
- `--llm-full-plan` 不能和 `--no-llm` 同时使用。
- `--llm-full-plan` 下如果 LLM 输出不满足 schema，会直接失败并返回错误（不会回退模板）。
- `--llm-full-plan` 下 `workflow` 固定为 `custom`（避免与模板映射语义混淆）。
- 字段约束改由 `modality` 驱动：`text` 需要 `text_keys`，`image` 需要 `image_key`，`multimodal` 需要两者。
- `--llm-full-plan` 现采用最小 ReAct 规划代理（含 `suggest_workflow` / `get_workflow_template` / `validate_operator_sequence` / `inspect_dataset` / `list_available_operators` 工具），不需要额外 GitHub Token。
- `plan` 阶段可通过 `inspect_dataset` 工具读取少量样本，自动推断 `text_keys` / `image_key` 与数据模态。
- `plan` 阶段会对照本地已安装 Data-Juicer 算子表校验算子名，未知算子会被拒绝。
- 对命名风格不同但语义一致的算子名（如 `DocumentMinHashDeduplicator`），会先做通用规范化映射后再校验。

多轮迭代（基于已有 plan 修订）：

```bash
djx plan "根据上轮结果收紧去重策略" \
  --base-plan plans/plan-rag.yaml \
  --from-run-id run_xxxxxxxxxxxx \
  --output plans/plan-rag-v2.yaml
```

说明：
- `--base-plan` 模式下，`dataset/export` 默认继承 base plan，可按需覆盖。
- `--from-run-id` 仅用于 `--base-plan` 修订模式，会把上一轮 run 的错误上下文注入规划。
- 生成的新 plan 会写入版本链路字段：`parent_plan_id`、`revision`、`change_summary`。

## 4. 执行计划

先确认后执行：

```bash
djx apply --plan plans/plan-rag.yaml
```

跳过确认：

```bash
djx apply --plan plans/plan-rag.yaml --yes
```

仅试跑（不执行 `dj-process`）：

```bash
djx apply --plan plans/plan-rag.yaml --yes --dry-run
```

超时控制（秒）：

```bash
djx apply --plan plans/plan-rag.yaml --yes --timeout 300
```

## 5. 查看运行追踪

查看某次 run：

```bash
djx trace <run_id>
```

查看统计：

```bash
djx trace --stats
```

按 `plan_id` 查看统计：

```bash
djx trace --stats --plan-id plan_xxxxxxxxxxxx
```

按 `plan_id` 查看最近运行列表：

```bash
djx trace --plan-id plan_xxxxxxxxxxxx --limit 10
```

## 6. 离线评测

使用内置评测集：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --execute none \
  --no-llm
```

使用全量 LLM 规划模式评测（每个 case 都不走模板）：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --execute none \
  --llm-full-plan
```

注意：
- `evaluate` 下同样不允许 `--no-llm --llm-full-plan` 组合。

`--execute` 模式：

- `none`：只评测规划与路由
- `dry-run`：评测执行链路但不实际运行 `dj-process`
- `run`：真实执行

并发、重试和超时：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --execute run \
  --jobs 4 \
  --retries 1 \
  --timeout 300
```

报告输出：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --output .djx/eval_report.json \
  --errors-output .djx/eval_errors.json
```

失败分桶 Top-K：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --failure-top-k 5
```

## 7. 模板查看

```bash
djx templates
```

查看单个模板：

```bash
djx templates rag_cleaning
```

## 8. 常见问题

`dj-process: command not found`：
- 说明 Data-Juicer CLI 未安装或未在 `PATH` 中。
- 先执行 `which dj-process` 检查。

`unsupported_operator`：
- 当前 Data-Juicer 版本不支持某些算子。
- 更新 workflow 模板或升级 Data-Juicer 版本。

`dataset_path does not exist`：
- 检查 `plan` 或 `eval_cases` 中路径是否在当前工作目录可访问。
