# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""Minimal tool-calling coding agent that runs entirely inside a Daytona sandbox.

The Fireworks API key is never present in this environment. The
FIREWORKS_API_KEY variable holds an opaque Daytona secret placeholder; the
sandbox's outbound proxy substitutes the real key into the Authorization
header, but only for HTTPS requests to api.fireworks.ai.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

# The `openai` package is preinstalled in the default Daytona Python sandbox.
from openai import OpenAI

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
MODEL = os.environ.get("FIREWORKS_MODEL", "accounts/fireworks/models/kimi-k3")
MAX_TURNS = 15
TRAJECTORY_PATH = "trajectory.jsonl"

SYSTEM_PROMPT = """You are a coding agent working in the current directory of a Linux sandbox.

Your goal: make `python tests.py` pass. Read tests.py first to understand the
expected behavior, then create solution.py implementing it.

Rules:
- Use the write_file and run_bash tools for all work.
- Always run `python tests.py` to verify before declaring success.
- When the tests pass, reply with a short summary and no tool calls."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Run a shell command and return its output and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute."},
                },
                "required": ["command"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    if name == "write_file":
        Path(args["path"]).write_text(args["content"], encoding="utf-8")
        return f"Wrote {len(args['content'])} characters to {args['path']}"
    if name == "run_bash":
        # Run the command in its own session (process group) so a timeout
        # kills the whole process tree, not just the shell.
        proc = subprocess.Popen(
            args["command"],
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
            proc.wait()
            return "error: command timed out after 120 seconds (process tree killed)"
        output = stdout.strip() or "(no output)"
        return f"exit code: {proc.returncode}\n{output[-4000:]}"
    return f"Unknown tool: {name}"


def main() -> None:
    client = OpenAI(
        base_url=FIREWORKS_BASE_URL,
        # This is the placeholder token. The proxy swaps it for the real key
        # on requests to api.fireworks.ai, and nowhere else.
        api_key=os.environ["FIREWORKS_API_KEY"],
    )

    # Snapshot the verifier before the agent can touch the filesystem. The
    # model may edit tests.py during the run, but the final verdict always
    # executes this pristine copy (anti reward-hacking).
    tests_snapshot = Path("tests.py").read_bytes()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Make `python tests.py` pass."},
    ]

    finished = False
    try:
        for turn in range(1, MAX_TURNS + 1):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                temperature=0.2,
            )
            message = response.choices[0].message
            messages.append(
                message.model_dump(include={"role", "content", "tool_calls"}, exclude_none=True)
            )

            if not message.tool_calls:
                print(f"[agent] finished after {turn} turn(s): {message.content}")
                finished = True
                break

            for tool_call in message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                    print(f"[agent] turn {turn}: {tool_call.function.name}({json.dumps(args)[:120]})")
                    result = execute_tool(tool_call.function.name, args)
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    result = f"error: invalid tool call ({exc})"
                    print(f"[agent] turn {turn}: rejected malformed tool call ({exc})")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        if not finished:
            print(f"[agent] stopped after {MAX_TURNS} turns without finishing")
    finally:
        # Export the trajectory in the OpenAI messages format, which Fireworks
        # accepts directly as supervised fine-tuning data. Written even when a
        # turn crashes: partial trajectories are useful for debugging, and only
        # verified runs should become training data anyway.
        with Path(TRAJECTORY_PATH).open("w", encoding="utf-8") as f:
            f.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
        print(f"[agent] trajectory written to {TRAJECTORY_PATH}")

    # Restore the pristine verifier, then run the final verification. In an RL
    # setup this exit code is the reward signal, so it must come from a test
    # file the policy could not have tampered with.
    Path("tests.py").write_bytes(tests_snapshot)
    try:
        verdict = subprocess.run(
            [sys.executable, "tests.py"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        print(verdict.stdout.strip())
        exit_code = verdict.returncode
    except subprocess.TimeoutExpired:
        print("verification timed out after 60 seconds")
        exit_code = 1
    print(f"[agent] verification exit code: {exit_code}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
