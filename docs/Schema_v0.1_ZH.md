# v0.1 Schema 详细定义

本文档描述 `data_juicer_agents` v0.1 的核心数据结构与字段约束，覆盖：
- Plan Schema（`djx plan` 输出 YAML）
- Run Trace Schema（`.djx/runs.jsonl`）
- Evaluate Report Schema（`djx evaluate` 输出 JSON）

## 1. Plan Schema

Plan 是 `djx apply` 的输入。建议始终通过 `djx plan` 生成，不手写。

### 1.1 字段定义

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plan_id` | `string` | 是 | 计划唯一标识，格式一般为 `plan_<12hex>` |
| `user_intent` | `string` | 是 | 本轮自然语言目标 |
| `workflow` | `string` | 是 | `rag_cleaning` / `multimodal_dedup` / `custom` |
| `dataset_path` | `string` | 是 | 输入数据路径 |
| `export_path` | `string` | 是 | 导出数据路径 |
| `modality` | `string` | 是 | `text` / `image` / `multimodal` / `unknown` |
| `text_keys` | `string[]` | 否 | 文本字段列表，`text` 或 `multimodal` 通常需要 |
| `image_key` | `string \| null` | 否 | 图像字段名，`image` 或 `multimodal` 通常需要 |
| `operators` | `OperatorStep[]` | 是 | 算子序列，不能为空 |
| `risk_notes` | `string[]` | 否 | 风险提示 |
| `estimation` | `object` | 否 | 规模/耗时估计 |
| `parent_plan_id` | `string \| null` | 否 | 修订链路父计划 ID |
| `revision` | `integer` | 是 | 修订版本，`>= 1`，首版通常为 `1` |
| `change_summary` | `string[]` | 否 | 相对父计划的变化摘要 |
| `approval_required` | `boolean` | 是 | 是否需要确认，默认 `true` |
| `created_at` | `string` | 是 | ISO8601 时间戳（UTC） |

`OperatorStep` 结构：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | `string` | 是 | Data-Juicer 算子名 |
| `params` | `object` | 是 | 算子参数 |

### 1.2 关键校验规则

- `workflow` 必须属于 `{rag_cleaning, multimodal_dedup, custom}`。
- `modality` 必须属于 `{text, image, multimodal, unknown}`。
- `revision >= 1`。
- `operators` 不能为空，且每个算子必须有 `name` 和 `object` 类型的 `params`。
- `dataset_path` 必须存在。
- `export_path` 的父目录必须存在。
- 算子名必须在本地已安装 Data-Juicer 注册表中可用（支持通用名称规范化，如 CamelCase -> snake_case）。
- 字段约束由 `modality` 驱动：
- `text` 要求 `text_keys`。
- `image` 要求 `image_key`。
- `multimodal` 要求同时有 `text_keys` 和 `image_key`。

### 1.3 Plan 示例

```yaml
plan_id: plan_d3d482c7b5fd
user_intent: deduplication
workflow: custom
dataset_path: data/demo-dataset.jsonl
export_path: data/tmp-llm-full-out.jsonl
modality: text
text_keys:
  - text
image_key: null
operators:
  - name: document_deduplicator
    params:
      text_key: text
      keep_first: true
      dedup_by: exact
risk_notes: []
estimation: {}
parent_plan_id: null
revision: 1
change_summary: []
approval_required: true
created_at: "2026-02-11T06:24:31.366774+00:00"
```

## 2. Run Trace Schema

Run Trace 是每次 `djx apply`（以及 `evaluate --execute dry-run/run`）执行后落盘的记录。

默认存储路径：`.djx/runs.jsonl`（每行一条 JSON）。

### 2.1 字段定义

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `run_id` | `string` | 是 | 本次执行 ID，格式一般为 `run_<12hex>` |
| `plan_id` | `string` | 是 | 执行所用计划 ID |
| `start_time` | `string` | 是 | ISO8601 时间戳 |
| `end_time` | `string` | 是 | ISO8601 时间戳 |
| `duration_seconds` | `number` | 是 | 执行耗时（秒） |
| `model_info` | `object` | 是 | 规划/校验/执行模型信息 |
| `retrieval_mode` | `string` | 是 | 路由模式标识 |
| `selected_workflow` | `string` | 是 | 运行时 workflow |
| `generated_recipe_path` | `string` | 是 | 生成的 DJ recipe 路径 |
| `command` | `string` | 是 | 实际执行命令 |
| `status` | `string` | 是 | `success` 或 `failed` |
| `artifacts` | `object` | 是 | 产物信息（例如 `export_path`） |
| `error_type` | `string` | 是 | 标准化错误类型 |
| `error_message` | `string` | 是 | 错误详情 |
| `retry_level` | `string` | 是 | 建议重试级别 |
| `next_actions` | `string[]` | 是 | 建议下一步动作 |

### 2.2 Trace 统计输出（`djx trace --stats`）

统计结构包含：
- `total_runs`
- `success_runs`
- `failed_runs`
- `execution_success_rate`
- `avg_duration_seconds`
- `plan_id`（当使用 `--plan-id` 过滤时为该值，否则为 `null`）
- `by_workflow`
- `by_error_type`

## 3. Evaluate Report Schema

`djx evaluate` 默认输出：
- 报告：`.djx/eval_report.json`
- 错误分析：`.djx/eval_errors.json`

### 3.1 `eval_report.json` 结构

顶层字段：
- `summary`: 汇总指标
- `results`: 每条 case 的评测结果

`summary` 常见字段：
- `total`
- `execution_mode`（`none`/`dry-run`/`run`）
- `jobs`
- `retries`
- `plan_valid`
- `execution_success`
- `task_success`
- `plan_valid_rate`
- `execution_success_rate`
- `task_success_rate`
- `retry_used_cases`
- `error_case_count`
- `failure_buckets_topk`

`results[i]` 常见字段：
- `index`
- `intent`
- `expected_workflow`
- `status`（`plan_valid`/`plan_invalid`/`planner_error` 等）
- `errors`
- `attempts`
- `plan_id`（若规划成功）
- `workflow`（若规划成功）
- `modality`（若规划成功）
- `execution_status`（`success`/`failed`/`skipped`）
- `task_success`（布尔）

## 4. 兼容与演进建议

- 增加字段时优先“向后兼容新增”，避免删除已存在字段。
- 修改枚举值前，先同步 `validate_plan`、CLI 文档与评测脚本。
- 涉及多轮计划字段（`parent_plan_id/revision/change_summary`）的变更，建议同步更新 trace 聚合与 notebook 示例。
