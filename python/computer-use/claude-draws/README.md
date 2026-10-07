# Claude Draws on Daytona

This example opens a canvas sketchpad in a Chromium window on a Daytona sandbox desktop and lets Claude draw in it with the mouse, through the Anthropic SDK's computer toolset.

## What you will build

- A sandbox desktop at 1280x800, created and deleted by `DaytonaComputer` from the [`daytona-toolsets`](https://pypi.org/project/daytona-toolsets/) package.
- A self-contained HTML sketchpad, `paint.html`, uploaded into the sandbox and opened in a visible Chromium window with no tab strip or omnibox.
- A drawing loop where `client.beta.messages.tool_runner` hands the computer toolset to the model, which takes screenshots, scrolls the color palette, picks swatches by name, and drags the mouse to draw.
- An unattended `confirm` callable that logs every action the model takes and approves it, because the desktop is a throwaway sandbox.

## Requirements

- Python 3.10 or higher on your machine.
- A Daytona account and API key.
- An Anthropic API key.

## Setup

```bash
git clone https://github.com/daytona/guides.git
cd guides/python/computer-use/claude-draws
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
cp .env.example .env  # macOS/Linux
# Windows PowerShell: Copy-Item .env.example .env
# edit .env with your Daytona and Anthropic API keys
```

`.env` is a shell file: `source .env` before running, or export the variables yourself.

Environment variables:

- `DAYTONA_API_KEY`: required. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- `ANTHROPIC_API_KEY`: required, for the model loop.
- `MODEL`: optional, the model the drawing loop uses. Defaults to `claude-sonnet-5-5`.

## Workflow

1. Source your keys and run the script:

   ```bash
   source .env
   python draw.py
   ```

2. Watch the run in your terminal. Each line is one step of the loop:

   ```
   sandbox 7f3c…, screen 1280x800
   sketchpad open at file:///tmp/claude-draws/paint.html; handing the desktop to the model
   [confirm] screenshot {}
   [screenshot] {}
   [text] I can see the sketchpad. The palette along the bottom…
   [confirm] scroll {"coordinate": [640, 720], "scroll_direction": "right", "scroll_amount": 3}
   ```

3. The last line totals what the drawing loop cost, summed over every assistant turn:

   ```
   tokens: 412905 input, 6124 output
   ```

   Screenshots dominate the input count: the model takes one after most actions, and each is billed as an image. Cache and server-tool counters are reported separately by the API and are not folded into these two numbers.

`draw.py` creates the sandbox, starts its desktop, uploads `paint.html`, and launches Chromium through an async Daytona process session — a foreground GUI process never returns, so `process.exec` would block until the browser exits. It waits for Chromium's loopback debugging port to answer before handing the desktop to the model, then prints the model's text and tool calls until the task finishes. The sandbox is deleted when the run ends.

The task prompt is fixed, in `TASK` at the top of `draw.py`. It targets colors by their visible label (`orange`, `teal`, `rose`), never by position, because the palette scrolls horizontally and swatch coordinates are not stable. It also keeps the model inside the drawing band, roughly 120 to 620 pixels from the top, where the floating docks do not intercept clicks. Edit `TASK` to draw something else, and keep both of those constraints.

Model-driven GUI runs are not deterministic: the same prompt will not produce the same picture twice, and the model can misread the screen or miss a swatch. Treat the result as a demo of the loop, not as a reproducible render.

## Files

- `draw.py`: creates the sandbox, uploads and opens the sketchpad, and runs the model's drawing loop.
- `paint.html`: the self-contained sketchpad — canvas, brush sizes, a 38-color palette, and a caption box, with no external assets. It also exposes a small read-only `window.paint` inspection surface (pixel probes, the selected color, a log of the strokes drawn) so a run can be checked from the devtools console or a browser test instead of by eye.
- `.env.example`: environment variable template.
