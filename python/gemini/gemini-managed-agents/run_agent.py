# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Send a prompt to a Gemini managed agent whose tools run in your Daytona sandboxes.

Streams the interaction: the agent's tool calls as it makes them (stderr) and
its reply (stdout). Start a worker first, with worker.py or with
`gemini-api environments poll` and provision_sandbox.py.
"""

import argparse
import json
import os
import sys
from typing import Any

from google import genai
from google.genai.interactions import Interaction

import sandbox_lib

DEFAULT_AGENT = "antigravity-preview-09-2026"
# Results of execute_bash arrive as code_execution_result steps, other tools as function_result.
RESULT_STEPS = ("function_result", "code_execution_result")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Gemini managed agent against your self-hosted environment.")
    parser.add_argument("prompt", help="task for the agent")
    args = parser.parse_args()
    sandbox_lib.load_env()

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    stream = client.interactions.create(
        agent=os.environ.get("GEMINI_AGENT", DEFAULT_AGENT),
        input=args.prompt,
        # The bare environment id returned by create_environment.py.
        environment=os.environ["GEMINI_ENVIRONMENT_ID"],
        stream=True,
        # `environment` is only accepted on v1beta, and google-genai 3.1 does not default to it.
        api_version="v1beta",
    )
    if isinstance(stream, Interaction):
        # create() returns a finished Interaction only when stream=False.
        raise TypeError("expected an event stream from interactions.create(stream=True)")

    # Tool names by call id, so results can be labelled; open tool steps by step index.
    tool_names: dict[str, str] = {}
    open_steps: dict[int, dict[str, Any]] = {}
    status = "incomplete"
    for event in stream:
        data = event.model_dump(mode="json", by_alias=True, exclude_none=True)
        kind = data.get("event_type")
        index = data.get("index", -1)
        if kind == "interaction.created":
            print(f"interaction {data['interaction']['id']}", file=sys.stderr, flush=True)
        elif kind == "step.start":
            step = data.get("step", {})
            if step.get("type") == "function_call":
                tool_names[step.get("id", "")] = step.get("name", "")
                open_steps[index] = {"call": True, "name": step.get("name"), "arguments": ""}
            elif step.get("type") in RESULT_STEPS:
                name = step.get("name") or tool_names.get(step.get("call_id", ""), "tool")
                open_steps[index] = {"call": False, "name": name, "is_error": step.get("is_error", False)}
        elif kind == "step.delta":
            delta = data.get("delta", {})
            step = open_steps.get(index)
            if delta.get("type") == "text":
                print(delta.get("text", ""), end="", flush=True)
            elif step and delta.get("type") == "arguments_delta":
                step["arguments"] += delta.get("arguments", "")
            elif step and delta.get("type") in RESULT_STEPS:
                step["is_error"] = delta.get("is_error", step["is_error"])
        elif kind == "step.stop" and index in open_steps:
            step = open_steps.pop(index)
            if step["call"]:
                print(f"→ {step['name']} {step['arguments']}", file=sys.stderr, flush=True)
            else:
                print(f"← {step['name']} ({'error' if step['is_error'] else 'ok'})", file=sys.stderr, flush=True)
        elif kind == "interaction.completed":
            status = data["interaction"].get("status", "completed")
        elif kind == "error":
            print(f"error: {json.dumps(data.get('error'))}", file=sys.stderr)
            return 1

    print()
    print(f"interaction {status}", file=sys.stderr)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
