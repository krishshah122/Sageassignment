from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SendCustomerMessage(ToolArguments):
    message: NonBlankString


class CreateInternalNote(ToolArguments):
    note: NonBlankString


class MarkOrderForReview(ToolArguments):
    reason: NonBlankString


TOOL_ARGUMENTS: dict[str, type[ToolArguments]] = {
    "send_customer_message": SendCustomerMessage,
    "create_internal_note": CreateInternalNote,
    "mark_order_for_review": MarkOrderForReview,
}

TOOL_DESCRIPTIONS = {
    "send_customer_message": "Simulate sending a message to the customer. Requires message.",
    "create_internal_note": "Add an internal order note. Requires note.",
    "mark_order_for_review": "Flag the order for human review. Requires reason.",
}


def execute_mock_tool(name: str, raw_arguments: dict[str, Any]) -> dict[str, Any]:
    argument_model = TOOL_ARGUMENTS.get(name)
    if argument_model is None:
        raise ValueError(f"Unsupported tool: {name}")
    arguments = argument_model.model_validate(raw_arguments).model_dump()
    if name == "send_customer_message":
        result = {"message": arguments["message"], "delivery": "simulated"}
    elif name == "create_internal_note":
        result = {"note": arguments["note"], "created": "simulated"}
    else:
        result = {"reason": arguments["reason"], "review": "simulated"}
    return {"tool": name, "arguments": arguments, "result": result}


class PlannedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal[
        "send_customer_message",
        "create_internal_note",
        "mark_order_for_review",
    ]
    arguments: dict[str, Any]


class FinalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: NonBlankString
    important_actions: list[dict[str, Any]]
    learnings: NonBlankString
    feedback: NonBlankString


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    memory_summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    actions: list[PlannedAction] = Field(max_length=6)
    next_wakeup_seconds: int | None = Field(default=None, ge=1, le=86400)
    final_output: FinalOutput | None = None


def available_tool_descriptions(tool_names: list[str]) -> dict[str, str]:
    return {
        name: TOOL_DESCRIPTIONS[name]
        for name in tool_names
        if name in TOOL_DESCRIPTIONS
    }
