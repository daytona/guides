# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""Run a Fireworks-powered coding agent inside a Daytona sandbox (BYOK).

The host never sends the Fireworks key into the sandbox. It stores the key as
a Daytona secret allowed only for api.fireworks.ai, mounts the secret's opaque
placeholder as an environment variable, and lets the sandbox's outbound proxy
substitute the real value on requests to Fireworks. Code inside the sandbox
can use the key but can never read it or exfiltrate it to another host.
"""

import os
import sys

from dotenv import load_dotenv

from daytona import (
    CreateSandboxFromSnapshotParams,
    CreateSecretParams,
    Daytona,
    DaytonaError,
    DaytonaForbiddenError,
    UpdateSecretParams,
)
from daytona_api_client.exceptions import ForbiddenException

SECRET_NAME = "fireworks-api-key"
FIREWORKS_HOSTS = ["api.fireworks.ai"]
DEFAULT_MODEL = "accounts/fireworks/models/kimi-k3"
AGENT_TIMEOUT_SECONDS = 600


def upsert_fireworks_secret(daytona: Daytona, value: str) -> None:
    """Create the host-scoped secret, or rotate its value if it already exists.

    Managing secrets requires the `manage:secrets` permission on your API key.
    Mounting an existing secret into a sandbox only requires `write:sandboxes`,
    so if your key can't manage secrets we continue and assume the secret was
    created in the dashboard.
    """
    try:
        existing = next(
            (secret for secret in daytona.secret.list().items if secret.name == SECRET_NAME),
            None,
        )
        if existing is None:
            daytona.secret.create(
                CreateSecretParams(
                    name=SECRET_NAME,
                    value=value,
                    description="Fireworks AI API key (BYOK), substituted only for api.fireworks.ai",
                    hosts=FIREWORKS_HOSTS,
                )
            )
            print(f"✓ Created secret '{SECRET_NAME}' allowed for {FIREWORKS_HOSTS}")
        else:
            daytona.secret.update(
                existing.id, UpdateSecretParams(value=value, hosts=FIREWORKS_HOSTS)
            )
            print(f"✓ Rotated secret '{SECRET_NAME}' (placeholder stays the same)")
    except (DaytonaForbiddenError, ForbiddenException):
        print(
            f"! Your API key lacks the 'manage:secrets' permission; skipping secret setup.\n"
            f"  Either grant it to the key, or create a secret named '{SECRET_NAME}'\n"
            f"  with host allowlist {FIREWORKS_HOSTS} in the dashboard:\n"
            f"  https://app.daytona.io/dashboard/secrets\n"
            f"  Continuing, assuming the secret already exists..."
        )


def main() -> None:
    # override=True makes .env authoritative over stale shell exports
    load_dotenv(override=True)

    fireworks_key = os.environ.get("FIREWORKS_API_KEY")
    if not fireworks_key:
        sys.exit("Set FIREWORKS_API_KEY (and DAYTONA_API_KEY) in your environment or .env")

    daytona = Daytona()
    upsert_fireworks_secret(daytona, fireworks_key)

    sandbox = None
    try:
        # Mount the secret: the sandbox env var is set to the placeholder,
        # never to the real key.
        sandbox = daytona.create(
            CreateSandboxFromSnapshotParams(
                language="python",
                secrets={"FIREWORKS_API_KEY": SECRET_NAME},
            )
        )
        print(f"✓ Sandbox {sandbox.id} created")

        # What the sandbox actually sees: an opaque placeholder.
        placeholder = sandbox.process.exec("printenv FIREWORKS_API_KEY")
        print(f"✓ Value inside the sandbox: {placeholder.result.strip()}")

        # BYOK sanity check. A 200 proves the proxy substituted the real key,
        # because Fireworks rejects the placeholder with a 401.
        check = sandbox.process.exec(
            'curl -s -o /dev/null -w "%{http_code}" '
            '-H "Authorization: Bearer $FIREWORKS_API_KEY" '
            "https://api.fireworks.ai/inference/v1/models"
        )
        print(f"✓ Fireworks auth check from sandbox: HTTP {check.result.strip()}")

        # Upload the task and the agent, then run the agent inside the sandbox.
        sandbox.fs.upload_file("tests.py", "tests.py")
        sandbox.fs.upload_file("agent.py", "agent.py")

        model = os.environ.get("FIREWORKS_MODEL", DEFAULT_MODEL)
        print(f"▶ Running agent with {model} ...")
        run = sandbox.process.exec(
            "python agent.py",
            env={"FIREWORKS_MODEL": model},
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        print(run.result)

        # Pull the trajectory: one JSONL row in the OpenAI messages format,
        # directly usable as a Fireworks supervised fine-tuning dataset.
        try:
            sandbox.fs.download_file("trajectory.jsonl", "trajectory.jsonl")
            print("✓ Saved trajectory.jsonl")
            print("  Upload it as a Fireworks dataset with:")
            print("  firectl dataset create my-agent-trajectories trajectory.jsonl")
        except DaytonaError:
            print("! No trajectory produced (agent crashed before writing one)")

        if run.exit_code != 0:
            sys.exit("Agent finished but tests did not pass; trajectory saved anyway.")

    finally:
        if sandbox is not None:
            try:
                daytona.delete(sandbox)
                print("✓ Sandbox deleted")
            except DaytonaError as error:
                print(f"! Could not delete sandbox {sandbox.id}: {error}")
                print(
                    "  Your API key may lack the 'delete:sandboxes' permission; "
                    "remove the sandbox in the dashboard instead."
                )


if __name__ == "__main__":
    main()
