# -*- coding: utf-8 -*-

from pathlib import Path

from data_juicer_agents.cli import main


def test_plan_command_no_llm(tmp_path: Path, monkeypatch):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"text":"hello world"}\n', encoding="utf-8")

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    export_file = export_dir / "result.jsonl"
    plan_file = tmp_path / "plan.yaml"

    monkeypatch.chdir(tmp_path)
    exit_code = main(
        [
            "plan",
            "clean rag corpus",
            "--dataset",
            str(dataset),
            "--export",
            str(export_file),
            "--output",
            str(plan_file),
            "--no-llm",
        ],
    )

    assert exit_code == 0
    assert plan_file.exists()
