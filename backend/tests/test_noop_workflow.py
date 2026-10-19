from __future__ import annotations

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.temporal.activities import ping
from app.temporal.workflow import NoopWorkflow


@pytest.mark.asyncio
async def test_noop_workflow_returns_pong() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-noop",
            workflows=[NoopWorkflow],
            activities=[ping],
        ):
            result = await env.client.execute_workflow(
                NoopWorkflow.run,
                "ok",
                id="noop-ok",
                task_queue="test-noop",
            )
    assert result == "pong:ok"


@pytest.mark.asyncio
async def test_noop_workflow_rejects_empty_name() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-noop",
            workflows=[NoopWorkflow],
            activities=[ping],
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    NoopWorkflow.run,
                    "   ",
                    id="noop-empty",
                    task_queue="test-noop",
                )
