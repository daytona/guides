"""Let Claude draw on a canvas sketchpad running in a Daytona sandbox desktop.

The script creates a sandbox through `DaytonaComputer`, uploads the self-contained `paint.html`
sketchpad next to this file, opens it in a visible Chromium window on the sandbox's X display, and
hands the computer toolset to `client.beta.messages.tool_runner` with a fixed drawing task. The
model then works the GUI the way a person would: screenshots, mouse drags and clicks on the
palette. Every tool call it makes is printed as it happens.

Usage:

    python draw.py

It runs unattended: the `confirm` callable logs each action and approves it, which is only
reasonable because the desktop is a throwaway sandbox that is deleted when the run ends.

Needs `DAYTONA_API_KEY` and `ANTHROPIC_API_KEY`. `MODEL` picks the model.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import time
from pathlib import Path

from anthropic import Anthropic
from anthropic.tools.computer import BetaComputerConfirmContext
from daytona import Sandbox, SessionExecuteRequest
from daytona_toolsets import DaytonaComputer

HERE = Path(__file__).resolve().parent
PAINT_HTML = HERE / "paint.html"

# Paths inside the sandbox. The profile doubles as HOME for the scrubbed Chromium environment.
REMOTE_DIR = "/tmp/claude-draws"
REMOTE_HTML = f"{REMOTE_DIR}/paint.html"
PROFILE = "/tmp/claude-draws-profile"
CHROMIUM = "chromium"
SESSION_ID = "claude-draws-chromium"

# The desktop size the sandbox boots with, and the window Chromium opens at.
WIDTH, HEIGHT = 1280, 800

# The task is deliberately phrased against swatch LABELS, never positions: every swatch in
# paint.html shows its color name as visible text and carries the same name in `data-color`, and
# the palette scrolls horizontally, so a fixed coordinate would be meaningless. The drawing band is
# the part of the screen the floating docks leave free at 1280x800.
TASK = """The screen shows a sketchpad web app called Paint, already open and maximized. Draw in \
it with the mouse.

How the app works:

- A floating toolbar docks along the top of the window: brush sizes labeled fine, small, medium \
and bold, a caption box, a live readout, and a Clear button.
- A floating color palette docks along the bottom. It scrolls horizontally and only shows part of \
itself at a time. Every swatch shows its color name as text under the color chip.
- The canvas fills the whole window behind those two docks.

How to work:

1. Take a screenshot first and find the toolbar and the palette.
2. Choose colors by NAME, never by position. Scroll the palette sideways until the swatch whose \
label you want is visible, then click that swatch. The readout in the top toolbar then shows the \
selected color name, so you can confirm the click landed before you draw.
3. Draw only in the middle band of the screen, roughly 120 to 620 pixels from the top. The \
floating toolbar and palette sit outside that band and will swallow clicks meant for the canvas.
4. Drag the mouse to draw freehand. Hold shift and click to draw a straight line from the last \
point you drew to the point you click, so shift-clicks chain into a polyline.

What to draw, a simple sunset over water:

- A large round sun in the upper middle of the drawing band, with the swatch labeled "orange".
- A straight horizon line across the drawing band and a few wave strokes under it, with the \
swatch labeled "teal".
- Two or three small clouds above the horizon, with the swatch labeled "rose".
- Finally click the caption box in the top toolbar and type: sunset by claude

