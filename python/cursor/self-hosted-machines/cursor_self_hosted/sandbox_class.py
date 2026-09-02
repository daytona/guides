"""Normalize the Daytona sandbox classes supported by this integration."""

from __future__ import annotations

from daytona import SandboxClass


SUPPORTED_SANDBOX_CLASSES = (
    SandboxClass.CONTAINER,
    SandboxClass.LINUX_VM,
    SandboxClass.WINDOWS,
)


class UnsupportedSandboxClassError(ValueError):
    """Raised when a snapshot uses a sandbox class this integration cannot run."""


def parse_sandbox_class(value: object) -> SandboxClass:
    """Return one supported Daytona sandbox class."""

    raw_value = getattr(value, "value", value)
    try:
        sandbox_class = SandboxClass(str(raw_value))
    except ValueError as error:
        supported = ", ".join(item.value for item in SUPPORTED_SANDBOX_CLASSES)
        raise UnsupportedSandboxClassError(
            f"Unsupported Daytona sandbox class {raw_value!r}; choose {supported}"
        ) from error

    if sandbox_class not in SUPPORTED_SANDBOX_CLASSES:
        supported = ", ".join(item.value for item in SUPPORTED_SANDBOX_CLASSES)
        raise UnsupportedSandboxClassError(
            f"Unsupported Daytona sandbox class {raw_value!r}; choose {supported}"
        )
    return sandbox_class


def snapshot_sandbox_class(snapshot: object) -> SandboxClass:
    """Read and validate the sandbox class returned by Daytona."""

    return parse_sandbox_class(getattr(snapshot, "sandbox_class", None))
