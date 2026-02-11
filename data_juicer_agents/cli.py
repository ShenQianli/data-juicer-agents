# -*- coding: utf-8 -*-
"""CLI entrypoint for Data-Juicer-Agents v0.1."""

from __future__ import annotations

import argparse
import sys

from data_juicer_agents.commands.apply_cmd import run_apply
from data_juicer_agents.commands.evaluate_cmd import run_evaluate
from data_juicer_agents.commands.plan_cmd import run_plan
from data_juicer_agents.commands.templates_cmd import run_templates
from data_juicer_agents.commands.trace_cmd import run_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="djx",
        description="Agentic CLI for Data-Juicer workflows (v0.1)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Generate a structured execution plan")
    plan.add_argument("intent", type=str, help="Natural language task intent")
    plan.add_argument("--dataset", default=None, help="Input dataset path")
    plan.add_argument("--export", default=None, help="Output jsonl path")
    plan.add_argument("--output", default=None, help="Output plan yaml path")
    plan.add_argument(
        "--base-plan",
        default=None,
        help="Base plan yaml path for revision mode",
    )
    plan.add_argument(
        "--from-run-id",
        default=None,
        help="Optional run_id context to guide revision",
    )
    plan.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable Qwen planning refinement and use template-only planning",
    )
    plan.add_argument(
        "--llm-full-plan",
        action="store_true",
        help="Generate full plan from LLM without using workflow templates",
    )
    plan.set_defaults(handler=run_plan)

    apply_cmd = sub.add_parser("apply", help="Apply a generated plan")
    apply_cmd.add_argument("--plan", required=True, help="Plan yaml path")
    apply_cmd.add_argument("--yes", action="store_true", help="Skip confirmation")
    apply_cmd.add_argument("--dry-run", action="store_true", help="Do not execute dj-process")
    apply_cmd.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Execution timeout in seconds",
    )
    apply_cmd.set_defaults(handler=run_apply)

    trace = sub.add_parser("trace", help="Replay one run trace")
    trace.add_argument("run_id", nargs="?", default=None, help="Run id from apply output")
    trace.add_argument(
        "--plan-id",
        default=None,
        help="Filter trace records by plan_id",
    )
    trace.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Limit records for --plan-id listing",
    )
    trace.add_argument("--stats", action="store_true", help="Show aggregated trace statistics")
    trace.set_defaults(handler=run_trace)

    templates = sub.add_parser("templates", help="List or show workflow templates")
    templates.add_argument("name", nargs="?", default=None, help="Optional template name")
    templates.set_defaults(handler=run_templates)

    evaluate = sub.add_parser("evaluate", help="Run offline evaluation cases and report success rates")
    evaluate.add_argument("--cases", required=True, help="Path to JSONL evaluation cases")
    evaluate.add_argument("--output", default=None, help="Output report path")
    evaluate.add_argument(
        "--errors-output",
        default=None,
        help="Output path for error/misroute analysis JSON",
    )
    evaluate.add_argument(
        "--execute",
        choices=["none", "dry-run", "run"],
        default="none",
        help="Execution mode for valid plans: none, dry-run, or run",
    )
    evaluate.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Execution timeout in seconds for each case",
    )
    evaluate.add_argument(
        "--include-logs",
        action="store_true",
        help="Include stdout/stderr in evaluation report",
    )
    evaluate.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Retry count for failed executions in dry-run/run mode",
    )
    evaluate.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel workers for evaluation cases",
    )
    evaluate.add_argument(
        "--failure-top-k",
        type=int,
        default=5,
        help="Top-K failure buckets in evaluation summary",
    )
    evaluate.add_argument(
        "--history-file",
        default=None,
        help="Path to evaluation history jsonl",
    )
    evaluate.add_argument(
        "--no-history",
        action="store_true",
        help="Disable appending evaluation history",
    )
    evaluate.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM during evaluation planning",
    )
    evaluate.add_argument(
        "--llm-full-plan",
        action="store_true",
        help="Use full LLM planning mode (no template reference) for each case",
    )
    evaluate.set_defaults(handler=run_evaluate)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
