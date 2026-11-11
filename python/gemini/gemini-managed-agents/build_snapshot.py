# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Build the worker snapshot from the Dockerfile.

Names the snapshot with sandbox_lib.snapshot_name() so the worker scripts and
this builder cannot drift, and skips the build if that snapshot already
exists and is active. Streams the build logs.
"""

import sys

from daytona import CreateSnapshotParams, Daytona, DaytonaNotFoundError, Image, Resources

import sandbox_lib

RESOURCES = Resources(cpu=2, memory=4, disk=10)


def main() -> int:
    sandbox_lib.load_env()
    name = sandbox_lib.snapshot_name()

    daytona = Daytona()
    try:
        existing = daytona.snapshot.get(name)
        if existing.state != "active":
            # For example a failed or unfinished build. Sandboxes can't be created from it.
            print(
                f"!! snapshot {name} exists but is {existing.state.value}; wait for it to finish, or delete it and rerun",
                file=sys.stderr,
            )
            return 1
        print(f"snapshot {name} already exists; skipping build")
        return 0
    except DaytonaNotFoundError:
        pass

    print(f"building snapshot {name} from {sandbox_lib.DOCKERFILE}...")
    snapshot = daytona.snapshot.create(
        CreateSnapshotParams(
            name=name,
            image=Image.from_dockerfile(str(sandbox_lib.DOCKERFILE)),
            resources=RESOURCES,
        ),
        on_logs=lambda chunk: print(chunk, end="", flush=True),
    )
    print(f"\n\ncreated snapshot {snapshot.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
