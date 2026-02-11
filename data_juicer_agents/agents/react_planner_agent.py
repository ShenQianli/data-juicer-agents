# -*- coding: utf-8 -*-
"""Minimal ReAct planner for full LLM planning mode."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

from data_juicer_agents.tools.dataset_probe import inspect_dataset_schema
from data_juicer_agents.tools.operator_registry import get_available_operator_names
from data_juicer_agents.tools.router_helpers import explain_routing

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_THINKING_BLOCK_WARNING = "Unsupported block type thinking in the message, skipped."


class _IgnoreThinkingBlockWarningFilter(logging.Filter):
    """Filter only the known formatter warning for thinking blocks."""

    def filter(self, record: logging.LogRecord) -> bool:
        return _THINKING_BLOCK_WARNING not in record.getMessage()


def _install_thinking_warning_filter() -> None:
    logger = logging.getLogger("as")
    for item in logger.filters:
        if isinstance(item, _IgnoreThinkingBlockWarningFilter):
            return
    logger.addFilter(_IgnoreThinkingBlockWarningFilter())


def _extract_json_text(text: str) -> str:
    match = _JSON_BLOCK_RE.search(text or "")
    if match:
        return match.group(1).strip()
    return (text or "").strip()


def _to_text_response(payload: Dict[str, Any]):
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse

    return ToolResponse(
        metadata={"ok": True},
        content=[TextBlock(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


def _parse_operators_input(value: str | list | None) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


class ReActFullPlanner:
    """A minimal ReAct planner with local workflow/tools grounding."""

    def __init__(
        self,
        workflows_dir: Path,
        model_name: str,
        max_iters: int = 6,
    ) -> None:
        self.workflows_dir = workflows_dir
        self.model_name = model_name
        self.max_iters = max_iters

    def _load_template(self, workflow: str) -> Dict[str, Any]:
        path = self.workflows_dir / f"{workflow}.yaml"
        if not path.exists():
            return {"error": f"workflow template not found: {workflow}"}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_toolkit(self):
        from agentscope.tool import Toolkit

        toolkit = Toolkit()

        def suggest_workflow(user_intent: str) -> ToolResponse:
            routing = explain_routing(user_intent)
            return _to_text_response(routing)

        def get_workflow_template(workflow: str) -> ToolResponse:
            data = self._load_template(workflow)
            if "error" in data:
                return _to_text_response(data)
            return _to_text_response(
                {
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "default_text_keys": data.get("default_text_keys", []),
                    "default_image_key": data.get("default_image_key"),
                    "operators": data.get("operators", []),
                    "risk_notes": data.get("risk_notes", []),
                    "estimation": data.get("estimation", {}),
                }
            )

        def validate_operator_sequence(
            workflow: str,
            operators_json: str,
            modality: str = "unknown",
        ) -> ToolResponse:
            operators = _parse_operators_input(operators_json)
            names = [str(item.get("name", "")).strip() for item in operators]
            names = [name for name in names if name]

            errors: List[str] = []
            warnings: List[str] = []

            if not names:
                errors.append("operators must not be empty")

            available_ops = get_available_operator_names()
            if available_ops:
                unknown = [name for name in names if name not in available_ops]
                if unknown:
                    errors.append(
                        "Unsupported operators not in installed registry: "
                        + ", ".join(sorted(set(unknown)))
                    )

            mode = modality if modality in {"text", "image", "multimodal", "unknown"} else "unknown"

            if workflow == "multimodal_dedup" or mode == "multimodal":
                if not any("image" in name and "dedup" in name for name in names):
                    warnings.append(
                        "multimodal_dedup usually requires an image dedup operator (e.g., image_deduplicator)."
                    )
            elif workflow == "rag_cleaning" or mode == "text":
                if not any("text_length_filter" == name for name in names):
                    warnings.append("rag_cleaning usually includes text_length_filter.")

            return _to_text_response(
                {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}
            )

        def inspect_dataset(dataset_path: str, sample_size: int = 20) -> ToolResponse:
            return _to_text_response(
                inspect_dataset_schema(dataset_path=dataset_path, sample_size=sample_size)
            )

        def list_available_operators(query: str = "", limit: int = 50) -> ToolResponse:
            names = sorted(get_available_operator_names())
            if query:
                tokens = [tok for tok in re.split(r"[\s,_-]+", query.lower()) if tok]
                if tokens:
                    names = [
                        name
                        for name in names
                        if all(tok in name.lower() for tok in tokens)
                    ]
            if limit <= 0:
                limit = 50
            limited = names[: min(limit, 200)]
            return _to_text_response({"count": len(names), "operators": limited})

        toolkit.register_tool_function(suggest_workflow)
        toolkit.register_tool_function(get_workflow_template)
        toolkit.register_tool_function(validate_operator_sequence)
        toolkit.register_tool_function(inspect_dataset)
        toolkit.register_tool_function(list_available_operators)
        return toolkit

    def _build_agent(self):
        from agentscope.agent import ReActAgent
        from agentscope.formatter import OpenAIChatFormatter
        from agentscope.model import OpenAIChatModel

        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("MODELSCOPE_API_TOKEN")
        if not api_key:
            raise RuntimeError("Missing API key: set DASHSCOPE_API_KEY or MODELSCOPE_API_TOKEN")

        base_url = os.environ.get(
            "DJA_OPENAI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        thinking_flag = os.environ.get("DJA_LLM_THINKING", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        model = OpenAIChatModel(
            model_name=self.model_name,
            api_key=api_key,
            stream=False,
            client_kwargs={"base_url": base_url},
            generate_kwargs={
                "temperature": 0,
                "extra_body": {"enable_thinking": thinking_flag},
            },
        )
        formatter = OpenAIChatFormatter()
        toolkit = self._build_toolkit()

        # Keep warnings in general, but silence the known "thinking block"
        # warning emitted by AgentScope formatter.
        _install_thinking_warning_filter()

        agent = ReActAgent(
            name="PlanReActAgent",
            sys_prompt=(
                "You are a Data-Juicer planning ReAct agent.\n"
                "Use tools to ground workflow and operator choices.\n"
                "Before final answer, you MUST call at least one tool.\n"
                "When text/image key hints are missing or intent is ambiguous, call inspect_dataset first.\n"
                "Before finalizing operators, call list_available_operators with intent keywords (e.g. dedup/filter) and use exact names.\n"
                "Output JSON only with keys: workflow, modality, text_keys, image_key, operators, risk_notes, estimation.\n"
                "Set workflow to custom in llm-full-plan mode.\n"
                "Output modality as one of text/image/multimodal/unknown.\n"
                "operators must be non-empty array of {name, params}.\n"
                "Operator names must come from installed Data-Juicer operators.\n"
                "Do not output markdown."
            ),
            model=model,
            formatter=formatter,
            toolkit=toolkit,
            max_iters=self.max_iters,
            parallel_tool_calls=False,
        )
        agent.set_console_output_enabled(enabled=False)
        return agent

    async def _plan_async(
        self,
        user_intent: str,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None,
        image_key: str | None,
        feedback_errors: List[str] | None = None,
    ) -> Dict[str, Any]:
        from agentscope.message import Msg

        agent = self._build_agent()
        feedback = feedback_errors or []
        user_prompt = (
            "Build a Data-Juicer plan from this context.\n"
            f"intent: {user_intent}\n"
            f"dataset_path: {dataset_path}\n"
            f"export_path: {export_path}\n"
            f"text_keys_hint: {json.dumps(text_keys or [], ensure_ascii=False)}\n"
            f"image_key_hint: {image_key or ''}\n"
            f"validation_feedback: {json.dumps(feedback, ensure_ascii=False)}\n"
        )
        msg = await agent(Msg(name="user", role="user", content=user_prompt))
        text = msg.get_text_content()
        payload = _extract_json_text(text)
        return json.loads(payload)

    def plan(
        self,
        user_intent: str,
        dataset_path: str,
        export_path: str,
        text_keys: List[str] | None,
        image_key: str | None,
        feedback_errors: List[str] | None = None,
    ) -> Dict[str, Any]:
        return asyncio.run(
            self._plan_async(
                user_intent=user_intent,
                dataset_path=dataset_path,
                export_path=export_path,
                text_keys=text_keys,
                image_key=image_key,
                feedback_errors=feedback_errors,
            )
        )


def run_react_full_plan(
    workflows_dir: Path,
    model_name: str,
    user_intent: str,
    dataset_path: str,
    export_path: str,
    text_keys: List[str] | None,
    image_key: str | None,
    feedback_errors: List[str] | None = None,
) -> Dict[str, Any]:
    planner = ReActFullPlanner(workflows_dir=workflows_dir, model_name=model_name)
    return planner.plan(
        user_intent=user_intent,
        dataset_path=dataset_path,
        export_path=export_path,
        text_keys=text_keys,
        image_key=image_key,
        feedback_errors=feedback_errors,
    )
