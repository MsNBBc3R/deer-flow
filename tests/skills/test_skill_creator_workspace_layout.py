"""Regressions for documented skill-creator evaluation workspace layouts."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/skill-creator/scripts/aggregate_benchmark.py"
)


@pytest.fixture
def benchmark_script():
    return runpy.run_path(str(SCRIPT))


def write_run(directory, *, pass_rate=1.0, tokens=100, seconds=2.0):
    directory.mkdir(parents=True)
    (directory / "outputs").mkdir()
    (directory / "grading.json").write_text(
        json.dumps(
            {
                "summary": {
                    "pass_rate": pass_rate,
                    "passed": int(pass_rate * 4),
                    "failed": 4 - int(pass_rate * 4),
                    "total": 4,
                },
                "expectations": [
                    {"text": "Produces a report", "passed": True, "evidence": "report"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (directory / "timing.json").write_text(
        json.dumps({"total_tokens": tokens, "total_duration_seconds": seconds}),
        encoding="utf-8",
    )
    return directory


def test_documented_direct_layout_collects_both_configurations(
    tmp_path, benchmark_script
):
    write_run(tmp_path / "eval-1" / "with_skill")
    write_run(
        tmp_path / "eval-1" / "without_skill",
        pass_rate=0.25,
        tokens=200,
        seconds=4.0,
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 2
    assert benchmark["metadata"]["evals_run"] == [1]
    results = {run["configuration"]: run for run in benchmark["runs"]}
    assert results["with_skill"]["run_number"] == 1
    assert results["with_skill"]["result"]["pass_rate"] == 1.0
    assert results["without_skill"]["result"]["pass_rate"] == 0.25
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == 100
    assert benchmark["run_summary"]["with_skill"]["time_seconds"]["mean"] == 2.0
    assert benchmark["run_summary"]["delta"]["pass_rate"] == "+0.75"


@pytest.mark.parametrize("legacy", [False, True], ids=["workspace", "legacy"])
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "numbered"])
@pytest.mark.parametrize("eval_name", ["sales-report", "localization"])
def test_descriptive_evaluations_use_metadata_in_both_run_layouts(
    tmp_path, benchmark_script, legacy, nested, eval_name
):
    root = tmp_path / "runs" if legacy else tmp_path
    evaluation = root / eval_name
    for config in ["with_skill", "old_skill"]:
        directory = evaluation / config
        if nested:
            directory /= "run-2"
        write_run(directory, tokens=42, seconds=3.5)
    (evaluation / "eval_metadata.json").write_text(
        json.dumps({"eval_id": 7, "eval_name": eval_name, "prompt": "Make a report"}),
        encoding="utf-8",
    )

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 2
    assert benchmark["metadata"]["evals_run"] == [7]
    assert {run["configuration"] for run in benchmark["runs"]} == {
        "with_skill",
        "old_skill",
    }
    assert {run["run_number"] for run in benchmark["runs"]} == {2 if nested else 1}
    for config in ["with_skill", "old_skill"]:
        assert benchmark["run_summary"][config]["tokens"]["mean"] == 42
        assert benchmark["run_summary"][config]["time_seconds"]["mean"] == 3.5


def test_numbered_runs_take_precedence_over_direct_grades(tmp_path, benchmark_script):
    config = tmp_path / "eval-1" / "with_skill"
    write_run(config, pass_rate=0.0, tokens=999, seconds=99.0)
    write_run(config / "run-1", tokens=100)
    write_run(config / "run-2", tokens=200)

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 2
    assert [run["run_number"] for run in benchmark["runs"]] == [1, 2]
    assert benchmark["run_summary"]["with_skill"]["pass_rate"]["mean"] == 1.0
    assert benchmark["run_summary"]["with_skill"]["tokens"]["mean"] == 150
    assert benchmark["run_summary"]["with_skill"]["time_seconds"]["mean"] == 2.0


def test_discovers_numeric_and_descriptive_evaluations_without_recursing(
    tmp_path, benchmark_script
):
    write_run(tmp_path / "eval-1" / "with_skill")
    descriptive = tmp_path / "sales-report"
    write_run(descriptive / "with_skill" / "run-2")
    (descriptive / "eval_metadata.json").write_text('{"eval_id": 7}', encoding="utf-8")
    write_run(tmp_path / "archive" / "eval-9" / "with_skill")
    write_run(tmp_path / "unrelated" / "with_skill")
    (tmp_path / "eval-not-a-directory").write_text("fixture", encoding="utf-8")

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 2
    assert benchmark["metadata"]["evals_run"] == [1, 7]
    assert [run["run_number"] for run in benchmark["runs"]] == [1, 2]


@pytest.mark.parametrize("metadata", ["{}", "{invalid"])
def test_descriptive_metadata_keeps_existing_id_fallback(
    tmp_path, benchmark_script, metadata
):
    evaluation = tmp_path / "report"
    write_run(evaluation / "with_skill")
    (evaluation / "eval_metadata.json").write_text(metadata, encoding="utf-8")

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 1
    assert benchmark["metadata"]["evals_run"] == [0]


def test_input_and_output_fixtures_are_not_configurations(tmp_path, benchmark_script):
    evaluation = tmp_path / "eval-1"
    write_run(evaluation / "with_skill")
    for name in ["inputs", "outputs"]:
        write_run(evaluation / name, pass_rate=0.0, tokens=999)

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 1
    assert benchmark["runs"][0]["configuration"] == "with_skill"


def test_auxiliary_run_paths_do_not_hide_direct_grades(tmp_path, benchmark_script):
    config = write_run(tmp_path / "eval-1" / "with_skill")
    (config / "run-notes").mkdir()
    (config / "run-2").write_text("fixture", encoding="utf-8")

    benchmark = benchmark_script["generate_benchmark"](tmp_path)

    assert len(benchmark["runs"]) == 1
    assert benchmark["runs"][0]["run_number"] == 1


def test_cli_reports_documented_workspace_results(tmp_path):
    evaluation = tmp_path / "iteration-1" / "sales-report"
    write_run(evaluation / "with_skill")
    write_run(evaluation / "without_skill", pass_rate=0.25, tokens=200, seconds=4.0)
    (evaluation / "eval_metadata.json").write_text('{"eval_id": 7}', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(evaluation.parent), "--skill-name", "sample"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    benchmark = json.loads(
        (evaluation.parent / "benchmark.json").read_text(encoding="utf-8")
    )
    assert len(benchmark["runs"]) == 2
    assert benchmark["metadata"]["evals_run"] == [7]
    assert benchmark["run_summary"]["delta"] == {
        "pass_rate": "+0.75",
        "time_seconds": "-2.0",
        "tokens": "-100",
    }
    markdown = (evaluation.parent / "benchmark.md").read_text(encoding="utf-8")
    assert "| Metric | With Skill | Without Skill | Delta |" in markdown
    assert "| Pass Rate | 100%" in markdown
    assert "25%" in markdown
    assert "+0.75" in markdown
    assert "With Skill: 100.0% pass rate" in completed.stdout
    assert "Without Skill: 25.0% pass rate" in completed.stdout
    assert "Delta:         +0.75" in completed.stdout
