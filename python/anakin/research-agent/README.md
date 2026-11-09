# Research Agent (Anakin + Daytona)

## Overview

This guide builds a research agent that answers questions from the live web and shows its working. [Anakin](https://anakin.io) searches and scrapes the web, and a Daytona sandbox runs the Python the agent writes to analyze what it found. The result is a cited Markdown report with charts.

Scraped pages are untrusted, and they influence the code the model writes. So the code runs in a sandbox that holds no API keys and has no outbound network, while the agent loop and the keys stay on your machine.

## Features

- **Live web data:** Anakin Search finds sources and the Anakin URL Scraper turns them into Markdown, with an optional real browser for JavaScript-heavy pages
- **Isolated analysis:** model-written Python runs in a Daytona sandbox, not on your machine
- **No keys in the sandbox:** the agent loop calls Anakin and the LLM from your machine, and passes the sandbox only the scraped text
- **No outbound network:** the sandbox is created with `network_block_all=True`
- **Small context:** the model sees a short preview of each page and writes code to read the full text from files
- **Prompt caching:** the conversation history is cached on providers that support it, since every turn resends it
- **Any LLM provider:** the agent uses [LiteLLM](https://docs.litellm.ai/docs/providers), so you can switch models with one environment variable

## Requirements

- **Python:** 3.10 to 3.14 (tested on 3.12)

## Environment Variables

- `DAYTONA_API_KEY`: Required for Daytona sandbox access. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- `ANAKIN_API_KEY`: Required for Anakin Search and scraping. Get it from [Anakin](https://anakin.io/signup)
- `ANTHROPIC_API_KEY`: Required for the default model. Get it from [Anthropic Console](https://console.anthropic.com)
- `RESEARCH_MODEL`: Optional. Any LiteLLM model that supports tool calling, such as `openai/<model>`. Set that provider's API key instead of `ANTHROPIC_API_KEY`
- `RESEARCH_MAX_TURNS`: Optional. The most model calls per run. Defaults to 20

## Getting Started

1. Create and activate a virtual environment:

```bash
python3 -m venv venv  # On Windows: python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -e .
```

3. Set your API keys:

```bash
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
# edit .env with your API keys
```

4. Run the agent with the default question, or ask your own:

```bash
python research_agent.py
python research_agent.py "Compare the free tiers of the top 3 serverless Postgres providers"
```

Each run saves its report and charts in a new timestamped folder under `output/`. In our test, the default question took about 3.5 minutes and 15 turns, using 6 searches and 18 scraped pages. LiteLLM estimated the LLM cost at $0.40, and the script prints this estimate at the end of each run. Runs vary, so set `RESEARCH_MAX_TURNS` lower to cap the cost.

## How It Works

1. **Sandbox:** the script creates a Python sandbox with no outbound network, then creates the `sources` and `output` folders.
2. **Search:** the model calls `web_search`, which runs on your machine with Anakin Search and returns titles, URLs and snippets.
3. **Scrape:** the model calls `scrape_pages`, which uses Anakin's batch scraper on your machine. Each page's full Markdown is uploaded to the sandbox, and the model gets back the file path and a preview.
4. **Analyze:** the model calls `run_python` to search the files, extract figures and build charts. The output goes back to the model, including any errors, so it can correct its code.
5. **Report:** when the model replies without a tool call, the script saves its report and downloads everything in the sandbox's `output` folder.
6. **Cleanup:** the sandbox is deleted, even if the run fails. It's also created as ephemeral, so if the script is killed, the sandbox deletes itself once it auto-stops.

## Security Notes

Isolation limits what model-written code can do, but it doesn't stop prompt injection. A malicious page could still mislead the model and skew the report, so check the cited sources before relying on a result.

## Learn More

- [Daytona network limits](https://www.daytona.io/docs/en/network-limits)
- [Daytona Python SDK](https://www.daytona.io/docs/en/python-sdk)
- [Anakin API reference](https://anakin.io/docs/api-reference)
- [Anakin Python SDK](https://anakin.io/docs/sdks)
