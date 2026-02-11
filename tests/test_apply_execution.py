# -*- coding: utf-8 -*-

import json
from pathlib import Path

import yaml

from data_juicer_agents.cli import main
from data_juicer_agents.core.schemas import OperatorStep, PlanModel


def test_apply_dry_run_creates_trace_and_recipe(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"text":"hello"}\n', encoding="utf-8")

    output = tmp_path / "output.jsonl"
    plan = PlanModel(
        plan_id="plan_test_apply",
        user_intent="clean",
        workflow="rag_cleaning",
        dataset_path=str(dataset),
        export_path=str(output),
        text_keys=["text"],
        operators=[OperatorStep(name="text_length_filter", params={"min_len": 1})],
    )

    plan_file = tmp_path / "plan.yaml"
    with open(plan_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan.to_dict(), f, sort_keys=False)

    monkeypatch.chdir(tmp_path)
    exit_code = main(["apply", "--plan", str(plan_file), "--yes", "--dry-run"])
    assert exit_code == 0
    assert (tmp_path / ".djx" / "runs.jsonl").exists()
    assert (tmp_path / ".djx" / "recipes" / "plan_test_apply.yaml").exists()


def test_apply_prints_trace_command_at_end(tmp_path: Path, monkeypatch, capsys):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"text":"hello"}\n', encoding="utf-8")

    output = tmp_path / "output.jsonl"
    plan = PlanModel(
        plan_id="plan_test_apply_trace_cmd",
        user_intent="clean",
        workflow="rag_cleaning",
        dataset_path=str(dataset),
        export_path=str(output),
        text_keys=["text"],
        operators=[OperatorStep(name="text_length_filter", params={"min_len": 1})],
    )

    plan_file = tmp_path / "plan.yaml"
    with open(plan_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan.to_dict(), f, sort_keys=False)

    monkeypatch.chdir(tmp_path)
    exit_code = main(["apply", "--plan", str(plan_file), "--yes", "--dry-run"])
    assert exit_code == 0

    output_text = capsys.readouterr().out.strip()
    trace_file = tmp_path / ".djx" / "runs.jsonl"
    run_payload = trace_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    run_id = json.loads(run_payload)["run_id"]
    assert "Run Summary:" in output_text
    assert "Trace command: djx trace " in output_text
    assert output_text.endswith(f"Trace command: djx trace {run_id}")
