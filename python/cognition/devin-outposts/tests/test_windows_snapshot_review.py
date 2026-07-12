from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from devin_outposts import build_windows_snapshot as snapshot_builder


class NotFoundError(Exception):
    status_code = 404


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requested_urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested_urls.append(url)
        return self.response


class FakeProcess:
    def exec(self, command: str, timeout: int | None = None) -> SimpleNamespace:
        return SimpleNamespace(exit_code=0, result="")


class SequencedFs:
    def __init__(
        self,
        *,
        log: bytes | BaseException = b"",
        exit_reads: list[bytes | BaseException] | None = None,
    ) -> None:
        self.log = log
        self.exit_reads = list(exit_reads or [b"0"])

    def download_file(self, path: str) -> bytes:
        value: bytes | BaseException
        if path.endswith(".log"):
            value = self.log
        else:
            value = self.exit_reads.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class FakeProvisioningSandbox:
    def __init__(self, fs: SequencedFs) -> None:
        self.process = FakeProcess()
        self.fs = fs


class SnapshotIdentityTests(unittest.TestCase):
    def test_default_identity_includes_recipe_release_and_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provisioner = Path(directory, "provision.ps1")
            provisioner.write_bytes(b"recipe-v1")
            sha_a = "a" * 64
            sha_b = "b" * 64

            baseline = snapshot_builder._snapshot_name(
                provisioner,
                None,
                source_snapshot="windows-medium",
                devin_cli_version="1.2.3",
                devin_cli_sha256=sha_a,
            )
            different_source = snapshot_builder._snapshot_name(
                provisioner,
                None,
                source_snapshot="windows-large",
                devin_cli_version="1.2.3",
                devin_cli_sha256=sha_a,
            )
            different_version = snapshot_builder._snapshot_name(
                provisioner,
                None,
                source_snapshot="windows-medium",
                devin_cli_version="1.2.4",
                devin_cli_sha256=sha_a,
            )
            different_sha = snapshot_builder._snapshot_name(
                provisioner,
                None,
                source_snapshot="windows-medium",
                devin_cli_version="1.2.3",
                devin_cli_sha256=sha_b,
            )

        self.assertEqual(
            len({baseline, different_source, different_version, different_sha}), 4
        )

    def test_explicit_name_is_operator_selected_identity(self) -> None:
        missing_provisioner = Path("/path/that/does/not/exist/provision.ps1")

        name = snapshot_builder._snapshot_name(
            missing_provisioner, "  operator-selected  "
        )

        self.assertEqual(name, "operator-selected")

    def test_current_release_uses_manifest_version_and_windows_sha(self) -> None:
        sha256 = "ABCDEF12" * 8
        client: Any = FakeHttpClient(
            FakeResponse(
                {
                    "version": " 1.2.3 ",
                    "platforms": {
                        "x86_64-pc-windows": {
                            "url": "https://example.test/devin.zip",
                            "sha256": sha256,
                        }
                    },
                }
            )
        )

        version, resolved_sha = snapshot_builder._resolve_current_devin_cli(client)

        self.assertEqual(version, "1.2.3")
        self.assertEqual(resolved_sha, sha256.lower())
        self.assertEqual(client.requested_urls, [snapshot_builder.DEVIN_MANIFEST_URL])


class ProvisionerPollingTests(unittest.TestCase):
    def run_provisioner(self, fs: SequencedFs) -> Any:
        sandbox = FakeProvisioningSandbox(fs)
        with patch.object(snapshot_builder.time, "sleep", return_value=None):
            return snapshot_builder._run_provisioner(  # type: ignore[arg-type]
                sandbox,
                verify_only=False,
                timeout=30,
            )

    def test_missing_log_and_exit_marker_are_polled_until_marker_exists(self) -> None:
        fs = SequencedFs(
            log=FileNotFoundError("log not created yet"),
            exit_reads=[NotFoundError("marker not created yet"), b"0"],
        )

        result = self.run_provisioner(fs)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.result, "")

    def test_log_read_failure_is_not_suppressed(self) -> None:
        failure = PermissionError("log access denied")

        with self.assertRaises(PermissionError) as raised:
            self.run_provisioner(SequencedFs(log=failure))

        self.assertIs(raised.exception, failure)

    def test_exit_marker_api_failure_is_not_suppressed(self) -> None:
        failure = RuntimeError("filesystem service unavailable")

        with self.assertRaises(RuntimeError) as raised:
            self.run_provisioner(SequencedFs(exit_reads=[failure]))

        self.assertIs(raised.exception, failure)


