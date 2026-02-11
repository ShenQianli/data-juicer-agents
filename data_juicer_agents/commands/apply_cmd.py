# -*- coding: utf-8 -*-
"""Implementation for `djx apply`."""

from __future__ import annotations

from pathlib import Path

import yaml

from data_juicer_agents.agents.executor_agent import ExecutorAgent
from data_juicer_agents.core.schemas import PlanModel
from data_juicer_agents.agents.validator_agent import ValidatorAgent
from data_juicer_agents.runtime.trace_store import TraceStore


def _confirm(plan: PlanModel) -> bool:
    print(f"About to execute plan: {plan.plan_id}")
    print(f"Workflow: {plan.workflow}")
    print(f"Dataset: {plan.dataset_path}")
    print(f"Export: {plan.export_path}")
    answer = input("Proceed? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def run_apply(args) -> int:
    if args.timeout <= 0:
        print("timeout must be > 0")
        return 2

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"Plan file not found: {plan_path}")
        return 2

    with open(plan_path, "r", encoding="utf-8") as f:
        plan_data = yaml.safe_load(f)

    plan = PlanModel.from_dict(plan_data)

    errors = ValidatorAgent.validate(plan)
    if errors:
        print("Plan validation failed:")
        for item in errors:
            print(f"- {item}")
        return 2

    if not args.yes and not _confirm(plan):
        print("Execution canceled")
        return 1

    runtime_dir = Path(".djx") / "recipes"
    executor = ExecutorAgent()
    trace, returncode, stdout, stderr = executor.execute(
        plan=plan,
        runtime_dir=runtime_dir,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
    )

    store = TraceStore()
    store.save(trace)

    if stdout:
        print("STDOUT:")
        print(stdout)
    if stderr:
        print("STDERR:")
        print(stderr)
    print("Run Summary:")
    print(f"Run ID: {trace.run_id}")
    print(f"Status: {trace.status}")
    print(f"Trace command: djx trace {trace.run_id}")

    return returncode
