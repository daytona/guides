"""Test a web app running in a Daytona sandbox with a Notte cloud browser.

The sandbox serves a small to-do app on a signed preview URL. A Notte cloud
browser then opens that URL twice: once with Playwright over CDP through the
Notte SDK, and once with Notte CLI commands. The browser runs on Notte, so the
sandbox never installs or launches Chromium, and it needs no internet access
beyond Daytona's default policy.
"""

import json
import subprocess
from pathlib import Path

from daytona import CreateSandboxFromSnapshotParams, Daytona, SessionExecuteRequest
from dotenv import load_dotenv
from notte_sdk import NotteClient

load_dotenv()

PORT = 3000
APP_DIR = "/home/daytona/app"
OUTPUT_DIR = Path(__file__).parent / "screenshots"
NEW_TODO = "Ship the Daytona guide"

# Preview URLs show a warning page to browsers on first load; this header skips it.
PREVIEW_HEADERS = {"X-Daytona-Skip-Preview-Warning": "true"}

# A small to-do app, standing in for whatever your agent builds in the sandbox.
APP_HTML = """<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Sandbox To-dos</title></head>
  <body style="font-family: sans-serif; max-width: 480px; margin: 40px auto">
    <h1>Sandbox To-dos</h1>
    <form id="add">
      <input id="title" name="title" placeholder="New to-do" aria-label="New to-do">
      <button type="submit">Add</button>
    </form>
    <ul id="todos">
      <li>Write the app</li>
      <li>Start the server</li>
    </ul>
    <p id="count">2 to-dos</p>
    <script>
      document.getElementById("add").addEventListener("submit", (event) => {
        event.preventDefault();
        const input = document.getElementById("title");
        if (!input.value.trim()) return;
        const item = document.createElement("li");
        item.textContent = input.value.trim();
        document.getElementById("todos").appendChild(item);
        const count = document.querySelectorAll("#todos li").length;
        document.getElementById("count").textContent = `${count} to-dos`;
        input.value = "";
      });
    </script>
  </body>
</html>
"""


def start_app(sandbox) -> str:
    """Serve the app from the sandbox and return a signed preview URL for it."""
    sandbox.fs.upload_file(APP_HTML.encode(), f"{APP_DIR}/index.html")
    sandbox.process.create_session("app")
    sandbox.process.execute_session_command(
        "app",
        SessionExecuteRequest(
            command=f"cd {APP_DIR} && python3 -m http.server {PORT} --bind 0.0.0.0",
            run_async=True,
        ),
    )
    # Wait until the server accepts connections before handing the URL to the browser.
    ready = sandbox.process.exec(
        f"for i in $(seq 1 50); do curl -sf http://localhost:{PORT} > /dev/null && exit 0; "
        "sleep 0.2; done; exit 1"
    )
    if ready.exit_code != 0:
        raise RuntimeError("the app did not start")
    # A signed URL carries its token, so the browser needs no auth header.
    return sandbox.create_signed_preview_url(PORT, expires_in_seconds=3600).url


def check_with_playwright(notte: NotteClient, url: str) -> None:
    """Read the app with Playwright over CDP and screenshot it."""
    with notte.Session(extra_http_headers=PREVIEW_HEADERS) as session:
        print(f"Watch the browser live: {session.response.viewer_url}")
        # session.page is a Playwright page connected to the Notte browser over CDP.
        page = session.page
        page.goto(url, wait_until="domcontentloaded")
        todos = page.locator("#todos li").all_inner_texts()
        print(f"Playwright saw '{page.title()}' with to-dos: {todos}")
        OUTPUT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=OUTPUT_DIR / "app.png")
        print(f"Screenshot saved to {OUTPUT_DIR / 'app.png'}")


def notte_cli(*args: str) -> str:
    """Run one Notte CLI command and return its output."""
    result = subprocess.run(
        ["notte", *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def check_with_notte_cli(url: str) -> None:
    """Add a to-do and scrape the page with Notte CLI commands."""
    session = json.loads(
        notte_cli(
            "sessions",
            "start",
            "--extra-http-headers",
            json.dumps(PREVIEW_HEADERS),
            "-o",
            "json",
        )
    )
    print(f"Notte CLI started session {session['session_id']}")
    try:
        for args in (
            ("page", "goto", url),
            ("page", "fill", "#title", NEW_TODO),
            ("page", "click", "button[type=submit]"),
            ("page", "scrape", "--only-main-content"),
        ):
            print(f"$ notte {' '.join(args)}")
            print(notte_cli(*args))
    finally:
        notte_cli("sessions", "stop", "--yes")


def main() -> None:
    notte = NotteClient()
    daytona = Daytona()
    sandbox = daytona.create(CreateSandboxFromSnapshotParams(snapshot="daytona-small"))
    print(f"Created sandbox {sandbox.id}")

    try:
        url = start_app(sandbox)
        print(f"App is live at a signed preview URL on port {PORT}")
        check_with_playwright(notte, url)
        check_with_notte_cli(url)
    finally:
        daytona.delete(sandbox)
        print("Sandbox deleted")


if __name__ == "__main__":
    main()