class FakeVerifierFs:
    def upload_file(
        self,
        source: str,
        destination: str,
        timeout: int | None = None,
    ) -> None:
        return None


class FakeVerifier:
    id = "sandbox-123"
    name = "verifier-name"
    fs = FakeVerifierFs()


class FakeDaytona:
    def create(self, params: object, timeout: int | None = None) -> FakeVerifier:
        return FakeVerifier()


class SuccessOutputTests(unittest.TestCase):
    def args(self, *, create_serving_sandbox: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            env_file=snapshot_builder.DEFAULT_ENV_FILE,
            source_snapshot="windows-medium",
            name="operator-selected",
            build_timeout=30,
            sandbox_timeout=30,
            create_serving_sandbox=create_serving_sandbox,
        )

    def run_main(
        self,
        *,
        verification_exit_code: int,
        computer_use_ok: bool,
        cleanup_ok: bool,
        create_serving_sandbox: bool = False,
    ) -> tuple[int, str]:
        snapshot = SimpleNamespace(
            name="operator-selected",
            state=snapshot_builder.SnapshotState.ACTIVE,
        )
        output = io.StringIO()
        with (
            patch.object(
                snapshot_builder,
                "_parse_args",
                return_value=self.args(create_serving_sandbox=create_serving_sandbox),
            ),
            patch.object(snapshot_builder, "load_dotenv", return_value=False),
            patch.object(snapshot_builder, "Daytona", return_value=FakeDaytona()),
            patch.object(snapshot_builder, "_find_snapshot", return_value=snapshot),
            patch.object(
                snapshot_builder,
                "_run_provisioner",
                return_value=SimpleNamespace(
                    exit_code=verification_exit_code,
                    result="",
                ),
            ),
            patch.object(
                snapshot_builder,
                "_verify_computer_use",
                return_value=computer_use_ok,
            ),
            patch.object(snapshot_builder, "_delete_sandbox", return_value=cleanup_ok),
            patch.object(
                snapshot_builder,
                "_resolve_current_devin_cli",
                side_effect=AssertionError(
                    "explicit identity must not resolve the current release"
                ),
            ),
            redirect_stdout(output),
        ):
            exit_code = snapshot_builder.main()
        return exit_code, output.getvalue()

    def test_verification_failure_prints_no_success_or_retention_output(self) -> None:
        exit_code, output = self.run_main(
            verification_exit_code=1,
            computer_use_ok=True,
            cleanup_ok=True,
            create_serving_sandbox=True,
        )

        self.assertEqual(exit_code, snapshot_builder.EXIT_COMMAND)
        self.assertNotIn("Snapshot ready:", output)
        self.assertNotIn("Serving sandbox retained:", output)

    def test_cleanup_failure_prints_no_success_output(self) -> None:
        exit_code, output = self.run_main(
            verification_exit_code=0,
            computer_use_ok=True,
            cleanup_ok=False,
        )

        self.assertEqual(exit_code, snapshot_builder.EXIT_CLEANUP)
        self.assertNotIn("Snapshot ready:", output)

    def test_success_output_follows_successful_verification_and_cleanup(self) -> None:
        exit_code, output = self.run_main(
            verification_exit_code=0,
            computer_use_ok=True,
            cleanup_ok=True,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Snapshot ready: operator-selected", output)
