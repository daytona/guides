"""Run Windows computer-use eval episodes on Daytona sandboxes."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from common import (
    create_sandbox,
    get_client,
    ps_exec,
    screenshot_png,
    start_computer_use,
    strip_clixml_noise,
)
from tasks import TASKS, Task

DEFAULT_SNAPSHOT = "windows-cu-evals-v1"
DEFAULT_RUNS_DIR = "runs"
RESULTS_FILE = "results.json"

# Keep the MCP tool surface focused on GUI actions. Recording tools are
# intentionally excluded: this guide saves only initial.png and final.png.
COMPUTER_USE_TOOLS = [
    "computer_use_accessibility_find",
    "computer_use_accessibility_focus",
    "computer_use_accessibility_invoke",
    "computer_use_accessibility_set_value",
    "computer_use_accessibility_tree",
    "computer_use_display_info",
    "computer_use_keyboard_hotkey",
    "computer_use_keyboard_press",
    "computer_use_keyboard_type",
    "computer_use_mouse_click",
    "computer_use_mouse_drag",
    "computer_use_mouse_move",
    "computer_use_mouse_position",
    "computer_use_mouse_scroll",
    "computer_use_screenshot",
    "computer_use_screenshot_compressed",
    "computer_use_screenshot_compressed_region",
    "computer_use_screenshot_region",
    "computer_use_start",
    "computer_use_status",
    "computer_use_stop",
    "computer_use_windows",
]
FILE_TOOLS: list[str] = []
DISALLOWED_DAYTONA_TOOLS = [
    "computer_use_recording_delete",
    "computer_use_recording_get",
    "computer_use_recording_list",
    "computer_use_recording_start",
    "computer_use_recording_stop",
    "create_sandbox",
    "destroy_sandbox",
    "execute_command",
    "git_clone",
    "preview_link",
]


class HarnessError(RuntimeError):
    """Raised for CLI or harness-level failures."""


class EpisodeError(RuntimeError):
    """Raised for a single task episode failure."""


@dataclass(frozen=True)
class AgentOptions:
    """Options passed through to a GUI agent CLI."""

    name: str
    model: str | None
    max_turns: int


@dataclass(frozen=True)
class EpisodeSpec:
    """Immutable inputs for one episode."""

    task: Task
    agent: AgentOptions
    snapshot: str
    run_id: str
    root_dir: Path


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Run Windows computer-use eval tasks on fresh Daytona sandboxes and "
            "score the resulting desktop state."
        )
    )
    parser.add_argument(
        "--agent",
        choices=("oracle", "nop", "claude", "codex"),
        required=True,
        help="GUI agent to run for each task. oracle and nop need only common.py/tasks.py.",
    )
    parser.add_argument(
        "--tasks",
        default="all",
        help="Comma-separated task ids to run, or 'all' (default).",
    )
    parser.add_argument(
        "--snapshot",
        default=DEFAULT_SNAPSHOT,
        help=f"Daytona snapshot to create each sandbox from (default: {DEFAULT_SNAPSHOT}).",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of task episodes to run concurrently (default: 1).",
    )
    parser.add_argument(
        "--runs-dir",
        default=DEFAULT_RUNS_DIR,
        help=f"Directory where run artifacts are written (default: {DEFAULT_RUNS_DIR}/).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model name passed through to claude or codex.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=40,
        help="Maximum Claude Code agent turns per task (claude only; default: 40).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.parallel < 1:
            raise HarnessError("--parallel must be at least 1")
        if args.max_turns < 1:
            raise HarnessError("--max-turns must be at least 1")

        selected_tasks = select_tasks(args.tasks, TASKS)
        run_id = utc_run_id()
        run_root = Path(args.runs_dir) / run_id
        try:
            run_root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise HarnessError(f"failed to create run directory {run_root}: {exc}") from exc

        agent = AgentOptions(name=args.agent, model=args.model, max_turns=args.max_turns)
        specs = [
            EpisodeSpec(
                task=task,
                agent=agent,
                snapshot=args.snapshot,
                run_id=run_id,
                root_dir=run_root,
            )
            for task in selected_tasks
        ]
        results = run_episodes(specs, max_workers=args.parallel)
        write_results(run_root, results)
        print_results(results)
        return 0
    except HarnessError as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        return 1


def select_tasks(tasks_arg: str, available: Sequence[Task]) -> list[Task]:
    """Select task objects from a comma-separated CLI value."""

    task_by_id: dict[str, Task] = {}
    duplicate_ids: set[str] = set()
    for task in available:
        if task.id in task_by_id:
            duplicate_ids.add(task.id)
        task_by_id[task.id] = task
        validate_task_id(task.id)

    if duplicate_ids:
        raise HarnessError(f"duplicate task ids in TASKS: {', '.join(sorted(duplicate_ids))}")

    if tasks_arg == "all":
        selected = list(available)
    else:
        ids = [task_id.strip() for task_id in tasks_arg.split(",")]
        if any(not task_id for task_id in ids):
            raise HarnessError("--tasks must be 'all' or a comma-separated list of non-empty ids")
        duplicate_requested = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
        if duplicate_requested:
            raise HarnessError(f"duplicate requested task id(s): {', '.join(duplicate_requested)}")
        missing = [task_id for task_id in ids if task_id not in task_by_id]
        if missing:
            known = ", ".join(sorted(task_by_id))
            raise HarnessError(f"unknown task id(s): {', '.join(missing)}; known ids: {known}")
        selected = [task_by_id[task_id] for task_id in ids]

    if not selected:
        raise HarnessError("no tasks selected")
    return selected


def validate_task_id(task_id: str) -> None:
    """Reject task ids that cannot safely be used as artifact directory names."""

    if task_id in {"", ".", ".."} or "/" in task_id or "\\" in task_id:
        raise HarnessError(f"unsafe task id for artifact directory: {task_id!r}")


def utc_run_id() -> str:
    """Return a compact UTC timestamp for a run artifact directory."""

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def run_episodes(specs: Sequence[EpisodeSpec], max_workers: int) -> list[dict[str, Any]]:
    """Run all requested episodes with bounded thread parallelism."""

    results_by_index: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(run_episode, spec): index for index, spec in enumerate(specs)}
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results_by_index[index] = future.result()
            except Exception as exc:  # Defensive: run_episode should convert failures to results.
                task = specs[index].task
                results_by_index[index] = {
                    "task": task.id,
                    "agent": specs[index].agent.name,
                    "passed": False,
                    "duration_s": 0.0,
                    "error": f"unhandled worker failure: {format_exception(exc)}",
                }
    return [results_by_index[index] for index in range(len(specs))]


def run_episode(spec: EpisodeSpec) -> dict[str, Any]:
    """Run one task in one fresh sandbox and return its score record."""

    started_at = time.monotonic()
    task_dir = spec.root_dir / spec.task.id
    task_dir.mkdir(parents=True, exist_ok=False)

    sandbox: Any | None = None
    sandbox_id = ""
    passed = False
    error: str | None = None

    try:
        client = get_client()
        sandbox = create_sandbox(
            client,
            snapshot=spec.snapshot,
            name=sandbox_name(spec.run_id, spec.agent.name, spec.task.id),
            labels={
                "guide": "windows-cu-evals",
                "run_id": spec.run_id,
                "task": spec.task.id,
                "agent": spec.agent.name,
            },
        )
        sandbox_id = get_sandbox_id(sandbox)
        start_computer_use(sandbox)
        run_setup_scripts(sandbox, spec.task)
        save_screenshot(sandbox, task_dir / "initial.png")

        agent_error = run_agent_and_capture_error(sandbox, sandbox_id, spec.task, spec.agent)
        final_screenshot_error = capture_final_screenshot(sandbox, task_dir / "final.png")
        error = combine_errors(agent_error, final_screenshot_error)

        if error is None:
            passed = verify_task(sandbox, spec.task)
    except Exception as exc:
        error = combine_errors(error, format_exception(exc))
    finally:
        if sandbox is not None:
            cleanup_error = delete_sandbox(sandbox)
            error = combine_errors(error, cleanup_error)

    duration_s = round(time.monotonic() - started_at, 3)
    return {
        "task": spec.task.id,
        "agent": spec.agent.name,
        "passed": passed,
        "duration_s": duration_s,
        "error": error,
    }


def run_setup_scripts(sandbox: Any, task: Task) -> None:
    """Run all setup scripts and abort the episode if any fails."""

    for index, script in enumerate(task.setup, start=1):
        response = ps_exec(sandbox, script, timeout=120)
        ensure_exec_ok(response, f"setup script {index}")


def save_screenshot(sandbox: Any, path: Path) -> None:
    """Save one full-screen PNG screenshot."""

    path.write_bytes(screenshot_png(sandbox))


def run_agent_and_capture_error(
    sandbox: Any,
    sandbox_id: str,
    task: Task,
    agent: AgentOptions,
) -> str | None:
    """Run the configured agent and return an episode error string if it fails."""

    try:
        run_agent(sandbox, sandbox_id, task, agent)
        return None
    except Exception as exc:
        return format_exception(exc)


def capture_final_screenshot(sandbox: Any, path: Path) -> str | None:
    """Save final.png even when the agent failed, when possible."""

    try:
        save_screenshot(sandbox, path)
        return None
    except Exception as exc:
        return f"final screenshot failed: {format_exception(exc)}"


def run_agent(sandbox: Any, sandbox_id: str, task: Task, agent: AgentOptions) -> None:
    """Dispatch the selected agent implementation."""

    if agent.name == "oracle":
        run_oracle_agent(sandbox, task)
    elif agent.name == "nop":
        time.sleep(2)
    elif agent.name == "claude":
        run_claude_agent(sandbox_id, task, agent)
    elif agent.name == "codex":
        run_codex_agent(sandbox_id, task, agent)
    else:  # argparse choices prevent this.
        raise EpisodeError(f"unknown agent: {agent.name}")


def run_oracle_agent(sandbox: Any, task: Task) -> None:
    """Solve the task by running its oracle PowerShell scripts."""

    deadline = time.monotonic() + task.timeout_s
    for index, script in enumerate(task.oracle, start=1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EpisodeError(f"oracle timed out after {task.timeout_s}s")
        response = ps_exec(sandbox, script, timeout=max(1, int(remaining)))
        ensure_exec_ok(response, f"oracle script {index}")


def run_claude_agent(sandbox_id: str, task: Task, agent: AgentOptions) -> None:
    """Run Claude Code against the Daytona MCP computer-use tools."""

    prompt = build_prompt(task, sandbox_id)
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key:
        raise EpisodeError("DAYTONA_API_KEY is required for Claude's Daytona MCP server")

    mcp_env = {"DAYTONA_API_KEY": api_key}
    if os.environ.get("DAYTONA_API_URL"):
        mcp_env["DAYTONA_API_URL"] = os.environ["DAYTONA_API_URL"]

    with tempfile.TemporaryDirectory(prefix="windows-evals-claude-") as temp_dir:
        config_path = Path(temp_dir) / "mcp.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "daytona": {
                            "command": "daytona",
                            "args": ["mcp", "start"],
                            "env": mcp_env,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        # Claude Code docs: `claude -p`, `--mcp-config`, `--strict-mcp-config`,
        # `--tools`, `--allowedTools`, `--disallowedTools`, `--permission-mode`,
        # `--output-format`, and `--max-turns` are documented at
        # https://code.claude.com/docs/en/cli-reference; the headless guide
        # documents comma-separated `--allowedTools`. Daytona documents
        # `daytona mcp start` and mcpServers JSON at https://www.daytona.io/docs/en/mcp.md.
        command = [
            "claude",
            "--bare",
            "-p",
            prompt,
            "--mcp-config",
            str(config_path),
            "--strict-mcp-config",
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(prefixed_claude_tools(COMPUTER_USE_TOOLS + FILE_TOOLS)),
            "--disallowedTools",
            ",".join(prefixed_claude_tools(DISALLOWED_DAYTONA_TOOLS)),
            "--output-format",
            "text",
            "--max-turns",
            str(agent.max_turns),
        ]
        if agent.model:
            command.extend(["--model", agent.model])
        run_subprocess(command, timeout_s=task.timeout_s, name="claude")


def run_codex_agent(sandbox_id: str, task: Task, agent: AgentOptions) -> None:
    """Run Codex CLI against a curated Daytona MCP server."""

    prompt = build_prompt(task, sandbox_id)
    env = os.environ.copy()
    if "CODEX_API_KEY" not in env and "OPENAI_API_KEY" in env:
        env["CODEX_API_KEY"] = env["OPENAI_API_KEY"]

    # Codex docs: `codex exec` is the non-interactive command
    # (https://developers.openai.com/codex/noninteractive), MCP servers are
    # configured with `[mcp_servers.<name>]` `command`, `args`, `env_vars`, and
    # `enabled_tools` (https://developers.openai.com/codex/mcp), and repeatable
    # `-c key=value` overrides are documented at
    # https://developers.openai.com/codex/config-advanced#one-off-overrides-from-the-cli.
    command = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--skip-git-repo-check",
        "--ephemeral",
    ]
    if agent.model:
        command.extend(["--model", agent.model])
    for override in codex_mcp_overrides(task.timeout_s):
        command.extend(["-c", override])
    command.append(prompt)
    run_subprocess(command, timeout_s=task.timeout_s, name="codex", env=env)


def build_prompt(task: Task, sandbox_id: str) -> str:
    """Build the shared prompt for GUI agents."""

    return (
        f"{task.instruction}\n\n"
        "Context:\n"
        f"- Target Daytona sandbox id: {sandbox_id}\n"
        f"- Interact ONLY through the daytona MCP computer_use_* tools against sandbox {sandbox_id}.\n"
        "- The desktop is 1024x768.\n"
        "- Do NOT use the execute_command tool.\n"
        "- The task is complete when the described end state exists on disk; do not verify via shell.\n"
    )


def prefixed_claude_tools(tool_names: Iterable[str]) -> list[str]:
    """Return Claude Code MCP permission-rule names for Daytona tools."""

    return [f"mcp__daytona__{tool_name}" for tool_name in tool_names]


def codex_mcp_overrides(timeout_s: int) -> list[str]:
    """Build Codex `-c` overrides for the Daytona MCP server."""

    env_vars = ["DAYTONA_API_KEY"]
    if os.environ.get("DAYTONA_API_URL"):
        env_vars.append("DAYTONA_API_URL")

    return [
        'mcp_servers.daytona.command="daytona"',
        'mcp_servers.daytona.args=["mcp","start"]',
        f"mcp_servers.daytona.env_vars={toml_string_array(env_vars)}",
        "mcp_servers.daytona.enabled=true",
        "mcp_servers.daytona.required=true",
        f"mcp_servers.daytona.startup_timeout_sec={min(max(timeout_s, 10), 60)}",
        f"mcp_servers.daytona.tool_timeout_sec={max(timeout_s, 60)}",
        f"mcp_servers.daytona.enabled_tools={toml_string_array(COMPUTER_USE_TOOLS + FILE_TOOLS)}",
        'approval_policy="never"',
        'sandbox_mode="read-only"',
    ]


def toml_string_array(values: Sequence[str]) -> str:
    """Return a TOML-compatible array of strings."""

    return "[" + ",".join(json.dumps(value) for value in values) + "]"


def run_subprocess(
    command: Sequence[str],
    *,
    timeout_s: int,
    name: str,
    env: dict[str, str] | None = None,
) -> None:
    """Run an external agent CLI with a wall-clock timeout."""

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EpisodeError(f"{name} CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise EpisodeError(f"{name} timed out after {timeout_s}s") from exc

    if completed.returncode != 0:
        detail = "\n".join(
            part
            for part in (
                f"stdout: {truncate(completed.stdout.strip())}" if completed.stdout.strip() else "",
                f"stderr: {truncate(completed.stderr.strip())}" if completed.stderr.strip() else "",
            )
            if part
        )
        suffix = f": {detail}" if detail else ""
        raise EpisodeError(f"{name} exited with code {completed.returncode}{suffix}")


def verify_task(sandbox: Any, task: Task) -> bool:
    """Run the task verifier and apply the guide pass criterion."""

    response = ps_exec(sandbox, task.verify, timeout=120)
    if response_exit_code(response) != 0:
        output = truncate(response_result(response).strip())
        suffix = f": {output}" if output else ""
        raise EpisodeError(f"verifier exited with code {response_exit_code(response)}{suffix}")
    return last_non_empty_line(response_result(response)) == "PASS"


def ensure_exec_ok(response: Any, label: str) -> None:
    """Raise EpisodeError if a PowerShell exec response failed."""

    exit_code = response_exit_code(response)
    if exit_code != 0:
        output = truncate(response_result(response).strip())
        suffix = f": {output}" if output else ""
        raise EpisodeError(f"{label} failed with exit code {exit_code}{suffix}")


def response_exit_code(response: Any) -> int:
    """Extract an exit code from a Daytona SDK execute response."""

    if isinstance(response, dict):
        value = response.get("exit_code", response.get("exitCode"))
    else:
        value = getattr(response, "exit_code", None)
        if value is None:
            value = getattr(response, "exitCode", None)
    if value is None:
        raise EpisodeError(f"exec response missing exit code: {type(response).__name__}")
    return int(value)


def response_result(response: Any) -> str:
    """Extract stdout text from a Daytona SDK execute response."""

    if isinstance(response, dict):
        value = response.get("result", "")
    else:
        value = getattr(response, "result", "")
    text = "" if value is None else str(value)
    return strip_clixml_noise(text)


def last_non_empty_line(text: str) -> str:
    """Return the last non-empty stdout line, or an empty string."""

    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def get_sandbox_id(sandbox: Any) -> str:
    """Extract a sandbox id from the SDK sandbox object."""

    for attr in ("id", "sandbox_id", "sandboxId"):
        value = getattr(sandbox, attr, None)
        if value:
            return str(value)
    raise EpisodeError(f"sandbox object missing id: {type(sandbox).__name__}")


def sandbox_name(run_id: str, agent_name: str, task_id: str) -> str:
    """Build a Daytona-safe sandbox name."""

    slug = re.sub(r"[^a-z0-9-]+", "-", f"win-eval-{run_id}-{agent_name}-{task_id}".lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:63].strip("-") or "win-eval"


def delete_sandbox(sandbox: Any) -> str | None:
    """Delete a sandbox and return any cleanup error."""

    try:
        sandbox.delete()
        return None
    except Exception as exc:
        return f"cleanup failed: {format_exception(exc)}"


def combine_errors(*errors: str | None) -> str | None:
    """Join non-empty error messages."""

    parts = [error for error in errors if error]
    return "; ".join(parts) if parts else None


def truncate(text: str, limit: int = 800) -> str:
    """Keep subprocess and exec diagnostics readable."""

    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def format_exception(exc: BaseException) -> str:
    """Format an exception without a traceback for result JSON."""

    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


def write_results(run_root: Path, results: Sequence[dict[str, Any]]) -> None:
    """Write the result records once after all episodes finish."""

    try:
        (run_root / RESULTS_FILE).write_text(json.dumps(list(results), indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"failed to write {RESULTS_FILE}: {exc}") from exc


def print_results(results: Sequence[dict[str, Any]]) -> None:
    """Print a markdown table and one-line summary."""

    print("| task | agent | pass/fail | duration |")
    print("|---|---|---|---:|")
    for result in results:
        status = result_status(result)
        print(f"| {result['task']} | {result['agent']} | {status} | {result['duration_s']:.3f}s |")

    passed = sum(1 for result in results if result.get("passed") is True and not result.get("error"))
    errors = sum(1 for result in results if result.get("error"))
    failed = len(results) - passed - errors
    print(f"Summary: {passed}/{len(results)} passed, {failed} failed, {errors} errored.")


def result_status(result: dict[str, Any]) -> str:
    """Return the table status for a result record."""

    if result.get("error"):
        return "error"
    return "pass" if result.get("passed") else "fail"


if __name__ == "__main__":
    raise SystemExit(main())
