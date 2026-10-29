# Coding Agent Example (Pydantic AI + Daytona)

## Overview

This example builds a [Pydantic AI](https://pydantic.dev/docs/ai/) coding agent using its native Daytona integration in `pydantic_ai_harness.daytona_sandbox`. The integration supplies the run's workspace; the harness `Coder` capability supplies the file and shell tools that operate in it.

The agent implements `moving_average(values, window)` in `stats.py`, writes pytest tests, executes them in a Daytona sandbox, and fixes failures until the suite passes. A second run adds a test in the same sandbox using its workspace ref. The script explicitly deletes the sandbox in `finally`.

A moving average is the mean of every `window` consecutive values, a common way to smooth noisy data such as sensor readings. For example, `moving_average([1, 2, 3, 4], 2)` returns `[1.5, 2.5, 3.5]`.

## Features

- **Sandbox execution:** Generated files and commands stay in the Daytona workspace.
- **Test-driven iteration:** The agent writes tests, runs them, and corrects errors or missing dependencies.
- **Workspace reuse:** A follow-up run reattaches by ref without replaying message history.
- **Typed output:** Each run returns a validated `TestReport`; a run that reports failed tests stops the script.
- **Tool trace:** Each run prints bounded sandbox tool arguments and results, followed by its JSON report.
- **Explicit cleanup:** The script keeps the sandbox ref reachable even if the first model run fails.

## Requirements

- **Python 3.11 or higher.**
- **Daytona account and API key.**
- **Anthropic API key** with access to `claude-sonnet-5`, or a supported model override.

> [!TIP]
> It's recommended to use a virtual environment (`venv` or `poetry`) to isolate project dependencies.

## Environment Variables

- `DAYTONA_API_KEY`: Required. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- `ANTHROPIC_API_KEY`: Required for the default model. Get it from [Anthropic Console](https://console.anthropic.com/).
- `MODEL` (optional): Model in `provider:model` format. Defaults to `anthropic:claude-sonnet-5`.

Copy `.env.example` to `.env` and fill in your keys. Your API keys stay on your machine: the agent calls the model from your application, and only the generated code runs in Daytona. Nothing from your machine's environment, including the keys in `.env`, reaches the sandbox.

## Getting Started

Clone the repository and open the example directory:

```bash
git clone https://github.com/daytona/guides.git
cd guides/python/pydantic-ai/coding-agent
cp .env.example .env
```

### Setup and Run

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -U "pydantic-ai-harness[daytona,anthropic]" python-dotenv
   ```

   The `daytona` extra installs the Daytona SDK. The `anthropic` extra installs the matching `pydantic-ai-slim[anthropic]` provider dependencies.

3. Fill in `.env`, then run:

   ```bash
   python main.py
   ```

## Configuration

- **Model:** `os.getenv("MODEL", "anthropic:claude-sonnet-5")` selects the model. For another provider, install its Pydantic AI extra and set the corresponding API key.
- **Task:** `TASK` defines the implementation and edge cases: valid windows over empty input return `[]`; oversized windows return `[]`; windows below 1 raise `ValueError`, including for empty input.
- **Follow-up:** `FOLLOWUP` adds a test for negative values without replacing the existing tests.
- **Workspace:** `WORKING_DIR` is `/home/daytona/project`. Both the initial backend and the reattachment capability use it. Settings on a capability do not override a caller-supplied backend.
- **Tools:** `Coder(sub_agents=False)` disables delegation for this small task. It exposes `shell`, `read_file`, `write_file`, `edit_file`, `list_files`, and `grep`. `DaytonaSandbox` itself adds no tools.
- **Dependencies inside Daytona:** The agent installs pytest if the default snapshot lacks it. Installing packages in your local virtual environment does not install them in the sandbox.

## How It Works

1. **Create the workspace:** A caller-owned `DaytonaSandboxBackend` creates the sandbox on first use during the run. Keeping the backend reachable gives `finally` access to its ref even if a model call fails before returning a result.
2. **Generate and test:** `await agent.run(TASK, workspace=backend)` writes the implementation and pytest tests, runs them, and corrects failures.
3. **Inspect the run:** `print_trace` reads `result.new_messages()` and prints sandbox tool calls and returns, excluding the default `final_result` output tool. Payloads are shortened; this is not a full audit log. The script prints the typed report and stops if it reports failed tests.
4. **Reattach:** The second call uses `workspace=first.workspace.ref`. It starts a new conversation in the same files, reads the existing implementation and tests, adds one test, and runs the full suite.
5. **Delete:** `await sandbox.destroy(ref)` runs in `finally`. The enclosing `aclosing` releases the caller-owned backend's client, which is separate from deleting the sandbox.

You can also continue with `message_history=first.all_messages()`; the native integration finds the sandbox ref in that history. Without a ref or history, a new run creates a new sandbox. A ref contains no credentials, so reattachment still requires `DAYTONA_API_KEY`.

### Typed output

`Agent(..., output_type=TestReport)` turns the report model into a JSON schema that the model fills through an output tool. Pydantic validates the final answer, so `result.output` is a `TestReport`, not a summary string. Its fields describe changed files, passed and failed test counts, and the final pytest output line.

If output validation fails, Pydantic AI sends the validation errors back to the model to retry. By default it retries once; pass `retries={"output": N}` to `Agent` to change that. Running out of retries raises `UnexpectedModelBehavior`. This validates the report's structure, not whether the model accurately reported pytest; compare it with the shell trace.

The script prints each report with `model_dump_json(indent=2)` and checks its failure count. If run 1 reports failed tests, `raise RuntimeError(...)` ends `main()` before the follow-up run; if run 2 does, the script exits with the error after it. Either way, the `finally` block still deletes the sandbox.

### Clean up

**The native integration never stops or deletes the sandbox when a run ends.** Sandboxes retain their disk until deleted. The script deletes its sandbox after both runs, including when a run raises an exception. Download any files you want to keep before cleanup.

If your application keeps a sandbox instead, for example to continue work in a later session, store its ID (the script prints it after the first run). A later process can rebuild the ref from that ID, pass it as `workspace=ref` to reattach, or delete the sandbox:

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_ai_harness.daytona_sandbox import DaytonaSandbox

ref = WorkspaceRef(provider="daytona", id="YOUR_SANDBOX_ID")
await DaytonaSandbox().destroy(ref)
```

Deleting by ref does not start a stopped sandbox first. The ref holds no credentials, so the process that deletes or reattaches still needs `DAYTONA_API_KEY`.

## Example Output

The following excerpts are from a real run with `anthropic:claude-sonnet-5`. Long file payloads and some tool results are omitted. Model responses and test counts can vary.

```text
Sandbox: fee5575f-8885-4ca8-a32c-02e7724bc894

Run 1 tool trace:
  -> list_files {"path":"."}
  <- list_files No files found.
  ... write_file calls created stats.py and test_stats.py ...
  -> shell {"command":"cd /home/daytona/project && python -m pytest -q 2>&1 | tail -30"}
  <- shell /usr/local/bin/python: No module named pytest ...
  -> shell {"command":"cd /home/daytona/project && pip install pytest -q 2>&1 | tail -20"}
  ... installation output omitted ...
  -> shell {"command":"cd /home/daytona/project && python -m pytest -q 2>&1 | tail -30"}
  <- shell .......... [100%] 10 passed in 0.03s ...
  ... workspace listing and cache cleanup omitted ...
{
  "files": [
    "stats.py",
    "test_stats.py"
  ],
  "tests_passed": 10,
  "tests_failed": 0,
  "pytest_summary": "10 passed in 0.03s"
}

Reattaching: fee5575f-8885-4ca8-a32c-02e7724bc894

Run 2 tool trace:
  -> read_file {"path":"stats.py"}
  -> read_file {"path":"test_stats.py"}
  ... edit_file added test_negative_values ...
  -> shell {"command":"cd /home/daytona/project && python -m pytest -q"}
  <- shell ........... [100%] 11 passed in 0.02s ...
{
  "files": [
    "test_stats.py"
  ],
  "tests_passed": 11,
  "tests_failed": 0,
  "pytest_summary": "11 passed in 0.02s"
}
Run 2 workspace: WorkspaceRef(provider='daytona', id='fee5575f-8885-4ca8-a32c-02e7724bc894')
Deleted sandbox: fee5575f-8885-4ca8-a32c-02e7724bc894
```

The first run corrected a missing dependency, not an implementation bug. The follow-up preserved the original ten tests and added an eleventh. Both typed reports matched the final pytest results.

## API Reference

- [`DaytonaSandbox` and `DaytonaSandboxBackend`](https://pydantic.dev/docs/ai/harness/daytona-sandbox/): native workspace creation, reattachment, configuration, and deletion.
- [`Coder`](https://pydantic.dev/docs/ai/harness/coder/): file tools and shell execution.
- [Workspaces](https://pydantic.dev/docs/ai/core-concepts/workspace/): workspace refs and run ownership.

### Alternative: pydantic-ai-daytona

Daytona also maintains [`pydantic-ai-daytona`](https://pypi.org/project/pydantic-ai-daytona/) ([source](https://github.com/daytona/integrations/tree/main/packages/pydantic-ai-daytona)), a Pydantic AI capability that works without the harness. The two approaches differ as follows:

| Feature | Native integration | pydantic-ai-daytona |
| --- | --- | --- |
| Tools | None of its own; `Coder` and other harness capabilities supply them | Its own `run_command`, `read_file`, `write_file`, and `list_directory` |
| Dependencies | `pydantic-ai-harness`; Python 3.11+ | `pydantic-ai-slim` and the Daytona SDK; Python 3.10+ |
| Sandbox lifetime | Persists after a run until you delete it | Created per run and deleted when the run ends (default) |
| Reuse across runs | Reattach by ref or message history | Share one `DaytonaSandboxSession`, or attach with `sandbox_id=` |
| Sandbox creation options | `snapshot`, `allow_internet_access`, `auto_stop_interval` | Also a container `image`, network allow lists by CIDR or domain, `ephemeral`, `auto_delete_interval`, `labels`, and `os_user` |

Use the native integration to run harness capabilities such as `Coder` in Daytona and to keep workspaces between runs. Use the package for a self-contained capability that cleans up after each run and offers more control over how the sandbox is created.

**Both packages export a class named `DaytonaSandbox`. The import path decides which one you get.** Use one or the other, not both.

Install it in the same virtual environment as the harness; the Anthropic provider is already installed above:

```bash
pip install -U "pydantic-ai-daytona>=0.2.1"
```

With the same API keys loaded, inside an async function:

```python
import os

from pydantic_ai import Agent
from pydantic_ai_daytona import DaytonaSandbox

model = os.getenv("MODEL", "anthropic:claude-sonnet-5")
agent = Agent(model, capabilities=[DaytonaSandbox()])
result = await agent.run("Run python -c 'print(2 + 2)' in the sandbox and report the result.")
print(result.output)
```

The agent runs the command with the package's `run_command` tool and replies with something like:

```text
The command `python -c 'print(2 + 2)'` output: **4**
```

#### Reuse one sandbox across runs

`DaytonaSandboxSession` owns one sandbox for as long as its `async with` block runs. Pass it to the capability to share that sandbox across runs; the capability uses the session but never closes it. With `model` from the previous snippet:

```python
from pydantic_ai import Agent
from pydantic_ai_daytona import DaytonaSandbox, DaytonaSandboxSession

async with DaytonaSandboxSession() as session:
    agent = Agent(model, capabilities=[DaytonaSandbox(session=session)])
    await agent.run("Create hello.py that prints 'hello from Daytona'.")
    result = await agent.run("Run hello.py and report its output.")
    print(result.output)
```

The second run finds the `hello.py` that the first run created and reports `hello from Daytona`. The sandbox is deleted when the block exits. A sandbox you attach with `sandbox_id=` instead is never deleted by the package.

## License

See the main project [LICENSE](../../../LICENSE) file for details.

## References

- [Pydantic AI](https://pydantic.dev/docs/ai/)
- [Daytona](https://www.daytona.io/)
- [Native Daytona integration source](https://github.com/pydantic/pydantic-ai/tree/main/src/pydantic_ai_harness/pydantic_ai_harness/daytona_sandbox)
- [`pydantic-ai-daytona` Python package](https://pypi.org/project/pydantic-ai-daytona/)
