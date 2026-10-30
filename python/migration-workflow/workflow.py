"""A disposable v2 workflow; importing this module makes no cloud calls."""
import argparse
import json
import os
import sys

from daytona import Daytona
from daytona.v2 import LifecyclePolicyConfig

# Public API evidence: https://pypi.org/pypi/daytona/2.0.0a4/json
# Targets daytona 2.0.0a4. Requires v2 Linux access.
def run_workflow(daytona: Daytona, image: str):
    sandbox = daytona.v2.create(
        image, wait_seconds=60, create_timeout_seconds=300,
        lifecycle_policy=LifecyclePolicyConfig(timeout_seconds=600, on_timeout="delete"),
    )
    print(f"Created disposable sandbox {sandbox.id}", file=sys.stderr)
    try:
        # create's caller wait can expire before startup; wait uses seconds.
        sandbox.wait(until="started", timeout=300)
        content = "migration ok\n"
        sandbox.fs.write_text("/tmp/migration-input.txt", content)
        result = sandbox.process.run(
            argv=["python3", "-c",
                  'from pathlib import Path; p=Path("/tmp/migration-input.txt"); Path("/tmp/migration-output.txt").write_bytes(p.read_bytes())'],
            execution_timeout=30,
        )
        if result.reason != "exited" or result.exit_code != 0:
            raise RuntimeError(f"Command did not succeed: {result.reason}, exit={result.exit_code}")
        output = sandbox.fs.read_text("/tmp/migration-output.txt")
        if output != content:
            raise RuntimeError("File round-trip did not preserve the content")
        return {"output": output, "exit_code": result.exit_code}
    finally:
        # Only this newly created disposable sandbox belongs to the example.
        # Deletion is asynchronous; returning does not prove teardown completed.
        sandbox.delete()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Create a billable disposable sandbox")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to create a billable disposable sandbox.")
    image = os.environ.get("DAYTONA_IMAGE")
    if not image or not os.environ.get("DAYTONA_API_KEY"):
        parser.error("Export DAYTONA_API_KEY and DAYTONA_IMAGE (a registered image with python3).")
    daytona = Daytona()
    try:
        print(json.dumps(run_workflow(daytona, image)))
    finally:
        daytona.close()


if __name__ == "__main__":
    main()