Take a screenshot when you are finished and describe what you drew."""


def confirm(context: BetaComputerConfirmContext) -> bool:
    """Approve every action, after logging it. The desktop is a throwaway sandbox, and the run has
    to finish without a human at the keyboard."""
    call = json.dumps(context.input.model_dump(exclude_none=True))  # escapes control chars
    print(f"[confirm] {context.member} {call}")
    return True


def upload_sketchpad(sandbox: Sandbox) -> None:
    """Put `paint.html` in the sandbox, next to the Chromium profile it will be opened from."""
    sandbox.process.exec(f"mkdir -p -m 700 {shlex.quote(REMOTE_DIR)} {shlex.quote(PROFILE)}")
    sandbox.fs.upload_file(PAINT_HTML.read_bytes(), REMOTE_HTML)


def launch_chromium(sandbox: Sandbox) -> None:
    """Open the uploaded sketchpad in a visible Chromium window on the sandbox's X display.

    Chromium is a foreground GUI process that never returns, so it is started through an async
    process session rather than `process.exec`, which would block until the browser exits. The
    debugging port listens on loopback inside the sandbox and is used here only as a readiness
    probe: once it answers, the window is up.
    """
    port = 20000 + secrets.randbelow(20000)
    is_root = sandbox.process.exec("id -u").result.strip() == "0"
    flags = [
        # Bound to loopback explicitly: this endpoint can drive the browser, and it is only ever
        # used from inside the sandbox as the readiness probe below.
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={PROFILE}",
        f"--window-size={WIDTH},{HEIGHT}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--password-store=basic",
        # Pages restored from the back-forward cache fire no load events to wait for.
        "--disable-features=BackForwardCache",
        # Chromium's sandbox cannot start as root; the Daytona sandbox is then the isolation.
        *(["--no-sandbox"] if is_root else []),
        # App mode: no tab strip or omnibox, so the whole window is the sketchpad.
        f"--app=file://{REMOTE_HTML}",
    ]
    # `env -i` scrubs the environment so the browser starts from a known state, which means the X
    # display has to be named explicitly. A Daytona sandbox desktop runs on `:0` — the same
    # invariant the toolset's own input helper falls back to — and the computer-use API reports
    # display geometry, not an X display string, so there is nothing to query. That server accepts
    # local connections from the sandbox user without a cookie, so no `XAUTHORITY` is carried
    # either. If any of that changed, Chromium would fail to connect and the probe below would
    # raise with a pointer to its log rather than hang.
    env = [f"HOME={PROFILE}", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "DISPLAY=:0"]
    command = (
        f"env -i {' '.join(shlex.quote(e) for e in env)} {shlex.quote(CHROMIUM)} "
        f"{' '.join(shlex.quote(f) for f in flags)} >{shlex.quote(PROFILE)}/chromium.log 2>&1"
    )
    sandbox.process.create_session(SESSION_ID)
    sandbox.process.execute_session_command(
        SESSION_ID, SessionExecuteRequest(command=command, run_async=True)
    )
    deadline = time.monotonic() + 60
    # Two bounds keep the wait short: `--max-time` stops curl hanging on a port that accepts but
    # never answers, and the exec timeout is whatever is left of the deadline — rounded up to a
    # whole second so the last fraction is still probed and the timeout is never zero — rather
    # than a fixed slice that could park here long after the deadline passed.
    probe = f"curl -sf --max-time 2 -o /dev/null http://127.0.0.1:{port}/json/version"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"Chromium did not start in the sandbox; see {PROFILE}/chromium.log there"
            )
        if sandbox.process.exec(probe, timeout=int(remaining) + 1).exit_code == 0:
            return
        time.sleep(0.5)


def main() -> None:
    if not PAINT_HTML.is_file():
        # The example runs from its checkout: `draw.py` uploads the `paint.html` sitting next to
        # it, and a non-editable `pip install .` copies the module to site-packages without the
        # HTML. Say so plainly here, before a sandbox is spent on a run that cannot work.
        raise SystemExit(
            f"{PAINT_HTML} is missing. Run this example from its checkout: clone the repo, "
            "`pip install -e .`, then `python draw.py` from this directory."
        )
    client = Anthropic()
    # DaytonaComputer creates the sandbox, starts its desktop, and deletes the sandbox on exit.
    with DaytonaComputer(confirm=confirm, resolution=(WIDTH, HEIGHT)) as computer:
        print(f"sandbox {computer.sandbox.id}, screen {computer.width}x{computer.height}")
        upload_sketchpad(computer.sandbox)
        launch_chromium(computer.sandbox)
        print(f"sketchpad open at file://{REMOTE_HTML}; handing the desktop to the model")
        runner = client.beta.messages.tool_runner(
            model=os.environ.get("MODEL", "claude-sonnet-5-5"),
            max_tokens=4096,
            max_iterations=120,
            tools=[computer],
            messages=[{"role": "user", "content": TASK}],
        )
        input_tokens = output_tokens = 0
        for message in runner:
            # Each assistant turn reports only its own usage, so the run total is the sum over the
            # loop. Cache and server-tool counters are separate fields and are not included here.
            input_tokens += message.usage.input_tokens
            output_tokens += message.usage.output_tokens
            for block in message.content:
                if block.type == "text":
                    print(f"[text] {block.text}")
                elif block.type == "tool_use":
                    print(f"[{block.name}] {json.dumps(block.input)}")
        print(f"tokens: {input_tokens} input, {output_tokens} output")


if __name__ == "__main__":
    main()
