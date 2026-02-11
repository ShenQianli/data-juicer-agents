# -*- coding: utf-8 -*-
"""Validator agent for plan sanity checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from data_juicer_agents.utils.llm_utils import call_model_json
from data_juicer_agents.tools.operator_registry import get_available_operator_names
from data_juicer_agents.core.schemas import PlanModel, validate_plan


VALIDATOR_MODEL_NAME = os.environ.get("DJA_VALIDATOR_MODEL", "qwen3-max-2026-01-23")


class ValidatorAgent:
    """Validate plan schema and local filesystem preconditions."""

    @staticmethod
    def validate(plan: PlanModel) -> List[str]:
        errors = validate_plan(plan)

        dataset_path = Path(plan.dataset_path)
        if not dataset_path.exists():
            errors.append(f"dataset_path does not exist: {plan.dataset_path}")

        export_parent = Path(plan.export_path).expanduser().resolve().parent
        if not export_parent.exists():
            errors.append(
                f"export parent directory does not exist: {export_parent}",
            )

        if plan.modality == "text" and not plan.text_keys:
            errors.append("text modality requires text_keys")

        if plan.modality == "image" and not plan.image_key:
            errors.append("image modality requires image_key")

        if plan.modality == "multimodal":
            if not plan.text_keys:
                errors.append("multimodal modality requires text_keys")
            if not plan.image_key:
                errors.append("multimodal modality requires image_key")

        # Validate operator names against installed Data-Juicer operator registry.
        available_ops = get_available_operator_names()
        if available_ops:
            unknown_ops = [
                op.name for op in plan.operators if op.name not in available_ops
            ]
            for op_name in unknown_ops:
                errors.append(
                    f"unsupported operator '{op_name}'; not found in installed Data-Juicer operators"
                )

        return errors

    @staticmethod
    def llm_review(plan: PlanModel) -> Dict[str, List[str]]:
        """Best-effort semantic review; returns warnings/errors from model."""

        prompt = (
            "You validate Data-Juicer plans for data engineers. "
            "Return JSON only: {errors: string[], warnings: string[]} with concise items. "
            "If no issue, return empty arrays.\n"
            f"Plan JSON:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}"
        )

        try:
            data = call_model_json(VALIDATOR_MODEL_NAME, prompt)
            errors = data.get("errors", []) if isinstance(data, dict) else []
            warnings = data.get("warnings", []) if isinstance(data, dict) else []
            if not isinstance(errors, list):
                errors = []
            if not isinstance(warnings, list):
                warnings = []
            return {
                "errors": [str(item) for item in errors],
                "warnings": [str(item) for item in warnings],
            }
        except Exception:
            return {"errors": [], "warnings": []}
