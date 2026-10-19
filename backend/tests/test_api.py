from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.api import runs
from app.main import app


@pytest.fixture
def api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, AsyncMock, AsyncMock, AsyncMock, AsyncMock]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db.session, "get_engine", lambda: engine)
    start_workflow = AsyncMock()
    signal_event = AsyncMock()
    signal_control = AsyncMock()
    terminate_workflow = AsyncMock()
    monkeypatch.setattr(runs, "_start_workflow", start_workflow)
    monkeypatch.setattr(runs, "_signal_event", signal_event)
    monkeypatch.setattr(runs, "_signal_control", signal_control)
    monkeypatch.setattr(runs, "_terminate_workflow", terminate_workflow)
    with TestClient(app) as client:
        yield client, start_workflow, signal_event, signal_control, terminate_workflow
    engine.dispose()


def test_supervisor_crud_and_run_lifecycle_api(api_client) -> None:
    client, start_workflow, signal_event, _, _ = api_client
    supervisor_response = client.post(
        "/api/supervisors",
        json={
            "name": "Order supervisor",
            "base_instruction": "Watch this order.",
            "available_tools": ["create_internal_note"],
        },
    )
    assert supervisor_response.status_code == 201
    supervisor = supervisor_response.json()

    assert client.get(f"/api/supervisors/{supervisor['id']}").status_code == 200
    assert client.get("/api/supervisors").json()["items"][0]["id"] == supervisor["id"]

    run_response = client.post(
        "/api/runs",
        json={
            "supervisor_id": supervisor["id"],
            "order_id": "ORD-1",
            "order_context": {"customer": "Ada"},
        },
    )
    assert run_response.status_code == 201
    run = run_response.json()
    assert run["status"] == "starting"
    start_workflow.assert_awaited_once()

    assert client.get("/api/runs").json()["items"][0]["id"] == run["id"]
    details = client.get(f"/api/runs/{run['id']}").json()
    assert details["order_context"] == {"customer": "Ada"}
    assert details["timeline"] == []
    assert details["memory_summary"] is None
    assert details["final_output"] is None

    event_response = client.post(
        f"/api/runs/{run['id']}/events",
        json={"type": "shipment_delayed", "payload": {"reason": "weather"}},
    )
    assert event_response.status_code == 202
    signal_event.assert_awaited_once()

    invalid_event = client.post(
        f"/api/runs/{run['id']}/events",
        json={"type": "not_an_order_event", "payload": {}},
    )
    assert invalid_event.status_code == 400

    too_many_tools = client.post(
        "/api/supervisors",
        json={
            "name": "Too many tools",
            "base_instruction": "Watch the order.",
            "available_tools": [
                "send_customer_message",
                "create_internal_note",
                "mark_order_for_review",
                "send_customer_message",
            ],
        },
    )
    assert too_many_tools.status_code == 422

    unsupported_tool = client.post(
        "/api/supervisors",
        json={
            "name": "Unsupported tool",
            "base_instruction": "Watch the order.",
            "available_tools": ["schedule_next_wakeup"],
        },
    )
    assert unsupported_tool.status_code == 422

    duplicate_tools = client.post(
        "/api/supervisors",
        json={
            "name": "Duplicate tools",
            "base_instruction": "Watch the order.",
            "available_tools": [
                "send_customer_message",
                "send_customer_message",
                "create_internal_note",
            ],
        },
    )
    assert duplicate_tools.status_code == 422


def test_api_returns_not_found_for_unknown_resources(api_client) -> None:
    client, _, _, _, _ = api_client
    unknown_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/supervisors/{unknown_id}").status_code == 404
    assert client.get(f"/api/runs/{unknown_id}").status_code == 404


def test_run_instructions_and_controls(api_client) -> None:
    client, _, _, signal_control, terminate_workflow = api_client
    supervisor = client.post(
        "/api/supervisors",
        json={"name": "Test", "base_instruction": "Monitor the order."},
    ).json()
    run = client.post(
        "/api/runs",
        json={"supervisor_id": supervisor["id"], "order_id": "ORD-3"},
    ).json()
    run_url = f"/api/runs/{run['id']}"

    instruction = client.post(
        f"{run_url}/instructions",
        json={"text": "Escalate shipment delays immediately."},
    )
    assert instruction.status_code == 200
    assert client.get(run_url).json()["extra_instructions"] == [
        "Escalate shipment delays immediately."
    ]
    detail = client.get(run_url).json()
    assert detail["timeline"][0]["type"] == "instruction_added"
    assert client.post(
        f"{run_url}/instructions",
        json={"text": "x" * 4001},
    ).status_code == 422

    paused = client.post(f"{run_url}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert client.post(f"{run_url}/pause").status_code == 409

    resumed = client.post(f"{run_url}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    assert client.post(f"{run_url}/resume").status_code == 409

    interrupted = client.post(f"{run_url}/interrupt")
    assert interrupted.status_code == 200
    assert [call.args[1] for call in signal_control.await_args_list] == [
        "pause",
        "resume",
        "interrupt",
    ]

    terminated = client.post(f"{run_url}/terminate")
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
    terminate_workflow.assert_awaited_once()
    assert client.post(f"{run_url}/interrupt").status_code == 409
    assert client.post(
        f"{run_url}/instructions",
        json={"text": "Another instruction."},
    ).status_code == 409
