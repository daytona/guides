# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Create a self-hosted Gemini Managed Agents environment.

Prints GEMINI_ENVIRONMENT_ID and GEMINI_ENVIRONMENT_KEY for your .env. The API
returns the environment key only once, at creation time.
"""

import argparse
import os
import sys
from typing import Any

import httpx

import sandbox_lib

ENVIRONMENTS_URL = "https://generativelanguage.googleapis.com/v1beta/environments"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a self-hosted Gemini Managed Agents environment.")
    parser.add_argument(
        "--snapshot",
        help="Daytona snapshot that provision_sandbox.py uses for this environment's sandboxes",
    )
    args = parser.parse_args()
    sandbox_lib.load_env()

    body: dict[str, Any] = {"mode": "self_hosted"}
    if args.snapshot:
        # custom_config is passed through, unchanged, to the provisioner of every interaction.
        body["custom_config"] = {"daytona": {"snapshot": args.snapshot}}

    # google-genai 3.1 has no self-hosted environment fields yet, so call the REST API directly.
    response = httpx.post(
        ENVIRONMENTS_URL,
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json=body,
        timeout=30,
    )
    if response.is_error:
        print(f"!! creating the environment failed ({response.status_code}): {response.text}", file=sys.stderr)
        return 1

    environment = response.json()
    print(f"created self-hosted environment {environment['id']}")
    print()
    print("Add these to .env. The environment key is shown only once:")
    print()
    print(f"GEMINI_ENVIRONMENT_ID={environment['id']}")
    print(f"GEMINI_ENVIRONMENT_KEY={environment['environment_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
