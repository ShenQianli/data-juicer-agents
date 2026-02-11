# -*- coding: utf-8 -*-
"""Implementation for `djx plan`."""

from __future__ import annotations

from pathlib import Path

import yaml

from data_juicer_agents.utils.plan_diff import build_plan_diff
from data_juicer_agents.agents.planner_agent import PlannerAgent, default_workflows_dir
from data_juicer_agents.core.schemas import PlanModel
from data_juicer_agents.agents.validator_agent import ValidatorAgent
from data_juicer_agents.runtime.trace_store import TraceStore


def _print_plan_diff(diff: dict) -> None:
    field_changes = diff.get("field_changes", {})
    metadata_changes = diff.get("metadata_changes", {})
    operators = diff.get("operators", {})

    if not field_changes and not metadata_changes and not operators.get("added") and not operators.get("removed") and not operators.get("order_changed"):
        print("Plan diff: no effective changes")
        return

    print("Plan diff:")
    for key, item in field_changes.items():
        print(f"- {key}: {item.get('old')} -> {item.get('new')}")
    for op in operators.get("added", []):
        print(f"- operators added: {op.get('name')}")
    for op in operators.get("removed", []):
        print(f"- operators removed: {op.get('name')}")
    if operators.get("order_changed"):
        print("- operators order changed")
    for key in metadata_changes.keys():
        print(f"- {key} updated")


def run_plan(args) -> int:
    if args.no_llm and args.llm_full_plan:
        print("Conflict: --llm-full-plan requires LLM. Remove --no-llm.")
        return 2

    base_plan = None
    if args.base_plan:
        base_path = Path(args.base_plan)
        if not base_path.exists():
            print(f"Base plan file not found: {base_path}")
            return 2
        with open(base_path, "r", encoding="utf-8") as f:
            base_plan = PlanModel.from_dict(yaml.safe_load(f))

    dataset_path = args.dataset
    export_path = args.export
    if base_plan is not None:
        if not dataset_path:
            dataset_path = base_plan.dataset_path
        if not export_path:
            export_path = base_plan.export_path
    else:
        if not dataset_path or not export_path:
            print("--dataset and --export are required when --base-plan is not provided.")
            return 2

    run_context = None
    if args.from_run_id:
        if base_plan is None:
            print("--from-run-id requires --base-plan.")
            return 2
        store = TraceStore()
        run_context = store.get(args.from_run_id)
        if run_context is None:
            print(f"Run not found: {args.from_run_id}")
            return 2
        if base_plan and run_context.get("plan_id") != base_plan.plan_id:
            print(
                "Warning: --from-run-id plan_id differs from --base-plan "
                f"({run_context.get('plan_id')} != {base_plan.plan_id})"
            )

    planner = PlannerAgent(
        default_workflows_dir(),
        use_llm=not args.no_llm,
        llm_full_plan=args.llm_full_plan,
    )
    try:
        plan = planner.build_plan(
            user_intent=args.intent,
            dataset_path=dataset_path,
            export_path=export_path,
            base_plan=base_plan,
            run_context=run_context,
        )
    except Exception as exc:
        print(f"Plan generation failed: {exc}")
        return 2

    errors = ValidatorAgent.validate(plan)
    if not args.no_llm:
        review = ValidatorAgent.llm_review(plan)
        errors.extend(review.get("errors", []))
    else:
        review = {"warnings": []}

    if errors:
        print("Plan validation failed:")
        for item in errors:
            print(f"- {item}")
        return 2

    output_path = Path(args.output) if args.output else Path("plans") / f"{plan.plan_id}.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan.to_dict(), f, allow_unicode=False, sort_keys=False)

    print(f"Plan generated: {output_path}")
    print(f"Workflow: {plan.workflow}")
    print(f"Operators: {[op.name for op in plan.operators]}")
    print(f"Revision: {plan.revision}")
    if plan.parent_plan_id:
        print(f"Parent Plan: {plan.parent_plan_id}")
    if plan.change_summary:
        print("Change Summary:")
        for line in plan.change_summary:
            print(f"- {line}")
    if base_plan:
        _print_plan_diff(build_plan_diff(base_plan, plan))
    print(
        "Planning meta: "
        f"strategy={planner.last_plan_meta.get('strategy')}, "
        f"plan_mode={planner.last_plan_meta.get('plan_mode')}, "
        f"llm_used={planner.last_plan_meta.get('llm_used')}, "
        f"llm_fallback={planner.last_plan_meta.get('llm_fallback')}"
    )
    for warning in review.get("warnings", []):
        print(f"Warning: {warning}")
    return 0
