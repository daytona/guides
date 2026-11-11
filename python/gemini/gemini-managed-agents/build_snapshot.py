# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Build the worker snapshot from the Dockerfile.

Names the snapshot with sandbox_lib.snapshot_name() so the worker scripts and
this builder cannot drift, and skips the build if that snapshot already
exists. Streams the build logs.
"""

from daytona import CreateSnapshotParams, Daytona, DaytonaNotFoundError, Image, Resources

import sandbox_lib

RESOURCES = Resources(cpu=2, memory=4, disk=10)


def main() -> int:
    sandbox_lib.load_env()
    name = sandbox_lib.snapshot_name()

    daytona = Daytona()
    try:
        existing = daytona.snapshot.get(name)
        print(f"snapshot {name} already exists (state {existing.state}); skipping build")
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
