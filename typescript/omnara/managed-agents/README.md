# Omnara Managed Agents on Daytona

## Overview

This example runs an [Omnara](https://www.omnara.com) agent on Daytona sandboxes in your own Daytona account. Omnara is an open-source managed agent platform: it runs the agent loop, keeps each agent's history in a durable event log, and handles tools, permissions, and streaming, with any model. You can use it at [app.omnara.com](https://app.omnara.com) or host it yourself.

Omnara connects to Daytona through a [machine pool](https://docs.omnara.com/machines/pools). You give Omnara your Daytona API key once, and it creates a sandbox for each agent that needs one and deletes the sandbox once it sits idle. The agent's commands run in the sandbox, and Omnara's own tools, like web search, run in Omnara.

The example launches an agent based on Omnara's [quickstart](https://docs.omnara.com/quickstart) on a Daytona sandbox. The agent reports the sandbox's operating system and free disk space, looks up the latest Node.js release on the web, and then installs it on the sandbox in a follow-up message.

## Features

- **Sandboxes in your Daytona account:** Agents run on your snapshots, in your region, under your Daytona limits, and each sandbox shows up in your Daytona dashboard.
- **One pool for many agents:** Omnara creates a sandbox when an agent launches and deletes it when the agent is archived or has been idle for 30 minutes.
- **Durable agents:** The agent's history lives in Omnara's event log, not in the sandbox, so a follow-up picks up where the last message left off.
- **Any model:** Change one line in `agent.yaml` to run the same agent on Claude, GPT, Gemini, or an open model.
- **No inbound ports:** The Omnara daemon in each sandbox connects outbound to Omnara.

## Prerequisites

- **Node.js:** Version 22.15 or higher is required.
- **Omnara account:** Sign up at [app.omnara.com](https://app.omnara.com). Every new organization comes with the `omnara-openrouter` model provider that `agent.yaml` uses. You need the admin or owner role in the organization.
- **Daytona account and API key:** Create a key at [app.daytona.io/dashboard/keys](https://app.daytona.io/dashboard/keys) with the `write:sandboxes` and `delete:sandboxes` permissions. Any Daytona tier works: the Omnara daemon in each sandbox downloads from `releases.omnara.com` and connects to `api.omnara.com`, and Daytona allows both on every tier.

## Environment Variables

To run this example, you need to set the following environment variables:

- `OMNARA_API_KEY`: Required to call the Omnara API. Use a personal access token (account menu, then **Personal tokens**) or an organization API key with the admin role (**API Tokens** page) from [app.omnara.com](https://app.omnara.com).
- `DAYTONA_API_KEY`: Required by `npm run setup`, which stores it as an Omnara secret so Omnara can create and delete the agent's sandboxes. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys). It's never passed into a sandbox.
- `OMNARA_ORG_ID`: Optional. The organization to use when your token can reach more than one.

Create a `.env` file in the project directory with these variables.

## Getting Started

### Setup and Run

1. Install dependencies:

   ```bash
   npm install
   ```

2. Create your `.env` file and fill in the two required keys:

   ```bash
   cp .env.example .env
   ```

3. Create the Omnara project, secret, and Daytona machine pool the example uses. You only need to do this once:

   ```bash
   npm run setup
   ```

4. Run the example:

   ```bash
   npm run start
   ```

### Clean Up

When you're done, delete everything the example created in Omnara, including the agents and their Daytona sandboxes:

```bash
npm run cleanup
```

## How It Works

**`npm run setup`** checks your Daytona API key with Daytona and finds the model in `agent.yaml`, then creates whatever doesn't exist yet: a project named `daytona-guide`, an org secret holding your Daytona key, a Daytona machine pool named `daytona-guide`, and grants that let the project use the pool and the model in `agent.yaml`. It leaves existing resources as they are, so running it again only adds what's missing.

**`npm run start`** runs the example:

1. It finds the project and pool that setup created, then compiles `agent.yaml` into an agent config and launches the agent in one API call. Omnara creates a Daytona sandbox from the pool right away, and the Omnara daemon inside it connects outbound to Omnara.
2. It waits for the sandbox to come online, then sends the agent its first message.
3. It streams the agent's timeline: messages, tool calls, and tool results. `web_search` and `web_fetch` run in Omnara, and `run_command` runs in the Daytona sandbox.
4. When the agent finishes its turn, it sends the follow-up to the same agent. It runs on the same sandbox with the full history, so the agent installs the version it just found. If a turn fails or you stop it from the dashboard, the script exits with an error. If nothing happens for 5 minutes, it stops the agent's turn and exits with an error.
5. It prints the model usage. The agent keeps running in Omnara, so you can keep talking to it from the dashboard link, and the pool deletes its sandbox after 30 idle minutes. The pool allows 5 sandboxes at a time, so a sixth run within 30 minutes fails with `machine pool capacity exceeded`. Wait for an idle sandbox to be deleted, or run `npm run cleanup` and `npm run setup`.

**`npm run cleanup`** deletes the project, which archives its agents, and the pool, which deletes their sandboxes. It then deletes the secret once Omnara has finished deleting the pool's machines, waiting up to 3 minutes. If it says Omnara is still deleting the pool's machines, run it again in a few minutes.

## Configuration

The agent lives in [`agent.yaml`](agent.yaml), and the Daytona pool settings and messages live in [`src/config.ts`](src/config.ts):

- **Pick a model:** Change `model.name` in `agent.yaml` to any model from `omnara-openrouter`, such as `openai/gpt-6.1-sol` or `anthropic/claude-sonnet-5.5`, then run `npm run setup` again to grant it to the project. To use your own model keys, add a [model provider](https://docs.omnara.com/organization/model-providers) in Omnara and set `model.provider_config` to its name.
- **Change the task:** Edit `instruction` in `agent.yaml` and the two messages in `src/config.ts`.
- **Change the sandbox:** Set `pool.snapshot`, `pool.target`, and the per-sandbox limits in `src/config.ts`, then run `npm run cleanup` and `npm run setup` to recreate the pool. A custom snapshot needs a writable home directory, a POSIX shell, `curl`, `base64`, and `sha256sum` or `shasum`. To prepare each new sandbox, for example by cloning a repository, add a `startup_script` to the machine source in `agent.yaml` under `machine_provider_options_overlay`.
- **Use a different Daytona key:** Run `npm run cleanup`, update `DAYTONA_API_KEY`, and run `npm run setup`.

## Example Output

`npm run setup`:

```
Project daytona-guide: created
Secret daytona-guide-api-key: created
Machine pool daytona-guide: created
Pool grant: created
Model grant for anthropic/claude-opus-5.5: created

Setup is done. Run `npm run start` to launch the agent.
```

`npm run start`, with the agent's longer answers trimmed (`…`):

````
Launched agent agt_bjbepvkua5emblnhrdw4poe6jq
Watch it live: https://app.omnara.com/projects/proj_agqvkhnyrr67bd6tlg6y3zt2ui/agents/agt_bjbepvkua5emblnhrdw4poe6jq
Waiting for the Daytona sandbox...
The agent's Daytona sandbox is ready after 5s

------------------------------------------------------------
User: Use your machine to report the operating system and the free disk space. Then find the latest stable Node.js release on the web and tell me the version.
  -> list_machines
  -> web_search  Node.js latest release 2026
     list_machines succeeded
     web_search succeeded
  -> run_command  cat /etc/os-release; uname -a; df -h
     run_command succeeded
  -> read_process
     read_process succeeded

Agent: Your machine runs **Debian 13 (trixie)** and has about **3.0 GB** of free disk space. The newest stable Node.js release is **v26.12.0**, and the newest LTS release is **v24.22.0**.
…

------------------------------------------------------------
User: Install that Node.js version on the machine and show me node --version.
  -> run_command  set -e; cd /tmp; V=v26.12.0; curl -fsSLO https://nodejs.org/dist/$V/node-$V-linux-x64.tar.xz; curl …
     run_command succeeded
  -> read_process
     read_process succeeded

Agent: The install worked, but `node` on the PATH still resolves to an older nvm-managed v25.9.0. Let me check the new binary and sort out the PATH.
  -> run_command  /usr/local/bin/node --version; echo "PATH=$PATH"; ls /usr/local/share/nvm/versions/node/ 2>/dev/nul…
     run_command succeeded
  -> run_command  export NVM_DIR=/usr/local/share/nvm; . "$NVM_DIR/nvm.sh"; export NVM_SYMLINK_CURRENT=true; nvm inst…
     run_command succeeded
  -> read_process
     read_process succeeded

Agent: Let me confirm in a fresh shell.
  -> run_command  node --version
     run_command succeeded

Agent: Node.js v26.12.0 is now installed, and running `node --version` in a fresh shell prints:

```
$ node --version
v26.12.0
```
…

------------------------------------------------------------
Model usage: 179,752 input and 2,982 output tokens ($0.1905)
The agent keeps running in Omnara, so you can keep talking to it from the link above. Its sandbox is deleted after it sits idle. Run `npm run cleanup` to remove everything this guide created.
````

## License

See the main project LICENSE file for details.

## References

- [Omnara documentation](https://docs.omnara.com)
- [Omnara quickstart](https://docs.omnara.com/quickstart)
- [Omnara machine pools](https://docs.omnara.com/machines/pools)
- [Daytona pools in Omnara](https://docs.omnara.com/machines/providers/daytona)
- [Omnara on GitHub](https://github.com/omnara-ai/omnara)
- [Daytona Documentation](https://www.daytona.io/docs)
