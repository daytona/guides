# Kimi Coding Agent with Daytona

A headless coding agent powered by [Moonshot AI's Kimi CLI](https://www.kimi.com/code/) running inside secure [Daytona sandboxes](https://www.daytona.io/), streaming its task output back to your terminal in real time.

## Features

- **Secure sandbox execution:** The Kimi CLI and any code it runs stay inside an isolated Daytona sandbox.
- **Fully headless:** Your Kimi API key is injected at sandbox creation, so there is no browser login or device flow to complete.
- **Streaming output:** Forwards the CLI's live output straight to your terminal as the agent works.
- **No permission prompts:** Runs each task with `--yolo` so it never blocks waiting for approval.
- **Multi-turn memory:** Turns after the first use `-C`, so the conversation keeps context across prompts.

## Prerequisites

- Node.js 18 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- A Kimi API key from the [Kimi API Platform](https://platform.kimi.ai/console/api-keys)

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and add your API keys:

   ```bash
   DAYTONA_API_KEY=your_daytona_key
   SANDBOX_KIMI_API_KEY=your_kimi_key
   ```

## Run

```bash
npm run start
```

Then type a prompt at the `User:` prompt and watch the agent stream its work. Press Ctrl+C to exit.

## What's happening

The script creates a Daytona sandbox with `KIMI_API_KEY`, `KIMI_BASE_URL`, and `KIMI_MODEL_NAME` injected at create time, so the CLI authenticates headlessly - no browser login or device flow. All three are needed: with no config file in the fresh sandbox, the CLI builds its model provider entirely from the environment, and it refuses to run ("LLM not set") if the base URL or model name is missing. The sample points at Moonshot's Open Platform endpoint (`https://api.moonshot.ai/v1`) with the `kimi-k3` model; change either in `src/index.ts` if you need a different endpoint or model (`GET https://api.moonshot.ai/v1/models` lists what your key can use). It then installs the CLI with `pip install kimi-cli` and confirms the install by running the binary by its full path with `"$HOME/.local/bin/kimi" --version`. pip's user install always drops the entrypoint at `$HOME/.local/bin/kimi`, but that directory is not always on the sandbox shell's `PATH`, and running by full path skips the `PATH` lookup entirely, so the check works the same regardless of how any given sandbox sets `PATH`.

Each turn opens a PTY in the sandbox. Rather than run Kimi as a child of that shell, the script tells the shell to `exec` Kimi, which makes Kimi take over the shell's process. This buys two things. First, the output you see is exactly what Kimi prints, with no shell prompt or echoed command around it, so it looks the same as running Kimi on your own machine. Second, because Kimi replaced the shell, the PTY closes the moment Kimi exits, which is how the script knows the turn has finished. A short readiness marker is printed right before `exec`; the script hides everything up to that marker (the shell's echoed launch line) and streams every byte after it.

Every prompt runs `kimi -p "<prompt>" --yolo`: `-p` processes a single prompt and exits, and `--yolo` auto-approves tool calls so the run never blocks on a confirmation. Every turn after the first adds `-C`, which continues the most recent session from the working directory, so context carries across prompts even though each turn is a separate CLI invocation. Kimi persists those sessions inside the sandbox; when you exit, the sandbox and everything stored inside it are deleted automatically.

## Example Output

> **Note:** The real output is more verbose - the CLI also prints the full contents of the files the agent writes and every verification command it runs while it works. The transcript below is trimmed to the tool summaries, the rendered QR codes, and the agent's responses for readability. Both codes scan: point your phone at them (most scanners handle the light-on-dark inversion of terminal themes automatically).

```
$ npm run start
Creating sandbox...
Installing Kimi CLI...
Starting Kimi CLI...

Agent ready. Press Ctrl+C at any time to exit.

User: Write a Python script qr.py from scratch - standard library only, absolutely no QR or imaging libraries - that encodes the URL https://daytona.io as a real QR code (byte mode, error correction level L, proper data masking with penalty scoring), and prints it to the terminal using '██' (two full blocks) for dark modules and two spaces for light modules, with a 4-module quiet zone. Run it and include the rendered QR code verbatim in your final response, plus one line stating which QR version and mask pattern you used.

• Used WriteFile (qr.py)
  [tool calls trimmed: the agent wrote the encoder, re-derived the Reed-Solomon generator
   polynomial from first principles, fixed a version-capacity bug and a format-info placement
   bug it found itself, and round-tripped all 8 mask patterns before presenting the result]
• Used Shell (cd /home/daytona && python3 qr.py)

  Version/mask line: QR Version 2 (25×25), EC level L, mask pattern 3 (penalty score 450).

  Rendered QR code (verbatim output of python3 qr.py):


          ██████████████  ████      ██    ██  ██████████████
          ██          ██            ██    ██  ██          ██
          ██  ██████  ██  ██    ████████  ██  ██  ██████  ██
          ██  ██████  ██  ████  ██            ██  ██████  ██
          ██  ██████  ██  ████████  ████████  ██  ██████  ██
          ██          ██    ██    ██  ██  ██  ██          ██
          ██████████████  ██  ██  ██  ██  ██  ██████████████
                            ██  ██  ████████
          ████████    ██  ██        ██████████    ██████  ██
            ██████████  ██  ██                  ██      ██
          ██    ████  ██              ██  ████    ██
          ██      ████  ██      ████████  ████      ████
            ██  ██  ██████████  ██      ██  ████  ██  ██████
                  ██    ██    ████  ██  ████  ██████      ██
            ████    ████████  ██  ██  ██  ██  ██  ██  ████
          ██    ██████    ██████  ████    ██████████      ██
              ██████  ████████  ██      ████████████████████
                          ██  ██  ████    ██      ██  ██  ██
          ██████████████    ████████      ██  ██  ██  ██████
          ██          ██    ████  ██    ████      ██    ████
          ██  ██████  ██      ████████    ████████████
          ██  ██████  ██  ████    ██████  ██████  ██████████
          ██  ██████  ██  ████  ██████  ████  ██  ██  ████
          ██          ██  ██  ██            ██    ██  ██
          ██████████████  ██  ██  ██  ██      ██████████████


User: Now use the same generator to also encode https://kimi.com/code and include both rendered QR codes verbatim in your final response, each with a text label line above it

• Used StrReplaceFile (qr.py)
• Used Shell (cd /home/daytona && python3 qr.py)

• Both QR codes fully verified: bitstream content, Reed-Solomon divisibility, format BCH, and complete matrix round-trips for all 8 masks each. Here is the verbatim output of python3 qr.py:

  https://daytona.io
  Version 2 (25x25), EC level L, mask pattern 3, penalty score 450

  [same https://daytona.io code as shown above]

  https://kimi.com/code
  Version 2 (25x25), EC level L, mask pattern 2, penalty score 511


          ██████████████      ██  ██      ██  ██████████████
          ██          ██  ██  ██    ██  ████  ██          ██
          ██  ██████  ██          ██  ██  ██  ██  ██████  ██
          ██  ██████  ██  ██████  ██████      ██  ██████  ██
          ██  ██████  ██    ██      ██        ██  ██████  ██
          ██          ██  ████  ████████████  ██          ██
          ██████████████  ██  ██  ██  ██  ██  ██████████████
                            ██████    ██████
          ██████████  ████████  ██  ████    ██  ██  ██  ██
            ██  ██        ██  ██  ██      ██    ██      ██
          ████  ██  ██████    ██      ██████    ██████  ████
            ████          ██      ██      ██████  ██      ██
              ██████  ██    ████  ██████    ████  ██  ██████
          ██    ██  ██  ██████            ██    ██  ██  ██
          ██  ██████████      ██████  ████████  ██████  ████
          ██  ████  ██      ██  ██    ██    ████████      ██
          ██  ████  ████        ██      ████████████  ██
                          ██████  ████  ████      ████
          ██████████████  ████      ████  ██  ██  ██  ██████
          ██          ██          ████    ██      ████  ████
          ██  ██████  ██  ██████  ██  ██████████████  ██████
          ██  ██████  ██  ████          ████████  ██████████
          ██  ██████  ██  ██    ████      ██        ████  ██
          ██          ██  ████  ██    ██████    ██████    ██
          ██████████████  ██    ██      ██  ████████████████

  Summary: Both URLs exceed Version 1-L's 152-bit capacity, so both use QR Version 2 (25×25), EC level L — https://daytona.io with mask pattern 3 (penalty 450) and https://kimi.com/code with mask patt
  ern 2 (penalty 511), each selected by the lowest ISO/IEC 18004 penalty score.

User:
```

## References

- [Kimi Code](https://www.kimi.com/code/)
- [Kimi CLI Documentation](https://moonshotai.github.io/kimi-cli/en/)
- [Daytona Documentation](https://www.daytona.io/docs/)
