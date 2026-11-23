# Daytona SDK 2.x migration readiness

This report covers every guide in this repo that uses Daytona, and what it takes to move each one to Daytona SDK 2.x. Each migration lives on its own branch with its own pull request. Nothing here is merged by this report.

## 1. Validity

- Checked: 2026-11-16 (frozen at 2026-11-16T15:48:44Z); PR state refreshed 2026-11-23.
- Base: [`625cdfe`](https://github.com/daytona/guides/commit/625cdfebb95193fa8bf0da2cd9e3358059b1307b) (`main` at the freeze). Every branch starts from it.
- SDK under test: `@daytona/sdk` 2.0.0-alpha.13 and `daytona` 2.0.0a13, migrated with the official upgrade tool of the same version. In 2.x, old-style calls run through the `v0` namespace, which bundles SDK 0.231.1.
- Registry state at the freeze: 2.0.0 was withdrawn on both registries (deprecated on npm, yanked on PyPI), so the newest live pre-release was used.
- Registry state on 2026-11-23: stable 2.1.0 is the default install on both npm (`latest`) and PyPI (published 2026-11-20, not deprecated, not yanked). Stable 2.x went live during this run. The branches still pin the tested pre-release; section 6 says how to flip them.
- Tools: Node 22.23.2, npm 10.9.8, pnpm 10.29.3, uv 0.12.9, Python 3.12.3, Pyright 1.1.414, pytest 9.2.0. Installs were limited to packages published before the freeze (except pnpm, see section 8).
- Ran offline: the upgrade tool, installs, type checks, import checks, the two guides' test suites, lockfile checks, wrapper probes.
- Ran live (2026-11-16 to 2026-11-23): one smoke per migrated guide against the Daytona platform through the 2.x `v0` namespace (section 7).
- Not run: Node 22.15.0 exactly (only the host Node above), GPU, Windows and LLM-driven flows, and anything on v2 sandboxes.

## 2. Answer

37 of 47 guides migrate to SDK 2.x today with the `v0` namespace: 4 need only the version pin, 33 need small, listed changes (mostly the Node.js floor and README samples). Each has a branch and an open pull request (18 ready for review, 19 still draft). The other 10 can't move on their own: 8 depend on a wrapper library and 2 never call the SDK, so their owners have to move first. Native v2 is a separate, later step: 17 guides map cleanly, 19 hit a v2 gap, 11 wait on an owner.

### Open-ended requirements (fixed first)

These requirements had no upper bound, so a plain install would pull SDK 2.x and break. The pin PR caps them below 1.0.0; it merged on 2026-11-16, after this run's base.

| guide | file:line | today (base) | pin | PR |
| --- | --- | --- | --- | --- |
| `python/ag2/bug-fixer-agent` | `README.md:38` | `pip install "ag2[openai]<1.0" daytona python-dotenv` | `pip install "ag2[openai]<1.0" "daytona<1.0.0" python-dotenv` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/claude/claude-managed-agents` | `pyproject.toml:8` | `"daytona",` | `"daytona<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/cognition/devin-outposts` | `pyproject.toml:12` | `"daytona>=0.202.0",` | `"daytona>=0.202.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/computer-use/windows-evals` | `pyproject.toml:7` | `"daytona>=0.202.0",` | `"daytona>=0.202.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/cursor/self-hosted-machines` | `pyproject.toml:12` | `"daytona>=0.202.0",` | `"daytona>=0.202.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/dspy-rlms` | `pyproject.toml:9` | `"daytona>=0.136.0",` | `"daytona>=0.136.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/gemini/gemini-managed-agents` | `pyproject.toml:7` | `"daytona>=0.231",` | `"daytona>=0.231,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/langgraph/plan-and-execute-data-agent` | `README.md:48` | `pip install -U langgraph langchain langchain-anthropic daytona pydantic python-dotenv` | `pip install -U langgraph langchain langchain-anthropic "daytona<1.0.0" pydantic python-dotenv` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/model-serving/sglang` | `pyproject.toml:15` | `"daytona>=0.201.0",` | `"daytona>=0.201.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/model-serving/vllm` | `pyproject.toml:11` | `"daytona>=0.201.0",` | `"daytona>=0.201.0,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/openai/agents-api` | `README.md:39` | `pip install openai daytona python-dotenv` | `pip install openai "daytona<1.0.0" python-dotenv` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/recursive-language-models` | `pyproject.toml:9` | `"daytona>=0.128.1",` | `"daytona>=0.128.1,<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |
| `python/reinforcement-learning/openenv` | `pyproject.toml:9` | `"daytona",` | `"daytona<1.0.0",` | [#43](https://github.com/daytona/guides/pull/43) |

### Matrix

v2 verdicts are for later; not planned now.

| item | kind | migration verdict | branch@sha | v2 verdict (for later; not planned now) | main gap |
| --- | --- | --- | --- | --- | --- |
| `python/ag2/bug-fixer-agent` | PY | REFUSED (exit 1, DaytonaCodeExecutor import fails on CreateSandboxFromImageParams) | no branch | BLOCKED-BY-REWRITE (AG2 DaytonaCodeExecutor) | AG2 `DaytonaCodeExecutor` imports 0.x root names |
| `python/claude/claude-managed-agents` | PY | READY-WITH-CHANGES (FIXME code fixes, README samples) | [feat/claude-managed-agents-sdk2](https://github.com/daytona/guides/tree/feat/claude-managed-agents-sdk2)@[`f44d39a`](https://github.com/daytona/guides/commit/f44d39a968895ab21aa95f48a3a0d222e5695f5e) ([#76](https://github.com/daytona/guides/pull/76), draft) | BLOCKED-BY-V2-GAP (persistent Linux sandboxes) | stop/start/archive of a kept Linux sandbox (`host_lib.py:232,252,274`) |
| `python/cognition/devin-outposts` | PY | READY-WITH-CHANGES (FIXME code fixes, test fakes) | [feat/devin-outposts-sdk2](https://github.com/daytona/guides/tree/feat/devin-outposts-sdk2)@[`fbfba50`](https://github.com/daytona/guides/commit/fbfba504f564793c4f3778b9732d1ed536accfd3) ([#82](https://github.com/daytona/guides/pull/82), draft) | BLOCKED-BY-V2-GAP (Windows sandboxes) | Windows sandboxes (`build_windows_snapshot.py`, `worker_windows.py`) |
| `python/computer-use/windows-evals` | PY | READY-WITH-CHANGES (custom API URL dropped, FIXME code fixes) | [feat/windows-evals-sdk2](https://github.com/daytona/guides/tree/feat/windows-evals-sdk2)@[`6ee21a4`](https://github.com/daytona/guides/commit/6ee21a406824b77b06c8d50f54f922ed42ca4922) ([#80](https://github.com/daytona/guides/pull/80), draft) | BLOCKED-BY-V2-GAP (Windows sandboxes) | Windows sandboxes (`harness.py:29`, `common.py:49-55`) |
| `python/cursor/self-hosted-machines` | PY | READY-WITH-CHANGES (FIXME code fixes, test fakes) | [feat/cursor-self-hosted-machines-sdk2](https://github.com/daytona/guides/tree/feat/cursor-self-hosted-machines-sdk2)@[`dc7c335`](https://github.com/daytona/guides/commit/dc7c3355c2426f2b60011fa8e19012ca12539274) ([#81](https://github.com/daytona/guides/pull/81), draft) | BLOCKED-BY-V2-GAP (Windows sandboxes) | Windows sandboxes (`build_windows_snapshot.py`, `worker_windows.py`) |
| `python/dspy-rlms` | PY | READY-WITH-CHANGES (install hint) | [feat/dspy-rlms-sdk2](https://github.com/daytona/guides/tree/feat/dspy-rlms-sdk2)@[`f4505e5`](https://github.com/daytona/guides/commit/f4505e57891ac5303f8371e360cb0e0ec78c171d) ([#75](https://github.com/daytona/guides/pull/75), draft) | BLOCKED-BY-V2-GAP (session commands) | session commands (`daytona_interpreter.py:409-410`) |
| `python/gemini/gemini-managed-agents` | PY | READY | [feat/gemini-managed-agents-sdk2](https://github.com/daytona/guides/tree/feat/gemini-managed-agents-sdk2)@[`7753202`](https://github.com/daytona/guides/commit/775320205b04687eb234c84261847b9fc75b9459) ([#73](https://github.com/daytona/guides/pull/73), draft) | BLOCKED-BY-V2-GAP (session commands) | session commands (`sandbox_lib.py:46-47,55,60`) |
| `python/langgraph/plan-and-execute-data-agent` | PY | READY-WITH-CHANGES (install line, README samples) | [feat/langgraph-plan-and-execute-data-agent-sdk2](https://github.com/daytona/guides/tree/feat/langgraph-plan-and-execute-data-agent-sdk2)@[`7dd7703`](https://github.com/daytona/guides/commit/7dd7703f461e6aeae2885b458e915d492e84e41d) ([#69](https://github.com/daytona/guides/pull/69), draft) | READY-WITH-CHANGES | register an image before create (`main.py:124`) |
| `python/model-serving/sglang` | PY | READY-WITH-CHANGES (README samples, Secret note) | [feat/sglang-sdk2](https://github.com/daytona/guides/tree/feat/sglang-sdk2)@[`154ddf9`](https://github.com/daytona/guides/commit/154ddf9cc486791f9455fb8f7e17988c2e964162) ([#78](https://github.com/daytona/guides/pull/78), draft) | BLOCKED-BY-V2-GAP (GPU) | GPU (`serve_sglang.py:40-41`) |
| `python/model-serving/vllm` | PY | READY-WITH-CHANGES (README samples, Secret note) | [feat/vllm-sdk2](https://github.com/daytona/guides/tree/feat/vllm-sdk2)@[`222b650`](https://github.com/daytona/guides/commit/222b650981403bc92a47972eb0bb48191c95c3a6) ([#77](https://github.com/daytona/guides/pull/77), draft) | BLOCKED-BY-V2-GAP (GPU) | GPU (`serve_vllm.py:38-39`) |
| `python/openai/agents-api` | PY | READY-WITH-CHANGES (install line) | [feat/openai-agents-api-sdk2](https://github.com/daytona/guides/tree/feat/openai-agents-api-sdk2)@[`564199e`](https://github.com/daytona/guides/commit/564199ee902ee4c7f6bb16095bf9c3a0dcd63d5a) ([#70](https://github.com/daytona/guides/pull/70), draft) | BLOCKED-BY-V2-GAP (persistent Linux sandboxes) | stop/start of a kept Linux sandbox (`webhook_managed.py:97,137-144`) |
| `python/recursive-language-models` | PY | READY | [feat/recursive-language-models-sdk2](https://github.com/daytona/guides/tree/feat/recursive-language-models-sdk2)@[`6c38862`](https://github.com/daytona/guides/commit/6c38862f19de383bb78547b6df97d439c36e6cff) ([#74](https://github.com/daytona/guides/pull/74), draft) | BLOCKED-BY-V2-GAP (session commands) | session commands (`rlm/repl.py:259,266`) |
| `python/reinforcement-learning/openenv` | PY | REFUSED (exit 1, DaytonaProvider import fails on CreateSandboxFromSnapshotParams) | no branch | BLOCKED-BY-REWRITE (OpenEnv DaytonaProvider) | OpenEnv `DaytonaProvider` imports 0.x root names |
| `python/ai-data-analyst` | PY | READY | [feat/py-ai-data-analyst-sdk2](https://github.com/daytona/guides/tree/feat/py-ai-data-analyst-sdk2)@[`1b2ca16`](https://github.com/daytona/guides/commit/1b2ca16e7269200265497305cab4b4aa1ff3dfd3) ([#65](https://github.com/daytona/guides/pull/65), draft) | READY-WITH-CHANGES | no chart artifacts in v2 results (`ai_data_analyst.py:86-93`) |
| `python/anakin/research-agent` | PY | READY | [feat/anakin-research-agent-sdk2](https://github.com/daytona/guides/tree/feat/anakin-research-agent-sdk2)@[`e24e730`](https://github.com/daytona/guides/commit/e24e730996249f6d227a1b7e5db7cc4b49498a05) ([#66](https://github.com/daytona/guides/pull/66), draft) | READY-WITH-CHANGES | network block at create (`research_agent.py:302-304`) |
| `python/computer-use/claude-draws` | PY | REFUSED (exit 1, resolver cannot co-install daytona-claude-toolsets with SDK 2.x) | no branch | BLOCKED-BY-REWRITE (daytona-claude-toolsets) | `daytona-claude-toolsets` pins `daytona<0.224.0` |
| `python/computer-use/openai-computer-use` | PY | READY-WITH-CHANGES (install line) | [feat/openai-computer-use-sdk2](https://github.com/daytona/guides/tree/feat/openai-computer-use-sdk2)@[`3975956`](https://github.com/daytona/guides/commit/39759564018888da490b90c5916701ad3dd36137) ([#68](https://github.com/daytona/guides/pull/68), draft) | READY-WITH-CHANGES | auto-stop/delete intervals -> lifecycle policy (`main.py:78-83`) |
| `python/fireworks/coding-agent` | PY | READY-WITH-CHANGES (README samples) | [feat/fireworks-coding-agent-sdk2](https://github.com/daytona/guides/tree/feat/fireworks-coding-agent-sdk2)@[`7ba28af`](https://github.com/daytona/guides/commit/7ba28af4a16b7cfd0bb4b4b7a6218ad3048a5c04) ([#71](https://github.com/daytona/guides/pull/71), draft) | READY-WITH-CHANGES | secrets move to `v2.secrets` (`main.py:34-72,90-95`) |
| `python/google-adk/code-generator-agent` | PY | REFUSED (exit 1, resolver backtracks to daytona-adk 0.1.0; import fails on CreateSandboxBaseParams) | no branch | BLOCKED-BY-REWRITE (daytona-adk) | `daytona-adk` pins `daytona<0.195.0` |
| `python/langchain/data-analysis` | PY | REFUSED (exit 1, resolver rejects wrapper SDK 0.x constraints) | no branch | BLOCKED-BY-REWRITE (langchain-daytona-data-analysis) | `langchain-daytona-data-analysis` caps `daytona<1.0.0` |
| `python/notte/browser-testing` | PY | READY-WITH-CHANGES (custom API URL dropped, README samples) | [feat/notte-browser-testing-sdk2](https://github.com/daytona/guides/tree/feat/notte-browser-testing-sdk2)@[`c7fee11`](https://github.com/daytona/guides/commit/c7fee116f4a77c77cc6b309a56450fc59ff3466d) ([#72](https://github.com/daytona/guides/pull/72), draft) | BLOCKED-BY-V2-GAP (session commands) | session commands (`browser_test.py:65-66`) |
| `python/pydantic-ai/coding-agent` | PY | REFUSED (exit 1, resolver backtracks to a harness without its Daytona module) | no branch | BLOCKED-BY-REWRITE (pydantic-ai-harness) | `pydantic-ai-harness` caps `daytona<1` |
| `python/reinforcement-learning/trl` | PY | READY-WITH-CHANGES (private import) | [feat/trl-sdk2](https://github.com/daytona/guides/tree/feat/trl-sdk2)@[`8d146b0`](https://github.com/daytona/guides/commit/8d146b08e8274d4a5486cc4a336514e49aff27f2) ([#79](https://github.com/daytona/guides/pull/79), draft) | READY-WITH-CHANGES | interpreter run has no callbacks (`train.py:198`) |
| `python/reinforcement-learning/verl-retool` | PY | REFUSED (exit 1, wrapper uses missing root symbols and forwards rejected api_url) | no branch | BLOCKED-BY-REWRITE (veRL ReTool) | veRL ReTool tool imports 0.x root names, passes `api_url` |
| `typescript/agentkit-inngest/coding-agent` | TS | READY-WITH-CHANGES (Node floor, deep import) | [feat/agentkit-inngest-coding-agent-sdk2](https://github.com/daytona/guides/tree/feat/agentkit-inngest-coding-agent-sdk2)@[`098a469`](https://github.com/daytona/guides/commit/098a469cc5e8e8fce843186a9127c4672390b4a7) ([#59](https://github.com/daytona/guides/pull/59), ready) | BLOCKED-BY-V2-GAP (session commands) | session commands (`src/index.ts:235-269`) |
| `typescript/ai-data-analyst` | TS | READY-WITH-CHANGES (Node floor) | [feat/ts-ai-data-analyst-sdk2](https://github.com/daytona/guides/tree/feat/ts-ai-data-analyst-sdk2)@[`7c5e860`](https://github.com/daytona/guides/commit/7c5e860357b941859d609b530b390a8eb2ef29d4) ([#45](https://github.com/daytona/guides/pull/45), ready) | READY-WITH-CHANGES | no chart artifacts in v2 results (`index.ts:70-71`) |
| `typescript/amp/amp-sdk` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/amp-sdk-sdk2](https://github.com/daytona/guides/tree/feat/amp-sdk-sdk2)@[`fc7ff6b`](https://github.com/daytona/guides/commit/fc7ff6b881f9a06091b636ad783b557573cd8e38) ([#47](https://github.com/daytona/guides/pull/47), ready) | BLOCKED-BY-V2-GAP (session commands) | session commands (`src/index.ts:108,111,125`) |
| `typescript/anchor/cloud-browser` | TS | READY-WITH-CHANGES (Node floor) | [feat/anchor-cloud-browser-sdk2](https://github.com/daytona/guides/tree/feat/anchor-cloud-browser-sdk2)@[`c0e883a`](https://github.com/daytona/guides/commit/c0e883aff7cc02e3e0944a81ac9d8c3240c5f5d9) ([#46](https://github.com/daytona/guides/pull/46), ready) | READY-WITH-CHANGES | `/home/daytona` -> `/root` (`src/index.ts:14`) |
| `typescript/anthropic/multi-agent-claude-sdk` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/multi-agent-claude-sdk-sdk2](https://github.com/daytona/guides/tree/feat/multi-agent-claude-sdk-sdk2)@[`e8cb66c`](https://github.com/daytona/guides/commit/e8cb66cd22f48f30af179f38bea13de009658b8a) ([#49](https://github.com/daytona/guides/pull/49), ready) | READY-WITH-CHANGES | no streaming callbacks (`src/index.ts:106-114`) |
| `typescript/anthropic/single-claude-agent-sdk` | TS | READY-WITH-CHANGES (Node floor, internal types, Secret note, README samples) | [feat/single-claude-agent-sdk-sdk2](https://github.com/daytona/guides/tree/feat/single-claude-agent-sdk-sdk2)@[`c86f658`](https://github.com/daytona/guides/commit/c86f6585a7f41df025571cf9ab4c3545601e7969) ([#58](https://github.com/daytona/guides/pull/58), ready) | READY-WITH-CHANGES | no streaming callbacks (`src/index.ts:21,94`) |
| `typescript/brainbase/universal-harness-api` | TS | NO-SDK (platform) | no branch | BLOCKED-BY-REWRITE (Brainbase platform) | Brainbase runs the sandboxes |
| `typescript/cognition/devin-cli` | TS | READY-WITH-CHANGES (Node floor) | [feat/devin-cli-sdk2](https://github.com/daytona/guides/tree/feat/devin-cli-sdk2)@[`be099fb`](https://github.com/daytona/guides/commit/be099fb2eefd184d829036b3fd5e85337ae6f4a6) ([#48](https://github.com/daytona/guides/pull/48), ready) | READY-WITH-CHANGES | PTY calls move to the v2 PTY API (`src/session.ts:63-94`) |
| `typescript/computer-use/claude-draws` | TS | REFUSED (exit 2, tsc TS2379 from nested SDK 0.x Sandbox type) | no branch | BLOCKED-BY-REWRITE (@daytona/claude-toolsets) | `@daytona/claude-toolsets` depends on `@daytona/sdk ^0.223.0` |
| `typescript/convex/ai-app-builder` | TS | NO-SDK (REST) | no branch | BLOCKED-BY-REWRITE (@daytona/convex REST) | `@daytona/convex` calls the v0 REST API |
| `typescript/copilotkit/generative-ui-coding-agent` | TS | READY-WITH-CHANGES (Node floor, README samples) | [feat/copilotkit-generative-ui-coding-agent-sdk2](https://github.com/daytona/guides/tree/feat/copilotkit-generative-ui-coding-agent-sdk2)@[`bf2f980`](https://github.com/daytona/guides/commit/bf2f980ef15acf45b0fc17c8835e66e1c2be3b1c) ([#67](https://github.com/daytona/guides/pull/67), draft) | BLOCKED-BY-V2-GAP (session commands) | session commands (`app/api/copilotkit/route.ts:84-85,246-247`) |
| `typescript/flue` | TS | READY-WITH-CHANGES (Node floor, engines, Secret note, README samples) | [feat/flue-sdk2](https://github.com/daytona/guides/tree/feat/flue-sdk2)@[`c043daf`](https://github.com/daytona/guides/commit/c043dafc8670cc402fbf237d4d64b376959324e3) ([#57](https://github.com/daytona/guides/pull/57), ready) | READY-WITH-CHANGES | `getWorkDir()` has no v2 helper (`.flue/connectors/daytona.ts:117`) |
| `typescript/gemini/gemini-cli` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/gemini-cli-sdk2](https://github.com/daytona/guides/tree/feat/gemini-cli-sdk2)@[`ae146d2`](https://github.com/daytona/guides/commit/ae146d28b8cfcd700067d478954bb4e6869f2db9) ([#50](https://github.com/daytona/guides/pull/50), ready) | READY-WITH-CHANGES | PTY calls move to the v2 PTY API (`src/session.ts:103-128`) |
| `typescript/kimi/kimi-cli` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples, lock drift) | [feat/kimi-cli-sdk2](https://github.com/daytona/guides/tree/feat/kimi-cli-sdk2)@[`07ea845`](https://github.com/daytona/guides/commit/07ea8457ea3e419de90d7eadad45c550d8dab3ee) ([#61](https://github.com/daytona/guides/pull/61), ready) | READY-WITH-CHANGES | PTY calls move to the v2 PTY API (`src/session.ts:67-115`) |
| `typescript/kiro/kiro-cli` | TS | READY-WITH-CHANGES (Node floor) | [feat/kiro-cli-sdk2](https://github.com/daytona/guides/tree/feat/kiro-cli-sdk2)@[`005d137`](https://github.com/daytona/guides/commit/005d13725edef672baa3e22077d198276eb9fbf1) ([#44](https://github.com/daytona/guides/pull/44), ready) | READY-WITH-CHANGES | PTY calls move to the v2 PTY API (`src/session.ts:63-94`) |
| `typescript/letta-code` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/letta-code-sdk2](https://github.com/daytona/guides/tree/feat/letta-code-sdk2)@[`e4356c1`](https://github.com/daytona/guides/commit/e4356c1ae8119d59cac12632e9ffecc52483f97c) ([#52](https://github.com/daytona/guides/pull/52), ready) | READY-WITH-CHANGES | PTY calls move to the v2 PTY API (`src/letta-session.ts:153-164`) |
| `typescript/mastra/coding-agent` | TS | READY-WITH-CHANGES (Node floor, engines, deep import) | [feat/mastra-coding-agent-sdk2](https://github.com/daytona/guides/tree/feat/mastra-coding-agent-sdk2)@[`de61b91`](https://github.com/daytona/guides/commit/de61b91dc82dd9046c6d1875d319fabfe6a5b8ae) ([#64](https://github.com/daytona/guides/pull/64), draft) | BLOCKED-BY-V2-GAP (interpreter argv) | interpreter `argv` (`src/mastra/tools/daytona/tools.ts:64,85`) |
| `typescript/omnara/managed-agents` | TS | READY-WITH-CHANGES (Node floor, engines) | [feat/omnara-managed-agents-sdk2](https://github.com/daytona/guides/tree/feat/omnara-managed-agents-sdk2)@[`b2bf2af`](https://github.com/daytona/guides/commit/b2bf2af5be7c99ba3fddb6daeee37f971aedc8b9) ([#60](https://github.com/daytona/guides/pull/60), ready) | BLOCKED-BY-REWRITE (Omnara platform) | Omnara creates the sandboxes (`src/setup.ts:46-62`) |
| `typescript/openai/codex-sdk` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/codex-sdk-sdk2](https://github.com/daytona/guides/tree/feat/codex-sdk-sdk2)@[`bb4048e`](https://github.com/daytona/guides/commit/bb4048e6b153b212fbbf38cd483f3e0de355807e) ([#51](https://github.com/daytona/guides/pull/51), ready) | BLOCKED-BY-V2-GAP (session commands) | session commands (`src/index.ts:28,31,38,46`) |
| `typescript/openclaw` | TS | READY-WITH-CHANGES (Node floor, Secret note, README samples) | [feat/openclaw-sdk2](https://github.com/daytona/guides/tree/feat/openclaw-sdk2)@[`8f4c9b5`](https://github.com/daytona/guides/commit/8f4c9b5f585cc2a4519bb03b2f1af68636c4862a) ([#53](https://github.com/daytona/guides/pull/53), ready) | BLOCKED-BY-V2-GAP (persistent Linux sandboxes) | kept Linux sandbox with auto-stop off (`src/index.ts:23,170`) |
| `typescript/opencode/opencode-sdk` | TS | READY-WITH-CHANGES (Node floor) | [feat/opencode-sdk-sdk2](https://github.com/daytona/guides/tree/feat/opencode-sdk-sdk2)@[`a6b47b5`](https://github.com/daytona/guides/commit/a6b47b53a26c22139d917b2230a431562f738078) ([#54](https://github.com/daytona/guides/pull/54), ready) | BLOCKED-BY-V2-GAP (session commands) | session commands (`src/server.ts:47,49,56`) |
| `typescript/opencode/opencode-web` | TS | READY-WITH-CHANGES (Node floor) | [feat/opencode-web-sdk2](https://github.com/daytona/guides/tree/feat/opencode-web-sdk2)@[`941ed54`](https://github.com/daytona/guides/commit/941ed5440c74a447cd599cab8de5dea05d05fcd7) ([#56](https://github.com/daytona/guides/pull/56), ready) | BLOCKED-BY-V2-GAP (session commands) | session commands (`src/index.ts:89,93,106`) |
| `typescript/vercel-ai-sdk/multi-language-benchmark-agent` | TS | READY-WITH-CHANGES (Node floor) | [feat/vercel-ai-sdk-benchmark-agent-sdk2](https://github.com/daytona/guides/tree/feat/vercel-ai-sdk-benchmark-agent-sdk2)@[`5d97aa3`](https://github.com/daytona/guides/commit/5d97aa39202c091a3dacaf85320f68b191b19325) ([#55](https://github.com/daytona/guides/pull/55), ready) | READY-WITH-CHANGES | create needs an image and region (`src/index.ts:52`) |

### Owners of the 10 guides without a branch

| guide | owner type | change it needs |
| --- | --- | --- |
| `python/ag2/bug-fixer-agent` | external project | [ag2ai/ag2](https://github.com/ag2ai/ag2): import params from `daytona.v0` and call `client.v0.create` |
| `python/reinforcement-learning/openenv` | external project | [OpenEnv](https://github.com/openenv/OpenEnv): import params from `daytona.v0`, call `.v0.create`/`.v0.delete`, bound its `daytona` extra |
| `python/computer-use/claude-draws` | Daytona integrations repo | [daytona/integrations](https://github.com/daytona/integrations) `daytona-claude-toolsets`: widen the pin, move to `daytona.v0` |
| `python/google-adk/code-generator-agent` | Daytona integrations repo | [daytona/integrations](https://github.com/daytona/integrations) `daytona-adk`: release on `daytona.v0` |
| `python/langchain/data-analysis` | Daytona integrations repo | [daytona/integrations](https://github.com/daytona/integrations) `langchain-daytona-data-analysis`: 2.x release |
| `python/pydantic-ai/coding-agent` | external project | [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) `pydantic-ai-harness`: widen `daytona<1`, use `daytona.v0` names |
| `python/reinforcement-learning/verl-retool` | external project | [verl-project/verl-recipe](https://github.com/verl-project/verl-recipe) ReTool tool: import from `daytona.v0`, stop passing `api_url` |
| `typescript/brainbase/universal-harness-api` | platform | Brainbase: moves its own sandboxes; nothing to change in this repo |
| `typescript/computer-use/claude-draws` | Daytona integrations repo | [daytona/integrations](https://github.com/daytona/integrations) `@daytona/claude-toolsets`: release on `@daytona/sdk` 2.x |
| `typescript/convex/ai-app-builder` | Daytona integrations repo | `@daytona/convex`: move its REST calls to v2 when v0 goes away; no SDK involved |

## 3. Details

Every migrated guide got the 2.x pin (`@daytona/sdk 2.0.0-alpha.13` or `daytona[v0-sdk]==2.0.0a13`) and its Daytona calls moved to `.v0` by the upgrade tool. Checks ran before and after; the result had to match (no new errors). "0.x drift" means the `v0` calls now run SDK 0.231.1 instead of the 0.x version the guide had before.

- **python/claude/claude-managed-agents** (READY-WITH-CHANGES (FIXME code fixes, README samples)). Tool moved calls to `.v0`. Forced break: a root `DAYT.get` at `orchestrator_lib.py:409` became `DAYT.v0.get`; README sample at `README.md:125` updated. Open: the bare `daytona` requirement had no 0.x floor, so the v0 version it ran before is unknown (now 0.231.1). Checks: PY-STD, smoke ITEM-CODE.
- **python/cognition/devin-outposts** (READY-WITH-CHANGES (FIXME code fixes, test fakes)). Tool moved calls to `.v0`; `orchestrator.py:411,431,611,679` and the snapshot builder fixed by hand; test fakes now wrap a `v0` mock. Base, migrated and fresh runs pass the same 60 tests. Open: direct `daytona-api-client` imports are kept (internal API client); no Windows run. Checks: PY-TESTS, smoke ITEM-CODE.
- **python/computer-use/windows-evals** (READY-WITH-CHANGES (custom API URL dropped, FIXME code fixes)). Custom API URL support removed (`common.py`, `harness.py`, `.env.example`, `README.md:36`), `client.create` -> `client.v0.create`, snapshot calls -> `.v0.snapshot`. Open: no Windows run; the smoke only builds the client and does a read-only lookup. Checks: PY-STD, smoke CLIENT-ONLY.
- **python/cursor/self-hosted-machines** (READY-WITH-CHANGES (FIXME code fixes, test fakes)). Tool moved calls to `.v0`; root `get`/`create`/`delete` and snapshot calls in five modules fixed by hand; test fakes wrap `v0`. Base, migrated and fresh runs pass the same 87 tests. Open: deprecated `DaytonaConfig.target` kept at `build_snapshot.py:230`, `monitor.py:187`, `spawn.py:319`. Checks: PY-TESTS, smoke ITEM-CODE.
- **python/dspy-rlms** (READY-WITH-CHANGES (install hint)). Only the pin and two install hints changed (`daytona_interpreter.py:235,315` now say `pip install -e .`). Open: 0.x drift from a 0.136.0 floor to 0.231.1; `demo.py` was not run. Checks: PY-STD, smoke ITEM-CODE.
- **python/gemini/gemini-managed-agents** (READY). Pin only; one tool comment removed at `provision_sandbox.py:81`. Checks pass unchanged. Open: 0.x drift 0.231.0 -> 0.231.1. Checks: PY-STD, smoke ITEM-CODE.
- **python/langgraph/plan-and-execute-data-agent** (READY-WITH-CHANGES (install line, README samples)). README install line (`README.md:48`) now pins 2.x; `README.md:77` prose uses `Daytona().v0.create()`. Open: the guide was unpinned before, so its old 0.x version is unknown. Checks: PY-STD, smoke GENERIC.
- **python/model-serving/sglang** (READY-WITH-CHANGES (README samples, Secret note)). Pin, README samples (`README.md:91-147`) and printed hints (`serve_sglang.py:119-120`) moved to `.v0`. Open: deprecated `DaytonaConfig(target=...)` kept at `serve_sglang.py:33` (emits a DeprecationWarning); the GPU script was not run. Checks: PY-STD, smoke CLIENT-ONLY.
- **python/model-serving/vllm** (READY-WITH-CHANGES (README samples, Secret note)). Pin, README samples (`README.md:83-139`) and printed hints (`serve_vllm.py:115-116`) moved to `.v0`. Open: the GPU script was not run. Checks: PY-STD, smoke CLIENT-ONLY.
- **python/openai/agents-api** (READY-WITH-CHANGES (install line)). README install line (`README.md:39`) now pins 2.x; no code change needed. Open: unpinned before, so the old 0.x version is unknown. Checks: PY-STD, smoke GENERIC.
- **python/recursive-language-models** (READY). Pin only. Checks pass unchanged. Open: 0.x drift 0.231.0 -> 0.231.1. Checks: PY-STD, smoke GENERIC.
- **python/ai-data-analyst** (READY). Pin only. Checks pass unchanged. Open: 0.x drift (floor 0.1.0, resolved 0.232.0 before) -> 0.231.1. Checks: PY-STD, smoke GENERIC.
- **python/anakin/research-agent** (READY). Pin only. Checks pass unchanged; the live smoke used the guide's own create shape. Open: 0.x drift 0.227.3 -> 0.231.1. Checks: PY-STD, smoke ITEM-CODE.
- **python/computer-use/openai-computer-use** (READY-WITH-CHANGES (install line)). README install line (`README.md:36`) moves from `daytona==0.224.1` to 2.x. Open: `main.py` was not run (needs interactive consent and the OpenAI API). Checks: PY-STD, smoke ITEM-CODE.
- **python/fireworks/coding-agent** (READY-WITH-CHANGES (README samples)). Pin and README samples (`README.md:62,72`). Open: internal import `daytona_api_client.exceptions` at `main.py:28` kept (allow-listed); 0.x drift 0.226.0 -> 0.231.1. Checks: PY-STD, smoke GENERIC.
- **python/notte/browser-testing** (READY-WITH-CHANGES (custom API URL dropped, README samples)). Custom API URL removed (`.env.example:2`, `README.md:26`); `README.md:64` uses `Daytona().v0.create()`. Open: the Notte client was never constructed. Checks: PY-STD, smoke ITEM-CODE.
- **python/reinforcement-learning/trl** (READY-WITH-CHANGES (private import)). Forced break: private import `daytona.v0.common.errors` merged into `from daytona.v0 import AsyncSandbox, DaytonaTimeoutError` (`train.py:14`). Open: training `main()` was not run (500 sandboxes plus GPU). Checks: PY-STD, smoke ITEM-CODE.
- **typescript/agentkit-inngest/coding-agent** (READY-WITH-CHANGES (Node floor, deep import)). Forced break: deep import `@daytona/sdk/src/FileSystem.js` -> `@daytona/sdk/v0` (`src/index.ts:12`); README Node floor 18 -> 22.15. Open: `Dockerfile:1` is still `node:20-alpine` (below the 2.x floor). Checks: TS-STD, smoke ITEM-CODE.
- **typescript/ai-data-analyst** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:18`). Open: 0.x drift 0.163.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/amp/amp-sdk** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README Node floor and Secret samples (`README.md:7,84,99,112`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/anchor/cloud-browser** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:20`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/anthropic/multi-agent-claude-sdk** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README Node floor and Secret samples (`README.md:25,115,130,143`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/anthropic/single-claude-agent-sdk** (READY-WITH-CHANGES (Node floor, internal types, Secret note, README samples)). Forced break: internal `@daytona/toolbox-api-client` type import replaced with local type aliases (`src/index.ts:15-16`); README floor and Secret samples. Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/cognition/devin-cli** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:15`). Open: 0.x drift 0.187.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/copilotkit/generative-ui-coding-agent** (READY-WITH-CHANGES (Node floor, README samples)). Tool moved 11 calls in `route.ts` to `.v0`; README floor and table (`README.md:9,57`). `next build` passes. Open: 0.x drift 0.184.0 -> 0.231.1. Checks: TS-BUILD (`next build`), smoke GENERIC.
- **typescript/flue** (READY-WITH-CHANGES (Node floor, engines, Secret note, README samples)). Pin, `engines.node` `>=22` -> `>=22.15.0`, README floor and Secret samples, JSDoc at `.flue/connectors/daytona.ts:18`. Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke ITEM-CODE.
- **typescript/gemini/gemini-cli** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README floor and Secret samples (`README.md:14,49,64,77`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/kimi/kimi-cli** (READY-WITH-CHANGES (Node floor, Secret note, README samples, lock drift)). Pin, README floor and Secret samples; `package-lock.json` regenerated. The base lock was already out of sync (0.187.0 locked vs `^0.201.0`), so `npm ci` failed at base. Open: 0.x drift -> 0.231.1. Checks: TS-STD + lock, smoke GENERIC.
- **typescript/kiro/kiro-cli** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:15`). Open: 0.x drift 0.187.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/letta-code** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README floor and Secret samples (`README.md:18,59,74,87`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/mastra/coding-agent** (READY-WITH-CHANGES (Node floor, engines, deep import)). Forced break: deep import -> `import type { FileUpload } from '@daytona/sdk/v0'` (`utils.ts:8`); `engines.node` -> `>=22.15.0`; pnpm lock regenerated; `mastra build` passes. Open: pnpm cannot freeze resolution to a date (16 of 80 new lock entries are newer than the freeze). Checks: TS-BUILD (`mastra build`) + lock, smoke ITEM-CODE.
- **typescript/omnara/managed-agents** (READY-WITH-CHANGES (Node floor, engines)). Pin, README floor (`README.md:21`) and `engines.node` `>=22` -> `>=22.15.0`; `package-lock.json` regenerated (about 1300 lines of transitive bumps). Open: 0.x drift 0.224.1 -> 0.231.1. Checks: TS-STD + lock, smoke CLIENT-ONLY.
- **typescript/openai/codex-sdk** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README floor and Secret samples (`README.md:17,57,72,85`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/openclaw** (READY-WITH-CHANGES (Node floor, Secret note, README samples)). Pin, README floor and Secret samples (`README.md:16,66,82,95`). Open: 0.x drift 0.201.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/opencode/opencode-sdk** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:15`). Open: 0.x drift 0.163.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/opencode/opencode-web** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:16`). Open: 0.x drift 0.163.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.
- **typescript/vercel-ai-sdk/multi-language-benchmark-agent** (READY-WITH-CHANGES (Node floor)). Pin and README Node floor (`README.md:17`). Open: 0.x drift 0.163.0 -> 0.231.1. Checks: TS-STD, smoke GENERIC.

Check profiles: PY-STD = compile, name resolution against the installed SDK, module import, Pyright, `uv pip check`, floor resolve; PY-TESTS adds the guide's pytest suite. TS-STD = `tsc --noEmit`, import probe of every `@daytona/*` specifier, exactly one `@daytona/sdk` version installed; TS-BUILD adds the guide's build; lock = `npm ci` / pnpm frozen install from the regenerated lockfile.

## 4. Who is excluded

- Custom API URL, all 37 branches: SDK 2.x ignores `DAYTONA_API_URL` (it warns and uses the default). Users who need a custom endpoint should stay on SDK 0.x. Two guides documented the variable and now say so (`windows-evals`, `notte-browser-testing`).
- Node.js >= 22.15.0, all 20 TypeScript branches: SDK 2.x needs it, so each README floor (and `engines.node` in flue, mastra and omnara) was raised. `typescript/agentkit-inngest/coding-agent/Dockerfile:1` still uses `node:20-alpine` and is flagged, not changed.
- Python >= 3.10, unchanged for all 17 Python branches.

## 5. Guides without a branch

Wrapper-blocked (measured 2026-11-23 against `daytona` 2.0.0a13 / `@daytona/sdk` 2.0.0-alpha.13). The guide's own code is fine; the library it installs is not, and only its owner can fix it. Daytona integrations packages are being migrated upstream, so nothing changes in this repo now.

- `python/computer-use/claude-draws`: the resolver can't install `daytona-claude-toolsets` 0.1.1 with SDK 2.x; it requires `daytona>=0.223.0,<0.224.0` ([pyproject.toml:41](https://github.com/daytona/integrations/blob/ada17ac756598395f8f850b7d42492b6bf7f511f/packages/claude-toolsets/python/pyproject.toml#L41)). Stays on 0.223.x meanwhile.
- `typescript/computer-use/claude-draws`: the tool applies, but npm nests a second `@daytona/sdk` 0.223.1 under `@daytona/claude-toolsets` 1.0.0 ([package.json:57](https://github.com/daytona/integrations/blob/ada17ac756598395f8f850b7d42492b6bf7f511f/packages/claude-toolsets/typescript/package.json#L57)) and `tsc` fails with TS2379 at `src/draw.ts:171,172,196`.
- `python/google-adk/code-generator-agent`: `daytona-adk` 0.2.0 pins `daytona<0.195.0` ([pyproject.toml:28](https://github.com/daytona/integrations/blob/ada17ac756598395f8f850b7d42492b6bf7f511f/packages/adk-plugin/pyproject.toml#L28)), so the resolver falls back to 0.1.0, whose import fails on `CreateSandboxBaseParams` ([plugin.py:16](https://github.com/daytona/integrations/blob/ada17ac756598395f8f850b7d42492b6bf7f511f/packages/adk-plugin/daytona_adk/plugin.py#L16)).
- `python/langchain/data-analysis`: every `langchain-daytona-data-analysis` version caps `daytona<1.0.0` ([pyproject.toml:24](https://github.com/daytona/integrations/blob/ada17ac756598395f8f850b7d42492b6bf7f511f/packages/langchain-data-analysis/pyproject.toml#L24)); resolver exit 1.
- `python/ag2/bug-fixer-agent` (ag2 0.14.0): `DaytonaCodeExecutor` imports `CreateSandboxFromImageParams` from the SDK root ([daytona_code_executor.py:28-38](https://github.com/ag2ai/ag2/blob/aa11de3c0c7bb615fb98eae6bea731ab1bb47e03/autogen/coding/daytona_code_executor.py#L28-L38)); 2.x no longer exports it there, so it raises a misleading `pip install ag2[daytona]` error. The pin PR keeps the guide on 0.x until ag2 is fixed.
- `python/pydantic-ai/coding-agent`: `pydantic-ai-harness` caps `daytona<1` ([pyproject.toml:80](https://github.com/pydantic/pydantic-ai/blob/541bd91c2da3c8ed4dec980dce527ff0501590a3/src/pydantic_ai_harness/pyproject.toml#L80)); forcing 2.x falls back to a harness without the Daytona module, and 0.68.0 fails on `daytona.SandboxState` at first use ([_backend.py:147](https://github.com/pydantic/pydantic-ai/blob/541bd91c2da3c8ed4dec980dce527ff0501590a3/src/pydantic_ai_harness/pydantic_ai_harness/daytona_sandbox/_backend.py#L147)).
- `python/reinforcement-learning/openenv`: `DaytonaProvider` imports `CreateSandboxFromSnapshotParams` from the root ([daytona_provider.py:381](https://github.com/openenv/OpenEnv/blob/24427e41df828d189cf6f9a3f0e177d2a1b6164d/src/openenv/core/containers/runtime/daytona_provider.py#L381)) and fails before any create; its `daytona` extra has no upper bound ([pyproject.toml:43-44](https://github.com/openenv/OpenEnv/blob/24427e41df828d189cf6f9a3f0e177d2a1b6164d/pyproject.toml#L43-L44)). The pin PR keeps the guide on 0.x.
- `python/reinforcement-learning/verl-retool`: the ReTool tool imports `CreateSandboxFromSnapshotParams` from the root ([daytona_sandbox_tool.py:50](https://github.com/verl-project/verl-recipe/blob/98de2b9b33bc3ed5ffce1e0eb7c70d2e270b3512/retool/daytona_sandbox_tool.py#L50)) and passes `api_url` to `DaytonaConfig` ([:104-111](https://github.com/verl-project/verl-recipe/blob/98de2b9b33bc3ed5ffce1e0eb7c70d2e270b3512/retool/daytona_sandbox_tool.py#L104-L111)), which 2.x rejects with a TypeError.

No SDK calls (call maps read at base). The SDK change doesn't touch them; they keep working while the v0 platform exists.

- `typescript/brainbase/universal-harness-api`: 0 Daytona SDK calls. Six Brainbase API calls go through one `fetch` (`src/client.ts:119`, stream at `:176`); `machine_kind: 'daytona'` (`src/config.ts:70`) only picks Brainbase's provider. Brainbase owns the move.
- `typescript/convex/ai-app-builder`: 0 Daytona SDK calls. `@daytona/convex` 1.0.0 sends 13 v0 REST calls through a single `fetch` (`dist/component/daytona.js:60`). The integrations repo owns the move.
- Non-SDK calls inside migrated guides, unchanged: `daytona mcp start` in `python/computer-use/windows-evals/harness.py:399-400,503-504` (base), and the preview-token `curl` in `python/model-serving/sglang/query.sh:10-11` and `python/model-serving/vllm/query.sh:9-10`.

## 6. GA flip runbook

Readiness rule: a stable 2.x counts when the same version is on npm and PyPI, npm `latest` points at it, and it is neither deprecated on npm nor yanked on PyPI. On 2026-11-23 stable 2.1.0 meets this rule, so the flip can happen now. The stable build itself was not tested in this run.

Steps, per branch:

1. Confirm the rule above still holds on both registries.
2. Bring the branch up to date with `main`. Rebasing needs a force-push of that branch; merging `main` into it avoids that, and the DCO check skips merge commits. Either way the SHAs in this report go stale.
3. Conflicts are expected on 11 PRs today: the pin PR (#43) merged after this run's base and touched the same `pyproject.toml` or README line in 11 guides (claude-managed-agents, devin-outposts, windows-evals, cursor-self-hosted-machines, dspy-rlms, gemini-managed-agents, langgraph-plan-and-execute-data-agent, sglang, vllm, openai-agents-api, recursive-language-models). Resolve each by keeping the branch's 2.x pin line and dropping the `<1.0.0` line.
4. Flip the pin at every site in the table below to `^2.0.0` (TS) or `daytona[v0-sdk]>=2,<3` (PY), README lines included.
5. Regenerate the lockfile where one exists, then run the check profile.
6. Mark any remaining draft PRs ready for review.

When the integrations packages ship their 2.x releases, run the same procedure for the 4 integrations-blocked guides (both claude-draws guides, google-adk, langchain).

| branch | pin sites | GA pin | lock command | check profile |
| --- | --- | --- | --- | --- |
| `feat/claude-managed-agents-sdk2` | `pyproject.toml:8` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/devin-outposts-sdk2` | `pyproject.toml:12`, `README.md:13` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-TESTS |
| `feat/windows-evals-sdk2` | `pyproject.toml:7` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/cursor-self-hosted-machines-sdk2` | `pyproject.toml:12`, `README.md:69` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-TESTS |
| `feat/dspy-rlms-sdk2` | `pyproject.toml:9` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/gemini-managed-agents-sdk2` | `pyproject.toml:7` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/langgraph-plan-and-execute-data-agent-sdk2` | `README.md:48` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/sglang-sdk2` | `pyproject.toml:15` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/vllm-sdk2` | `pyproject.toml:11` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/openai-agents-api-sdk2` | `README.md:39` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/recursive-language-models-sdk2` | `pyproject.toml:9` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/py-ai-data-analyst-sdk2` | `pyproject.toml:16` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/anakin-research-agent-sdk2` | `pyproject.toml:13` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/openai-computer-use-sdk2` | `README.md:36` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/fireworks-coding-agent-sdk2` | `pyproject.toml:15` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/notte-browser-testing-sdk2` | `pyproject.toml:8` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/trl-sdk2` | `pyproject.toml:11` | `daytona[v0-sdk]>=2,<3` | none (no lockfile) | PY-STD |
| `feat/agentkit-inngest-coding-agent-sdk2` | `package.json:16` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/ts-ai-data-analyst-sdk2` | `package.json:16` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/amp-sdk-sdk2` | `package.json:22` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/anchor-cloud-browser-sdk2` | `package.json:20` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/multi-agent-claude-sdk-sdk2` | `package.json:21` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/single-claude-agent-sdk-sdk2` | `package.json:20` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/devin-cli-sdk2` | `package.json:22` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/copilotkit-generative-ui-coding-agent-sdk2` | `package.json:25` | `^2.0.0` | none (no lockfile) | TS-BUILD (`next build`) |
| `feat/flue-sdk2` | `package.json:27` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/gemini-cli-sdk2` | `package.json:22` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/kimi-cli-sdk2` | `package.json:22`, `package-lock.json (root spec + node_modules/@daytona/sdk version)` | `^2.0.0` | `npm install --ignore-scripts`, then `npm ci --ignore-scripts` | TS-STD + lock |
| `feat/kiro-cli-sdk2` | `package.json:22` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/letta-code-sdk2` | `package.json:20` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/mastra-coding-agent-sdk2` | `package.json:21`, `pnpm-lock.yaml:12-13 (importer specifier + version)`, `pnpm-lock.yaml:342,3554 (package entries)` | `^2.0.0` | `npx -y pnpm@10.29.3 install --no-frozen-lockfile --ignore-scripts`, then `--frozen-lockfile` | TS-BUILD (`mastra build`) + lock |
| `feat/omnara-managed-agents-sdk2` | `package.json:28`, `package-lock.json:12`, `package-lock.json:372`, `package-lock.json:373` | `^2.0.0` | `npm install --ignore-scripts`, then `npm ci --ignore-scripts` | TS-STD + lock |
| `feat/codex-sdk-sdk2` | `package.json:20` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/openclaw-sdk2` | `package.json:12` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/opencode-sdk-sdk2` | `package.json:21` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/opencode-web-sdk2` | `package.json:20` | `^2.0.0` | none (no lockfile) | TS-STD |
| `feat/vercel-ai-sdk-benchmark-agent-sdk2` | `package.json:24` | `^2.0.0` | none (no lockfile) | TS-STD |

### Reproduce a branch from scratch

Environment for every command (the freeze time keeps npm and uv on the same packages this run saw):

```sh
git clone https://github.com/daytona/guides && cd guides
git checkout 625cdfebb95193fa8bf0da2cd9e3358059b1307b
export T_FREEZE=2026-11-16T15:48:44Z
export CI=true npm_config_yes=true npm_config_before="$T_FREEZE" npm_config_audit=false npm_config_fund=false UV_EXCLUDE_NEWER="$T_FREEZE"
unset DAYTONA_API_URL DAYTONA_TARGET DAYTONA_V0_API_URL DAYTONA_V2_API_URL DAYTONA_JWT_TOKEN DAYTONA_ORGANIZATION_ID DAYTONA_API_KEY
cd <guide dir>
```

TypeScript with a `package-lock.json` (kimi-cli, omnara-managed-agents):

```sh
npm ci --ignore-scripts
npx -y @daytona/upgrade@2.0.0-alpha.13 . --yes
# apply the manual edits listed below for this branch
rm -r node_modules
npm install --ignore-scripts
npm ci --ignore-scripts
```

TypeScript without a lockfile: `npm install --no-package-lock --ignore-scripts`, then the tool, then the edits. mastra: `npx -y pnpm@10.29.3 install --frozen-lockfile --ignore-scripts`, the tool, the edits, then `npx -y pnpm@10.29.3 install --no-frozen-lockfile --ignore-scripts` (pnpm ignores the freeze date). Python: `uvx --from daytona-upgrade==2.0.0a13 daytona-upgrade . --yes`, then the edits; README-only guides get the pin by hand. windows-evals also needs `--drop-api-url` (the tool refuses without it). Compare the result with the branch, ignoring `node_modules`.

Manual edits per branch (path:line before → after):

- `feat/claude-managed-agents-sdk2`:
  - orchestrator_lib.py:409 (tool numbering; plan :408) R1: '# FIXME(daytona-upgrade) ...' + 'sb = DAYT.get(sandbox_id)' → 'sb = DAYT.v0.get(sandbox_id)' (DAYT = Daytona() at :31)
  - README.md:125 D1: 'sb = dayt.get("byoc-sess_01...")' → 'sb = dayt.v0.get("byoc-sess_01...")'
- `feat/devin-outposts-sdk2`:
  - devin_outposts/build_windows_snapshot.py:396-399 resolve Daytona.v0 inside the existing try and pass the compatibility client to snapshot lookup.
  - devin_outposts/orchestrator.py:411,431,611,679 move root get/create/list to .v0.
  - devin_outposts/sandbox.py:20 retain the tool-migrated dead fallback as specified.
  - tests/test_builder_review.py:19-20 strict root Mock; configure and assert on the inner v0 mock.
  - tests/test_windows_snapshot_review.py:233-235; tests/test_orchestrator.py:99,171; tests/test_lifecycle_review.py:132,242 R5: strict root facades wrap existing inner fakes.
  - tests/test_orchestrator.py:109-111: exercise existing sandbox lookup before supervision without changing the test ID or suspension assertions.
  - README.md:13: document the exact SDK pin and compatibility namespace.
- `feat/windows-evals-sdk2`:
  - common.py:36-46 (base): remove DaytonaConfig import and replace the custom URL branch with return Daytona().
  - common.py:56 (base): client.create → client.v0.create.
  - prep_snapshot.py:231,245: client.snapshot.get/list → client.v0.snapshot.get/list.
  - harness.py:389-390,499-500 (base): drop legacy URL forwarding in the Claude and Codex MCP configurations.
  - .env.example:7-8 (base): remove the custom URL example.
  - README.md:36: replace the URL variable entry with the SDK 0.x note.
- `feat/cursor-self-hosted-machines-sdk2`:
  - build_linux_vm_snapshot.py:63,217,296 daytona.snapshot.&lt;method&gt; to daytona.v0.snapshot.&lt;method&gt;; :180,201,248 R1: root delete/create to .v0.
  - build_snapshot.py:99 daytona.snapshot.list to daytona.v0.snapshot.list; :230-232 R4: initialize .v0 inside the existing try.
  - build_windows_snapshot.py:76,283,346 daytona.snapshot.&lt;method&gt; to daytona.v0.snapshot.&lt;method&gt;; :240,262,324 R1: root delete/create to .v0.
  - monitor.py:141 daytona.get to daytona.v0.get; :184-191 R4: initialize .v0 inside the existing try.
  - spawn.py:179 daytona.snapshot.get to daytona.v0.snapshot.get; :187,201,211 R1: root get/create to .v0; :316-323 R4: initialize .v0 inside the existing try.
  - tests/test_snapshot.py:160,186,204,226,253,299,364; tests/test_spawn.py:280,504,662,710,757; tests/test_monitor.py:118; tests/test_linux_vm_snapshot.py:133,188,225,266; tests/test_windows_snapshot.py:141,198,262,306: R5 wrap each fake root with SimpleNamespace(v0=fake) and preserve assertions.
  - README.md:69: document SDK pin and compatibility namespace.
- `feat/dspy-rlms-sdk2`:
  - daytona_interpreter.py:235 '        - Daytona SDK: pip install daytona' → '        - Daytona SDK: pip install -e . (from this guide's directory)'
  - daytona_interpreter.py:315 (base :314) '"Daytona not installed. Install with: pip install daytona\n"' → '"Daytona not installed. Install with: pip install -e . (from this guide's directory)\n"'
- `feat/gemini-managed-agents-sdk2`:
  - provision_sandbox.py:81 (tool numbering) delete R2 FIXME comment on dict .get, logic unchanged
- `feat/langgraph-plan-and-execute-data-agent-sdk2`:
  - README.md:48 pip install line: daytona → "daytona[v0-sdk]==2.0.0a13"
  - README.md:77 prose: Daytona().create() → Daytona().v0.create()
- `feat/sglang-sdk2`:
  - README.md:91 'Daytona(DaytonaConfig(target="us-east-1")).get("SANDBOX_ID")' → '...).v0.get("SANDBOX_ID")'
  - README.md:112 'Daytona().get(' → 'Daytona().v0.get('
  - README.md:121 'needs `daytona` 0.192.0 or newer and a one-time Secret setup' → 'uses `daytona.v0` from the `daytona` version this guide pins and a one-time Secret setup'
  - README.md:130 'from daytona import CreateSecretParams, Daytona' → 'from daytona import Daytona' + 'from daytona.v0 import CreateSecretParams'
  - README.md:135 'daytona.secret.create(' → 'daytona.v0.secret.create('
  - README.md:147 diff context 'sb = daytona.create(' → 'sb = daytona.v0.create('
  - serve_sglang.py:119-120 printed hints 'daytona.get(' → 'daytona.v0.get('
- `feat/vllm-sdk2`:
  - README.md:83 Daytona().get( → Daytona().v0.get(
  - README.md:104 Daytona().get( → Daytona().v0.get(
  - README.md:113 'needs `daytona` 0.192.0 or newer and' → 'uses `daytona.v0` from the `daytona` version this guide pins and'
  - README.md:122 from daytona import CreateSecretParams, Daytona → from daytona import Daytona + from daytona.v0 import CreateSecretParams
  - README.md:127 daytona.secret.create( → daytona.v0.secret.create(
  - README.md:139 diff-block context daytona.create( → daytona.v0.create(
  - serve_vllm.py:115-116 printed hints daytona.get( → daytona.v0.get(
- `feat/openai-agents-api-sdk2`:
  - python/openai/agents-api/README.md:39: pip install openai daytona python-dotenv → pip install openai "daytona[v0-sdk]==2.0.0a13" python-dotenv
- `feat/recursive-language-models-sdk2`: none.
- `feat/py-ai-data-analyst-sdk2`: none.
- `feat/anakin-research-agent-sdk2`: none.
- `feat/openai-computer-use-sdk2`:
  - python/computer-use/openai-computer-use/README.md:36: "daytona==0.224.1" → "daytona[v0-sdk]==2.0.0a13"
- `feat/fireworks-coding-agent-sdk2`:
  - README.md:62 daytona.secret.create( → daytona.v0.secret.create(
  - README.md:72 daytona.create( → daytona.v0.create(
- `feat/notte-browser-testing-sdk2`:
  - .env.example:2 DAYTONA_API_URL=https://app.daytona.io/api → line deleted
  - README.md:26 - `DAYTONA_API_URL`: The Daytona API endpoint ... → - custom API URL: stay on SDK 0.x
  - README.md:64 `Daytona().create()` → `Daytona().v0.create()`
- `feat/trl-sdk2`:
  - train.py:14-15 (tool output) R6: 'from daytona.v0 import AsyncSandbox' + 'from daytona.v0.common.errors import DaytonaTimeoutError' → train.py:14 'from daytona.v0 import AsyncSandbox, DaytonaTimeoutError' (private line deleted; rg 'daytona(\.v0)?\.common' → no lines)
- `feat/agentkit-inngest-coding-agent-sdk2`:
  - src/index.ts:12: import type { FileUpload } from '@daytona/sdk/src/FileSystem.js' → import type { FileUpload } from '@daytona/sdk/v0'
  - README.md:19: Version 18 or higher → Version 22.15 or higher
- `feat/ts-ai-data-analyst-sdk2`:
  - README.md:18: Version 18 or higher → Version 22.15 or higher
- `feat/amp-sdk-sdk2`:
  - README.md:7: Node.js 18 or newer → Node.js 22.15 or newer
  - README.md:84: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:99: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:112: daytona.create( → daytona.v0.create(
- `feat/anchor-cloud-browser-sdk2`:
  - README.md:20: Version 18 or higher → Version 22.15 or higher
- `feat/multi-agent-claude-sdk-sdk2`:
  - README.md:25: Version 18 or higher → Version 22.15 or higher
  - README.md:115: needs `@daytona/sdk` 0.192.0 or newer → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:130: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:143: daytona.create( → daytona.v0.create(
- `feat/single-claude-agent-sdk-sdk2`:
  - src/index.ts:8 (base :7): delete import { InterpreterContext, ExecuteResponse } from '@daytona/toolbox-api-client' (internal types)
  - src/index.ts:15-16: add type InterpreterContext = Awaited&lt;ReturnType&lt;Sandbox['codeInterpreter']['createContext']&gt;&gt; and type ExecuteResponse = Awaited&lt;ReturnType&lt;Sandbox['process']['executeCommand']&gt;&gt; after the imports; existing uses (:19, :84) unchanged
  - README.md:17: Node.js Version 18 or higher → Version 22.15 or higher
  - README.md:57: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:72: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:85: daytona.create( → daytona.v0.create(
- `feat/devin-cli-sdk2`:
  - README.md:15: Node.js 18 or newer → Node.js 22.15 or newer
- `feat/copilotkit-generative-ui-coding-agent-sdk2`:
  - README.md:9: **Node.js 20 or newer** → **Node.js 22.15 or newer**
  - README.md:57: tool table cell daytona.create({ public: true, ephemeral: true, ... }) → daytona.v0.create({ public: true, ephemeral: true, ... })
- `feat/flue-sdk2`:
  - package.json:24: engines.node &gt;=22 → &gt;=22.15.0
  - README.md:27: Node.js 22+ → Node.js 22.15+
  - README.md:226: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:240: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:253: diff context client.create( → client.v0.create(
  - .flue/connectors/daytona.ts:18: JSDoc client.create( → client.v0.create(
- `feat/gemini-cli-sdk2`:
  - README.md:14: Node.js 20 or newer → Node.js 22.15 or newer
  - README.md:49: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:64: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:77: daytona.create( → daytona.v0.create(
- `feat/kimi-cli-sdk2`:
  - README.md:15: Node.js 18 or newer → Node.js 22.15 or newer
  - README.md:54: Secret sentence 'needs `@daytona/sdk` 0.192.0 or newer' → 'uses `daytona.v0` from the `@daytona/sdk` version this guide pins'
  - README.md:69: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:82: daytona.create( → daytona.v0.create(
  - package-lock.json: regenerated by npm install (lock drift at base: 0.187.0 locked vs ^0.201.0 required)
- `feat/kiro-cli-sdk2`:
  - README.md:15: Node.js 18 or newer → Node.js 22.15 or newer
- `feat/letta-code-sdk2`:
  - README.md:18: Node.js Version 18 → 22.15
  - README.md:59: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:74: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:87: daytona.create( → daytona.v0.create(
- `feat/mastra-coding-agent-sdk2`:
  - src/mastra/tools/daytona/utils.ts:8: import { FileUpload } from '@daytona/sdk/src/FileSystem' → import type { FileUpload } from '@daytona/sdk/v0'
  - README.md:21: Node.js 20 or higher → Node.js 22.15 or higher
  - package.json:18: engines.node &gt;=22.13.0 → &gt;=22.15.0
  - pnpm-lock.yaml: regenerated by pnpm install --no-frozen-lockfile (new pin)
- `feat/omnara-managed-agents-sdk2`:
  - README.md:21: - **Node.js:** Version 22 or higher is required. → - **Node.js:** Version 22.15 or higher is required.
  - package.json:25: "node": "&gt;=22" → "node": "&gt;=22.15.0" (inside "engines": { ... } at lines 24-26, 4-space indent, no other change; edited before lock regeneration so package-lock.json packages[""].engines.node (package-lock.json:22) becomes "&gt;=22.15.0" via npm install)
- `feat/codex-sdk-sdk2`:
  - README.md:17: Node.js 18 or higher → Node.js 22.15 or higher
  - README.md:57: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:72: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:85: daytona.create( → daytona.v0.create(
- `feat/openclaw-sdk2`:
  - README.md:16: Node.js Version 18 → 22.15
  - README.md:66: Secret sentence → uses `daytona.v0` from the `@daytona/sdk` version this guide pins
  - README.md:82: daytona.secret.create( → daytona.v0.secret.create(
  - README.md:95: daytona.create( → daytona.v0.create(
- `feat/opencode-sdk-sdk2`:
  - README.md:15: Node.js Version 18 or higher → Version 22.15 or higher
- `feat/opencode-web-sdk2`:
  - README.md:16: Node.js Version 18 → 22.15
- `feat/vercel-ai-sdk-benchmark-agent-sdk2`:
  - README.md:17: Version 18 or higher → Version 22.15 or higher

### Release and follow-ups

- Release automation: none. Only the CLA and DCO checks run, on pull requests. Keep the `!` in PR titles if squash-merging, so the breaking change stays visible.
- Outside the branches: root `README.md:10` still says Node.js 18+ as the baseline; `.github/ISSUE_TEMPLATE/bug_report.md:33-34` gives 0.x and Node 20 as examples; the docs-site walkthroughs for these guides need the same `.v0` and Node floor changes; the wrapper owners in section 5.

## 7. Live runs and cleanup

- 33 guides ran a live smoke (21 GENERIC, 12 ITEM-CODE); 4 were CLIENT-ONLY (client built, read-only lookup, no sandbox); 10 had no branch and no smoke.
- Sandboxes: 38 created, 38 deleted, 38 confirmed gone by direct lookup. The 5 beyond one per guide were two extra runs on kiro-cli and three on trl while investigating the listing gap below.
- Sweep for leftover tagged sandboxes: 0 before the run and 0 at 2026-11-23T17:00Z. The sweep relies on listing, so with the gap below the per-sandbox direct lookup is the real cleanup proof.
- Positive control: each smoke checked that its own sandbox showed up in a label-filtered list. From about 16:50Z on 2026-11-23 the platform list stopped returning running sandboxes, so trl and cursor-self-hosted-machines record this check as not applicable; direct lookup confirmed the sandbox and its labels, and cleanup was verified the same way. This is a platform listing gap, not a migration defect.
- GENERIC = a standard create/run/delete through the guide's client setup; ITEM-CODE = the guide's own helper code drives the sandbox. The class per guide is in section 3.

## 8. Risks and unverified

- Session-command v2 verdicts (10 guides) rest on one measurement: the deployed daemon returned HTTP 422 on 2026-11-02 on an earlier alpha. Not re-measured.
- The stable build is untested. 2.0.0 was withdrawn at the freeze; stable 2.1.0 went live on 2026-11-20. The flip in section 6 still needs its checks run on the stable version.
- 0.x drift: every guide's `v0` calls now run SDK 0.231.1. No regressions were found, but guides with old floors (0.128.x to 0.187.x) jump the furthest.
- The pnpm lock (mastra) isn't time-frozen: 16 of 80 new entries were published after the freeze.
- GENERIC smokes exercise the client and a sandbox, not all of the guide's own code.
- Deprecated `DaytonaConfig.target` is still used in cursor-self-hosted-machines and sglang.
- Internal API-client imports remain: `daytona_api_client` in devin-outposts and fireworks-coding-agent.
