# v0.1 CLI 详细用法

本文档是 `djx` 的命令参考手册，和当前 v0.1 代码行为保持一致。

## 1. 全局入口

```bash
djx --help
```

子命令：
- `plan`
- `apply`
- `trace`
- `templates`
- `evaluate`

## 2. `djx plan`

用途：生成结构化 Plan YAML。

### 2.1 基础语法

```bash
djx plan "<intent>" --dataset <path> --export <path> [options]
```

### 2.2 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `intent` | 位置参数 | 自然语言任务描述 |
| `--dataset` | string | 输入数据路径；在非 `--base-plan` 模式必填 |
| `--export` | string | 导出路径；在非 `--base-plan` 模式必填 |
| `--output` | string | 计划输出路径；缺省写入 `plans/<plan_id>.yaml` |
| `--base-plan` | string | 进入修订模式，基于已有 plan 迭代 |
| `--from-run-id` | string | 注入上一轮 run 上下文（仅 `--base-plan` 模式可用） |
| `--no-llm` | flag | 禁用 LLM（模板模式不打补丁；修订模式按 base plan 生成增量版本） |
| `--llm-full-plan` | flag | 完全由 LLM 生成 plan（不参考模板） |

### 2.3 约束

- `--llm-full-plan` 与 `--no-llm` 互斥。
- 未指定 `--base-plan` 时，`--dataset/--export` 必须提供。
- `--from-run-id` 只能和 `--base-plan` 一起使用。

### 2.4 常用示例

模板优先：

```bash
djx plan "clean rag corpus for retrieval" \
  --dataset data/demo-dataset.jsonl \
  --export data/out.jsonl \
  --output plans/plan-rag.yaml
```

纯 LLM 全量计划：

```bash
djx plan "deduplication" \
  --dataset data/demo-dataset.jsonl \
  --export data/out.jsonl \
  --output plans/plan-full-llm.yaml \
  --llm-full-plan
```

多轮修订（继承 base plan 的 dataset/export）：

```bash
djx plan "根据上轮结果收紧去重策略" \
  --base-plan plans/plan-rag.yaml \
  --from-run-id run_xxxxxxxxxxxx \
  --output plans/plan-rag-v2.yaml
```

## 3. `djx apply`

用途：执行 plan，并写入 trace。

### 3.1 基础语法

```bash
djx apply --plan <plan.yaml> [options]
```

### 3.2 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `--plan` | string | 计划文件路径 |
| `--yes` | flag | 跳过执行确认 |
| `--dry-run` | flag | 不实际执行 `dj-process` |
| `--timeout` | int | 执行超时秒数（必须 > 0） |

### 3.3 输出行为

执行结束后会在末尾输出：
- `Run Summary`
- `Run ID`
- `Status`
- `Trace command: djx trace <run_id>`

## 4. `djx trace`

用途：查看单次 run 详情，或按范围聚合统计。

### 4.1 基础语法

```bash
djx trace [run_id] [options]
```

### 4.2 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `run_id` | 位置参数 | 指定后查看该 run 详细信息 |
| `--stats` | flag | 输出聚合统计 JSON |
| `--plan-id` | string | 按 plan 过滤统计或列表 |
| `--limit` | int | `--plan-id` 列表模式下返回最近 N 条（必须 > 0） |

### 4.3 示例

查看单次执行：

```bash
djx trace run_a71d3b2ea1f0
```

全局统计：

```bash
djx trace --stats
```

按计划聚合：

```bash
djx trace --stats --plan-id plan_8e28219c0943
```

按计划列最近运行：

```bash
djx trace --plan-id plan_8e28219c0943 --limit 10
```

## 5. `djx templates`

用途：查看内置 workflow 模板。

### 5.1 语法

```bash
djx templates [name]
```

### 5.2 示例

```bash
djx templates
djx templates rag_cleaning
djx templates multimodal_dedup
```

## 6. `djx evaluate`

用途：批量离线评测规划/执行成功率。

### 6.1 基础语法

```bash
djx evaluate --cases <cases.jsonl> [options]
```

### 6.2 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `--cases` | string | JSONL 用例文件 |
| `--output` | string | 报告输出路径 |
| `--errors-output` | string | 错误分析输出路径 |
| `--execute` | enum | `none` / `dry-run` / `run` |
| `--timeout` | int | 每 case 超时秒数（> 0） |
| `--include-logs` | flag | 报告中包含 stdout/stderr |
| `--retries` | int | 执行失败重试次数（>= 0） |
| `--jobs` | int | 并发 worker 数（> 0） |
| `--failure-top-k` | int | Top-K 失败分桶（> 0） |
| `--history-file` | string | history jsonl 路径 |
| `--no-history` | flag | 不写 history |
| `--no-llm` | flag | 评测时禁用 LLM |
| `--llm-full-plan` | flag | 每个 case 都走 full-plan 模式 |

### 6.3 约束

- `--llm-full-plan` 与 `--no-llm` 互斥。
- `--timeout > 0`、`--jobs > 0`、`--failure-top-k > 0`、`--retries >= 0`。

### 6.4 示例

仅评估规划：

```bash
djx evaluate \
  --cases eval_cases/v0.1_baseline.jsonl \
  --execute none \
  --no-llm
```

真实执行评估：

```bash
djx evaluate \
  --cases eval_cases/v0.1_run_smoke.jsonl \
  --execute run \
  --jobs 2 \
  --timeout 120 \
  --retries 1
```

## 7. 环境变量（常用）

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | DashScope API Key |
| `DJA_PLANNER_MODEL` | Planner 模型名（默认 `qwen3-max-2026-01-23`） |
| `DJA_VALIDATOR_MODEL` | Validator 模型名（默认 `qwen3-max-2026-01-23`） |
| `DJA_OPENAI_BASE_URL` | OpenAI 兼容接口地址 |
| `DJA_LLM_THINKING` | 是否开启 thinking（`true/false`） |
| `DJA_MODEL_FALLBACKS` | 模型回退链（逗号分隔） |

## 8. 常见故障排查

- `Plan validation failed: unsupported operator ...`
- 检查本地 Data-Juicer 版本支持的算子；必要时重新 `plan`。

- `Run not found: run_xxx`
- 确认 `.djx/runs.jsonl` 中存在该 `run_id`，注意不要把 `plan_id` 当成 `run_id`。

- `Conflict: --llm-full-plan requires LLM`
- 移除 `--no-llm` 或取消 `--llm-full-plan`。
