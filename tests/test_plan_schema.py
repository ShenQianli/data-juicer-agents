# -*- coding: utf-8 -*-

from data_juicer_agents.core.schemas import OperatorStep, PlanModel, validate_plan


def test_plan_schema_validates_required_fields():
    plan = PlanModel(
        plan_id=PlanModel.new_id(),
        user_intent="clean rag data",
        workflow="rag_cleaning",
        dataset_path="/tmp/data.jsonl",
        export_path="/tmp/out.jsonl",
        operators=[OperatorStep(name="text_length_filter", params={"min_len": 5})],
    )

    errors = validate_plan(plan)
    assert errors == []


def test_plan_schema_rejects_empty_operators():
    plan = PlanModel(
        plan_id="p1",
        user_intent="x",
        workflow="rag_cleaning",
        dataset_path="/tmp/data.jsonl",
        export_path="/tmp/out.jsonl",
        operators=[],
    )
    errors = validate_plan(plan)
    assert "operators must not be empty" in errors


def test_plan_schema_rejects_invalid_revision():
    plan = PlanModel(
        plan_id="p2",
        user_intent="x",
        workflow="rag_cleaning",
        dataset_path="/tmp/data.jsonl",
        export_path="/tmp/out.jsonl",
        revision=0,
        operators=[OperatorStep(name="text_length_filter", params={"min_len": 1})],
    )
    errors = validate_plan(plan)
    assert "revision must be >= 1" in errors
