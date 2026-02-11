# -*- coding: utf-8 -*-
"""Planner agent for building structured execution plans."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from data_juicer_agents.utils.llm_utils import call_model_json
from data_juicer_agents.tools.operator_registry import (
    get_available_operator_names,
    resolve_operator_name,
)
from data_juicer_agents.utils.plan_diff import build_plan_diff, summarize_plan_diff
from data_juicer_agents.agents.react_planner_agent import run_react_full_plan
from data_juicer_agents.core.schemas import OperatorStep, PlanModel
from data_juicer_agents.tools.router_helpers import explain_routing, select_workflow


PLANNER_MODEL_NAME = os.environ.get("DJA_PLANNER_MODEL", "qwen3-max-2026-01-23")
_ALLOWED_WORKFLOWS = {"rag_cleaning", "multimodal_dedup", "custom"}


class PlannerAgent:
    """Create plans using workflow templates and optional LLM planning modes."""

    def __init__(
        self,
        workflows_dir: Path,
        use_llm: bool = True,
        llm_full_plan: bool = False,
    ):
        self.workflows_dir = workflows_dir
        self.use_llm = use_llm
        self.llm_full_plan = llm_full_plan
        self.last_plan_meta: Dict[str, str] = {
            "strategy": "workflow-template",
            "llm_used": "false",
            "llm_fallback": "false",
            "plan_mode": "template",
        }

    def _load_template(self, workflow: str) -> Dict:
        template_path = self.workflows_dir / f"{workflow}.yaml"
        with open(template_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def _normalize_workflow(value: str) -> str:
        workflow = str(value or "").strip()
        if workflow in _ALLOWED_WORKFLOWS:
            return workflow
        return "custom"

    @staticmethod
    def _infer_modality(
        text_keys: List[str] | None,
        image_key: str | None,
        generated_modality: str | None = None,
    ) -> str:
        if generated_modality in {"text", "image", "multimodal", "unknown"}:
            return generated_modality
        has_text = bool(text_keys)
        has_image = bool(image_key)
        if has_text and has_image:
            return "multimodal"
        if has_image:
            return "image"
        if has_text:
            return "text"
        return "unknown"

    @staticmethod
    def _parse_operator_steps(raw_ops: object) -> List[OperatorStep]:
        if not isinstance(raw_ops, list):
            return []
        available_ops = get_available_operator_names()
        parsed: List[OperatorStep] = []
        for item in raw_ops:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name", "")).strip()
            name = resolve_operator_name(raw_name, available_ops=available_ops)
            params = item.get("params", {})
            if not name or not isinstance(params, dict):
                continue
            parsed.append(OperatorStep(name=name, params=params))
        return parsed

    @staticmethod
    def _plan_from_template(
        user_intent: str,
        workflow: str,
        template: Dict,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None,
        image_key: str | None,
    ) -> PlanModel:
        operators = [
            OperatorStep(name=item["name"], params=item.get("params", {}))
            for item in template.get("operators", [])
        ]

        if not export_path:
            export_path = template.get("default_export_path", "./output/result.jsonl")

        if not text_keys:
            text_keys = template.get("default_text_keys", ["text"])

        if not image_key:
            image_key = template.get("default_image_key")

        if not dataset_path:
            raise ValueError("dataset_path is required")

        return PlanModel(
            plan_id=PlanModel.new_id(),
            user_intent=user_intent,
            workflow=workflow,
            dataset_path=dataset_path,
            export_path=export_path,
            modality=PlannerAgent._infer_modality(
                text_keys=text_keys,
                image_key=image_key,
                generated_modality=template.get("default_modality"),
            ),
            text_keys=text_keys,
            image_key=image_key,
            operators=operators,
            risk_notes=list(template.get("risk_notes", [])),
            estimation=dict(template.get("estimation", {})),
            approval_required=True,
        )

    @staticmethod
    def _apply_patch(base: PlanModel, patch: Dict) -> PlanModel:
        # Keep critical fields deterministic and only patch safe mutable fields.
        text_keys = patch.get("text_keys", base.text_keys)
        image_key = patch.get("image_key", base.image_key)
        risk_notes = patch.get("risk_notes", base.risk_notes)
        estimation = patch.get("estimation", base.estimation)

        patched_ops = PlannerAgent._parse_operator_steps(patch.get("operators"))
        if not patched_ops:
            patched_ops = base.operators

        return PlanModel(
            plan_id=base.plan_id,
            user_intent=base.user_intent,
            workflow=base.workflow,
            dataset_path=base.dataset_path,
            export_path=base.export_path,
            modality=PlannerAgent._infer_modality(
                text_keys=text_keys,
                image_key=image_key,
                generated_modality=patch.get("modality", base.modality),
            ),
            text_keys=text_keys,
            image_key=image_key,
            operators=patched_ops,
            risk_notes=list(risk_notes),
            estimation=dict(estimation),
            approval_required=base.approval_required,
            created_at=base.created_at,
        )

    def _build_patch_prompt(self, base_plan: PlanModel) -> str:
        return (
            "You are a planning assistant for Data-Juicer.\n"
            "Refine the given plan but keep it executable and concise.\n"
            "Return JSON only with optional fields: text_keys, image_key, operators, risk_notes, estimation.\n"
            "optional modality field: text/image/multimodal/unknown.\n"
            "operators must be an array of objects: {name: string, params: object}.\n"
            "Do not include markdown or explanations.\n\n"
            f"Base plan:\n{json.dumps(base_plan.to_dict(), ensure_ascii=False)}\n"
        )

    def _build_revision_patch_prompt(
        self,
        base_plan: PlanModel,
        user_intent: str,
        run_context: Dict[str, Any] | None,
    ) -> str:
        return (
            "You are editing an existing Data-Juicer execution plan for the next iteration.\n"
            "Return JSON only with optional keys: workflow, modality, text_keys, image_key, operators, risk_notes, estimation, change_summary.\n"
            "operators must be an array of {name: string, params: object}.\n"
            "change_summary should be a concise list of what changed and why.\n"
            "Keep dataset_path/export_path unchanged unless absolutely necessary.\n"
            "Do not include markdown or explanations.\n\n"
            f"user_intent: {user_intent}\n"
            f"base_plan:\n{json.dumps(base_plan.to_dict(), ensure_ascii=False)}\n"
            f"last_run_context:\n{json.dumps(run_context or {}, ensure_ascii=False)}\n"
        )

    def _build_full_plan_prompt(
        self,
        user_intent: str,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None,
        image_key: str | None,
    ) -> str:
        return (
            "You are a Data-Juicer planning assistant.\n"
            "Generate a complete execution plan from scratch, without template references.\n"
            "Return JSON only with keys: workflow, modality, text_keys, image_key, operators, risk_notes, estimation.\n"
            "workflow should be custom in this mode.\n"
            "modality must be one of: text, image, multimodal, unknown.\n"
            "operators must be a non-empty array: [{\"name\": str, \"params\": object}].\n"
            "Do not include markdown or explanation text.\n"
            "Use the provided dataset_path/export_path context when deciding fields and operators.\n\n"
            f"intent: {user_intent}\n"
            f"dataset_path: {dataset_path}\n"
            f"export_path: {export_path}\n"
            f"text_keys_hint: {json.dumps(text_keys or [], ensure_ascii=False)}\n"
            f"image_key_hint: {image_key or ''}\n"
        )

    def _plan_from_llm_full(
        self,
        user_intent: str,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None,
        image_key: str | None,
    ) -> PlanModel:
        if not dataset_path:
            raise ValueError("dataset_path is required")

        generated = run_react_full_plan(
            workflows_dir=self.workflows_dir,
            model_name=PLANNER_MODEL_NAME,
            user_intent=user_intent,
            dataset_path=dataset_path,
            export_path=export_path,
            text_keys=text_keys,
            image_key=image_key,
        )
        if not isinstance(generated, dict):
            raise ValueError("LLM full-plan output must be a JSON object")

        # In llm_full_plan mode, workflow is treated as template namespace only.
        # Pure LLM plans should remain "custom" to avoid template coupling ambiguity.
        workflow = "custom"

        llm_text_keys = generated.get("text_keys", [])
        if not isinstance(llm_text_keys, list):
            llm_text_keys = []
        final_text_keys = text_keys if text_keys else llm_text_keys

        llm_image_key = generated.get("image_key")
        final_image_key = image_key if image_key else llm_image_key
        final_modality = self._infer_modality(
            text_keys=final_text_keys,
            image_key=final_image_key,
            generated_modality=generated.get("modality"),
        )

        operators = self._parse_operator_steps(generated.get("operators"))
        if not operators:
            raise ValueError("LLM full-plan output must include non-empty operators")

        risk_notes = generated.get("risk_notes", [])
        if not isinstance(risk_notes, list):
            risk_notes = []

        estimation = generated.get("estimation", {})
        if not isinstance(estimation, dict):
            estimation = {}

        return PlanModel(
            plan_id=PlanModel.new_id(),
            user_intent=user_intent,
            workflow=workflow,
            dataset_path=dataset_path,
            export_path=export_path,
            modality=final_modality,
            text_keys=final_text_keys,
            image_key=final_image_key,
            operators=operators,
            risk_notes=[str(item) for item in risk_notes],
            estimation=estimation,
            approval_required=True,
        )

    def _build_revised_plan(
        self,
        base_plan: PlanModel,
        user_intent: str,
        patch: Dict[str, Any] | None,
    ) -> PlanModel:
        patch = patch or {}
        text_keys = patch.get("text_keys", base_plan.text_keys)
        image_key = patch.get("image_key", base_plan.image_key)
        risk_notes = patch.get("risk_notes", base_plan.risk_notes)
        estimation = patch.get("estimation", base_plan.estimation)
        workflow = self._normalize_workflow(patch.get("workflow", base_plan.workflow))

        patched_ops = self._parse_operator_steps(patch.get("operators"))
        if not patched_ops:
            patched_ops = base_plan.operators

        revised = PlanModel(
            plan_id=PlanModel.new_id(),
            user_intent=user_intent,
            workflow=workflow,
            dataset_path=base_plan.dataset_path,
            export_path=base_plan.export_path,
            modality=self._infer_modality(
                text_keys=text_keys,
                image_key=image_key,
                generated_modality=patch.get("modality", base_plan.modality),
            ),
            text_keys=text_keys,
            image_key=image_key,
            operators=patched_ops,
            risk_notes=list(risk_notes),
            estimation=dict(estimation),
            parent_plan_id=base_plan.plan_id,
            revision=max(1, int(base_plan.revision)) + 1,
            change_summary=[],
            approval_required=base_plan.approval_required,
        )

        llm_summary = patch.get("change_summary", [])
        if isinstance(llm_summary, list) and llm_summary:
            revised.change_summary = [str(item) for item in llm_summary if str(item).strip()]
        if not revised.change_summary:
            diff = build_plan_diff(base_plan, revised)
            revised.change_summary = summarize_plan_diff(diff)
        return revised

    def build_plan(
        self,
        user_intent: str,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None = None,
        image_key: str | None = None,
        base_plan: PlanModel | None = None,
        run_context: Dict[str, Any] | None = None,
    ) -> PlanModel:
        if base_plan is not None:
            self.last_plan_meta = {
                "strategy": "plan-revision",
                "routing_reason": "base plan revision mode",
                "llm_used": "false",
                "llm_fallback": "false",
                "plan_mode": "revision",
            }
            if not self.use_llm:
                self.last_plan_meta["plan_mode"] = "revision_no_llm"
                return self._build_revised_plan(
                    base_plan=base_plan,
                    user_intent=user_intent,
                    patch=None,
                )

            try:
                patch_prompt = self._build_revision_patch_prompt(
                    base_plan=base_plan,
                    user_intent=user_intent,
                    run_context=run_context,
                )
                patch = call_model_json(PLANNER_MODEL_NAME, patch_prompt)
                revised = self._build_revised_plan(
                    base_plan=base_plan,
                    user_intent=user_intent,
                    patch=patch,
                )
                self.last_plan_meta["llm_used"] = "true"
                self.last_plan_meta["plan_mode"] = "revision_with_llm_patch"
                return revised
            except Exception:
                self.last_plan_meta["llm_used"] = "true"
                self.last_plan_meta["llm_fallback"] = "true"
                self.last_plan_meta["plan_mode"] = "revision_no_llm"
                return self._build_revised_plan(
                    base_plan=base_plan,
                    user_intent=user_intent,
                    patch=None,
                )

        if self.llm_full_plan:
            self.last_plan_meta = {
                "strategy": "llm-full-plan",
                "routing_reason": "full llm generation mode",
                "llm_used": "true" if self.use_llm else "false",
                "llm_fallback": "false",
                "plan_mode": "llm_full",
            }
            if not self.use_llm:
                raise ValueError("llm_full_plan requires use_llm=True")

            try:
                return self._plan_from_llm_full(
                    user_intent=user_intent,
                    dataset_path=dataset_path,
                    export_path=export_path,
                    text_keys=text_keys,
                    image_key=image_key,
                )
            except Exception as exc:
                self.last_plan_meta["llm_fallback"] = "true"
                raise ValueError(f"LLM full-plan mode failed: {exc}") from exc

        routing = explain_routing(user_intent)
        workflow = select_workflow(user_intent)
        template = self._load_template(workflow)

        base_plan = self._plan_from_template(
            user_intent=user_intent,
            workflow=workflow,
            template=template,
            dataset_path=dataset_path,
            export_path=export_path,
            text_keys=text_keys,
            image_key=image_key,
        )

        self.last_plan_meta = {
            "strategy": routing["strategy"],
            "routing_reason": routing["reason"],
            "llm_used": "false",
            "llm_fallback": "false",
            "plan_mode": "template",
        }

        if not self.use_llm:
            return base_plan

        try:
            patch_prompt = self._build_patch_prompt(base_plan)
            patch = call_model_json(PLANNER_MODEL_NAME, patch_prompt)
            plan = self._apply_patch(base_plan, patch)
            self.last_plan_meta["llm_used"] = "true"
            self.last_plan_meta["plan_mode"] = "template_with_llm_patch"
            return plan
        except Exception:
            self.last_plan_meta["llm_used"] = "true"
            self.last_plan_meta["llm_fallback"] = "true"
            self.last_plan_meta["plan_mode"] = "template"
            return base_plan


def default_workflows_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "workflows"
