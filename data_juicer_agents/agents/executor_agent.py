# -*- coding: utf-8 -*-
"""Executor agent for deterministic Data-Juicer execution."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import yaml

from data_juicer_agents.core.schemas import PlanModel, RunTraceModel


_DEFAULT_PLANNER_MODEL = os.environ.get("DJA_PLANNER_MODEL", "qwen3-max-2026-01-23")
_DEFAULT_VALIDATOR_MODEL = os.environ.get("DJA_VALIDATOR_MODEL", "qwen3-max-2026-01-23")


def _classify_error(returncode: int, stderr: str) -> tuple[str, str, List[str]]:
    if returncode == 0:
        return "none", "none", []

    msg = (stderr or "").lower()

    if "command not found" in msg or "not recognized" in msg:
        return "missing_command", "high", [
            "Install Data-Juicer CLI and verify dj-process is in PATH",
            "Run `which dj-process` to verify environment",
        ]

    if "no such file or directory" in msg:
        return "missing_path", "medium", [
            "Check dataset_path and export_path in plan",
            "Ensure recipe file path exists and is readable",
        ]

    if "permission denied" in msg:
        return "permission_denied", "high", [
            "Fix file or directory permissions",
            "Retry with a writable export path",
        ]

    if "keyerror" in msg and "operators.modules" in msg:
        return "unsupported_operator", "high", [
            "Check workflow operator names against installed Data-Juicer version",
            "Regenerate plan with supported operators",
        ]

    if "keyerror:" in msg and ("_mapper" in msg or "_deduplicator" in msg):
        return "unsupported_operator", "high", [
            "Operator missing in current Data-Juicer installation",
            "Replace unsupported operator and retry",
        ]

    if "timeout" in msg:
        return "timeout", "medium", [
            "Reduce dataset size and retry",
            "Increase execution timeout in future versions",
        ]

    return "command_failed", "low", [
        "Inspect stderr details",
        "Adjust operator parameters and retry",
    ]


class ExecutorAgent:
    """Execute validated plans and generate run traces."""

    @staticmethod
    def _write_recipe(plan: PlanModel, runtime_dir: Path) -> Path:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        recipe_path = runtime_dir / f"{plan.plan_id}.yaml"
        recipe = {
            "project_name": plan.plan_id,
            "dataset_path": plan.dataset_path,
            "export_path": plan.export_path,
            "text_keys": plan.text_keys,
            "image_key": plan.image_key,
            "np": 1,
            "skip_op_error": False,
            "process": [{step.name: step.params} for step in plan.operators],
        }
        with open(recipe_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(recipe, f, allow_unicode=False, sort_keys=False)
        return recipe_path

    def execute(
        self,
        plan: PlanModel,
        runtime_dir: Path,
        dry_run: bool = False,
        timeout_seconds: int = 300,
        command_override: str | None = None,
    ) -> Tuple[RunTraceModel, int, str, str]:
        recipe_path = self._write_recipe(plan, runtime_dir)
        command = command_override or f"dj-process --config {recipe_path}"

        start_dt = datetime.now(timezone.utc)

        if dry_run:
            returncode = 0
            stdout = "dry-run: command not executed"
            stderr = ""
        else:
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                returncode = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                returncode = 124
                stdout = exc.stdout or ""
                stderr = (exc.stderr or "") + f"\nTimeout after {timeout_seconds}s"

        end_dt = datetime.now(timezone.utc)
        duration = (end_dt - start_dt).total_seconds()
        status = "success" if returncode == 0 else "failed"
        error_type, retry_level, next_actions = _classify_error(returncode, stderr)

        trace = RunTraceModel(
            run_id=RunTraceModel.new_id(),
            plan_id=plan.plan_id,
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            duration_seconds=duration,
            model_info={
                "planner": _DEFAULT_PLANNER_MODEL,
                "validator": _DEFAULT_VALIDATOR_MODEL,
                "executor": "deterministic-cli",
            },
            retrieval_mode="workflow-first",
            selected_workflow=plan.workflow,
            generated_recipe_path=str(recipe_path),
            command=command,
            status=status,
            artifacts={"export_path": plan.export_path},
            error_type=error_type,
            error_message="" if returncode == 0 else stderr.strip(),
            retry_level=retry_level,
            next_actions=next_actions,
        )

        return trace, returncode, stdout, stderr
