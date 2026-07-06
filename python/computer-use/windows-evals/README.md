# Windows Computer-Use Evals on Daytona

This example builds a reusable Windows snapshot, defines an 8-task GUI eval suite, and runs Claude Code or Codex CLI through Daytona's MCP computer-use tools.

## What you will build

- A Windows snapshot based on `windows-medium`, with Python 3.13 and the eval files already installed.
- An 8-task GUI suite that uses stock Windows apps such as Notepad, Explorer, Calculator, Paint, and PowerShell.
- A harness that runs Claude Code or Codex CLI through Daytona's `computer_use_*` MCP tools.
- Verifiers that run outside the agent loop and check the real filesystem, registry, or app output after each task.

## Requirements

- Python 3.10 or higher on your machine.
- A Daytona account and API key.
- Claude Code and/or Codex CLI only for `--agent claude` / `--agent codex` runs. The `oracle` and `nop` agents need neither.

## Setup

```bash
git clone https://github.com/daytona/guides.git
cd guides/python/computer-use/windows-evals
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
cp .env.example .env  # macOS/Linux
# Windows PowerShell: Copy-Item .env.example .env
# edit .env with your Daytona API key
```

The scripts also load `.env` automatically from this directory, while any variables you export in your shell take precedence.

Environment variables:

- `DAYTONA_API_KEY`: required for all scripts. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- `DAYTONA_API_URL`: optional, only when targeting a non-default API endpoint.
- `ANTHROPIC_API_KEY`: only for `harness.py --agent claude`.
- `OPENAI_API_KEY`: only for `harness.py --agent codex`.

## Workflow

1. Build the reusable eval snapshot once:

   ```bash
   python prep_snapshot.py
   ```

2. Check the verifiers with the built-in agents:

   ```bash
   python harness.py --agent oracle
   python harness.py --agent nop
   ```

   The `oracle` agent should pass all 8 tasks. The `nop` agent should fail all 8 tasks.

3. Run a real agent on a subset or the full suite:

   ```bash
   python harness.py --agent claude --tasks notepad-write-save,calc-to-notepad
   python harness.py --agent codex --parallel 4
   ```

Each episode creates a fresh sandbox from the derived snapshot, starts Daytona computer use, runs the selected agent over MCP, verifies final state from outside the agent loop, and deletes the sandbox. Run artifacts are written under `runs/<timestamp>/` and include `results.json`, `initial.png`, and `final.png` for each task.

## Files

- `prep_snapshot.py`: creates the `windows-cu-evals-v1` snapshot from `windows-medium`.
- `tasks.py`: defines the 8 GUI tasks, setup scripts, verifiers, and oracle scripts.
- `harness.py`: runs episodes through `oracle`, `nop`, Claude Code, or Codex CLI.
- `common.py`: shared Daytona client, PowerShell, and screenshot helpers.
- `.env.example`: environment variable template.
