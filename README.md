# Daytona Guides

Runnable, self-contained examples showing how to build AI agents, data analysts, model-serving endpoints, and reinforcement-learning workflows on [Daytona](https://www.daytona.io) sandboxes.

Each guide lives in its own folder with its own README, dependencies, and `.env.example`. Most guides also have a step-by-step walkthrough in the [Daytona docs](https://www.daytona.io/docs/en/guides).

## Prerequisites

- A **Daytona account** and **API key** — create one in the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- The runtime the guide uses — **Python** or **Node.js**. Minimum versions vary by guide (baseline Python 3.10+ / Node.js 18+, though some need newer, e.g. Python 3.12 or Node.js 22), so check the guide's own README.
- Any provider API keys a given guide needs (OpenAI, Anthropic, Gemini, etc.) — see that guide's README.

## Getting started

```bash
git clone https://github.com/daytona/guides.git
cd guides/<path-to-guide>      # e.g. typescript/openai/codex-sdk

cp .env.example .env           # then fill in your keys
```

Then follow the guide's own README to install dependencies and run it.

## Python guides

| Guide | Description |
| --- | --- |
| [AG2 Bug Fixer](python/ag2/bug-fixer-agent/openai) | Two AG2 agents that iteratively fix broken code, running each attempt in a sandbox. |
| [Data Analyst (LiteLLM)](python/ai-data-analyst/litellm) | Natural-language data analysis with LiteLLM, executing Python in a sandbox. |
| [Data Analyst (OpenAI)](python/ai-data-analyst/openai) | Natural-language data analysis with the OpenAI API, executing Python in a sandbox. |
| [Claude Managed Agents](python/claude/claude-managed-agents) | Self-host Claude Managed Agents inside Daytona sandboxes. |
| [Windows Computer-Use Evals](python/computer-use/windows-evals) | Windows GUI computer-use eval suite driven by Claude Code / Codex via MCP. |
| [DSPy RLMs](python/dspy-rlms) | Run DSPy's Recursive Language Model (REPL-in-a-loop) module on Daytona. |
| [Google ADK Code Generator](python/google-adk/code-generator-agent/gemini) | Google ADK agent that generates and verifies code with the Daytona plugin. |
| [LangChain Data Analysis](python/langchain/data-analysis/anthropic) | LangChain agent doing secure data analysis via the Daytona data-analysis tool. |
| [LangGraph Plan-and-Execute](python/langgraph/plan-and-execute-data-agent) | Plan-and-execute ETL + analytical-SQL agent wired as a six-node state machine. |
| [Model Serving (SGLang)](python/model-serving/sglang) | Serve gpt-oss-20b with SGLang on a GPU sandbox behind a preview URL. |
| [Model Serving (vLLM)](python/model-serving/vllm) | Serve an open-weights model with vLLM on a GPU sandbox behind a preview URL. |
| [Recursive Language Models](python/recursive-language-models) | Recursive-LM agents that spawn sub-agents, each in its own sandbox. |
| [OpenEnv (FinQA)](python/reinforcement-learning/openenv) | Evaluate and train models on FinQA with OpenEnv and Daytona sandboxes. |
| [TRL RL Rollouts](python/reinforcement-learning/trl) | Run TRL RL rollouts, executing generated code in parallel sandboxes. |
| [veRL ReTool Benchmark](python/reinforcement-learning/verl-retool) | Benchmark script for veRL's ReTool sandbox execution backend. |

## TypeScript guides

| Guide | Description |
| --- | --- |
| [Inngest AgentKit Coding Agent](typescript/agentkit-inngest/coding-agent/anthropic) | Autonomous coding agent built with Inngest AgentKit. |
| [Data Analyst (OpenAI)](typescript/ai-data-analyst/openai) | Natural-language data analysis with the OpenAI API, executing code in a sandbox. |
| [Amp Code Coding Agent](typescript/amp/amp-sdk) | Coding agent powered by the Amp Code CLI. |
| [Claude Two-Agent System](typescript/anthropic/multi-agent-claude-sdk) | Two-agent Claude system coordinating work across sandboxes. |
| [Claude Coding Agent](typescript/anthropic/single-claude-agent-sdk) | Single Claude Code agent you drive from the CLI. |
| [Devin CLI Coding Agent](typescript/cognition/devin-cli) | Coding agent powered by Cognition's Devin CLI. |
| [CopilotKit Generative-UI Agent](typescript/copilotkit/generative-ui-coding-agent) | CopilotKit agent that streams every tool call as generative UI. |
| [Flue Bug-Fix Agent](typescript/flue) | Autonomous GitHub-issue bug-fix agent built with Flue. |
| [Gemini CLI Coding Agent](typescript/gemini/gemini-cli) | Headless coding agent powered by the Gemini CLI. |
| [Kiro CLI Coding Agent](typescript/kiro/kiro-cli) | Coding agent powered by AWS Kiro's CLI. |
| [Letta Code Agent](typescript/letta-code) | Letta Code agent driven from the CLI. |
| [Mastra Code Execution Agent](typescript/mastra/coding-agent/openai) | Mastra agent that plans, writes, executes, and iterates on code. |
| [OpenAI Codex Agent](typescript/openai/codex-sdk) | OpenAI Codex agent driven from the CLI. |
| [OpenClaw Assistant](typescript/openclaw) | OpenClaw general-purpose AI assistant with a web Control UI. |
| [OpenCode Server](typescript/opencode/opencode-sdk) | OpenCode coding-agent server driven from the CLI. |
| [OpenCode Web](typescript/opencode/opencode-web) | OpenCode agent with a web interface. |
| [Vercel AI SDK Benchmark Agent](typescript/vercel-ai-sdk/multi-language-benchmark-agent) | Vercel AI SDK agent that benchmarks Python vs TypeScript and plots the results. |

## Contributing

Each guide is self-contained — keep changes scoped to a single guide's folder, include a clear README, and provide a `.env.example` for any required keys. Every commit needs a [DCO](https://developercertificate.org/) sign-off (`git commit -s`), and first-time contributors sign the [CLA](CLA.md). See [CONTRIBUTING.md](CONTRIBUTING.md) for the full process.

## License

[Apache-2.0](LICENSE) © Daytona Platforms Inc.
