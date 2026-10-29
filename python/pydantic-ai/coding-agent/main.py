# Copyright Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""Generate tested Python code, reattach to its Daytona workspace, then delete it."""

import asyncio
import os
from contextlib import aclosing
from textwrap import shorten

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.run import AgentRunResult
from pydantic_ai_harness.coder import Coder
from pydantic_ai_harness.daytona_sandbox import DaytonaSandbox, DaytonaSandboxBackend

WORKING_DIR = "/home/daytona/project"
TASK = """Implement moving_average(values, window) in stats.py with type hints.
Return the arithmetic mean of every consecutive full window as a list of floats.
For a valid window, an empty list or window > len(values) returns [].
window < 1 raises ValueError, including when values is empty.
Write test_stats.py using pytest: cover normal windows, window=1, window=len(values),
empty input, oversized windows, zero and negative windows, and fractional values.
Run python -m pytest -q. If pytest is missing, install it in the sandbox.
Fix any failures and re-run until green.
Report the files created or changed in this run and the final pytest results."""
FOLLOWUP = """The existing stats.py and test_stats.py are in this workspace.
Read them. Add one more pytest test for moving_average([-4, -2, 0, 2], 2),
expecting [-3.0, -1.0, 1.0]. Do not replace the existing tests.
Run the full suite with python -m pytest -q, fix failures, and re-run until green.
Report the files created or changed in this run and the final pytest results."""


class TestReport(BaseModel):
    """Files changed and final pytest results from one run."""

    files: list[str] = Field(description="Files created or changed in this run")
    tests_passed: int = Field(description="Number of tests passed in the final pytest run")
    tests_failed: int = Field(description="Number of tests failed in the final pytest run")
    pytest_summary: str = Field(description="Final line of the pytest output, e.g. 11 passed in 0.03s")


def print_trace(result: AgentRunResult[TestReport]) -> None:
    """Print bounded tool arguments and results from this run only."""
    for message in result.new_messages():
        for part in message.parts:
            if isinstance(part, (ToolCallPart, ToolReturnPart)) and part.tool_name == "final_result":
                continue
            if isinstance(part, ToolCallPart):
                arguments = shorten(part.args_as_json_str(), width=180)
                print(f"  -> {part.tool_name} {arguments}")
            elif isinstance(part, ToolReturnPart):
                output = shorten(str(part.content), width=500)
                print(f"  <- {part.tool_name} {output}")


async def main() -> None:
    """Run the agent twice in one Daytona sandbox, then delete the sandbox."""
    load_dotenv()
    model = os.getenv("MODEL", "anthropic:claude-sonnet-5")
    sandbox = DaytonaSandbox(working_dir=WORKING_DIR)
    agent = Agent(model, output_type=TestReport, capabilities=[Coder(sub_agents=False), sandbox])

    # Keep the backend available for cleanup even if the first run fails.
    async with aclosing(DaytonaSandboxBackend(working_dir=WORKING_DIR)) as backend:
        try:
            first = await agent.run(TASK, workspace=backend)
            ref = first.workspace.ref
            assert ref is not None
            print(f"Sandbox: {ref.id}", flush=True)
            print("\nRun 1 tool trace:")
            print_trace(first)
            print(first.output.model_dump_json(indent=2))
            if first.output.tests_failed:
                raise RuntimeError(f"Run 1 reported {first.output.tests_failed} failed tests")

            print(f"\nReattaching: {ref.id}", flush=True)
            second = await agent.run(FOLLOWUP, workspace=ref)
            print("\nRun 2 tool trace:")
            print_trace(second)
            print(second.output.model_dump_json(indent=2))
            print(f"Run 2 workspace: {second.workspace.ref}")
        finally:
            ref = backend.ref
            if ref is not None:
                await sandbox.destroy(ref)
                print(f"Deleted sandbox: {ref.id}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
