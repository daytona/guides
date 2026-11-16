# Kiro Coding Agent with Daytona

A coding agent powered by [AWS Kiro's CLI](https://kiro.dev/docs/cli/) running inside secure [Daytona sandboxes](https://www.daytona.io/), streaming its task output back to your terminal in real time.

## Features

- **Secure sandbox execution:** The Kiro CLI and any code it runs stay inside an isolated Daytona sandbox.
- **Works on any plan:** Logs in with Kiro's device flow (pick a provider, approve in your browser) so later turns run headless - works on the free tier, no API key required.
- **Streaming output:** Forwards the CLI's live stdout straight to your terminal as the agent works.
- **No permission prompts:** Runs each task with `--no-interactive --trust-all-tools` so it never blocks waiting for approval.
- **Multi-turn memory:** Turns after the first use `--resume`, so the conversation keeps context across prompts.

## Prerequisites

- Node.js 22.15 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- A [Kiro account](https://app.kiro.dev/) - any plan, including the free tier. You log in interactively the first time the sandbox starts (pick a provider, open the printed URL, approve the sign-in in your browser); no API key is required.

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and add your Daytona API key:

   ```bash
   DAYTONA_API_KEY=your_daytona_key
   ```

## Run

```bash
npm run start
```

Then type a prompt at the `User:` prompt and watch the agent stream its work. Press Ctrl+C to exit.

## What's happening

The script creates a Daytona sandbox and installs the CLI with `curl -fsSL https://cli.kiro.dev/install | bash`. The installer always drops the binary at `$HOME/.local/bin/kiro-cli`, but that directory is not always on the sandbox shell's `PATH`, and the installer's exit code is not a reliable success signal, so the script confirms the install a different way: it runs the binary by its full path with `"$HOME/.local/bin/kiro-cli" --version`. Running by full path skips the `PATH` lookup entirely, so the check works the same regardless of how any given sandbox sets `PATH`.

Every phase that talks to Kiro uses the same trick. Opening a PTY starts a shell in the sandbox. Rather than run Kiro as a child of that shell, the script tells the shell to `exec` Kiro, which makes Kiro take over the shell's process. This buys two things. First, the output you see is exactly what Kiro prints, with no shell prompt or echoed command around it, so it looks the same as running Kiro on your own machine. Second, because Kiro replaced the shell, the PTY closes the moment Kiro exits, which is how the script knows the command has finished. A short readiness marker is printed right before `exec`; the script hides everything up to that marker (the shell's echoed launch line) and streams every byte after it.

Two phases follow this pattern:

- **Login** (`kiro-cli login --use-device-flow`, interactive) bridges your local stdin into the sandbox PTY in raw mode so you can pick a provider and complete sign-in. Kiro prints a URL and a one-time code; you approve in your own browser while the sandbox-side CLI polls AWS until it succeeds. `kiro-cli whoami` is the source of truth for success.
- **Turns** (`kiro-cli chat --no-interactive --trust-all-tools "<prompt>"`, headless) stream Kiro's output back live and end when Kiro exits. No keyboard bridge. Every turn after the first adds `--resume`, which continues the most recent conversation from the working directory, so context carries across prompts.

Kiro persists both the login and the conversation inside the sandbox, so login is one-time and later turns remember earlier ones. When you exit, the sandbox and everything stored inside it are deleted automatically.

## Example Output

> **Note:** The real `kiro-cli chat` output is more verbose - it also prints the full contents of any files the agent writes (with line numbers and diff markers) and per-step tool-call metadata. The transcript below is trimmed to the agent's responses and the program output for readability.

```
$ npm run start
Creating sandbox...
Installing Kiro CLI...
Starting Kiro CLI...

Log in to Kiro to continue (any plan works, including the free tier).
Pick a provider, open the URL that appears below, and approve the sign-in in your browser.

? Select login method ›
❯ Use with Builder ID
  Use with Google
  Use with GitHub
  Use with Your Organization

Confirm the following code in the browser
Code: ABCD-EFGH
Open this URL: https://view.awsapps.com/start/#/device?user_code=ABCD-EFGH

Logging in... done

Agent ready. Press Ctrl+C at any time to exit.

User: Write donut.js that renders a 3D donut/torus as static ASCII art (roughly 80×24), with shading by surface normals against a fixed light direction. Use the characters .,-~:;=!*#$@ from darkest to brightest. Then run it with node donut.js and show the output.

I'll create the following file: /home/daytona/donut.js (using tool: write)
Creating: /home/daytona/donut.js
 - Completed in 0.0s

I will run the following command: node donut.js (using tool: shell)
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                   $$$$$$$$$$$                                  
                             $$$$$####*****####$$$$$                            
                          $$$$$##**!=*!!!!!*=!**##$$$$$                         
                       !$$$$$$#**!!===;;:;;===!!**#$$$$$$                       
                      *$$$$$$##*=;;:--,...,--:;;=*##$$$$$$*                     
                     *#$$$$$$##*!;-,.... ....,~;!*##$$$$$$#*                    
                    ;*##$$$$$$##*=:.         .:=*##$$$$$$##*;                   
                    ;*##$$$$$$$$##*!         !*##$$$$$$$###*;                   
                    :!*##$$$$$$$$$$$$#######$$$$$$$$$$$$##*!:                   
                    ~=!**###$$$$$$$$$$$$$$$$$$$$$$$$$###**!=:                   
                     :!!!**####$$$$$$$$$$$$$$$$$$$####**!=!;                    
                      ~==!!!***######$$$$$$$######***!!!==:                     
                       .:;=!!*!******************!!!!!=;:,                      
                         .~:;;=!=!***********!!==!=;;:~,                        
                            .,~::;;;;=======;;;;:~~-                            
                                  .,---------,.                                 
                                                                                
                                                                                
 - Completed in 0.32s

The shading uses .,-~:;=!*#$@ (dark→bright) based on the dot product of each surface normal with the light direction (0, 1, -1). The $ and # characters on the lit upper-left face the light most directly, while . and , appear on the darker lower portions.

User:
```

## References

- [Kiro CLI Documentation](https://kiro.dev/docs/cli/)
- [Daytona Documentation](https://www.daytona.io/docs/)
