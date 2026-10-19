from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.llm import build_messages, request_decision

EVALUATION_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = EVALUATION_DIR / "scenarios.json"
RESULTS_DIR = EVALUATION_DIR / "results"


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Evaluation scenarios must be a non-empty JSON array")
    required_fields = {
        "id",
        "supervisor_instruction",
        "run_instructions",
        "order_id",
        "order_context",
        "trigger",
        "finalizing",
        "new_events",
        "memory_summary",
        "recent_timeline",
        "available_tools",
        "reference",
    }
    for index, scenario in enumerate(scenarios):
        missing = required_fields - scenario.keys()
        if missing:
            raise ValueError(
                f"Scenario {index} is missing required fields: {sorted(missing)}"
            )
    return scenarios


def make_evaluation_row(
    scenario: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    evidence = {
        "supervisor_instruction": scenario["supervisor_instruction"],
        "run_instructions": scenario["run_instructions"],
        "order_id": scenario["order_id"],
        "order_context": scenario["order_context"],
        "trigger": scenario["trigger"],
        "finalizing": scenario["finalizing"],
        "new_events": scenario["new_events"],
        "memory_summary": scenario["memory_summary"],
        "recent_timeline": scenario["recent_timeline"],
        "available_tools": scenario["available_tools"],
    }
    return {
        "case_id": scenario["id"],
        "user_input": json.dumps(evidence, sort_keys=True),
        "retrieved_contexts": [json.dumps(evidence, sort_keys=True)],
        "response": json.dumps(response, sort_keys=True),
        "reference": scenario["reference"],
    }


async def collect_agent_responses(
    scenarios: list[dict[str, Any]], api_key: str, model: str
) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        messages = build_messages(
            base_instruction=scenario["supervisor_instruction"],
            order_id=scenario["order_id"],
            order_context=scenario["order_context"],
            extra_instructions=scenario["run_instructions"],
            memory_summary=scenario["memory_summary"],
            recent_timeline=scenario["recent_timeline"],
            events=scenario["new_events"],
            cause=scenario["trigger"],
            finalizing=scenario["finalizing"],
            available_tools=scenario["available_tools"],
        )
        decision = await request_decision(
            messages=messages,
            api_key=api_key,
            model=model,
        )
        rows.append(
            make_evaluation_row(scenario, decision.model_dump(mode="json"))
        )
        print(f"Collected agent response for {scenario['id']}")
    return rows


def run_ragas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    import litellm
    import pandas as pd
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import llm_factory
    from ragas.metrics import AspectCritic, Faithfulness, FactualCorrectness
    from ragas.run_config import RunConfig

    evaluator_name = os.environ.get(
        "RAGAS_MODEL", "groq/openai/gpt-oss-20b"
    )
    litellm.num_retries = 3
    evaluator_llm = llm_factory(
        evaluator_name,
        provider="litellm",
        client=litellm.completion,
        temperature=0,
    )
    metrics = [
        ("faithfulness", Faithfulness(llm=evaluator_llm)),
        ("factual_correctness", FactualCorrectness(llm=evaluator_llm)),
        (
            "response_relevance",
            AspectCritic(
                name="response_relevance",
                definition=(
                    "The agent response directly addresses the supplied order context, "
                    "instructions, and triggering event without unrelated content."
                ),
                llm=evaluator_llm,
            ),
        ),
        (
            "instruction_adherence",
            AspectCritic(
                name="instruction_adherence",
                definition=(
                    "The response follows supervisor and run instructions, uses only "
                    "enabled tools, does not invent facts, and does not claim simulated "
                    "actions happened in the real world."
                ),
                llm=evaluator_llm,
            ),
        ),
    ]
    dataset = EvaluationDataset.from_list(
        [
            {
                key: row[key]
                for key in ("user_input", "retrieved_contexts", "response", "reference")
            }
            for row in rows
        ]
    )
    score_frames = []
    pause_seconds = max(0, int(os.environ.get("RAGAS_PAUSE_SECONDS", "65")))
    for index, (metric_name, metric) in enumerate(metrics):
        metric_result = evaluate(
            dataset=dataset,
            metrics=[metric],
            run_config=RunConfig(max_workers=1, max_retries=3, max_wait=15),
        ).to_pandas()
        score_columns = [
            column
            for column in metric_result.columns
            if column not in {"user_input", "retrieved_contexts", "response", "reference"}
        ]
        if len(score_columns) != 1:
            raise ValueError(
                f"Expected one score column for {metric_name}; found {score_columns}"
            )
        score_frames.append(
            metric_result[[score_columns[0]]].rename(
                columns={score_columns[0]: metric_name}
            )
        )
        if index < len(metrics) - 1 and pause_seconds:
            print(
                f"Waiting {pause_seconds}s before the next RAGAS metric to respect "
                "provider token-per-minute limits."
            )
            time.sleep(pause_seconds)

    scored = pd.concat(
        [pd.DataFrame({"case_id": [row["case_id"] for row in rows]}), *score_frames],
        axis=1,
    )
    metric_summaries = {
        column: {
            "mean": (
                float(scored[column].dropna().mean())
                if not scored[column].dropna().empty
                else None
            ),
            "scored_cases": int(scored[column].count()),
            "total_cases": len(scored),
        }
        for column in (
            "faithfulness",
            "factual_correctness",
            "response_relevance",
            "instruction_adherence",
        )
        if column in scored
    }
    incomplete_metrics = [
        name
        for name, result in metric_summaries.items()
        if result["scored_cases"] != result["total_cases"]
    ]
    if incomplete_metrics:
        print(
            "RAGAS could not score every case for: "
            + ", ".join(incomplete_metrics)
            + ". Check the CSV and provider rate limits.",
            file=sys.stderr,
        )
    return {
        "case_count": len(rows),
        "evaluator_model": evaluator_name,
        "metrics": metric_summaries,
        "results": scored,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Groq agent scenarios and score them with RAGAS."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Directory for the JSON score report and per-scenario CSV",
    )
    parser.add_argument(
        "--responses",
        type=Path,
        help="Score a previously captured RAGAS input JSON instead of calling Groq again",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.responses:
        rows = json.loads(args.responses.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("Response input must be a non-empty JSON array")
        input_path = args.responses
    else:
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("GROQ_API_KEY is required to run the live RAGAS evaluation")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        rows = asyncio.run(collect_agent_responses(load_scenarios(), api_key, model))
        input_path = args.output_dir / f"ragas-input-{timestamp}.json"
        input_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    evaluation = run_ragas(rows)

    csv_path = args.output_dir / f"ragas-{timestamp}.csv"
    json_path = args.output_dir / f"ragas-{timestamp}.json"
    evaluation["results"].to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(
            {
                "case_count": evaluation["case_count"],
                "evaluator_model": evaluation["evaluator_model"],
                "metrics": evaluation["metrics"],
                "input_data": input_path.name,
                "csv_report": csv_path.name,
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    print(json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
