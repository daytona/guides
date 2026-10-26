# Fireworks Coding Agent Example (Fireworks AI + Daytona)

## Overview

This example demonstrates how to run a coding agent powered by [Fireworks AI](https://fireworks.ai) open models (Kimi, DeepSeek, Qwen, GLM, ...) inside a [Daytona](https://daytona.io) sandbox, with the Fireworks API key handled as a **BYOK (bring your own key) secret** that never enters the sandbox in plaintext.

The agent receives a small coding task (`tests.py`), iterates with `write_file` / `run_bash` tools until the tests pass, and exports its full trajectory in the OpenAI messages format — directly usable as a **Fireworks supervised fine-tuning dataset**.

## Features

- **BYOK via Daytona secrets:** The Fireworks key is stored as an organization secret with a host allowlist (`api.fireworks.ai`). The sandbox only ever holds an opaque placeholder; Daytona's outbound proxy substitutes the real key at request time, and response scrubbing prevents sandbox code from ever reading it
- **Open-model inference:** The agent calls Fireworks' OpenAI-compatible serverless API from inside the sandbox — no code changes versus any other OpenAI-compatible provider
- **Safe code execution:** Everything the model writes and runs executes in an isolated Daytona sandbox, not on your machine
- **Verifiable outcome:** The task is graded by `python tests.py` — the same pass/fail signal a verifier produces in reinforcement learning
- **Fine-tuning data export:** The full multi-turn trajectory (system/user/assistant/tool messages, including `tool_calls`) is saved as `trajectory.jsonl`, ready for `firectl dataset create`

## Requirements

- **Python:** Version 3.10 or higher

> [!TIP]
> It's recommended to use a virtual environment (`venv` or `poetry`) to isolate project dependencies.

## Environment Variables

- `DAYTONA_API_KEY`: Required for access to Daytona sandboxes. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- `FIREWORKS_API_KEY`: Required. Get it from the [Fireworks Dashboard](https://app.fireworks.ai). Used once on the host to create/rotate the Daytona secret — it is never sent to the sandbox
- `FIREWORKS_MODEL` (optional): Any serverless model from the [Fireworks model library](https://fireworks.ai/models). Defaults to `accounts/fireworks/models/kimi-k3`

See the `.env.example` file for the exact structure. Copy `.env.example` to `.env` and fill in your API keys before running.

## Getting Started

1. Create and activate a virtual environment:

   ```bash
   python3.10 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -e .
   ```

3. Copy `.env.example` to `.env` and add your API keys.

4. Run the example:

   ```bash
   python main.py
   ```

## How It Works

### 1. BYOK secret (host side, `main.py`)

The host stores your Fireworks key as a Daytona organization secret with a host allowlist:

```python
daytona.secret.create(CreateSecretParams(
    name="fireworks-api-key",
    value=fireworks_key,
    hosts=["api.fireworks.ai"],
))
```

When the sandbox is created, the secret is mounted as an environment variable. The variable holds an opaque placeholder (`dtn_secret_...`), not the key:

```python
sandbox = daytona.create(CreateSandboxFromSnapshotParams(
    language="python",
    secrets={"FIREWORKS_API_KEY": "fireworks-api-key"},
))
```

The script proves both halves of the model:

- `printenv FIREWORKS_API_KEY` inside the sandbox prints the placeholder
- an authenticated `curl` to `https://api.fireworks.ai/inference/v1/models` returns `200`, proving the proxy substituted the real key (Fireworks would reject the placeholder with a `401`)

Because substitution only happens for `api.fireworks.ai`, agent code cannot leak the key to any other host — a request anywhere else carries the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets) for details.

### 2. Agent loop (sandbox side, `agent.py`)

The agent runs entirely inside the sandbox and talks to Fireworks through the standard OpenAI client:

```python
client = OpenAI(
    base_url="https://api.fireworks.ai/inference/v1",
    api_key=os.environ["FIREWORKS_API_KEY"],  # the placeholder
)
```

It exposes two tools to the model — `write_file` and `run_bash` — and loops until the model stops calling tools or hits the turn limit. The task: implement `solution.py` so that `python tests.py` passes.

### 3. Verification and trajectory export

After the loop, the agent reruns `tests.py` as the final verdict and writes the complete message history to `trajectory.jsonl`:

```json
{"messages": [{"role": "system", ...}, {"role": "assistant", "tool_calls": [...]}, {"role": "tool", ...}, ...]}
```

The host downloads the file. Fireworks uses the same OpenAI-compatible format for supervised fine-tuning data, so successful trajectories can be uploaded as-is:

```bash
firectl dataset create my-agent-trajectories trajectory.jsonl
```

Collect many successful runs (vary the tasks), and you have an SFT dataset distilled from your own agent — the standard first step before [reinforcement learning on the Fireworks Training API](https://docs.fireworks.ai/fine-tuning/training-api/cookbook/agentic-rl).

## Next Steps

- Swap in your own task by replacing `tests.py` — anything gradeable by exit code works
- Scale out: create hundreds of sandboxes in parallel for batch data generation (see the [RL guides](https://www.daytona.io/docs/en/guides) for the pool pattern)
- Train on the verifiable signal: the `tests.py` exit code used here is exactly the reward a verifier computes in Fireworks' [Agentic RL cookbook](https://docs.fireworks.ai/fine-tuning/training-api/cookbook/agentic-rl) — see also Daytona's [reinforcement learning guides](https://www.daytona.io/docs/en/guides/reinforcement-learning/openenv-finqa)
