# Devin Coding Agent with Daytona

A coding agent powered by [Cognition's Devin CLI](https://docs.devin.ai/cli), running inside secure, disposable [Daytona sandboxes](https://www.daytona.io/) and printing its results back to your terminal.

## Features

- **Secure sandbox execution:** The Devin CLI and any code it runs stay inside an isolated Daytona sandbox.
- **Works on any plan:** Logs in with Devin's manual-token flow (paste a code once) and dismisses Devin's one-time setup wizard so later turns run headless - works on the free tier, no API key required.
- **Output in your terminal:** Devin runs in the sandbox and its output is forwarded straight to your terminal. Headless `-p` turns print their result when the task finishes (Devin has no token-by-token stream format).
- **No permission prompts:** Runs each task with `--permission-mode dangerous` so it never blocks waiting for approval.
- **Multi-turn memory:** Turns after the first use `--continue`, so the conversation keeps context across prompts.

## Prerequisites

- Node.js 22.15 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- A [Devin account](https://app.devin.ai/) - any plan, including the free tier. You log in interactively the first time the sandbox starts (open the printed URL, sign in, paste the code back); no API key is required.

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

Then type a prompt at the `User:` prompt. Devin works on the task in the sandbox and prints its result back when it finishes. Press Ctrl+C to exit.

## What's happening

The script creates a Daytona sandbox and installs the CLI with `curl -fsSL https://cli.devin.ai/install.sh | bash`. That installer finishes by launching Devin's interactive onboarding wizard, which needs a terminal. The install runs without one, so the wizard bails out and the install command exits with an error code even though the `devin` binary itself installed fine. Because that exit code is unreliable, the script confirms the install a different way: it runs the binary directly with `"$HOME/.local/bin/devin" --version`. The installer always drops the binary at `$HOME/.local/bin/devin`, so a working `--version` proves the install succeeded. The script calls the binary by its full path rather than a bare `devin`. A bare name only works if its directory is on the shell's `PATH` (the list of directories the shell searches for commands), and whether `~/.local/bin` is on `PATH` varies between shell types and sandbox configurations. Running the binary by full path skips the `PATH` lookup entirely, so the install check works the same regardless of how any given sandbox sets `PATH`.

Every phase that talks to Devin uses the same trick. Opening a PTY starts a shell in the sandbox. Rather than run Devin as a child of that shell, the script tells the shell to `exec` Devin, which makes Devin take over the shell's process. This buys two things. First, the output you see is exactly what Devin prints, with no shell prompt or echoed command around it, so it looks the same as running Devin on your own machine. Second, because Devin replaced the shell, the PTY closes the moment Devin exits, which is how the script knows the command has finished.

Sending the launch command has one side effect: the sandbox shell echoes it back before `exec` runs, so the first bytes out of the PTY are the shell repeating the command rather than Devin's output. To keep the screen clean, the launch command prints a short marker right before `exec`; the script hides everything up to that marker and forwards every byte after it. That marker is the only reason any output is filtered at all.

Three phases follow this pattern:

- **Login** (`devin auth login --force-manual-token-flow`, interactive) bridges your local stdin into the sandbox PTY in raw mode so you can paste the code Devin asks for; `devin auth status` is the source of truth for success.
- **One-time setup** (`devin setup`, interactive) lets you dismiss Devin's first-run onboarding wizard ("Skip for now" if you do not need a Git provider). Devin records `setup_complete` on disk, so later turns are not interrupted.
- **Turns** (`devin -p "<prompt>" --permission-mode dangerous`, headless) run the task and print Devin's output back when it finishes. No keyboard bridge. Every turn after the first adds `--continue`, which resumes the most recent session in the working directory, so context carries across prompts.

When you exit, the sandbox and the credentials stored inside it are deleted automatically.

## Example Output

```
$ npm run start
Creating sandbox...
Installing Devin CLI...
Starting Devin CLI...

Log in to Devin to continue (any plan works, including the free tier).
Open the URL that appears below, sign in, and paste the code back here.


Visit https://app.devin.ai/auth/cli/continue?state=...&code_challenge=...&code_challenge_method=S256 to sign in, then copy the code and paste it below.

Code:
❭ Paste the code from the sign-in page
Enter submit  Esc cancel

Login successful! Credentials stored.

Finishing one-time Devin setup. Use the arrow keys and choose "Skip for now" if you do not need a Git provider.


Welcome to Devin CLI!
Logged in as you@example.com.

✓ Organization: My Team
You're all set. Run devin to get started.

Agent ready. Press Ctrl+C at any time to exit.

User: Write a Python module mydiff.py implementing Myers' diff algorithm to compute the line-level diff between two text strings, producing a minimal edit script. Add a CLI that takes two file paths and prints a git-style diff with - for removed lines, + for added lines, and a space for context. Create two sample files (old.txt and new.txt) holding a short Python function before and after a refactor. Run the diff CLI on them and show the output. Add a pytest suite covering empty inputs, identical inputs, full replacement, and a known small case with a known minimal edit script. Run the tests.
I've successfully implemented Myers' diff algorithm with all requested features. Here's a summary:

## Created Files

1. **mydiff.py** - Complete implementation including:
   - Myers' diff algorithm for computing minimal edit scripts
   - CLI with argparse for git-style diff output
   - Support for context lines (default 3, configurable with `-U` flag)
   - Edit class representing operations (delete, insert, equal)

2. **old.txt** - Sample Python function before refactoring

3. **new.txt** - Refactored version with simplified logic

4. **test_mydiff.py** - Comprehensive pytest suite with 11 tests covering:
   - Empty inputs
   - Identical inputs
   - Full replacement
   - Known small case with verified minimal edit script
   - Insert at beginning
   - Delete at end
   - Empty old/new files
   - Format diff with context
   - Minimal edit script property verification
   - Complex refactor scenario

## Sample Diff Output

Running `python mydiff.py old.txt new.txt` produces:

@@ -1,26 +1,11 @@
 def calculate_user_score(user_data):
-    if user_data is None:
+    if not user_data:
         return 0

-    base_score = 0
-    if user_data.get('is_active', False):
-        base_score = base_score + 10
-    else:
-        base_score = base_score + 5
+    score = 0
+    score += 15 if user_data.get('is_active') else 5
+    score += 20 if user_data.get('is_premium') else 0
+    score += 15 if user_data.get('login_count', 0) > 10 else 5
+    score += 10 if user_data.get('has_profile_pic') else 0

-    if user_data.get('is_premium', False):
-        base_score = base_score + 20
-    else:
-        base_score = base_score + 0
-
-    if user_data.get('login_count', 0) > 10:
-        base_score = base_score + 15
-    else:
-        base_score = base_score + 5
-
-    if user_data.get('has_profile_pic', False):
-        base_score = base_score + 10
-    else:
-        base_score = base_score + 0
-
-    return base_score
+    return score

## Test Results

All 11 tests passed successfully:
============================== 11 passed in 0.05s ==============================

The implementation correctly handles edge cases, produces minimal edit scripts, and displays git-style diffs with proper context.

User:
```

## References

- [Devin CLI Documentation](https://docs.devin.ai/cli)
- [Daytona Documentation](https://www.daytona.io/docs/)
