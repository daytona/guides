import os
import time

from daytona import CreateSandboxFromSnapshotParams, Daytona
from dotenv import load_dotenv
from openai import OpenAI
from openai.lib.computer import ComputerToolset

load_dotenv()

START_URL = "https://docs.python.org/3/"
TASK = "Click Tutorial once. Return the main heading on the page that opens."
MAX_STEPS = 5
REQUEST_TIMEOUT = 20


class DaytonaDriver:
    def __init__(self, computer, display):
        self.computer = computer
        self.display = display
        self.clicked = False

    def screenshot(self):
        image = self.computer.screenshot.take_full_screen(
            show_cursor=False,
            request_timeout=REQUEST_TIMEOUT,
        )
        if not image.screenshot:
            raise RuntimeError("Daytona returned no screenshot.")
        return {
            "type": "computer_screenshot",
            "image_url": f"data:image/png;base64,{image.screenshot}",
        }

    def click(self, action):
        # Limit the model to the single click required by this example.
        if self.clicked or action.button != "left" or action.keys:
            raise RuntimeError("Only one plain left click is allowed.")
        inside_x = 0 <= action.x < self.display.width
        inside_y = 0 <= action.y < self.display.height
        if not inside_x or not inside_y:
            raise RuntimeError("Click is outside the display.")
        self.clicked = True
        self.computer.mouse.click(
            action.x,
            action.y,
            button="left",
            request_timeout=REQUEST_TIMEOUT,
        )

    def unsupported(self, action):
        raise RuntimeError(f"Unsupported action: {action.type}")

    double_click = drag = keypress = move = unsupported
    scroll = type = wait = unsupported


# Gate actions before dispatch even though unsupported driver methods also raise.
def before_action(action):
    return action.type in ("screenshot", "click")


# This example stops rather than approving pending model safety checks.
def approve_safety_checks(call):
    return False


def main():
    consent = input("Allow screenshots and one click? [y/N] ")
    if consent.lower() != "y":
        return

    daytona = Daytona()
    sandbox = None
    toolset = None
    try:
        sandbox = daytona.create(
            CreateSandboxFromSnapshotParams(
                auto_stop_interval=20,
                auto_delete_interval=60,
            ),
            timeout=REQUEST_TIMEOUT,
        )
        sandbox.computer_use.start(request_timeout=REQUEST_TIMEOUT)

        deadline = time.monotonic() + 60
        while True:
            status = sandbox.computer_use.get_status(
                request_timeout=REQUEST_TIMEOUT
            ).status
            if status == "active":
                break
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Computer use did not become active in time "
                    f"(last status: {status})."
                )
            time.sleep(2)

        sandbox.process.exec(
            f"DISPLAY=:0 nohup chromium --no-sandbox --disable-dev-shm-usage "
            f"{START_URL} >/tmp/cu-browser.log 2>&1 </dev/null &",
            timeout=REQUEST_TIMEOUT,
        )
        time.sleep(10)

        displays = sandbox.computer_use.display.get_info(
            request_timeout=REQUEST_TIMEOUT
        ).displays or []
        active = [display for display in displays if display.is_active]
        if len(active) != 1 or active[0].x != 0 or active[0].y != 0:
            raise RuntimeError("Expected one active display at (0, 0).")
        if not active[0].width or not active[0].height:
            raise RuntimeError("Display dimensions are unavailable.")

        driver = DaytonaDriver(sandbox.computer_use, active[0])
        toolset = ComputerToolset(driver)
        request = {
            "model": os.environ["OPENAI_MODEL"],
            "store": False,
            "tools": [{"type": "computer"}],
            "tool_choice": "required",
            "input": TASK,
        }
        with OpenAI(timeout=30, max_retries=0) as client:
            response = toolset.run(
                client,
                request,
                max_steps=MAX_STEPS,
                before_action=before_action,
                approve_safety_checks=approve_safety_checks,
            )
        if not driver.clicked:
            raise RuntimeError("The model returned without clicking.")
        print(response.output_text)
    finally:
        try:
            if toolset is not None:
                toolset.close()
        finally:
            if sandbox is not None:
                sandbox.delete(wait=True)
                print(f"Deleted sandbox {sandbox.id}")


if __name__ == "__main__":
    main()
