from __future__ import annotations

from pathlib import Path

from evals.evaluate_agent import load_scenarios, make_evaluation_row


def test_ragas_scenarios_are_synthetic_and_have_evidence_and_references() -> None:
    scenarios = load_scenarios(Path(__file__).parents[1] / "evals" / "scenarios.json")

    assert len(scenarios) == 3
    assert all(
        scenario["order_id"].startswith("EVAL-")
        and scenario["reference"]
        and scenario["new_events"]
        and set(scenario["available_tools"])
        <= {
            "send_customer_message",
            "create_internal_note",
            "mark_order_for_review",
        }
        for scenario in scenarios
    )


def test_ragas_row_contains_only_case_evidence_and_agent_output() -> None:
    scenario = load_scenarios()[0]
    response = {
        "summary": "Synthetic weather delay recorded.",
        "actions": [],
    }

    row = make_evaluation_row(scenario, response)

    assert row["case_id"] == "shipment-delay"
    assert "Synthetic weather delay" in row["retrieved_contexts"][0]
    assert row["response"] == '{"actions": [], "summary": "Synthetic weather delay recorded."}'
    assert row["reference"] == scenario["reference"]
